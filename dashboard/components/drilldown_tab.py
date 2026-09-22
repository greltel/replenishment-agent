"""
Drill-down tab — per-material analysis ("why does the agent propose this?").

For a chosen material:
  • Master data summary + the agent's reasoning (forecast, net requirement,
    lot-sizing policy, rules that fired)
  • Stock projection chart over the planning horizon (projected on-hand,
    safety stock line, planned receipts, exposure inside the lead time)
  • Full MRP grid
  • Consumption history chart
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import config
from src.data_layer.repository import Repository
from src.mrp.engine import MRPEngine
from src.mrp.lot_sizing import poq_period
from src.utils.forecasting import forecast, annual_demand
from dashboard import theme
from dashboard.theme import fmt_int, fmt_num, fmt_eur, fmt_date, section, plotly, badge


@st.cache_data(ttl=300)
def _material_choices() -> list[tuple[str, str]]:
    """Return list of (material_id, description) tuples."""
    repo = Repository()
    df = pd.read_sql(
        "SELECT material_id, COALESCE(description, '') AS description "
        "FROM materials ORDER BY material_id",
        repo.engine,
    )
    repo.close()
    return list(zip(df["material_id"], df["description"]))


def _compute_mrp_for_material(material_id: str, as_of: date, horizon: int = 60,
                              method: str = "moving_average") -> tuple[pd.DataFrame, dict]:
    """Run forecast + MRP on demand for a single material (same inputs as the agent)."""
    repo = Repository()
    material = repo.get_material(material_id)
    if material is None:
        repo.close()
        return pd.DataFrame(), {}

    current_stock = repo.get_current_stock(material_id, as_of=as_of)
    open_orders = repo.get_open_pos(material_id)
    history = repo.get_consumption_history(material_id, days=365, as_of=as_of)

    demand = forecast(history, horizon_days=horizon, method=method, as_of=as_of)
    annual = annual_demand(history, as_of=as_of)

    mrp = MRPEngine(
        horizon_days=horizon,
        ordering_cost=config.default_ordering_cost,
        holding_rate=config.default_holding_rate,
    )
    df = mrp.calculate(
        material=material,
        current_stock=current_stock,
        open_orders=open_orders,
        demand=demand,
        annual_demand_value=annual,
        as_of=as_of,
    )

    last_mv = max((m.posting_date for m in history), default=None)
    avg_daily = sum(demand) / len(demand) if demand else 0.0
    master = {
        "material_id":   material.material_id,
        "description":   material.description or "",
        "abc_class":     material.abc_class,
        "material_type": material.material_type,
        "uom":           material.uom,
        "lot_sizing":    (material.lot_sizing or "LFL").upper(),
        "lead_time":     int(material.lead_time_days or 0),
        "safety_stock":  float(material.safety_stock or 0),
        "reorder_point": float(material.reorder_point or 0),
        "moq":           float(material.moq or 0),
        "fixed_lot":     float(material.fixed_lot_size or 0),
        "standard_cost": float(material.standard_cost or 0),
        "current_stock": current_stock,
        "open_pos":      [(po.expected_date, float(po.quantity)) for po in open_orders],
        "forecast_daily": avg_daily,
        "annual_demand": annual,
        "n_history":     len(history),
        "last_movement": last_mv,
        "poq_days":      poq_period(annual, config.default_ordering_cost,
                                    config.default_holding_rate,
                                    material.standard_cost or 1.0),
    }

    repo.close()
    return df, master


def _consumption_history_df(material_id: str, as_of: date) -> pd.DataFrame:
    repo = Repository()
    movements = repo.get_consumption_history(material_id, days=365, as_of=as_of)
    repo.close()
    if not movements:
        return pd.DataFrame()
    df = pd.DataFrame([
        {"date": m.posting_date, "quantity": abs(m.quantity)}
        for m in movements
    ])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _reasoning(master: dict, mrp_df: pd.DataFrame, proposals: pd.DataFrame) -> None:
    """Explain the agent's decision for this material in plain words."""
    stock = master["current_stock"]
    ss = master["safety_stock"]
    fc = master["forecast_daily"]
    lt = master["lead_time"]
    cover_days = stock / fc if fc > 0 else None
    open_qty = sum(q for _, q in master["open_pos"])
    orders = mrp_df[mrp_df["planned_receipt"] > 0]

    # Status badge
    if stock < 0.5 * ss:
        status = badge("ΚΡΙΣΙΜΟ — απόθεμα < 50% του safety stock", "critical")
    elif stock < ss:
        status = badge("Κάτω από το safety stock", "warning")
    else:
        status = badge("Απόθεμα επαρκές", "good")

    policy = master["lot_sizing"]
    policy_label = theme.LOT_SIZING_LABELS_EL.get(policy, policy)
    if policy == "POQ":
        policy_note = f"παραγγελία που καλύπτει ~{master['poq_days']} ημέρες ζήτησης (οικονομικό διάστημα από EOQ)"
    elif policy == "EOQ":
        policy_note = "ποσότητα Wilson: √(2·D·S/(h·c)), τουλάχιστον όση η ανάγκη και το MOQ"
    elif policy == "WW":
        policy_note = "δυναμικός προγραμματισμός στον ορίζοντα πρόβλεψης (ελάχιστο κόστος παραγγελίας + διακράτησης)"
    elif policy == "FOQ":
        policy_note = f"πολλαπλάσια των {fmt_int(master['fixed_lot'] or master['moq'])} μονάδων"
    else:
        policy_note = "ακριβώς η καθαρή ανάγκη (με ελάχιστο το MOQ)"

    lines = [
        f"{status}",
        f"- **Απόθεμα σήμερα:** {fmt_int(stock)} {master['uom'] or ''} "
        + (f"(≈ {fmt_num(cover_days, 0)} ημέρες κάλυψης)" if cover_days is not None else "(χωρίς πρόβλεψη ζήτησης)")
        + (f" · ανοιχτές παραγγελίες {fmt_int(open_qty)}" if open_qty else " · καμία ανοιχτή παραγγελία"),
        f"- **Πρόβλεψη ζήτησης:** {fmt_num(fc, 1)} μονάδες/ημέρα (κινητός μέσος 30 ημ., "
        f"{fmt_int(master['n_history'])} κινήσεις τους τελευταίους 12 μήνες"
        + (f", τελευταία {fmt_date(master['last_movement'])})" if master["last_movement"] else ")"),
        f"- **Safety stock:** {fmt_int(ss)} · **Lead time:** {lt} ημ. · **MOQ:** {fmt_int(master['moq'])}",
        f"- **Πολιτική lot sizing:** {policy_label} — {policy_note}",
    ]
    if orders.empty:
        lines.append("- **Απόφαση:** το προβλεπόμενο απόθεμα παραμένει πάνω από το safety stock "
                     "σε όλο τον ορίζοντα → **καμία παραγγελία**.")
    else:
        first = orders.iloc[0]
        lines.append(
            f"- **Απόφαση MRP:** το προβλεπόμενο απόθεμα πέφτει κάτω από το safety stock στις "
            f"**{fmt_date(first['planned_arrival'])}** → παραγγελία **{fmt_int(first['planned_receipt'])}** "
            f"μονάδων με έκδοση **{fmt_date(first['planned_release'])}** "
            f"(συνολικά {len(orders)} παραγγελίες στον ορίζοντα)."
        )
        if bool(mrp_df.iloc[: max(lt, 1)]["below_safety"].any()):
            lines.append("- ⚠️ Η ανάγκη εμφανίζεται **μέσα στο lead time**: καμία νέα παραγγελία δεν "
                         "μπορεί να φτάσει νωρίτερα από σήμερα + lead time — ο planner μπορεί να "
                         "χρειαστεί επίσπευση (expedite).")

    # Rules from persisted proposals for this material
    if not proposals.empty:
        mine = proposals[proposals["material_id"] == master["material_id"]]
        if not mine.empty:
            rules = (mine["rule_triggered"].dropna().astype(str)
                         .str.split(" | ", regex=False).explode().str.strip())
            rules = [r for r in rules.unique() if r]
            if rules:
                pretty = ", ".join(f"`{r}` ({theme.RULE_LABELS_EL.get(r, '')})" for r in rules)
                lines.append(f"- **Κανόνες που εφαρμόστηκαν στις αποθηκευμένες προτάσεις:** {pretty}")
            else:
                lines.append("- **Κανόνες:** καμία τροποποίηση από τους επιχειρησιακούς κανόνες.")

    st.markdown("\n".join(lines), unsafe_allow_html=True)


def render(proposals: pd.DataFrame, materials: pd.DataFrame, as_of: date) -> None:
    """Render the drill-down tab."""
    materials_list = _material_choices()
    if not materials_list:
        st.warning("Δεν υπάρχουν υλικά στη βάση. Τρέξτε πρώτα το ETL.")
        return

    def _label(item: tuple[str, str]) -> str:
        mid, desc = item
        return f"{mid}  —  {desc}" if desc else mid

    material_ids = [m[0] for m in materials_list]

    # Default: first urgent material (most interesting to show)
    default_idx = 0
    if not proposals.empty:
        urgent = proposals[proposals["expedite"] == 1]
        if not urgent.empty:
            first = urgent.sort_values("estimated_cost", ascending=False).iloc[0]["material_id"]
            if first in material_ids:
                default_idx = material_ids.index(first)

    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        selected_tuple = st.selectbox("Υλικό", materials_list, index=default_idx,
                                      format_func=_label, key="dd_material")
    with c2:
        horizon = st.selectbox("Ορίζοντας (ημ.)", [30, 60, 90, 120], index=1, key="dd_horizon")
    with c3:
        method = st.selectbox("Μέθοδος πρόβλεψης",
                              ["moving_average", "exponential_smoothing", "simple_average"],
                              format_func=lambda m: {"moving_average": "Κινητός μέσος (30 ημ.)",
                                                     "exponential_smoothing": "Εκθετική εξομάλυνση",
                                                     "simple_average": "Απλός μέσος"}[m],
                              key="dd_method")
    selected = selected_tuple[0] if selected_tuple else None
    if not selected:
        return

    with st.spinner("Υπολογισμός MRP…"):
        mrp_df, master = _compute_mrp_for_material(selected, as_of, horizon=horizon, method=method)

    if mrp_df.empty:
        st.error(f"Δεν υπάρχουν δεδομένα για το {selected}")
        return

    # ---------- Master data + reasoning ----------
    left, right = st.columns([1, 1.5])
    with left:
        section(f"Master data — {master['material_id']}",
                master["description"] or "")
        stock_tone = ("critical" if master["current_stock"] < 0.5 * master["safety_stock"]
                      else "warning" if master["current_stock"] < master["safety_stock"] else "good")
        rows = [
            ("Κλάση ABC", master["abc_class"] or "—"),
            ("Τύπος υλικού", theme.MATERIAL_TYPE_EL.get(master["material_type"], master["material_type"] or "—")),
            ("Απόθεμα σήμερα", f"<b style='color:{theme.STATUS[stock_tone]}'>{fmt_int(master['current_stock'])}</b> {master['uom'] or ''}"),
            ("Safety stock", fmt_int(master["safety_stock"])),
            ("Reorder point", fmt_int(master["reorder_point"])),
            ("Lead time", f"{master['lead_time']} ημέρες"),
            ("MOQ", fmt_int(master["moq"])),
            ("Lot sizing", theme.LOT_SIZING_LABELS_EL.get(master["lot_sizing"], master["lot_sizing"])),
            ("Standard cost", fmt_eur(master["standard_cost"], 2)),
            ("Ανοιχτές παραγγελίες", (f"{len(master['open_pos'])} · {fmt_int(sum(q for _, q in master['open_pos']))} μον."
                                      if master["open_pos"] else "—")),
        ]
        html = "<table style='width:100%;font-size:.9rem;border-collapse:collapse'>"
        for k, v in rows:
            html += (f"<tr><td style='color:{theme.TEXT_SECONDARY};padding:.28rem 0;"
                     f"border-bottom:1px solid {theme.GRID}'>{k}</td>"
                     f"<td style='text-align:right;font-weight:600;padding:.28rem 0;"
                     f"border-bottom:1px solid {theme.GRID}'>{v}</td></tr>")
        html += "</table>"
        st.markdown(html, unsafe_allow_html=True)
    with right:
        section("Γιατί προτείνει ο πράκτορας;",
                "Η αιτιολόγηση της απόφασης, βήμα-βήμα, όπως την υπολογίζει το MRP.")
        _reasoning(master, mrp_df, proposals)

    st.divider()

    # ---------- Stock projection chart ----------
    section("Προβολή αποθέματος στον ορίζοντα σχεδιασμού",
            "Προβλεπόμενο διαθέσιμο απόθεμα ανά ημέρα, μετά τις προγραμματισμένες "
            "παραλαβές και τις προτεινόμενες παραγγελίες.")

    fig = go.Figure()
    x = pd.to_datetime(mrp_df["period"])

    # Exposure zone: periods below safety stock
    below = mrp_df[mrp_df["below_safety"]]
    if not below.empty:
        fig.add_trace(go.Bar(
            x=pd.to_datetime(below["period"]),
            y=[master["safety_stock"]] * len(below),
            marker_color="rgba(208,59,59,0.10)", marker_line_width=0,
            name="Κάτω από safety stock", hoverinfo="skip", showlegend=True,
        ))

    fig.add_trace(go.Scatter(
        x=x, y=mrp_df["projected_on_hand"],
        mode="lines", name="Προβλεπόμενο απόθεμα",
        line=dict(color=theme.ACCENT, width=2.5),
        hovertemplate="%{x|%d.%m.%Y}: %{y:,.0f}<extra></extra>",
    ))
    fig.add_hline(y=master["safety_stock"], line_dash="dash",
                  line_color=theme.STATUS["critical"], line_width=1.5,
                  annotation_text=f"Safety stock {fmt_int(master['safety_stock'])}",
                  annotation_position="top left",
                  annotation_font=dict(size=11, color=theme.STATUS["critical"]))

    receipts = mrp_df[mrp_df["scheduled_receipt"] > 0]
    if not receipts.empty:
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(receipts["period"]), y=receipts["projected_on_hand"],
            mode="markers", name="Παραλαβή ανοιχτής παραγγελίας",
            marker=dict(symbol="diamond", size=11, color=theme.NEUTRAL_DARK,
                        line=dict(color="white", width=2)),
            text=[fmt_int(v) for v in receipts["scheduled_receipt"]],
            hovertemplate="%{x|%d.%m.%Y}: παραλαβή %{text}<extra></extra>",
        ))
    landing = mrp_df[mrp_df["planned_arrival_qty"] > 0]
    if not landing.empty:
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(landing["period"]), y=landing["projected_on_hand"],
            mode="markers", name="Άφιξη προτεινόμενης παραγγελίας",
            marker=dict(symbol="triangle-up", size=14, color=theme.STATUS["good"],
                        line=dict(color="white", width=2)),
            text=[fmt_int(v) for v in landing["planned_arrival_qty"]],
            hovertemplate="%{x|%d.%m.%Y}: άφιξη %{text}<extra></extra>",
        ))
    orders = mrp_df[(mrp_df["planned_receipt"] > 0) & (mrp_df["planned_arrival"] == mrp_df["period"])]
    if not orders.empty:
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(orders["period"]), y=orders["projected_on_hand"],
            mode="markers", name="Άφιξη προτεινόμενης παραγγελίας",
            marker=dict(symbol="triangle-up", size=14, color=theme.STATUS["good"],
                        line=dict(color="white", width=2)),
            text=[fmt_int(v) for v in orders["planned_receipt"]],
            hovertemplate="%{x|%d.%m.%Y}: άφιξη %{text}<extra></extra>",
            showlegend=landing.empty,
        ))
    releases = mrp_df[mrp_df["planned_receipt"] > 0]
    for r in releases.itertuples():
        fig.add_vline(x=pd.Timestamp(r.planned_release).timestamp() * 1000,
                      line_color=theme.STATUS["good"], line_width=1, line_dash="dot",
                      opacity=0.6)

    theme.base_layout(fig, height=400)
    fig.update_layout(barmode="overlay", hovermode="x unified")
    fig.update_yaxes(title=f"Ποσότητα ({master['uom'] or 'μονάδες'})", rangemode="tozero")
    fig.update_xaxes(title="Ημερομηνία")
    plotly(fig, key="dd_projection")
    st.caption("Διακεκομμένες κάθετες γραμμές: ημερομηνίες έκδοσης παραγγελίας "
               "(άφιξη = έκδοση + lead time).")

    # ---------- MRP grid ----------
    with st.expander("📋 Πλήρης πίνακας MRP (ανά ημέρα)"):
        display_df = mrp_df.copy()
        display_df["period"] = pd.to_datetime(display_df["period"]).dt.strftime("%d.%m.%Y")
        for col in ["gross_requirement", "scheduled_receipt", "planned_arrival_qty",
                    "projected_on_hand", "net_requirement", "planned_receipt"]:
            display_df[col] = display_df[col].round(1)
        for col in ["planned_release", "planned_arrival"]:
            display_df[col] = pd.to_datetime(display_df[col], errors="coerce").dt.strftime("%d.%m.%Y").fillna("")
        display_df["below_safety"] = display_df["below_safety"].map({True: "⚠️", False: ""})
        display_df = display_df.rename(columns={
            "period": "Ημέρα", "gross_requirement": "Μικτή ανάγκη",
            "scheduled_receipt": "Ανοιχτές παραγγ.", "planned_arrival_qty": "Άφιξη πρότασης",
            "projected_on_hand": "Προβλ. απόθεμα", "net_requirement": "Καθαρή ανάγκη",
            "planned_receipt": "Πρόταση (ποσ.)", "planned_release": "Έκδοση",
            "planned_arrival": "Άφιξη", "below_safety": "< SS",
        })
        theme.dataframe(display_df, hide_index=True, height=320)

    # ---------- Consumption history ----------
    section("Ιστορικό κατανάλωσης (12 μήνες)",
            "Εβδομαδιαία κατανάλωση (κινήσεις 261/201/281).")
    history_df = _consumption_history_df(selected, as_of)
    if history_df.empty:
        st.info("Δεν υπάρχει ιστορικό κατανάλωσης για αυτό το υλικό.")
        return

    weekly = history_df.set_index("date")["quantity"].resample("W").sum().reset_index()
    fig = go.Figure(go.Bar(
        x=weekly["date"], y=weekly["quantity"], marker_color=theme.ACCENT,
        hovertemplate="Εβδομάδα %{x|%d.%m.%Y}: %{y:,.0f}<extra></extra>",
    ))
    theme.base_layout(fig, height=260, legend=False)
    fig.update_yaxes(title="Ποσότητα / εβδομάδα")
    plotly(fig, key="dd_history")

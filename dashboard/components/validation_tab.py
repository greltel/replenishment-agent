"""
Validation tab — the evaluation chapter of the thesis, in one place:

  1. As-Is vs To-Be backtest        (validation_report.csv, *_abc.csv)
  2. Cost scenarios                  (validation_report_all_scenarios.csv)
  3. Sensitivity analysis            (validation_report_sensitivity.csv)
  4. Random windows + bootstrap CI   (bootstrap_report.csv, *_summary.csv)
  5. Rule ablation                   (ablation_report.csv)

Every section reads the CSV produced by the corresponding script and says
which command produces it, so the committee can see the traceability.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import PROJECT_ROOT
from dashboard import theme
from dashboard.theme import fmt_int, fmt_num, fmt_eur, fmt_pct, section, plotly, kpi_tile


# ─── Pretty labels ───
LABELS = {
    "cycle_service_level_pct":   "Επίπεδο εξυπηρέτησης (%)",
    "fill_rate_pct":             "Fill rate (%)",
    "stockout_days":             "Ημέρες έλλειψης (υλικό×ημέρα)",
    "holding_cost_eur":          "Κόστος διακράτησης (€)",
    "capital_cost_eur":          "  · κόστος κεφαλαίου",
    "warehouse_cost_eur":        "  · αποθήκευση",
    "obsolescence_cost_eur":     "  · απαξίωση",
    "insurance_cost_eur":        "  · ασφάλιση",
    "stockout_cost_eur":         "Κόστος ελλείψεων (€)",
    "lost_sales_eur":            "  · χαμένες πωλήσεις",
    "expedite_premium_eur":      "  · επείγουσες προμήθειες",
    "ordering_cost_eur":         "Κόστος παραγγελιών (€)",
    "total_cost_of_ownership":   "Συνολικό κόστος (TCO, €)",
    "holding_cost_annualized_eur": "Κόστος διακράτησης — ετήσιο ισοδύναμο (€)",
    "tco_annualized_eur":        "TCO — ετήσιο ισοδύναμο (€)",
    "inventory_turns":           "Κυκλοφοριακή ταχύτητα (turns)",
    "avg_inventory_eur":         "Μέση αξία αποθέματος (€)",
    "n_orders":                  "Αριθμός παραγγελιών",
    "avg_order_size":            "Μέσο μέγεθος παραγγελίας",
    "days_of_cover_avg":         "Ημέρες κάλυψης (μ.ό.)",
}
DIRECTION_EL = {
    "↑ better": "↑ καλύτερα", "↓ better": "↓ καλύτερα",
    "↑ worse": "↑ χειρότερα", "↓ worse": "↓ χειρότερα",
    "= same": "= ίδιο", "neutral": "—",
}


def _load_csv(name: str) -> pd.DataFrame | None:
    for p in (PROJECT_ROOT / name, PROJECT_ROOT / "scripts" / name):
        if p.exists():
            try:
                return pd.read_csv(p)
            except Exception:
                return None
    return None


def _missing(cmd: str, what: str) -> None:
    st.info(f"Δεν βρέθηκε {what}. Παραγωγή με:\n\n```\n{cmd}\n```")


def _asis_tobe_bar(labels: list[str], asis: list[float], tobe: list[float],
                   key: str, height: int = 320, yaxis: str = "€") -> None:
    fig = go.Figure()
    fig.add_bar(x=labels, y=asis, name="As-Is (ιστορικές αποφάσεις)",
                marker_color=theme.NEUTRAL,
                text=[fmt_eur(v) if yaxis == "€" else fmt_num(v, 1) for v in asis],
                textposition="outside", hovertemplate="As-Is · %{x}: %{text}<extra></extra>")
    fig.add_bar(x=labels, y=tobe, name="To-Be (πράκτορας)",
                marker_color=theme.ACCENT,
                text=[fmt_eur(v) if yaxis == "€" else fmt_num(v, 1) for v in tobe],
                textposition="outside", hovertemplate="To-Be · %{x}: %{text}<extra></extra>")
    fig.update_layout(barmode="group")
    theme.base_layout(fig, height=height)
    fig.update_yaxes(title=yaxis, tickformat=",.0f")
    plotly(fig, key=key)


# ============================================================
# 1. Main backtest
# ============================================================
def _render_backtest(df: pd.DataFrame) -> None:
    df = df.copy()
    df["metric_label"] = df["metric"].map(LABELS).fillna(df["metric"])
    row = lambda m: df[df["metric"] == m].iloc[0] if (df["metric"] == m).any() else None

    tco = row("total_cost_of_ownership")
    csl = row("cycle_service_level_pct")
    so = row("stockout_days")
    hold = row("holding_cost_eur")
    inv = row("avg_inventory_eur")
    period = row("period_days")
    period_days = int(period["as_is"]) if period is not None else None
    tco_ann = row("tco_annualized_eur")

    section("Backtest As-Is vs To-Be",
            f"Προσομοίωση παραθύρου {period_days or '—'} ημερών πάνω στο ιστορικό: "
            "«As-Is» = οι πραγματικές παραλαβές της εταιρείας, «To-Be» = ο πράκτορας "
            "αποφασίζει κάθε 7 ημέρες με τα ίδια δεδομένα (χωρίς look-ahead). "
            "Κόστη για τη διάρκεια του παραθύρου.")

    c = st.columns(5)
    if tco is not None:
        c[0].markdown(kpi_tile("Εξοικονόμηση TCO",
                               fmt_eur(-tco["delta_abs"]),
                               f"{fmt_pct(-tco['delta_pct'], 1)} του As-Is TCO "
                               f"({fmt_eur(tco['as_is'])} → {fmt_eur(tco['to_be'])})",
                               "good" if tco["delta_abs"] < 0 else "critical"),
                      unsafe_allow_html=True)
    if tco_ann is not None:
        c[1].markdown(kpi_tile("Ετήσιο ισοδύναμο εξοικονόμησης",
                               fmt_eur(-tco_ann["delta_abs"]),
                               f"× 365/{period_days} — ενδεικτική γραμμική αναγωγή",
                               "accent"), unsafe_allow_html=True)
    if csl is not None:
        c[2].markdown(kpi_tile("Επίπεδο εξυπηρέτησης",
                               f"{fmt_num(csl['as_is'], 1)}% → {fmt_num(csl['to_be'], 1)}%",
                               f"{csl['delta_abs']:+.2f} ποσοστιαίες μονάδες",
                               "good" if csl["delta_abs"] >= 0 else "critical"),
                      unsafe_allow_html=True)
    if so is not None:
        c[3].markdown(kpi_tile("Ημέρες έλλειψης",
                               f"{fmt_int(so['as_is'])} → {fmt_int(so['to_be'])}",
                               f"{fmt_pct(so['delta_pct'], 0, signed=True) if pd.notna(so['delta_pct']) else ''}",
                               "good" if so["delta_abs"] <= 0 else "critical"),
                      unsafe_allow_html=True)
    if inv is not None:
        c[4].markdown(kpi_tile("Μέση αξία αποθέματος",
                               fmt_pct(inv["delta_pct"], 1, signed=True),
                               f"{fmt_eur(inv['as_is'])} → {fmt_eur(inv['to_be'])}",
                               "good" if inv["delta_abs"] <= 0 else "critical"),
                      unsafe_allow_html=True)
    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)

    g1, g2 = st.columns([1.2, 1])
    with g1:
        section("Σύνθεση συνολικού κόστους (TCO)",
                "TCO = διακράτηση + ελλείψεις + παραγγελίες. Ο πράκτορας ανταλλάσσει "
                "λίγο περισσότερες παραγγελίες με λιγότερο απόθεμα και λιγότερες ελλείψεις.")
        parts = ["holding_cost_eur", "stockout_cost_eur", "ordering_cost_eur", "total_cost_of_ownership"]
        sub = df[df["metric"].isin(parts)].set_index("metric").reindex(parts)
        _asis_tobe_bar(["Διακράτηση", "Ελλείψεις", "Παραγγελίες", "TCO"],
                       sub["as_is"].tolist(), sub["to_be"].tolist(), key="val_tco")
    with g2:
        section("Ανάλυση κόστους διακράτησης",
                "Silver-Pyke-Peterson: κεφάλαιο + αποθήκευση + απαξίωση + ασφάλιση.")
        parts = ["capital_cost_eur", "warehouse_cost_eur", "obsolescence_cost_eur", "insurance_cost_eur"]
        sub = df[df["metric"].isin(parts)].set_index("metric").reindex(parts)
        _asis_tobe_bar(["Κεφάλαιο", "Αποθήκευση", "Απαξίωση", "Ασφάλιση"],
                       sub["as_is"].tolist(), sub["to_be"].tolist(), key="val_holding")

    with st.expander("Αναλυτικός πίνακας KPI", expanded=False):
        order = ["cycle_service_level_pct", "fill_rate_pct", "stockout_days",
                 "holding_cost_eur", "capital_cost_eur", "warehouse_cost_eur",
                 "obsolescence_cost_eur", "insurance_cost_eur",
                 "stockout_cost_eur", "lost_sales_eur", "expedite_premium_eur",
                 "ordering_cost_eur", "total_cost_of_ownership",
                 "holding_cost_annualized_eur", "tco_annualized_eur",
                 "avg_inventory_eur", "inventory_turns", "days_of_cover_avg",
                 "n_orders", "avg_order_size"]
        sub = df.set_index("metric").reindex([m for m in order if m in set(df["metric"])]).reset_index()
        table = pd.DataFrame({
            "KPI": sub["metric"].map(LABELS).fillna(sub["metric"]),
            "As-Is": sub["as_is"].round(2),
            "To-Be": sub["to_be"].round(2),
            "Δ": sub["delta_abs"].round(2),
            "Δ %": sub["delta_pct"].round(1),
            "Κατεύθυνση": sub["direction"].map(DIRECTION_EL).fillna(sub["direction"]),
        })
        theme.dataframe(table, hide_index=True, height=560)

    abc = _load_csv("validation_report_abc.csv")
    if abc is not None and not abc.empty:
        section("Εξοικονόμηση ανά κλάση ABC",
                "Το μεγαλύτερο μέρος της αξίας προέρχεται από τα A-items (αρχή Pareto).")
        a1, a2 = st.columns([1, 1.2])
        with a1:
            _asis_tobe_bar([f"Κλάση {c}" for c in abc["abc_class"]],
                           abc["asis_tco"].tolist(), abc["tobe_tco"].tolist(),
                           key="val_abc", height=300)
        with a2:
            table = pd.DataFrame({
                "Κλάση": abc["abc_class"],
                "Υλικά": abc["n_materials"],
                "TCO As-Is (€)": abc["asis_tco"].round(0),
                "TCO To-Be (€)": abc["tobe_tco"].round(0),
                "Εξοικονόμηση (€)": abc["savings"].round(0),
                "Εξοικ. %": abc["savings_pct"].round(1),
                "Service As-Is": abc["asis_service"],
                "Service To-Be": abc["tobe_service"],
            })
            theme.dataframe(table, hide_index=True)

    st.caption("Μεθοδολογία κόστους: Silver, Pyke & Peterson (1998) · Vollmann et al. (2005). "
               "Το κόστος διακράτησης = μέση αξία αποθέματος × ετήσιο ποσοστό × ημέρες/365· "
               "κόστος ελλείψεων = χαμένο περιθώριο + premium επείγουσας προμήθειας· "
               "κόστος παραγγελιών = πλήθος × €50. Οι ημέρες έλλειψης του As-Is προκύπτουν "
               "από το ιστορικό αποθέματος· η μη ικανοποιηθείσα ζήτηση δεν καταγράφεται στο SAP, "
               "άρα το κόστος ελλείψεων του As-Is είναι συντηρητική εκτίμηση.")


# ============================================================
# 2. Cross-scenario
# ============================================================
def _render_cross_scenario(df: pd.DataFrame) -> None:
    section("Σενάρια κόστους",
            "Conservative (~12% holding rate) · realistic (~20%) · aggressive (~28%). "
            "Η εξοικονόμηση πρέπει να διατηρείται ανεξάρτητα από τις κοστολογικές παραδοχές.")
    if "total_cost_of_ownership" not in df.columns:
        theme.dataframe(df, hide_index=True)
        return
    rows = []
    for scen in ("conservative", "realistic", "aggressive"):
        a = df[df["scenario"] == f"{scen}_asis"]
        t = df[df["scenario"] == f"{scen}_tobe"]
        if a.empty or t.empty:
            continue
        a_tco = float(a["total_cost_of_ownership"].iloc[0])
        t_tco = float(t["total_cost_of_ownership"].iloc[0])
        rows.append({"scenario": scen, "asis": a_tco, "tobe": t_tco,
                     "savings": a_tco - t_tco,
                     "pct": (a_tco - t_tco) / a_tco * 100 if a_tco else np.nan})
    if not rows:
        theme.dataframe(df, hide_index=True)
        return
    r = pd.DataFrame(rows)
    c1, c2 = st.columns([1.2, 1])
    with c1:
        _asis_tobe_bar([s.capitalize() for s in r["scenario"]], r["asis"].tolist(),
                       r["tobe"].tolist(), key="val_scen", height=300)
    with c2:
        table = pd.DataFrame({
            "Σενάριο": r["scenario"].str.capitalize(),
            "TCO As-Is (€)": r["asis"].round(0),
            "TCO To-Be (€)": r["tobe"].round(0),
            "Εξοικονόμηση (€)": r["savings"].round(0),
            "Εξοικ. %": r["pct"].round(1),
        })
        theme.dataframe(table, hide_index=True)


# ============================================================
# 3. Sensitivity
# ============================================================
def _render_sensitivity(df: pd.DataFrame) -> None:
    section("Ανάλυση ευαισθησίας",
            "Διαταράξεις ±20% σε lead time, ζήτηση (±10%) και holding rate. "
            "Στιβαρό αποτέλεσμα = η εξοικονόμηση διατηρεί πρόσημο και τάξη μεγέθους.")
    if "tco_savings" not in df.columns:
        theme.dataframe(df, hide_index=True)
        return
    label_el = {
        "base": "Βάση", "lt_-20%": "Lead time −20%", "lt_+20%": "Lead time +20%",
        "demand_-10%": "Ζήτηση −10%", "demand_+10%": "Ζήτηση +10%",
        "holding_-20%": "Holding −20%", "holding_+20%": "Holding +20%",
        "worst_case": "Χειρότερη περίπτωση", "best_case": "Καλύτερη περίπτωση",
    }
    labels = [label_el.get(v, v) for v in df["variation"]]
    fig = go.Figure(go.Bar(
        x=labels, y=df["tco_savings"],
        marker_color=[theme.ACCENT_DARK if v == "base" else theme.ACCENT for v in df["variation"]],
        text=[fmt_eur(v) for v in df["tco_savings"]], textposition="outside",
        hovertemplate="%{x}: %{text}<extra></extra>",
    ))
    theme.base_layout(fig, height=340, legend=False)
    fig.update_yaxes(title="Εξοικονόμηση TCO (€)", tickformat=",.0f")
    plotly(fig, key="val_sens")
    with st.expander("Πίνακας ευαισθησίας"):
        theme.dataframe(df, hide_index=True)


# ============================================================
# 4. Bootstrap
# ============================================================
def _render_bootstrap(samples: pd.DataFrame, summary: pd.DataFrame | None) -> None:
    section("Στατιστική σημαντικότητα — τυχαία παράθυρα και bootstrap",
            "Στάδιο 1: N τυχαία παράθυρα backtest (seed 42). Στάδιο 2: bootstrap του "
            "μέσου (B = 2.000), t-CI και ακριβής έλεγχος προσήμου. Απαντά στο ερώτημα "
            "«μήπως το αποτέλεσμα οφείλεται σε ευνοϊκή περίοδο;».")
    valid = samples[samples["error"].fillna("") == ""] if "error" in samples.columns else samples
    savings = valid["savings"].astype(float)
    n = len(savings)
    window_days = int(valid["window_days"].iloc[0]) if "window_days" in valid.columns and n else None

    stats = None
    if summary is not None and not summary.empty and "metric" in summary.columns:
        s = summary[summary["metric"].isin(["tco_savings_eur", "savings"])]
        if not s.empty:
            stats = s.iloc[0]

    mean = float(savings.mean()) if n else 0.0
    c = st.columns(4)
    c[0].markdown(kpi_tile("Μέση εξοικονόμηση / παράθυρο", fmt_eur(mean),
                           f"{n} παράθυρα" + (f" × {window_days} ημ." if window_days else ""),
                           "good" if mean > 0 else "critical"), unsafe_allow_html=True)
    if stats is not None and "mean_ci_lower" in stats:
        c[1].markdown(kpi_tile("95% CI του μέσου (bootstrap)",
                               f"[{fmt_eur(stats['mean_ci_lower'])}, {fmt_eur(stats['mean_ci_upper'])}]",
                               f"B = {fmt_int(stats.get('n_bootstrap', 0))} · p "
                               f"{'< 0,001' if stats['p_value'] < 0.001 else '= ' + fmt_num(stats['p_value'], 4)}",
                               "accent"), unsafe_allow_html=True)
        c[2].markdown(kpi_tile("t-test / έλεγχος προσήμου",
                               f"{fmt_int(stats.get('n_positive', 0))} / {n} θετικά",
                               f"t = {fmt_num(stats.get('t_statistic', 0), 2)} · p(t) "
                               f"{'< 0,001' if stats.get('t_p_value', 1) < 0.001 else fmt_num(stats.get('t_p_value', 1), 4)}"
                               f" · p(sign) {'< 0,001' if stats.get('sign_test_p_value', 1) < 0.001 else fmt_num(stats.get('sign_test_p_value', 1), 4)}",
                               "good" if stats.get("is_significant") else "critical"),
                      unsafe_allow_html=True)
        c[3].markdown(kpi_tile("Στατιστικά σημαντικό;",
                               "ΝΑΙ" if stats.get("is_significant") else "ΟΧΙ",
                               "το CI του μέσου εξαιρεί το 0 και p < 0,05" if stats.get("is_significant")
                               else "το CI περιλαμβάνει το 0",
                               "good" if stats.get("is_significant") else "critical"),
                      unsafe_allow_html=True)
    else:
        c[1].markdown(kpi_tile("Τυπική απόκλιση", fmt_eur(float(savings.std(ddof=1)) if n > 1 else 0),
                               "των τιμών ανά παράθυρο"), unsafe_allow_html=True)
        c[2].markdown(kpi_tile("Θετικά παράθυρα", f"{int((savings > 0).sum())} / {n}", ""),
                      unsafe_allow_html=True)
    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)

    h1, h2 = st.columns([1.3, 1])
    with h1:
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=savings, nbinsx=max(8, min(15, n // 2)), marker_color=theme.ACCENT,
            marker_line=dict(color="white", width=2), name="Παράθυρα",
            hovertemplate="Εξοικονόμηση %{x}: %{y} παράθυρα<extra></extra>",
        ))
        fig.add_vline(x=0, line_color=theme.TEXT_SECONDARY, line_width=1)
        fig.add_vline(x=mean, line_color=theme.STATUS["good"], line_width=2, line_dash="dash",
                      annotation_text=f"μέσος {fmt_eur(mean)}", annotation_position="top right",
                      annotation_font=dict(size=11, color=theme.STATUS["good"]))
        if stats is not None and "mean_ci_lower" in stats:
            fig.add_vrect(x0=stats["mean_ci_lower"], x1=stats["mean_ci_upper"],
                          fillcolor=theme.STATUS["good"], opacity=0.10, line_width=0,
                          annotation_text="95% CI μέσου", annotation_position="bottom left",
                          annotation_font=dict(size=10, color=theme.STATUS["good"]))
        theme.base_layout(fig, height=320, legend=False,
                          title="Κατανομή εξοικονόμησης TCO ανά παράθυρο")
        fig.update_xaxes(title="Εξοικονόμηση (€ ανά παράθυρο)", tickformat=",.0f")
        fig.update_yaxes(title="Παράθυρα")
        plotly(fig, key="val_boot_hist")
    with h2:
        fig = go.Figure(go.Scatter(
            x=list(range(1, n + 1)), y=savings,
            mode="markers", marker=dict(size=9, color=[theme.STATUS["good"] if v > 0 else theme.STATUS["critical"] for v in savings],
                                        line=dict(color="white", width=1.5)),
            hovertemplate="Παράθυρο %{x}: %{y:,.0f} €<extra></extra>", name="",
        ))
        fig.add_hline(y=0, line_color=theme.TEXT_SECONDARY, line_width=1)
        theme.base_layout(fig, height=320, legend=False, title="Εξοικονόμηση ανά παράθυρο")
        fig.update_xaxes(title="Παράθυρο #")
        fig.update_yaxes(title="€", tickformat=",.0f")
        plotly(fig, key="val_boot_points")

    with st.expander("Πίνακας παραθύρων (Παράρτημα Γ)"):
        cols = [c for c in ["window", "window_start", "window_end", "asis_tco", "tobe_tco",
                            "savings", "asis_service", "tobe_service"] if c in valid.columns]
        theme.dataframe(valid[cols], hide_index=True, height=360)


# ============================================================
# 5. Ablation
# ============================================================
def _render_ablation(df: pd.DataFrame) -> None:
    section("Rule ablation — συνεισφορά κάθε κανόνα (leave-one-out)",
            "Ο πράκτορας ξανατρέχει 7 φορές, κάθε φορά χωρίς έναν κανόνα. Η διαφορά από "
            "το baseline είναι η οριακή συνεισφορά του κανόνα. «Ενημερωτικοί» κανόνες "
            "(σήμανση επείγοντος, εκτίμηση κόστους) δεν αλλάζουν ποσότητες, άρα δεν "
            "μετακινούν KPIs — αλλάζουν όμως τι βλέπει ο planner.")
    abl = df[df["disabled_rule"] != "(none)"].copy()
    base = df[df["disabled_rule"] == "(none)"]
    if abl.empty:
        theme.dataframe(df, hide_index=True)
        return
    abl["label"] = abl["disabled_rule"].map(lambda r: f"{r}  ·  {theme.RULE_LABELS_EL.get(r, '')}")
    abl = abl.sort_values("Δ_tco")
    colors = [theme.STATUS["good"] if v > 0 else theme.STATUS["warning"] if v < 0 else theme.NEUTRAL
              for v in abl["Δ_tco"]]
    fig = go.Figure(go.Bar(
        x=abl["Δ_tco"], y=abl["label"], orientation="h", marker_color=colors,
        text=[fmt_eur(v) for v in abl["Δ_tco"]], textposition="outside",
        cliponaxis=False,
        hovertemplate="%{y}<br>Δ TCO όταν αφαιρεθεί: %{text}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=theme.TEXT_SECONDARY, line_width=1)
    theme.base_layout(fig, height=360, legend=False,
                      title="Δ TCO όταν αφαιρεθεί ο κανόνας (πράσινο = ο κανόνας εξοικονομεί, "
                            "πορτοκαλί = κοστίζει, γκρι = χωρίς επίδραση)")
    # Leave room for the "outside" value labels so they are never clipped by
    # the plot edge (the largest bar otherwise hides its own label).
    lo, hi = float(abl["Δ_tco"].min()), float(abl["Δ_tco"].max())
    span = max(hi - lo, abs(hi), abs(lo), 1.0)
    fig.update_xaxes(title="Δ TCO (€)", tickformat=",.0f",
                     range=[min(lo, 0) - 0.18 * span, max(hi, 0) + 0.18 * span])
    plotly(fig, key="val_ablation")
    if not base.empty:
        b = base.iloc[0]
        st.caption(f"Baseline (όλοι οι κανόνες): TCO {fmt_eur(b['tco_eur'])} · "
                   f"service {fmt_num(b['service_level_pct'], 2)}% · "
                   f"ημέρες έλλειψης {fmt_int(b['stockout_days'])} · "
                   f"προτάσεις {fmt_int(b['n_proposals'])}.")
    with st.expander("Πίνακας ablation"):
        cols = ["disabled_rule", "n_proposals", "Δ_proposals", "service_level_pct", "Δ_service_pp",
                "holding_cost_eur", "Δ_holding", "stockout_cost_eur", "Δ_stockout_cost",
                "stockout_days", "Δ_stockout_days", "tco_eur", "Δ_tco"]
        theme.dataframe(df[[c for c in cols if c in df.columns]], hide_index=True)


# ============================================================
# Entry point
# ============================================================
def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    main = _load_csv("validation_report.csv")
    if main is None or main.empty or "metric" not in main.columns:
        _missing("python scripts/run_validation.py", "αναφορά backtest (validation_report.csv)")
    else:
        _render_backtest(main)

    st.divider()
    scen = _load_csv("validation_report_all_scenarios.csv")
    if scen is None or scen.empty:
        _missing("python scripts/run_validation.py --all-scenarios",
                 "σύγκριση σεναρίων κόστους (validation_report_all_scenarios.csv)")
    else:
        _render_cross_scenario(scen)

    st.divider()
    sens = _load_csv("validation_report_sensitivity.csv")
    if sens is None or sens.empty:
        _missing("python scripts/run_validation.py --sensitivity",
                 "ανάλυση ευαισθησίας (validation_report_sensitivity.csv)")
    else:
        _render_sensitivity(sens)

    st.divider()
    boot = _load_csv("bootstrap_report.csv")
    if boot is None or boot.empty:
        _missing("python scripts/run_bootstrap.py", "ανάλυση bootstrap (bootstrap_report.csv)")
    else:
        _render_bootstrap(boot, _load_csv("bootstrap_report_summary.csv"))

    st.divider()
    abl = _load_csv("ablation_report.csv")
    if abl is None or abl.empty:
        _missing("python scripts/run_rule_ablation.py --stress-test",
                 "μελέτη ablation (ablation_report.csv)")
    else:
        _render_ablation(abl)

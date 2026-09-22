"""Overview tab — visual summary of the agent's proposals + how the agent works."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import theme
from dashboard.theme import fmt_int, fmt_eur, section, plotly


def _bdi_explainer() -> None:
    """A compact 'how it decides' strip for the committee."""
    st.markdown(
        """
        <div class="bdi-row">
          <div class="bdi-box"><h4>1 · Beliefs — Αντίληψη</h4>
            <p>Τρέχον απόθεμα (MARD), ανοιχτές παραγγελίες (EKKO/EKPO), ιστορικό
            κατανάλωσης 12 μηνών (MB51) και master data (MARC) φορτώνονται ως
            «πεποιθήσεις» του πράκτορα για την ημερομηνία αναφοράς.</p></div>
          <div class="bdi-arrow">→</div>
          <div class="bdi-box"><h4>2 · Desires — Στόχοι</h4>
            <p>Επίπεδο εξυπηρέτησης 98%, ελαχιστοποίηση κόστους διακράτησης,
            αποφυγή ελλείψεων, σεβασμός MOQ και ημερολογίου προμηθευτή.</p></div>
          <div class="bdi-arrow">→</div>
          <div class="bdi-box"><h4>3 · Deliberation — MRP + Κανόνες</h4>
            <p>Πρόβλεψη ζήτησης → χρονικά κλιμακωμένο MRP (net requirements, lead-time
            offset) → lot sizing (LFL/FOQ/EOQ/POQ/Wagner-Whitin) → 7 επιχειρησιακοί
            κανόνες με προτεραιότητα.</p></div>
          <div class="bdi-arrow">→</div>
          <div class="bdi-box"><h4>4 · Intentions — Προτάσεις</h4>
            <p>Για κάθε υλικό: <b>πότε</b> (ημερομηνία παραγγελίας) και <b>πόσο</b>
            (ποσότητα), με αιτιολόγηση (κανόνες), σήμανση επείγοντος και εκτίμηση
            κόστους — έτοιμες για έγκριση από τον planner.</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render(proposals: pd.DataFrame, materials: pd.DataFrame, as_of: date) -> None:
    with st.expander("Πώς αποφασίζει ο πράκτορας (κύκλος BDI)", expanded=False):
        _bdi_explainer()

    if proposals.empty:
        st.warning("Δεν υπάρχουν προτάσεις για εμφάνιση.")
        return

    df = proposals.merge(
        materials[["material_id", "abc_class", "lot_sizing", "lead_time_days",
                   "description"]],
        on="material_id", how="left",
    )
    df["proposed_date"] = pd.to_datetime(df["proposed_date"])

    # ---------- Row 1: by ABC class ----------
    c1, c2 = st.columns(2)
    with c1:
        section("Προτάσεις ανά κλάση ABC",
                "Πλήθος προτάσεων στον ορίζοντα σχεδιασμού.")
        counts = (df.groupby("abc_class")["proposal_id"].count()
                    .reindex(theme.ABC_ORDER).fillna(0))
        fig = go.Figure(go.Bar(
            x=counts.index, y=counts.values,
            marker_color=[theme.ABC_COLORS[c] for c in counts.index],
            text=[fmt_int(v) for v in counts.values], textposition="outside",
            hovertemplate="Κλάση %{x}: %{y} προτάσεις<extra></extra>",
        ))
        theme.base_layout(fig, height=300, legend=False)
        fig.update_yaxes(title="Προτάσεις")
        plotly(fig, key="ov_abc_counts")

    with c2:
        section("Αξία παραγγελιών ανά κλάση ABC",
                "Εκτιμώμενο κόστος αγοράς (ποσότητα × standard cost).")
        value = (df.groupby("abc_class")["estimated_cost"].sum()
                   .reindex(theme.ABC_ORDER).fillna(0))
        fig = go.Figure(go.Bar(
            x=value.index, y=value.values,
            marker_color=[theme.ABC_COLORS[c] for c in value.index],
            text=[fmt_eur(v) for v in value.values], textposition="outside",
            hovertemplate="Κλάση %{x}: %{text}<extra></extra>",
        ))
        theme.base_layout(fig, height=300, legend=False)
        fig.update_yaxes(title="€", tickformat=",.0f")
        plotly(fig, key="ov_abc_value")

    # ---------- Row 2: weekly timeline ----------
    section("Χρονοδιάγραμμα παραγγελιών",
            "Προτεινόμενη ποσότητα ανά εβδομάδα έκδοσης παραγγελίας, ανά κλάση ABC.")
    weekly = df.copy()
    weekly["week"] = weekly["proposed_date"].dt.to_period("W-SUN").dt.start_time
    pivot = (weekly.groupby(["week", "abc_class"])["proposed_qty"].sum()
                   .unstack("abc_class").reindex(columns=theme.ABC_ORDER).fillna(0))
    fig = go.Figure()
    for cls in theme.ABC_ORDER:
        if cls in pivot.columns:
            fig.add_bar(
                x=pivot.index, y=pivot[cls],
                name=f"Κλάση {cls}", marker_color=theme.ABC_COLORS[cls],
                hovertemplate="Εβδομάδα %{x|%d.%m.%Y} · " + cls + ": %{y:,.0f}<extra></extra>",
            )
    fig.update_layout(barmode="stack")
    theme.base_layout(fig, height=320)
    fig.update_xaxes(title="Εβδομάδα (Δευτέρα)", type="date", tickformat="%d.%m",
                     dtick=7 * 24 * 3600 * 1000)
    fig.update_yaxes(title="Ποσότητα")
    plotly(fig, key="ov_timeline")

    # ---------- Row 3: rules + urgent list ----------
    c3, c4 = st.columns([3, 2])
    with c3:
        section("Ενεργοποίηση κανόνων",
                "Πόσες προτάσεις επηρέασε κάθε κανόνας (μία πρόταση μπορεί να "
                "έχει περάσει από πολλούς κανόνες).")
        rules_series = (df["rule_triggered"].dropna().astype(str)
                          .str.split(" | ", regex=False).explode().str.strip())
        rules_series = rules_series[rules_series != ""]
        if rules_series.empty:
            st.info("Καμία πρόταση δεν τροποποιήθηκε από κανόνα.")
        else:
            counts = rules_series.value_counts().sort_values()
            labels = [f"{r}  ·  {theme.RULE_LABELS_EL.get(r, '')}" for r in counts.index]
            fig = go.Figure(go.Bar(
                x=counts.values, y=labels, orientation="h",
                marker_color=theme.ACCENT,
                text=[fmt_int(v) for v in counts.values], textposition="outside",
                hovertemplate="%{y}: %{x} προτάσεις<extra></extra>",
            ))
            theme.base_layout(fig, height=max(240, 44 * len(counts) + 60), legend=False)
            fig.update_xaxes(title="Προτάσεις")
            plotly(fig, key="ov_rules")

    with c4:
        section("Επείγουσες προτάσεις",
                "Υλικά με απόθεμα κάτω από το 50% του safety stock.")
        urgent = (df[df["expedite"] == 1]
                    .sort_values(["proposed_date", "estimated_cost"], ascending=[True, False])
                    .drop_duplicates("material_id").head(8))
        if urgent.empty:
            st.success("Καμία επείγουσα πρόταση — όλα τα υλικά πάνω από το όριο ασφαλείας.")
        else:
            rows = []
            for r in urgent.itertuples():
                rows.append({
                    "Υλικό": r.material_id,
                    "Περιγραφή": (r.description or "")[:32],
                    "ABC": r.abc_class,
                    "Παραγγελία": r.proposed_date.strftime("%d.%m"),
                    "Ποσότητα": fmt_int(r.proposed_qty),
                })
            theme.dataframe(pd.DataFrame(rows), hide_index=True,
                            height=min(330, 38 * (len(rows) + 1) + 4))

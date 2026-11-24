"""KPI tiles at the top of the dashboard."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from dashboard import theme
from dashboard.theme import fmt_int, fmt_eur, fmt_date, kpi_tile


def render(proposals: pd.DataFrame, materials: pd.DataFrame, summary: dict) -> None:
    """Render the top KPI tiles."""
    if proposals.empty:
        st.info("Δεν υπάρχουν προτάσεις ακόμη. Τρέξτε τον πράκτορα: "
                "`python scripts/run_agent.py` ή πατήστε «Εκτέλεση πράκτορα».")
        return

    n_proposals = len(proposals)
    n_materials_total = int(summary.get("n_materials") or len(materials) or 0)
    materials_active = proposals["material_id"].nunique()
    total_cost = float(proposals["estimated_cost"].sum())
    n_urgent = int(proposals["expedite"].sum())
    n_urgent_materials = int(proposals.loc[proposals["expedite"] == 1, "material_id"].nunique())

    as_of = summary.get("as_of")
    dates = pd.to_datetime(proposals["proposed_date"])
    next_14 = int((dates <= pd.Timestamp(as_of) + pd.Timedelta(days=14)).sum()) if as_of else 0
    first_date = dates.min()

    # Value at risk: cost of the urgent proposals
    urgent_value = float(proposals.loc[proposals["expedite"] == 1, "estimated_cost"].sum())

    a_ids = set(materials.loc[materials["abc_class"] == "A", "material_id"]) if not materials.empty else set()
    n_a = int(proposals["material_id"].isin(a_ids).sum())

    cols = st.columns(5)
    tiles = [
        kpi_tile("Προτάσεις αναπλήρωσης", fmt_int(n_proposals),
                 f"{fmt_int(next_14)} εντός 14 ημερών · ορίζοντας 60 ημ.",
                 "accent"),
        kpi_tile("Υλικά με πρόταση", f"{fmt_int(materials_active)} / {fmt_int(n_materials_total)}",
                 f"{fmt_int(n_a)} προτάσεις σε υλικά A-class"),
        kpi_tile("Επείγοντα υλικά", fmt_int(n_urgent_materials),
                 f"απόθεμα < 50% του safety stock (R-EXPEDITE) · αξία {fmt_eur(urgent_value)}",
                 "critical" if n_urgent else "good"),
        kpi_tile("Αξία προτεινόμενων παραγγελιών", fmt_eur(total_cost),
                 f"ποσότητα {fmt_int(float(proposals['proposed_qty'].sum()))} μονάδες"),
        kpi_tile("Αδρανές απόθεμα", fmt_int(summary.get("inactive_materials", 0)) + " υλικά",
                 f">180 ημ. χωρίς κατανάλωση · δεσμευμένη αξία "
                 f"{fmt_eur(summary.get('inactive_stock_value', 0))}",
                 "warning" if summary.get("inactive_materials") else ""),
    ]
    for col, html in zip(cols, tiles):
        col.markdown(html, unsafe_allow_html=True)
    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)

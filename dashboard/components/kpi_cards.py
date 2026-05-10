"""KPI cards row at the top of the dashboard."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    """Render the top KPI cards."""
    if proposals.empty:
        st.info("No proposals yet. Run the agent first: `python scripts/run_agent.py`")
        return

    n_proposals = len(proposals)
    total_qty = float(proposals["proposed_qty"].sum())
    total_cost = float(proposals["estimated_cost"].sum())
    materials_active = proposals["material_id"].nunique()
    n_expedite = int(proposals["expedite"].sum())

    # ABC distribution of proposals
    abc_a = len(proposals[proposals["material_id"].isin(
        materials[materials["abc_class"] == "A"]["material_id"]
    )])

    cols = st.columns(5)
    cols[0].metric("Total proposals",  f"{n_proposals:,}")
    cols[1].metric("Materials covered", f"{materials_active:,}")
    cols[2].metric("Total qty",         f"{total_qty:,.0f}")
    cols[3].metric("Estimated cost",    f"€{total_cost:,.0f}")
    cols[4].metric(
        "Expedite alerts",
        f"{n_expedite:,}",
        delta=f"of which A-class: {abc_a}" if abc_a else None,
        delta_color="off",
    )

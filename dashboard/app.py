"""
Streamlit dashboard for the Replenishment Agent.

Run with:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Add project root to path so `src.` imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_layer.repository import Repository
from dashboard.components import (
    kpi_cards,
    overview_tab,
    proposals_tab,
    drilldown_tab,
    forecast_tab,
    validation_tab,
    copilot_tab,
)


# ============================================================
# Page config
# ============================================================
st.set_page_config(
    page_title="Replenishment Agent — Athens MBA",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# Data loading (cached)
# ============================================================
@st.cache_data(ttl=120)
def load_proposals() -> pd.DataFrame:
    repo = Repository()
    try:
        df = pd.read_sql("SELECT * FROM proposals ORDER BY proposed_date", repo.engine)
    except Exception:
        df = pd.DataFrame()
    repo.close()
    return df


@st.cache_data(ttl=300)
def load_materials() -> pd.DataFrame:
    repo = Repository()
    try:
        df = pd.read_sql("SELECT * FROM materials", repo.engine)
    except Exception:
        df = pd.DataFrame()
    repo.close()
    return df


def _refresh_caches():
    load_proposals.clear()
    load_materials.clear()


# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.title("📦 Replenishment Agent")
    st.caption("Athens MBA — Διπλωματική Εργασία")
    st.divider()

    materials_df = load_materials()
    if not materials_df.empty:
        # Filters affect tabs that subscribe to them
        st.subheader("Filters")
        abc_options = sorted(materials_df["abc_class"].dropna().unique().tolist())
        abc_selected = st.multiselect(
            "ABC class",
            options=abc_options,
            default=abc_options,
        )
    else:
        abc_selected = []

    st.divider()
    st.subheader("Actions")

    if st.button("🔄 Refresh data", use_container_width=True):
        _refresh_caches()
        st.rerun()

    if st.button("🤖 Re-run agent", use_container_width=True):
        with st.spinner("Running agent..."):
            project_root = Path(__file__).resolve().parent.parent
            result = subprocess.run(
                [sys.executable, str(project_root / "scripts" / "run_agent.py")],
                capture_output=True, text=True, cwd=project_root,
            )
            if result.returncode == 0:
                st.success("Agent run completed!")
                _refresh_caches()
                st.rerun()
            else:
                st.error(f"Agent failed:\n{result.stderr[-500:]}")

    st.divider()
    st.caption(f"Materials in DB: {len(materials_df)}")


# ============================================================
# Main content
# ============================================================
st.title("Inventory Replenishment Dashboard")

proposals_df = load_proposals()

# Apply ABC filter at top level
if abc_selected and not proposals_df.empty:
    valid_materials = materials_df[
        materials_df["abc_class"].isin(abc_selected)
    ]["material_id"].tolist()
    proposals_df = proposals_df[proposals_df["material_id"].isin(valid_materials)]


# KPI row
kpi_cards.render(proposals_df, materials_df)
st.divider()


# Tabs
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Overview",
    "📋 Proposals",
    "🔍 Drill-down",
    "📈 Forecast",
    "⚖ As-Is vs To-Be",
    "💬 AI Copilot",
])

with tab1:
    overview_tab.render(proposals_df, materials_df)

with tab2:
    proposals_tab.render(proposals_df, materials_df)

with tab3:
    drilldown_tab.render(proposals_df, materials_df)

with tab4:
    forecast_tab.render(proposals_df, materials_df)

with tab5:
    validation_tab.render(proposals_df, materials_df)

with tab6:
    # Copilot needs a fresh repo (not the cached DataFrames)
    _copilot_repo = Repository()
    try:
        copilot_tab.render(_copilot_repo)
    finally:
        _copilot_repo.close()


# Footer
st.divider()
st.caption(
    "Replenishment Agent v1.0 — BDI architecture · MRP + Rules engine · "
    "Built for Athens MBA διπλωματική εργασία"
)

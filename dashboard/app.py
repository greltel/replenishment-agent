"""
Streamlit dashboard for the Replenishment Agent.

Run with:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# Add project root to path so `src.` imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import config, PROJECT_ROOT
from src.data_layer.repository import Repository
from src.rules.engine import RulesEngine
from src.utils.as_of_date import get_effective_today, reset_cache
from dashboard import theme
from dashboard.theme import fmt_int, fmt_eur, fmt_date, kpi_tile
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
    page_title="Ευφυής Πράκτορας Αναπλήρωσης — Athens MBA",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject_css()


# ============================================================
# Data loading (cached)
# ============================================================
@st.cache_data(ttl=120)
def load_proposals() -> pd.DataFrame:
    repo = Repository()
    try:
        df = pd.read_sql("SELECT * FROM proposals ORDER BY proposed_date", repo.engine)
        if not df.empty:
            df["proposed_date"] = pd.to_datetime(df["proposed_date"])
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


@st.cache_data(ttl=300)
def load_dataset_summary() -> dict:
    repo = Repository()
    try:
        summary = repo.get_dataset_summary()
    except Exception:
        summary = {}
    repo.close()
    reset_cache()
    summary["as_of"] = get_effective_today()
    return summary


def _refresh_caches():
    load_proposals.clear()
    load_materials.clear()
    load_dataset_summary.clear()
    for fn in (drilldown_tab._material_choices, forecast_tab._material_choices):
        try:
            fn.clear()
        except Exception:
            pass


# ============================================================
# Sidebar
# ============================================================
materials_df = load_materials()
summary = load_dataset_summary()
as_of: date = summary.get("as_of") or date.today()

with st.sidebar:
    st.markdown("### 📦 Replenishment Agent")
    st.caption("Athens MBA — Διπλωματική Εργασία")
    st.divider()

    st.markdown("**Δεδομένα**")
    st.markdown(
        f"- Υλικά: **{fmt_int(summary.get('n_materials', 0))}**\n"
        f"- Κινήσεις: **{fmt_int(summary.get('n_movements', 0))}**\n"
        f"- Ανοιχτές παραγγελίες: **{fmt_int(summary.get('n_open_pos', 0))}**\n"
        f"- Ιστορικό: {fmt_date(summary.get('first_movement'))} → "
        f"{fmt_date(summary.get('last_movement'))}\n"
        f"- Ημερομηνία αναφοράς: **{fmt_date(as_of)}**"
    )
    st.divider()

    st.markdown("**Φίλτρα**")
    if not materials_df.empty:
        abc_options = [c for c in theme.ABC_ORDER
                       if c in set(materials_df["abc_class"].dropna())]
        abc_selected = st.multiselect("Κλάση ABC", options=abc_options, default=abc_options)
        only_urgent = st.toggle("Μόνο επείγουσες προτάσεις", value=False)
    else:
        abc_selected, only_urgent = [], False

    st.divider()
    st.markdown("**Ενέργειες**")
    if st.button("🔄 Ανανέωση δεδομένων", **theme.wide_kwargs(st.button)):
        _refresh_caches()
        st.rerun()

    if st.button("🤖 Εκτέλεση πράκτορα", **theme.wide_kwargs(st.button),
                 help="Τρέχει έναν πλήρη κύκλο BDI (perceive → deliberate → act) "
                      "και αποθηκεύει νέες προτάσεις."):
        with st.spinner("Ο πράκτορας σκέφτεται…"):
            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "run_agent.py")],
                capture_output=True, text=True, cwd=PROJECT_ROOT,
            )
        if result.returncode == 0:
            st.success("Ο κύκλος ολοκληρώθηκε — νέες προτάσεις αποθηκεύτηκαν.")
            _refresh_caches()
            st.rerun()
        else:
            st.error(f"Σφάλμα εκτέλεσης:\n{result.stderr[-600:]}")

    st.divider()
    with st.expander("Ενεργοί κανόνες", expanded=False):
        try:
            rules = RulesEngine().list_rules()
            for r in rules:
                label = theme.RULE_LABELS_EL.get(r["name"], r["name"])
                st.markdown(f"`{r['priority']:>2}` **{r['name']}**  \n"
                            f"<span style='color:{theme.TEXT_SECONDARY};font-size:.8rem'>"
                            f"{label}</span>", unsafe_allow_html=True)
        except Exception as e:  # pragma: no cover
            st.caption(f"(δεν φορτώθηκαν: {e})")

    st.caption(f"Ορίζοντας σχεδιασμού: {config.planning_horizon_days} ημέρες · "
               f"Επίπεδο εξυπηρέτησης-στόχος: {config.default_service_level:.0%}")


# ============================================================
# Header
# ============================================================
proposals_df = load_proposals()

n_urgent_all = (int(proposals_df.loc[proposals_df["expedite"] == 1, "material_id"].nunique())
                if not proposals_df.empty else 0)
st.markdown(
    f"""
    <div class="ra-header">
      <div>
        <div class="ra-title">Ευφυής Πράκτορας Αναπλήρωσης Αποθεμάτων</div>
        <div class="ra-subtitle">Αρχιτεκτονική BDI · Δυναμικό MRP · Επιχειρησιακοί κανόνες ·
        Διασύνδεση SAP ERP</div>
        <div class="ra-chips">
          <span class="ra-chip">Ημερομηνία αναφοράς <b>{fmt_date(as_of)}</b></span>
          <span class="ra-chip">Ορίζοντας σχεδιασμού <b>{config.planning_horizon_days} ημ.</b></span>
          <span class="ra-chip">Υλικά <b>{fmt_int(summary.get('n_materials', 0))}</b></span>
          <span class="ra-chip">Ιστορικό <b>{fmt_date(summary.get('first_movement'))} – {fmt_date(summary.get('last_movement'))}</b></span>
          <span class="ra-chip">Επείγοντα υλικά <b>{fmt_int(n_urgent_all)}</b></span>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Apply filters at top level
if not proposals_df.empty and not materials_df.empty:
    if abc_selected:
        valid = materials_df[materials_df["abc_class"].isin(abc_selected)]["material_id"]
        proposals_df = proposals_df[proposals_df["material_id"].isin(set(valid))]
    if only_urgent:
        proposals_df = proposals_df[proposals_df["expedite"] == 1]


# KPI row
kpi_cards.render(proposals_df, materials_df, summary)


# Tabs
tab_labels = [
    "📊 Επισκόπηση",
    "📋 Προτάσεις",
    "🔍 Ανάλυση υλικού",
    "📈 Πρόβλεψη ζήτησης",
    "⚖️ As-Is vs To-Be",
    "💬 AI Copilot",
]
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(tab_labels)

with tab1:
    overview_tab.render(proposals_df, materials_df, as_of)

with tab2:
    proposals_tab.render(proposals_df, materials_df)

with tab3:
    drilldown_tab.render(proposals_df, materials_df, as_of)

with tab4:
    forecast_tab.render(proposals_df, materials_df, as_of)

with tab5:
    validation_tab.render(proposals_df, materials_df)

with tab6:
    # Copilot needs a live repo (not the cached DataFrames)
    _copilot_repo = Repository()
    try:
        copilot_tab.render(_copilot_repo)
    finally:
        _copilot_repo.close()


# Footer
st.divider()
st.caption(
    "Replenishment Agent v1.1 — BDI architecture · MRP engine (LFL/FOQ/EOQ/POQ/WW) · "
    "7 επιχειρησιακοί κανόνες · Athens MBA (ΟΠΑ | ΕΜΠ) — Γεώργιος Δράκος, "
    "επιβλέπων: Σωτήρης Γκαγιαλής"
)

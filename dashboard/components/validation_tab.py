"""
Validation tab — As-Is vs To-Be comparison from backtest.

Loads the validation_report.csv produced by scripts/run_validation.py.
Now supports decomposed cost analysis, scenario picker, and ABC drill-down.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import PROJECT_ROOT


def _load_report(filename: str = "validation_report.csv") -> pd.DataFrame | None:
    """Load a validation report by filename."""
    candidates = [
        PROJECT_ROOT / filename,
        PROJECT_ROOT / "scripts" / filename,
    ]
    for p in candidates:
        if p.exists():
            return pd.read_csv(p)
    return None


def _list_reports() -> list[str]:
    """Find all validation_*.csv files in the project root."""
    reports = []
    for p in PROJECT_ROOT.glob("validation_report*.csv"):
        reports.append(p.name)
    return sorted(reports)


# ─── Pretty labels ───
LABELS = {
    "cycle_service_level_pct": "Service Level (%)",
    "fill_rate_pct":           "Fill Rate (%)",
    "holding_cost_eur":        "Holding Cost (€)",
    "stockout_days":           "Stockout days",
    "inventory_turns":         "Inventory turns",
    "avg_inventory_eur":       "Avg Inventory Value (€)",
    "n_orders":                "Number of Orders",
    "avg_order_size":          "Avg Order Size",
    "capital_cost_eur":        "Capital Cost (€)",
    "warehouse_cost_eur":      "Warehouse Cost (€)",
    "obsolescence_cost_eur":   "Obsolescence Cost (€)",
    "insurance_cost_eur":      "Insurance Cost (€)",
    "stockout_cost_eur":       "Stockout Cost (€)",
    "lost_sales_eur":          "Lost Sales (€)",
    "expedite_premium_eur":    "Expedite Premium (€)",
    "total_cost_of_ownership": "Total Cost of Ownership (€)",
    "days_of_cover_avg":       "Days of Cover (avg)",
}


def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    st.subheader("As-Is vs To-Be — Backtest Comparison")

    # Report selector
    available_reports = _list_reports()
    if not available_reports:
        st.warning(
            "No validation report found. Run the backtest first:\n\n"
            "```\n"
            "python scripts/run_validation.py --window-days 60\n"
            "python scripts/run_validation.py --all-scenarios\n"
            "python scripts/run_validation.py --sensitivity\n"
            "```"
        )
        return

    selected = st.selectbox(
        "Validation report",
        available_reports,
        help="Pick a report to display. Multiple reports are produced when "
             "running --all-scenarios or --sensitivity.",
    )

    df = _load_report(selected)
    if df is None or df.empty:
        st.error(f"Could not load {selected}")
        return

    # ─── Branch by report type ───
    is_sensitivity = "variation" in df.columns
    is_cross_scenario = "scenario" in df.columns and "metric" not in df.columns

    if is_sensitivity:
        _render_sensitivity(df)
    elif is_cross_scenario:
        _render_cross_scenario(df)
    else:
        _render_single_scenario(df)


# ============================================================
# Single-scenario report (the typical case)
# ============================================================
def _render_single_scenario(df: pd.DataFrame) -> None:
    df["metric_label"] = df["metric"].map(LABELS).fillna(df["metric"])

    # ─── Top-line takeaways ───
    st.markdown("### Συνοπτικά αποτελέσματα")

    holding_row = df[df["metric"] == "holding_cost_eur"]
    csl_row = df[df["metric"] == "cycle_service_level_pct"]
    stockout_row = df[df["metric"] == "stockout_days"]
    tco_row = df[df["metric"] == "total_cost_of_ownership"]

    col_a, col_b, col_c, col_d = st.columns(4)
    if not csl_row.empty:
        delta = csl_row["delta_abs"].iloc[0]
        col_a.metric("Service Level Δ", f"{delta:+.2f}pp",
                     delta=f"{csl_row['delta_pct'].iloc[0]:+.1f}%" if pd.notna(csl_row['delta_pct'].iloc[0]) else None)
    if not holding_row.empty:
        delta = holding_row["delta_abs"].iloc[0]
        col_b.metric("Holding Cost Δ", f"€{delta:+,.0f}",
                     delta=f"{holding_row['delta_pct'].iloc[0]:+.1f}%" if pd.notna(holding_row['delta_pct'].iloc[0]) else None,
                     delta_color="inverse")
    if not stockout_row.empty:
        delta = stockout_row["delta_abs"].iloc[0]
        col_c.metric("Stockouts Δ", f"{delta:+.0f} days",
                     delta_color="inverse")
    if not tco_row.empty:
        delta = tco_row["delta_abs"].iloc[0]
        col_d.metric("TCO Δ", f"€{delta:+,.0f}",
                     delta=f"{tco_row['delta_pct'].iloc[0]:+.1f}%" if pd.notna(tco_row['delta_pct'].iloc[0]) else None,
                     delta_color="inverse")

    # ─── Service-level table ───
    st.markdown("### KPIs Επιπέδου Εξυπηρέτησης")
    sl_metrics = ["cycle_service_level_pct", "fill_rate_pct", "stockout_days"]
    _render_metric_table(df, sl_metrics)

    # ─── Cost decomposition ───
    st.markdown("### Ανάλυση Κόστους (€)")

    cost_metrics = [
        "holding_cost_eur", "capital_cost_eur", "warehouse_cost_eur",
        "obsolescence_cost_eur", "insurance_cost_eur",
        "stockout_cost_eur", "lost_sales_eur", "expedite_premium_eur",
        "total_cost_of_ownership", "avg_inventory_eur",
    ]
    _render_metric_table(df, cost_metrics)

    # ─── Cost breakdown chart ───
    breakdown_metrics = ["capital_cost_eur", "warehouse_cost_eur",
                         "obsolescence_cost_eur", "insurance_cost_eur"]
    breakdown_df = df[df["metric"].isin(breakdown_metrics)].copy()

    if not breakdown_df.empty and breakdown_df["as_is"].sum() > 0:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=breakdown_df["metric_label"], y=breakdown_df["as_is"],
            name="As-Is", marker_color="#cbd5e0",
        ))
        fig.add_trace(go.Bar(
            x=breakdown_df["metric_label"], y=breakdown_df["to_be"],
            name="To-Be (Agent)", marker_color="#1a365d",
        ))
        fig.update_layout(
            barmode="group", height=400,
            title="Διάσπαση Holding Cost",
            yaxis_title="€",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ─── Operational ───
    st.markdown("### Επιχειρησιακά KPIs")
    op_metrics = ["inventory_turns", "n_orders", "avg_order_size",
                  "days_of_cover_avg"]
    _render_metric_table(df, op_metrics)

    st.caption(
        "Τα νούμερα προέρχονται από προσομοίωση πάνω στα ιστορικά δεδομένα. "
        "Τα κόστη υπολογίζονται με μεθοδολογία Silver-Pyke-Peterson (1998) — "
        "διάσπαση holding rate σε capital + warehouse + obsolescence + insurance "
        "+ shrinkage. Stockout cost = lost sales + expedite premium."
    )


def _render_metric_table(df: pd.DataFrame, metric_names: list[str]) -> None:
    sub = df[df["metric"].isin(metric_names)].copy()
    if sub.empty:
        return
    display = sub[["metric_label", "as_is", "to_be", "delta_abs",
                   "delta_pct", "direction", "significant"]].copy()
    display.columns = ["Metric", "As-Is", "To-Be (Agent)",
                       "Δ", "Δ%", "Direction", "Σημαντικό"]
    st.dataframe(display, use_container_width=True, hide_index=True)


# ============================================================
# Cross-scenario report (--all-scenarios)
# ============================================================
def _render_cross_scenario(df: pd.DataFrame) -> None:
    st.markdown("### Σύγκριση Σεναρίων Κόστους")
    st.caption(
        "Τρία σενάρια: conservative (~12% holding rate), "
        "realistic (~20%), aggressive (~28%). Ο agent αξιολογείται "
        "ως προς το τι θα έπραττε σε κάθε υπόθεση κόστους."
    )

    st.dataframe(df, use_container_width=True, hide_index=True)

    # Bar chart of TCO across scenarios
    if "total_cost_of_ownership" in df.columns:
        fig = go.Figure()
        # Separate As-Is vs To-Be per scenario
        for scen_type, color in [("asis", "#cbd5e0"), ("tobe", "#1a365d")]:
            mask = df["scenario"].str.endswith(f"_{scen_type}")
            sub = df[mask]
            scen_names = sub["scenario"].str.replace(f"_{scen_type}", "")
            fig.add_trace(go.Bar(
                x=scen_names,
                y=sub["total_cost_of_ownership"],
                name="As-Is" if scen_type == "asis" else "To-Be (Agent)",
                marker_color=color,
            ))
        fig.update_layout(
            barmode="group", height=400,
            title="Total Cost of Ownership ανά σενάριο",
            yaxis_title="€",
        )
        st.plotly_chart(fig, use_container_width=True)


# ============================================================
# Sensitivity report (--sensitivity)
# ============================================================
def _render_sensitivity(df: pd.DataFrame) -> None:
    st.markdown("### Ανάλυση Ευαισθησίας")
    st.caption(
        "Πώς αλλάζει το TCO όταν διαταράσσουμε ±20% τα lead times, "
        "τη ζήτηση, ή το holding rate. Robust αποτέλεσμα = το savings "
        "παραμένει σταθερό κατά μέγεθος ανεξαρτήτως διατάραξης."
    )

    st.dataframe(df, use_container_width=True, hide_index=True)

    if "tco_savings" in df.columns:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df["variation"], y=df["tco_savings"],
            marker_color=["#1a365d" if v == "base" else "#3182ce"
                          for v in df["variation"]],
        ))
        fig.update_layout(
            height=400,
            title="TCO Savings ανά διατάραξη",
            yaxis_title="Εξοικονόμηση (€)",
            xaxis_title="Διατάραξη",
        )
        st.plotly_chart(fig, use_container_width=True)

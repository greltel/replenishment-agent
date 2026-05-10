"""
Validation tab — As-Is vs To-Be comparison from backtest.

Loads the validation_report.csv produced by scripts/run_validation.py.
If absent, prompts the user to run the backtest.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import PROJECT_ROOT


def _load_report() -> pd.DataFrame | None:
    """Load the most recent validation report."""
    candidates = [
        PROJECT_ROOT / "validation_report.csv",
        PROJECT_ROOT / "scripts" / "validation_report.csv",
    ]
    for p in candidates:
        if p.exists():
            return pd.read_csv(p)
    return None


def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    st.subheader("As-Is vs To-Be — Backtest Comparison")

    df = _load_report()

    if df is None:
        st.warning(
            "No validation report found. Run the backtest first:\n\n"
            "```\npython scripts/run_validation.py --window-days 90\n```"
        )
        return

    # Pretty metric labels
    label_map = {
        "cycle_service_level_pct": "Service Level (%)",
        "fill_rate_pct":           "Fill Rate (%)",
        "holding_cost_eur":        "Holding Cost (€)",
        "stockout_days":           "Stockout days",
        "inventory_turns":         "Inventory turns",
        "avg_inventory_eur":       "Avg inventory value (€)",
        "n_orders":                "Number of orders",
        "avg_order_size":          "Avg order size",
    }
    df["metric_label"] = df["metric"].map(label_map).fillna(df["metric"])

    # Format display
    display_df = df[["metric_label", "as_is", "to_be", "delta_abs", "delta_pct"]].copy()
    display_df.columns = ["Metric", "As-Is", "To-Be (Agent)", "Δ", "Δ%"]
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # ---------- Bar chart comparison for key metrics ----------
    st.subheader("Visual comparison")

    key_metrics = [
        "cycle_service_level_pct", "fill_rate_pct",
        "holding_cost_eur", "stockout_days",
    ]
    chart_df = df[df["metric"].isin(key_metrics)].copy()
    chart_df["metric_label"] = chart_df["metric"].map(label_map)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=chart_df["metric_label"], y=chart_df["as_is"],
        name="As-Is", marker_color="#cbd5e0",
    ))
    fig.add_trace(go.Bar(
        x=chart_df["metric_label"], y=chart_df["to_be"],
        name="To-Be (Agent)", marker_color="#1a365d",
    ))
    fig.update_layout(
        barmode="group",
        height=400,
        yaxis_title="Value",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ---------- Highlight savings ----------
    st.subheader("Key takeaways")

    holding_row = df[df["metric"] == "holding_cost_eur"]
    csl_row = df[df["metric"] == "cycle_service_level_pct"]
    stockout_row = df[df["metric"] == "stockout_days"]

    c1, c2, c3 = st.columns(3)
    if not csl_row.empty:
        delta = csl_row["delta_abs"].iloc[0]
        c1.metric("Service Level Δ", f"{delta:+.2f}pp",
                   delta=f"{csl_row['delta_pct'].iloc[0]:+.1f}%" if csl_row['delta_pct'].iloc[0] else None)

    if not holding_row.empty:
        delta = holding_row["delta_abs"].iloc[0]
        c2.metric("Holding cost Δ", f"€{delta:+,.0f}",
                   delta=f"{holding_row['delta_pct'].iloc[0]:+.1f}%" if holding_row['delta_pct'].iloc[0] else None,
                   delta_color="inverse")

    if not stockout_row.empty:
        delta = stockout_row["delta_abs"].iloc[0]
        c3.metric("Stockouts Δ", f"{delta:+.0f} days",
                   delta=f"{stockout_row['delta_pct'].iloc[0]:+.1f}%" if stockout_row['delta_pct'].iloc[0] else None,
                   delta_color="inverse")

    st.caption(
        "Σημείωση: Τα νούμερα προέρχονται από προσομοίωση πάνω στα ιστορικά δεδομένα. "
        "Ένας περιορισμός είναι ότι η ζήτηση κατά τη διάρκεια του παραθύρου θεωρείται "
        "δεδομένη — δεν λαμβάνεται υπόψη η αλληλεπίδραση πελάτη-εταιρείας."
    )

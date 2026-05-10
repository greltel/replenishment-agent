"""
Drill-down tab — per-material analysis.

For a chosen material:
  • Master data summary
  • Stock projection chart over the planning horizon
  • Full MRP grid (gross/scheduled/POH/net/planned)
  • Consumption history chart
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from src.data_layer.repository import Repository
from src.mrp.engine import MRPEngine
from src.utils.forecasting import forecast


@st.cache_data(ttl=300)
def _material_choices() -> list[str]:
    repo = Repository()
    df = pd.read_sql("SELECT material_id FROM materials ORDER BY material_id", repo.engine)
    repo.close()
    return df["material_id"].tolist()


def _compute_mrp_for_material(material_id: str, horizon: int = 60) -> tuple[pd.DataFrame, dict]:
    """Run the MRP engine on demand for a single material — returns (mrp_df, master_dict)."""
    repo = Repository()
    material = repo.get_material(material_id)
    if material is None:
        repo.close()
        return pd.DataFrame(), {}

    current_stock = repo.get_current_stock(material_id)
    open_orders = repo.get_open_pos(material_id)
    history = repo.get_consumption_history(material_id, days=365)

    demand = forecast(history, horizon_days=horizon, method="moving_average")

    mrp = MRPEngine(horizon_days=horizon)
    df = mrp.calculate(
        material=material,
        current_stock=current_stock,
        open_orders=open_orders,
        demand=demand,
    )

    master = {
        "material_id":   material.material_id,
        "abc_class":     material.abc_class,
        "material_type": material.material_type,
        "uom":           material.uom,
        "lot_sizing":    material.lot_sizing,
        "lead_time":     material.lead_time_days,
        "safety_stock":  material.safety_stock,
        "moq":           material.moq,
        "standard_cost": material.standard_cost,
        "current_stock": current_stock,
        "open_pos_count": len(open_orders),
    }

    repo.close()
    return df, master


def _consumption_history_df(material_id: str) -> pd.DataFrame:
    repo = Repository()
    movements = repo.get_consumption_history(material_id, days=365)
    repo.close()
    if not movements:
        return pd.DataFrame()
    df = pd.DataFrame([
        {"date": m.posting_date, "quantity": abs(m.quantity)}
        for m in movements
    ])
    df["date"] = pd.to_datetime(df["date"])
    return df


def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    """Render the drill-down tab."""
    materials_list = _material_choices()
    if not materials_list:
        st.warning("No materials in DB. Run ETL first.")
        return

    # Default: pick first expedite material if available
    default_idx = 0
    if not proposals.empty:
        expedite = proposals[proposals["expedite"] == 1]
        if not expedite.empty:
            first_expedite = expedite.iloc[0]["material_id"]
            if first_expedite in materials_list:
                default_idx = materials_list.index(first_expedite)

    selected = st.selectbox("Select material", materials_list, index=default_idx)
    if not selected:
        return

    horizon = st.slider("Planning horizon (days)", 14, 120, 60, step=7)

    # ---------- Run MRP for this material ----------
    with st.spinner("Computing MRP..."):
        mrp_df, master = _compute_mrp_for_material(selected, horizon=horizon)

    if mrp_df.empty:
        st.error(f"No data for {selected}")
        return

    # ---------- Master data ----------
    st.subheader(f"Master data — {master['material_id']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ABC class",     master["abc_class"] or "-")
    c1.metric("Material type", master["material_type"] or "-")
    c2.metric("Lot sizing",    master["lot_sizing"] or "-")
    c2.metric("Lead time",     f"{master['lead_time']} days")
    c3.metric("Safety stock",  f"{master['safety_stock']:.0f}")
    c3.metric("MOQ",           f"{master['moq']:.0f}")
    c4.metric("Current stock", f"{master['current_stock']:.0f}")
    c4.metric("Standard cost", f"€{master['standard_cost']:.2f}")

    st.divider()

    # ---------- Stock projection chart ----------
    st.subheader("Stock projection")

    fig = go.Figure()

    # Projected on-hand
    fig.add_trace(go.Scatter(
        x=mrp_df["period"], y=mrp_df["projected_on_hand"],
        mode="lines+markers", name="Projected on-hand",
        line=dict(color="#1a365d", width=3),
    ))

    # Safety stock line
    fig.add_hline(
        y=master["safety_stock"],
        line_dash="dash", line_color="#e53e3e",
        annotation_text="Safety Stock",
    )

    # Mark planned receipts
    receipt_rows = mrp_df[mrp_df["planned_receipt"] > 0]
    if not receipt_rows.empty:
        fig.add_trace(go.Scatter(
            x=receipt_rows["period"],
            y=receipt_rows["projected_on_hand"],
            mode="markers",
            name="Planned receipts",
            marker=dict(symbol="triangle-up", size=15, color="#38a169"),
        ))

    fig.update_layout(
        height=400,
        xaxis_title="Date",
        yaxis_title=f"Quantity ({master['uom']})",
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ---------- MRP grid ----------
    with st.expander("📋 Full MRP grid"):
        display_df = mrp_df.copy()
        display_df["period"] = pd.to_datetime(display_df["period"]).dt.strftime("%Y-%m-%d")
        for col in ["gross_requirement", "scheduled_receipt",
                     "projected_on_hand", "net_requirement", "planned_receipt"]:
            display_df[col] = display_df[col].round(1)
        if "planned_release" in display_df.columns:
            display_df["planned_release"] = pd.to_datetime(
                display_df["planned_release"], errors="coerce"
            ).dt.strftime("%Y-%m-%d").fillna("")
        st.dataframe(display_df, use_container_width=True, height=300, hide_index=True)

    # ---------- Consumption history ----------
    st.subheader("Consumption history (last 365 days)")
    history_df = _consumption_history_df(selected)
    if history_df.empty:
        st.info("No consumption history.")
        return

    # Resample weekly for cleaner chart
    weekly = history_df.set_index("date")["quantity"].resample("W").sum().reset_index()
    fig = px.bar(weekly, x="date", y="quantity",
                  title="Weekly consumption",
                  color_discrete_sequence=["#2c7a7b"])
    fig.update_layout(height=300)
    st.plotly_chart(fig, use_container_width=True)

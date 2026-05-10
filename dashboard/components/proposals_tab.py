"""Proposals tab — sortable table with filters and Excel export."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st


def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    if proposals.empty:
        st.warning("No proposals to display.")
        return

    df = proposals.merge(
        materials[["material_id", "abc_class", "material_type", "lead_time_days"]],
        on="material_id", how="left",
    )

    # ---------- Filters ----------
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        expedite_only = st.checkbox("Expedite only", value=False)
    with c2:
        min_qty = st.number_input("Min qty", value=0, step=10)
    with c3:
        search = st.text_input("Search material ID")

    if expedite_only:
        df = df[df["expedite"] == 1]
    df = df[df["proposed_qty"] >= min_qty]
    if search:
        df = df[df["material_id"].str.contains(search, case=False, na=False)]

    # ---------- Display table ----------
    display_cols = [
        "material_id", "abc_class", "proposed_date", "proposed_qty",
        "estimated_cost", "supplier_id", "lead_time_days",
        "rule_triggered", "expedite", "confidence",
    ]
    display_df = df[[c for c in display_cols if c in df.columns]].copy()

    # Format
    if "proposed_qty" in display_df.columns:
        display_df["proposed_qty"] = display_df["proposed_qty"].round(0).astype(int)
    if "estimated_cost" in display_df.columns:
        display_df["estimated_cost"] = display_df["estimated_cost"].round(2)
    if "expedite" in display_df.columns:
        display_df["expedite"] = display_df["expedite"].map({1: "🔥", 0: ""})

    st.write(f"**Showing {len(display_df)} proposals**")
    st.dataframe(display_df, use_container_width=True, height=500, hide_index=True)

    # ---------- Export ----------
    c1, c2 = st.columns(2)
    with c1:
        csv = display_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇ Download CSV",
            csv,
            file_name="replenishment_proposals.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        # Excel
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            display_df.to_excel(writer, sheet_name="Proposals", index=False)
        st.download_button(
            "⬇ Download Excel",
            buffer.getvalue(),
            file_name="replenishment_proposals.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

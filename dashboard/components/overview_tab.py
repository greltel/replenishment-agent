"""Overview tab — visual summaries of agent's proposals."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st


def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    if proposals.empty:
        st.warning("No proposals to display.")
        return

    df = proposals.merge(
        materials[["material_id", "abc_class", "lot_sizing", "lead_time_days"]],
        on="material_id", how="left",
    )

    # ---------- Row 1: counts by ABC and timing ----------
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Proposals by ABC class")
        abc_counts = (df.groupby("abc_class")["proposal_id"].count()
                       .reindex(["A", "B", "C"]).fillna(0).reset_index())
        abc_counts.columns = ["ABC class", "Proposals"]
        fig = px.bar(abc_counts, x="ABC class", y="Proposals",
                      color="ABC class",
                      color_discrete_map={"A": "#1a365d", "B": "#2c7a7b", "C": "#cbd5e0"})
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Estimated cost by ABC class")
        cost_by_abc = df.groupby("abc_class")["estimated_cost"].sum().reset_index()
        fig = px.pie(cost_by_abc, names="abc_class", values="estimated_cost",
                      color="abc_class",
                      color_discrete_map={"A": "#1a365d", "B": "#2c7a7b", "C": "#cbd5e0"})
        st.plotly_chart(fig, use_container_width=True)

    # ---------- Row 2: timing heatmap ----------
    st.subheader("Proposals timeline (next 60 days)")
    df["proposed_date"] = pd.to_datetime(df["proposed_date"])
    df["week"] = df["proposed_date"].dt.strftime("W%U")

    heat = (df.groupby(["abc_class", "week"])["proposed_qty"].sum()
              .reset_index())
    if not heat.empty:
        fig = px.density_heatmap(heat, x="week", y="abc_class", z="proposed_qty",
                                   color_continuous_scale="Blues",
                                   title="Total quantity by week × ABC class")
        st.plotly_chart(fig, use_container_width=True)

    # ---------- Row 3: rules triggered ----------
    st.subheader("Rules triggered")
    if "rule_triggered" in df.columns:
        # Split rules (each proposal may have multiple)
        rules_series = df["rule_triggered"].dropna().str.split(" | ").explode().str.strip()
        rules_series = rules_series[rules_series != ""]

        if not rules_series.empty:
            rule_counts = rules_series.value_counts().reset_index()
            rule_counts.columns = ["Rule", "Count"]
            fig = px.bar(rule_counts, x="Count", y="Rule", orientation="h",
                          color="Count", color_continuous_scale="Teal")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No rules triggered.")

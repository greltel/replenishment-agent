"""Proposals tab — the planner's worklist: filters, table, Excel/CSV export."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from dashboard import theme
from dashboard.theme import fmt_int, fmt_eur, section


COLUMNS_EL = {
    "material_id":    "Υλικό",
    "description":    "Περιγραφή",
    "abc_class":      "ABC",
    "material_type":  "Τύπος",
    "proposed_date":  "Ημ/νία παραγγελίας",
    "proposed_qty":   "Ποσότητα",
    "estimated_cost": "Εκτ. κόστος (€)",
    "supplier_id":    "Προμηθευτής",
    "lead_time_days": "Lead time (ημ.)",
    "lot_sizing":     "Lot sizing",
    "rule_triggered": "Κανόνες",
    "urgent":         "Επείγον",
    "confidence":     "Εμπιστοσύνη",
}


def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    if proposals.empty:
        st.warning("Δεν υπάρχουν προτάσεις για εμφάνιση.")
        return

    df = proposals.merge(
        materials[["material_id", "description", "abc_class", "material_type",
                   "lead_time_days", "lot_sizing"]],
        on="material_id", how="left",
    )
    df["proposed_date"] = pd.to_datetime(df["proposed_date"])

    section("Λίστα εργασιών planner",
            "Κάθε γραμμή είναι μία πρόταση παραγγελίας: πότε να εκδοθεί, πόσο, "
            "και ποιοι κανόνες την επηρέασαν. Ταξινόμηση με κλικ στις στήλες.")

    # ---------- Filters ----------
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.4, 2.2])
    with c1:
        expedite_only = st.checkbox("Μόνο επείγουσες", value=False, key="prop_urgent")
    with c2:
        min_qty = st.number_input("Ελάχ. ποσότητα", value=0, step=10, key="prop_minqty")
    with c3:
        max_date = df["proposed_date"].max().date()
        min_date = df["proposed_date"].min().date()
        until = st.date_input("Έως ημερομηνία", value=max_date,
                              min_value=min_date, max_value=max_date, key="prop_until")
    with c4:
        search = st.text_input("Αναζήτηση κωδικού ή περιγραφής", key="prop_search")

    if expedite_only:
        df = df[df["expedite"] == 1]
    df = df[df["proposed_qty"] >= min_qty]
    df = df[df["proposed_date"].dt.date <= until]
    if search:
        mask_id = df["material_id"].str.contains(search, case=False, na=False)
        mask_desc = df["description"].fillna("").str.contains(search, case=False, na=False)
        df = df[mask_id | mask_desc]

    df = df.sort_values(["expedite", "proposed_date"], ascending=[False, True])

    # ---------- Display table ----------
    display = pd.DataFrame({
        "urgent":         df["expedite"].map({1: "🔴 Επείγον", 0: ""}),
        "material_id":    df["material_id"],
        "description":    df["description"].fillna(""),
        "abc_class":      df["abc_class"],
        "proposed_date":  df["proposed_date"].dt.date,
        "proposed_qty":   df["proposed_qty"].round(0).astype(int),
        "estimated_cost": df["estimated_cost"].round(2),
        "supplier_id":    df["supplier_id"],
        "lead_time_days": df["lead_time_days"],
        "lot_sizing":     df["lot_sizing"],
        "rule_triggered": df["rule_triggered"].fillna("—"),
    }).rename(columns=COLUMNS_EL)

    k1, k2, k3 = st.columns(3)
    k1.metric("Προτάσεις στη λίστα", fmt_int(len(display)))
    k2.metric("Συνολική ποσότητα", fmt_int(float(df["proposed_qty"].sum())))
    k3.metric("Συνολικό εκτ. κόστος", fmt_eur(float(df["estimated_cost"].sum())))

    col_cfg = {}
    if hasattr(st, "column_config"):
        col_cfg = {
            COLUMNS_EL["proposed_date"]: st.column_config.DateColumn(format="DD.MM.YYYY"),
            COLUMNS_EL["proposed_qty"]: st.column_config.NumberColumn(format="%d"),
            COLUMNS_EL["estimated_cost"]: st.column_config.NumberColumn(format="€ %.2f"),
            COLUMNS_EL["lead_time_days"]: st.column_config.NumberColumn(format="%d"),
        }
    theme.dataframe(display, hide_index=True, height=520, column_config=col_cfg)

    # ---------- Export ----------
    e1, e2 = st.columns(2)
    with e1:
        csv = display.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇ Λήψη CSV", csv, file_name="protaseis_anaplirosis.csv",
                           mime="text/csv", **theme.wide_kwargs(st.download_button))
    with e2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            display.to_excel(writer, sheet_name="Proposals", index=False)
        st.download_button(
            "⬇ Λήψη Excel", buffer.getvalue(), file_name="protaseis_anaplirosis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            **theme.wide_kwargs(st.download_button),
        )

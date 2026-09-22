"""
Demand Forecast tab.

Visualises historical demand for a material and compares three forecasting
methods (simple average, moving average, exponential smoothing) with
walk-forward validation (Bergmeir & Benítez 2012). Metrics: MAE, RMSE, MAPE,
Bias. The best method per material is recommended by MAPE.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data_layer.repository import Repository
from src.utils.forecasting import (
    consumption_to_daily_series,
    simple_average,
    moving_average,
    exponential_smoothing,
    compare_methods,
    best_method,
)
from dashboard import theme
from dashboard.theme import fmt_int, fmt_num, section, plotly


METHOD_LABELS = {
    "simple_average":         "Απλός μέσος",
    "moving_average":         "Κινητός μέσος (30 ημ.)",
    "exponential_smoothing":  "Εκθετική εξομάλυνση (α=0,3)",
}

METHOD_COLORS = {
    "simple_average":         theme.NEUTRAL_DARK,
    "moving_average":         theme.ACCENT,
    "exponential_smoothing":  theme.ORANGE,
}


@st.cache_data(ttl=300)
def _material_choices() -> list[tuple[str, str]]:
    """Return (material_id, description) tuples, sorted by ID."""
    repo = Repository()
    df = pd.read_sql(
        "SELECT material_id, COALESCE(description, '') AS description "
        "FROM materials ORDER BY material_id",
        repo.engine,
    )
    repo.close()
    return list(zip(df["material_id"], df["description"]))


@st.cache_data(ttl=300)
def _top_consumer() -> str | None:
    """Material with the largest consumption in the history (a rich series)."""
    repo = Repository()
    try:
        df = pd.read_sql(
            "SELECT material_id, SUM(ABS(quantity)) AS q FROM movements "
            "WHERE movement_type IN ('261','201','281') GROUP BY material_id "
            "ORDER BY q DESC LIMIT 1", repo.engine)
    finally:
        repo.close()
    return str(df["material_id"].iloc[0]) if not df.empty else None


def _default_material_index(materials_list: list[tuple[str, str]], materials: pd.DataFrame) -> int:
    ids = [m[0] for m in materials_list]
    top = _top_consumer()
    return ids.index(top) if top in ids else 0


def _load_history(material_id: str, as_of: date, days_back: int = 365) -> pd.Series:
    """Load consumption history for one material as a daily Series."""
    repo = Repository()
    movements = repo.get_consumption_history(material_id, days=days_back, as_of=as_of)
    repo.close()
    return consumption_to_daily_series(movements, horizon_back_days=days_back, as_of=as_of)


def render(proposals: pd.DataFrame, materials: pd.DataFrame, as_of: date) -> None:
    section("Πρόβλεψη ζήτησης ανά υλικό",
            "Τρεις μέθοδοι πρόβλεψης αξιολογούνται με walk-forward validation "
            "(5 παράθυρα: εκπαίδευση 60 ημ. → έλεγχος 14 ημ.). Ο πράκτορας δεν "
            "«εμπιστεύεται» μία μέθοδο — μετρά ποια ταιριάζει στο μοτίβο ζήτησης.")

    materials_list = _material_choices()
    if not materials_list:
        st.warning("Δεν υπάρχουν υλικά στη βάση δεδομένων. Τρέξτε πρώτα το ETL.")
        return

    def _label(item: tuple[str, str]) -> str:
        mid, desc = item
        return f"{mid}  —  {desc}" if desc else mid

    default_idx = _default_material_index(materials_list, materials)

    c1, c2, c3, c4 = st.columns([3, 1, 1, 1.3])
    with c1:
        selected_tuple = st.selectbox("Υλικό", materials_list, index=default_idx,
                                      format_func=_label, key="fcst_material")
    with c2:
        history_days = st.selectbox("Ιστορικό (ημ.)", [90, 180, 365, 730], index=2,
                                    key="fcst_history_days")
    with c3:
        horizon = st.selectbox("Πρόβλεψη (ημ.)", [14, 30, 60, 90], index=1,
                               key="fcst_horizon")
    with c4:
        level = st.selectbox("Αξιολόγηση σε", ["Εβδομαδιαίο επίπεδο", "Ημερήσιο επίπεδο"],
                             index=0, key="fcst_level",
                             help="Η ακρίβεια μετριέται σε εβδομαδιαίες ποσότητες (όπως τις "
                                  "καταναλώνει το MRP) — το MAPE σε ημερήσια, διακοπτόμενη "
                                  "ζήτηση είναι παραπλανητικά υψηλό (Syntetos & Boylan 2005).")
    weekly_eval = level.startswith("Εβδομαδιαίο")

    if not selected_tuple:
        return

    material_id, description = selected_tuple
    history = _load_history(material_id, as_of, days_back=history_days)

    if len(history) == 0 or history.sum() == 0:
        st.info("Δεν υπάρχει αρκετό ιστορικό κατανάλωσης για αυτό το υλικό "
                "στο επιλεγμένο χρονικό διάστημα.")
        return

    # ─── Summary stats ───
    nonzero = history[history > 0]
    cv = history.std() / history.mean() if history.mean() > 0 else 0
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Σύνολο κατανάλωσης", fmt_int(history.sum()))
    s2.metric("Ενεργές ημέρες", f"{len(nonzero)} / {len(history)}")
    s3.metric("Μέση ημερήσια ζήτηση", fmt_num(history.mean(), 2))
    s4.metric("Μεταβλητότητα (CV)", fmt_num(cv, 2))

    # ─── Forecasts ───
    forecasts = {
        "simple_average":         simple_average(history, horizon),
        "moving_average":         moving_average(history, horizon),
        "exponential_smoothing":  exponential_smoothing(history, horizon),
    }

    with st.spinner("Walk-forward validation…"):
        if weekly_eval:
            eval_series = history.resample("W").sum()
            comparison = compare_methods(
                eval_series, train_window=min(8, len(eval_series) // 2), test_window=2,
                n_folds=5, method_kwargs={"moving_average": {"window": 4}},
            )
        else:
            eval_series = history
            comparison = compare_methods(
                history, train_window=min(60, len(history) // 2), test_window=14, n_folds=5,
            )
    best = best_method(comparison, metric="wmape")

    # ─── Plot ───
    method_choice = st.multiselect(
        "Μέθοδοι προς εμφάνιση", options=list(METHOD_LABELS.keys()),
        default=list(METHOD_LABELS.keys()), format_func=lambda m: METHOD_LABELS[m],
        key="fcst_methods",
    )

    fig = go.Figure()
    history_dates = [d.strftime("%Y-%m-%d") for d in history.index]
    fig.add_trace(go.Scatter(
        x=history_dates, y=history.values, mode="lines", name="Ιστορικό (ημερήσιο)",
        line=dict(color=theme.NEUTRAL, width=1),
        hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
    ))
    smoothed = history.rolling(7, min_periods=1).mean()
    fig.add_trace(go.Scatter(
        x=history_dates, y=smoothed.values, mode="lines", name="Ιστορικό (κινητός μέσος 7 ημ.)",
        line=dict(color=theme.TEXT_SECONDARY, width=2),
        hovertemplate="%{x}: %{y:,.1f}<extra></extra>",
    ))
    last_date = history.index[-1]
    future_dates = [d.strftime("%Y-%m-%d") for d in
                    pd.date_range(start=last_date + pd.Timedelta(days=1), periods=horizon, freq="D")]
    for method in method_choice:
        fig.add_trace(go.Scatter(
            x=future_dates, y=forecasts[method], mode="lines",
            name=METHOD_LABELS[method] + (" ★" if method == best else ""),
            line=dict(color=METHOD_COLORS[method], width=2.5 if method == best else 1.5,
                      dash="solid" if method == best else "dash"),
            hovertemplate="%{x}: %{y:,.1f}<extra></extra>",
        ))
    last_date_str = last_date.strftime("%Y-%m-%d")
    fig.add_shape(type="line", x0=last_date_str, x1=last_date_str, y0=0, y1=1, yref="paper",
                  line=dict(color=theme.STATUS["critical"], width=1, dash="dot"))
    fig.add_annotation(x=last_date_str, y=1, yref="paper", text="σήμερα", showarrow=False,
                       font=dict(color=theme.STATUS["critical"], size=11), xshift=22, yshift=-6)
    theme.base_layout(fig, height=400)
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(title="Ημερομηνία")
    fig.update_yaxes(title="Ζήτηση (μονάδες/ημέρα)")
    plotly(fig, key="fcst_plot")

    # ─── Accuracy metrics ───
    unit = "εβδομάδα" if weekly_eval else "ημέρα"
    section("Ακρίβεια πρόβλεψης (walk-forward validation)",
            f"5 παράθυρα rolling-origin σε {'εβδομαδιαίες' if weekly_eval else 'ημερήσιες'} "
            f"ποσότητες. Χαμηλότερες τιμές = καλύτερη πρόβλεψη· το ★ δείχνει την καλύτερη "
            "μέθοδο κατά WMAPE (Σ|σφάλμα| / Σ|ζήτηση|).")

    if not comparison.empty:
        a1, a2 = st.columns([1.3, 1])
        with a1:
            comp_display = comparison.copy()
            comp_display["Μέθοδος"] = comp_display["method"].map(METHOD_LABELS)
            comp_display["★"] = comp_display["method"].apply(lambda m: "★" if m == best else "")
            comp_display = comp_display[["★", "Μέθοδος", "mae", "rmse", "wmape", "mape", "bias", "n_folds"]]
            comp_display.columns = ["★", "Μέθοδος", f"MAE (μον./{unit})", "RMSE", "WMAPE (%)",
                                    "MAPE (%)", "Bias", "Παράθυρα"]
            theme.dataframe(comp_display, hide_index=True)
        with a2:
            if comparison["n_folds"].sum() > 0:
                fig_acc = go.Figure(go.Bar(
                    x=[METHOD_LABELS[m] for m in comparison["method"]],
                    y=comparison["wmape"],
                    marker_color=[theme.ACCENT if m == best else theme.NEUTRAL
                                  for m in comparison["method"]],
                    text=[f"{v:.1f}%" for v in comparison["wmape"]], textposition="outside",
                    hovertemplate="%{x}: WMAPE %{y:.1f}%<extra></extra>",
                ))
                theme.base_layout(fig_acc, height=260, legend=False)
                fig_acc.update_yaxes(title="WMAPE (%)")
                plotly(fig_acc, key="fcst_mape")

    # ─── Recommendation ───
    best_row = comparison[comparison["method"] == best].iloc[0] if not comparison.empty else None
    if best_row is not None and best_row["n_folds"] > 0:
        bias_val = best_row["bias"]
        bias_dir = ("υπερεκτίμηση" if bias_val > 0 else
                    ("υποεκτίμηση" if bias_val < 0 else "ουδέτερο"))
        cv_note = ("σταθερή ζήτηση — οι απλές μέθοδοι επαρκούν" if cv < 0.5 else
                   "μέτρια μεταβλητότητα — προτιμάται η εκθετική εξομάλυνση" if cv < 1.0 else
                   "υψηλή μεταβλητότητα — κάθε μέθοδος έχει δυσκολία, το safety stock απορροφά τη διαφορά")
        mape_note = ("εξαιρετική (<10%)" if best_row["wmape"] < 10 else
                     "πολύ καλή (10–20%)" if best_row["wmape"] < 20 else
                     "αποδεκτή (20–50%)" if best_row["wmape"] < 50 else
                     "χαμηλή (>50%) — τυπικό για διακοπτόμενη ζήτηση")
        st.success(
            f"**Σύσταση:** {METHOD_LABELS[best]} (WMAPE {best_row['wmape']:.1f}% · "
            f"MAE {best_row['mae']:.1f} μον./{unit}). Μεταβλητότητα ημερήσιας ζήτησης CV {cv:.2f}: "
            f"{cv_note}. Bias {bias_val:+.2f} ({bias_dir}). Ακρίβεια: {mape_note}."
        )
    else:
        st.info("Δεν ήταν δυνατή η αξιολόγηση — ανεπαρκές ιστορικό.")

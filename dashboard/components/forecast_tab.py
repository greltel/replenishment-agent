"""
Demand Forecast tab.

Visualizes historical demand for a material and compares three forecasting
methods (simple_average, moving_average, exponential_smoothing) using
walk-forward validation. Helps planners (and the thesis defense committee)
understand:

  1. What does demand look like for any given material?
  2. How accurate is each forecasting method?
  3. Which method should the agent use for which material?

Methodology:
  • Walk-forward (rolling-origin) validation, n=5 folds by default
  • Metrics: MAE, RMSE, MAPE, Bias (Bergmeir & Benítez 2012)
  • Best-method recommendation per material based on MAPE
"""
from __future__ import annotations

from datetime import date, timedelta

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
    walk_forward_evaluate,
)


METHOD_LABELS = {
    "simple_average":         "Simple Average",
    "moving_average":         "Moving Average (30d)",
    "exponential_smoothing":  "Exp. Smoothing (α=0.3)",
}

METHOD_COLORS = {
    "simple_average":         "#9CA3AF",
    "moving_average":         "#3B82F6",
    "exponential_smoothing":  "#10B981",
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


def _load_history(material_id: str, days_back: int = 365) -> pd.Series:
    """Load consumption history for one material as a daily Series."""
    repo = Repository()
    movements = repo.get_consumption_history(material_id, days=days_back)
    repo.close()
    return consumption_to_daily_series(movements, horizon_back_days=days_back)


def render(proposals: pd.DataFrame, materials: pd.DataFrame) -> None:
    st.subheader("📈 Demand Forecast")
    st.caption(
        "Σύγκριση 3 μεθόδων πρόβλεψης ζήτησης με walk-forward validation. "
        "Διαλέξτε ένα υλικό και δείτε ιστορικό + μελλοντική πρόβλεψη + ακρίβεια."
    )

    # ─── Material selector ───
    materials_list = _material_choices()
    if not materials_list:
        st.warning("Δεν υπάρχουν υλικά στη βάση δεδομένων. Τρέξτε πρώτα το ETL.")
        return

    def _label(item: tuple[str, str]) -> str:
        mid, desc = item
        return f"{mid}  —  {desc}" if desc else mid

    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        selected_tuple = st.selectbox(
            "Material", materials_list, format_func=_label, key="fcst_material",
        )
    with c2:
        history_days = st.selectbox(
            "Ιστορικό", [90, 180, 365, 730], index=2, key="fcst_history_days",
        )
    with c3:
        horizon = st.selectbox(
            "Πρόβλεψη (ημ.)", [14, 30, 60, 90], index=1, key="fcst_horizon",
        )

    if not selected_tuple:
        return

    material_id = selected_tuple[0]
    description = selected_tuple[1]

    if description:
        st.markdown(f"**{description}**")

    # ─── Load history ───
    history = _load_history(material_id, days_back=history_days)

    if len(history) == 0 or history.sum() == 0:
        st.info(
            "Δεν υπάρχει αρκετό ιστορικό κατανάλωσης για αυτό το υλικό "
            "για το επιλεγμένο χρονικό διάστημα."
        )
        return

    # ─── Summary stats ───
    nonzero = history[history > 0]
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Σύνολο κατανάλωσης", f"{history.sum():,.0f}")
    s2.metric("Ενεργές ημέρες",     f"{len(nonzero)}/{len(history)}")
    s3.metric("Μέσος όρος/ημέρα",   f"{history.mean():.2f}")
    s4.metric("CV (variability)",
              f"{(history.std()/history.mean() if history.mean() > 0 else 0):.2f}")

    # ─── Generate forecasts ───
    forecasts = {
        "simple_average":         simple_average(history, horizon),
        "moving_average":         moving_average(history, horizon),
        "exponential_smoothing":  exponential_smoothing(history, horizon),
    }

    # ─── Accuracy comparison ───
    with st.spinner("Walk-forward validation..."):
        comparison = compare_methods(
            history,
            train_window=min(60, len(history) // 2),
            test_window=14,
            n_folds=5,
        )
    best = best_method(comparison, metric="mape")

    # ─── Plot ───
    st.markdown("### Ιστορικό + Πρόβλεψη")
    method_choice = st.multiselect(
        "Μέθοδοι προς εμφάνιση",
        options=list(METHOD_LABELS.keys()),
        default=list(METHOD_LABELS.keys()),
        format_func=lambda m: METHOD_LABELS[m],
    )

    fig = go.Figure()

    # Historical actual demand
    # Convert pandas Timestamps to ISO strings to avoid plotly/pandas conflicts
    # (Plotly's add_vline internally does sum() on Timestamps which fails)
    history_dates = [d.strftime("%Y-%m-%d") for d in history.index]
    fig.add_trace(go.Scatter(
        x=history_dates, y=history.values,
        mode="lines", name="Ιστορικό",
        line=dict(color="#1F2937", width=1.5),
    ))

    # Future forecasts
    last_date = history.index[-1]
    future_dates_pd = pd.date_range(
        start=last_date + pd.Timedelta(days=1), periods=horizon, freq="D",
    )
    future_dates = [d.strftime("%Y-%m-%d") for d in future_dates_pd]
    last_date_str = last_date.strftime("%Y-%m-%d")

    for method in method_choice:
        fig.add_trace(go.Scatter(
            x=future_dates, y=forecasts[method],
            mode="lines",
            name=METHOD_LABELS[method] + (" ⭐" if method == best else ""),
            line=dict(
                color=METHOD_COLORS[method],
                width=2.5 if method == best else 1.5,
                dash="solid" if method == best else "dash",
            ),
        ))

    # Vertical line at "now" — use add_shape instead of add_vline to avoid
    # a Plotly bug where add_vline + Timestamp sums timestamps internally
    fig.add_shape(
        type="line",
        x0=last_date_str, x1=last_date_str,
        y0=0, y1=1, yref="paper",
        line=dict(color="red", width=1, dash="dot"),
    )
    fig.add_annotation(
        x=last_date_str, y=1, yref="paper",
        text="τώρα", showarrow=False,
        font=dict(color="red", size=11),
        xshift=20, yshift=-5,
    )

    fig.update_layout(
        height=420, hovermode="x unified",
        xaxis_title="Ημερομηνία",
        yaxis_title="Ζήτηση (μονάδες/ημέρα)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ─── Accuracy metrics ───
    st.markdown("### Ακρίβεια Πρόβλεψης (Walk-Forward Validation)")
    st.caption(
        "Δοκιμή σε 5 ιστορικά παράθυρα: train σε προηγούμενες 60 ημέρες, "
        "test στις επόμενες 14. Χαμηλότερες τιμές = καλύτερη πρόβλεψη. "
        "Το ⭐ δείχνει την καλύτερη μέθοδο βάσει MAPE."
    )

    if not comparison.empty:
        # Decorate the comparison df
        comp_display = comparison.copy()
        comp_display["method_label"] = comp_display["method"].map(METHOD_LABELS)
        comp_display["best"] = comp_display["method"].apply(
            lambda m: "⭐" if m == best else ""
        )
        comp_display = comp_display[
            ["best", "method_label", "mae", "rmse", "mape", "bias", "n_folds"]
        ]
        comp_display.columns = [
            "", "Μέθοδος", "MAE", "RMSE", "MAPE (%)", "Bias", "Folds",
        ]
        st.dataframe(comp_display, use_container_width=True, hide_index=True)

        # Bar chart of MAPE
        if comparison["n_folds"].sum() > 0:
            fig_acc = go.Figure()
            fig_acc.add_trace(go.Bar(
                x=[METHOD_LABELS[m] for m in comparison["method"]],
                y=comparison["mape"],
                marker_color=[
                    "#10B981" if m == best else "#9CA3AF"
                    for m in comparison["method"]
                ],
                text=[f"{v:.1f}%" for v in comparison["mape"]],
                textposition="auto",
            ))
            fig_acc.update_layout(
                height=300,
                title="MAPE ανά Μέθοδο (χαμηλότερο = καλύτερο)",
                yaxis_title="MAPE (%)",
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig_acc, use_container_width=True)

    # ─── Recommendation ───
    st.markdown("### Σύσταση")

    best_row = comparison[comparison["method"] == best].iloc[0] if not comparison.empty else None
    if best_row is not None and best_row["n_folds"] > 0:
        cv = history.std() / history.mean() if history.mean() > 0 else 0
        bias_val = best_row["bias"]
        bias_dir = "υπερεκτίμηση" if bias_val > 0 else ("υποεκτίμηση" if bias_val < 0 else "ουδέτερο")

        st.success(
            f"Καλύτερη μέθοδος: **{METHOD_LABELS[best]}** "
            f"(MAPE = {best_row['mape']:.1f}%, MAE = {best_row['mae']:.1f})"
        )

        st.markdown(
            f"""
            **Ανάλυση:**
            - **Variability (CV):** {cv:.2f}
              {' — Σταθερή ζήτηση, οι απλές μέθοδοι δουλεύουν καλά.' if cv < 0.5 else ''}
              {' — Μέτρια μεταβλητότητα, exp. smoothing προτείνεται.' if 0.5 <= cv < 1.0 else ''}
              {' — Υψηλή μεταβλητότητα — όλες οι μέθοδοι θα έχουν δυσκολία.' if cv >= 1.0 else ''}
            - **Bias:** {bias_val:+.2f} ({bias_dir})
            - **MAPE interpretation:**
              {' Εξαιρετική (<10%)' if best_row['mape'] < 10 else ''}
              {' Πολύ καλή (10-20%)' if 10 <= best_row['mape'] < 20 else ''}
              {' Αποδεκτή (20-50%)' if 20 <= best_row['mape'] < 50 else ''}
              {' Χαμηλή — εξετάστε διαφορετική μέθοδο (>50%)' if best_row['mape'] >= 50 else ''}
            """
        )
    else:
        st.info("Δεν ήταν δυνατή η αξιολόγηση — ανεπαρκές ιστορικό.")

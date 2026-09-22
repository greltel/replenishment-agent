"""
Visual theme shared by every dashboard tab.

One palette, used by role (not by taste):
  • ABC classes are an ORDERED category → one blue ramp, dark = A.
  • As-Is vs To-Be is an emphasis pair → neutral grey vs the accent blue.
  • Status colours are reserved for meaning (urgent / warning / ok) and are
    always paired with an icon or a label, never used for a data series.

Also provides small Streamlit/Plotly helpers so every tab renders the same
way regardless of the installed Streamlit version.
"""
from __future__ import annotations

import inspect
from datetime import date
from typing import Any

import plotly.graph_objects as go
import streamlit as st


# ============================================================
# Palette
# ============================================================
ACCENT      = "#2a78d6"     # primary series / To-Be
ACCENT_DARK = "#1c5cab"
NEUTRAL     = "#b5b3ad"     # As-Is / de-emphasised series
NEUTRAL_DARK = "#7d7b76"
ORANGE      = "#eb6834"     # second categorical slot
AQUA        = "#1baf7a"
YELLOW      = "#eda100"

ABC_COLORS = {"A": "#1c5cab", "B": "#3987e5", "C": "#86b6ef"}   # ordinal ramp
ABC_ORDER = ["A", "B", "C"]

STATUS = {
    "critical": "#d03b3b",
    "warning":  "#fab219",
    "good":     "#0ca30c",
}

TEXT_PRIMARY   = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
TEXT_MUTED     = "#8a8880"
SURFACE        = "#fcfcfb"
SURFACE_ALT    = "#f3f2ee"
BORDER         = "#e4e2dc"
GRID           = "#ecebe6"

RULE_LABELS_EL = {
    "R-DEAD-STOCK":       "Νεκρό απόθεμα (καταστολή)",
    "R-EXPEDITE":         "Επείγουσα παραγγελία",
    "R-SAFETY-BUFFER-A":  "Buffer +20% (A-class)",
    "R-LONG-LEAD-BUFFER": "Buffer +15% (LT > 14 ημ.)",
    "R-MOQ-ENFORCE":      "Ελάχιστη ποσότητα (MOQ)",
    "R-CALENDAR-SHIFT":   "Μετάθεση σε εργάσιμη",
    "R-COST-ESTIMATE":    "Εκτίμηση κόστους",
}

LOT_SIZING_LABELS_EL = {
    "LFL": "Lot-for-Lot",
    "FOQ": "Σταθερή ποσότητα (FOQ)",
    "EOQ": "Οικονομική ποσότητα (EOQ)",
    "POQ": "Περιοδική ποσότητα (POQ)",
    "WW":  "Wagner-Whitin",
}

MATERIAL_TYPE_EL = {
    "ROH": "Πρώτη ύλη", "HALB": "Ημικατεργασμένο",
    "FERT": "Τελικό προϊόν", "VERP": "Συσκευασία",
}


# ============================================================
# CSS
# ============================================================
_CSS = f"""
<style>
  /* Hide Streamlit chrome that distracts during a presentation */
  #MainMenu, footer, header [data-testid="stToolbar"], [data-testid="stDecoration"],
  .stAppDeployButton, [data-testid="stStatusWidget"] {{ visibility: hidden; }}
  header[data-testid="stHeader"] {{ background: transparent; }}

  .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }}

  /* Header */
  .ra-header {{ display:flex; align-items:flex-end; justify-content:space-between;
                gap: 1rem; padding-bottom: .6rem; border-bottom: 1px solid {BORDER};
                margin-bottom: 1rem; flex-wrap: wrap; }}
  .ra-title {{ font-size: 1.65rem; font-weight: 700; color:{TEXT_PRIMARY}; line-height:1.15; margin:0; }}
  .ra-subtitle {{ color:{TEXT_SECONDARY}; font-size: .95rem; margin-top:.25rem; }}
  .ra-chips {{ display:flex; gap:.5rem; flex-wrap:wrap; justify-content:flex-start; margin-top:.4rem; }}
  .ra-chip {{ background:{SURFACE_ALT}; border:1px solid {BORDER}; border-radius: 999px;
              padding: .25rem .7rem; font-size:.8rem; color:{TEXT_SECONDARY}; white-space:nowrap; }}
  .ra-chip b {{ color:{TEXT_PRIMARY}; font-weight:600; }}

  /* KPI tiles */
  .ra-kpi {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius: 12px;
             padding: .8rem 1rem; min-height: 118px; }}
  .ra-kpi .lbl {{ font-size:.8rem; color:{TEXT_SECONDARY}; font-weight:600; }}
  .ra-kpi .val {{ font-size:1.7rem; font-weight:700; color:{TEXT_PRIMARY}; line-height:1.2;
                  margin-top:.15rem; }}
  .ra-kpi .sub {{ font-size:.8rem; color:{TEXT_MUTED}; margin-top:.2rem; }}
  .ra-kpi.critical .val {{ color:{STATUS['critical']}; }}
  .ra-kpi.good .val {{ color:{STATUS['good']}; }}
  .ra-kpi.accent .val {{ color:{ACCENT_DARK}; }}
  .ra-kpi.warning .val {{ color:#b25e00; }}

  /* Section titles */
  .ra-h {{ font-size:1.1rem; font-weight:700; color:{TEXT_PRIMARY}; margin: .4rem 0 .2rem 0; }}
  .ra-cap {{ font-size:.85rem; color:{TEXT_SECONDARY}; margin-bottom:.6rem; }}

  /* Badges */
  .ra-badge {{ display:inline-block; border-radius:6px; padding:.1rem .5rem; font-size:.78rem;
               font-weight:600; }}
  .ra-badge.critical {{ background:#fbe3e3; color:{STATUS['critical']}; }}
  .ra-badge.warning {{ background:#fff1cc; color:#8a5a00; }}
  .ra-badge.good {{ background:#e1f5e1; color:#0a6e0a; }}
  .ra-badge.neutral {{ background:{SURFACE_ALT}; color:{TEXT_SECONDARY}; }}

  /* BDI diagram */
  .bdi-row {{ display:flex; gap:.6rem; align-items:stretch; }}
  .bdi-box {{ flex:1; background:{SURFACE}; border:1px solid {BORDER}; border-top:4px solid {ACCENT};
              border-radius:10px; padding:.7rem .9rem; }}
  .bdi-box h4 {{ margin:0 0 .3rem 0; font-size:.95rem; color:{TEXT_PRIMARY}; }}
  .bdi-box p {{ margin:0; font-size:.82rem; color:{TEXT_SECONDARY}; line-height:1.35; }}
  .bdi-arrow {{ align-self:center; color:{TEXT_MUTED}; font-size:1.4rem; }}

  /* Tabs a bit larger for the projector */
  button[data-baseweb="tab"] p, [data-testid="stTab"] p {{ font-size: 1rem; }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# ============================================================
# Formatting helpers (Greek number style: 1.234,56)
# ============================================================
def fmt_int(v: float | int | None) -> str:
    if v is None:
        return "—"
    return f"{int(round(v)):,}".replace(",", ".")


def fmt_num(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_eur(v: float | None, decimals: int = 0) -> str:
    if v is None:
        return "—"
    return "€" + fmt_num(v, decimals)


def fmt_pct(v: float | None, decimals: int = 1, signed: bool = False) -> str:
    if v is None:
        return "—"
    s = fmt_num(abs(v), decimals) if signed else fmt_num(v, decimals)
    if signed:
        sign = "+" if v > 0 else ("−" if v < 0 else "")
        return f"{sign}{s}%"
    return f"{s}%"


def fmt_date(d: date | str | None) -> str:
    if d is None:
        return "—"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return d
    return d.strftime("%d.%m.%Y")


# ============================================================
# Streamlit helpers
# ============================================================
def _accepts(fn, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def wide_kwargs(fn) -> dict[str, Any]:
    """Stretch-to-container kwargs for the installed Streamlit version."""
    if _accepts(fn, "width"):
        return {"width": "stretch"}
    if _accepts(fn, "use_container_width"):
        return {"use_container_width": True}
    return {}


def plotly(fig: go.Figure, key: str | None = None) -> None:
    kw = wide_kwargs(st.plotly_chart)
    if key is not None and _accepts(st.plotly_chart, "key"):
        kw["key"] = key
    st.plotly_chart(fig, config={"displayModeBar": False}, **kw)


def dataframe(df, **kwargs) -> None:
    st.dataframe(df, **wide_kwargs(st.dataframe), **kwargs)


def kpi_tile(label: str, value: str, sub: str = "", tone: str = "") -> str:
    return (f'<div class="ra-kpi {tone}"><div class="lbl">{label}</div>'
            f'<div class="val">{value}</div><div class="sub">{sub}</div></div>')


def section(title: str, caption: str = "") -> None:
    st.markdown(f'<div class="ra-h">{title}</div>', unsafe_allow_html=True)
    if caption:
        st.markdown(f'<div class="ra-cap">{caption}</div>', unsafe_allow_html=True)


def badge(text: str, tone: str = "neutral") -> str:
    return f'<span class="ra-badge {tone}">{text}</span>'


# ============================================================
# Plotly base layout
# ============================================================
def base_layout(fig: go.Figure, height: int = 340, legend: bool = True,
                title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        title=dict(text=title, font=dict(size=14, color=TEXT_PRIMARY), x=0) if title else None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=12, color=TEXT_SECONDARY),
        margin=dict(l=10, r=10, t=40 if title else 24, b=10),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor=BORDER),
        bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=BORDER,
                     tickfont=dict(size=11))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, showline=False,
                     tickfont=dict(size=11))
    return fig

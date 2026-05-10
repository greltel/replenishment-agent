"""
SAP-aware parsers.

SAP exports have several quirks that standard pd.to_numeric / float() don't
handle:
  • Trailing-minus notation:  '3.000-'    means -3000
  • European format:          '1.234,56'  means 1234.56
  • Date format:              '20260508'  means 2026-05-08
  • Mixed empty/null values

These parsers handle all of the above robustly.
"""
from __future__ import annotations

import pandas as pd


def parse_sap_number(value, default: float = 0.0) -> float:
    """Robust parser for numbers exported from SAP.

    Handles:
      • Trailing minus sign (SAP convention): '3.000-' → -3000.0
      • Leading minus:                        '-3.000' → -3000.0
      • European format with both . and ,:    '1.234,56' → 1234.56
      • US format with both , and .:          '1,234.56' → 1234.56
      • Already numeric (int/float):          passes through
      • NaN / empty / None:                   returns default

    Heuristics for ambiguous single-separator cases:
      • '3.000'  (only dots, all-3-digit groups) → 3000   (thousands)
      • '3.5'    (only dot, single decimal)      → 3.5    (decimal)
      • '3,000'  (only comma, exactly 3 digits)  → 3000   (thousands)
      • '3,5'    (only comma, single decimal)    → 3.5    (decimal)
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return default

    # Detect trailing or leading minus and strip it
    is_negative = False
    if s.endswith("-"):
        is_negative = True
        s = s[:-1].strip()
    elif s.startswith("-"):
        is_negative = True
        s = s[1:].strip()

    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # Both present — last one is decimal separator
        if s.rfind(",") > s.rfind("."):
            # European: '1.234,56'
            s = s.replace(".", "").replace(",", ".")
        else:
            # US: '1,234.56'
            s = s.replace(",", "")
    elif has_comma:
        last_comma = s.rfind(",")
        # If exactly 3 digits after the only comma → thousands separator
        if len(s) - last_comma - 1 == 3 and s[:last_comma].replace(",", "").isdigit():
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif has_dot:
        parts = s.split(".")
        # Multiple dots, all groups (after first) exactly 3 digits → thousands
        if len(parts) > 1 and all(len(p) == 3 and p.isdigit() for p in parts[1:]):
            s = s.replace(".", "")
        # else: leave as decimal '3.5'

    try:
        result = float(s)
    except ValueError:
        return default

    return -result if is_negative else result


def parse_sap_int(value, default: int = 0) -> int:
    """Same as parse_sap_number but returns int."""
    return int(parse_sap_number(value, default))


def parse_sap_number_series(series: pd.Series, default: float = 0.0) -> pd.Series:
    """Vectorized version of parse_sap_number for pandas Series.

    Returns a pd.Series of floats. Useful for DataFrame columns.
    """
    return series.apply(lambda x: parse_sap_number(x, default))


def parse_sap_date(series: pd.Series) -> pd.Series:
    """Parse SAP date column to pandas datetime.

    SAP exports dates as YYYYMMDD integers/strings (e.g. 20260508).
    Excel/CSV may convert to other formats. This handles both.
    """
    s = series.astype(str).str.strip()
    # Handle the 8-digit YYYYMMDD case explicitly (most common in CSV exports)
    is_yyyymmdd = s.str.match(r"^\d{8}$").fillna(False)
    result = pd.to_datetime(s, errors="coerce", format="mixed")
    # Override the YYYYMMDD ones with explicit parse
    if is_yyyymmdd.any():
        result.loc[is_yyyymmdd] = pd.to_datetime(
            s[is_yyyymmdd], format="%Y%m%d", errors="coerce"
        )
    return result

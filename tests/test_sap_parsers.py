"""Tests for SAP-aware number and date parsers."""
import math
from datetime import date

import pandas as pd
import pytest

from src.data_layer.sap_parsers import (
    parse_sap_number,
    parse_sap_int,
    parse_sap_number_series,
    parse_sap_date,
)


class TestParseSAPNumberBasics:
    """Plain numbers without separators."""

    def test_int_passes_through(self):
        assert parse_sap_number(42) == 42.0

    def test_float_passes_through(self):
        assert parse_sap_number(3.14) == 3.14

    def test_string_int(self):
        assert parse_sap_number("42") == 42.0

    def test_string_float(self):
        assert parse_sap_number("3.14") == 3.14

    def test_zero(self):
        assert parse_sap_number(0) == 0.0
        assert parse_sap_number("0") == 0.0


class TestParseSAPNumberNullHandling:
    """Null/missing/empty value handling."""

    def test_none_returns_default(self):
        assert parse_sap_number(None) == 0.0

    def test_nan_returns_default(self):
        assert parse_sap_number(float("nan")) == 0.0

    def test_empty_string_returns_default(self):
        assert parse_sap_number("") == 0.0
        assert parse_sap_number("   ") == 0.0

    def test_nan_string_returns_default(self):
        assert parse_sap_number("nan") == 0.0
        assert parse_sap_number("NULL") == 0.0
        assert parse_sap_number("None") == 0.0

    def test_custom_default(self):
        assert parse_sap_number(None, default=1.0) == 1.0
        assert parse_sap_number("", default=99) == 99.0


class TestParseSAPNumberTrailingMinus:
    """SAP convention: '3.000-' means -3000."""

    def test_simple_trailing_minus(self):
        assert parse_sap_number("42-") == -42.0

    def test_decimal_trailing_minus(self):
        assert parse_sap_number("3.5-") == -3.5

    def test_thousands_trailing_minus(self):
        # The exact bug from production!
        assert parse_sap_number("3.000-") == -3000.0

    def test_european_decimal_trailing_minus(self):
        assert parse_sap_number("1.234,56-") == -1234.56

    def test_leading_minus_still_works(self):
        assert parse_sap_number("-42") == -42.0
        assert parse_sap_number("-3.000") == -3000.0


class TestParseSAPNumberEuropeanFormat:
    """European number format: '.' = thousands, ',' = decimal."""

    def test_european_thousands_only(self):
        assert parse_sap_number("3.000") == 3000.0
        assert parse_sap_number("1.234.567") == 1234567.0

    def test_european_decimal_only(self):
        assert parse_sap_number("3,5") == 3.5
        assert parse_sap_number("0,75") == 0.75

    def test_european_full_format(self):
        assert parse_sap_number("1.234,56") == 1234.56
        assert parse_sap_number("12.345.678,90") == 12345678.90


class TestParseSAPNumberUSFormat:
    """US format: ',' = thousands, '.' = decimal."""

    def test_us_thousands_only(self):
        assert parse_sap_number("3,000") == 3000.0

    def test_us_decimal_only(self):
        # Single dot with non-3-digit fraction → decimal
        assert parse_sap_number("3.5") == 3.5
        assert parse_sap_number("3.14") == 3.14

    def test_us_full_format(self):
        assert parse_sap_number("1,234.56") == 1234.56


class TestParseSAPNumberAmbiguous:
    """Edge cases that require heuristics."""

    def test_three_digits_after_dot_treated_as_thousands(self):
        # Following SAP/European convention
        assert parse_sap_number("3.000") == 3000.0

    def test_two_digits_after_dot_treated_as_decimal(self):
        assert parse_sap_number("3.50") == 3.50

    def test_invalid_fallback(self):
        assert parse_sap_number("abc") == 0.0
        assert parse_sap_number("12.34.56") == 0.0  # ambiguous, falls back


class TestParseSAPInt:
    def test_basic(self):
        assert parse_sap_int("42") == 42
        assert parse_sap_int("3.000-") == -3000

    def test_truncates_decimal(self):
        assert parse_sap_int("3.5") == 3

    def test_default(self):
        assert parse_sap_int(None, default=7) == 7


class TestParseSAPNumberSeries:
    def test_pandas_series(self):
        s = pd.Series(["3.000-", "1.234,56", "42", "", None])
        result = parse_sap_number_series(s)
        assert result.tolist() == [-3000.0, 1234.56, 42.0, 0.0, 0.0]


class TestParseSAPDate:
    def test_yyyymmdd_string(self):
        s = pd.Series(["20260508", "20260109"])
        result = parse_sap_date(s)
        assert result.iloc[0].date() == date(2026, 5, 8)
        assert result.iloc[1].date() == date(2026, 1, 9)

    def test_yyyymmdd_int(self):
        s = pd.Series([20260508, 20260109])
        result = parse_sap_date(s)
        assert result.iloc[0].date() == date(2026, 5, 8)

    def test_iso_format(self):
        s = pd.Series(["2026-05-08", "2026-01-09"])
        result = parse_sap_date(s)
        assert result.iloc[0].date() == date(2026, 5, 8)

    def test_mixed_formats(self):
        s = pd.Series(["20260508", "2026-01-09"])
        result = parse_sap_date(s)
        assert result.iloc[0].date() == date(2026, 5, 8)
        assert result.iloc[1].date() == date(2026, 1, 9)

    def test_empty(self):
        s = pd.Series(["", None])
        result = parse_sap_date(s)
        # Both should be NaT
        assert result.iloc[0] is pd.NaT or pd.isna(result.iloc[0])

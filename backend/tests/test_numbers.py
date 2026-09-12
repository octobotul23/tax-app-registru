"""Number and date parsing.

These cases are the real failure modes seen when a vision model transcribes a
Romanian receipt: it echoes the local format sometimes and normalises it other
times, in the same session. Getting this wrong turns 1.234,56 lei into 1.23.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.ai.numbers import parse_date, parse_decimal, parse_money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Plain values that need no interpretation.
        ("12", "12"),
        ("12.50", "12.50"),
        (19.99, "19.99"),
        (42, "42"),
        (Decimal("7.77"), "7.77"),

        # Romanian: dot groups thousands, comma marks decimals.
        ("1.234,56", "1234.56"),
        ("12,34", "12.34"),
        ("1.234.567,89", "1234567.89"),
        ("0,99", "0.99"),
        ("12,5", "12.5"),

        # Anglo: comma groups thousands, dot marks decimals.
        ("1,234.56", "1234.56"),
        ("1,234,567.89", "1234567.89"),

        # Ambiguous singles, resolved by the three-digit rule.
        ("1,500", "1500"),      # grouping - money has two decimals, not three
        ("1.234", "1234"),      # same rule mirrored for the Romanian layout
        ("1.500.000", "1500000"),

        # Currency noise the model failed to strip.
        ("1.234,56 LEI", "1234.56"),
        ("RON 89,90", "89.90"),
        ("  45,00  ", "45.00"),
        ("€ 1.200,00", "1200.00"),

        # Negatives, for refund lines.
        ("-12,50", "-12.50"),
    ],
)
def test_parse_decimal(raw: object, expected: str) -> None:
    assert parse_decimal(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "   ", "abc", "-", ".", ",", [], {}])
def test_parse_decimal_rejects_junk(raw: object) -> None:
    assert parse_decimal(raw) is None


def test_parse_money_rounds_to_cents() -> None:
    assert parse_money("12,999") == Decimal("13.00")
    assert parse_money("0,001") == Decimal("0.00")


def test_float_does_not_pick_up_binary_noise() -> None:
    """Decimal(0.1) is 0.1000000000000000055...; going via str() avoids that."""
    assert parse_decimal(0.1) == Decimal("0.1")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-04-03", date(2025, 4, 3)),
        ("03.04.2025", date(2025, 4, 3)),   # day-first: 3 April, not 4 March
        ("03/04/2025", date(2025, 4, 3)),
        ("03-04-2025", date(2025, 4, 3)),
        ("2025-04-03T14:22:00", date(2025, 4, 3)),
        ("2025-04-03 14:22", date(2025, 4, 3)),
        ("25.12.2024", date(2024, 12, 25)),
    ],
)
def test_parse_date(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


def test_day_first_beats_month_first() -> None:
    """These are European receipts: 03/04 is the third of April."""
    assert parse_date("03/04/2025") == date(2025, 4, 3)


@pytest.mark.parametrize("raw", [None, "", "not a date", "2087-01-01", "1899-01-01", 42])
def test_parse_date_rejects_junk_and_impossible_years(raw: object) -> None:
    assert parse_date(raw) is None


def test_parse_date_passes_through_a_real_date() -> None:
    assert parse_date(date(2025, 1, 1)) == date(2025, 1, 1)

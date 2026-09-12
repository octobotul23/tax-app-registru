"""Turning whatever the model wrote into a Decimal.

Receipts in Romania use `1.234,56`. Receipts in the US use `1,234.56`. A vision
model reading a Romanian receipt will sometimes echo the local format and
sometimes helpfully "normalise" it to the American one, in the same session, on
the same prompt. Guessing wrong turns 1.234,56 lei into 1.23 lei, so this gets
its own module and its own tests.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_CURRENCY_NOISE = re.compile(r"[^\d.,\-]")


def _trailing_digits(text: str, separator_index: int) -> int:
    """How many characters follow the separator at `separator_index`."""
    return len(text) - separator_index - 1


def parse_decimal(value: object) -> Decimal | None:
    """Best-effort numeric parse. Returns None rather than raising."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # str() first: Decimal(0.1) is 0.1000000000000000055511151231257827
        return Decimal(str(value))
    if not isinstance(value, str):
        return None

    text = _CURRENCY_NOISE.sub("", value.strip())
    if not text or text in {"-", ".", ","}:
        return None

    negative = text.startswith("-")
    text = text.lstrip("-")

    last_dot, last_comma = text.rfind("."), text.rfind(",")

    if last_dot >= 0 and last_comma >= 0:
        # Both present: whichever comes last is the decimal separator and the
        # other is a thousands grouper. Handles 1.234,56 and 1,234.56 alike.
        if last_comma > last_dot:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")

    elif last_comma >= 0:
        # Commas only. Exactly three trailing digits means grouping ("1,500"),
        # because money here has two decimals, never three. Anything else is a
        # decimal comma: "12,34", "12,5".
        if text.count(",") > 1 or _trailing_digits(text, last_comma) == 3:
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")

    elif last_dot >= 0:
        # Dots only. Same reasoning mirrored: "1.234" on a Romanian receipt is
        # one thousand two hundred thirty-four, not one point two three four.
        digits_only = text.replace(".", "")
        if text.count(".") > 1 or (
            _trailing_digits(text, last_dot) == 3 and len(digits_only) > 3
        ):
            text = digits_only

    if not text or text == ".":
        return None

    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return -result if negative else result


def parse_money(value: object) -> Decimal | None:
    """Parse and round to two places, the resolution money actually has."""
    parsed = parse_decimal(value)
    if parsed is None:
        return None
    return parsed.quantize(Decimal("0.01"))


_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%y",
    "%d/%m/%y",
    "%Y/%m/%d",
    "%m/%d/%Y",
)


def parse_date(value: object) -> date | None:
    """Parse a date the model emitted, preferring day-first reading.

    Day-first is listed ahead of month-first on purpose: these are European
    receipts, so 03/04/2025 means 3 April, not 4 March.
    """
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    # Drop any time portion the model tacked on.
    text = re.split(r"[ T]", text)[0]

    for pattern in _DATE_PATTERNS:
        try:
            parsed = datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        # A receipt from 2087 means the model misread the year.
        if 2000 <= parsed.year <= date.today().year + 1:
            return parsed
    return None

"""Currency conversion into the base currency.

Rates are looked up by date, not by "now". A receipt from March is converted at
March's rate and that result is frozen onto the row, so reprinting last
quarter's balance next year gives the same numbers it gave at the time.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ExchangeRate

CENTS = Decimal("0.01")
ONE = Decimal("1")


class MissingRate(Exception):
    """No exchange rate is on file for this currency on this date."""

    def __init__(self, currency: str, on: date) -> None:
        self.currency = currency
        self.on = on
        super().__init__(
            f"No exchange rate for {currency} on {on:%Y-%m-%d}. "
            f"Add one in Settings before this document can be valued in "
            f"{settings.base_currency}."
        )


def quantize(amount: Decimal) -> Decimal:
    """Round to 2 decimal places, half-up - the way an invoice rounds."""
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def normalise_currency(code: str | None) -> str:
    return (code or settings.base_currency).strip().upper()


def is_supported(code: str) -> bool:
    return normalise_currency(code) in settings.currencies


def resolve_rate(db: Session, currency: str, on: date) -> Decimal:
    """The rate converting `currency` into the base currency on `on`.

    Picks the most recent rate effective on or before that date, which is how
    a bank rate table behaves: a rate stands until superseded.
    """
    code = normalise_currency(currency)
    if code == settings.base_currency:
        return ONE

    stmt = (
        select(ExchangeRate.rate_to_base)
        .where(ExchangeRate.currency == code, ExchangeRate.effective_from <= on)
        .order_by(ExchangeRate.effective_from.desc())
        .limit(1)
    )
    rate = db.execute(stmt).scalar_one_or_none()
    if rate is None:
        raise MissingRate(code, on)
    return Decimal(rate)


def convert(amount: Decimal, rate: Decimal) -> Decimal:
    """Apply a rate and round to cents."""
    try:
        return quantize(Decimal(amount) * Decimal(rate))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"Cannot convert {amount!r} at rate {rate!r}") from exc


def value_in_base(
    db: Session,
    amount: Decimal | None,
    currency: str | None,
    on: date | None,
    explicit_rate: Decimal | None = None,
) -> tuple[Decimal | None, Decimal | None]:
    """Return `(fx_rate, amount_in_base)` for a document.

    `explicit_rate` wins when supplied - that is the escape hatch for "the bank
    actually charged me this rate", which no rate table will ever match exactly.
    Returns `(None, None)` when there is no amount to convert.
    """
    if amount is None:
        return None, None

    code = normalise_currency(currency)
    if explicit_rate is not None:
        rate = Decimal(explicit_rate)
    elif code == settings.base_currency:
        rate = ONE
    else:
        rate = resolve_rate(db, code, on or date.today())

    return rate, convert(Decimal(amount), rate)

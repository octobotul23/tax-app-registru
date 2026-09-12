"""Exchange rates into the base currency.

Entered by hand on purpose. This stack is built to run on your own server with
no outbound internet, and more importantly: the rate that belongs in your books
is the one your bank actually charged you, which no public rate table will
match to the bani.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import Document, DocumentStatus, ExchangeRate
from app.schemas import ExchangeRateIn, ExchangeRateOut
from app.services.documents import recompute_base
from app.services.money import MissingRate, resolve_rate

router = APIRouter(prefix="/api/rates", tags=["rates"])


@router.get("/currencies", response_model=list[str])
def supported_currencies(_: CurrentUser) -> list[str]:
    return settings.currencies


@router.get("", response_model=list[ExchangeRateOut])
def list_rates(db: DbSession, _: CurrentUser):
    return list(
        db.execute(
            select(ExchangeRate)
            .order_by(ExchangeRate.currency, ExchangeRate.effective_from.desc())
        ).scalars()
    )


@router.get("/current")
def current_rates(db: DbSession, _: CurrentUser) -> dict[str, str | None]:
    """Today's effective rate per currency, for display next to an amount."""
    today = date.today()
    out: dict[str, str | None] = {}
    for code in settings.currencies:
        try:
            out[code] = str(resolve_rate(db, code, today))
        except MissingRate:
            out[code] = None
    return out


@router.post("", response_model=ExchangeRateOut, status_code=status.HTTP_201_CREATED)
def upsert_rate(payload: ExchangeRateIn, db: DbSession, _: CurrentUser):
    if payload.currency == settings.base_currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{settings.base_currency} is the base currency; its rate is always 1",
        )
    if payload.currency not in settings.currencies:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{payload.currency} is not enabled. Supported: "
                f"{', '.join(settings.currencies)}"
            ),
        )

    existing = db.execute(
        select(ExchangeRate).where(
            ExchangeRate.currency == payload.currency,
            ExchangeRate.effective_from == payload.effective_from,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.rate_to_base = payload.rate_to_base
        existing.note = payload.note
        rate = existing
    else:
        rate = ExchangeRate(**payload.model_dump())
        db.add(rate)

    db.commit()
    db.refresh(rate)
    return rate


@router.post("/revalue", status_code=status.HTTP_200_OK)
def revalue_pending(db: DbSession, _: CurrentUser) -> dict[str, int]:
    """Re-value documents that were stuck without a rate.

    Adding a missing rate does not retroactively fix the receipts that were
    filed before it existed, so this walks the documents that have a total but
    no base value and tries again.
    """
    stranded = list(
        db.execute(
            select(Document).where(
                Document.deleted_at.is_(None),
                Document.total.is_not(None),
                Document.total_base.is_(None),
            )
        ).scalars()
    )

    fixed = 0
    for document in stranded:
        if recompute_base(db, document) is None and document.total_base is not None:
            fixed += 1
            if document.status == DocumentStatus.NEEDS_REVIEW and document.ai_error:
                document.ai_error = None

    db.commit()
    return {"examined": len(stranded), "revalued": fixed}


@router.delete("/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rate(rate_id: uuid.UUID, db: DbSession, _: CurrentUser) -> None:
    rate = db.get(ExchangeRate, rate_id)
    if rate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rate")
    db.delete(rate)
    db.commit()

"""The "who paid how much" reports, and the dashboard summary."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import Date, and_, cast, func, select

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import (
    COUNTABLE_STATUSES,
    Document,
    DocumentKind,
    DocumentStatus,
    FundingSource,
)
from app.schemas import BalanceReport, CategoryTotal, DashboardSummary
from app.services.balance import compute_balance
from app.services.money import quantize

router = APIRouter(prefix="/api/reports", tags=["reports"])

ZERO = Decimal("0.00")


@router.get("/balance", response_model=BalanceReport)
def balance(
    db: DbSession,
    _: CurrentUser,
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
) -> BalanceReport:
    """Who funded the business out of pocket, and who owes whom as a result."""
    return compute_balance(db, period_start, period_end)


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(db: DbSession, _: CurrentUser) -> DashboardSummary:
    """The numbers worth seeing the moment you open the app."""
    today = date.today()
    month_start = today.replace(day=1)

    counts = dict(
        db.execute(
            select(Document.status, func.count(Document.id))
            .where(Document.deleted_at.is_(None))
            .group_by(Document.status)
        ).all()
    )

    effective_date = func.coalesce(Document.document_date, cast(Document.created_at, Date))
    this_month = [
        Document.deleted_at.is_(None),
        Document.kind == DocumentKind.RECEIPT,
        Document.status.in_(COUNTABLE_STATUSES),
        effective_date >= month_start,
        effective_date <= today,
    ]

    receipts_this_month = db.execute(
        select(func.count(Document.id)).where(and_(*this_month))
    ).scalar_one()

    spend_this_month = db.execute(
        select(func.coalesce(func.sum(Document.total_base), 0)).where(and_(*this_month))
    ).scalar_one()

    # Last 12 months of spending, grouped by what it was for. Null categories
    # are kept rather than dropped - "uncategorised" is itself worth seeing.
    window_start = today - timedelta(days=365)
    category_rows = db.execute(
        select(
            Document.category,
            Document.funding_source,
            func.coalesce(func.sum(Document.total_base), 0),
            func.count(Document.id),
        )
        .where(
            Document.deleted_at.is_(None),
            Document.kind == DocumentKind.RECEIPT,
            Document.status.in_(COUNTABLE_STATUSES),
            Document.total_base.is_not(None),
            effective_date >= window_start,
        )
        .group_by(Document.category, Document.funding_source)
        .order_by(func.coalesce(func.sum(Document.total_base), 0).desc())
        .limit(10)
    ).all()

    return DashboardSummary(
        base_currency=settings.base_currency,
        pending_scans=int(counts.get(DocumentStatus.PENDING, 0))
        + int(counts.get(DocumentStatus.PROCESSING, 0)),
        needs_review=int(counts.get(DocumentStatus.NEEDS_REVIEW, 0)),
        failed_scans=int(counts.get(DocumentStatus.FAILED, 0)),
        receipts_this_month=int(receipts_this_month),
        spend_this_month=quantize(spend_this_month or ZERO),
        top_categories=[
            CategoryTotal(
                category=category,
                funding_source=source,
                total_base=quantize(total),
                document_count=int(count),
            )
            for category, source, total, count in category_rows
        ],
    )


@router.get("/categories", response_model=list[CategoryTotal])
def categories(
    db: DbSession,
    _: CurrentUser,
    period_start: date | None = None,
    period_end: date | None = None,
    funding_source: FundingSource | None = None,
) -> list[CategoryTotal]:
    """Spending by category, for the period you are reporting on."""
    effective_date = func.coalesce(Document.document_date, cast(Document.created_at, Date))
    filters = [
        Document.deleted_at.is_(None),
        Document.kind == DocumentKind.RECEIPT,
        Document.status.in_(COUNTABLE_STATUSES),
        Document.total_base.is_not(None),
    ]
    if period_start is not None:
        filters.append(effective_date >= period_start)
    if period_end is not None:
        filters.append(effective_date <= period_end)
    if funding_source is not None:
        filters.append(Document.funding_source == funding_source)

    rows = db.execute(
        select(
            Document.category,
            Document.funding_source,
            func.coalesce(func.sum(Document.total_base), 0),
            func.count(Document.id),
        )
        .where(and_(*filters))
        .group_by(Document.category, Document.funding_source)
        .order_by(func.coalesce(func.sum(Document.total_base), 0).desc())
    ).all()

    return [
        CategoryTotal(
            category=category,
            funding_source=source,
            total_base=quantize(total),
            document_count=int(count),
        )
        for category, source, total, count in rows
    ]

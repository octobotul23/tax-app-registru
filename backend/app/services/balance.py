"""Who paid how much, and who owes whom.

The rule the whole app exists to enforce:

  * A purchase made with BUSINESS money is recorded and then forgotten about,
    balance-wise. The company paid; nobody is owed anything.
  * A purchase made with a partner's PERSONAL money is a claim. That partner
    funded the business out of pocket.

The balance then asks a second question: given that both partners have been
funding the business personally, are they carrying it *evenly*? Each partner's
fair share of the total personal outlay is their equity share of it. Anyone
above their share is owed by the others; anyone below owes.

Settlements - real transfers between the partners - are subtracted so the
ledger can actually return to zero once you have squared up.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    COUNTABLE_STATUSES,
    UNVERIFIED_STATUSES,
    Document,
    DocumentKind,
    FundingSource,
    Settlement,
    User,
)
from app.schemas import BalanceReport, PartnerBalance, SettlementSuggestion
from app.services.money import quantize

ZERO = Decimal("0.00")

#: Below this, a residual imbalance is rounding noise rather than a real debt
#: worth transferring money over.
SETTLEMENT_EPSILON = Decimal("0.01")


def _effective_date():
    """The date a document belongs to: what it says, else when it was filed."""
    return func.coalesce(Document.document_date, cast(Document.created_at, Date))


def _period_filter(period_start: date | None, period_end: date | None) -> list:
    clauses = []
    if period_start is not None:
        clauses.append(_effective_date() >= period_start)
    if period_end is not None:
        clauses.append(_effective_date() <= period_end)
    return clauses


def compute_balance(
    db: Session,
    period_start: date | None = None,
    period_end: date | None = None,
) -> BalanceReport:
    base_filters = [
        Document.deleted_at.is_(None),
        Document.kind == DocumentKind.RECEIPT,
        *_period_filter(period_start, period_end),
    ]
    countable = [
        *base_filters,
        Document.status.in_(COUNTABLE_STATUSES),
        Document.total_base.is_not(None),
    ]

    # --- outlay per partner, split by whose money it was -------------------
    rows = db.execute(
        select(
            Document.payer_id,
            Document.funding_source,
            func.coalesce(func.sum(Document.total_base), 0),
            func.count(Document.id),
        )
        .where(and_(*countable))
        .group_by(Document.payer_id, Document.funding_source)
    ).all()

    personal: dict[uuid.UUID, Decimal] = {}
    business: dict[uuid.UUID, Decimal] = {}
    doc_counts: dict[uuid.UUID, int] = {}
    for payer_id, source, total, count in rows:
        bucket = personal if source == FundingSource.PERSONAL else business
        bucket[payer_id] = bucket.get(payer_id, ZERO) + Decimal(total)
        doc_counts[payer_id] = doc_counts.get(payer_id, 0) + int(count)

    # --- how much of the personal outlay is still only a machine guess -----
    unverified_rows = db.execute(
        select(Document.payer_id, func.coalesce(func.sum(Document.total_base), 0))
        .where(
            and_(
                *countable,
                Document.funding_source == FundingSource.PERSONAL,
                Document.status.in_(UNVERIFIED_STATUSES),
            )
        )
        .group_by(Document.payer_id)
    ).all()
    unverified = {payer_id: Decimal(total) for payer_id, total in unverified_rows}

    # --- receipts we had to leave out, so the report can say so ------------
    excluded = db.execute(
        select(func.count(Document.id)).where(
            and_(
                *base_filters,
                or_(
                    Document.status.not_in(COUNTABLE_STATUSES),
                    Document.total_base.is_(None),
                ),
            )
        )
    ).scalar_one()

    # --- settlements already made -----------------------------------------
    settlement_filters = [Settlement.deleted_at.is_(None)]
    if period_start is not None:
        settlement_filters.append(Settlement.settled_on >= period_start)
    if period_end is not None:
        settlement_filters.append(Settlement.settled_on <= period_end)

    received = dict(
        db.execute(
            select(Settlement.to_user_id, func.coalesce(func.sum(Settlement.amount_base), 0))
            .where(and_(*settlement_filters))
            .group_by(Settlement.to_user_id)
        ).all()
    )
    paid = dict(
        db.execute(
            select(Settlement.from_user_id, func.coalesce(func.sum(Settlement.amount_base), 0))
            .where(and_(*settlement_filters))
            .group_by(Settlement.from_user_id)
        ).all()
    )

    # --- fair shares -------------------------------------------------------
    partners = list(
        db.execute(select(User).where(User.is_active.is_(True)).order_by(User.created_at)).scalars()
    )
    total_personal = quantize(sum(personal.values(), ZERO))

    # Equity shares are meant to sum to 1, but nothing forces a human to enter
    # them that way. Normalise so a typo skews nobody's fair share. If they all
    # somehow came out at zero, fall back to an even split.
    share_sum = sum((Decimal(p.equity_share) for p in partners), ZERO)
    if share_sum > 0:
        shares = {p.id: Decimal(p.equity_share) / share_sum for p in partners}
    else:
        even = Decimal(1) / Decimal(len(partners) or 1)
        shares = {p.id: even for p in partners}

    balances: list[PartnerBalance] = []
    for partner in partners:
        outlay = quantize(personal.get(partner.id, ZERO))
        fair = quantize(total_personal * shares[partner.id])
        got = quantize(Decimal(received.get(partner.id, 0)))
        gave = quantize(Decimal(paid.get(partner.id, 0)))
        balances.append(
            PartnerBalance(
                user_id=partner.id,
                display_name=partner.display_name,
                equity_share=Decimal(partner.equity_share),
                personal_outlay=outlay,
                business_outlay=quantize(business.get(partner.id, ZERO)),
                unverified_outlay=quantize(unverified.get(partner.id, ZERO)),
                fair_share=fair,
                settlements_received=got,
                settlements_paid=gave,
                net_position=quantize(outlay - fair - got + gave),
                document_count=doc_counts.get(partner.id, 0),
            )
        )

    return BalanceReport(
        base_currency=settings.base_currency,
        period_start=period_start,
        period_end=period_end,
        total_personal_outlay=total_personal,
        total_business_outlay=quantize(sum(business.values(), ZERO)),
        total_unverified=quantize(sum(unverified.values(), ZERO)),
        partners=balances,
        suggested_settlements=suggest_settlements(balances),
        excluded_document_count=int(excluded),
    )


def suggest_settlements(balances: list[PartnerBalance]) -> list[SettlementSuggestion]:
    """Smallest set of transfers that flattens everyone to zero.

    Greedy largest-debtor-pays-largest-creditor. For n partners this needs at
    most n-1 transfers, which is optimal in the number of payments; with two
    partners it is simply "one of you pays the other once".
    """
    creditors = sorted(
        [b for b in balances if b.net_position > SETTLEMENT_EPSILON],
        key=lambda b: b.net_position,
        reverse=True,
    )
    debtors = sorted(
        [b for b in balances if b.net_position < -SETTLEMENT_EPSILON],
        key=lambda b: b.net_position,
    )

    # Work on copies so the report's own numbers are not mutated underneath it.
    owed = {c.user_id: c.net_position for c in creditors}
    owes = {d.user_id: -d.net_position for d in debtors}
    names = {b.user_id: b.display_name for b in balances}

    suggestions: list[SettlementSuggestion] = []
    ci = di = 0
    while ci < len(creditors) and di < len(debtors):
        creditor, debtor = creditors[ci], debtors[di]
        amount = min(owed[creditor.user_id], owes[debtor.user_id])
        if amount > SETTLEMENT_EPSILON:
            suggestions.append(
                SettlementSuggestion(
                    from_user_id=debtor.user_id,
                    from_display_name=names[debtor.user_id],
                    to_user_id=creditor.user_id,
                    to_display_name=names[creditor.user_id],
                    amount=quantize(amount),
                )
            )
            owed[creditor.user_id] -= amount
            owes[debtor.user_id] -= amount

        if owed[creditor.user_id] <= SETTLEMENT_EPSILON:
            ci += 1
        if owes[debtor.user_id] <= SETTLEMENT_EPSILON:
            di += 1

    return suggestions

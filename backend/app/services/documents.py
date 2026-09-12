"""Writing extraction results and human corrections onto a document row."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ai.extract import ExtractionResult
from app.config import settings
from app.models import Document, DocumentKind, DocumentStatus, LineItem, User
from app.schemas import DocumentUpdate, LineItemIn
from app.services.money import MissingRate, value_in_base

log = logging.getLogger(__name__)


def apply_extraction(db: Session, document: Document, result: ExtractionResult) -> Document:
    """Write what the model read onto the document, then decide its status.

    Human-entered values are never overwritten: if somebody already typed a
    total in while the scan was queued, their number wins.
    """
    document.ai_model = result.model_name
    document.ai_confidence = result.confidence
    document.ai_raw = result.raw_payload()
    document.ai_error = None
    document.scanned_at = datetime.now(UTC)

    if document.status == DocumentStatus.CONFIRMED:
        # Somebody verified this by hand while the scan was in flight. Keep the
        # machine reading for the audit trail and change nothing else.
        log.info("Document %s was confirmed during scanning; keeping human values", document.id)
        db.flush()
        return document

    _fill_if_empty(document, "merchant_name", result.merchant_name)
    _fill_if_empty(document, "merchant_tax_id", result.merchant_tax_id)
    _fill_if_empty(document, "document_date", result.document_date)
    _fill_if_empty(document, "title", result.title)
    _fill_if_empty(document, "currency", result.currency or settings.base_currency)
    _fill_if_empty(document, "subtotal", result.subtotal)
    _fill_if_empty(document, "tax_total", result.tax_total)
    _fill_if_empty(document, "total", result.total)

    if result.line_items and not document.line_items:
        _replace_line_items(
            db,
            document,
            [
                LineItemIn(
                    description=item["description"],
                    quantity=item["quantity"],
                    unit_price=item["unit_price"],
                    line_total=item["line_total"],
                    vat_rate=item["vat_rate"],
                )
                for item in result.line_items
            ],
        )

    rate_problem = recompute_base(db, document)
    document.status = _decide_status(document, result, rate_problem)
    db.flush()
    return document


def _decide_status(
    document: Document, result: ExtractionResult, rate_problem: str | None
) -> DocumentStatus:
    if document.kind == DocumentKind.OBJECT_LIST:
        # An object list has no total to get wrong; anything transcribed at all
        # is a success, and the items are reviewable on screen anyway.
        return DocumentStatus.PARSED if result.line_items else DocumentStatus.NEEDS_REVIEW

    if document.total is None or rate_problem is not None:
        return DocumentStatus.NEEDS_REVIEW
    if result.confidence < settings.review_confidence_threshold:
        return DocumentStatus.NEEDS_REVIEW
    return DocumentStatus.PARSED


def apply_update(
    db: Session, document: Document, payload: DocumentUpdate, actor: User
) -> Document:
    """Apply a human's corrections and mark the document verified.

    Any edit through this path counts as a person vouching for the numbers, so
    the document lands in CONFIRMED - that is the whole point of the review
    screen, and it is what moves an amount from "unverified" into the balance
    proper.
    """
    data = payload.model_dump(exclude_unset=True)
    line_items = data.pop("line_items", None)

    # Only honour an fx rate the caller sent in THIS request. Reusing the rate
    # already stored on the row would be a silent money bug: correcting a
    # receipt's currency from EUR to USD would keep applying the euro rate to
    # the dollar amount, producing a wrong total with no error anywhere.
    explicit_rate = data.get("fx_rate")

    for attribute, value in data.items():
        setattr(document, attribute, value)

    if line_items is not None:
        _replace_line_items(db, document, [LineItemIn(**item) for item in line_items])

    rate_problem = recompute_base(db, document, explicit_rate=explicit_rate)

    if rate_problem is not None:
        document.status = DocumentStatus.NEEDS_REVIEW
        document.ai_error = rate_problem
    elif document.kind == DocumentKind.RECEIPT and document.total is None:
        document.status = DocumentStatus.NEEDS_REVIEW
    else:
        document.status = DocumentStatus.CONFIRMED
        document.confirmed_by_id = actor.id
        document.confirmed_at = datetime.now(UTC)
        document.ai_error = None

    db.flush()
    return document


def requeue(document: Document) -> Document:
    """Send a document back to the scan worker for another try."""
    document.status = DocumentStatus.PENDING
    document.scan_attempts = 0
    document.ai_error = None
    return document


def recompute_base(
    db: Session, document: Document, explicit_rate: Decimal | None = None
) -> str | None:
    """Refresh `fx_rate` and `total_base`. Returns a message if it could not.

    A missing rate is not an exception here: the receipt is still perfectly
    valid, it just cannot be valued in the base currency until somebody adds
    the rate. The document stays put and says so.
    """
    if document.total is None:
        document.fx_rate = None
        document.total_base = None
        return None

    try:
        rate, base = value_in_base(
            db,
            amount=Decimal(document.total),
            currency=document.currency,
            on=document.document_date or _created_date(document),
            explicit_rate=Decimal(explicit_rate) if explicit_rate is not None else None,
        )
    except MissingRate as exc:
        document.fx_rate = None
        document.total_base = None
        return str(exc)

    document.fx_rate = rate
    document.total_base = base
    return None


def _created_date(document: Document) -> date:
    created = document.created_at
    return created.date() if created else date.today()


def _fill_if_empty(document: Document, attribute: str, value: object) -> None:
    if value is None:
        return
    if getattr(document, attribute, None) in (None, ""):
        setattr(document, attribute, value)


def _replace_line_items(db: Session, document: Document, items: list[LineItemIn]) -> None:
    """Swap the whole set of line items.

    Replacing wholesale rather than diffing is the right call here: the review
    screen sends the complete list it is showing, and a partial merge would
    make deleting a spurious row impossible.
    """
    document.line_items.clear()
    db.flush()  # emit the DELETEs before the INSERTs reuse line_no values

    for index, item in enumerate(items):
        document.line_items.append(
            LineItem(
                line_no=index,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
                vat_rate=item.vat_rate,
                category=item.category,
            )
        )

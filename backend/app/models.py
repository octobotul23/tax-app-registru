"""Database schema.

The domain in one paragraph: two partners photograph receipts. Each receipt is
tagged with a *funding source* - BUSINESS money or a partner's PERSONAL money.
Business-funded purchases are recorded for the books but create no debt. A
personal-funded purchase means the business owes that partner. The balance page
nets those claims out and subtracts any settlements already paid.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class FundingSource(str, enum.Enum):
    """Whose money left the account."""

    BUSINESS = "BUSINESS"   # company funds - recorded, but nobody is owed anything
    PERSONAL = "PERSONAL"   # a partner's own money - the business owes them back


class DocumentKind(str, enum.Enum):
    RECEIPT = "RECEIPT"          # a till receipt or invoice with money on it
    OBJECT_LIST = "OBJECT_LIST"  # a photographed inventory or stock list


class DocumentStatus(str, enum.Enum):
    PENDING = "PENDING"            # stored, queued for the scan worker
    PROCESSING = "PROCESSING"      # a worker has claimed it
    PARSED = "PARSED"              # AI read it confidently; not yet human-checked
    NEEDS_REVIEW = "NEEDS_REVIEW"  # AI read it but is unsure - a human must look
    CONFIRMED = "CONFIRMED"        # a human has verified the numbers
    FAILED = "FAILED"              # scanning gave up; enter the numbers by hand


#: Statuses carrying a total we are willing to put into a balance.
COUNTABLE_STATUSES = (
    DocumentStatus.PARSED,
    DocumentStatus.NEEDS_REVIEW,
    DocumentStatus.CONFIRMED,
)

#: Of those, the ones a human has not vouched for yet. Reported separately so
#: nobody mistakes a machine guess for a verified figure.
UNVERIFIED_STATUSES = (
    DocumentStatus.PARSED,
    DocumentStatus.NEEDS_REVIEW,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Share of the partnership, used to work out a fair split when equalising
    # who has funded the business out of pocket. Two equal partners: 0.5 each.
    equity_share: Mapped[float] = mapped_column(
        Numeric(6, 5), nullable=False, default=0.5
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    uploaded_documents: Mapped[list["Document"]] = relationship(
        back_populates="uploader", foreign_keys="Document.uploader_id"
    )

    __table_args__ = (
        CheckConstraint(
            "equity_share >= 0 AND equity_share <= 1", name="ck_equity_share_range"
        ),
    )


class Document(Base):
    """One uploaded photograph and whatever we managed to read off it.

    Receipts and object lists share this table because they share an identical
    lifecycle - upload, queue, scan, review - and differ only in which fields
    end up populated. An object list simply leaves the money columns null.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[DocumentKind] = mapped_column(
        Enum(DocumentKind, name="document_kind"), nullable=False, index=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        nullable=False,
        default=DocumentStatus.PENDING,
        index=True,
    )
    funding_source: Mapped[FundingSource] = mapped_column(
        Enum(FundingSource, name="funding_source"), nullable=False, index=True
    )

    # Who photographed it, and whose money actually paid. Usually the same
    # person, but not always - keeping them apart stops the balance from
    # crediting the wrong partner.
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # --- the stored image -------------------------------------------------
    original_filename: Mapped[str | None] = mapped_column(String(512))
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    thumb_path: Mapped[str | None] = mapped_column(String(512))
    image_mime: Mapped[str] = mapped_column(String(80), nullable=False)
    image_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Lets us warn "you already uploaded this photo" without blocking it.
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # --- what the document says -------------------------------------------
    title: Mapped[str | None] = mapped_column(String(255))       # mainly for object lists
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    merchant_tax_id: Mapped[str | None] = mapped_column(String(64))
    document_date: Mapped[date | None] = mapped_column(Date, index=True)

    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal: Mapped[float | None] = mapped_column(Numeric(12, 2))
    tax_total: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total: Mapped[float | None] = mapped_column(Numeric(12, 2))

    # The rate actually applied, frozen at the moment of conversion, plus the
    # resulting base-currency figure. Storing the result - rather than
    # converting at report time - keeps historical balances reproducible.
    fx_rate: Mapped[float | None] = mapped_column(Numeric(18, 8))
    total_base: Mapped[float | None] = mapped_column(Numeric(14, 2), index=True)

    notes: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80), index=True)

    # --- scan bookkeeping -------------------------------------------------
    ai_model: Mapped[str | None] = mapped_column(String(120))
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    ai_raw: Mapped[dict | None] = mapped_column(JSONB)
    ai_error: Mapped[str | None] = mapped_column(Text)
    scan_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Soft delete: nothing in a tax ledger should ever truly vanish.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    uploader: Mapped["User"] = relationship(
        foreign_keys=[uploader_id], back_populates="uploaded_documents"
    )
    payer: Mapped["User"] = relationship(foreign_keys=[payer_id])
    confirmed_by: Mapped["User | None"] = relationship(foreign_keys=[confirmed_by_id])
    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="LineItem.line_no",
    )

    __table_args__ = (
        Index(
            "ix_documents_balance_lookup",
            "payer_id",
            "funding_source",
            "status",
            "deleted_at",
        ),
        Index("ix_documents_feed", "deleted_at", "created_at"),
        CheckConstraint("scan_attempts >= 0", name="ck_scan_attempts_non_negative"),
    )


class LineItem(Base):
    """A single row read off a receipt, or a single entry on an object list.

    Object-list rows leave unit_price and line_total null - the item is being
    recorded, not costed.
    """

    __tablename__ = "line_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    description: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    line_total: Mapped[float | None] = mapped_column(Numeric(12, 2))
    vat_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    category: Mapped[str | None] = mapped_column(String(80))

    document: Mapped["Document"] = relationship(back_populates="line_items")

    __table_args__ = (
        UniqueConstraint("document_id", "line_no", name="uq_line_items_doc_line"),
    )


class ExchangeRate(Base):
    """Manually maintained rates into the base currency.

    Deliberately not fetched from the internet by default: this stack is meant
    to run offline on your own server. Enter the rate the bank actually gave
    you and the books will match your statements.
    """

    __tablename__ = "exchange_rates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    rate_to_base: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("currency", "effective_from", name="uq_rate_currency_date"),
        CheckConstraint("rate_to_base > 0", name="ck_rate_positive"),
    )


class Settlement(Base):
    """A real payment between partners, or from the business to a partner.

    Without this the balance only ever climbs. Recording "I transferred you
    400 RON on the 3rd" is what lets the ledger return to zero.
    """

    __tablename__ = "settlements"

    id: Mapped[uuid.UUID] = _uuid_pk()
    from_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_base: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    settled_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(String(512))

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    from_user: Mapped["User"] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped["User"] = relationship(foreign_keys=[to_user_id])

    __table_args__ = (
        CheckConstraint("amount_base > 0", name="ck_settlement_amount_positive"),
        CheckConstraint(
            "from_user_id <> to_user_id", name="ck_settlement_distinct_parties"
        ),
    )

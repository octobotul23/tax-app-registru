"""Pydantic request and response models.

Money crosses this boundary as `Decimal`, never `float`. A float cannot hold
19.99 exactly, and a ledger that drifts by a bani per receipt is worse than no
ledger at all.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import DocumentKind, DocumentStatus, FundingSource

ORM = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    model_config = ORM

    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool
    is_active: bool
    equity_share: Decimal
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    is_admin: bool = False
    equity_share: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    is_admin: bool | None = None
    equity_share: Decimal | None = Field(default=None, ge=0, le=1)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------

class LineItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=512)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100)
    category: str | None = Field(default=None, max_length=80)


class LineItemOut(LineItemIn):
    model_config = ORM

    id: uuid.UUID
    line_no: int


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DocumentSummary(BaseModel):
    """Row shape for the document feed - deliberately without line items."""

    model_config = ORM

    id: uuid.UUID
    kind: DocumentKind
    status: DocumentStatus
    funding_source: FundingSource
    uploader_id: uuid.UUID
    payer_id: uuid.UUID
    title: str | None
    merchant_name: str | None
    document_date: date | None
    currency: str | None
    total: Decimal | None
    total_base: Decimal | None
    category: str | None
    ai_confidence: float | None
    image_bytes: int
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    model_config = ORM

    original_filename: str | None
    image_mime: str
    merchant_tax_id: str | None
    subtotal: Decimal | None
    tax_total: Decimal | None
    fx_rate: Decimal | None
    notes: str | None
    ai_model: str | None
    ai_error: str | None
    scan_attempts: int
    scanned_at: datetime | None
    confirmed_by_id: uuid.UUID | None
    confirmed_at: datetime | None
    line_items: list[LineItemOut] = []


class DocumentUpdate(BaseModel):
    """Human corrections applied on top of whatever the AI read.

    Every field is optional: the review screen sends only what changed. Setting
    any money field re-derives `total_base` from the applicable rate.
    """

    funding_source: FundingSource | None = None
    payer_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=255)
    merchant_name: str | None = Field(default=None, max_length=255)
    merchant_tax_id: str | None = Field(default=None, max_length=64)
    document_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    subtotal: Decimal | None = None
    tax_total: Decimal | None = None
    total: Decimal | None = None
    fx_rate: Decimal | None = Field(default=None, gt=0)
    notes: str | None = None
    category: str | None = Field(default=None, max_length=80)
    line_items: list[LineItemIn] | None = None

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class DocumentPage(BaseModel):
    """One page of the document feed, plus the total so the UI can paginate."""

    items: list[DocumentSummary]
    total: int
    limit: int
    offset: int


class UploadResult(BaseModel):
    document: DocumentDetail
    #: True when an identical photo already exists. The upload still succeeds -
    #: this is a warning for the UI, not a rejection.
    duplicate_of: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------

class ExchangeRateIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    rate_to_base: Decimal = Field(gt=0)
    effective_from: date
    note: str | None = Field(default=None, max_length=255)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class ExchangeRateOut(ExchangeRateIn):
    model_config = ORM

    id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------

class SettlementIn(BaseModel):
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    amount_base: Decimal = Field(gt=0)
    settled_on: date
    note: str | None = Field(default=None, max_length=512)


class SettlementOut(SettlementIn):
    model_config = ORM

    id: uuid.UUID
    created_by_id: uuid.UUID | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Balance report
# ---------------------------------------------------------------------------

class PartnerBalance(BaseModel):
    user_id: uuid.UUID
    display_name: str
    equity_share: Decimal

    #: Spent from this partner's own pocket on business things.
    personal_outlay: Decimal
    #: Spent by this partner using company money. Tracked, but owed to nobody.
    business_outlay: Decimal
    #: Of `personal_outlay`, how much rests on an unreviewed machine reading.
    unverified_outlay: Decimal
    #: What this partner should have carried, given their equity share.
    fair_share: Decimal
    #: Settlements already paid out to / received by this partner.
    settlements_received: Decimal
    settlements_paid: Decimal
    #: personal_outlay - fair_share - net settlements.
    #: Positive: the partnership still owes them. Negative: they owe it.
    net_position: Decimal
    document_count: int


class SettlementSuggestion(BaseModel):
    """A concrete transfer that would flatten the balance."""

    from_user_id: uuid.UUID
    from_display_name: str
    to_user_id: uuid.UUID
    to_display_name: str
    amount: Decimal


class BalanceReport(BaseModel):
    base_currency: str
    period_start: date | None
    period_end: date | None

    total_personal_outlay: Decimal
    total_business_outlay: Decimal
    total_unverified: Decimal

    partners: list[PartnerBalance]
    suggested_settlements: list[SettlementSuggestion]

    #: Count of documents excluded from the figures because they are still
    #: queued, mid-scan, or failed to scan. Shown so a balance is never
    #: quietly incomplete.
    excluded_document_count: int


class CategoryTotal(BaseModel):
    category: str | None
    funding_source: FundingSource
    total_base: Decimal
    document_count: int


class DashboardSummary(BaseModel):
    base_currency: str
    pending_scans: int
    needs_review: int
    failed_scans: int
    receipts_this_month: int
    spend_this_month: Decimal
    top_categories: list[CategoryTotal]

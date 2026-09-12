"""Initial schema: users, documents, line items, exchange rates, settlements.

Revision ID: 0001
Revises:
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Created explicitly with create_type=False on the columns below, so the type
# exists exactly once even though three tables reference it.
document_kind = postgresql.ENUM(
    "RECEIPT", "OBJECT_LIST", name="document_kind", create_type=False
)
document_status = postgresql.ENUM(
    "PENDING",
    "PROCESSING",
    "PARSED",
    "NEEDS_REVIEW",
    "CONFIRMED",
    "FAILED",
    name="document_status",
    create_type=False,
)
funding_source = postgresql.ENUM(
    "BUSINESS", "PERSONAL", name="funding_source", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    document_kind.create(bind, checkfirst=True)
    document_status.create(bind, checkfirst=True)
    funding_source.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "equity_share", sa.Numeric(6, 5), nullable=False, server_default="0.5"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "equity_share >= 0 AND equity_share <= 1", name="ck_equity_share_range"
        ),
    )

    op.create_table(
        "exchange_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rate_to_base", sa.Numeric(18, 8), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("note", sa.String(255)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("currency", "effective_from", name="uq_rate_currency_date"),
        sa.CheckConstraint("rate_to_base > 0", name="ck_rate_positive"),
    )
    op.create_index("ix_exchange_rates_currency", "exchange_rates", ["currency"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", document_kind, nullable=False),
        sa.Column("status", document_status, nullable=False),
        sa.Column("funding_source", funding_source, nullable=False),
        sa.Column(
            "uploader_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(512)),
        sa.Column("image_path", sa.String(512), nullable=False),
        sa.Column("thumb_path", sa.String(512)),
        sa.Column("image_mime", sa.String(80), nullable=False),
        sa.Column("image_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("merchant_name", sa.String(255)),
        sa.Column("merchant_tax_id", sa.String(64)),
        sa.Column("document_date", sa.Date()),
        sa.Column("currency", sa.String(3)),
        sa.Column("subtotal", sa.Numeric(12, 2)),
        sa.Column("tax_total", sa.Numeric(12, 2)),
        sa.Column("total", sa.Numeric(12, 2)),
        sa.Column("fx_rate", sa.Numeric(18, 8)),
        sa.Column("total_base", sa.Numeric(14, 2)),
        sa.Column("notes", sa.Text()),
        sa.Column("category", sa.String(80)),
        sa.Column("ai_model", sa.String(120)),
        sa.Column("ai_confidence", sa.Float()),
        sa.Column("ai_raw", postgresql.JSONB()),
        sa.Column("ai_error", sa.Text()),
        sa.Column("scan_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scanned_at", sa.DateTime(timezone=True)),
        sa.Column(
            "confirmed_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("scan_attempts >= 0", name="ck_scan_attempts_non_negative"),
    )

    for column in (
        "kind",
        "status",
        "funding_source",
        "uploader_id",
        "payer_id",
        "image_sha256",
        "document_date",
        "total_base",
        "category",
        "deleted_at",
    ):
        op.create_index(f"ix_documents_{column}", "documents", [column])

    # The index the balance report actually uses: it sums by payer and funding
    # source over live rows, so leading with payer_id lets Postgres answer the
    # whole query from this one index.
    op.create_index(
        "ix_documents_balance_lookup",
        "documents",
        ["payer_id", "funding_source", "status", "deleted_at"],
    )
    op.create_index("ix_documents_feed", "documents", ["deleted_at", "created_at"])

    op.create_table(
        "line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("unit_price", sa.Numeric(12, 2)),
        sa.Column("line_total", sa.Numeric(12, 2)),
        sa.Column("vat_rate", sa.Numeric(5, 2)),
        sa.Column("category", sa.String(80)),
        sa.UniqueConstraint("document_id", "line_no", name="uq_line_items_doc_line"),
    )
    op.create_index("ix_line_items_document_id", "line_items", ["document_id"])

    op.create_table(
        "settlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "from_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "to_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("settled_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(512)),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_base > 0", name="ck_settlement_amount_positive"),
        sa.CheckConstraint(
            "from_user_id <> to_user_id", name="ck_settlement_distinct_parties"
        ),
    )
    op.create_index("ix_settlements_from_user_id", "settlements", ["from_user_id"])
    op.create_index("ix_settlements_to_user_id", "settlements", ["to_user_id"])
    op.create_index("ix_settlements_settled_on", "settlements", ["settled_on"])


def downgrade() -> None:
    op.drop_table("settlements")
    op.drop_table("line_items")
    op.drop_table("documents")
    op.drop_table("exchange_rates")
    op.drop_table("users")

    bind = op.get_bind()
    funding_source.drop(bind, checkfirst=True)
    document_status.drop(bind, checkfirst=True)
    document_kind.drop(bind, checkfirst=True)

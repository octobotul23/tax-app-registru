"""First-run setup: schema, owner account, sane starting rates."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import ExchangeRate, User
from app.security import hash_password

log = logging.getLogger(__name__)


def run_migrations() -> None:
    """Bring the database up to the latest revision."""
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
    log.info("Database schema is up to date")


def ensure_owner_account() -> None:
    """Create the first account from the environment, once.

    Only ever runs against an empty users table, so restarting the container
    cannot resurrect a deleted account or reset a changed password.
    """
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        return

    with SessionLocal() as db:
        existing = db.execute(select(func.count(User.id))).scalar_one()
        if existing:
            return

        owner = User(
            email=settings.bootstrap_admin_email.lower(),
            password_hash=hash_password(settings.bootstrap_admin_password),
            display_name=settings.bootstrap_admin_name,
            is_admin=True,
            # 0.5, not 1. Fair shares are normalised by the sum across active
            # partners, so a lone owner still comes out at 100% - and adding
            # the partner later gives an even split with no correction step.
            equity_share=Decimal("0.5"),
        )
        db.add(owner)
        db.commit()
        log.warning(
            "Created the owner account %s from environment variables. "
            "Change this password after signing in.",
            owner.email,
        )


def seed_starting_rates() -> None:
    """Put a placeholder rate in for each non-base currency.

    A wrong-but-present rate is better than a missing one here: a missing rate
    blocks a receipt from being valued at all, whereas a placeholder gets the
    receipt into the books with a number you can correct in Settings. The note
    on the row says loudly that it is a placeholder.
    """
    placeholders = {"EUR": "5.00", "USD": "4.60"}

    with SessionLocal() as db:
        for code in settings.currencies:
            if code == settings.base_currency or code not in placeholders:
                continue
            exists = db.execute(
                select(func.count(ExchangeRate.id)).where(ExchangeRate.currency == code)
            ).scalar_one()
            if exists:
                continue
            db.add(
                ExchangeRate(
                    currency=code,
                    rate_to_base=placeholders[code],
                    effective_from=date(2020, 1, 1),
                    note="PLACEHOLDER - replace with your real rate in Settings",
                )
            )
        db.commit()

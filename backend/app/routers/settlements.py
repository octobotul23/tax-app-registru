"""Recording real transfers between partners.

This is what lets the balance go back to zero. Without it the ledger only ever
counts upward and stops meaning anything the first time you square up.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Settlement, User
from app.schemas import SettlementIn, SettlementOut

router = APIRouter(prefix="/api/settlements", tags=["settlements"])


@router.get("", response_model=list[SettlementOut])
def list_settlements(db: DbSession, _: CurrentUser) -> list[Settlement]:
    return list(
        db.execute(
            select(Settlement)
            .where(Settlement.deleted_at.is_(None))
            .order_by(Settlement.settled_on.desc(), Settlement.created_at.desc())
        ).scalars()
    )


@router.post("", response_model=SettlementOut, status_code=status.HTTP_201_CREATED)
def create_settlement(
    payload: SettlementIn, db: DbSession, user: CurrentUser
) -> Settlement:
    if payload.from_user_id == payload.to_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A settlement needs two different people",
        )

    for party in (payload.from_user_id, payload.to_user_id):
        if db.get(User, party) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No such user"
            )

    settlement = Settlement(
        from_user_id=payload.from_user_id,
        to_user_id=payload.to_user_id,
        amount_base=payload.amount_base,
        settled_on=payload.settled_on,
        note=payload.note,
        created_by_id=user.id,
    )
    db.add(settlement)
    db.commit()
    db.refresh(settlement)
    return settlement


@router.delete("/{settlement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_settlement(settlement_id: uuid.UUID, db: DbSession, _: CurrentUser) -> None:
    """Soft delete, so a mistaken entry can be undone without losing history."""
    settlement = db.execute(
        select(Settlement).where(
            Settlement.id == settlement_id, Settlement.deleted_at.is_(None)
        )
    ).scalar_one_or_none()
    if settlement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No such settlement"
        )
    settlement.deleted_at = datetime.now(UTC)
    db.commit()

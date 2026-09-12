"""Partner accounts.

There is no public registration endpoint. The first account is created from
environment variables at startup; that owner then creates the partner account
here. On a server reachable from the internet, an open /register is how you end
up sharing your books with a stranger.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.deps import AdminUser, CurrentUser, DbSession
from app.models import User
from app.schemas import UserCreate, UserOut, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: DbSession, _: CurrentUser) -> list[User]:
    """Every partner. Needed by the UI to attribute a receipt to a payer."""
    return list(db.execute(select(User).order_by(User.created_at)).scalars())


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession, _: AdminUser) -> User:
    exists = db.execute(
        select(User.id).where(func.lower(User.email) == payload.email.lower())
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        is_admin=payload.is_admin,
        equity_share=payload.equity_share,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, payload: UserUpdate, db: DbSession, actor: AdminUser
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")

    data = payload.model_dump(exclude_unset=True)

    # Guard against the two ways an admin can lock everyone out of the books.
    if user.id == actor.id:
        if data.get("is_admin") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot remove your own administrator rights",
            )
        if data.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account",
            )

    if data.get("is_active") is False:
        remaining = db.execute(
            select(func.count(User.id)).where(User.is_active.is_(True), User.id != user.id)
        ).scalar_one()
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one account must stay active",
            )

    for attribute, value in data.items():
        setattr(user, attribute, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(user_id: uuid.UUID, db: DbSession, actor: AdminUser) -> None:
    """Deactivate rather than delete.

    A partner who has ever paid for something is referenced by every receipt
    they funded. Removing the row would either orphan those receipts or cascade
    away part of the ledger, so accounts are switched off instead.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
    if user.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )

    remaining = db.execute(
        select(func.count(User.id)).where(User.is_active.is_(True), User.id != user.id)
    ).scalar_one()
    if remaining == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one account must stay active",
        )

    user.is_active = False
    db.commit()

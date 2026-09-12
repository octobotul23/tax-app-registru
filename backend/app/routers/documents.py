"""Uploading, listing, reviewing and correcting documents."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbSession
from app.models import (
    Document,
    DocumentKind,
    DocumentStatus,
    FundingSource,
    LineItem,
    User,
)
from app.schemas import (
    DocumentDetail,
    DocumentPage,
    DocumentUpdate,
    UploadResult,
)
from app.services import documents as doc_service
from app.services.storage import InvalidImage, absolute_path, save_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Browsers must not cache a receipt image in a shared proxy; it is private
# financial data. `private` plus a short max-age keeps scrolling snappy without
# leaving copies anywhere but the user's own browser.
_IMAGE_CACHE = "private, max-age=3600"


@router.post("", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_document(
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(..., description="Photograph of the receipt or list"),
    kind: DocumentKind = Form(DocumentKind.RECEIPT),
    funding_source: FundingSource = Form(...),
    payer_id: uuid.UUID | None = Form(None),
    title: str | None = Form(None),
    notes: str | None = Form(None),
) -> UploadResult:
    """Store a photograph and queue it for scanning.

    Returns as soon as the image is safely on disk. Reading it takes seconds to
    minutes depending on hardware, so that happens in the worker - an upload
    that blocked on the model would time out on a phone connection.
    """
    payer = _resolve_payer(db, user, payer_id)

    raw = await file.read()
    try:
        stored = save_upload(raw, file.filename)
    except InvalidImage as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    duplicate_of = db.execute(
        select(Document.id)
        .where(Document.image_sha256 == stored.sha256, Document.deleted_at.is_(None))
        .limit(1)
    ).scalar_one_or_none()

    document = Document(
        kind=kind,
        status=DocumentStatus.PENDING,
        funding_source=funding_source,
        uploader_id=user.id,
        payer_id=payer.id,
        original_filename=file.filename,
        image_path=stored.image_path,
        thumb_path=stored.thumb_path,
        image_mime=stored.mime,
        image_bytes=stored.size_bytes,
        image_sha256=stored.sha256,
        title=title,
        notes=notes,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    return UploadResult(
        document=DocumentDetail.model_validate(document),
        duplicate_of=duplicate_of,
    )


@router.get("", response_model=DocumentPage)
def list_documents(
    db: DbSession,
    _: CurrentUser,
    kind: DocumentKind | None = None,
    funding_source: FundingSource | None = None,
    doc_status: DocumentStatus | None = Query(None, alias="status"),
    payer_id: uuid.UUID | None = None,
    uploader_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DocumentPage:
    query = select(Document).where(Document.deleted_at.is_(None))
    query = _apply_filters(
        query,
        kind=kind,
        funding_source=funding_source,
        doc_status=doc_status,
        payer_id=payer_id,
        uploader_id=uploader_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    rows = db.execute(
        query.order_by(
            func.coalesce(Document.document_date, func.date(Document.created_at)).desc(),
            Document.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).scalars()

    return DocumentPage(
        items=list(rows), total=int(total), limit=limit, offset=offset
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, db: DbSession, _: CurrentUser) -> Document:
    document = db.execute(
        select(Document)
        .options(selectinload(Document.line_items))
        .where(Document.id == document_id, Document.deleted_at.is_(None))
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such document")
    return document


@router.patch("/{document_id}", response_model=DocumentDetail)
def update_document(
    document_id: uuid.UUID, payload: DocumentUpdate, db: DbSession, user: CurrentUser
) -> Document:
    """Apply corrections. Saving marks the document verified by this user."""
    document = _load(db, document_id)

    if payload.payer_id is not None and db.get(User, payload.payer_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No such payer"
        )

    doc_service.apply_update(db, document, payload, user)
    db.commit()
    db.refresh(document)
    return document


@router.post("/{document_id}/rescan", response_model=DocumentDetail)
def rescan_document(document_id: uuid.UUID, db: DbSession, _: CurrentUser) -> Document:
    """Put a document back in the queue - after swapping the model, say."""
    document = _load(db, document_id)
    doc_service.requeue(document)
    db.commit()
    db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, db: DbSession, _: CurrentUser) -> None:
    """Soft delete: the row and the photograph both stay on disk.

    Deleting for real would make an already-printed balance impossible to
    reproduce, which is exactly what you do not want from a book of account.
    """
    document = _load(db, document_id)
    document.deleted_at = datetime.now(UTC)
    db.commit()


@router.get("/{document_id}/image")
def document_image(document_id: uuid.UUID, db: DbSession, _: CurrentUser) -> Response:
    return _serve(_load(db, document_id), thumb=False)


@router.get("/{document_id}/thumbnail")
def document_thumbnail(document_id: uuid.UUID, db: DbSession, _: CurrentUser) -> Response:
    return _serve(_load(db, document_id), thumb=True)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load(db: DbSession, document_id: uuid.UUID) -> Document:
    document = db.execute(
        select(Document)
        .options(selectinload(Document.line_items))
        .where(Document.id == document_id, Document.deleted_at.is_(None))
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such document")
    return document


def _resolve_payer(db: DbSession, user: User, payer_id: uuid.UUID | None) -> User:
    """Who actually paid. Defaults to the uploader, which is the common case."""
    if payer_id is None or payer_id == user.id:
        return user
    payer = db.get(User, payer_id)
    if payer is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No such payer"
        )
    return payer


def _serve(document: Document, thumb: bool) -> Response:
    relative = document.thumb_path if thumb else document.image_path
    if not relative:
        relative = document.image_path

    try:
        data = absolute_path(relative).read_bytes()
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The image file is missing from storage",
        ) from exc

    return Response(
        content=data,
        media_type=document.image_mime or "image/jpeg",
        headers={
            "Cache-Control": _IMAGE_CACHE,
            "Content-Disposition": f'inline; filename="{document.id}.jpg"',
        },
    )


def _apply_filters(
    query: Select,
    *,
    kind: DocumentKind | None,
    funding_source: FundingSource | None,
    doc_status: DocumentStatus | None,
    payer_id: uuid.UUID | None,
    uploader_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    search: str | None,
) -> Select:
    effective_date = func.coalesce(Document.document_date, func.date(Document.created_at))

    if kind is not None:
        query = query.where(Document.kind == kind)
    if funding_source is not None:
        query = query.where(Document.funding_source == funding_source)
    if doc_status is not None:
        query = query.where(Document.status == doc_status)
    if payer_id is not None:
        query = query.where(Document.payer_id == payer_id)
    if uploader_id is not None:
        query = query.where(Document.uploader_id == uploader_id)
    if date_from is not None:
        query = query.where(effective_date >= date_from)
    if date_to is not None:
        query = query.where(effective_date <= date_to)

    if search:
        pattern = f"%{search.strip()}%"
        # `.any()` builds a correlated EXISTS, so a receipt matches when any one
        # of its lines does - that is what makes searching "cement" find the
        # receipt that has cement on line 4.
        query = query.where(
            or_(
                Document.merchant_name.ilike(pattern),
                Document.title.ilike(pattern),
                Document.notes.ilike(pattern),
                Document.category.ilike(pattern),
                Document.line_items.any(LineItem.description.ilike(pattern)),
            )
        )
    return query

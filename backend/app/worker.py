"""Background scan worker.

Runs as its own container so a slow or wedged model call can never make the API
unresponsive. The queue is just the documents table: Postgres with
`FOR UPDATE SKIP LOCKED` is a perfectly good job broker at this scale, and it
saves running Redis and Celery to move a handful of receipts a day.

    python -m app.worker
"""

from __future__ import annotations

import logging
import signal
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.extract import extract_document
from app.ai.ollama import OllamaClient, OllamaError
from app.config import settings
from app.db import SessionLocal
from app.models import Document, DocumentStatus
from app.services.documents import apply_extraction
from app.services.storage import read_bytes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s worker: %(message)s",
)
log = logging.getLogger("worker")

#: A document stuck in PROCESSING longer than this had its worker die under it.
STALE_CLAIM_AFTER = timedelta(minutes=30)

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    log.info("Signal %s received - finishing the current document, then stopping", signum)
    _shutdown = True


def claim_next(db: Session) -> uuid.UUID | None:
    """Atomically take ownership of one queued document.

    SKIP LOCKED is what makes this safe to run in more than one process: a
    worker steps over rows another worker has already locked rather than
    blocking on them or, worse, scanning the same receipt twice.
    """
    candidate = (
        select(Document.id)
        .where(Document.status == DocumentStatus.PENDING, Document.deleted_at.is_(None))
        .order_by(Document.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )

    claimed = db.execute(
        update(Document)
        .where(Document.id == candidate)
        .values(status=DocumentStatus.PROCESSING, updated_at=datetime.now(UTC))
        .returning(Document.id)
    ).scalar_one_or_none()

    db.commit()
    return claimed


def release_stale_claims(db: Session) -> int:
    """Requeue documents whose worker died mid-scan.

    Without this, a container restart at the wrong moment strands a receipt in
    PROCESSING forever and it silently never enters the books.
    """
    cutoff = datetime.now(UTC) - STALE_CLAIM_AFTER
    released = db.execute(
        update(Document)
        .where(
            Document.status == DocumentStatus.PROCESSING,
            Document.updated_at < cutoff,
        )
        .values(status=DocumentStatus.PENDING)
        .returning(Document.id)
    ).all()
    db.commit()
    if released:
        log.warning("Requeued %d document(s) abandoned by a previous worker", len(released))
    return len(released)


def process_one(db: Session, document_id: uuid.UUID, client: OllamaClient) -> None:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        return

    document.scan_attempts += 1
    attempt = document.scan_attempts
    started = time.monotonic()

    try:
        image = read_bytes(document.image_path)
    except OSError as exc:
        log.error("Document %s: image missing from storage (%s)", document_id, exc)
        document.status = DocumentStatus.FAILED
        document.ai_error = f"The stored image could not be read: {exc}"
        db.commit()
        return

    try:
        result = extract_document(image, document.kind, client=client)
    except OllamaError as exc:
        _handle_failure(db, document, str(exc), attempt)
        return
    except Exception as exc:  # noqa: BLE001 - a worker must never die on one bad row
        log.exception("Document %s: unexpected error during extraction", document_id)
        _handle_failure(db, document, f"Unexpected error: {exc}", attempt)
        return

    apply_extraction(db, document, result)
    db.commit()

    log.info(
        "Document %s scanned in %.1fs - status=%s confidence=%.2f total=%s %s",
        document_id,
        time.monotonic() - started,
        document.status.value,
        result.confidence,
        document.total,
        document.currency or "",
    )


def _handle_failure(db: Session, document: Document, message: str, attempt: int) -> None:
    """Retry, or give up and let a human type the numbers in."""
    document.ai_error = message

    if attempt >= settings.worker_max_attempts:
        document.status = DocumentStatus.FAILED
        log.error(
            "Document %s failed after %d attempt(s): %s", document.id, attempt, message
        )
    else:
        document.status = DocumentStatus.PENDING
        log.warning(
            "Document %s attempt %d/%d failed, will retry: %s",
            document.id,
            attempt,
            settings.worker_max_attempts,
            message,
        )
    db.commit()


def wait_for_model(client: OllamaClient, attempts: int = 60) -> bool:
    """Give Ollama time to come up and finish pulling the model."""
    for attempt in range(attempts):
        if client.health():
            installed = client.installed_models()
            wanted = client.model.split(":")[0]
            if any(name.split(":")[0] == wanted for name in installed):
                log.info("Model %s is ready", client.model)
                return True
            log.info(
                "Ollama is up but %s is not pulled yet (attempt %d/%d)",
                client.model,
                attempt + 1,
                attempts,
            )
        else:
            log.info("Waiting for Ollama at %s (attempt %d/%d)",
                     client.base_url, attempt + 1, attempts)
        time.sleep(5)
    return False


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    client = OllamaClient()
    log.info("Scan worker starting - model=%s at %s", client.model, client.base_url)

    if not wait_for_model(client):
        # Not fatal: the model may finish pulling later, and uploads keep
        # queueing regardless. Say so loudly and carry on polling.
        log.error(
            "Model %s is still unavailable. Uploads will queue until it is "
            "pulled: docker compose exec ollama ollama pull %s",
            client.model,
            client.model,
        )

    with SessionLocal() as db:
        release_stale_claims(db)

    idle_cycles = 0
    while not _shutdown:
        try:
            with SessionLocal() as db:
                document_id = claim_next(db)
                if document_id is None:
                    idle_cycles += 1
                    # Sweep for abandoned claims occasionally, not every tick.
                    if idle_cycles % 60 == 0:
                        release_stale_claims(db)
                    time.sleep(settings.worker_poll_seconds)
                    continue

                idle_cycles = 0
                process_one(db, document_id, client)

        except KeyboardInterrupt:
            break
        except Exception:  # noqa: BLE001 - keep the loop alive through anything
            log.exception("Worker loop error - backing off before retrying")
            time.sleep(min(60, settings.worker_poll_seconds * 4))

    log.info("Scan worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())

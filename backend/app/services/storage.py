"""Receipt photo storage: validate, normalise, downscale, write to disk.

Images are re-encoded rather than stored as uploaded. That does three useful
things at once: it proves the bytes really are an image, it strips EXIF (so we
are not quietly archiving the GPS coordinates of every shop you visited), and
it caps the size handed to the vision model, which is the slowest step in the
pipeline by an order of magnitude.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings

# Phone cameras produce HEIC by default on iOS. Without this plugin every
# iPhone upload dies with an unhelpful "cannot identify image file".
try:  # pragma: no cover - depends on the optional wheel being installed
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:  # pragma: no cover
    HEIC_SUPPORTED = False

# A decompression bomb is a small file that expands to gigabytes of pixels.
# 80 MP is far beyond any phone camera and well under a dangerous allocation.
Image.MAX_IMAGE_PIXELS = 80_000_000

STORED_MIME = "image/jpeg"
_JPEG_QUALITY = 88
_THUMB_QUALITY = 78


@dataclass(frozen=True)
class StoredImage:
    """Everything the database needs to know about a saved photograph."""

    image_path: str      # relative to settings.storage_dir
    thumb_path: str
    mime: str
    size_bytes: int
    sha256: str
    width: int
    height: int


def storage_root() -> Path:
    root = Path(settings.storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def absolute_path(relative: str) -> Path:
    """Resolve a stored relative path, refusing anything that escapes the root.

    Paths come out of the database rather than straight off a request, but a
    traversal check here costs nothing and closes the hole permanently.
    """
    root = storage_root().resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Refusing to read outside the storage root: {relative!r}")
    return candidate


class InvalidImage(Exception):
    """The uploaded bytes are not an image we can decode."""


def save_upload(raw: bytes, original_filename: str | None = None) -> StoredImage:
    """Validate and store one uploaded photograph.

    Raises InvalidImage if the bytes cannot be decoded as a picture.
    """
    if not raw:
        raise InvalidImage("The uploaded file is empty")
    if len(raw) > settings.max_upload_bytes:
        raise InvalidImage(
            f"File is larger than the {settings.max_upload_mb} MB limit"
        )

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()  # cheap structural check; consumes the file object
        with Image.open(io.BytesIO(raw)) as img:
            # Phones record rotation in EXIF rather than rotating the pixels.
            # Without this, half the receipts reach the model sideways.
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            full = _fit(img, settings.image_max_edge)
            thumb = _fit(img, settings.thumb_max_edge)
            full_bytes = _encode(full, _JPEG_QUALITY)
            thumb_bytes = _encode(thumb, _THUMB_QUALITY)
            width, height = full.size
    except UnidentifiedImageError as exc:
        raise InvalidImage(
            "That file is not a picture we can read. Supported: JPEG, PNG, WEBP"
            + (", HEIC" if HEIC_SUPPORTED else " (HEIC support is not installed)")
        ) from exc
    except (OSError, ValueError) as exc:
        raise InvalidImage(f"The image could not be processed: {exc}") from exc

    # Hash the ORIGINAL bytes, not the re-encoded ones: JPEG encoding is not
    # bit-reproducible across Pillow versions, so hashing the output would stop
    # duplicate detection working after an upgrade.
    digest = hashlib.sha256(raw).hexdigest()

    now = datetime.now(UTC)
    folder = f"{now:%Y/%m}"
    stem = uuid.uuid4().hex
    rel_image = f"{folder}/{stem}.jpg"
    rel_thumb = f"{folder}/{stem}_thumb.jpg"

    root = storage_root()
    (root / folder).mkdir(parents=True, exist_ok=True)
    _write_atomic(root / rel_image, full_bytes)
    _write_atomic(root / rel_thumb, thumb_bytes)

    return StoredImage(
        image_path=rel_image,
        thumb_path=rel_thumb,
        mime=STORED_MIME,
        size_bytes=len(full_bytes),
        sha256=digest,
        width=width,
        height=height,
    )


def read_bytes(relative: str) -> bytes:
    return absolute_path(relative).read_bytes()


def delete_quietly(relative: str | None) -> None:
    """Remove a stored file, ignoring the case where it is already gone."""
    if not relative:
        return
    try:
        absolute_path(relative).unlink(missing_ok=True)
    except (ValueError, OSError):
        pass


def _fit(img: Image.Image, max_edge: int) -> Image.Image:
    """Downscale so the longest edge is at most `max_edge`. Never upscales."""
    if max(img.size) <= max_edge:
        return img.copy()
    scale = max_edge / max(img.size)
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(new_size, Image.LANCZOS)


def _encode(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    # No exif= argument, so metadata is dropped on the floor by construction.
    img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file so a crash cannot leave a half-written receipt."""
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)

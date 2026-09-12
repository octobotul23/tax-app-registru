"""Turn a photograph into a structured, *scored* extraction.

The scoring is the important half. A vision model will report high confidence
about a total it hallucinated, so its self-assessment is treated as one weak
opinion among several. The strongest signal available is arithmetic: if the
line items add up to the stated total, something real was read off the page.
If they do not, the extraction goes to a human regardless of how sure the model
claims to be.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.ai.numbers import parse_date, parse_decimal, parse_money
from app.ai.ollama import OllamaClient, OllamaError
from app.ai.prompts import (
    RECEIPT_SCHEMA,
    RECEIPT_SYSTEM,
    object_list_prompt,
    receipt_prompt,
)
from app.config import settings
from app.models import DocumentKind

log = logging.getLogger(__name__)

#: Sums are compared with a tolerance: receipts round per line, so the parts
#: legitimately miss the whole by a few bani.
_ABS_TOLERANCE = Decimal("0.05")
_REL_TOLERANCE = Decimal("0.02")

_MAX_LINE_ITEMS = 200


@dataclass
class Check:
    """One piece of evidence about whether the extraction is trustworthy."""

    name: str
    passed: bool
    detail: str
    weight: float

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "weight": self.weight,
        }


@dataclass
class ExtractionResult:
    document_type: str = "other"
    merchant_name: str | None = None
    merchant_tax_id: str | None = None
    document_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax_total: Decimal | None = None
    total: Decimal | None = None
    title: str | None = None
    notes: str | None = None
    line_items: list[dict] = field(default_factory=list)

    model_confidence: float = 0.0
    confidence: float = 0.0
    checks: list[Check] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    model_name: str = ""

    @property
    def needs_review(self) -> bool:
        return (
            self.total is None
            or self.confidence < settings.review_confidence_threshold
        )

    def raw_payload(self) -> dict:
        """What gets stored in `documents.ai_raw`.

        The model's own output is kept verbatim alongside our checks, so a
        disputed figure months from now can be traced back to what was actually
        read off the photograph.
        """
        return {
            "model": self.model_name,
            "model_confidence": self.model_confidence,
            "computed_confidence": self.confidence,
            "checks": [c.as_dict() for c in self.checks],
            "response": self.raw,
        }


def extract_document(
    image: bytes, kind: DocumentKind, client: OllamaClient | None = None
) -> ExtractionResult:
    """Run the vision model over one image and score what came back.

    Raises OllamaError if the model server is unreachable or misbehaving; the
    caller decides whether that is worth a retry.
    """
    client = client or OllamaClient()
    is_receipt = kind == DocumentKind.RECEIPT
    prompt = receipt_prompt() if is_receipt else object_list_prompt()

    raw = client.vision_json(
        prompt=prompt,
        image=image,
        system=RECEIPT_SYSTEM,
        schema=RECEIPT_SCHEMA,
    )
    return _score(_coerce(raw, client.model), is_receipt)


def _coerce(raw: dict, model_name: str) -> ExtractionResult:
    """Map loose model output onto typed fields, discarding what makes no sense."""
    result = ExtractionResult(raw=raw, model_name=model_name)

    result.document_type = str(raw.get("document_type") or "other").lower()
    result.merchant_name = _clean_text(raw.get("merchant_name"), 255)
    result.merchant_tax_id = _clean_text(raw.get("merchant_tax_id"), 64)
    result.title = _clean_text(raw.get("title"), 255)
    result.notes = _clean_text(raw.get("notes"), 2000)
    result.document_date = parse_date(raw.get("document_date"))

    currency = _clean_text(raw.get("currency"), 16)
    result.currency = _normalise_currency(currency)

    result.subtotal = parse_money(raw.get("subtotal"))
    result.tax_total = parse_money(raw.get("tax_total"))
    result.total = parse_money(raw.get("total"))

    # A negative or absurd total is a misread, not a refund we should book.
    if result.total is not None and result.total < 0:
        result.total = None

    result.model_confidence = _clamp(parse_decimal(raw.get("confidence")))
    result.line_items = _coerce_line_items(raw.get("line_items"))
    return result


def _coerce_line_items(items: object) -> list[dict]:
    if not isinstance(items, list):
        return []

    cleaned: list[dict] = []
    for entry in items[:_MAX_LINE_ITEMS]:
        if not isinstance(entry, dict):
            continue
        description = _clean_text(entry.get("description"), 512)
        if not description:
            continue

        quantity = parse_decimal(entry.get("quantity"))
        unit_price = parse_money(entry.get("unit_price"))
        line_total = parse_money(entry.get("line_total"))
        vat_rate = parse_decimal(entry.get("vat_rate"))

        # Fill in whichever of the three the receipt did not print, when the
        # other two make it derivable.
        if line_total is None and quantity is not None and unit_price is not None:
            line_total = (quantity * unit_price).quantize(Decimal("0.01"))
        elif (
            unit_price is None
            and line_total is not None
            and quantity is not None
            and quantity != 0
        ):
            unit_price = (line_total / quantity).quantize(Decimal("0.01"))

        cleaned.append(
            {
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "vat_rate": vat_rate if vat_rate is not None and 0 <= vat_rate <= 100 else None,
            }
        )
    return cleaned


def _score(result: ExtractionResult, is_receipt: bool) -> ExtractionResult:
    """Blend the model's opinion with independent evidence."""
    checks: list[Check] = []

    # The model's own view: one voice, not the deciding one.
    checks.append(
        Check(
            name="model_self_report",
            passed=result.model_confidence >= 0.5,
            detail=f"Model reported {result.model_confidence:.2f} confidence",
            weight=1.0,
        )
    )
    weighted = result.model_confidence * 1.0
    total_weight = 1.0

    if is_receipt:
        # Strongest evidence available: do the parts add up to the whole?
        priced = [i["line_total"] for i in result.line_items if i["line_total"] is not None]
        if result.total is not None and len(priced) >= 2:
            line_sum = sum(priced, Decimal("0"))
            matches = _close_enough(line_sum, result.total)
            checks.append(
                Check(
                    name="line_items_sum_to_total",
                    passed=matches,
                    detail=f"Line items total {line_sum}, receipt says {result.total}",
                    weight=2.0,
                )
            )
            weighted += (1.0 if matches else 0.0) * 2.0
            total_weight += 2.0

        # Second independent arithmetic check.
        if result.total is not None and result.subtotal is not None and result.tax_total is not None:
            matches = _close_enough(result.subtotal + result.tax_total, result.total)
            checks.append(
                Check(
                    name="subtotal_plus_tax_equals_total",
                    passed=matches,
                    detail=(
                        f"{result.subtotal} + {result.tax_total} "
                        f"{'=' if matches else '!='} {result.total}"
                    ),
                    weight=1.0,
                )
            )
            weighted += (1.0 if matches else 0.0) * 1.0
            total_weight += 1.0

        for name, value, detail in (
            ("merchant_identified", result.merchant_name, "Merchant name read"),
            ("date_identified", result.document_date, "Purchase date read"),
        ):
            present = value is not None
            checks.append(
                Check(
                    name=name,
                    passed=present,
                    detail=detail if present else f"{detail.split()[0]} not readable",
                    weight=0.5,
                )
            )
            weighted += (1.0 if present else 0.0) * 0.5
            total_weight += 0.5

    result.checks = checks
    result.confidence = round(weighted / total_weight, 4) if total_weight else 0.0

    # No total means nothing to book. Whatever the arithmetic said, a human has
    # to type the number in, so do not let the score imply otherwise.
    if is_receipt and result.total is None:
        result.confidence = 0.0
        result.checks.append(
            Check(
                name="total_present",
                passed=False,
                detail="No total could be read - enter it by hand",
                weight=0.0,
            )
        )

    return result


def _close_enough(left: Decimal, right: Decimal) -> bool:
    """Compare two money figures allowing for per-line rounding."""
    difference = abs(left - right)
    if difference <= _ABS_TOLERANCE:
        return True
    reference = max(abs(left), abs(right))
    return reference > 0 and (difference / reference) <= _REL_TOLERANCE


def _clamp(value: Decimal | None) -> float:
    if value is None:
        return 0.5  # no opinion offered; treat as a shrug, not as certainty
    as_float = float(value)
    # Some models answer on a 0-100 scale despite the instruction.
    if as_float > 1.0:
        as_float /= 100.0
    return max(0.0, min(1.0, as_float))


def _clean_text(value: object, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "unknown", "-"}:
        return None
    return text[:max_length]


def _normalise_currency(value: str | None) -> str | None:
    """Map whatever the model wrote onto a supported ISO code."""
    if not value:
        return None
    token = value.strip().upper().replace(".", "")
    aliases = {
        "LEI": "RON", "LEU": "RON", "L": "RON", "RON": "RON",
        "EURO": "EUR", "EUR": "EUR", "€": "EUR",
        "USD": "USD", "DOLLAR": "USD", "DOLLARS": "USD", "$": "USD",
    }
    code = aliases.get(token, token[:3])
    return code if code in settings.currencies else None


__all__ = ["ExtractionResult", "Check", "extract_document", "OllamaError"]

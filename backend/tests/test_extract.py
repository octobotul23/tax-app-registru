"""Extraction scoring.

The point of these tests: a model that *claims* high confidence about a total
its own line items contradict must not be trusted. Arithmetic outranks
self-assessment.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.ai.extract import extract_document
from app.config import settings
from app.models import DocumentKind


class StubClient:
    """Stands in for OllamaClient, returning a canned response."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.model = "stub-vision:1b"

    def vision_json(self, **_kwargs: object) -> dict:
        return self.response


def receipt(**overrides: object) -> dict:
    base = {
        "document_type": "receipt",
        "merchant_name": "Dedeman SRL",
        "merchant_tax_id": "RO12345678",
        "document_date": "03.04.2025",
        "currency": "LEI",
        "subtotal": "100,00",
        "tax_total": "19,00",
        "total": "119,00",
        "confidence": 0.9,
        "line_items": [
            {"description": "Ciment 40kg", "quantity": 2, "unit_price": "29,50", "line_total": "59,00"},
            {"description": "Vopsea alba 5L", "quantity": 1, "unit_price": "60,00", "line_total": "60,00"},
        ],
    }
    base.update(overrides)
    return base


def extract(payload: dict, kind: DocumentKind = DocumentKind.RECEIPT):
    return extract_document(b"not-really-an-image", kind, client=StubClient(payload))


def test_a_clean_receipt_parses_and_scores_high() -> None:
    result = extract(receipt())

    assert result.merchant_name == "Dedeman SRL"
    assert result.merchant_tax_id == "RO12345678"
    assert result.document_date == date(2025, 4, 3)
    assert result.currency == "RON"          # "LEI" maps onto the ISO code
    assert result.total == Decimal("119.00")
    assert result.confidence >= settings.review_confidence_threshold
    assert not result.needs_review


def test_line_items_that_do_not_add_up_force_a_review() -> None:
    """The model says it is 95% sure. The arithmetic says otherwise."""
    result = extract(
        receipt(
            total="500,00",       # the two lines only come to 119
            confidence=0.95,
        )
    )

    sum_check = next(c for c in result.checks if c.name == "line_items_sum_to_total")
    assert not sum_check.passed
    assert result.confidence < 0.95, "a failed sum must drag the score down"
    assert result.needs_review


def test_subtotal_plus_tax_mismatch_is_caught() -> None:
    result = extract(receipt(subtotal="100,00", tax_total="19,00", total="200,00"))
    tax_check = next(
        c for c in result.checks if c.name == "subtotal_plus_tax_equals_total"
    )
    assert not tax_check.passed


def test_per_line_rounding_still_counts_as_adding_up() -> None:
    """Receipts round each line, so the parts miss the whole by a few bani."""
    result = extract(
        receipt(
            total="119,02",
            line_items=[
                {"description": "A", "line_total": "59,00"},
                {"description": "B", "line_total": "60,00"},
            ],
        )
    )
    sum_check = next(c for c in result.checks if c.name == "line_items_sum_to_total")
    assert sum_check.passed


def test_an_unreadable_total_scores_zero_however_confident_the_model_is() -> None:
    result = extract(receipt(total=None, confidence=0.99))

    assert result.total is None
    assert result.confidence == 0.0
    assert result.needs_review
    assert any(c.name == "total_present" and not c.passed for c in result.checks)


def test_a_negative_total_is_treated_as_a_misread() -> None:
    result = extract(receipt(total="-119,00"))
    assert result.total is None


def test_missing_line_price_is_derived_from_quantity_and_unit_price() -> None:
    result = extract(
        receipt(
            line_items=[
                {"description": "Ciment 40kg", "quantity": 3, "unit_price": "29,50"}
            ]
        )
    )
    assert result.line_items[0]["line_total"] == Decimal("88.50")


def test_unsupported_currency_is_dropped_rather_than_guessed() -> None:
    result = extract(receipt(currency="GBP"))
    assert result.currency is None


def test_placeholder_strings_become_null() -> None:
    result = extract(receipt(merchant_name="N/A", merchant_tax_id="unknown"))
    assert result.merchant_name is None
    assert result.merchant_tax_id is None


def test_percentage_style_confidence_is_rescaled() -> None:
    """Some models answer 85 when asked for a 0-1 score."""
    result = extract(receipt(confidence=85))
    assert result.model_confidence == 0.85


def test_object_list_transcribes_items_without_needing_a_total() -> None:
    result = extract(
        {
            "document_type": "object_list",
            "title": "Inventar depozit",
            "total": None,
            "confidence": 0.8,
            "line_items": [
                {"description": "Scaun birou", "quantity": 4},
                {"description": "Masa lemn", "quantity": 1},
            ],
        },
        kind=DocumentKind.OBJECT_LIST,
    )

    assert result.title == "Inventar depozit"
    assert len(result.line_items) == 2
    assert result.line_items[0]["line_total"] is None


def test_raw_payload_keeps_the_model_response_for_audit() -> None:
    payload = receipt()
    result = extract(payload)
    stored = result.raw_payload()

    assert stored["response"] == payload
    assert stored["model"] == "stub-vision:1b"
    assert any(check["name"] == "line_items_sum_to_total" for check in stored["checks"])

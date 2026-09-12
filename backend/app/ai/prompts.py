"""Prompts and the JSON schema the vision model is constrained to.

The schema is not decoration. Passing it to Ollama as `format` switches the
model from "please reply in JSON" to grammar-constrained decoding, which makes
malformed output structurally impossible rather than merely unlikely.
"""

from __future__ import annotations

from app.config import settings

RECEIPT_SYSTEM = (
    "You transcribe photographs of receipts and invoices into structured data. "
    "You are a transcriber, not an assistant: you copy what is printed and you "
    "never invent, estimate, or complete a value you cannot actually read. "
    "Any field you cannot read must be null."
)


def receipt_prompt() -> str:
    currencies = ", ".join(settings.currencies)
    return f"""Read this receipt photograph and return the data as JSON.

WHAT TO EXTRACT
- merchant_name: the shop or company name, usually largest at the top.
- merchant_tax_id: the fiscal code. On Romanian receipts this is printed as
  "CUI", "CIF", "C.U.I." or "Cod fiscal", often followed by RO and digits.
- document_date: the purchase date. Return it as YYYY-MM-DD.
  Romanian receipts print dates day-first: 03.04.2025 is 3 April 2025.
- currency: one of {currencies}. "LEI", "RON" and "L" all mean RON.
  Assume {settings.base_currency} when nothing indicates otherwise.
- subtotal: the net amount before tax, if printed separately.
- tax_total: the tax amount. Romanian receipts label this "TVA".
- total: the final amount paid. Romanian receipts label this "TOTAL" or
  "TOTAL DE PLATA". This is the single most important number on the page.
- line_items: one entry per purchased product.

READING NUMBERS
- Romanian receipts write one thousand two hundred thirty-four lei and
  fifty-six bani as 1.234,56 - a comma for decimals, a dot for thousands.
- Return every number in plain JSON form with a dot for decimals and no
  thousands separator: 1.234,56 becomes 1234.56.
- Do not include any currency symbol inside a number field.

RULES
- Transcribe only. If the photo is blurred, cropped, or the total is
  unreadable, set that field to null. A null is correct; a guess is not.
- If a line item has no readable price, still record the description and
  leave the price fields null.
- confidence: how sure you are of the TOTAL specifically, from 0.0 to 1.0.
  Use below 0.5 if the image is blurred, cut off, or badly lit.
- If this is not a receipt at all, set document_type accordingly and leave the
  money fields null."""


def object_list_prompt() -> str:
    return """Read this photograph of a list of objects and return it as JSON.

This is an inventory or stock list, not a receipt. Transcribe each entry.

- title: any heading written on the list, otherwise null.
- line_items: one entry per object listed, with:
    - description: the object name as written.
    - quantity: how many, if a number is given, otherwise null.
    - unit_price / line_total: only if prices are actually written on the
      list. Most object lists have no prices - leave them null.
- Leave merchant_name, total, subtotal and tax_total null unless the page
  genuinely is a priced document.
- confidence: how legible the handwriting or print is, from 0.0 to 1.0.

Transcribe only what is written. Do not infer objects that are not listed."""


#: Grammar the model is constrained to. Kept flat and permissive on types -
#: numbers arrive as strings often enough that rejecting them wholesale would
#: lose otherwise perfect reads. app.ai.numbers does the coercion.
RECEIPT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "enum": ["receipt", "invoice", "object_list", "other"],
        },
        "merchant_name": {"type": ["string", "null"]},
        "merchant_tax_id": {"type": ["string", "null"]},
        "document_date": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "subtotal": {"type": ["number", "string", "null"]},
        "tax_total": {"type": ["number", "string", "null"]},
        "total": {"type": ["number", "string", "null"]},
        "title": {"type": ["string", "null"]},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": ["number", "string", "null"]},
                    "unit_price": {"type": ["number", "string", "null"]},
                    "line_total": {"type": ["number", "string", "null"]},
                    "vat_rate": {"type": ["number", "string", "null"]},
                },
                "required": ["description"],
            },
        },
        "confidence": {"type": ["number", "string", "null"]},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["document_type", "total", "line_items", "confidence"],
}

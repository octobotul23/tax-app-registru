# Architecture

Four containers, one database, no external services.

```
   browser
      │  same origin - no CORS anywhere
      ▼
  ┌────────┐   /api/*   ┌────────┐
  │ nginx  │ ─────────► │  api   │  FastAPI. Handles requests. Never calls the model.
  │ (web)  │            └───┬────┘
  └────────┘                │
                            ▼
                     ┌─────────────┐
                     │  postgres   │  Also the job queue. See below.
                     └──────┬──────┘
                            │ polls for PENDING rows
                            ▼
                     ┌─────────────┐      ┌──────────┐
                     │   worker    │ ───► │  ollama  │  the vision model
                     └─────────────┘      └──────────┘
```

`api` and `worker` are the **same image** with a different entrypoint
(`uvicorn app.main:app` versus `python -m app.worker`). They share every module,
so extraction logic cannot drift between what the worker writes and what the API
reads back.

Only nginx and Postgres publish ports, and Postgres binds to `127.0.0.1`. Ollama
is unreachable from outside the Compose network.

---

## The queue is the documents table

There is no Redis, no Celery, no RabbitMQ. A row with `status = PENDING` *is* a
queued job:

```sql
SELECT id FROM documents
 WHERE status = 'PENDING' AND deleted_at IS NULL
 ORDER BY created_at
 LIMIT 1
   FOR UPDATE SKIP LOCKED;
```

`SKIP LOCKED` is what makes this safe. Two workers running the same query never
hand back the same row — the second one steps over the locked row instead of
blocking on it. That is the whole of the concurrency design.

Why not a real broker? A broker would be a second place where state lives, and
the two could disagree: a job could succeed in Redis while its row failed to
update, and you would have a receipt that is forever "scanning". Here the claim
and the result are the same transaction. It cannot half-happen.

The cost is polling — the worker wakes every few seconds and asks. For two
people photographing receipts, that is free.

**Crash recovery.** A worker killed mid-scan leaves a row stuck in `PROCESSING`
with nobody holding it. `release_stale_claims()` returns any row untouched for
30 minutes to `PENDING`. `scan_attempts` caps the retries so a genuinely
unreadable image ends in `FAILED` rather than looping forever.

---

## Why extraction is a pipeline, not one function

```
  bytes → storage.py → prompts.py → OllamaClient → extract.py → documents.py
          validate      ask         transport      interpret     persist
          strip EXIF                               and score
          downscale
```

Each stage is independently testable, which matters because only one of them
can be tested without a GPU. `tests/test_extract.py` feeds a `StubClient` a
canned model response and asserts the scoring — no Ollama, no images, runs in
milliseconds.

### The prompt is constrained, not requested

The model is not asked nicely for JSON. `format` is set to a **JSON schema**,
which Ollama compiles into a decoding grammar: tokens that would break the
schema are masked out before sampling. The model is structurally incapable of
replying "Sure! Here is the receipt: ```json …```".

This removes an entire bug class. Without it you write a regex to find the JSON
inside the prose, and that regex fails on the first receipt whose merchant name
contains a brace.

### Scoring outranks the model

`_score()` in `app/ai/extract.py` blends weighted evidence:

| Signal | Weight |
|---|---|
| Do the line items sum to the total? | **2.0** |
| Does subtotal + TVA equal the total? | 1.0 |
| The model's own confidence | 1.0 |
| Merchant identified | 0.5 |
| Date identified | 0.5 |

Arithmetic carries double the model's opinion, deliberately. A vision model
reports high confidence about totals it hallucinated; it cannot fake the line
items adding up. And no total at all is a hard `confidence = 0.0` — no blend,
no partial credit, straight to human review.

---

## Data model

```
users ──┬── documents.uploader_id      who took the photo
        ├── documents.payer_id         whose money it was      ← the important one
        └── documents.confirmed_by_id  who vouched for it

documents ── line_items (ordered by line_no, replaced wholesale on edit)

settlements: from_user → to_user, an amount, a date
exchange_rates: currency + effective_from → rate_to_base
```

**`payer_id` is separate from `uploader_id`** because you will photograph
receipts your partner paid for. Attributing the money to whoever happened to
hold the phone would quietly corrupt the balance.

**`funding_source` on each document** is the switch the entire app turns on:

- `BUSINESS` — company money. Recorded as an expense, creates no claim.
- `PERSONAL` — a partner's own money. Creates a claim against the business.

The balance report only ever sums `PERSONAL` rows. Business spending appears in
the dashboard and the category report but never in "who owes whom".

**Money columns are `Numeric`, never `Float`.** They cross the API as JSON
*strings* — Pydantic serialises `Decimal` that way, and the TypeScript client
keeps them as `type Money = string`. A number that is parsed into a JS `Number`
at any point in the round trip has already lost the guarantee.

**`deleted_at` everywhere.** Nothing is hard-deleted. A balance you printed in
March has to still produce the same figures in November.

---

## Currency

Each document stores four things: `currency` and `total` exactly as printed on
the receipt, plus `fx_rate` and `total_base` computed at save time.

Freezing the rate onto the row is the point. If balances recomputed from the
current rate table, every historical total would move each time you entered a
new rate — last quarter's report would silently disagree with the copy you
filed.

`POST /api/rates/revalue` exists for the receipts that were filed *before* a
rate existed. Those have a total but no base value, so they sit outside the
balance; adding the missing rate does not retroactively rescue them. Revalue
walks exactly those rows, tries again, and reports how many it recovered. It
never touches a document that already has a frozen rate.

A missing rate is not an error. The receipt is valid; it just cannot be valued
in lei yet. The document lands in `NEEDS_REVIEW` with a message saying which
rate is missing, and the balance report lists it as unvalued rather than
pretending it is worth zero.

---

## Authentication

A JWT in an **httpOnly** cookie. The token is never visible to JavaScript, so an
XSS bug in the frontend cannot exfiltrate a session — which is the failure mode
of every design that stores a token in `localStorage`.

Frontend and API share an origin (nginx proxies `/api` in production, Vite
proxies it in development), so:

- no CORS configuration exists, and therefore cannot be misconfigured
- `SameSite=Lax` is sufficient against CSRF
- the cookie flows automatically; no `Authorization` header plumbing

Passwords are Argon2id via `argon2-cffi` directly. Argon2 is memory-hard, which
is what makes GPU cracking expensive rather than merely slow.

# API reference

Everything lives under `/api`. FastAPI generates interactive docs at
`http://localhost:8000/docs` when the API is reachable directly — this file is
the version you can read without the server running.

**Authentication** is a session cookie set by `POST /api/auth/login`. Every
endpoint except `/api/health` requires it. Endpoints marked **admin** require
`is_admin`.

**Money is a JSON string**, never a number: `"total": "127.45"`. This is not an
oversight. `127.45` parsed as an IEEE double is not 127.45, and a ledger that
drifts by a ban per receipt is worse than no ledger. Keep it a string until you
format it for display.

---

## Auth

| | |
|---|---|
| `POST /api/auth/login` | `{email, password}` → user, sets the cookie |
| `POST /api/auth/logout` | clears the cookie |
| `GET /api/auth/me` | the signed-in user; how the frontend checks a session |
| `POST /api/auth/password` | `{current_password, new_password}` — min 10 chars |

There is no registration endpoint. Accounts come from `POST /api/users`, which
is admin-only.

---

## Users

| | |
|---|---|
| `GET /api/users` | every partner — the UI needs this to attribute a payer |
| `POST /api/users` | **admin.** `{email, password, display_name, is_admin, equity_share}` |
| `PATCH /api/users/{id}` | **admin.** any of `display_name`, `is_active`, `is_admin`, `equity_share` |
| `DELETE /api/users/{id}` | **admin.** deactivates; never deletes |

`equity_share` is 0–1, default 0.5. It sets each partner's fair share of the
personal outlay — see [who-paid.md](who-paid.md).

Three guards exist because each one is a way to lock everybody out of the books:
you cannot remove your own admin rights, you cannot deactivate yourself, and you
cannot deactivate the last active account.

Deactivation rather than deletion is structural, not politeness. A partner who
ever paid for anything is referenced by every receipt they funded; removing the
row would orphan those receipts or cascade away part of the ledger.

---

## Documents

### `POST /api/documents`

`multipart/form-data`. Returns **201** immediately — it does not wait for the
model.

| Field | |
|---|---|
| `file` | the photograph. JPEG, PNG, WebP, or HEIC |
| `funding_source` | **required.** `BUSINESS` or `PERSONAL` |
| `kind` | `RECEIPT` (default) or `OBJECT_LIST` |
| `payer_id` | whose money. Defaults to you |
| `title`, `notes` | optional |

`funding_source` has no default on purpose. It is the field that decides whether
a purchase creates a debt between the partners, and a wrong default would
silently invent or erase one. Make the caller say it.

The response includes `duplicate_of` when the same image has been uploaded
before — matched on SHA-256 of the bytes. The upload still succeeds; you get
told, and decide. Two genuinely separate purchases can produce byte-identical
photographs only if someone uploaded the same file twice, but "only if" is not
"never", so the app reports rather than rejects.

### `GET /api/documents`

| Query | |
|---|---|
| `kind` | `RECEIPT` or `OBJECT_LIST` |
| `funding_source` | `BUSINESS` or `PERSONAL` |
| `status` | `PENDING`, `PROCESSING`, `PARSED`, `NEEDS_REVIEW`, `CONFIRMED`, `FAILED` |
| `payer_id`, `uploader_id` | UUID |
| `date_from`, `date_to` | ISO dates, against the printed date |
| `search` | merchant, title, notes, **and line-item descriptions** |
| `limit`, `offset` | 1–200, default 50 |

Returns `{items, total, limit, offset}`. Ordered by printed date descending,
falling back to upload date for receipts whose date could not be read.

`search` reaching into line items is what makes the app useful in practice —
"where did we buy those cables" is a question about an item, not a merchant.

### The rest

| | |
|---|---|
| `GET /api/documents/{id}` | full detail including line items and the AI trace |
| `PATCH /api/documents/{id}` | corrections. **Saving marks it CONFIRMED** |
| `POST /api/documents/{id}/rescan` | back to `PENDING` for another read |
| `DELETE /api/documents/{id}` | soft delete |
| `GET /api/documents/{id}/image` | the photograph, authenticated |
| `GET /api/documents/{id}/thumbnail` | small version for lists |

`PATCH` accepts any subset of: `funding_source`, `payer_id`, `title`,
`merchant_name`, `merchant_tax_id`, `document_date`, `currency`, `subtotal`,
`tax_total`, `total`, `fx_rate`, `notes`, `category`, `line_items`.

Two behaviours worth knowing:

**`line_items` replaces the whole list.** It is not a merge. The review screen
sends the complete set it is displaying, and a partial merge would make deleting
a spurious row impossible.

**`fx_rate` is only honoured if you send it in that request.** Omit it and the
rate is re-resolved from the rate table. This matters: correcting a receipt's
currency from EUR to USD while silently keeping the euro rate would produce a
wrong total with no error anywhere.

Images are served through an authenticated endpoint rather than a static
directory, so a receipt URL leaking is not the same as the receipt leaking.

---

## Reports

| | |
|---|---|
| `GET /api/reports/balance` | `?period_start=&period_end=` — the whole answer to "who paid how much" |
| `GET /api/reports/dashboard` | this month's totals, queue depth, what needs review |
| `GET /api/reports/categories` | `?period_start=&period_end=&funding_source=` |

`/balance` returns per-partner `personal_outlay`, `business_outlay`,
`unverified_outlay`, `fair_share`, settlements in and out, and `net_position` —
plus `suggested_settlements` and `excluded_document_count`. The full arithmetic
is in [who-paid.md](who-paid.md).

`excluded_document_count` is deliberately part of the response, not a separate
call. A balance is only meaningful alongside what it had to leave out, and
making that a second request invites a UI that forgets to make it.

---

## Settlements

| | |
|---|---|
| `GET /api/settlements` | newest first |
| `POST /api/settlements` | `{from_user_id, to_user_id, amount_base, settled_on, note}` |
| `DELETE /api/settlements/{id}` | soft delete |

`amount_base` is in the base currency (RON) — a settlement is a bank transfer
between two people, not a purchase, so there is nothing to convert.

Recording a settlement is what lets the balance return to zero. Without it the
app would keep telling you about a debt you already paid.

---

## Exchange rates

| | |
|---|---|
| `GET /api/rates/currencies` | the configured list |
| `GET /api/rates` | every rate, newest per currency first |
| `GET /api/rates/current` | today's effective rate per currency; `null` where none applies |
| `POST /api/rates` | `{currency, rate_to_base, effective_from, note}` |
| `POST /api/rates/revalue` | retry receipts stranded without a rate |
| `DELETE /api/rates/{id}` | remove a rate |

A rate applies from `effective_from` until a newer one supersedes it. Posting
the same currency and date again overwrites rather than duplicating — entering a
correction is the common case, and a second row for the same day would make
"which rate applies" ambiguous.

Rates for the base currency are rejected: RON is always 1.

`revalue` exists because adding a rate does not retroactively fix the receipts
filed before it. Those have a total but no base value, so they sit outside the
balance. Revalue walks exactly those and returns `{revalued: n}`.

---

## System

| | |
|---|---|
| `GET /api/health` | **unauthenticated.** liveness only |
| `GET /api/system/status` | model name, whether Ollama answers, queue depth |

These are separate on purpose. Docker probes `/api/health` every few seconds and
the worker waits on it at boot; if it blocked on a vision model loading 6 GB
onto a CPU, Compose would declare the API dead and restart it in a loop.
`/api/health` touches nothing slow. The real check is authenticated and lives
elsewhere.

---

## Errors

Standard FastAPI `{"detail": "..."}`. Worth knowing:

| | |
|---|---|
| **401** | no session, or it expired |
| **403** | signed in, but not admin |
| **409** | duplicate email |
| **422** | validation, including a file that is not a readable image |
| **409** on a rate | a required exchange rate is missing — the detail says which currency and date |

The missing-rate case has its own handler rather than being a generic 500
because it is not a bug — it is a thing the user has to go and fix, and the
message tells them exactly what to enter.

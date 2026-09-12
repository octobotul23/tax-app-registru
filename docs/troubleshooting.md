# Troubleshooting

Symptoms you are actually likely to hit, and what each one means.

---

## Receipts sit on "Scanning" forever

Check the worker is alive and talking to Ollama:

```bash
docker compose ps
```

```bash
docker compose logs --tail=50 worker
```

Three usual causes:

**The model was never pulled.** `ollama-init` downloads ~6 GB on first boot and
a slow connection can outlast your patience. Check:

```bash
docker compose exec ollama ollama list
```

If the list is empty, pull it by hand:

```bash
docker compose exec ollama ollama pull qwen2.5vl:7b
```

**The model name in `.env` does not match what is installed.** `OLLAMA_VISION_MODEL`
has to be exactly what `ollama list` shows, tag included. `qwen2.5vl` and
`qwen2.5vl:7b` are different strings to Ollama.

**It is just slow.** On CPU, a single receipt takes 30–90 seconds and the
machine will feel busy. That is normal. Watch one go through:

```bash
docker compose logs -f worker
```

If a worker was killed mid-scan, its receipt is stuck in `PROCESSING` with
nobody holding it. Nothing needs doing — the stale-claim sweep returns it to
`PENDING` after 30 minutes. To hurry it, hit **Scan again** on the document.

---

## Everything is being sent to review

Look at the parsed fields on a few of them before changing settings.

**If the totals are right but the line items are wrong or missing**, that is the
scoring working as designed. Line items carry double the weight of the model's
own confidence, so a receipt whose items do not sum to its total goes to a human
no matter how sure the model claims to be. Faded thermal paper does this
constantly.

**If the totals themselves are wrong**, the photograph is the problem far more
often than the model. Flatten the receipt, fill the frame with it, avoid glare
and shadow across the totals line. A vision model cannot read what is not in the
pixels.

**If you are on a 3B model**, move to `qwen2.5vl:7b` if you have the memory. The
accuracy difference on real receipts is large.

You can lower `REVIEW_CONFIDENCE_THRESHOLD` in `.env`, but think about what that
buys: fewer receipts stopped for review means more wrong numbers entering your
balance silently. The threshold is not the bug.

---

## "No exchange rate for EUR on 2026-03-14"

There is no rate for that currency on or before that receipt's date.

Go to **Settings → Exchange rates** and add one with `effective_from` on or
before the receipt's date. The app will not interpolate or guess a rate, because
a guessed rate is a wrong number that looks like a right one.

Receipts filed *before* you added the rate are not fixed retroactively — they
have a total but no lei value, so they sit outside the balance. **Settings →
Revalue** walks exactly those and values them.

If you never deal in foreign currency, set `CURRENCIES=RON` in `.env` and the
problem cannot arise.

---

## The balance looks wrong

Work through these in order.

**Is `excluded_document_count` above zero?** The balance page shows it. Excluded
receipts are ones still scanning, failed, or lacking an exchange rate — they are
not in the total. That is usually the whole explanation.

**Check `funding_source` on the recent uploads.** A receipt paid with company
money but filed as personal money invents a debt that does not exist. This is
the most common real error, and it is a one-click fix on the document page.

**Check `payer_id`, not just who uploaded it.** You will photograph receipts
your partner paid for. The payer field is what the balance uses; the uploader is
only provenance.

**Check the equity shares** in Settings. Two partners at 0.5 each gives an even
split. One at 1 and one at 0.5 normalises to 67%/33%, which is legitimate if
that is your partnership and wrong if it was a typo.

**Check the period.** If you settled up in April for March's spending, a report
over March alone still shows the debt open — correctly, because it was open
then. Widen the range.

---

## Cannot sign in

**First boot:** the owner account comes from `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD`, and it is created **only against an empty users
table**. Changing those variables later does nothing — that is deliberate, so
restarting a container cannot resurrect a deleted account or reset a changed
password.

Confirm it was created:

```bash
docker compose logs api | grep -i "owner account"
```

**Lost the admin password.** There is no email reset — this app has no mail
server. Reset the hash directly:

```bash
docker compose exec api python -c "from app.security import hash_password; print(hash_password('your-new-password'))"
```

```bash
docker compose exec db psql -U ledger -d ledger -c "UPDATE users SET password_hash = 'PASTE_THE_HASH' WHERE email = 'you@example.com';"
```

**Signed in, then immediately signed out.** The session cookie is rejected.
Either `SECRET_KEY` changed between restarts (every existing session becomes
invalid — sign in again), or `COOKIE_SECURE=true` while you are on plain HTTP,
in which case the browser will not send the cookie back at all.

---

## Uploads fail

**HEIC files rejected.** iPhone photographs are HEIC. `pillow-heif` handles
them, but only if it installed cleanly:

```bash
docker compose exec api python -c "import pillow_heif; print('HEIC ok')"
```

**Large photographs rejected.** `MAX_UPLOAD_MB` in `.env` caps it, default 20.
Modern phone cameras can exceed that. The image is downscaled after validation,
not before, so the cap applies to what leaves the phone.

**"Not a readable image".** Something that is not actually an image, or a
truncated upload. The file is opened and re-encoded on the way in precisely so
this fails at upload rather than an hour later in the worker.

---

## Out of memory / the machine crawls

The vision model is the whole story. On CPU it wants several GB of RAM and will
use every core it can get.

Options, in order of how much they cost you:

1. Move to `qwen2.5vl:3b` — halves the memory, costs accuracy on poor receipts
2. Give Docker Desktop more RAM (Settings → Resources)
3. Enable GPU: uncomment the `deploy.resources` block for `ollama` in
   `docker-compose.yml`, which needs the NVIDIA Container Toolkit installed

Uploads stay fast regardless — they never touch the model. Only the reading is
slow, and it happens in the background.

---

## Starting over

Destroys every receipt, the database, **and the downloaded models** — the next
boot re-downloads ~6 GB:

```bash
docker compose down -v
```

Usually you want the models kept. Drop only the data volumes:

```bash
docker compose down
```

```bash
docker volume rm partner-ledger_db-data partner-ledger_uploads
```

Back up first if there is anything in there you want:

```bash
docker compose exec -T db pg_dump -U ledger ledger > backup.sql
```

---

## Reading what the model actually said

Every scan stores the raw model response on the document row. On the document
page it is under the AI details; from the database:

```bash
docker compose exec db psql -U ledger -d ledger -c "SELECT ai_model, ai_confidence, ai_raw FROM documents ORDER BY created_at DESC LIMIT 1;"
```

This is the first thing to look at when a receipt parses strangely. It separates
"the model read it wrong" from "the model read it right and something after that
mangled it" — two very different bugs.

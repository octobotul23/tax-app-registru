# Registru — partner expense ledger

A shared ledger for two business partners. You both photograph receipts; a
vision model running **on your own server** reads them; the app works out who
paid how much out of their own pocket, and who owes whom.

Nothing leaves your machine. There is no cloud API key anywhere in this stack.

---

## The idea in one table

| You upload a receipt as… | What the app does with it |
|---|---|
| **Business money** | Records it as a company expense. Nobody is owed anything — the business already paid. |
| **Own money** | Records it as a claim. You funded the business out of pocket, so the business owes you. |

The **Who paid** page nets those claims out. If you have put in 1.000 lei of
your own money and your partner 400, the fair share is 700 each — so your
partner owes you 300. When they pay you back, you record the payment and the
balance returns to zero.

Business-money spending is tracked for the books but never creates a debt
between the two of you. That distinction is the whole point of the app.

---

## What you need

| | Why |
|---|---|
| **Docker + Docker Compose** | Runs the whole stack with one command |
| **~10 GB disk** | Mostly the vision model |
| **8 GB RAM minimum** | 16 GB is comfortable |
| **An NVIDIA GPU** *(optional)* | 2–5 seconds per receipt instead of 30–90 |

It runs fine on CPU only. Receipts just take longer to read, and since reading
happens in the background you mostly will not notice.

> **Neither Python nor Docker is currently installed on this Windows machine.**
> The backend has therefore not been executed here — only the frontend was
> built and typechecked. See [Running it locally](#running-it-locally-without-docker)
> below for what to install.

---

## Getting started

```bash
cp .env.example .env
```

Edit `.env`. The three that matter before first boot:

```bash
SECRET_KEY=                 # generate one, see below
BOOTSTRAP_ADMIN_EMAIL=      # your email - this becomes the owner account
BOOTSTRAP_ADMIN_PASSWORD=   # change it after your first sign-in
```

Generate a real secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then bring it up:

```bash
docker compose up -d --build
```

The first run downloads the vision model (~6 GB), so give it a few minutes.
Watch it happen:

```bash
docker compose logs -f ollama-init worker
```

Open **http://localhost:8080** and sign in with the bootstrap credentials.

### Then, in the app

1. **Settings → Partners → Add partner** — create your business partner's
   account. Leave both shares at `0.5` for an equal partnership.
2. **Settings → Exchange rates** — replace the placeholder EUR and USD rates
   with real ones. They are deliberately wrong on install so you notice them.
3. **Upload** — photograph a receipt, pick whose money paid, done.

---

## How a receipt travels through the system

```
  phone camera
       │
       ▼
  POST /api/documents ──── image re-encoded, EXIF stripped, downscaled
       │                   status: PENDING          (returns immediately)
       ▼
  documents table  ◄────── the queue. Postgres, FOR UPDATE SKIP LOCKED.
       │
       ▼
  worker container ─────── claims one row → status: PROCESSING
       │
       ▼
  Ollama (qwen2.5vl) ───── reads the photo, returns JSON
       │
       ▼
  scoring ──────────────── do the line items add up to the total?
       │                   does subtotal + TVA equal the total?
       │
       ├── confident ────► PARSED
       └── not confident ► NEEDS_REVIEW   ← a human checks the photo
                                │
                                ▼
                           CONFIRMED      ← counted as verified in the balance
```

The upload never waits for the model. That is deliberate: a vision model on CPU
can take a minute per image, and an upload that blocked on it would time out on
a phone connection every time.

---

## Why some things are built the way they are

**The model's confidence is not trusted on its own.**
A vision model will report 95% confidence about a total it invented. So the app
computes its own score, dominated by arithmetic: *do the line items sum to the
stated total?* If they do not, the receipt goes to a human no matter what the
model claimed. You can see the individual checks on any receipt — they are
stored with it permanently.

**Money is `Decimal` end to end.**
Never `float`, in Python or in JavaScript. A float cannot represent 19,99
exactly, and a ledger that drifts by a ban per receipt is worse than no ledger.
Amounts travel over the API as JSON strings precisely so they survive the trip.

**Exchange rates are entered by hand.**
Not fetched from the internet. The rate that belongs in your books is the one
your bank actually charged you, which no public rate table matches. A rate
applies from its date until you enter a newer one, and the converted value is
frozen onto each receipt — so reprinting last quarter's balance next year gives
the same numbers it gave at the time.

**Nothing is ever really deleted.**
Deleting a receipt sets `deleted_at`. The row and the photograph both stay.
An already-printed balance has to remain reproducible.

**There is no public sign-up.**
The first account comes from environment variables; that owner creates the
partner account. An open `/register` on an internet-facing server is how you
end up sharing your books with a stranger.

---

## Everyday commands

```bash
docker compose logs -f worker          # watch receipts being read
```

```bash
docker compose exec ollama ollama list # which models are installed
```

```bash
docker compose restart worker          # after changing the model in .env
```

Back up the database:

```bash
docker compose exec -T db pg_dump -U ledger ledger > backup-$(date +%F).sql
```

Back up the receipt photographs (they are **not** in the database):

```bash
docker run --rm -v partner-ledger_uploads:/data -v "$PWD:/out" alpine tar czf /out/receipts-$(date +%F).tar.gz -C /data .
```

---

## Choosing a model

Set `OLLAMA_VISION_MODEL` in `.env`, then `docker compose restart worker`.

| Model | VRAM | Notes |
|---|---|---|
| `qwen2.5vl:7b` | ~6 GB | Default. Best accuracy for the size, handles Romanian receipts well. |
| `qwen2.5vl:3b` | ~3 GB | For a small GPU or CPU-only. Noticeably weaker on faded thermal paper. |
| `llama3.2-vision:11b` | ~8 GB | Alternative. Weaker on non-English receipts in testing. |

Pull a new one before switching:

```bash
docker compose exec ollama ollama pull qwen2.5vl:3b
```

Receipts read with an older model can be re-read individually with **Scan
again** on the document page.

---

## Running it locally without Docker

Neither Python nor Docker is installed on this machine yet. To install both:

```powershell
winget install Python.Python.3.12 Docker.DockerDesktop
```

Then, for backend development against a Postgres you are running yourself:

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements-dev.txt
```

```bash
cd backend && uvicorn app.main:app --reload
```

```bash
cd backend && python -m app.worker
```

```bash
cd frontend && npm run dev
```

The Vite dev server proxies `/api` to `localhost:8000`, so the session cookie
works exactly as it does in production.

Run the tests:

```bash
cd backend && pytest
```

The tests cover the two things most likely to be silently wrong: parsing
Romanian number formats, and the settlement arithmetic.

---

## Layout

```
backend/
  app/
    models.py           the schema, and the domain explained in prose
    schemas.py          API request/response shapes
    worker.py           the scan loop
    ai/
      prompts.py        what the vision model is asked, and the JSON grammar
      extract.py        scoring - arithmetic outranks self-reported confidence
      numbers.py        1.234,56 vs 1,234.56, with tests
    services/
      balance.py        who paid how much, who owes whom
      money.py          currency conversion
      documents.py      applying scans and human corrections
      storage.py        image validation, EXIF stripping, downscaling
    routers/            the HTTP endpoints
  alembic/              database migrations
  tests/
frontend/
  src/
    styles/tokens/      design tokens (see below)
    pages/              one file per screen
    api/                typed client
docker-compose.yml
```

---

## Further reading

| | |
|---|---|
| [docs/who-paid.md](docs/who-paid.md) | The money arithmetic in full, with a worked example. Read this one. |
| [docs/architecture.md](docs/architecture.md) | How the four containers fit together, and why the queue is a table |
| [docs/api.md](docs/api.md) | Every endpoint, without needing the server running |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Symptoms you are actually likely to hit |

---

## The design system

The token files under `frontend/src/styles/tokens/` deliberately mirror the
filenames of the **Aperture** design system in Claude Design
(`colors.css`, `spacing.css`, `radii.css`, `typography.css`, `elevation.css`,
`motion.css`, `layout.css`, `fonts.css`).

The values in them right now are placeholders written for this app. No component
references a raw colour — everything goes through a token — so importing the
real Aperture set is a matter of replacing the contents of those files, not
restyling the application.

**That import is currently blocked.** Pulling the project needs a one-time
authorisation:

1. Open a terminal and run `claude`
2. Type `/design-login`

After that, the Aperture tokens and `Ledger.dc.html` can be pulled into this
repository.

---

## Security notes

- The session is a JWT in an **httpOnly** cookie. No token is reachable from
  JavaScript, so an XSS bug cannot steal a session.
- Frontend and API share one origin (nginx in production, the Vite proxy in
  development), so there is no CORS hole and `SameSite=Lax` blocks CSRF.
- Passwords are Argon2id.
- Receipt images are served through an authenticated endpoint, never from a
  public static directory.
- Uploaded images are re-encoded, which strips EXIF — including the GPS
  coordinates phones attach to every photo.
- Postgres is bound to `127.0.0.1` and Ollama is not published at all.

If you expose this beyond your LAN, put it behind HTTPS and set
`COOKIE_SECURE=true`.

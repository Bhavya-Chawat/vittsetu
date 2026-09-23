# VittSetu — SC Channel Finance Navigator

An AI-driven platform that helps Scheduled Caste entrepreneurs and students navigate NSFDC's Channel Finance System — built for the SIH problem statement *"AI-Driven Scheme Matching for Marginalized Entrepreneurs"* (Ministry of Social Justice and Empowerment).

Three core tools, all grounded in NSFDC's officially published terms (see `scripts/seed_schemes.py` for exact sources and capture dates — nothing here is invented):

- **Smart Scheme Recommender** — a deterministic rule engine (`scheme_engine.py`) matches an applicant's income, category, and project/education need against NSFDC's 5 loan schemes (Micro Finance Scheme, Term Loan, Aajeevika Micro-Finance Yojana, Udyam Nidhi Yojana, Educational Loan Scheme), with a plain-language "why" for every match and rejection.
- **Financial Calculator** — EMI, moratorium, financing %, and applicant contribution (`financial_engine.py`), bounded by each scheme's real limits.
- **Geo-Spatial Channel Partner Locator** — a Leaflet/OpenStreetMap map of NSFDC's real Channel Partners (SCAs, PSBs, RRBs, NBFC-MFIs, ...), ingested from NSFDC's own published partner directories (`scripts/ingest_partners.py`), with a live admin-operated capacity flag so applications route away from partners currently unable to take them.

Plus **"Ask VittSetu"**, the original multilingual RAG chatbot (unchanged), now grounded in NSFDC-specific content, for open-ended questions and voice interaction in English, Hindi, Kannada, and Telugu.

VittSetu helps beneficiaries discover, calculate, and find the right partner — the actual loan application is submitted through the Government of India's official [PM-SURAJ portal](https://pmsuraj.dosje.gov.in/) or directly with the chosen Channel Partner.

## Quick Start (Windows, first time)

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Node.js LTS](https://nodejs.org/) if you don't already have them.
2. Get a free Groq API key: https://console.groq.com/keys
3. Double-click **`run.bat`** (or run it from a terminal: `run.bat`).

That's it. On first run it will, in order: create the Python virtual environment and install dependencies, prompt you (via Notepad) to paste in your `GROQ_API_KEY`, seed the scheme database, download and geocode NSFDC's official Channel Partner directories (~5-8 minutes, one-time), install and build the frontend, then start everything and open `http://localhost:8000` in your browser. Every step after the first is skipped automatically on subsequent runs — `run.bat` is also the normal way to start VittSetu day-to-day.

Not on Windows, or want to understand/control each step? See **Manual Setup** below — it's exactly what `run.bat` automates.

## Prerequisites

| Tool | Why | Check |
|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Python env + dependency manager | `uv --version` |
| [Node.js LTS](https://nodejs.org/) (v18+) | Builds/runs the React frontend | `node --version` |
| A [Groq API key](https://console.groq.com/keys) | Powers the RAG chat + AI requirement interpretation — **required**, the app will not start without it | — |
| `ffmpeg` (optional) | Only needed for `voice_service` (audio normalization) | `ffmpeg -version` |
| A Hugging Face token (optional) | Only needed for `voice_service`'s gated ASR/TTS models | — |

## Manual Setup

**Backend:**

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt
uv pip install --python .venv -r voice_service/requirements.txt   # only needed for voice features
```

Copy `.env.example` to `.env` and fill in:

- `GROQ_API_KEY` — **required**, for `api.py` (RAG chat + `/api/interpret`). Without this the server will not start — `agent.py` instantiates the Groq client at import time. Get one at https://console.groq.com/keys.
- `ADMIN_TOKEN` — protects the admin console (partner capacity toggle, scheme edits). Defaults to `vittsetu-admin-dev` for local use; change it for anything beyond your own machine.
- `HF_TOKEN` — only needed to run `voice_service` (its models are gated on Hugging Face). See `voice_service/README.md` for the access request steps.
- `VOICE_SERVICE_URL` — where `api.py` looks for `voice_service`. Defaults to `http://localhost:8001`; only set it if running voice_service elsewhere.

`ffmpeg` (system package, not pip) is also required if you're running `voice_service` — it normalizes recorded audio before transcription.

Seed the structured scheme/partner database (one-time; creates `vittsetu.db`):

```bash
uv run python scripts/seed_schemes.py      # the 5 verified NSFDC schemes (seconds)
uv run python scripts/ingest_partners.py   # NSFDC's official Channel Partner directories (~5-8 minutes — downloads + geocodes ~80 real addresses)
```

`ingest_partners.py` is safe to skip or interrupt — the app runs fine with zero partners (the locator just shows an empty state until you run it), and re-running it later only adds partners it hasn't already ingested.

**Frontend:**

```bash
cd frontend
npm install
```

## Run

### Windows one-click

```bash
run.bat
```

Runs the full **Manual Setup** above automatically wherever a step hasn't been done yet, then starts the voice service, backend, and frontend together and opens your browser. See **Quick Start** above for what happens on first run.

### Development (hot-reload, two servers)

```bash
# Terminal 1 — backend: RAG chat + scheme/calculator/partner APIs, port 8000
uv run uvicorn api:app --reload

# Terminal 2 — frontend dev server, port 5173 (proxies /api, /ask, /transcribe, /speak, /health to :8000)
npm --prefix frontend run dev

# Terminal 3 — voice service (speech-to-text / text-to-speech), port 8001 — optional
uv run uvicorn voice_service.main:app --port 8001
```

Open `http://localhost:5173`. `uv run` picks up `.venv` automatically — no manual activation, no OS-specific paths. If you're not using `uv`, activate the venv first (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on macOS/Linux) and drop the `uv run` prefix.

### Single-URL / demo mode (one server)

```bash
npm --prefix frontend run build     # builds frontend/dist/
uv run uvicorn api:app
```

Once `frontend/dist/` exists, `api.py` serves the built React app directly at `http://localhost:8000` alongside all APIs — no separate frontend server needed. This is what `run.bat` does automatically on Windows.

Voice features degrade gracefully (clean `503`s) if `voice_service` isn't running — everything else works without it. First run of `voice_service` needs its gated Hugging Face models downloaded and cached — see `voice_service/README.md`.

## Admin Console

Visit `/admin`, sign in with `ADMIN_TOKEN`. From there you can toggle a Channel Partner's capacity status (`available` / `limited` / `not_accepting`) — the partner locator excludes `not_accepting` partners live, and re-ranks around `limited` ones. This reflects NSFDC's own internal fund-utilization/NPA tracking, which isn't publicly published — every partner starts at `available` (never a fabricated status) until an admin who has that real operational knowledge sets otherwise.

## Data Provenance

- **Scheme terms** (`scripts/seed_schemes.py`): transcribed verbatim from `http://nsfdc.nic.in/scheme` and `http://nsfdc.nic.in/how-to-apply-2`, captured 2026-09-18. Update the affected fields and `last_verified_date` there (or via the admin console) if NSFDC revises its terms.
- **Channel Partners** (`scripts/ingest_partners.py`): parsed from NSFDC's own published PDF directories at `http://nsfdc.nic.in/our-channel-partners`, geocoded via OpenStreetMap Nominatim. Small Finance Bank and Cooperative Society use a PDF layout the parser can't yet handle reliably — add those via the admin console, or extend the parser.
- **Partner capacity**: never sourced or fabricated — a real, live, admin-operated field (see above).
- **`data/nsfdc_schemes/`**: longer-form scheme documents for the RAG chatbot, same official sources as above.

## Automated Generic Scheme Ingestion (secondary/legacy)

`scripts/fetch_schemes.py` pulls official Central/State schemes from [MyScheme.gov.in](https://www.myscheme.gov.in/) into categorized `data/` subfolders and rebuilds the RAG index. This predates VittSetu's NSFDC focus — useful if you want to broaden "Ask VittSetu" beyond NSFDC schemes, but not part of the core Recommender/Calculator/Locator flow (those are driven entirely by `vittsetu.db`, not this).

```bash
python scripts/fetch_schemes.py --list-categories
python scripts/fetch_schemes.py --category business --count 5
python scripts/fetch_schemes.py --query "solar subsidy" --count 3
```

## Project Structure

```
├── api.py                       # FastAPI backend: all routers + RAG /ask, /transcribe, /speak proxies, serves frontend/dist
├── agent.py / rag_core.py / rag_tools.py   # LangGraph RAG pipeline (unchanged) — powers "Ask VittSetu"
├── db.py / models.py / schemas.py          # SQLite (schemes, partners, applications)
├── scheme_engine.py             # Eligibility + recommendation rules (deterministic, no LLM)
├── financial_engine.py          # EMI / amortization calculator
├── partner_engine.py            # Geospatial compatibility + capacity-aware ranking
├── routers/                     # /api/schemes, /calculate, /partners, /admin, /interpret
├── frontend/                    # React (Vite) app — the applicant wizard, map, admin console, Ask VittSetu
│   └── src/pages/                Home, Eligibility, Requirement, Results, Calculator, Partners, Checklist, AskVittSetu, Admin
├── data/nsfdc_schemes/           # NSFDC-specific long-form docs for the RAG chatbot
├── scripts/
│   ├── seed_schemes.py           # Seeds the 5 verified NSFDC schemes into vittsetu.db
│   ├── ingest_partners.py        # Parses + geocodes NSFDC's official Channel Partner PDFs
│   ├── fetch_schemes.py          # Secondary: generic MyScheme.gov.in ingestion for the RAG corpus
│   ├── add_scheme.py             # Manually add a RAG document
│   └── build_index.py            # Force-rebuild the ChromaDB index
└── voice_service/                # Separate FastAPI microservice: ASR + TTS
```

See `voice_service/README.md` for voice-service-specific details (models, VRAM handling, TTS fallback behavior).

## Repo Hygiene

Nothing large or generated is tracked in git — it's all reproducible from a fresh clone via the setup steps above:

| Path | Size (typical) | Regenerate with |
|---|---|---|
| `.venv/` | ~1.2 GB | `uv venv` + `uv pip install` |
| `frontend/node_modules/` | ~70 MB | `npm install` |
| `frontend/dist/` | <1 MB | `npm run build` |
| `chroma_db/` | grows with `data/` | `POST /reindex`, or delete and restart |
| `vittsetu.db` | tiny | `scripts/seed_schemes.py` + `scripts/ingest_partners.py` |
| Voice models (`~/.cache/huggingface/`) | ~3-4 GB | `voice_service/download_models.py` (outside the repo entirely) |

`.env` (your API keys) is also gitignored — never committed, only `.env.example` is.

# VittSetu — SC Channel Finance Navigator

An AI-driven platform that helps Scheduled Caste entrepreneurs and students navigate NSFDC's Channel Finance System — built for the SIH problem statement *"AI-Driven Scheme Matching for Marginalized Entrepreneurs"* (Ministry of Social Justice and Empowerment).

Three core tools, all grounded in NSFDC's officially published terms (see `scripts/seed_schemes.py` for exact sources and capture dates — nothing here is invented):

- **Smart Scheme Recommender** — a deterministic rule engine (`scheme_engine.py`, no LLM) matches an applicant's income (against each scheme's own ceiling), category, activity and project/education need against NSFDC's 5 loan schemes (Micro Finance Scheme, Term Loan, Aajeevika Micro-Finance Yojana, Udyam Nidhi Yojana, Educational Loan Scheme). It picks a **best fit** — preferring schemes with a routable Channel Partner near the applicant, then the lowest effective rate — spells out the trade-offs of every alternative, and shows a side-by-side comparison. Business activities are classified by a keyword taxonomy stored as data (`reference_data/activity_taxonomy.json`) and confirmed by the user; education loans match the course against NSFDC's recognized list.
- **Financial Calculator** — `financial_engine.py` applies each scheme's guideline rules, stored as data on the scheme: moratorium (Term Loan: 12 months for plantation/construction, else 6; ELS: course period + 1 year before repayment starts, else 6 months), tenure (ELS: 12 vs 10 years), and per-partner-type rates (UNY: 13% via Cooperative Banks/Societies, 15% via Small Finance Banks, set by the selected partner). Interest accrues during the moratorium (capitalized by default); repayment is quarterly by default (NSFDC's practice), with monthly/half-yearly options, an adjustable loan amount and tenure, a full amortization schedule, and a principal-vs-interest chart.
- **Geo-Spatial Partner Locator & Router** — a Leaflet/OpenStreetMap map of NSFDC's real Channel Partners (SCAs, PSBs, RRBs, NBFC-MFIs, ...), ingested from NSFDC's own published partner directories (`scripts/ingest_partners.py`). A routing policy steers applications away from partners with high NPAs, overdues or poor fund utilization (admin-entered figures — see **Partner Routing** below), markers are colour-coded by routing status, and the applicant picks a partner and routes their application to it, getting a `VS-YYYY-NNNNNN` reference they can track at `/track`.

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
| A [Groq API key](https://console.groq.com/keys) | Powers the RAG chat + AI requirement interpretation. Without it those two features return `503`; everything else still works | — |
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

- `GROQ_API_KEY` — needed for the LLM features ("Ask VittSetu" chat + `/api/interpret` form-filling). The server starts without it — the recommender, calculator, partner locator and admin console all work — but those two endpoints return a clear `503` until it's set. Get one at https://console.groq.com/keys.
- `ADMIN_TOKEN` — protects the admin console (partner capacity toggle, scheme edits). Defaults to `vittsetu-admin-dev` for local use; change it for anything beyond your own machine.
- `HF_TOKEN` — only needed to run `voice_service` (its models are gated on Hugging Face). See `voice_service/README.md` for the access request steps.
- `VOICE_SERVICE_URL` — where `api.py` looks for `voice_service`. Defaults to `http://localhost:8001`; only set it if running voice_service elsewhere.

`ffmpeg` (system package, not pip) is also required if you're running `voice_service` — it normalizes recorded audio before transcription.

Seed the structured scheme/partner database (one-time; creates `vittsetu.db`):

```bash
uv run python scripts/seed_schemes.py      # the 5 verified NSFDC schemes (seconds); safe to re-run — fills fields an older DB lacks
uv run python scripts/ingest_partners.py   # NSFDC's official Channel Partner directories (~5-8 minutes — downloads + geocodes ~80 real addresses)
```

`ingest_partners.py` is safe to skip or interrupt — the app runs fine with zero partners (the locator just shows an empty state until you run it), and re-running it later only adds partners it hasn't already ingested. Use `--only "<partner type>"` (e.g. `--only "Small Finance Bank"`) to ingest a single directory.

If the scheme-to-partner-type mapping (`SCHEME_CODES_BY_TYPE` in `ingest_partners.py`) changes, apply it to already-ingested rows without re-downloading anything:

```bash
uv run python scripts/backfill_partner_schemes.py --dry-run   # preview
uv run python scripts/backfill_partner_schemes.py
```

On startup, `api.py` adds any columns missing from an existing `vittsetu.db` (`db.migrate()`), so an older database keeps working after model changes — no need to delete it.

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

## Tests

```bash
uv pip install --python .venv -r requirements-dev.txt
uv run pytest
```

The suite runs against a throwaway SQLite database seeded from `scripts/seed_schemes.py`, with the Groq LLM mocked — it never touches your `vittsetu.db`, `chroma_db/`, `.env` keys or the network.

## Admin Console

Visit `/admin`, sign in with `ADMIN_TOKEN`. From there you can:

- **Toggle a partner's capacity** (`available` / `limited` / `not_accepting`) — `not_accepting` partners are routed away immediately; `limited` ones rank below `available` ones. Every partner starts at `available` (never a fabricated status).
- **Enter portfolio figures** (NPA %, overdue %, fund utilization %, allocated/disbursed funds, with an "as of" date) — download the CSV template, fill it in, validate, import. Imports are all-or-nothing. Single partners can also be updated via `PATCH /api/admin/partners/{id}/metrics`.
- **Manage routed applications** — advance each through `routed → acknowledged_by_partner → handed_off_to_pmsuraj → sanctioned → disbursed`, or mark it `rejected` from any open status. Every change is recorded in an audit trail.

## Partner Routing

NSFDC tracks per-partner NPAs, overdues and fund utilization internally but doesn't publish them, so VittSetu **never invents them**: they are admin-entered, and a partner without figures shows "no data". `partner_engine.RoutingPolicy` turns the figures into a routing status with a plain-language reason:

| Status | When (default thresholds) | Effect |
|---|---|---|
| `eligible` | figures on record, all within thresholds | ranked first |
| `no_data` | no figures, or figures older than 365 days | routable, ranked after `eligible` |
| `deprioritized` | NPA ≥ 5%, overdues ≥ 10%, or utilization < 60% | routable, ranked last |
| `excluded` | NPA ≥ 10%, overdues ≥ 25%, utilization < 30%, or capacity `not_accepting` | not routable; shown separately with the reason |

Routable partners are ranked by routing status, then capacity, then distance (or district match without a location). Every threshold can be overridden with an env var named `VITTSETU_ROUTING_<FIELD>` — e.g. `VITTSETU_ROUTING_NPA_EXCLUDE_PCT=12`, or `VITTSETU_ROUTING_MAX_METRICS_AGE_DAYS=none` to disable the staleness check. The defaults are illustrative starting points for NSFDC operations to tune.

**Demo data.** For a demo without real figures:

```bash
uv run python scripts/seed_demo_metrics.py          # fills partners that have no real figures
uv run python scripts/seed_demo_metrics.py --clear  # removes them again
```

These rows are tagged `metrics_updated_by = "DEMO DATA"` and labelled **DEMO DATA** everywhere they appear (partner cards, map popups, routing reasons, admin console). The script never overwrites real figures, and real figures entered later replace a partner's demo figures entirely.

## Data Provenance

- **Scheme terms** (`scripts/seed_schemes.py`): transcribed verbatim from `http://nsfdc.nic.in/scheme` and `http://nsfdc.nic.in/how-to-apply-2`, captured 2026-09-18. Update the affected fields and `last_verified_date` there (or via the admin console) if NSFDC revises its terms. The guideline rules (moratorium, tenure, per-partner-type rates) live there too as data; after changing them, run `seed_schemes.py --refresh` to apply them to an existing database (plain `seed_schemes.py` only fills empty fields, and `run.bat` runs it on every start).
- **Calculator conventions not published by NSFDC** — stated in every calculator result's notes rather than hidden: moratorium interest is simple interest on the amount disbursed (capitalized unless you choose to pay it as it falls due); instalments are equal, on a reducing balance; ELS's 12/10-year repayment period is counted after the moratorium (the scheme page lists them separately, unlike the other schemes' "including the moratorium"); "up to 6 months" moratorium is taken as 6.
- **Channel Partners** (`scripts/ingest_partners.py`): parsed from all 8 of NSFDC's published PDF directories at `http://nsfdc.nic.in/our-channel-partners`, geocoded via OpenStreetMap Nominatim. The Small Finance Bank directory lists bank names only (no addresses), so those partners appear in lists but not on the map. Which schemes each partner type channels (`SCHEME_CODES_BY_TYPE`) is sourced from `nsfdc.nic.in/scheme` and `nsfdc.nic.in/how-to-apply-2`, with the quoted wording in the code; Other Agencies/SIDBI are left unmapped because neither page says which schemes they channel.
- **Partner locator ranking** (`partner_engine.py`): with a location, nearest first nationwide (no state filter — the closest partner may be across a border); without one, the applicant's state, falling back to national results with a note if the state has none. District is a ranking preference matched against the partner's address, never a filter.
- **Partner capacity and portfolio figures** (NPA / overdue / utilization): never sourced or fabricated — live, admin-operated fields (see **Partner Routing**). Demo figures are always labelled as such.
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
├── agent.py / rag_core.py / rag_tools.py   # LangGraph RAG pipeline — powers "Ask VittSetu"
├── llm_client.py                # Lazily-built Groq client (app starts without GROQ_API_KEY)
├── db.py / models.py / schemas.py          # SQLite (schemes, partners, applications) + additive startup migration
├── scheme_engine.py             # Eligibility, best-fit recommendation + trade-offs (deterministic, no LLM)
├── financial_engine.py          # Guideline-rule-driven loan calculator + amortization schedule
├── activity_taxonomy.py         # Keyword classifier over reference_data/activity_taxonomy.json
├── partner_engine.py            # Routing policy (NPA/overdue/utilization) + geospatial ranking
├── routers/                     # /api/schemes, /calculate, /partners, /admin, /interpret, /applications
├── frontend/                    # React (Vite) app — the applicant wizard, map, admin console, Ask VittSetu
│   └── src/pages/                Home, Eligibility, Requirement, Results, Calculator, Partners, Checklist, Track, AskVittSetu, Admin
├── data/nsfdc_schemes/           # NSFDC-specific long-form docs for the RAG chatbot
├── scripts/
│   ├── seed_schemes.py           # Seeds the 5 verified NSFDC schemes into vittsetu.db
│   ├── ingest_partners.py        # Parses + geocodes NSFDC's official Channel Partner PDFs (--only <type>)
│   ├── backfill_partner_schemes.py  # Re-applies the scheme mapping to already-ingested partners
│   ├── seed_demo_metrics.py      # Fills clearly-labelled DEMO portfolio figures (--clear to remove)
│   ├── fetch_schemes.py          # Secondary: generic MyScheme.gov.in ingestion for the RAG corpus
│   ├── add_scheme.py             # Manually add a RAG document
│   └── build_index.py            # Force-rebuild the ChromaDB index
├── tests/                        # pytest suite (temp DB, mocked LLM — no network, no API key)
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

# Voice Service

Multilingual voice layer for Setu: speech-to-text (ASR) via **SraVaani-1.0** (IISc SPIRE Lab), and text-to-speech (TTS) via **edge-tts** (primary) with **Indic Parler-TTS** (AI4Bharat) as an automatic offline fallback. Runs as its own component, separate from the main RAG backend (`api.py`), so the heavy `torch`/`transformers` stack doesn't bloat that service.

## Status

`main.py` runs a working, hardened FastAPI service with `/transcribe` and `/speak`, wired into `api.py` (as a proxy — see its `/transcribe` and `/speak` endpoints) and into the frontend (mic button in `setu-scheme-navigator.html`). Run this service alongside `api.py` for voice features to work; if it's down, `api.py`'s voice endpoints return a clean `503` and text-only Q&A keeps working.

- `main.py` — the service (`/health`, `/transcribe`, `/speak`).
- `test_transcribe.py` / `test_tts.py` — standalone one-off sanity scripts (predate `main.py`).
- `download_models.py` — one-time model download/cache script.

### Running it

```bash
.venv/bin/uvicorn voice_service.main:app --port 8001
```

Run alongside `api.py` (`uvicorn api:app --reload`, port 8000). `api.py` looks for the voice service at `http://localhost:8001` by default — override with a `VOICE_SERVICE_URL` env var if it's running elsewhere.

### Endpoints

- `POST /transcribe` — multipart form upload, field name `audio`. Any format `ffmpeg` can decode (webm/opus from browser `MediaRecorder`, wav, mp3, ogg, ...) is normalized to 16kHz mono WAV before transcription. Returns `{"text": "..."}`.
- `POST /speak` — JSON body `{"text": "...", "description": "..."}` (`description` only affects the Parler-TTS fallback path, controls voice characteristics per its prompt format). Markdown is stripped from `text` before synthesis (see below). Returns `audio/mpeg` (edge-tts) or `audio/wav` (Parler-TTS fallback) — check the response `Content-Type`, don't assume one format.
- `GET /health` — `{"status": "ok", "device": "cuda:0" | "cpu", "gpu_memory": "..."}`.

Both endpoints validate input (empty/oversized uploads, empty/oversized text, undecodable audio) and return proper 4xx errors rather than crashing. Local GPU inference is serialized behind a lock, since both models share one GPU with limited VRAM and concurrent `.generate()` calls can race for memory.

### TTS: edge-tts primary, Parler-TTS fallback

`/speak` tries [`edge-tts`](https://github.com/rany2/edge-tts) first — a free Python library that calls the same neural voice engine behind Microsoft Edge's "Read aloud" feature (no API key, no billing). Verified via SraVaani round-trip: ~1-1.5s per request (vs 20-27s for local generation) with correct pronunciation across Kannada, Hindi, and English, including numerals (₹50,000 read out as "पचास हजार रुपये", not spelled digit-by-digit).

Language isn't passed explicitly — `_pick_edge_voice()` scans the text's Unicode ranges (Devanagari → `hi-IN-SwaraNeural`, Kannada script → `kn-IN-SapnaNeural`, Telugu script → `te-IN-ShrutiNeural`, else → `en-IN-NeerjaNeural`) and picks a voice accordingly.

**Known risk**: edge-tts works by replicating Microsoft Edge's internal, unpublished API rather than a supported public endpoint — it could break without warning if Microsoft changes that internal API, and using it outside an actual Edge browser session is arguably outside Microsoft's intended terms. This is exactly why it's not the only path: any exception (network failure, timeout after `EDGE_TTS_TIMEOUT=10s`, API breakage) falls back automatically to the fully local, self-hosted Parler-TTS generation — verified via a forced-failure test (`TestClient` + monkeypatched `_edge_tts_synthesize`) that the fallback still returns valid `audio/wav` on edge-tts failure.

Chrome's built-in Web Speech API (`speechSynthesis`) was considered and rejected: voice availability is a per-user, per-OS lottery (verified: only `hi-IN` was available via Chrome on Linux here, no Kannada/Telugu) — not viable for a public-facing tool where we can't ask users to install OS-level voice packs first.

### Markdown stripping before synthesis

RAG answers come back as markdown (bold, tables) for the frontend to render. Before synthesis, `_markdown_to_speech_text()` converts that through a real parser (`markdown` → HTML → `BeautifulSoup.get_text()`) rather than regex-stripping, so `**bold**`/`| table | cells |`/`` `code` `` don't get literally read aloud. The frontend's *display* of the answer is unaffected — this only touches what gets synthesized. The `MAX_SPEAK_CHARS` cap applies to the cleaned text (what actually reaches the model), not the raw markdown, since cleaning typically shortens it.

### VRAM and CUDA OOM handling

Both models load in `float16` on CUDA (`float32` on CPU, where fp16 isn't well supported) — this was a real fix, not a preemptive one: a browser-tested long, markdown-table-formatted RAG answer triggered a genuine `torch.OutOfMemoryError` under `float32` on an 8GB GPU. Measured effect of the fp16 switch:

| | float32 (before) | float16 (after) |
|---|---|---|
| SraVaani static footprint | ~1.85GB | ~0.94GB |
| Indic Parler-TTS static footprint | ~3.83GB | ~1.90GB |
| Combined baseline | ~5.68GB | ~1.90GB |

Transcription output is byte-identical between dtypes (verified). `/speak` and `/transcribe` also call `torch.cuda.empty_cache()` after each generation — PyTorch's caching allocator doesn't return freed blocks to the OS on its own, so without this, `reserved` memory only ratchets upward across requests within a long-running process; verified 5 consecutive near-max-length (1000 char) `/speak` calls all return to the same ~1.97GB reserved baseline afterward, with zero creep. Both endpoints also catch `torch.cuda.OutOfMemoryError` explicitly, returning a clean `503` (with an `empty_cache()` recovery attempt) instead of an unhandled crash.

**Known latency:** this table describes the Parler-TTS *fallback* path — with edge-tts as primary, typical `/speak` latency is now ~1-2s, not 20-27s. The fallback path (only hit when edge-tts fails) still takes ~20-27s for text near the 1000-char cap. The frontend has no loading indicator specific to `/speak` yet — worth adding, mainly for the fallback case.

### Logging

The service logs to stdout (`logging`, not `print`) — startup model-load timing and GPU memory, and per-request text/audio length, duration, and GPU memory before/after. Useful for correlating a failure with exactly what request triggered it.

### System requirement: ffmpeg

`/transcribe` shells out to `ffmpeg` to normalize incoming audio — this is a **system binary**, not a pip package. Install it via your OS package manager (e.g. `sudo dnf install ffmpeg` / `sudo apt install ffmpeg`) before running the service.

## Models

| | SraVaani-1.0 | Indic Parler-TTS |
|---|---|---|
| Task | ASR (speech → text) | TTS (text → speech) |
| Org | IISc SPIRE Lab / ARTPARK | AI4Bharat |
| Languages | 65 Indic languages/dialects | 21 Indic languages + English |
| Size | ~900MB (FP16) | ~2-3GB |
| HF repo | [`ARTPARK-IISc/SraVaani-1.0`](https://huggingface.co/ARTPARK-IISc/SraVaani-1.0) | [`ai4bharat/indic-parler-tts`](https://huggingface.co/ai4bharat/indic-parler-tts) |
| Gating | Gated, **manual approval required** | Gated, auto-approved |

Since TTS only covers 21 of SraVaani's 65 languages, voice *replies* are scoped to that shared 21-language set — outside it, we fall back to text-only responses.

### Note: transformers version

`parler-tts` pins `transformers==4.46.1`, which downgrades from the `transformers 5.15.1` pulled in by `sentence-transformers` elsewhere in the project. Both models share the same `.venv` — this has been verified to work fine: SraVaani produces identical transcription output under 4.46.1 as under 5.15.1, and a Hindi TTS → ASR round trip (Indic Parler-TTS output fed back into SraVaani) transcribed correctly.

## Setup

From the repo root:

```bash
uv venv --python 3.12 .venv          # if not already created
uv pip install --python .venv -r requirements.txt
uv pip install --python .venv -r voice_service/requirements.txt
```

### Hugging Face access

Both models are gated. You need your own HF account and access token:

1. Create a token at https://huggingface.co/settings/tokens (read access is enough).
2. Add it to `.env` in the repo root: `HF_TOKEN=hf_...`
3. **SraVaani** requires manual approval per account — visit https://huggingface.co/ARTPARK-IISc/SraVaani-1.0, request access, and wait for it to be granted before proceeding.
4. **Indic Parler-TTS** auto-approves — visiting https://huggingface.co/ai4bharat/indic-parler-tts and accepting the terms is enough.

### Download models (one-time)

```bash
.venv/bin/python voice_service/download_models.py
```

This downloads and caches both models to `~/.cache/huggingface/hub/` (not part of the repo). It exits with a clear error message if access hasn't been granted yet for either model. Expect this to take a while on first run (~3-4GB total download) — subsequent runs of the service reuse the cache and start fast.

## Hardware notes

GPU strongly recommended (both models will run on CPU but much slower). Indic Parler-TTS + SraVaani together need a few GB of VRAM — if you're also running other local models (e.g. Ollama), free that VRAM first.

## Test scripts

```bash
.venv/bin/python voice_service/test_transcribe.py   # ASR sanity check
.venv/bin/python voice_service/test_tts.py           # TTS sanity check, writes voice_service/test_samples/tts_*.wav
```

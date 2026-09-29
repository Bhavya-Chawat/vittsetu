import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env before importing any project module that reads settings.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rag_core import build_vector_store, force_rebuild_index
from agent import agent
from db import init_db
from llm_client import LLMUnavailableError
from routers import schemes, calculate, partners, admin, interpret, applications, stats

VOICE_SERVICE_URL = os.environ.get("VOICE_SERVICE_URL", "http://localhost:8001")

FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

# Browsers may call the API cross-origin only from these origins. The built
# frontend is served same-origin by this app, so production usually needs none;
# the defaults cover the Vite dev server and local single-server mode.
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"
CORS_ORIGINS = [o.strip() for o in os.environ.get("VITTSETU_CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()]

app = FastAPI(title="VittSetu — SC Channel Finance Navigator API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH"],
    allow_headers=["Content-Type", "X-Admin-Token", "X-Admin-User"],
)

app.include_router(schemes.router)
app.include_router(calculate.router)
app.include_router(partners.router)
app.include_router(admin.router)
app.include_router(interpret.router)
app.include_router(applications.router)
app.include_router(stats.router)

if admin.is_production() and admin.expected_admin_token() is None:
    print("[WARN] VITTSETU_ENV=production but ADMIN_TOKEN is unset or the default — the admin console is disabled.")


@app.exception_handler(LLMUnavailableError)
def llm_unavailable_handler(request: Request, exc: LLMUnavailableError):
    """LLM-backed endpoints (/ask, /api/interpret) fail cleanly without GROQ_API_KEY."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})

# Build index once at startup
init_db()
collection = build_vector_store()


class Query(BaseModel):
    question: str
    history: list = []
    language: str = "en"


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "chunks_indexed": collection.count()}

@app.post("/reindex")
def reindex():
    """Force rebuild the vector store index from data/ directory."""
    global collection
    collection = force_rebuild_index()
    return {"status": "success", "chunks_indexed": collection.count()}

@app.post("/ask")
def ask(q: Query):
    result = agent.invoke({
        "question": q.question,
        "chat_history": q.history,
        "language": q.language,
        "rewritten_query": "",
        "retrieved_text": "",
        "route": "",
        "relevance": "",
        "retries": 0,
        "answer": "",
    })
    return {"answer": result["answer"]}


class SpeakRequest(BaseModel):
    text: str
    description: str | None = None


@app.post("/transcribe")
async def transcribe(audio: UploadFile):
    """Proxy: forwards recorded audio to the voice service and returns its transcript."""
    raw = await audio.read()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{VOICE_SERVICE_URL}/transcribe",
                files={"audio": (audio.filename, raw, audio.content_type)},
            )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Voice service is unreachable.")
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = "Transcription failed."
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


@app.post("/speak")
async def speak(req: SpeakRequest):
    """Proxy: forwards text to the voice service and streams back synthesized audio."""
    body = {"text": req.text}
    if req.description:
        body["description"] = req.description
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{VOICE_SERVICE_URL}/speak", json=body)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Voice service is unreachable.")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Speech synthesis failed.")
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "audio/wav"))


# ── Frontend (React SPA) ─────────────────────────────────────────────────
# Only active once `npm --prefix frontend run build` has produced dist/.
# During development, run the Vite dev server separately (see README) —
# its proxy config forwards /api, /ask, /transcribe, /speak, /health to
# this backend, so this block stays inactive and out of the way.
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend_assets")

    @app.get("/favicon.svg")
    def frontend_favicon():
        return FileResponse(FRONTEND_DIST / "favicon.svg")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        """SPA fallback: any non-API path renders the React app, which handles routing client-side."""
        return FileResponse(FRONTEND_DIST / "index.html")
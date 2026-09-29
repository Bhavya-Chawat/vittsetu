"""Shared fixtures: a throwaway SQLite DB seeded with the real NSFDC schemes,
and FastAPI TestClients with the Groq LLM either mocked or unconfigured.

Environment is pinned at import time — before any project module loads — so
nothing here touches the developer's vittsetu.db, chroma_db/, .env secrets or
the network.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

_TMP = Path(tempfile.mkdtemp(prefix="vittsetu-tests-"))
os.environ["VITTSETU_DB_PATH"] = str(_TMP / "test.db")
# Present-but-empty: load_dotenv never overrides an existing variable, so a real
# key in .env can't leak in, and llm_client treats "" as not configured.
os.environ["GROQ_API_KEY"] = ""
os.environ["ADMIN_TOKEN"] = "test-admin-token"

import rag_core  # noqa: E402

# api.py builds the vector store at import; point it at empty temp dirs so the
# embedding model is never loaded and the real chroma_db/ is never written.
rag_core.CHROMA_DIR = str(_TMP / "chroma_db")
rag_core.DATA_DIR = _TMP / "data"
rag_core.DATA_DIR.mkdir()

import llm_client  # noqa: E402
from db import Base, SessionLocal, engine  # noqa: E402
from models import Partner  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token"}


@pytest.fixture
def db_session():
    """Fresh schema per test, seeded with the 5 schemes from scripts/seed_schemes.py."""
    import seed_schemes

    Base.metadata.drop_all(bind=engine)
    seed_schemes.seed()  # init_db() + inserts SCHEMES exactly as production seeding does
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_partner(db_session):
    """Factory: insert a Partner with sensible defaults, overridable per field."""
    def _make(name, **fields):
        fields.setdefault("partner_type", "SCA")
        fields.setdefault("eligible_scheme_codes", ["MFS", "TERM_LOAN", "ELS"])
        fields.setdefault("capacity_status", "available")
        partner = Partner(name=name, **fields)
        db_session.add(partner)
        db_session.commit()
        return partner
    return _make


class FakeLLM:
    """Stands in for ChatGroq: records prompts, answers via a swappable function."""

    def __init__(self):
        self.prompts: list[str] = []
        self.reply = lambda prompt: "Mocked answer."

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return type("AIMessage", (), {"content": self.reply(prompt)})()


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm_client, "get_llm", lambda max_tokens: fake)
    return fake


def _app():
    import api  # imported lazily so the environment above is in place first
    return api.app


@pytest.fixture
def client(db_session, fake_llm):
    """TestClient with the Groq LLM mocked."""
    from fastapi.testclient import TestClient
    return TestClient(_app())


@pytest.fixture
def client_without_llm(db_session):
    """TestClient with no GROQ_API_KEY configured — LLM features must degrade to 503."""
    from fastapi.testclient import TestClient
    return TestClient(_app())

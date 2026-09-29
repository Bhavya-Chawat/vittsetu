"""Startup without an LLM key, admin auth, and the additive DB migration."""

import json

import pytest

from sqlalchemy import create_engine, inspect, text

from conftest import ADMIN_HEADERS
from db import migrate


# ── Works without GROQ_API_KEY ───────────────────────────────────────────────

def test_rule_engine_calculator_and_locator_work_without_llm_key(client_without_llm):
    c = client_without_llm
    assert len(c.get("/api/schemes").json()) == 5

    rec = c.post("/api/recommend", json={
        "profile": {"annual_family_income": 200000, "is_sc_category": True, "purpose": "business"},
        "business": {"project_type": "Tailoring", "estimated_cost": 100000},
    })
    assert rec.status_code == 200
    assert {m["scheme"]["code"] for m in rec.json()["matched"]} == {"MFS", "AMY", "UNY"}

    calc = c.post("/api/calculate", json={"scheme_code": "MFS", "project_cost": 100000})
    assert calc.status_code == 200
    assert calc.json()["loan_amount"] == 90000

    assert c.post("/api/partners/nearby", json={"scheme_code": "MFS"}).status_code == 200
    assert c.get("/api/admin/partners", headers=ADMIN_HEADERS).status_code == 200


def test_llm_endpoints_return_503_without_key(client_without_llm):
    ask = client_without_llm.post("/ask", json={"question": "What is MFS?"})
    assert ask.status_code == 503
    assert "GROQ_API_KEY" in ask.json()["detail"]

    interp = client_without_llm.post("/api/interpret", json={"text": "tailoring shop, 2 lakh"})
    assert interp.status_code == 503


# ── With the LLM mocked ──────────────────────────────────────────────────────

def test_interpret_uses_llm_output(client, fake_llm):
    fake_llm.reply = lambda prompt: json.dumps(
        {"purpose": "business", "project_type": "Tailoring", "estimated_cost": 200000}
    )

    body = client.post("/api/interpret", json={"text": "tailoring shop, 2 lakh"}).json()

    assert body["project_type"] == "Tailoring"
    assert body["estimated_cost"] == 200000
    assert "tailoring shop, 2 lakh" in fake_llm.prompts[0]


def test_ask_off_topic_goes_direct(client, fake_llm):
    fake_llm.reply = lambda prompt: "direct" if "classifier" in prompt else "Hello! Ask me about schemes."

    resp = client.post("/ask", json={"question": "hi"})

    assert resp.status_code == 200
    assert resp.json()["answer"] == "Hello! Ask me about schemes."


# ── Admin auth ───────────────────────────────────────────────────────────────

def test_admin_requires_token_from_env(client, monkeypatch):
    assert client.get("/api/admin/schemes").status_code == 401
    assert client.get("/api/admin/schemes", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert client.get("/api/admin/schemes", headers=ADMIN_HEADERS).status_code == 200

    # Read per request, not frozen at import time.
    monkeypatch.setenv("ADMIN_TOKEN", "rotated")
    assert client.get("/api/admin/schemes", headers=ADMIN_HEADERS).status_code == 401
    assert client.get("/api/admin/schemes", headers={"X-Admin-Token": "rotated"}).status_code == 200


# ── Migration ────────────────────────────────────────────────────────────────

def test_migrate_adds_missing_columns_to_existing_tables(tmp_path):
    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as conn:
        # A partners table from "before" capacity tracking and scheme codes existed.
        conn.execute(text("CREATE TABLE partners (id INTEGER PRIMARY KEY, name VARCHAR(300) NOT NULL, "
                          "partner_type VARCHAR(50) NOT NULL)"))
        conn.execute(text("INSERT INTO partners (name, partner_type) VALUES ('Old Row', 'SCA')"))

    added = migrate(bind=old)

    assert "partners.capacity_status" in added
    assert "partners.eligible_scheme_codes" in added
    assert not any(a.startswith("schemes.") for a in added)  # absent tables are left to create_all

    cols = {c["name"] for c in inspect(old).get_columns("partners")}
    assert {"capacity_status", "eligible_scheme_codes", "lat", "lon", "updated_at"} <= cols

    with old.connect() as conn:
        row = conn.execute(text("SELECT capacity_status, eligible_scheme_codes FROM partners")).one()
        # Scalar default via SQL DEFAULT; callable default (list) backfilled.
        assert row.capacity_status == "available"
        assert json.loads(row.eligible_scheme_codes) == []

        conn.execute(text("INSERT INTO partners (name, partner_type) VALUES ('New Row', 'PSB')"))
        assert conn.execute(text("SELECT capacity_status FROM partners WHERE name='New Row'")).scalar() == "available"

    assert migrate(bind=old) == []  # idempotent


def test_migrate_creates_missing_unique_index(tmp_path):
    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE applications (id INTEGER PRIMARY KEY, status VARCHAR(30))"))

    added = migrate(bind=old)

    assert "applications.reference" in added
    assert "index:ix_applications_reference" in added
    [index] = [ix for ix in inspect(old).get_indexes("applications") if ix["name"] == "ix_applications_reference"]
    assert index["unique"]
    with old.begin() as conn:
        conn.execute(text("INSERT INTO applications (reference) VALUES ('VS-2026-000001')"))
        with pytest.raises(Exception):
            conn.execute(text("INSERT INTO applications (reference) VALUES ('VS-2026-000001')"))

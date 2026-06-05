"""
Integration tests via FastAPI TestClient over an isolated in-memory SQLite DB.

Covers the multi-user invariants we care about most:
  - auth (signup/login/me),
  - per-user data isolation on /api/jobs,
  - rerank / reset-rankings semantics,
  - admin gating (ADMIN_EMAILS),
  - account + data deletion,
  - safe résumé-upload validation.

The pipeline (run_pipeline) is monkeypatched to a no-op so /rerank doesn't try
to hit an LLM or the global engine in a background task.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_jobs
from app.config import settings
from app.db.base import Base
from app.db import models
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    # One shared in-memory connection for the whole test (StaticPool), so tables
    # created here are visible to every request.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    # Don't actually run the pipeline from /rerank's background task.
    monkeypatch.setattr(routes_jobs, "run_pipeline", lambda *a, **k: "")
    monkeypatch.setattr(settings, "admin_emails_raw", "")

    c = TestClient(app)
    c._Session = TestSession  # expose for direct DB seeding in tests
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _signup(client, email, password="password123", name="T"):
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "name": name})
    assert r.status_code == 201, r.text
    return r.json()["access_token"], r.json()["user"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── auth ──────────────────────────────────────────────────────────────
def test_signup_login_me(client):
    token, user = _signup(client, "alice@test.com")
    assert user["email"] == "alice@test.com"
    assert user["is_admin"] is False

    r = client.post("/api/auth/login", json={"email": "alice@test.com", "password": "password123"})
    assert r.status_code == 200
    r = client.get("/api/auth/me", headers=_auth(token))
    assert r.status_code == 200 and r.json()["email"] == "alice@test.com"

    # wrong password
    assert client.post(
        "/api/auth/login", json={"email": "alice@test.com", "password": "nope"}
    ).status_code == 401


def test_protected_routes_require_auth(client):
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/dashboard/summary").status_code == 401


# ── per-user isolation ────────────────────────────────────────────────
def _seed_job_and_ranking(session, user_id, title="Backend Engineer", score=90):
    job = models.Job(
        source="greenhouse", external_id=f"ext-{user_id[:6]}-{title}",
        url=f"https://ex.com/{user_id[:6]}/{title}", url_hash=f"h{user_id[:6]}{title}"[:64],
        title=title, company="Acme", description="Build APIs", status="new",
    )
    session.add(job)
    session.flush()
    session.add(models.Ranking(user_id=user_id, job_id=job.id, rank_score=score, status="ranked"))
    session.commit()
    return job.id


def test_jobs_are_isolated_per_user(client):
    t1, u1 = _signup(client, "u1@test.com")
    t2, u2 = _signup(client, "u2@test.com")
    with client._Session() as s:
        _seed_job_and_ranking(s, u1["id"])

    r1 = client.get("/api/jobs?min_rank=0", headers=_auth(t1)).json()
    r2 = client.get("/api/jobs?min_rank=0", headers=_auth(t2)).json()
    assert r1["total"] == 1
    assert r2["total"] == 0  # user 2 must NOT see user 1's ranking


# ── rerank / reset ────────────────────────────────────────────────────
def test_rerank_requires_resume(client):
    t1, _ = _signup(client, "noresume@test.com")
    assert client.post("/api/jobs/rerank", headers=_auth(t1)).status_code == 400


def test_reset_rankings_keeps_protected(client):
    t1, u1 = _signup(client, "reset@test.com")
    with client._Session() as s:
        jid_ranked = _seed_job_and_ranking(s, u1["id"], title="Ranked Role", score=80)
        jid_tailored = _seed_job_and_ranking(s, u1["id"], title="Tailored Role", score=85)
        rk = s.query(models.Ranking).filter_by(job_id=jid_tailored).first()
        rk.status = "tailored"
        s.commit()

    r = client.post("/api/jobs/reset-rankings", headers=_auth(t1))
    assert r.status_code == 200 and r.json()["cleared"] == 1  # only the 'ranked' one

    remaining = client.get("/api/jobs?min_rank=0&status=tailored", headers=_auth(t1)).json()
    assert remaining["total"] == 1


# ── admin gating ──────────────────────────────────────────────────────
def test_admin_requires_admin(client, monkeypatch):
    t1, _ = _signup(client, "regular@test.com")
    assert client.get("/api/admin/users", headers=_auth(t1)).status_code == 403

    # Promote via ADMIN_EMAILS (request-time check) and retry.
    monkeypatch.setattr(settings, "admin_emails_raw", "regular@test.com")
    r = client.get("/api/admin/users", headers=_auth(t1))
    assert r.status_code == 200
    assert any(u["email"] == "regular@test.com" for u in r.json())
    assert client.get("/api/admin/stats", headers=_auth(t1)).status_code == 200


# ── delete account ────────────────────────────────────────────────────
def test_delete_account_removes_user_and_data(client):
    t1, u1 = _signup(client, "delete@test.com")
    with client._Session() as s:
        _seed_job_and_ranking(s, u1["id"])
    assert client.delete("/api/auth/me", headers=_auth(t1)).status_code == 204
    # Token now resolves to a missing user → 401.
    assert client.get("/api/auth/me", headers=_auth(t1)).status_code == 401
    with client._Session() as s:
        assert s.query(models.Ranking).filter_by(user_id=u1["id"]).count() == 0


# ── upload validation ─────────────────────────────────────────────────
def test_upload_rejects_bad_magic_bytes(client):
    t1, _ = _signup(client, "upload@test.com")
    files = {"file": ("resume.pdf", b"this is not really a pdf", "application/pdf")}
    r = client.post("/api/resume/upload", headers=_auth(t1), files=files)
    assert r.status_code == 415


def test_upload_rejects_unknown_extension(client):
    t1, _ = _signup(client, "upload2@test.com")
    files = {"file": ("resume.exe", b"MZ\x90\x00", "application/octet-stream")}
    r = client.post("/api/resume/upload", headers=_auth(t1), files=files)
    assert r.status_code == 415


def test_upload_rejects_empty(client):
    t1, _ = _signup(client, "upload3@test.com")
    files = {"file": ("resume.pdf", b"", "application/pdf")}
    r = client.post("/api/resume/upload", headers=_auth(t1), files=files)
    assert r.status_code == 400

"""
Integration tests for production reliability features:
  - closed jobs hidden by default
  - forgot/reset password (success, wrong code, expired)
  - admin /sources and /system-health
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import models
from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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
    monkeypatch.setattr(settings, "admin_emails_raw", "")
    c = TestClient(app)
    c._Session = TestSession
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _signup(client, email="u@test.com", pw="password123"):
    r = client.post("/api/auth/signup", json={"email": email, "password": pw})
    assert r.status_code == 201, r.text
    return r.json()["access_token"], r.json()["user"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _seed_job(s, ext="1", open_status="open", company="Acme"):
    j = models.Job(
        source="greenhouse", external_id=ext, url=f"https://ex.com/{ext}",
        url_hash=f"h{ext}"[:64], title="Backend Engineer", company=company,
        description="Build APIs", status="new", open_status=open_status,
    )
    s.add(j)
    s.flush()
    return j.id


def _rank(s, uid, jid, score=80):
    s.add(models.Ranking(user_id=uid, job_id=jid, rank_score=score, status="ranked", match_label="good"))
    s.commit()


# ── closed jobs ──
def test_closed_job_hidden_by_default(client):
    t, u = _signup(client, "c@test.com")
    with client._Session() as s:
        open_id = _seed_job(s, "o1", "open")
        closed_id = _seed_job(s, "c1", "closed", company="Globex")
        _rank(s, u["id"], open_id)
        _rank(s, u["id"], closed_id)

    res = client.get("/api/jobs?min_rank=0", headers=_auth(t)).json()
    ids = {it["id"] for it in res["items"]}
    assert open_id in ids and closed_id not in ids  # closed hidden by default

    res2 = client.get("/api/jobs?min_rank=0&include_closed=true", headers=_auth(t)).json()
    ids2 = {it["id"] for it in res2["items"]}
    assert closed_id in ids2

    one = client.get(f"/api/jobs/{closed_id}", headers=_auth(t)).json()
    assert one["open_status"] == "closed"  # badge data still available when opened


def test_job_exposes_source_confidence(client):
    t, u = _signup(client, "sc@test.com")
    with client._Session() as s:
        jid = _seed_job(s, "x1")
        _rank(s, u["id"], jid)
    res = client.get("/api/jobs?min_rank=0", headers=_auth(t)).json()
    assert res["items"][0]["source_confidence"] == "high"  # greenhouse


# ── forgot / reset password ──
def test_forgot_and_reset_password(client):
    _signup(client, "fp@test.com", "oldpassword1")
    # forgot → dev_otp returned (no provider in dev)
    r = client.post("/api/auth/forgot-password", json={"email": "fp@test.com"})
    assert r.status_code == 200
    code = r.json().get("dev_otp")
    assert code

    # wrong code rejected
    bad = client.post("/api/auth/reset-password",
                      json={"email": "fp@test.com", "code": "000000", "new_password": "newpassword1"})
    assert bad.status_code == 400

    # correct code → new password works
    ok = client.post("/api/auth/reset-password",
                     json={"email": "fp@test.com", "code": code, "new_password": "newpassword1"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert client.post("/api/auth/login", json={"email": "fp@test.com", "password": "newpassword1"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "fp@test.com", "password": "oldpassword1"}).status_code == 401


def test_forgot_password_unknown_email_is_generic(client):
    r = client.post("/api/auth/forgot-password", json={"email": "ghost@test.com"})
    assert r.status_code == 200 and r.json()["status"] == "otp_sent"


def test_reset_password_expired_code(client):
    _signup(client, "exp@test.com", "oldpassword1")
    r = client.post("/api/auth/forgot-password", json={"email": "exp@test.com"})
    code = r.json()["dev_otp"]
    with client._Session() as s:
        row = (
            s.query(models.EmailOTP)
            .join(models.User)
            .filter(models.User.email == "exp@test.com")
            .first()
        )
        row.expires_at = dt.datetime.utcnow() - dt.timedelta(minutes=1)
        s.commit()
    bad = client.post("/api/auth/reset-password",
                      json={"email": "exp@test.com", "code": code, "new_password": "newpassword1"})
    assert bad.status_code == 400 and "expired" in bad.json()["detail"].lower()


# ── admin diagnostics ──
def test_admin_sources_and_system_health(client, monkeypatch):
    t, _ = _signup(client, "admin@test.com")
    # not admin yet
    assert client.get("/api/admin/sources", headers=_auth(t)).status_code == 403
    monkeypatch.setattr(settings, "admin_emails_raw", "admin@test.com")
    # Make the credential check deterministic regardless of any ambient .env.
    monkeypatch.setattr(settings, "adzuna_app_id", "")
    monkeypatch.setattr(settings, "adzuna_app_key", "")

    srcs = client.get("/api/admin/sources", headers=_auth(t))
    assert srcs.status_code == 200
    by_name = {s["name"]: s for s in srcs.json()}
    assert by_name["greenhouse"]["confidence"] == "high"
    assert by_name["indeed"]["stub"] is True
    # adzuna requires creds → flagged missing when unset
    assert "ADZUNA_APP_ID" in by_name["adzuna"]["missing_credentials"]

    sh = client.get("/api/admin/system-health", headers=_auth(t)).json()
    assert "verification_active" in sh and "email_misconfigured" in sh

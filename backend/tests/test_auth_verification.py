"""
Email-OTP verification + verified-user gating (integration, in-memory SQLite).

Verification is force-enabled here (the rest of the suite runs with it off). With
no email provider configured in dev, the signup-start / resend responses include
a `dev_otp` we use to drive the flow.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_runs
from app.auth.security import create_access_token
from app.config import settings
from app.db import models
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services import otp


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
    # Enforce verification for these tests; never actually send email.
    monkeypatch.setattr(settings, "require_email_verification", True)
    monkeypatch.setattr(settings, "email_provider", "")
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(routes_runs, "run_pipeline", lambda *a, **k: "")
    c = TestClient(app)
    c._Session = TestSession
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _start(client, email="new@test.com", pw="password123", **extra):
    return client.post(
        "/api/auth/signup-start",
        json={"email": email, "password": pw, **extra},
    )


# ── signup creates an UNVERIFIED user + an OTP ──
def test_signup_creates_unverified_user(client):
    r = _start(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "otp_sent"
    assert body.get("dev_otp")  # dev convenience
    assert "access_token" not in body  # no login until verified

    with client._Session() as s:
        u = s.query(models.User).filter_by(email="new@test.com").first()
        assert u is not None
        assert u.email_verified is False
        otps = s.query(models.EmailOTP).filter_by(user_id=u.id).all()
        assert len(otps) == 1


def test_otp_hash_not_plaintext(client):
    r = _start(client, email="hash@test.com")
    code = r.json()["dev_otp"]
    with client._Session() as s:
        row = s.query(models.EmailOTP).join(models.User).filter(
            models.User.email == "hash@test.com"
        ).first()
        assert row.otp_hash != code               # not stored in plaintext
        assert row.otp_hash == otp.hash_otp(code)  # but is the HMAC of it


def test_wrong_otp_rejected(client):
    _start(client, email="wrong@test.com")
    r = client.post("/api/auth/verify-email", json={"email": "wrong@test.com", "code": "000000"})
    assert r.status_code == 400
    with client._Session() as s:
        u = s.query(models.User).filter_by(email="wrong@test.com").first()
        assert u.email_verified is False


def test_expired_otp_rejected(client):
    r = _start(client, email="exp@test.com")
    code = r.json()["dev_otp"]
    with client._Session() as s:
        row = s.query(models.EmailOTP).join(models.User).filter(
            models.User.email == "exp@test.com"
        ).first()
        row.expires_at = dt.datetime.utcnow() - dt.timedelta(minutes=1)
        s.commit()
    r = client.post("/api/auth/verify-email", json={"email": "exp@test.com", "code": code})
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()


def test_correct_otp_verifies_and_logs_in(client):
    r = _start(client, email="ok@test.com")
    code = r.json()["dev_otp"]
    r = client.post("/api/auth/verify-email", json={"email": "ok@test.com", "code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["user"]["email_verified"] is True
    with client._Session() as s:
        u = s.query(models.User).filter_by(email="ok@test.com").first()
        assert u.email_verified is True and u.email_verified_at is not None


def test_resend_is_generic_for_unknown_email(client):
    # No enumeration: unknown email still returns a generic otp_sent.
    r = client.post("/api/auth/resend-otp", json={"email": "ghost@test.com"})
    assert r.status_code == 200
    assert r.json()["status"] == "otp_sent"


def test_login_unverified_is_blocked(client):
    _start(client, email="li@test.com", pw="password123")
    r = client.post("/api/auth/login", json={"email": "li@test.com", "password": "password123"})
    assert r.status_code == 403
    assert "verif" in r.json()["detail"].lower()


# ── verified-user gating ──
def _mint(user_id):
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def test_unverified_token_cannot_run_or_save(client):
    with client._Session() as s:
        u = models.User(email="u1@test.com", password_hash="x", email_verified=False)
        s.add(u)
        s.commit()
        uid = u.id
    h = _mint(uid)
    assert client.post("/api/runs/trigger", headers=h).status_code == 403
    assert client.post("/api/jobs/reset-rankings", headers=h).status_code == 403
    assert client.post("/api/watchlist", headers=h, json={"company": "Stripe"}).status_code == 403


def test_verified_token_can_run(client):
    with client._Session() as s:
        u = models.User(email="u2@test.com", password_hash="x", email_verified=True)
        s.add(u)
        s.commit()
        uid = u.id
    r = client.post("/api/runs/trigger", headers=_mint(uid))
    assert r.status_code == 200
    assert r.json()["status"] == "started"


# ── guest résumé attaches after signup + verification ──
def test_guest_resume_attaches_after_verification(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.resume_parser.extract_and_parse",
        lambda fn, data: ("raw résumé text", {"name": "Guest User", "skills": {"languages": ["Python"]}}),
    )
    up = client.post(
        "/api/guest/upload",
        files={"file": ("resume.txt", b"Some real resume text here.", "text/plain")},
    )
    assert up.status_code == 200, up.text
    token = up.json()["token"]

    r = _start(client, email="g@test.com", guest_token=token)
    code = r.json()["dev_otp"]
    r = client.post("/api/auth/verify-email", json={"email": "g@test.com", "code": code})
    assert r.status_code == 200
    auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

    me = client.get("/api/resume/me", headers=auth)
    assert me.status_code == 200
    body = me.json()
    assert body["has_resume"] is True
    assert body["parsed_json"]["name"] == "Guest User"

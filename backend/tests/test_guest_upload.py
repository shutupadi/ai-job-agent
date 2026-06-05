"""
Guest (pre-signup) résumé upload + preview (integration, in-memory SQLite).

The real parser would call an LLM, so extract_and_parse is monkeypatched.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    monkeypatch.setattr(
        "app.services.resume_parser.extract_and_parse",
        lambda fn, data: (
            "raw text",
            {
                "name": "Ada Lovelace",
                "experience_years": 3,
                "seniority": "mid",
                "role_direction": "software engineering",
                "target_titles": ["Backend Engineer"],
                "primary_skills": ["Python", "FastAPI"],
                "skills": {"languages": ["Python"]},
            },
        ),
    )
    c = TestClient(app)
    c._Session = TestSession
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _upload(client, name="resume.txt", content=b"A real resume body with text."):
    return client.post(
        "/api/guest/upload",
        files={"file": (name, content, "text/plain")},
    )


def test_guest_upload_parses_and_stores(client):
    r = _upload(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"]
    assert body["profile"]["name"] == "Ada Lovelace"
    assert body["profile"]["experience_years"] == 3
    assert "Python" in body["profile"]["primary_skills"]
    # stored as an unclaimed guest session
    with client._Session() as s:
        gs = s.query(models.GuestSession).filter_by(token=body["token"]).first()
        assert gs is not None and gs.claimed is False
        assert gs.parsed_json["name"] == "Ada Lovelace"


def test_guest_get_by_token(client):
    token = _upload(client).json()["token"]
    r = client.get(f"/api/guest/{token}")
    assert r.status_code == 200
    assert r.json()["profile"]["name"] == "Ada Lovelace"


def test_guest_expired_returns_404(client):
    token = _upload(client).json()["token"]
    with client._Session() as s:
        gs = s.query(models.GuestSession).filter_by(token=token).first()
        gs.expires_at = dt.datetime.utcnow() - dt.timedelta(hours=1)
        s.commit()
    assert client.get(f"/api/guest/{token}").status_code == 404


def test_guest_upload_rejects_bad_type(client):
    r = client.post(
        "/api/guest/upload",
        files={"file": ("evil.exe", b"MZ\x00\x00binary", "application/octet-stream")},
    )
    assert r.status_code == 415


def test_no_account_created_for_guest(client):
    _upload(client)
    with client._Session() as s:
        assert s.query(models.User).count() == 0

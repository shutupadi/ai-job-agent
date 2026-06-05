"""
Integration tests for the job-intelligence endpoints (preferences, watchlist,
feedback, career profile, source health) over an isolated in-memory SQLite DB.
"""

from __future__ import annotations

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


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    return r.json()["access_token"], r.json()["user"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_job(s, title="Backend Engineer", company="Acme", ext="1"):
    job = models.Job(
        source="greenhouse", external_id=ext, url=f"https://ex.com/{ext}",
        url_hash=f"h{ext}"[:64], title=title, company=company,
        description="Build APIs", status="new",
    )
    s.add(job)
    s.flush()
    return job.id


def _rank(s, user_id, job_id, score=80, status="ranked", saved=False):
    s.add(models.Ranking(
        user_id=user_id, job_id=job_id, rank_score=score, status=status,
        saved=saved, match_label="good",
    ))
    s.commit()


# ── preferences ──
def test_preferences_get_default_then_update(client):
    t, _ = _signup(client, "p1@test.com")
    r = client.get("/api/preferences", headers=_auth(t))
    assert r.status_code == 200
    assert r.json()["target_roles"] == []

    upd = {"target_roles": ["Backend Engineer"], "min_salary_lpa": 20,
           "must_have_skills": ["python"], "alert_instant": True}
    r = client.put("/api/preferences", headers=_auth(t), json=upd)
    assert r.status_code == 200
    body = r.json()
    assert body["target_roles"] == ["Backend Engineer"]
    assert body["min_salary_lpa"] == 20
    assert body["alert_instant"] is True
    # persisted
    assert client.get("/api/preferences", headers=_auth(t)).json()["must_have_skills"] == ["python"]


# ── watchlist ──
def test_watchlist_crud_and_isolation(client):
    t1, _ = _signup(client, "w1@test.com")
    t2, _ = _signup(client, "w2@test.com")
    r = client.post("/api/watchlist", headers=_auth(t1), json={"company": "Stripe"})
    assert r.status_code == 201
    item_id = r.json()["id"]
    assert r.json()["priority"] == "prioritize"

    # user2 cannot see or modify user1's item
    assert client.get("/api/watchlist", headers=_auth(t2)).json() == []
    assert client.patch(f"/api/watchlist/{item_id}", headers=_auth(t2),
                        json={"priority": "block"}).status_code == 404

    # owner updates + deletes
    assert client.patch(f"/api/watchlist/{item_id}", headers=_auth(t1),
                        json={"priority": "block"}).json()["priority"] == "block"
    assert client.delete(f"/api/watchlist/{item_id}", headers=_auth(t1)).status_code == 204
    assert client.get("/api/watchlist", headers=_auth(t1)).json() == []


def test_watchlist_dedupes_by_company(client):
    t, _ = _signup(client, "w3@test.com")
    client.post("/api/watchlist", headers=_auth(t), json={"company": "Stripe, Inc."})
    client.post("/api/watchlist", headers=_auth(t), json={"company": "stripe", "priority": "normal"})
    items = client.get("/api/watchlist", headers=_auth(t)).json()
    assert len(items) == 1
    assert items[0]["priority"] == "normal"  # second upsert won


# ── feedback ──
def test_hide_company_hides_all_its_jobs(client):
    t, u = _signup(client, "f1@test.com")
    with client._Session() as s:
        j1 = _seed_job(s, "Backend Engineer", "Acme", "a1")
        j2 = _seed_job(s, "Frontend Engineer", "Acme Inc", "a2")  # same company, diff suffix
        j3 = _seed_job(s, "Backend Engineer", "Globex", "g1")
        _rank(s, u["id"], j1); _rank(s, u["id"], j2); _rank(s, u["id"], j3)

    # hide via j1 → both Acme rankings hidden, Globex remains
    r = client.post(f"/api/jobs/{j1}/feedback", headers=_auth(t), json={"action": "hide_company"})
    assert r.status_code == 200 and r.json()["hidden"] is True
    visible = client.get("/api/jobs?min_rank=0", headers=_auth(t)).json()
    companies = {it["company"] for it in visible["items"]}
    assert companies == {"Globex"}


def test_save_then_reset_preserves_saved(client):
    t, u = _signup(client, "f2@test.com")
    with client._Session() as s:
        j1 = _seed_job(s, ext="s1")
        j2 = _seed_job(s, company="Globex", ext="s2")
        _rank(s, u["id"], j1); _rank(s, u["id"], j2)
    client.post(f"/api/jobs/{j1}/feedback", headers=_auth(t), json={"action": "save"})
    r = client.post("/api/jobs/reset-rankings", headers=_auth(t))
    assert r.status_code == 200 and r.json()["cleared"] == 1   # only the unsaved one
    saved = client.get("/api/jobs?min_rank=0&saved_only=true", headers=_auth(t)).json()
    assert saved["total"] == 1


# ── career profile ──
def test_career_profile_edit(client):
    t, u = _signup(client, "cp@test.com")
    # no résumé yet → 404
    assert client.get("/api/preferences/profile", headers=_auth(t)).status_code == 404
    with client._Session() as s:
        s.add(models.Resume(
            user_id=u["id"], filename="r.pdf", raw_text="x",
            parsed_json={"name": "A", "experience_years": 2, "seniority": "mid",
                         "role_direction": "software engineering", "target_titles": []},
            is_active=True,
        ))
        s.commit()
    r = client.put("/api/preferences/profile", headers=_auth(t),
                   json={"target_titles": ["SDE II"], "experience_years": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["target_titles"] == ["SDE II"]
    assert body["experience_years"] == 4


# ── admin source health ──
def test_source_health_admin_only(client, monkeypatch):
    t, _ = _signup(client, "sh@test.com")
    with client._Session() as s:
        s.add(models.SourceHealth(source="greenhouse", jobs_found=10, jobs_added=3))
        s.commit()
    assert client.get("/api/admin/source-health", headers=_auth(t)).status_code == 403
    monkeypatch.setattr(settings, "admin_emails_raw", "sh@test.com")
    r = client.get("/api/admin/source-health", headers=_auth(t))
    assert r.status_code == 200
    assert any(row["source"] == "greenhouse" for row in r.json())

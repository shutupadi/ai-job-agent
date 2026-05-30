"""Résumé endpoints — upload/parse master résumé, list tailored versions, tailor."""

from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.config import settings
from app.db import models
from app.db.session import get_db
from app.schemas.schemas import (
    CoverLetterOut,
    MasterResumeOut,
    ResumeVersionOut,
    TailorRequest,
    TailorResponse,
)
from app.services import cover_letter as cover_letter_svc
from app.services import resume_engine, resume_parser

router = APIRouter()


def _active_resume(db: Session, user_id: str) -> models.Resume | None:
    return (
        db.query(models.Resume)
        .filter(models.Resume.user_id == user_id, models.Resume.is_active.is_(True))
        .order_by(models.Resume.created_at.desc())
        .first()
    )


# ── master résumé (per user) ──────────────────────────────────────────
@router.get("/me", response_model=MasterResumeOut)
def my_resume(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    row = _active_resume(db, user.id)
    if not row:
        return MasterResumeOut(has_resume=False)
    return MasterResumeOut(
        id=row.id, filename=row.filename, parsed_json=row.parsed_json,
        created_at=row.created_at, has_resume=True,
    )


@router.post("/upload", response_model=MasterResumeOut)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Upload a PDF/DOCX/TXT résumé → AI parses it → becomes your active master."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > settings.max_resume_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {settings.max_resume_mb} MB).")
    try:
        text, parsed = resume_parser.extract_and_parse(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Could not parse résumé: {e}")

    # Persist the original file under storage/uploads/<user_id>/.
    safe = "".join(c for c in (file.filename or "resume") if c.isalnum() or c in "._-")[:60] or "resume"
    updir = Path(settings.storage_dir) / "uploads" / user.id
    pdf_path = None
    try:
        updir.mkdir(parents=True, exist_ok=True)
        p = updir / safe
        p.write_bytes(data)
        pdf_path = str(p)
    except Exception:
        pass

    # Deactivate previous résumé(s), insert the new active one.
    db.query(models.Resume).filter(
        models.Resume.user_id == user.id, models.Resume.is_active.is_(True)
    ).update({"is_active": False})
    row = models.Resume(
        user_id=user.id, filename=file.filename, raw_text=text[:20000],
        parsed_json=parsed, pdf_path=pdf_path, is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return MasterResumeOut(
        id=row.id, filename=row.filename, parsed_json=parsed,
        created_at=row.created_at, has_resume=True,
    )


# ── tailored versions (per user) ──────────────────────────────────────
@router.get("/versions", response_model=List[ResumeVersionOut])
def list_versions(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
    limit: int = 50,
):
    rows = (
        db.query(models.ResumeVersion)
        .filter(models.ResumeVersion.user_id == user.id)
        .order_by(models.ResumeVersion.created_at.desc())
        .limit(limit)
        .all()
    )
    return [ResumeVersionOut.model_validate(r) for r in rows]


@router.get("/for-job/{job_id}", response_model=TailorResponse)
def docs_for_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    rv = (
        db.query(models.ResumeVersion)
        .filter_by(user_id=user.id, job_id=job_id)
        .order_by(models.ResumeVersion.created_at.desc())
        .first()
    )
    cl = (
        db.query(models.CoverLetter)
        .filter_by(user_id=user.id, job_id=job_id)
        .order_by(models.CoverLetter.created_at.desc())
        .first()
    )
    return TailorResponse(
        resume=ResumeVersionOut.model_validate(rv) if rv else None,
        cover_letter=CoverLetterOut.model_validate(cl) if cl else None,
    )


@router.post("/tailor", response_model=TailorResponse)
def tailor(
    payload: TailorRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Tailor YOUR master résumé to a job + generate a cover letter (downloads)."""
    job = db.get(models.Job, payload.job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    resume_json = resume_engine.load_user_resume(db, user.id)
    if not resume_json:
        raise HTTPException(400, "Upload your résumé first (Settings → résumé).")
    rv = resume_engine.tailor_for_job(db, job, resume_json=resume_json, user_id=user.id)
    cl = cover_letter_svc.generate_for_job(db, job, rv.json_payload, user_id=user.id)
    rk = (
        db.query(models.Ranking)
        .filter_by(user_id=user.id, job_id=job.id)
        .first()
    )
    if rk:
        rk.status = "tailored"
    db.commit()
    db.refresh(rv)
    db.refresh(cl)
    return TailorResponse(
        resume=ResumeVersionOut.model_validate(rv),
        cover_letter=CoverLetterOut.model_validate(cl),
    )

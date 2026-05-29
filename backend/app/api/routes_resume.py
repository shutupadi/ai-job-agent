"""Resume endpoints — list versions, fetch master, on-demand tailor."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.schemas import (
    CoverLetterOut,
    ResumeVersionOut,
    TailorRequest,
    TailorResponse,
)
from app.services import cover_letter as cover_letter_svc
from app.services import resume_engine

router = APIRouter()


def _latest_cover_letter(db: Session, job_id: str) -> models.CoverLetter | None:
    return (
        db.query(models.CoverLetter)
        .filter(models.CoverLetter.job_id == job_id)
        .order_by(models.CoverLetter.created_at.desc())
        .first()
    )


def _latest_resume(db: Session, job_id: str) -> models.ResumeVersion | None:
    return (
        db.query(models.ResumeVersion)
        .filter(models.ResumeVersion.job_id == job_id)
        .order_by(models.ResumeVersion.created_at.desc())
        .first()
    )


@router.get("/master")
def get_master():
    return resume_engine.load_master_resume()


@router.get("/versions", response_model=List[ResumeVersionOut])
def list_versions(db: Session = Depends(get_db), limit: int = 50):
    rows = (
        db.query(models.ResumeVersion)
        .order_by(models.ResumeVersion.created_at.desc())
        .limit(limit)
        .all()
    )
    return [ResumeVersionOut.model_validate(r) for r in rows]


@router.get("/for-job/{job_id}", response_model=TailorResponse)
def docs_for_job(job_id: str, db: Session = Depends(get_db)):
    """Latest tailored resume + cover letter for a job (for re-rendering links)."""
    rv = _latest_resume(db, job_id)
    cl = _latest_cover_letter(db, job_id)
    return TailorResponse(
        resume=ResumeVersionOut.model_validate(rv) if rv else None,
        cover_letter=CoverLetterOut.model_validate(cl) if cl else None,
    )


@router.post("/tailor", response_model=TailorResponse)
def tailor(payload: TailorRequest, db: Session = Depends(get_db)):
    """On-demand: tailor the master résumé to a job + generate a cover letter.

    This is the 'approve' action — invoked when the user picks a shortlisted job
    they want to apply to. Returns download URLs for both PDFs."""
    job = db.get(models.Job, payload.job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    rv = resume_engine.tailor_for_job(db, job)
    cl = cover_letter_svc.generate_for_job(db, job, rv.json_payload)
    job.status = "tailored"
    db.commit()
    db.refresh(rv)
    db.refresh(cl)
    return TailorResponse(
        resume=ResumeVersionOut.model_validate(rv),
        cover_letter=CoverLetterOut.model_validate(cl),
    )

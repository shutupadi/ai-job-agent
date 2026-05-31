#!/usr/bin/env python
"""
Read-only admin report: who has signed up + the résumés they uploaded.

This NEVER changes the database — it only reads and prints.

▶ Recommended (see the LIVE data on Render):
    Render dashboard → ai-job-agent-backend → "Shell" tab, then run:
        python scripts/show_users.py

▶ Locally (uses the DATABASE_URL from your .env — i.e. your local data):
        backend/.venv/Scripts/python.exe backend/scripts/show_users.py
"""

from __future__ import annotations

import os
import sys

# Make `import app...` work no matter how this script is launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import Application, Ranking, Resume, User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def _fmt(d) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if d else "-"


def _login_method(u: User) -> str:
    if u.google_sub and u.password_hash:
        return "Google + Password"
    if u.google_sub:
        return "Google"
    if u.password_hash:
        return "Email / Password"
    return "-"


def main() -> None:
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at).all()
        print()
        print("=" * 74)
        print(f"  REGISTERED USERS: {len(users)}")
        print("=" * 74)

        for i, u in enumerate(users, 1):
            resumes = (
                db.query(Resume)
                .filter(Resume.user_id == u.id)
                .order_by(Resume.created_at.desc())
                .all()
            )
            n_rank = db.query(Ranking).filter(Ranking.user_id == u.id).count()
            n_short = (
                db.query(Ranking)
                .filter(Ranking.user_id == u.id, Ranking.rank_score >= 70)
                .count()
            )
            n_app = db.query(Application).filter(Application.user_id == u.id).count()

            flags = []
            if u.is_admin:
                flags.append("ADMIN")
            if not u.is_active:
                flags.append("DISABLED")

            print()
            print(f"[{i}] {u.name or '(no name)'}  <{u.email}>")
            print(f"    signed up : {_fmt(u.created_at)}   via {_login_method(u)}")
            print(
                f"    mode      : {u.experience_pref}"
                + (f"   [{', '.join(flags)}]" if flags else "")
            )
            print(
                f"    activity  : {n_rank} ranked / {n_short} shortlisted (>=70)"
                f" / {n_app} applied"
            )
            print(f"    resumes   : {len(resumes)}")
            for r in resumes:
                pj = r.parsed_json or {}
                yrs = pj.get("experience_years")
                pname = pj.get("name") or pj.get("full_name")
                skills = pj.get("skills")
                nskills = len(skills) if isinstance(skills, list) else "?"
                on_disk = bool(r.pdf_path and os.path.exists(r.pdf_path))
                active = " (active)" if r.is_active else ""
                print(f"        - {r.filename or '(unnamed)'}{active}"
                      f"  | uploaded {_fmt(r.created_at)}")
                print(
                    f"          parsed: name={pname or '-'},"
                    f" experience_years={yrs if yrs is not None else '-'},"
                    f" skills={nskills}, text={len(r.raw_text or '')} chars"
                )
                print(
                    f"          pdf: {r.pdf_path or '-'}"
                    f"  ({'on disk' if on_disk else 'NOT on disk - ephemeral, wiped on redeploy'})"
                )

        total_resumes = db.query(Resume).count()
        print()
        print("-" * 74)
        print(
            f"  TOTAL: {len(users)} users, {total_resumes} resumes"
            f"  (extracted text + parsed JSON always kept in the DB)"
        )
        print("-" * 74)
        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()

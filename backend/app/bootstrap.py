"""
First-boot bootstrap.

- Ensures storage dirs exist.
- Copies the example master resume to data/master_resume.json if missing.
- (Idempotent — safe to run on every container start.)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.config import settings
from app.utils.logger import log

EXAMPLE_RESUME = {
    "name": settings.candidate_full_name,
    "email": settings.candidate_email,
    "phone": settings.candidate_phone,
    "links": {
        "linkedin": settings.candidate_linkedin,
        "github": settings.candidate_github,
        "portfolio": settings.candidate_portfolio,
    },
    "summary": (
        "Final-year engineering student with hands-on experience in "
        "Python, Java, distributed systems and machine-learning pipelines. "
        "Strong DSA fundamentals and a track record of shipping end-to-end "
        "projects."
    ),
    "skills": {
        "languages": ["Python", "Java", "C++", "SQL", "TypeScript"],
        "frameworks": ["FastAPI", "Spring Boot", "React", "Next.js", "PyTorch"],
        "infra": ["Docker", "Kubernetes", "AWS", "PostgreSQL", "Redis", "Kafka"],
        "concepts": [
            "Data Structures & Algorithms",
            "System Design",
            "Microservices",
            "ML/MLOps",
            "Statistics",
        ],
    },
    "experience": [
        {
            "company": "Example Tech",
            "title": "Software Engineering Intern",
            "location": "Bangalore, India",
            "start": "May 2025",
            "end": "Jul 2025",
            "bullets": [
                "Built a low-latency order-matching micro-service in Python+FastAPI handling 5k RPS.",
                "Reduced data-pipeline cost 38% by migrating batch ETL to incremental CDC on Kafka.",
                "Owned CI/CD with GitHub Actions and Argo CD across 4 micro-services.",
            ],
        }
    ],
    "projects": [
        {
            "name": "Distributed Key-Value Store",
            "stack": ["Go", "Raft", "gRPC"],
            "bullets": [
                "Implemented a Raft-backed KV store with snapshotting and log compaction.",
                "Benchmarked >12k writes/sec on a 3-node cluster with linearizable reads.",
            ],
        },
        {
            "name": "ML Resume Screener",
            "stack": ["Python", "scikit-learn", "spaCy"],
            "bullets": [
                "Fine-tuned a classifier on 8k resumes hitting 0.91 F1 vs human baseline 0.84.",
                "Shipped as a Streamlit app used by the campus placement cell.",
            ],
        },
    ],
    "education": [
        {
            "school": "Your College",
            "degree": "B.Tech, Computer Science",
            "start": "2022",
            "end": "2026",
            "details": "CGPA 8.7/10. Coursework: OS, DBMS, Distributed Systems, ML.",
        }
    ],
    "achievements": [
        "Top 0.5% in ICPC Regional 2024.",
        "Smart India Hackathon Winner 2024.",
        "Maintainer of an OSS project with 1.4k GitHub stars.",
    ],
}


def main() -> None:
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    example_path = data_dir / "master_resume.example.json"
    real_path = data_dir / "master_resume.json"

    if not example_path.exists():
        example_path.write_text(json.dumps(EXAMPLE_RESUME, indent=2), encoding="utf-8")
        log.info(f"Wrote example master resume to {example_path}")

    if not real_path.exists():
        shutil.copy(example_path, real_path)
        log.info(f"Seeded {real_path} from example. Edit it with your real details.")


if __name__ == "__main__":
    main()

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps required for Playwright + reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl wget gnupg ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 fonts-liberation libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && \
    python -m playwright install chromium

COPY . .

EXPOSE 8000
# Run DB migrations (and best-effort seed) on startup, THEN serve. This makes the
# image self-contained on hosts like Render that use the Dockerfile CMD directly.
# (docker-compose overrides this with its own command, so local is unaffected.)
CMD ["bash", "-lc", "alembic upgrade head && (python -m app.bootstrap || true) && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

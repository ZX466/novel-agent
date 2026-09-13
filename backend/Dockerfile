# Backend image — built on the Tencent Cloud server via docker compose.
# Local dev does NOT use this Dockerfile; run uvicorn directly.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for asyncpg / pgvector. Mirrors keep the rebuild sane on CN
# networks: deb.debian.org direct downloads crawled at ~2KB/s during the
# 2026-09-13 cache-wipe rebuild (1700s+ just for apt). R10-⑨: addUSTC apt
# mirror + Aliyun PyPI mirror (both inline, no extra files).
RUN sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ \
    && pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

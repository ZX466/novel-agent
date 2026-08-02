"""Smoke test for /health endpoint.

Uses the shared `app_client` fixture from conftest.py. Does NOT hit the
LLM pipeline or database.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(app_client: TestClient) -> None:
    response = app_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

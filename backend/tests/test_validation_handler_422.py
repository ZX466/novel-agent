"""Regression tests for the 422 validation handler (deployed 09-13).

The custom handler returned exc.errors() verbatim; those entries carry the
original exception object in ctx["error"] (a ValueError), which json.dumps
cannot serialize → the 422 handler itself raised TypeError and the client
got a 500. Two failure modes must be JSON-safe:

1. value_error raised by a model_validator (ctx.error = ValueError)
2. assertion_error raised by a Field constraint (ctx.error = AssertionError)
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from pydantic import Field


def _client() -> TestClient:
    from app.main import validation_exception_handler

    from fastapi.exceptions import RequestValidationError

    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    class Body(BaseModel):
        chapter_id: int | None = None

        @field_validator("chapter_id")
        @classmethod
        def _need_content(cls, v):
            raise ValueError("需要 chapter_id 或非空 content_text")

    @app.post("/boom")
    async def boom(body: Body) -> dict:
        return body.model_dump()

    return TestClient(app, raise_server_exceptions=False)


def test_value_error_ctx_is_json_serializable() -> None:
    """A validator ValueError → clean 422, not a handler crash (500)."""
    res = _client().post("/boom", json={"chapter_id": None})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, list)
    assert any("chapter_id 或非空 content_text" in str(e.get("msg", "")) for e in detail)


def test_assertion_error_ctx_is_json_serializable() -> None:
    """Field-constraint AssertionError must survive the same path."""
    from app.main import validation_exception_handler

    from fastapi.exceptions import RequestValidationError

    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    class Body(BaseModel):
        title: str = Field(default="", min_length=3)  # type: ignore[arg-type]

    @app.post("/short")
    async def short(body: Body) -> dict:
        return body.model_dump()

    res = TestClient(app, raise_server_exceptions=False).post("/short", json={"title": ""})
    assert res.status_code == 422
    json.dumps(res.json())  # must not raise

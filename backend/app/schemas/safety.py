"""Pydantic schemas for 交稿雷达 (R6-3) safety preflight."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SafetyFinding(BaseModel):
    """One matched rule — advisory, non-blocking."""

    rule_name: str
    category: str
    severity: str
    description: str = ""
    count: int = Field(default=0, ge=0)
    sample: str = ""


class SafetyScanSummary(BaseModel):
    """Aggregate over all findings."""

    matched_count: int = Field(default=0, ge=0)
    max_severity: str = "INFO"
    should_block: bool = False
    by_category: dict[str, list[str]] = Field(default_factory=dict)


class SafetyScanReport(BaseModel):
    """Result of a non-blocking pre-export safety scan."""

    doc_id: int
    content_hash: str
    cached: bool = False
    truncated: bool = False
    rules_checked: int = Field(default=0, ge=0)
    scanned_at: datetime | None = None
    summary: SafetyScanSummary = Field(default_factory=SafetyScanSummary)
    findings: list[SafetyFinding] = Field(default_factory=list)
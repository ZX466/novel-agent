"""Evaluation ORM model.

Persists quality scores produced at each evaluation point in the
novel-writing pipeline, so quality can be tracked over time (trend
analysis) rather than being discarded after each run.

Evaluation sources (the `stage` field):
  - draft / refine / final_polish — EditorAgent three-stage evaluator
  - consistency_check             — PlotterAgent consistency score
  - reflection                    — EditorAgent self-reflection score
  - safety                        — ContentSafetyAgent verdict score
  - pipeline_evaluate             — LangGraph evaluate_node score

`chapter_id` is nullable because some evaluations (e.g. cross-chapter
consistency, world setting) are not tied to a single chapter.

`feedback` stores the evaluator's free-form notes; structured issues
(JSON-serializable) can be embedded here as a JSON string.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Evaluation(Base):
    """A single quality-evaluation record for traceability and trends."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True
    )
    chapter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chapters.id"), nullable=True, index=True
    )
    # Which pipeline stage produced this evaluation.
    stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Evaluator score in [0.0, 1.0]. Clamped at the call site.
    score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Source task_id (DAG) or "pipeline" so a record can be traced back to
    # the run that produced it.
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Evaluation id={self.id} stage={self.stage} "
            f"score={self.score} chapter_id={self.chapter_id}>"
        )

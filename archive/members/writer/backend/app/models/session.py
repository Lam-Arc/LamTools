from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String, Text, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import gen_uuid, now
from ..database import Base


class WriterSession(Base):
    __tablename__ = "writer_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    title: Mapped[str] = mapped_column(String(255), default="New Session")
    work_root: Mapped[str] = mapped_column(String(1024), default="")
    branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phase: Mapped[str] = mapped_column(String(50), default="idle")
    mode: Mapped[str] = mapped_column(String(50), default="EXECUTE")
    status: Mapped[str] = mapped_column(String(50), default="active")
    # Project relationship
    project_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("writer_projects.id"), nullable=True
    )
    # Runtime state fields (merged from WriterSessionState)
    loop_position: Mapped[str] = mapped_column(String(50), default="execute")
    task_complexity: Mapped[str] = mapped_column(String(50), default="simple")
    planning_depth: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    transcript_revision: Mapped[int] = mapped_column(Integer, default=0)
    # JSON columns for structured data
    todos: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    open_loops: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    context_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    runtime_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # runtime_state stores: git_state, git_history, locked_context,
    # delegation_queue, pending_decision_points, decision_history,
    # session_memory, turns_without_output, total_reads/writes, etc.
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

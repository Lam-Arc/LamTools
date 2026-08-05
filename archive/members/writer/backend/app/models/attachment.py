from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import gen_uuid, now
from ..database import Base


class WriterAttachment(Base):
    __tablename__ = "writer_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("writer_projects.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("writer_sessions.id"), nullable=False)
    message_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("writer_messages.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="user_upload")
    agent_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    preview_type: Mapped[str] = mapped_column(String(50), nullable=False, default="external")
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

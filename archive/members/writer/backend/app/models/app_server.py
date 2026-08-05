from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import gen_uuid, now


class WriterAppEvent(Base):
    __tablename__ = "writer_app_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_writer_app_events_thread_seq"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=gen_uuid)
    thread_id: Mapped[str] = mapped_column(String(36), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    item_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    parent_item_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    client_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class WriterThreadSnapshot(Base):
    __tablename__ = "writer_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class WriterArtifact(Base):
    __tablename__ = "writer_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=gen_uuid)
    thread_id: Mapped[str] = mapped_column(String(36), nullable=False)
    turn_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    item_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    path: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

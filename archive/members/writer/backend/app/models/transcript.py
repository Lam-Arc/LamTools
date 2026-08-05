from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import gen_uuid, now
from ..database import Base


class WriterTranscriptTurn(Base):
    __tablename__ = "writer_transcript_turns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("writer_sessions.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    user_text: Mapped[str] = mapped_column(Text, default="")
    user_message_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("writer_messages.id"), nullable=True)
    status_cache: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    final_reply_block_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_state_changed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    terminal_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    terminal_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)


class WriterTranscriptModelCall(Base):
    __tablename__ = "writer_transcript_model_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(36), ForeignKey("writer_transcript_turns.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)


class WriterTranscriptBlock(Base):
    __tablename__ = "writer_transcript_blocks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(36), ForeignKey("writer_transcript_turns.id"), nullable=False)
    model_call_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("writer_transcript_model_calls.id"), nullable=True)
    parent_block_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    producer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running")
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_kind: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    response_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tool_args_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tool_result_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)


class WriterActiveProducer(Base):
    __tablename__ = "writer_active_producers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(36), ForeignKey("writer_transcript_turns.id"), nullable=False)
    model_call_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    parent_block_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(50), default="runtime")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    recoverable: Mapped[bool] = mapped_column(default=False)


class WriterTranscriptArtifact(Base):
    __tablename__ = "writer_transcript_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    turn_id: Mapped[str] = mapped_column(String(36), ForeignKey("writer_transcript_turns.id"), nullable=False)
    block_id: Mapped[str] = mapped_column(String(128), ForeignKey("writer_transcript_blocks.id"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), default="")
    file_path: Mapped[str] = mapped_column(String(2048), default="")
    file_type: Mapped[str] = mapped_column(String(50), default="file")
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import now
from ..database import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    namespace: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


__all__ = ["AppSetting"]

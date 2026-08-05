from __future__ import annotations

import uuid
from datetime import datetime, timezone


def gen_uuid() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)

"""Multi-bot manager for the QQ plugin.

The host owns one plugin backend; this manager owns N independent QQ bot
instances.  Each instance keeps its own data directory (config, gateway resume
state, target peers, logs, media) and its own secret key, so creating a bot in
another Sunday session produces a different AppID instead of re-pointing the
same bot.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import load_config, save_config
from .runtime import QQBotRuntime


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class QQBotManager:
    def __init__(
        self,
        context: Any,
        *,
        runtime_factory: Callable[..., QQBotRuntime] = QQBotRuntime,
    ) -> None:
        self.context = context
        self.runtime_factory = runtime_factory
        self.base_dir = Path(getattr(context, "data_dir", None) or Path(__file__).resolve().parent.parent / "data") / "plugin-data" / "qq-bot"
        self.bots_root = self.base_dir / "bots"
        self.metadata_path = self.base_dir / "bots.jsonc"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.bots_root.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.logger = self._make_logger()
        self.running = False
        self.bots: dict[str, QQBotRuntime] = {}
        self.metadata: dict[str, dict[str, Any]] = {}
        self.errors: dict[str, str] = {}

    def _make_logger(self) -> logging.Logger:
        logger = logging.getLogger("qqbot.manager")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.FileHandler(self.base_dir / "logs" / "manager.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter("[qq-bot:manager] %(levelname)s %(message)s"))
            logger.addHandler(console)
        logger.propagate = False
        return logger

    # ── Metadata / paths ───────────────────────────────────────────────────
    def _load_metadata(self) -> None:
        try:
            raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        bots = raw.get("bots") if isinstance(raw, dict) else None
        if not isinstance(bots, dict):
            bots = {}
        self.metadata = {
            str(bot_id): dict(record)
            for bot_id, record in bots.items()
            if isinstance(record, dict)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(bot_id))
        }

    def _save_metadata(self) -> None:
        payload = {"bots": self.metadata}
        temp = self.metadata_path.with_suffix(".jsonc.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.metadata_path)

    def _bot_dir(self, bot_id: str) -> Path:
        return self.bots_root / bot_id

    def _new_bot_id(self) -> str:
        return f"bot_{uuid.uuid4().hex[:10]}"

    def _record(self, bot_id: str) -> dict[str, Any]:
        return self.metadata.setdefault(
            bot_id,
            {"name": f"QQ 机器人 {bot_id[-6:]}", "createdAt": _now()},
        )

    # ── Migration / bootstrap ─────────────────────────────────────────────
    def _legacy_config(self) -> Path:
        return Path(getattr(self.context, "data_dir", None) or self.base_dir.parent.parent) / "config.jsonc"

    def _migrate_legacy(self) -> None:
        legacy = self._legacy_config()
        if not legacy.is_file() or self.metadata:
            return
        bot_id = "default"
        bot_dir = self._bot_dir(bot_id)
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / "logs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, bot_dir / "config.jsonc")
        for name in ("gateway-session.json", "target-peers.json", "prefs.json"):
            source = legacy.parent / name
            if source.is_file():
                shutil.copy2(source, bot_dir / name)
        old_log = legacy.parent / "logs" / "qqbot.log"
        if old_log.is_file():
            shutil.copy2(old_log, bot_dir / "logs" / "qqbot.log")
        self._record(bot_id)
        self.metadata[bot_id]["name"] = "QQ 机器人（迁移）"
        self._save_metadata()
        self.logger.info("migrated legacy QQ config into bot %s", bot_id)

    def _ensure_default_bot(self) -> None:
        if self.metadata:
            return
        bot_id = "default"
        bot_dir = self._bot_dir(bot_id)
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / "logs").mkdir(parents=True, exist_ok=True)
        self._record(bot_id)
        self._save_metadata()

    # ── Lifecycle ──────────────────────────────────────────────────────────
    async def start(self, context: Any | None = None) -> None:
        if context is not None:
            self.context = context
        self._load_metadata()
        self._migrate_legacy()
        self._ensure_default_bot()
        self.running = True
        bot_ids = list(self.metadata)
        await asyncio.gather(
            *(self._start_one(bot_id) for bot_id in bot_ids),
            return_exceptions=True,
        )
        self.logger.info("QQ bot manager started with %d bot(s)", len(self.bots))

    async def _start_one(self, bot_id: str) -> None:
        if bot_id in self.bots:
            return
        bot_dir = self._bot_dir(bot_id)
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / "logs").mkdir(parents=True, exist_ok=True)
        config_path = bot_dir / "config.jsonc"
        if not config_path.is_file():
            save_config(bot_dir, {})
        runtime = self.runtime_factory(
            self.context,
            bot_id=bot_id,
            data_dir=bot_dir,
        )
        try:
            await runtime.start()
        except Exception as exc:  # noqa: BLE001 - one bot must not kill the manager
            self.errors[bot_id] = f"{type(exc).__name__}: {exc}"
            self.logger.exception("QQ bot %s failed to start", bot_id)
            try:
                await runtime.stop()
            except Exception:
                pass
            return
        self.bots[bot_id] = runtime
        self.errors.pop(bot_id, None)

    async def stop(self) -> None:
        self.running = False
        runtimes = list(self.bots.values())
        self.bots.clear()
        await asyncio.gather(
            *(runtime.stop() for runtime in runtimes),
            return_exceptions=True,
        )
        self.logger.info("QQ bot manager stopped")

    @property
    def lifecycle_tasks(self) -> list[asyncio.Task]:
        # Per-bot gateway tasks are intentionally not exposed: one bot dying
        # must not mark the whole plugin unavailable.  health_check/status
        # surfaces per-bot state instead.
        return []

    def health_check(self) -> dict[str, Any]:
        bots = [self.describe_bot(bot_id) for bot_id in self.metadata]
        ready = bool(self.running)
        return {
            "ready": ready,
            "bots": bots,
            "errors": dict(self.errors),
        }

    # ── Bot lookup / CRUD ──────────────────────────────────────────────────
    def get_bot(self, bot_id: str) -> QQBotRuntime | None:
        return self.bots.get(str(bot_id or ""))

    def default_bot(self) -> QQBotRuntime | None:
        if "default" in self.bots:
            return self.bots["default"]
        return next(iter(self.bots.values()), None)

    def bot_for_session(self, session_id: str) -> tuple[str, QQBotRuntime] | None:
        session_id = str(session_id or "").strip()
        if not session_id:
            return None
        for bot_id, runtime in self.bots.items():
            if str(runtime.config.get("targetSessionId") or "").strip() == session_id:
                return bot_id, runtime
        return None

    def find_session_bot_id(self, session_id: str) -> str:
        session_id = str(session_id or "").strip()
        if not session_id:
            return ""
        running = self.bot_for_session(session_id)
        if running is not None:
            return running[0]
        for bot_id in self.metadata:
            if bot_id in self.bots:
                continue
            try:
                config = load_config(self._bot_dir(bot_id))
            except Exception:
                continue
            if str(config.get("targetSessionId") or "").strip() == session_id:
                return bot_id
        return ""

    def describe_bot(self, bot_id: str) -> dict[str, Any]:
        bot_id = str(bot_id or "")
        runtime = self.bots.get(bot_id)
        record = self.metadata.get(bot_id) or {}
        if runtime is None:
            try:
                stored = load_config(self._bot_dir(bot_id))
            except Exception:
                stored = {}
            return {
                "botId": bot_id,
                "name": str(record.get("name") or bot_id),
                "appId": str(stored.get("appId") or ""),
                "targetProjectId": str(stored.get("targetProjectId") or ""),
                "targetSessionId": str(stored.get("targetSessionId") or ""),
                "phase": "failed" if bot_id in self.errors else "starting",
                "bind": {"phase": "failed", "reason": self.errors.get(bot_id, "未启动")}
                if bot_id in self.errors
                else {"phase": "starting"},
                "gateway": "",
                "error": self.errors.get(bot_id, ""),
            }
        config = runtime.config or {}
        health = runtime.health_check() if hasattr(runtime, "health_check") else {}
        return {
            "botId": bot_id,
            "name": str(record.get("name") or bot_id),
            "appId": str(runtime._app_id() or ""),
            "targetProjectId": str(config.get("targetProjectId") or ""),
            "targetSessionId": str(config.get("targetSessionId") or ""),
            "phase": str((runtime.bind_state() or {}).get("phase") or "starting"),
            "bind": runtime.bind_state(),
            "gateway": str(health.get("gateway") or ""),
            "error": str(self.errors.get(bot_id) or ""),
        }

    def list_bots(self, session_id: str = "") -> dict[str, Any]:
        session_id = str(session_id or "").strip()
        bots = [self.describe_bot(bot_id) for bot_id in self.metadata]
        if session_id:
            bots = [bot for bot in bots if bot.get("targetSessionId") == session_id]
        return {"ok": True, "bots": bots}

    async def create_bot(
        self,
        *,
        session_id: str,
        project_id: str = "",
        name: str = "",
    ) -> dict[str, Any]:
        session_id = str(session_id or "").strip()
        if not session_id:
            return {"ok": False, "error": "sessionId 不能为空"}
        existing_id = self.find_session_bot_id(session_id)
        if existing_id:
            return {
                "ok": True,
                "existing": True,
                "botId": existing_id,
                "bot": self.describe_bot(existing_id),
            }

        bot_id = self._new_bot_id()
        bot_dir = self._bot_dir(bot_id)
        bot_dir.mkdir(parents=True, exist_ok=True)
        (bot_dir / "logs").mkdir(parents=True, exist_ok=True)

        reference = self.default_bot()
        base_config = dict(reference.config) if reference is not None else load_config(bot_dir)
        for key in ("appId", "appSecret", "targetProjectId", "targetSessionId"):
            base_config.pop(key, None)
        base_config["targetProjectId"] = str(project_id or "")
        base_config["targetSessionId"] = session_id
        save_config(bot_dir, base_config)

        self.metadata[bot_id] = {
            "name": str(name or f"QQ-{session_id[:8]}"),
            "createdAt": _now(),
        }
        self._save_metadata()
        await self._start_one(bot_id)
        return {
            "ok": bot_id in self.bots,
            "botId": bot_id,
            "existing": False,
            "bot": self.describe_bot(bot_id),
            **({"error": self.errors[bot_id]} if bot_id in self.errors else {}),
        }

    async def delete_bot(self, bot_id: str) -> dict[str, Any]:
        bot_id = str(bot_id or "")
        runtime = self.bots.pop(bot_id, None)
        if runtime is not None:
            try:
                await runtime.stop()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("QQ bot %s stop failed: %s", bot_id, exc)
        self.metadata.pop(bot_id, None)
        self.errors.pop(bot_id, None)
        self._save_metadata()
        view = getattr(self.context, "service", lambda _name: None)("secrets")
        if view is not None:
            try:
                view.delete("appSecret" if bot_id in {"", "default"} else f"appSecret:{bot_id}")
            except Exception:
                pass
        return {"ok": True, "botId": bot_id, "dataKept": str(self._bot_dir(bot_id))}

    # ── Delegates used by operations ───────────────────────────────────────
    async def targets(self) -> dict[str, Any]:
        runtime = self.default_bot()
        if runtime is None:
            return {"ok": False, "error": "没有运行中的机器人"}
        return await runtime.targets()

    def models_list(self) -> dict[str, Any]:
        runtime = self.default_bot()
        if runtime is None:
            return {"ok": False, "error": "没有运行中的机器人"}
        return runtime.models_list()

    def logs_tail(self, tail: int = 80, bot_id: str = "") -> dict[str, Any]:
        runtime = self.get_bot(bot_id) or self.default_bot()
        if runtime is None:
            return {"ok": False, "error": "没有运行中的机器人"}
        return runtime.logs_tail(tail)

    def diagnose(self, bot_id: str = "") -> dict[str, Any]:
        runtime = self.get_bot(bot_id) or self.default_bot()
        if runtime is None:
            return {"ok": False, "error": "没有运行中的机器人"}
        return runtime.diagnose()


__all__ = ["QQBotManager"]

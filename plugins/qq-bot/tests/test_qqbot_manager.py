from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qqbot.config import load_config
from qqbot.manager import QQBotManager
from qqbot.state import set_manager


class FakeRuntime:
    def __init__(self, context, *, bot_id: str, data_dir: Path) -> None:
        self.context = context
        self.bot_id = bot_id
        self.data_dir = Path(data_dir)
        self.config = load_config(self.data_dir)
        self.running = False
        self.stopped = False

    async def start(self) -> None:
        self.running = True

    async def stop(self) -> None:
        self.running = False
        self.stopped = True

    def _app_id(self) -> str:
        return str(self.config.get("appId") or "")

    def bind_state(self) -> dict:
        return {"phase": "bound" if self._app_id() else "waiting"}

    def health_check(self) -> dict:
        return {"ready": True, "gateway": "connected" if self.running else "stopped"}

    def status(self) -> dict:
        return {"ok": True, "botId": self.bot_id, "appId": self._app_id()}

    async def targets(self) -> dict:
        return {"ok": True, "projects": []}

    def models_list(self) -> dict:
        return {"ok": True, "models": []}


def _context(tmp_path: Path):
    return SimpleNamespace(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        service=lambda _name: None,
    )


@pytest.mark.asyncio
async def test_manager_creates_independent_bots_per_session(tmp_path: Path) -> None:
    manager = QQBotManager(_context(tmp_path), runtime_factory=FakeRuntime)
    await manager.start()
    assert "default" in manager.bots

    first = await manager.create_bot(session_id="session-a", project_id="project-1")
    second = await manager.create_bot(session_id="session-b", project_id="project-2")

    assert first["ok"] is True and second["ok"] is True
    assert first["botId"] != second["botId"]
    assert first["bot"]["targetSessionId"] == "session-a"
    assert second["bot"]["targetSessionId"] == "session-b"
    assert manager.get_bot(first["botId"]).data_dir != manager.get_bot(second["botId"]).data_dir

    duplicate = await manager.create_bot(session_id="session-a")
    assert duplicate["existing"] is True
    assert duplicate["botId"] == first["botId"]

    listed = manager.list_bots("session-b")
    assert [bot["botId"] for bot in listed["bots"]] == [second["botId"]]

    await manager.delete_bot(second["botId"])
    assert manager.get_bot(second["botId"]) is None
    assert all(bot["botId"] != second["botId"] for bot in manager.list_bots()["bots"])
    await manager.stop()


@pytest.mark.asyncio
async def test_manager_migrates_legacy_single_bot(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "logs").mkdir(parents=True)
    (data / "config.jsonc").write_text(
        json.dumps(
            {
                "appId": "legacy-app",
                "targetSessionId": "legacy-session",
                "targetProjectId": "legacy-project",
            }
        ),
        encoding="utf-8",
    )
    (data / "logs" / "qqbot.log").write_text("old log\n", encoding="utf-8")
    (data / "gateway-session.json").write_text('{"sessionId":"old"}', encoding="utf-8")

    manager = QQBotManager(_context(tmp_path), runtime_factory=FakeRuntime)
    await manager.start()

    bot = manager.get_bot("default")
    assert bot is not None
    assert bot.config["appId"] == "legacy-app"
    assert bot.config["targetSessionId"] == "legacy-session"
    assert bot.config["targetProjectId"] == "legacy-project"
    assert (bot.data_dir / "gateway-session.json").is_file()
    assert (bot.data_dir / "logs" / "qqbot.log").read_text(encoding="utf-8") == "old log\n"
    await manager.stop()


@pytest.mark.asyncio
async def test_operation_bot_id_routes_to_the_selected_runtime(tmp_path: Path, monkeypatch) -> None:
    import ops

    manager = QQBotManager(_context(tmp_path), runtime_factory=FakeRuntime)
    await manager.start()
    created = await manager.create_bot(session_id="session-ops")
    bot_id = created["botId"]
    set_manager(manager)
    try:
        result = await ops.status(
            SimpleNamespace(payload={"botId": bot_id}),
        )
    finally:
        set_manager(None)
        await manager.stop()

    assert result.status == "ok"
    assert result.payload["botId"] == bot_id

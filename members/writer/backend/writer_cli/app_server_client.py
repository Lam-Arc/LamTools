from __future__ import annotations

from typing import Any

from lamtools_core.app.live_client import CoreAppServerClient


class AppServerClient(CoreAppServerClient):
    def __init__(self, base_url: str = "http://localhost:6173") -> None:
        super().__init__(
            base_url,
            path="/api/app-server",
            client_info={"name": "lamwriter_cli", "version": "0.1.0"},
        )

    async def start_turn(
        self,
        *,
        thread_id: str,
        message: str,
        work_root: str = "",
        mode: str = "",
        model_id: str | None = None,
        shallow_thinking_enabled: bool | None = None,
        client_message_id: str | None = None,
    ) -> dict[str, Any]:
        return await super().start_turn(
            thread_id=thread_id,
            input_items=[{"type": "text", "text": message}],
            work_root=work_root,
            mode=mode,
            model_id=model_id,
            shallow_thinking_enabled=shallow_thinking_enabled,
            client_message_id=client_message_id,
        )

    async def steer_turn(self, *, thread_id: str, turn_id: str, message: str) -> dict[str, Any]:
        return await super().steer_turn(
            thread_id=thread_id,
            turn_id=turn_id,
            input_items=[{"type": "text", "text": message}],
        )

    async def list_sessions(self, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        response = await self.request("session.list", {"limit": limit, "offset": offset})
        sessions = response.get("sessions")
        return sessions if isinstance(sessions, list) else []

    async def create_session(
        self,
        *,
        title: str,
        work_root: str = "",
        mode: str = "EXECUTE",
    ) -> dict[str, Any]:
        response = await self.request(
            "session.create",
            {"title": title, "work_root": work_root, "mode": mode},
        )
        session = response.get("session")
        return session if isinstance(session, dict) else {}

    async def create_project(self, *, work_root: str) -> dict[str, Any]:
        response = await self.request("project.create", {"work_root": work_root})
        project = response.get("project")
        return project if isinstance(project, dict) else {}

    async def list_projects(self) -> list[dict[str, Any]]:
        response = await self.request("project.list", {})
        projects = response.get("projects")
        return projects if isinstance(projects, list) else []

    async def pick_project_directory(self) -> str:
        response = await self.request("project.directory.pick", {})
        return str(response.get("path") or "")

    async def get_session(self, *, session_id: str) -> dict[str, Any]:
        response = await self.request("session.get", {"session_id": session_id})
        session = response.get("session")
        return session if isinstance(session, dict) else {}

    async def update_session(self, *, session_id: str, title: str) -> dict[str, Any]:
        response = await self.request("session.update", {"session_id": session_id, "title": title})
        session = response.get("session")
        return session if isinstance(session, dict) else {}

    async def delete_session(self, *, session_id: str) -> None:
        await self.request("session.delete", {"session_id": session_id})


__all__ = ["AppServerClient"]

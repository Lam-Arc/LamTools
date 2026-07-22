from __future__ import annotations

from lamtools_core.member import MemberManifest

manifest = MemberManifest(
    id="writer",
    name="LamWriter",
    display_name="Writer",
    version="0.1.0",
    capabilities=[
        "write",
        "edit",
        "git",
        "commit-review",
        "goal",
        "arrange",
    ],
    default_routes={
        "/api/core": "Core sessions, projects, goals, arrangements, attachments, and turns",
        "/api/core/app-server": "Core live app-server shared by GUI and CLI",
    },
)
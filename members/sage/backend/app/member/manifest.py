from __future__ import annotations

from lamtools_core.member import MemberManifest

manifest = MemberManifest(
    id="sage",
    name="LamSage",
    display_name="Sage",
    version="0.1.0",
    capabilities=[
        "explore",
        "discover",
        "verify",
        "trace",
        "map",
        "recommend",
        "signal",
        "bridge",
        "synthesize",
        "maintenance",
        "goal",
        "arrange",
        "document-normalize",
    ],
    default_routes={
        "/api/core": "Core sessions, projects, goals, arrangements, attachments, and turns",
        "/api/core/app-server": "Core live app-server shared by GUI and CLI",
    },
)

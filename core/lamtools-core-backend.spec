# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LamCore backend sidecar.

Build:
    pyinstaller lamtools-core-backend.spec

The built exe is a thin FastAPI server started by the Tauri shell.
It does NOT manage windows, ports, or idle detection.

Requires the frontend to be built first (optional — for SPA fallback):
    cd core/desktop && npm run build
"""

from pathlib import Path

_PROJECT_ROOT = Path(".").resolve()

# ---------------------------------------------------------------------------
# Bundled data files
# ---------------------------------------------------------------------------
_datas: list[tuple[str, str]] = [
    # Frontend SPA (built by Vite) — optional, for SPA fallback
    ("desktop/dist", "frontend"),
    # Bundled default resources — seeded into the user config directory on
    # first run (config/defaults.py) and read as fallbacks at runtime.
    ("config/resources", "config/resources"),
    ("config/command", "config/command"),
    ("config/llm_adapters", "config/llm_adapters"),
]

# ---------------------------------------------------------------------------
# Hidden imports — every submodule reachable in lamtools_core
# (122 Core modules + 3rd-party runtime deps)
# ---------------------------------------------------------------------------
_hiddenimports = [
    # === 3rd-party runtime dependencies ===
    "httpx",
    "httpcore",
    "sqlalchemy",
    "aiosqlite",
    "aiosqlite.core",
    "sqlite3",
    "docx",
    "pypdf",
    # HTTP server stack
    "fastapi",
    "starlette",
    "starlette.routing",
    "uvicorn",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.logging",
    # Form/multipart parsing (FastAPI requires python-multipart at import time)
    "python_multipart",
    # Misc
    "multiprocessing",
    "asyncio",
    "websockets",

    # === lamtools_core top-level modules ===
    "lamtools_core",
    "lamtools_core.agent",
    "lamtools_core.checkpoint",
    "lamtools_core.cli",
    "lamtools_core.composer_commands",
    "lamtools_core.context_compaction",
    "lamtools_core.skills",
    "lamtools_core.sub_agent",
    "lamtools_core.sub_session",
    "lamtools_core.tokens",

    # === lamtools_core top-level packages ===
    "lamtools_core.app",
    "lamtools_core.attachment",
    "lamtools_core.config",
    "lamtools_core.event",
    "lamtools_core.http",
    "lamtools_core.kernel",
    "lamtools_core.llm",
    "lamtools_core.mcp",
    "lamtools_core.member",
    "lamtools_core.plugins",
    "lamtools_core.project",
    "lamtools_core.prompt",
    "lamtools_core.provider",
    "lamtools_core.runtime",
    "lamtools_core.run_event",
    "lamtools_core.session",
    "lamtools_core.snapshot",
    "lamtools_core.tool",
    "lamtools_core.usage",

    # === app/ submodules ===
    "lamtools_core.app.agent_app",
    "lamtools_core.app.approval_continuation",
    "lamtools_core.app.approval_resolution",
    "lamtools_core.app.base_agent",
    "lamtools_core.app.cli_live",
    "lamtools_core.app.command_execution",
    "lamtools_core.app.core_db",
    "lamtools_core.app.core_session_store",
    "lamtools_core.app.default_agent",
    "lamtools_core.app.durable_operations",
    "lamtools_core.app.event_store",
    "lamtools_core.app.factory",
    "lamtools_core.app.http_agent_app",
    "lamtools_core.app.http_agent_server",
    "lamtools_core.app.live_approval",
    "lamtools_core.app.live_client",
    "lamtools_core.app.live_hub",
    "lamtools_core.app.live_member",
    "lamtools_core.app.live_operations",
    "lamtools_core.app.live_protocol",
    "lamtools_core.app.live_router",
    "lamtools_core.app.operation_catalog",
    "lamtools_core.app.operation_groups",
    "lamtools_core.app.persistence_host",
    "lamtools_core.app.project_context",
    "lamtools_core.app.project_store",
    "lamtools_core.app.queue_state",
    "lamtools_core.app.snapshot_store",
    "lamtools_core.app.sqlite_write",
    "lamtools_core.app.turn_acceptance",

    # === attachment/ submodules ===
    "lamtools_core.attachment.files",
    "lamtools_core.attachment.http",
    "lamtools_core.attachment.service",
    "lamtools_core.attachment.store",

    # === config/ submodules ===
    "lamtools_core.config.operations",
    "lamtools_core.config.provider_store",
    "lamtools_core.config.settings_store",
    "lamtools_core.config.model_store",
    "lamtools_core.config.root",
    "lamtools_core.config.defaults",

    # === event/ submodules ===
    "lamtools_core.event.run_item",
    "lamtools_core.event.runtime_projection",

    # === http/ submodules ===
    "lamtools_core.http.routes",

    # === kernel/ submodules ===
    "lamtools_core.kernel.display",
    "lamtools_core.kernel.errors",
    "lamtools_core.kernel.kit",
    "lamtools_core.kernel.loop",
    "lamtools_core.kernel.policy",
    "lamtools_core.kernel.state",
    "lamtools_core.kernel.summary",
    "lamtools_core.kernel.tracing",
    "lamtools_core.kernel.hooks",

    # === llm/ submodules ===
    "lamtools_core.llm.adapter",
    "lamtools_core.llm.helpers",
    "lamtools_core.llm.policy",
    "lamtools_core.llm.profiles",
    "lamtools_core.llm.retry",
    "lamtools_core.llm.shallow_thinking",

    # === mcp/ submodules ===
    "lamtools_core.mcp.client",
    "lamtools_core.mcp.config",
    "lamtools_core.mcp.registry",
    "lamtools_core.mcp.schemas",

    # === member/ submodules ===
    "lamtools_core.member.kit",
    "lamtools_core.member.manifest",
    "lamtools_core.member.registry",

    # === plugins/ submodules ===
    "lamtools_core.plugins.engine",
    "lamtools_core.plugins.hook_config",
    "lamtools_core.plugins.models",
    "lamtools_core.plugins.operations",
    "lamtools_core.plugins.registry",
    "lamtools_core.plugins.trust",

    # === project/ submodules ===
    "lamtools_core.project.directory_picker",

    # === run_event/ submodules ===
    "lamtools_core.run_event.hub",

    # === runtime/ submodules ===
    "lamtools_core.runtime.arrange",
    "lamtools_core.runtime.audit",
    "lamtools_core.runtime.background_processes",
    "lamtools_core.runtime.evidence",
    "lamtools_core.runtime.goal",
    "lamtools_core.runtime.observer",
    "lamtools_core.runtime.plan",

    # === tool/ submodules ===
    "lamtools_core.tool.approval",
    "lamtools_core.tool.approval_continuation",
    "lamtools_core.tool.command",
    "lamtools_core.tool.command_runner",
    "lamtools_core.tool.command_tools",
    "lamtools_core.tool.default_toolbox",
    "lamtools_core.tool.document_normalize",
    "lamtools_core.tool.durable_tools",
    "lamtools_core.tool.git_tools",
    "lamtools_core.tool.loadtools",
    "lamtools_core.tool.mcp_tools",
    "lamtools_core.tool.permission",
    "lamtools_core.tool.spreadsheet",
    "lamtools_core.tool.sub_agent_runner",
    "lamtools_core.tool.web_tools",
    "lamtools_core.tool.workspace",
    "lamtools_core.tool.workspace_files",
    "lamtools_core.tool.verification",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ["desktop_backend.py"],
    pathex=["src"],
    binaries=[],
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LamCore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="desktop/app-icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LamCore",
)
# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for LamTools Core backend.
Produces: dist/lamtools-core-backend/
"""

a = Analysis(
    ['src/lamtools_core/app/http_agent_server.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('skills', 'lamtools_core/resources/skills'),
        ('command', 'lamtools_core/resources/command'),
    ],
    hiddenimports=[
        'aiosqlite', 'aiosqlite.core', 'sqlite3',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'lamtools_core',
        'lamtools_core.cli',
        'lamtools_core.app',
        'lamtools_core.app.agent_app',
        'lamtools_core.app.base_agent',
        'lamtools_core.app.http_agent_app',
        'lamtools_core.app.http_agent_server',
        'lamtools_core.app.default_agent',
    ],
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
    name='lamtools-core-backend',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='lamtools-core-backend',
)
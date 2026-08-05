from __future__ import annotations

from app.core.writer import git as writer_git


def test_windows_git_creationflags_hide_console(monkeypatch):
    monkeypatch.setattr(writer_git.sys, "platform", "win32")
    monkeypatch.setattr(writer_git.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    flags = writer_git._windows_git_creationflags()

    assert flags & 0x08000000

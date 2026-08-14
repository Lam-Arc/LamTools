"""Tests for WorkflowStore scoping (delete must never cross scopes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.project.workflow_store import WorkflowDef, WorkflowStore


def _make_definition(name: str, *, work_root: str | None) -> WorkflowDef:
    return WorkflowDef(
        name=name,
        nodes=[],
        edges=[],
        description=f"workflow {name}",
        work_root=work_root,
    )


def _write_folder(store: WorkflowStore, definition: WorkflowDef) -> None:
    import asyncio

    asyncio.run(store.save(definition))


def _delete(store: WorkflowStore, name: str, *, work_root: str | None) -> bool:
    import asyncio

    return asyncio.run(store.delete(name, work_root=work_root))


@pytest.fixture
def scoped_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[WorkflowStore, Path, Path]:
    """A store with an isolated global root (LAMTOOLS_HOME) + one project root."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    monkeypatch.setenv("LAMTOOLS_HOME", str(home))
    store = WorkflowStore()
    store.list_sync(work_root=None)  # prime cache with empty global
    return store, home, project


class TestWorkflowStoreScopedDelete:
    def test_delete_project_does_not_touch_global_same_name(self, scoped_store: tuple[WorkflowStore, Path, Path]) -> None:
        store, home, project = scoped_store
        _write_folder(store, _make_definition("shared", work_root=None))
        _write_folder(store, _make_definition("shared", work_root=str(project)))
        assert store.get_sync("shared", work_root=None) is not None
        assert store.get_sync("shared", work_root=str(project)) is not None

        assert _delete(store, "shared", work_root=str(project)) is True

        # The project copy is gone…
        assert store.get_sync("shared", work_root=str(project)) is None
        # …but the global one survives (audit 11: cross-scope rmtree).
        assert store.get_sync("shared", work_root=None) is not None

    def test_delete_global_does_not_touch_project_same_name(self, scoped_store: tuple[WorkflowStore, Path, Path]) -> None:
        store, home, project = scoped_store
        _write_folder(store, _make_definition("shared", work_root=None))
        _write_folder(store, _make_definition("shared", work_root=str(project)))

        assert _delete(store, "shared", work_root=None) is True

        assert store.get_sync("shared", work_root=None) is None
        assert store.get_sync("shared", work_root=str(project)) is not None

    def test_delete_missing_name_returns_false(self, scoped_store: tuple[WorkflowStore, Path, Path]) -> None:
        store, home, project = scoped_store
        _write_folder(store, _make_definition("keep", work_root=None))
        assert _delete(store, "nope", work_root=None) is False
        assert store.get_sync("keep", work_root=None) is not None


class TestWorkflowStoreSlugFallback:
    def test_delete_matches_non_ascii_name_within_scope(self, scoped_store: tuple[WorkflowStore, Path, Path]) -> None:
        store, home, project = scoped_store
        _write_folder(store, _make_definition("lam的小实验", work_root=str(project)))
        assert _delete(store, "lam的小实验", work_root=str(project)) is True
        assert store.get_sync("lam的小实验", work_root=str(project)) is None


class TestWorkflowStoreSlugCollision:
    def test_ambiguous_slug_delete_refuses_to_guess(self, scoped_store: tuple[WorkflowStore, Path, Path]) -> None:
        """Two names folding to the same slug must never let delete hit the
        wrong one — the slug fallback only fires when it is unambiguous."""
        store, home, project = scoped_store
        # "lam的小实验" and "lam的小实验！" both slug to "lam____"; neither
        # is an exact match for the thread-id form.
        _write_folder(store, _make_definition("lam的小实验", work_root=str(project)))
        _write_folder(store, _make_definition("lam的小实验！", work_root=str(project)))

        # Ambiguous slug → refuse rather than guess.
        assert _delete(store, "lam____", work_root=str(project)) is False
        # Exact names still work for both.
        assert store.get_sync("lam的小实验", work_root=str(project)) is not None
        assert store.get_sync("lam的小实验！", work_root=str(project)) is not None

    def test_unique_slug_fallback_still_resolves(self, scoped_store: tuple[WorkflowStore, Path, Path]) -> None:
        store, home, project = scoped_store
        _write_folder(store, _make_definition("lam的小实验", work_root=str(project)))
        # No other name folds to this slug → thread-id form resolves it.
        assert store.get_sync("lam____", work_root=str(project)) is not None
        assert _delete(store, "lam____", work_root=str(project)) is True
        assert store.get_sync("lam的小实验", work_root=str(project)) is None

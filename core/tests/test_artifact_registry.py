from __future__ import annotations

import json

from lamtools_core.artifact import ArtifactRegistry, kind_from_mime


def test_kind_from_mime_mapping():
    assert kind_from_mime("image/png") == "image"
    assert kind_from_mime("video/mp4") == "video"
    assert kind_from_mime("audio/mpeg") == "audio"
    assert kind_from_mime("application/pdf") == "pdf"
    assert kind_from_mime("application/vnd.openxmlformats-officedocument.wordprocessingml.document") == "document"
    assert kind_from_mime("text/plain") == "document"
    assert kind_from_mime("application/x-something-else") == "file"


def test_register_writes_manifest(tmp_path):
    registry = ArtifactRegistry(tmp_path)

    record = registry.register(
        kind="image",
        mime_type="image/png",
        name="out.png",
        path="workspace://.lam/artifacts/images/out.png",
        source="agent_generated",
        prompt="a red cat",
    )

    assert record.artifact_id
    manifest = tmp_path / ".lam" / "artifact" / f"{record.artifact_id}.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["kind"] == "image"
    assert data["source"] == "agent_generated"
    assert data["prompt"] == "a red cat"
    assert data["deleted"] is False
    assert data["created_at"]

    fetched = registry.get(record.artifact_id)
    assert fetched is not None
    assert fetched.name == "out.png"
    assert fetched.path == "workspace://.lam/artifacts/images/out.png"


def test_generated_images_link_parent_children(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    parent = registry.register(
        kind="image",
        mime_type="image/png",
        name="ref.png",
        path="workspace://.lam/artifacts/images/ref.png",
        source="user_upload",
    )

    ids = registry.register_generated_images(
        prompt="make it night",
        files=[("image/png", 123, ".lam/artifacts/images/a.png"), ("image/png", 456, ".lam/artifacts/images/b.png")],
        parent_ids=[parent.artifact_id],
    )

    assert len(ids) == 2
    child_a = registry.get(ids[0])
    child_b = registry.get(ids[1])
    assert child_a.prompt == "make it night"
    assert child_a.parent_ids == [parent.artifact_id]
    assert child_a.source == "agent_generated"
    # parent's children updated
    refreshed_parent = registry.get(parent.artifact_id)
    assert refreshed_parent.children_ids == ids
    # child b is not a parent of child a
    assert child_a.children_ids == []
    assert child_b.parent_ids == [parent.artifact_id]


def test_resolve_artifact_id(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    record = registry.register(
        kind="image",
        mime_type="image/png",
        name="a.png",
        path="workspace://.lam/artifacts/images/a.png",
        source="agent_generated",
    )

    assert registry.resolve_artifact_id(".lam/artifacts/images/a.png", work_root=tmp_path) == record.artifact_id
    assert registry.resolve_artifact_id("workspace://.lam/artifacts/images/a.png", work_root=tmp_path) == record.artifact_id
    assert registry.resolve_artifact_id(str(tmp_path / ".lam/artifacts/images/a.png"), work_root=tmp_path) == record.artifact_id
    assert registry.resolve_artifact_id("unknown.png", work_root=tmp_path) is None
    assert registry.resolve_artifact_id("https://example.com/x.png", work_root=tmp_path) is None


def test_resolve_attachment_artifact(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    registry.register(
        kind="image",
        mime_type="image/png",
        name="up.png",
        path="attachment://abc123",
        source="user_upload",
    )

    assert registry.resolve_artifact_id("attachment://abc123", work_root=tmp_path) is not None


def test_soft_delete_keeps_tombstone(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    a = registry.register(kind="image", mime_type="image/png", name="a.png", path="workspace://a.png", source="agent_generated")
    b = registry.register(kind="image", mime_type="image/png", name="b.png", path="workspace://b.png", source="agent_generated")

    assert registry.soft_delete([a.artifact_id]) == 1
    # id 保留（manifest 仍在，deleted=True）
    tombstone = registry.get(a.artifact_id)
    assert tombstone is not None and tombstone.deleted is True
    assert (tmp_path / ".lam" / "artifact" / f"{a.artifact_id}.json").exists()

    active = [r.artifact_id for r in registry.list()]
    assert b.artifact_id in active
    assert a.artifact_id not in active
    all_records = [r.artifact_id for r in registry.list(include_deleted=True)]
    assert a.artifact_id in all_records
    # 重复删除不重复计数
    assert registry.soft_delete([a.artifact_id]) == 0
    # 未知 id 不计入
    assert registry.soft_delete(["missing"]) == 0


def test_list_sorted_by_created_at(tmp_path):
    registry = ArtifactRegistry(tmp_path)
    first = registry.register(kind="image", mime_type="image/png", name="a.png", path="workspace://a.png", source="agent_generated")
    second = registry.register(kind="image", mime_type="image/png", name="b.png", path="workspace://b.png", source="agent_generated")

    ids = [r.artifact_id for r in registry.list()]
    assert ids == [first.artifact_id, second.artifact_id]

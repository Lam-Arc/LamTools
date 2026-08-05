from app.member import kit, manifest


def test_member_manifest_and_kit_match() -> None:
    """Sage exposes its member contract through the shared Core interface."""
    assert kit.id == manifest.id
    assert kit.display_name == manifest.display_name
    assert kit.prompt_fragments()
    assert kit.tool_specs() == []
    assert kit.verification_policy().name == f"{manifest.id}-default"
    assert kit.verification_policy().required is True
    evidence_categories = set(kit.verification_policy().metadata["evidence_categories"])
    assert {"file_read", "web", "browser", "mcp", "agent"} <= evidence_categories
    assert "skill" not in evidence_categories
    assert "control" not in evidence_categories
    assert "document_normalize" in kit.verification_policy().metadata["evidence_tools"]

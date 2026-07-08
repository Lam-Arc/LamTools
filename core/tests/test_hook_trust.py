from __future__ import annotations

from lamtools_core.plugins import HookTrustStore


def test_hook_trust_store_persists_hashes(tmp_path):
    path = tmp_path / "trust.json"
    store = HookTrustStore(path)
    store.trust("abc123")

    assert HookTrustStore(path).is_trusted("abc123") is True
    assert HookTrustStore(path).is_trusted("missing") is False


def test_hook_trust_store_can_untrust_hash(tmp_path):
    store = HookTrustStore(tmp_path / "trust.json")
    store.trust("abc123")
    store.untrust("abc123")

    assert store.is_trusted("abc123") is False

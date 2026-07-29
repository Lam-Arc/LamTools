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


def test_hook_trust_store_handles_multiple_hashes(tmp_path):
    store = HookTrustStore(tmp_path / "trust.json")
    store.trust("hash-1")
    store.trust("hash-2")
    store.trust("hash-3")

    # Reload to verify persistence
    store2 = HookTrustStore(tmp_path / "trust.json")
    assert store2.is_trusted("hash-1")
    assert store2.is_trusted("hash-2")
    assert store2.is_trusted("hash-3")
    assert not store2.is_trusted("hash-4")


def test_hook_trust_store_untrust_non_existent_noop(tmp_path):
    store = HookTrustStore(tmp_path / "trust.json")
    store.trust("hash-1")
    store.untrust("hash-999")  # should not crash

    assert store.is_trusted("hash-1")
    assert not store.is_trusted("hash-999")

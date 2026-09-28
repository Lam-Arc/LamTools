"""Tests for cross-process session ownership helpers."""

from __future__ import annotations

import os
import socket

from lamtools_core.runtime_owner import (
    LIVE_RUN_STATES,
    OWNER_METADATA_KEY,
    is_own_token,
    owner_is_live,
    owner_token,
    process_is_alive,
    read_owner,
    refresh_owner,
    state_row_is_live,
)


def test_owner_token_records_this_process():
    token = owner_token()

    assert token["pid"] == os.getpid()
    assert token["host"] == socket.gethostname()
    assert token["started_at"] <= token["heartbeat_at"]
    assert is_own_token(token) is True


def test_refresh_owner_keeps_the_original_start_time():
    metadata: dict = {}
    first = refresh_owner(metadata, now=1000.0)
    second = refresh_owner(metadata, now=2000.0)

    assert read_owner(metadata) == second
    assert second["started_at"] == first["started_at"] == 1000.0
    assert second["heartbeat_at"] == 2000.0


def test_read_owner_ignores_missing_or_malformed_metadata():
    assert read_owner(None) == {}
    assert read_owner({}) == {}
    assert read_owner({OWNER_METADATA_KEY: "not-a-token"}) == {}
    assert read_owner({OWNER_METADATA_KEY: {"pid": 1}}) == {"pid": 1}


def test_process_is_alive_distinguishes_this_process_from_a_missing_pid():
    assert process_is_alive(os.getpid()) is True
    assert process_is_alive(0) is False
    # A pid no OS assigns on a freshly booted machine.
    assert process_is_alive(999_999_999) is False


def test_owner_is_live_uses_local_pid_then_heartbeat():
    local_dead = {"pid": 999_999_999, "host": socket.gethostname(), "heartbeat_at": 0.0}
    assert owner_is_live(local_dead) is False

    remote_fresh = {"pid": 1, "host": "another-host", "heartbeat_at": 1000.0}
    remote_stale = {"pid": 1, "host": "another-host", "heartbeat_at": 1000.0}
    assert owner_is_live(remote_fresh, now=1100.0, stale_after=600.0) is True
    assert owner_is_live(remote_stale, now=5000.0, stale_after=600.0) is False

    assert owner_is_live(None) is False
    assert owner_is_live({}) is False


def test_state_row_is_live_only_for_in_flight_states():
    owner = owner_token()
    for status in sorted(LIVE_RUN_STATES):
        assert state_row_is_live({"status": status, "metadata": {OWNER_METADATA_KEY: owner}}) is True
    for status in ("done", "failed", "cancelled", "idle", ""):
        assert state_row_is_live({"status": status, "metadata": {OWNER_METADATA_KEY: owner}}) is False


def test_state_row_is_live_is_false_when_the_owning_process_is_gone():
    payload = {
        "status": "running",
        "metadata": {OWNER_METADATA_KEY: {"pid": 999_999_999, "host": socket.gethostname()}},
    }

    assert state_row_is_live(payload) is False
    assert state_row_is_live(None) is False

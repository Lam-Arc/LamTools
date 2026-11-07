"""Tests for the model usage ledger, pricing and provider connection status."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lamtools_core.config.model_store import ModelConfig, ModelStore, normalize_pricing
from lamtools_core.config.operations import build_config_operation_catalog
from lamtools_core.config.provider_probe import _state_for_status, load_cached_status, probe_provider
from lamtools_core.config.provider_store import ProviderConfig, ProviderStore
from lamtools_core.usage.ledger import read_usage, record_model_call


@pytest.fixture()
def usage_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "usage.db"
    monkeypatch.setenv("LAMTOOLS_CORE_USAGE_DB", str(path))
    return path


def _write_provider(config_root: Path, provider_id: str, *, name: str, api_key: str = "sk-test", extra: dict | None = None) -> None:
    store = ProviderStore()
    store.write(
        ProviderConfig(
            id=provider_id,
            name=name,
            api_type="openai",
            base_url="https://example.test/v1",
            api_key=api_key,
            extra=extra or {},
        ),
        scope="global",
        work_root=None,
    )


def _write_model(config_root: Path, record_id: str, provider_id: str, provider_name: str, *, pricing: dict | None = None) -> None:
    store = ModelStore()
    store.write(
        ModelConfig(
            id=record_id,
            model_id=f"{record_id}-upstream",
            display_name=record_id,
            provider_id=provider_id,
            provider=provider_name,
            context_window=128000,
            max_output_tokens=8192,
            capability="text",
            pricing=pricing or {},
        ),
        scope="global",
        work_root=None,
    )


def test_normalize_pricing_drops_invalid_values() -> None:
    assert normalize_pricing(None) == {}
    assert normalize_pricing({"input_per_1m": "0.5", "output_per_1m": -1}) == {"input_per_1m": 0.5}
    assert normalize_pricing({"input_per_1m": "abc", "currency": "usd"}) == {"currency": "USD"}
    assert normalize_pricing({"output_per_1m": float("nan")}) == {}


def test_model_pricing_roundtrips_through_jsonc(isolated_config_root: Path) -> None:
    _write_model(
        isolated_config_root, "deepseek-flash", "deepseek", "DeepSeek",
        pricing={"input_per_1m": 0.14, "output_per_1m": 0.28, "currency": "USD"},
    )
    model = ModelStore().get_sync("deepseek-flash", work_root=None)
    assert model is not None
    assert model.pricing["input_per_1m"] == pytest.approx(0.14)
    raw = json.loads(Path(model.source_path).read_text(encoding="utf-8"))
    assert raw["pricing"]["output_per_1m"] == pytest.approx(0.28)


def test_ledger_records_calls_and_aggregates(usage_db: Path) -> None:
    record_model_call(
        model_record_id="model-a", model_id="up-a", provider_id="p1", provider_name="P1",
        input_tokens=1000, output_tokens=500, cached_tokens=200,
    )
    record_model_call(
        model_record_id="model-a", model_id="up-a", provider_id="p1", provider_name="P1",
        input_tokens=2000, output_tokens=1000,
    )
    record_model_call(model_record_id="model-b", model_id="up-b", provider_id="p2", provider_name="P2")

    summary = read_usage(days=30)
    assert summary["totals"] == {
        "calls": 3, "input_tokens": 3000, "output_tokens": 1500,
        "cached_tokens": 200, "tokens": 4500,
    }
    by_model = {item["model_record_id"]: item for item in summary["by_model"]}
    assert by_model["model-a"]["calls"] == 2
    assert by_model["model-a"]["tokens"] == 4500
    assert by_model["model-b"]["calls"] == 1
    assert len(summary["series"]["model-a"]) == 14
    assert summary["tracking_since"]


def test_usage_rpc_applies_pricing_and_budget(isolated_config_root: Path, usage_db: Path) -> None:
    _write_provider(isolated_config_root, "p1", name="P1", extra={"monthly_budget_usd": 10})
    _write_model(
        isolated_config_root, "model-a", "p1", "P1",
        pricing={"input_per_1m": 1.0, "output_per_1m": 2.0},
    )
    record_model_call(
        model_record_id="model-a", model_id="up-a", provider_id="p1", provider_name="P1",
        input_tokens=1_000_000, output_tokens=500_000,
    )
    catalog = build_config_operation_catalog(work_root=None)

    async def run() -> dict:
        result = await catalog.execute("config.models.usage", {"range": "30d"})
        return result.payload

    payload = asyncio.run(run())
    assert payload["totals"]["cost"] == pytest.approx(2.0)
    assert payload["by_model"][0]["priced"] is True
    assert payload["by_model"][0]["cost"] == pytest.approx(2.0)
    provider = payload["by_provider"][0]
    assert provider["budget_usd"] == pytest.approx(10)
    assert provider["month_cost"] == pytest.approx(2.0)
    assert payload["daily"][-1]["tokens"] == 1_500_000


def test_provider_status_uses_cache_and_marks_missing_keys(isolated_config_root: Path) -> None:
    _write_provider(isolated_config_root, "p1", name="P1")
    _write_provider(isolated_config_root, "p2", name="P2", api_key="")
    cache = isolated_config_root.parent / "cache" / "provider_status.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "providers": {
            "p1": {"state": "ok", "latency_ms": 123, "checked_at": "now", "model_count": 4},
            "p2": {"state": "ok", "latency_ms": 50, "checked_at": "now"},
        }
    }), encoding="utf-8")
    assert load_cached_status()["providers"]["p1"]["state"] == "ok"

    catalog = build_config_operation_catalog(work_root=None)

    async def run() -> dict:
        result = await catalog.execute("config.providers.status", {})
        return result.payload

    payload = asyncio.run(run())
    assert payload["providers"]["p1"] == {
        "state": "ok", "detail": "", "latency_ms": 123, "http_status": 0,
        "model_count": 4, "checked_at": "now",
    }
    # A cached success cannot survive a removed key.
    assert payload["providers"]["p2"]["state"] == "missing_key"


def test_probe_provider_reports_local_states_without_network(isolated_config_root: Path) -> None:
    async def run() -> tuple[dict, dict]:
        missing = await probe_provider(ProviderConfig(id="x", name="X", base_url="https://example.test/v1", api_key=""))
        invalid = await probe_provider(ProviderConfig(id="y", name="Y", base_url="not-a-url", api_key="k"))
        return missing, invalid

    missing, invalid = asyncio.run(run())
    assert missing["state"] == "missing_key"
    assert invalid["state"] == "invalid"


def test_probe_state_mapping() -> None:
    assert _state_for_status(200) == "ok"
    assert _state_for_status(401) == "unauthorized"
    assert _state_for_status(404) == "no_model_list"
    assert _state_for_status(429) == "rate_limited"
    assert _state_for_status(500) == "error"

def test_model_create_keeps_zero_values_and_pricing(isolated_config_root: Path) -> None:
    _write_provider(isolated_config_root, "p1", name="P1")
    catalog = build_config_operation_catalog(work_root=None)

    async def run() -> dict:
        result = await catalog.execute("config.model.create", {
            "provider_id": "p1",
            "model_id": "zero-model",
            "display_name": "Zero Model",
            "temperature": 0,
            "thinking_supported": True,
            "thinking_budget": 0,
            "enabled": False,
            "pricing": {"input_per_1m": 0.2, "output_per_1m": 0.4, "currency": "usd"},
        })
        return result.payload

    asyncio.run(run())
    model = ModelStore().get_sync("p1-zero-model", work_root=None)
    assert model is not None
    assert model.temperature == 0
    assert model.thinking_budget == 0
    assert model.enabled is False
    assert model.pricing["input_per_1m"] == pytest.approx(0.2)
    assert model.pricing["currency"] == "USD"

    from lamtools_core.cli_commands.config import list_llm_model_configs

    listed = list_llm_model_configs()
    assert listed[0]["pricing"]["output_per_1m"] == pytest.approx(0.4)
    assert listed[0]["enabled"] is False

"""File-backed model definitions (jsonc).

Model definitions live as one jsonc file per model under:

* Project:  ``{work_root}/.lam/config/models/<model_id>.jsonc``
* Global:   ``~/.lam/config/models/<model_id>.jsonc``
* Built-in: the app-shipped ``core/config/resources/models/`` directory.

Resolution merges all scopes with **project overriding global overriding
built-in** on a per-``model_id`` basis (so a project can specialise a single
model without forking the whole set). Provider connection info (base_url,
api_key, api_type) stays in the shared config DB; each model references its
provider by ``provider`` name (or ``provider_id``).

This mirrors the file-backed resource-store pattern used by bundled plugins.
discovery pattern: lazy scan + mtime signature cache. Parsing uses
:func:`lamtools_core.llm.profiles.load_jsonc` (comment- and trailing-comma
tolerant) — never plain ``json.loads``.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .id_validation import validate_config_id
from typing import Any

from lamtools_core.llm.model_capabilities import Capability, resolve_capability
from lamtools_core.config.root import core_config_dir, legacy_user_config_dir
from lamtools_core.llm.profiles import load_jsonc

MODELS_SUBDIR = "models"
MODEL_FILENAME_SUFFIX = ".jsonc"

#: 模型能直接产出什么。``capability`` 描述输入模态（能不能看图），
#: 这里描述输出模态，直调台据此切换输入与结果形态。
OUTPUT_TYPES = ("text", "image", "video", "audio")


def normalize_output_type(value: Any) -> str:
    """把 jsonc/RPC 里的输出类型收敛到四种已知值，未知值按文本处理。

    user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
    +(不认识的类型不能带进调用台，否则界面会去执行一个不存在的调用路径。)
    """
    normalized = str(value or "").strip().lower()
    return normalized if normalized in OUTPUT_TYPES else "text"


@dataclass
class ModelConfig:
    """A single model definition loaded from jsonc."""

    id: str = ""                  # stable safe record id / file stem
    model_id: str = ""
    display_name: str = ""
    provider: str = ""            # provider name (resolved against the DB)
    provider_id: str = ""        # alternative: explicit provider DB id
    context_window: int = 0
    max_output_tokens: int = 4096
    temperature: float = 0.2
    thinking_supported: bool = False
    thinking_budget: int = 10000
    reasoning_effort: str = ""
    reasoning: dict[str, Any] = field(default_factory=dict)
    adapter_profile_id: str = ""  # reference to a shared adapter profile
    request_body: dict[str, Any] = field(default_factory=dict)  # per-model override
    adapter_profile_override: dict[str, Any] = field(default_factory=dict)
    capability: str = ""          # "text" | "multimodal" | "" (→ builtin table)
    # user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
    # +(输出类型决定直调台给哪种输入表单、把结果渲染成文本/图片/视频/音频)。
    output_type: str = "text"     # "text" | "image" | "video" | "audio"
    notes: str = ""               # free-form notes/remarks (optional, user-facing)
    is_default: bool = False
    # user:“能不能启停模型？”+(停用只从可选列表里下线，不删除配置；已有会话仍可继续跑。)
    enabled: bool = True
    # user:“展示模型能力、连接状态、调用用量、Token 消耗、费用与额度”+(价格随模型定义保存，
    # 用量聚合时按它折算费用；未配置价格就只报 token，不编造金额。)
    pricing: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""         # which file this came from (for debugging/UI)

    @property
    def resolved_capability(self) -> Capability:
        # jsonc capability is the single source of truth; model_id plays no role.
        return resolve_capability(jsonc_capability=self.capability)

    def to_extra(self) -> dict[str, Any]:
        """Materialise the model_extra dict consumed by the adapter profile resolver.

        ``adapter_profile_id`` and a per-model ``request_body`` override are
        surfaced through the existing ``model_extra`` plumbing
        (``adapter_profile_id`` / ``adapter_profile_override``).
        """
        extra: dict[str, Any] = {}
        if self.adapter_profile_id:
            extra["adapter_profile_id"] = self.adapter_profile_id
        override = copy.deepcopy(self.adapter_profile_override)
        if self.request_body:
            # The profile resolver reads ``adapter_profile_override.request.body``.
            request = override.get("request") if isinstance(override.get("request"), dict) else {}
            body = request.get("body") if isinstance(request.get("body"), dict) else {}
            request["body"] = _deep_merge(body, self.request_body)
            override["request"] = request
        if override:
            extra["adapter_profile_override"] = override
        if self.reasoning:
            extra["reasoning"] = copy.deepcopy(self.reasoning)
        if self.capability:
            extra["capability"] = self.capability
        return extra


def _repo_resource_models_dir() -> Path:
    """Built-in shipped models dir: <repo>/core/config/resources/models.

    Resolved relative to this file in dev; from ``_MEIPASS/config/resources``
    when frozen (PyInstaller).
    """
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "config" / "resources" / MODELS_SUBDIR
    return Path(__file__).resolve().parent.parent.parent.parent / "config" / "resources" / MODELS_SUBDIR


class ModelStore:
    """Discovers, parses, and writes per-model jsonc definition files."""

    def __init__(self, *, explicit_roots: Iterable[str | Path] = ()) -> None:
        self._explicit_roots = tuple(Path(item).resolve() for item in explicit_roots)
        self._cached_signature: tuple[tuple[str, int, int], ...] | None = None
        self._cached_models: dict[str, ModelConfig] | None = None
        self._cached_default: str = ""

    # -- discovery --------------------------------------------------------

    def _candidate_dirs(self, work_root: str | None) -> list[Path]:
        """Return model dirs in ascending precedence (built-in → legacy → unified → project).

        The unified config directory is where new writes land, so it must
        override the legacy ``{lam_home}/config/models`` read fallback — a
        model edited/created in the unified directory would otherwise be
        shadowed by a stale legacy file with the same ``model_id``.
        """
        dirs: list[Path] = []
        builtin = _repo_resource_models_dir()
        if builtin.is_dir():
            dirs.append(builtin)
        legacy = legacy_user_config_dir() / MODELS_SUBDIR
        if legacy.is_dir() and legacy != core_config_dir() / MODELS_SUBDIR:
            dirs.append(legacy)
        # Unified config directory (user-modifiable after packaging).
        unified = core_config_dir() / MODELS_SUBDIR
        if unified.is_dir():
            dirs.append(unified)
        for root in self._explicit_roots:
            candidate = root / "config" / MODELS_SUBDIR
            if candidate.is_dir():
                dirs.append(candidate)
        if work_root:
            project_dir = Path(work_root).resolve() / ".lam" / "config" / MODELS_SUBDIR
            if project_dir.is_dir():
                dirs.append(project_dir)
        return dirs

    def _candidate_files(self, work_root: str | None) -> list[Path]:
        seen: set[Path] = set()
        results: list[Path] = []
        for directory in self._candidate_dirs(work_root):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.jsonc")):
                resolved = path.resolve()
                if resolved not in seen and resolved.is_file():
                    seen.add(resolved)
                    results.append(resolved)
        return results

    def _signature(self, work_root: str | None) -> tuple[tuple[str, int, int], ...]:
        entries: list[tuple[str, int, int]] = []
        for path in self._candidate_files(work_root):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(entries)

    # -- parse -----------------------------------------------------------

    @staticmethod
    def _parse(path: Path) -> ModelConfig | None:
        try:
            data = load_jsonc(path)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        record_id = str(data.get("id") or path.stem).strip()
        try:
            validate_config_id("model record", record_id)
        except ValueError:
            return None
        model_id = str(data.get("model_id") or record_id).strip()
        if not model_id:
            return None
        thinking = data.get("thinking")
        if not isinstance(thinking, dict):
            thinking = {}
        request_body = data.get("request_body")
        if not isinstance(request_body, dict):
            request_body = {}
        profile_override = data.get("adapter_profile_override")
        if not isinstance(profile_override, dict):
            profile_override = {}
        reasoning = data.get("reasoning")
        if not isinstance(reasoning, dict):
            reasoning = {}
        pricing = normalize_pricing(data.get("pricing"))
        return ModelConfig(
            id=record_id,
            model_id=model_id,
            display_name=str(data.get("display_name") or "").strip(),
            provider=str(data.get("provider") or "").strip(),
            provider_id=str(data.get("provider_id") or "").strip(),
            context_window=int(data.get("context_window") or 0),
            max_output_tokens=int(data.get("max_output_tokens") or 4096),
            # user:“温度/推理预算填 0 要能保存”+(0 是合法值，解析时不能被默认值吞掉。)
            temperature=(
                0.2 if data.get("temperature") is None else float(data.get("temperature"))
            ),
            thinking_supported=bool(thinking.get("supported", data.get("thinking_supported") or False)),
            thinking_budget=(
                10000
                if thinking.get("budget", data.get("thinking_budget")) is None
                else int(thinking.get("budget", data.get("thinking_budget")))
            ),
            reasoning_effort=str(data.get("reasoning_effort") or "").strip(),
            reasoning=copy.deepcopy(reasoning),
            adapter_profile_id=str(data.get("adapter_profile_id") or "").strip(),
            request_body=request_body,
            adapter_profile_override=copy.deepcopy(profile_override),
            capability=str(data.get("capability") or "").strip().lower(),
            output_type=normalize_output_type(data.get("output_type")),
            notes=str(data.get("notes") or "").strip(),
            is_default=bool(data.get("is_default") or False),
            enabled=bool(data.get("enabled", True)),
            pricing=pricing,
            source_path=str(path),
        )

    # -- async API -------------------------------------------------------

    async def list(self, *, work_root: str | None = None) -> list[ModelConfig]:
        return await asyncio.to_thread(self.list_sync, work_root=work_root)

    def list_sync(self, *, work_root: str | None = None) -> list[ModelConfig]:
        models = self._load_map(work_root)
        return sorted(models.values(), key=lambda m: (m.display_name or m.model_id or m.id).casefold())

    async def get(self, model_ref: str, *, work_root: str | None = None) -> ModelConfig | None:
        return await asyncio.to_thread(self.get_sync, model_ref, work_root=work_root)

    def get_sync(self, model_ref: str, *, work_root: str | None = None) -> ModelConfig | None:
        if not model_ref:
            return None
        ref = model_ref.strip()
        models = self._load_map(work_root)
        if ref in models:
            return models[ref]
        # External model ids are not filesystem ids and may contain '/'.  They
        # remain accepted as an unambiguous convenience lookup.
        lowered = ref.lower()
        exact = [model for model in models.values() if model.model_id == ref or model.display_name.lower() == lowered]
        if len(exact) == 1:
            return exact[0]
        # Substring match on display_name as a last resort.
        for model in models.values():
            if lowered and lowered in model.display_name.lower():
                return model
        return None

    async def default_model_id(self, *, work_root: str | None = None) -> str:
        return await asyncio.to_thread(self.default_model_id_sync, work_root=work_root)

    def default_model_id_sync(self, *, work_root: str | None = None) -> str:
        self._load_map(work_root)
        return self._cached_default

    # -- internal: cached load ------------------------------------------

    def _load_map(self, work_root: str | None) -> dict[str, ModelConfig]:
        files = self._candidate_files(work_root)
        from .change_notice import observe_config_files

        observe_config_files("model", files)
        sig = self._signature(work_root)
        if self._cached_signature == sig and self._cached_models is not None:
            return self._cached_models
        # Candidate files are ordered built-in → global → explicit → project,
        # so later entries override earlier ones on a per-model_id basis.
        models: dict[str, ModelConfig] = {}
        default_id = ""
        for path in files:
            model = self._parse(path)
            if model is None:
                continue
            models[model.id] = model
            if model.is_default:
                default_id = default_id or model.id
        self._cached_signature = sig
        self._cached_models = models
        self._cached_default = default_id
        return models

    # -- write -----------------------------------------------------------

    @staticmethod
    def write_path(model_id: str, *, scope: str, work_root: str | None) -> Path:
        validate_config_id("model record", model_id)
        if scope == "project" and work_root:
            return Path(work_root).resolve() / ".lam" / "config" / MODELS_SUBDIR / f"{model_id}{MODEL_FILENAME_SUFFIX}"
        return core_config_dir() / MODELS_SUBDIR / f"{model_id}{MODEL_FILENAME_SUFFIX}"

    def write(self, model: ModelConfig, *, scope: str, work_root: str | None) -> Path:
        if not model.id:
            try:
                model.id = validate_config_id("model record", model.model_id)
            except ValueError:
                model.id = make_model_record_id(model.provider_id or model.provider, model.model_id)
        validate_config_id("model record", model.id)
        path = self.write_path(model.id, scope=scope, work_root=work_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        from lamtools_core.config.root import atomic_write_text

        atomic_write_text(path, self._serialize(model))
        from .change_notice import mark_self_written

        mark_self_written(path)
        self._cached_signature = None  # invalidate cache
        self._cached_models = None
        return path

    @staticmethod
    def _serialize(model: ModelConfig) -> str:
        import json

        data: dict[str, Any] = {
            "id": model.id,
            "model_id": model.model_id,
            "display_name": model.display_name,
            "provider": model.provider,
            "context_window": model.context_window,
            "max_output_tokens": model.max_output_tokens,
            "temperature": model.temperature,
            "thinking": {"supported": model.thinking_supported, "budget": model.thinking_budget},
            "adapter_profile_id": model.adapter_profile_id,
            "capability": model.capability,
            "output_type": normalize_output_type(model.output_type),
            "notes": model.notes,
            "is_default": model.is_default,
            "enabled": model.enabled,
        }
        if model.provider_id:
            data["provider_id"] = model.provider_id
        if model.reasoning_effort:
            data["reasoning_effort"] = model.reasoning_effort
        if model.reasoning:
            data["reasoning"] = copy.deepcopy(model.reasoning)
        if model.request_body:
            data["request_body"] = copy.deepcopy(model.request_body)
        if model.adapter_profile_override:
            data["adapter_profile_override"] = copy.deepcopy(model.adapter_profile_override)
        if model.pricing:
            data["pricing"] = copy.deepcopy(model.pricing)
        return json.dumps(data, ensure_ascii=False, indent=2)


PRICING_KEYS = ("input_per_1m", "output_per_1m", "cache_read_per_1m", "cache_write_per_1m")


def normalize_pricing(value: Any) -> dict[str, Any]:
    """Keep only finite non-negative per-million-token prices.

    user:“展示模型能力、连接状态、调用用量、Token 消耗、费用与额度”+(价格是可选配置；
    缺失或非法值一律丢弃，免得把错误数字乘进费用。)
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in PRICING_KEYS:
        raw = value.get(key)
        if raw is None or raw == "":
            continue
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price < 0 or price != price or price in (float("inf"), float("-inf")):
            continue
        result[key] = price
    currency = str(value.get("currency") or "").strip().upper()
    if currency:
        result["currency"] = currency[:8]
    return result


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


__all__ = [
    "MODELS_SUBDIR",
    "MODEL_FILENAME_SUFFIX",
    "OUTPUT_TYPES",
    "ModelConfig",
    "ModelStore",
    "make_model_record_id",
    "normalize_output_type", "normalize_pricing",
]


def make_model_record_id(provider_id: str, model_id: str) -> str:
    """Return a deterministic safe record id without changing upstream model_id."""
    raw = f"{provider_id}-{model_id}".strip("-")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-.").lower()
    if not slug or not slug[0].isalnum():
        slug = f"model-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"
    if len(slug) > 128:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        slug = f"{slug[:115].rstrip('-.')}-{digest}"
    return validate_config_id("model record", slug)


def resolve_model_capability(model_id: str, *, work_root: str | None = None) -> str:
    """Resolve a model's modality by reading its jsonc ``capability``.

    jsonc is the single source of truth, so a bare model_id is *not* enough —
    this looks up the model's jsonc definition (project over global over
    built-in) and returns its resolved capability, defaulting to ``"text"``
    when the model has no definition or no declared``capability``.
    """
    try:
        model = ModelStore().get_sync(model_id, work_root=work_root)
    except Exception:
        return "text"
    return model.resolved_capability if model is not None else "text"

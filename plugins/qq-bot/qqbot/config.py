"""Configuration, presets and prompt composition for the QQ bot plugin."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .util import jsonc_load, write_json

# Defaults are copied from the upstream ``ConfigSchema`` (0.5.3).  The extra
# fields at the end are host-side additions; they do not remove any upstream
# capability.
DEFAULTS: dict[str, Any] = {
    "appId": "",
    "appSecret": "",
    "provider": "",
    "model": "",
    "preset": "",
    "cwd": "",
    "targetProjectId": "",
    "targetSessionId": "",
    "requireMention": True,
    "groupPrompt": "",
    "directPrompt": "",
    "textChunkLimit": 4500,
    "bubbles": {
        "profile": "full",
        "table": "markdown",
        "code": "fence",
        "heading": "keep",
        "inlineCode": "keep",
        "math": "keep",
        "html": "keep",
    },
    "streaming": True,
    "sessionIdleTimeout": 30 * 60 * 1000,
    "maxQueue": 20,
    "processingTimeoutMs": 30 * 60 * 1000,
    "askTimeoutMs": 5 * 60 * 1000,
    "historyLimit": 10,
    "access": {
        "c2cMode": "open",
        "c2cAllow": [],
        "groupMode": "open",
        "groupAllow": [],
    },
    "showToolResults": False,
    "debug": False,
    "media": {"enabled": True, "maxMB": 200, "ttlHours": 24},
    "vision": {
        "enabled": False,
        "provider": "",
        "model": "",
        "defaultPrompt": "Describe this image in detail.",
        "maxBytes": 10 * 1024 * 1024,
        "maxTokens": 1024,
        "timeoutMs": 120000,
    },
    "sendFile": {
        "restrictPaths": True,
        "extraRoots": [],
        "sendPresentedFiles": True,
        "maxFiles": 4,
    },
    # Host-side additions
    "agentMode": "",
    "replyLimit": 4,
}

DEFAULT_PRESETS: dict[str, Any] = {
    "presets": [
        {
            "id": "default",
            "title": "默认",
            "mode": "",
            "tools": [],
            "prompt": "",
        },
        {
            "id": "readonly",
            "title": "只读",
            "mode": "low",
            "tools": [
                "read_file",
                "list_dir",
                "search_files",
                "search_content",
                "load_skill",
                "web_search",
                "web_fetch",
            ],
            "prompt": "这一轮只允许读取和搜索，不要修改文件或执行有副作用的命令。",
        },
        {
            "id": "careful",
            "title": "谨慎执行",
            "mode": "medium",
            "tools": [],
            "prompt": "执行有副作用的操作前先用一句话说明你要做什么；能只读就先只读。",
        },
    ]
}


def config_file(data_dir: Path) -> Path:
    return Path(data_dir) / "config.jsonc"


def presets_file(data_dir: Path) -> Path:
    return Path(data_dir) / "presets.jsonc"


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except Exception:
        return default
    return max(low, min(high, number))


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _mode(value: Any) -> str:
    value = str(value or "").strip()
    return value if value in {"open", "allowlist", "disabled"} else "open"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = deep_merge(DEFAULTS, raw or {})
    cfg["appId"] = str(cfg.get("appId") or "").strip()
    cfg["appSecret"] = str(cfg.get("appSecret") or "").strip()
    for key in ("provider", "model", "preset", "cwd", "targetProjectId", "targetSessionId", "groupPrompt", "directPrompt"):
        cfg[key] = str(cfg.get(key) or "").strip()
    cfg["requireMention"] = _bool(cfg.get("requireMention"), True)
    cfg["streaming"] = _bool(cfg.get("streaming"), True)
    cfg["showToolResults"] = _bool(cfg.get("showToolResults"), False)
    cfg["debug"] = _bool(cfg.get("debug"), False)
    cfg["textChunkLimit"] = _int(cfg.get("textChunkLimit"), 4500, 200, 10000)
    cfg["sessionIdleTimeout"] = _int(cfg.get("sessionIdleTimeout"), 30 * 60 * 1000, 60_000, 7 * 24 * 3600 * 1000)
    cfg["maxQueue"] = _int(cfg.get("maxQueue"), 20, 0, 200)
    cfg["processingTimeoutMs"] = _int(cfg.get("processingTimeoutMs"), 30 * 60 * 1000, 10_000, 24 * 3600 * 1000)
    cfg["askTimeoutMs"] = _int(cfg.get("askTimeoutMs"), 5 * 60 * 1000, 10_000, 24 * 3600 * 1000)
    cfg["historyLimit"] = _int(cfg.get("historyLimit"), 10, 0, 200)
    cfg["replyLimit"] = _int(cfg.get("replyLimit"), 4, 1, 10)
    mode = str(cfg.get("agentMode") or "").strip()
    cfg["agentMode"] = mode if mode in {"", "auto", "low", "medium", "high"} else ""

    access = cfg.get("access") if isinstance(cfg.get("access"), dict) else {}
    cfg["access"] = {
        "c2cMode": _mode(access.get("c2cMode")),
        "c2cAllow": _string_list(access.get("c2cAllow")),
        "groupMode": _mode(access.get("groupMode")),
        "groupAllow": _string_list(access.get("groupAllow")),
    }

    bubbles = cfg.get("bubbles") if isinstance(cfg.get("bubbles"), dict) else {}
    raw_bubbles = raw.get("bubbles") if isinstance(raw, dict) and isinstance(raw.get("bubbles"), dict) else {}
    profile = str(bubbles.get("profile") or "full").strip().lower()
    if profile not in {"safe", "full"}:
        profile = "full"
    defaults = {
        "safe": {
            "table": "cards",
            "code": "quote",
            "heading": "keep",
            "inlineCode": "quote",
            "math": "plain",
            "html": "strip",
        },
        "full": {
            "table": "markdown",
            "code": "fence",
            "heading": "keep",
            "inlineCode": "keep",
            "math": "keep",
            "html": "keep",
        },
    }[profile]
    allowed = {
        "table": {"markdown", "cards"},
        "code": {"fence", "quote"},
        "heading": {"keep", "bold"},
        "inlineCode": {"keep", "quote"},
        "math": {"keep", "plain"},
        "html": {"keep", "strip"},
    }
    normalized_bubbles = {"profile": profile}
    for key, fallback in defaults.items():
        value = str(raw_bubbles.get(key) or fallback).strip()
        normalized_bubbles[key] = value if value in allowed[key] else fallback
    cfg["bubbles"] = normalized_bubbles

    media = cfg.get("media") if isinstance(cfg.get("media"), dict) else {}
    cfg["media"] = {
        "enabled": _bool(media.get("enabled"), True),
        "maxMB": _int(media.get("maxMB"), 200, 1, 2048),
        "ttlHours": _int(media.get("ttlHours"), 24, 0, 24 * 365),
    }

    vision = cfg.get("vision") if isinstance(cfg.get("vision"), dict) else {}
    cfg["vision"] = {
        "enabled": _bool(vision.get("enabled"), False),
        "provider": str(vision.get("provider") or "").strip(),
        "model": str(vision.get("model") or "").strip(),
        "defaultPrompt": str(vision.get("defaultPrompt") or "Describe this image in detail."),
        "maxBytes": _int(vision.get("maxBytes"), 10 * 1024 * 1024, 1024, 100 * 1024 * 1024),
        "maxTokens": _int(vision.get("maxTokens"), 1024, 1, 65536),
        "timeoutMs": _int(vision.get("timeoutMs"), 120000, 1000, 600000),
    }

    send_file = cfg.get("sendFile") if isinstance(cfg.get("sendFile"), dict) else {}
    cfg["sendFile"] = {
        "restrictPaths": _bool(send_file.get("restrictPaths"), True),
        "extraRoots": _string_list(send_file.get("extraRoots")),
        "sendPresentedFiles": _bool(send_file.get("sendPresentedFiles"), True),
        "maxFiles": _int(send_file.get("maxFiles"), 4, 0, 20),
    }
    return cfg


def load_config(data_dir: Path) -> dict[str, Any]:
    path = config_file(data_dir)
    raw = jsonc_load(path, default={})
    if not isinstance(raw, dict):
        raw = {}
    # Older builds wrote config.json; accept it as a fallback.
    if not raw:
        legacy = Path(data_dir) / "config.json"
        legacy_raw = jsonc_load(legacy, default={})
        if isinstance(legacy_raw, dict):
            raw = legacy_raw
    return normalize(raw)


def load_raw_config(data_dir: Path) -> dict[str, Any]:
    path = config_file(data_dir)
    raw = jsonc_load(path, default={})
    return raw if isinstance(raw, dict) else {}


def save_config(data_dir: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a patch into the on-disk config and return the normalized result."""
    current = load_raw_config(data_dir)
    merged = deep_merge(current, patch or {})
    write_json(config_file(data_dir), merged)
    return normalize(merged)


def redacted(config: dict[str, Any]) -> dict[str, Any]:
    safe = json.loads(json.dumps(config, ensure_ascii=False))
    if safe.get("appSecret"):
        safe["appSecret"] = "********"
    return safe


# ── Presets ────────────────────────────────────────────────────────────────

def load_presets(data_dir: Path) -> list[dict[str, Any]]:
    path = presets_file(data_dir)
    raw = jsonc_load(path, default={})
    if not isinstance(raw, dict) or not raw.get("presets"):
        write_json(path, DEFAULT_PRESETS)
        raw = DEFAULT_PRESETS
    presets = []
    for item in raw.get("presets") or []:
        if not isinstance(item, dict):
            continue
        preset_id = str(item.get("id") or "").strip()
        if not preset_id:
            continue
        presets.append(
            {
                "id": preset_id,
                "title": str(item.get("title") or preset_id),
                "mode": str(item.get("mode") or "").strip(),
                "tools": [str(tool).strip() for tool in (item.get("tools") or []) if str(tool).strip()],
                "prompt": str(item.get("prompt") or ""),
            }
        )
    return presets


def find_preset(data_dir: Path, preset_id: str) -> dict[str, Any] | None:
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        return None
    for preset in load_presets(data_dir):
        if preset["id"] == preset_id:
            return preset
    return None


# ── Session identity / prompts ─────────────────────────────────────────────

_SAFE_AGENT = re.compile(r"[^a-z0-9_]+")


def session_key(app_id: str, scope: str, peer_id: str) -> str:
    return f"qqbot:{app_id}:{scope}:{peer_id}"


def agent_name(key: str, generation: int = 0) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    name = f"qq_{digest}"
    if generation:
        name += f"_g{generation}"
    return _SAFE_AGENT.sub("_", name.lower())


def scope_prompt(config: dict[str, Any], scope: str) -> str:
    return str(config.get("groupPrompt") if scope == "group" else config.get("directPrompt") or "").strip()


def plugin_skill_body() -> str:
    """Return the plugin skill text used as request-local context.

    The upstream plugin injects a QQ-specific prompt through the DSH system
    prompt.  LamTools has no system-prompt waterfall for child sessions, so the
    equivalent text is passed as ``late_context`` on every run.
    """
    path = Path(__file__).resolve().parent.parent / "skills" / "qq-bot" / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    # Drop YAML frontmatter; the body is what the model needs.
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    return text.strip()


def build_late_context(config: dict[str, Any], scope: str, *, include_scope_prompt: bool = True) -> str:
    parts = [
        "你在 QQ 里和用户对话。回复会直接发到 QQ，所以不要假设用户能看到 LamTools 的界面。",
        "需要发文件时用 qqbot_send_file；需要看图片时用 qqbot_describe_image。",
        "群聊里会有多个人说话；只回复当前这条消息，不要把历史里其他人的话当成当前指令。",
    ]
    if include_scope_prompt:
        extra = scope_prompt(config, scope)
        if extra:
            parts.append(extra)
    skill = plugin_skill_body()
    if skill:
        parts.append(skill)
    return "\n\n".join(parts)


__all__ = [
    "DEFAULTS",
    "DEFAULT_PRESETS",
    "config_file",
    "presets_file",
    "deep_merge",
    "normalize",
    "load_config",
    "load_raw_config",
    "save_config",
    "redacted",
    "load_presets",
    "find_preset",
    "session_key",
    "agent_name",
    "scope_prompt",
    "build_late_context",
]

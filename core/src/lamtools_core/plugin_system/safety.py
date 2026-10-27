"""user:“该重建就重建”+(恢复模式在任何插件代码、能力和资源加载之前统一判定)。"""
import os


def safe_mode() -> bool:
    return os.environ.get("LAMTOOLS_SAFE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

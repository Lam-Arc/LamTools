"""引擎适配器注册表。

user:“新增搜索引擎原则上只需新增适配器，不修改 Agent 接口和通用清洗模块”+
(注册表是唯一入口：加一个类、在这里登记一行，其它层不用动)。
"""

from __future__ import annotations

from .base import EngineAdapter, normalize_freshness
from .baidu import BaiduAdapter
from .bing import BingAdapter
from .google import GoogleAdapter

_ADAPTERS: dict[str, EngineAdapter] = {
    "google": GoogleAdapter(),
    "bing": BingAdapter(),
    "baidu": BaiduAdapter(),
}

# `auto` 的顺序：先 Bing（默认引擎、对中文长句最稳），再百度（中文覆盖最好），最后 Google。
# 顺序是有代价的决定：单个引擎失败会自动尝试下一个，但不会把三个都翻一遍（省时间与请求量）。
AUTO_ORDER: tuple[str, ...] = ("bing", "baidu", "google")

SUPPORTED = tuple(_ADAPTERS)


def get(name: str) -> EngineAdapter:
    key = str(name or "").strip().lower()
    if key in {"", "auto"}:
        raise ValueError("auto 不是具体引擎，请用 resolve()")
    adapter = _ADAPTERS.get(key)
    if adapter is None:
        raise ValueError(f"不支持的搜索引擎：{name}（可选：auto/{'/'.join(SUPPORTED)}）")
    return adapter


def resolve(name: str) -> list[EngineAdapter]:
    """把 engine 参数展开成尝试顺序。"""
    key = str(name or "auto").strip().lower()
    if key in {"", "auto"}:
        return [_ADAPTERS[item] for item in AUTO_ORDER]
    return [get(key)]


def detect(url: str) -> EngineAdapter | None:
    """按 URL 反查引擎（打开结果后仍知道它来自哪个引擎）。"""
    for adapter in _ADAPTERS.values():
        if adapter.detect_page(url):
            return adapter
    return None


__all__ = ["AUTO_ORDER", "SUPPORTED", "EngineAdapter", "detect", "get", "normalize_freshness", "resolve"]

"""user:“目前市场就提供一个 QQ robot 和哔哩哔哩那个插件”+(固定官方目录、独立 GitHub 发布、宿主校验安装身份)。"""
from __future__ import annotations

import asyncio
import json
import re
import httpx
from pathlib import Path
from urllib.parse import urlsplit

from lamtools_core.distribution import get_json
from lamtools_core.update.checker import compare_versions

REPOSITORY = "Lam-Arc/Sunday-Plugins"
CATALOG_URL = f"https://github.com/{REPOSITORY}/releases/latest/download/catalog.json"
DESCRIPTIONS = {
    "qq-bot": {"title": "QQ robot", "category": "消息与协作", "description": "把 Sunday 接入 QQ 私聊与群聊，保留会话、审批续跑与文件投递。", "capabilities": ["QQ 私聊与群聊", "持久会话", "审批与文件投递"]},
    "bili-scroll": {"title": "刷B站", "category": "内容与信息", "description": "读取视频字幕、整理值得看的内容，生成日报并发送提醒。", "capabilities": ["视频与字幕检索", "每日内容简报", "消息提醒"]},
}


def validate_catalog(data):
    if data.get("format") != 1 or not isinstance(data.get("plugins"), list):
        raise ValueError("插件市场目录格式无效")
    seen = set()
    for row in data["plugins"]:
        if not isinstance(row, dict) or row.get("id") not in DESCRIPTIONS or row["id"] in seen:
            raise ValueError("插件市场包含未知或重复插件")
        seen.add(row["id"])
        parsed = urlsplit(str(row.get("url") or ""))
        if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.startswith(f"/{REPOSITORY}/releases/download/") or not parsed.path.endswith(".zip"):
            raise ValueError("插件安装包必须来自官方插件 GitHub Release")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256") or "")) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", str(row.get("version") or "")):
            raise ValueError("插件版本或摘要无效")
    return data


def load_catalog():
    # user:“从 GitHub 等平台下载并安装”+(API 资产入口避免依赖 github.com 主站连通性，仍以同一发布包摘要校验)。
    try:
        release = get_json(f"https://api.github.com/repos/{REPOSITORY}/releases/latest")
        assets = {row["name"]: row for row in release.get("assets", [])}
        catalog_asset = assets["catalog.json"]
        catalog = validate_catalog(get_json(catalog_asset["url"], headers={"Accept": "application/octet-stream"}))
        for row in catalog["plugins"]:
            asset = assets.get(row["url"].rsplit("/", 1)[-1], {})
            api_url = str(asset.get("url") or "")
            if api_url.startswith(f"https://api.github.com/repos/{REPOSITORY}/releases/assets/"):
                row["api_url"] = api_url
        return catalog
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        return validate_catalog(get_json(CATALOG_URL))


async def list_market(host):
    error = ""
    source = "github"
    cache = Path(host.state.path).parent / "plugin-market-cache.json"
    try:
        data = await asyncio.to_thread(load_catalog)
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(cache)
    except Exception as exc:
        error = str(exc)
        source = "cache"
        try:
            data = validate_catalog(json.loads(cache.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            data = {"plugins": []}
    releases = {row["id"]: row for row in data["plugins"]}
    items = []
    for name, description in DESCRIPTIONS.items():
        installed = host.get(name)
        release = releases.get(name, {})
        version = release.get("version", "")
        items.append({**description, "id": name, "version": version, "installed_version": installed.version if installed else "",
                      "update_available": bool(installed and version and compare_versions(version, installed.version) > 0),
                      "installable": bool(release), "repository_url": f"https://github.com/{REPOSITORY}",
                      "release_url": f"https://github.com/{REPOSITORY}/releases/latest", "source": "GitHub"})
    return {"plugins": items, "source": source, "error": error}


async def install_market_plugin(host, name):
    from .management import install_or_update
    if name not in DESCRIPTIONS:
        raise ValueError("市场未收录此插件")
    # Each action reloads the authoritative catalog; renderer-supplied URLs,
    # versions and checksums are never trusted.
    data = await asyncio.to_thread(load_catalog)
    row = next((row for row in data["plugins"] if row["id"] == name), None)
    if row is None:
        raise ValueError("暂时无法获取该插件的发布包，请刷新后重试")
    return await install_or_update(host, {"source": "url", "url": row.get("api_url") or row["url"], "fallback_url": row["url"] if row.get("api_url") else "", "sha256": row["sha256"],
                                         "expected_name": name, "expected_version": row["version"]}, update=host.get(name) is not None)


def register_market_operations(catalog, host):
    from lamtools_core.app import OperationResult
    async def listing(request):
        return OperationResult(name=request.name, payload=await list_market(host))
    async def install(request):
        try:
            result = await install_market_plugin(host, str(request.payload.get("name") or ""))
            return OperationResult(name=request.name, payload=result)
        except Exception as exc:
            return OperationResult(name=request.name, status="error", payload={"error": str(exc)})
    catalog.register("plugin.market.list", listing, owner="plugin-system")
    catalog.register("plugin.market.install", install, owner="plugin-system")

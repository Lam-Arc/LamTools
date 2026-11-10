"""素材入库：把项目里真会复用的东西按「用法 + 三问法标签」登记进资料库。

user:“让现有库通过添加一部分能力，能够实现对素材的收纳、整理与再利用”
+(库里的素材必须能被人话检索、自带用法、用完能回写；这里提供一次可重复执行的
播种：清单写在项目里，entry 必须在文件里真实存在才写入，否则宁可不入库)。

清单是一份 JSON，形状如下：

    {
      "aliases": {"@": "core/ui/src"},
      "assets": [
        {
          "file": "core/ui/src/styles/optical-glass.css",
          "name": "光学玻璃材质",
          "folder": "样式/材质",
          "tags": ["material", "glass", "low-trans", "surface"],
          "rating": 5,
          "usage": {
            "entry": ".optical-glass--low-trans",
            "requires": "--theme-main-solid / --optical-glass-tint，父级需要有可透的背景",
            "example": "<div class=\\"optical-glass optical-glass--low-trans\\"></div>"
          }
        }
      ],
      "retag": [
        {"file": "core/ui/src/styles/base.css", "tags": ["foundation", "reset", "typography"]}
      ]
    }

`assets` 是「带用法的新素材」，`retag` 是「已经在库里的文件，把标签换成人的说法」。
素材的标签取并集、评分/层级/用法只在缺失时写入（除非显式 overwrite）；
retag 是整组替换，因为要清掉的正是从类名切出来的 head/row/label。
"""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any

SEED_MANIFEST_VERSION = 1

_CLASS_TOKEN = re.compile(r"\.([A-Za-z_][\w-]*)")
_ID_TOKEN = re.compile(r"#([A-Za-z_][\w-]*)")
_IMPORT_SPECIFIER = re.compile(r"""from\s+['"]([^'"]+)['"]|import\s+['"]([^'"]+)['"]""")


class SeedError(ValueError):
    """清单本身不成立（不是某一条素材的问题）。"""


def load_manifest(path: Path) -> dict[str, Any]:
    """读清单并做结构校验；结构不对就整体失败，不猜。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SeedError(f"读不到清单：{path}（{exc}）") from exc
    except ValueError as exc:
        raise SeedError(f"清单不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise SeedError("清单根节点必须是对象")
    version = payload.get("version", SEED_MANIFEST_VERSION)
    if int(version) != SEED_MANIFEST_VERSION:
        raise SeedError(f"不认识的清单版本：{version}")
    assets = payload.get("assets") or []
    retag = payload.get("retag") or []
    aliases = payload.get("aliases") or {}
    if not isinstance(assets, list) or not isinstance(retag, list) or not isinstance(aliases, dict):
        raise SeedError("assets / retag 必须是数组，aliases 必须是对象")
    for item in [*assets, *retag]:
        if not isinstance(item, dict):
            raise SeedError("assets / retag 的每一项必须是对象")
    return {
        "assets": assets,
        "retag": retag,
        "aliases": {str(key): str(value) for key, value in aliases.items()},
    }


def _resolve_inside(root: Path, raw: str) -> Path:
    """把清单里的工作区相对路径落到真实文件；越界直接拒绝。"""
    value = str(raw or "").strip().replace("\\", "/")
    if value.startswith("workspace://"):
        value = value[len("workspace://"):]
    if not value:
        raise ValueError("file 为空")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"路径越出工作区：{raw}") from exc
    return candidate


def _resolve_specifier(specifier: str, *, from_file: Path, root: Path, aliases: dict[str, str]) -> Path | None:
    """把 import 的模块路径落成工作区里的文件；外部包返回 None（无从校验）。"""
    if specifier.startswith("."):
        return (from_file.parent / specifier).resolve()
    for prefix, target in aliases.items():
        if specifier == prefix or specifier.startswith(f"{prefix}/"):
            rest = specifier[len(prefix):].lstrip("/")
            return (root / target / rest).resolve()
    return None


def _verify_entry(path: Path, entry: str, *, root: Path, aliases: dict[str, str]) -> list[str]:
    """entry 必须是「文件里真实存在的类名」或「能落到真实文件的 import」。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if entry.startswith("import "):
        match = _IMPORT_SPECIFIER.search(entry)
        specifier = (match.group(1) or match.group(2)) if match else ""
        if not specifier:
            return [f"entry 的 import 语句没有可识别的模块路径：{entry}"]
        target = _resolve_specifier(specifier, from_file=path, root=root, aliases=aliases)
        if target is None:
            return []
        if not target.is_file():
            return [f"entry 指向的文件不存在：{specifier}"]
        return []
    # 设计令牌也是取用的抓手：--radius 这类变量必须在这份文件里真的定义过。
    if entry.startswith("--"):
        names = [name for name in re.findall(r"--[A-Za-z0-9_-]+", entry) if name]
        missing = [name for name in names if f"{name}:" not in text]
        if not names:
            return [f"entry 没有可识别的令牌名：{entry}"]
        if missing:
            return [f"entry 在 {path.name} 里找不到：{', '.join(missing)}"]
        return []
    classes = _CLASS_TOKEN.findall(entry)
    ids = _ID_TOKEN.findall(entry)
    if not classes and not ids:
        return [f"entry 既不是类名、令牌也不是 import：{entry}"]
    missing = [f".{name}" for name in classes if f".{name}" not in text]
    missing += [f"#{name}" for name in ids if f"#{name}" not in text]
    if missing:
        return [f"entry 在 {path.name} 里找不到：{', '.join(missing)}"]
    return []


def verify_asset(root: Path, asset: dict[str, Any], aliases: dict[str, str]) -> tuple[Path | None, list[str]]:
    """校验一份素材；返回（落点，问题列表）。问题为空才允许入库。"""
    raw = str(asset.get("file") or "").strip()
    try:
        path = _resolve_inside(root, raw)
    except ValueError as exc:
        return None, [str(exc)]
    if not path.is_file():
        return None, [f"文件不存在：{raw}"]
    problems: list[str] = []
    if not str(asset.get("name") or "").strip():
        problems.append("name 为空")
    tags = asset.get("tags")
    if not isinstance(tags, list) or not [str(tag).strip() for tag in tags]:
        problems.append("tags 至少要有一个词")
    rating = asset.get("rating", 0)
    if not isinstance(rating, int) or not 0 <= rating <= 5:
        problems.append("rating 必须是 0 到 5 的整数")
    usage = asset.get("usage")
    if not isinstance(usage, dict) or not str(usage.get("entry") or "").strip():
        problems.append("usage.entry 缺失（没有 entry 的素材不算取用素材）")
    else:
        problems.extend(_verify_entry(path, str(usage["entry"]).strip(), root=root, aliases=aliases))
    return path, problems


async def _file_asset(
    store: Any,
    *,
    project_id: str,
    root: Path,
    path: Path,
    manifest_path: Path,
    name: str = "",
) -> Any:
    """登记（或刷新）一份素材文件；不复活已从资料库移除的条目。"""
    relative = path.relative_to(root).as_posix()
    return await store.register(
        project_id=project_id,
        work_root=root,
        path=f"workspace://{relative}",
        kind="file_change",
        mime_type=mimetypes.guess_type(path.name)[0] or "",
        name=name,
        source="agent_generated",
        role="deliverable",
        provenance={"registered_by": "library_seed", "manifest": str(manifest_path)},
        reactivate=False,
    )


async def seed_library(
    store: Any,
    *,
    project_id: str,
    work_root: str | Path,
    manifest_path: str | Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """按清单播种：带用法的素材入库，其余文件重打标签。返回一份可读的报告。"""
    root = Path(work_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    manifest = load_manifest(manifest_file)
    report: dict[str, Any] = {
        "project_id": project_id,
        "manifest": str(manifest_file),
        "assets": [],
        "retagged": [],
        "skipped": [],
        "failed": [],
    }

    for asset in manifest["assets"]:
        raw = str(asset.get("file") or "").strip()
        path, problems = verify_asset(root, asset, manifest["aliases"])
        if path is None or problems:
            report["failed"].append({"file": raw, "problems": problems or ["无法定位文件"]})
            continue
        record = await _file_asset(
            store,
            project_id=project_id,
            root=root,
            path=path,
            manifest_path=manifest_file,
            name=str(asset.get("name") or "").strip(),
        )
        if record.deleted:
            report["skipped"].append({"file": raw, "reason": "已从资料库移除"})
            continue
        changed: list[str] = []
        tags = [str(tag) for tag in asset.get("tags") or []]
        merged = list(dict.fromkeys([*(record.tags or []), *tags]))
        if merged != list(record.tags or []):
            record = await store.set_tags(record.artifact_id, merged)
            changed.append("tags")
        folder = str(asset.get("folder") or "").strip()
        if folder and (overwrite or not record.folder):
            record = await store.set_folder(record.artifact_id, folder)
            changed.append("folder")
        rating = int(asset.get("rating") or 0)
        if rating and (overwrite or not record.rating):
            record = await store.set_rating(record.artifact_id, rating)
            changed.append("rating")
        usage = asset.get("usage") if isinstance(asset.get("usage"), dict) else {}
        if usage and (overwrite or not record.usage):
            record = await store.set_usage(record.artifact_id, usage)
            changed.append("usage")
        report["assets"].append({
            "artifact_id": record.artifact_id,
            "file": raw,
            "name": record.name,
            "tags": record.tags,
            "rating": record.rating,
            "entry": (record.usage or {}).get("entry", ""),
            "changed": changed,
        })

    for item in manifest["retag"]:
        raw = str(item.get("file") or "").strip()
        tags = [str(tag) for tag in item.get("tags") or [] if str(tag).strip()]
        try:
            path = _resolve_inside(root, raw)
        except ValueError as exc:
            report["failed"].append({"file": raw, "problems": [str(exc)]})
            continue
        if not path.is_file():
            report["failed"].append({"file": raw, "problems": ["文件不存在"]})
            continue
        if not tags:
            report["failed"].append({"file": raw, "problems": ["tags 至少要有一个词"]})
            continue
        record = await _file_asset(store, project_id=project_id, root=root, path=path, manifest_path=manifest_file)
        if record.deleted:
            report["skipped"].append({"file": raw, "reason": "已从资料库移除"})
            continue
        # 重打是「换掉」，不是「再加」：从类名切出来的 head/row/label 必须消失。
        if list(record.tags or []) != tags:
            record = await store.set_tags(record.artifact_id, tags)
        report["retagged"].append({
            "artifact_id": record.artifact_id,
            "file": raw,
            "tags": record.tags,
        })

    return report


__all__ = [
    "SEED_MANIFEST_VERSION",
    "SeedError",
    "load_manifest",
    "seed_library",
    "verify_asset",
]

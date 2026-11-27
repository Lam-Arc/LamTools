"""方案 library — plans are markdown files in the project's 「方案/」 folder.

One plan is one document: a small frontmatter (状态 / 摘要 / 收藏) over the
body sections (需求与边界、取舍、步骤、目标与完成判据、风险、未答问题). The
agent drafts and edits these files with its ordinary file tools while it talks
to the user; this module reads the folder and provides the library's file
operations (create / folder / rename / move / favorite) so the UI, the CLI and
the agent all work on the same plain files.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

#: The designated folder inside every project workspace.
PLAN_LIBRARY_DIRNAME = "方案"

#: Frontmatter values seen in the wild, mapped onto the four library states.
_STATUS_ALIASES = {
    "草稿": "draft",
    "draft": "draft",
    "就绪": "ready",
    "ready": "ready",
    "执行中": "executing",
    "executing": "executing",
    "完成": "done",
    "done": "done",
}

#: The plan-type vocabulary（PRD §3）：一级分类 + 扩展分类。
#: user:“统一方案分类与编写规范”+(类型是第一级元数据；扩展类型不必进 UI 一级入口)。
PLAN_TYPES: dict[str, str] = {
    "PRD": "产品需求文档",
    "SPEC": "技术规范",
    "DESIGN": "设计方案",
    "RESEARCH": "调研方案",
    "EXP": "实验方案",
    "PLAN": "实施方案",
    "AUDIT": "审查方案",
    "REPORT": "结果报告",
    "ARCH": "架构设计",
    "ADR": "架构决策记录",
    "RFC": "提案与讨论",
    "POC": "概念验证",
    "TEST": "测试方案",
    "MIG": "迁移方案",
    "SOP": "标准操作流程",
    "RCA": "根因分析",
}

#: 一级分类：方案首页的类型筛选先用这一组。
PRIMARY_PLAN_TYPES: tuple[str, ...] = (
    "PRD",
    "SPEC",
    "DESIGN",
    "RESEARCH",
    "EXP",
    "PLAN",
    "AUDIT",
    "REPORT",
)

#: 扩展类型归到哪个一级分类的骨架（见 PRD §3.2 的建议归属）。
_EXTENDED_BASE = {
    "ARCH": "SPEC",
    "ADR": "SPEC",
    "RFC": "DESIGN",
    "POC": "EXP",
    "TEST": "PLAN",
    "MIG": "PLAN",
    "SOP": "PLAN",
    "RCA": "AUDIT",
}

#: 每类方案的核心内容（PRD §4）：写进新建骨架当提示，不当作强制章节。
_TYPE_SECTIONS: dict[str, tuple[str, ...]] = {
    "PRD": ("背景与问题", "目标与范围", "需求", "约束与假设", "验收标准"),
    "SPEC": ("设计目标", "机制", "接口与行为", "边界条件", "验证方式"),
    "DESIGN": ("设计目标", "使用场景", "交互流程", "视觉与体验要求", "验收标准"),
    "RESEARCH": ("调研目标", "调查范围", "事实依据", "发现", "结论"),
    "EXP": ("实验目标", "假设", "变量与指标", "实验方法", "停止条件"),
    "PLAN": ("目标与现状", "实施步骤", "依赖", "验收要求"),
    "AUDIT": ("审查目标", "审查范围", "问题与证据", "影响", "改进建议"),
    "REPORT": ("实际成果", "验证证据", "结论", "差异", "遗留问题"),
}

_TYPE_CODE_BY_LABEL = {label: code for code, label in PLAN_TYPES.items()}

#: 文件名里显式写出的英文类型代码（PRD / SPEC / EXP …）。
_TYPE_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])(" + "|".join(PLAN_TYPES) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

#: 文件名/标题里的中文角色词，按优先级排列：先认角色（报告、审查、计划），
#: 再认领域词（设计、架构、规范），避免「架构与实施计划」被写成架构设计。
_TYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AUDIT", ("审计", "审查")),
    ("RCA", ("根因",)),
    ("REPORT", ("验收报告", "实施报告", "验证报告", "复核报告", "结果报告", "报告")),
    ("ADR", ("架构决策", "决策记录")),
    ("PLAN", ("实施计划", "实施方案", "实施安排", "改造计划", "迁移计划")),
    ("TEST", ("测试方案", "测试计划")),
    ("DESIGN", ("设计方案", "设计说明", "界面设计", "交互设计", "视觉设计")),
    ("ARCH", ("架构",)),
    ("SPEC", ("技术规范", "接口规范", "协议规范", "规范")),
    ("EXP", ("实验", "概念验证")),
    ("RESEARCH", ("调研", "调查", "现状复核", "可行性")),
    ("MIG", ("迁移",)),
    ("SOP", ("操作流程", "标准作业")),
    ("RFC", ("提案", "讨论稿")),
)

#: 设计状态（PRD §8.1）与实施状态（§8.2）是两条独立的轴。
_DESIGN_ALIASES = {
    "草案": "draft",
    "草稿": "draft",
    "draft": "draft",
    "生效": "active",
    "就绪": "active",
    "ready": "active",
    "active": "active",
    "执行中": "active",
    "executing": "active",
    "完成": "active",
    "done": "active",
    "已归档": "archived",
    "归档": "archived",
    "archived": "archived",
    "已废弃": "deprecated",
    "废弃": "deprecated",
    "deprecated": "deprecated",
}

_IMPL_ALIASES = {
    "未实施": "none",
    "未开始": "none",
    "none": "none",
    "实施中": "doing",
    "执行中": "doing",
    "doing": "doing",
    "executing": "doing",
    "待验收": "review",
    "review": "review",
    "已验收": "accepted",
    "accepted": "accepted",
    "完成": "accepted",
    "done": "accepted",
}

#: 旧文档没有 `实施` 字段时，从旧状态词推断实施轴。
_LEGACY_IMPL = {"执行中": "doing", "executing": "doing", "完成": "accepted", "done": "accepted"}

#: 写回 frontmatter 时用用户读得懂的中文词；「就绪」保持旧写法，
#: 既有技能与历史文档不必因为一次元数据编辑而改术语。
_DESIGN_WRITE = {"draft": "草稿", "active": "就绪", "archived": "已归档", "deprecated": "已废弃"}
_IMPL_WRITE = {"none": "未实施", "doing": "实施中", "review": "待验收", "accepted": "已验收"}

#: Frontmatter values meaning "this plan is starred".
_FAVORITE_TRUTHY = {"true", "yes", "1", "是", "y", "on"}

_PLAN_SKELETON = """---
状态: 草稿
摘要:
---

# {title}

（在这里写下方案内容。就绪后对助手说「可以开工了」。）
"""


def _skeleton_for(plan_type: str, title: str) -> str:
    """新建文档的骨架：有类型时按该类型的核心内容（PRD §4）铺一节提示。

    user:“不同类型的方案应具有各自的核心内容要求，而非共用一套僵化模板”+
    (骨架只给读者列提纲，正文仍由 Agent 按复杂度自行决定篇幅与结构)。
    扩展类型沿用其建议归属的一级分类骨架。
    """
    base = _EXTENDED_BASE.get(plan_type, plan_type)
    sections = _TYPE_SECTIONS.get(base)
    if not sections:
        return _PLAN_SKELETON.format(title=title)
    lines = [
        "---",
        f"类型: {plan_type}",
        "状态: 草稿",
        "摘要:",
        "---",
        "",
        f"# {title}",
        "",
        "（按需要增删下面的小节；目标、边界与验收标准写清楚后，再把状态改成「就绪」。）",
        "",
    ]
    for section in sections:
        lines.extend([f"## {section}", "", "（待写）", ""])
    return "\n".join(lines)


class PlanLibraryError(ValueError):
    """A library file operation cannot be performed safely."""


def normalize_plan_type(raw: str | None) -> str:
    """A frontmatter 类型 (code or Chinese label) as a plan-type code; unknown → ''."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return ""
    if cleaned.upper() in PLAN_TYPES:
        return cleaned.upper()
    return _TYPE_CODE_BY_LABEL.get(cleaned, "")


def plan_type_label(code: str | None) -> str:
    """The Chinese name shown in the library; an unclassified plan says so."""
    return PLAN_TYPES.get((code or "").strip().upper(), "未分类")


def _infer_plan_type(*texts: str) -> str:
    """Guess a plan's type from its filename and title (frontmatter stays authoritative).

    user:“识别现有方案的类型与专题”“保留无法自动判断的历史方案”+(读侧推断，
    不写回文件；推断不出就留空，由用户或 Agent 后续整理)。
    """
    for text in texts:
        if not text:
            continue
        match = _TYPE_CODE_RE.search(text)
        if match:
            return match.group(1).upper()
    for text in texts:
        if not text:
            continue
        for code, keywords in _TYPE_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return code
    return ""


_DESIGN_LABELS = {"draft": "草案", "active": "生效", "archived": "已归档", "deprecated": "已废弃"}
_IMPL_LABELS = {"none": "未实施", "doing": "实施中", "review": "待验收", "accepted": "已验收"}


def design_status_label(code: str | None) -> str:
    """The Chinese name of a design status, for reports and API consumers."""
    return _DESIGN_LABELS.get((code or "").strip().lower(), "草案")


def impl_status_label(code: str | None) -> str:
    """The Chinese name of an implementation status."""
    return _IMPL_LABELS.get((code or "").strip().lower(), "未实施")


def normalize_design_status(raw: str | None) -> str:
    """Design status (PRD §8.1); unknown values read as a draft."""
    return _DESIGN_ALIASES.get((raw or "").strip().lower(), "draft")


def normalize_impl_status(raw: str | None) -> str:
    """Implementation status (PRD §8.2); unknown values read as 未实施."""
    return _IMPL_ALIASES.get((raw or "").strip().lower(), "none")


def _read_statuses(fields: dict[str, str]) -> tuple[str, str]:
    """设计状态与实施状态两条轴：旧文档的单一 状态 也能拆成两条。

    user:“方案设计状态与实施状态相互独立”+(历史文档只写了一个 状态，
    读的时候按旧词推断实施轴，不改文件)。
    """
    raw_status = (fields.get("状态") or fields.get("status") or "").strip()
    key = raw_status.lower()
    design = _DESIGN_ALIASES.get(key, "draft")
    raw_impl = (fields.get("实施") or fields.get("impl") or "").strip()
    impl = _IMPL_ALIASES.get(raw_impl.lower(), "none") if raw_impl else _LEGACY_IMPL.get(key, "none")
    return design, impl


def _derive_status(design_status: str, impl_status: str) -> str:
    """兼容旧客户端的综合状态：开工仍以 ready 为准。"""
    if design_status in {"draft", "archived", "deprecated"}:
        return design_status
    if impl_status in {"doing", "review"}:
        return "executing"
    if impl_status == "accepted":
        return "done"
    return "ready"


def _split_related(raw: str) -> list[str]:
    """Frontmatter 关联: comma / semicolon / newline separated, order kept."""
    return [part.strip() for part in re.split(r"[,，;；\n]", raw or "") if part.strip()]


def plan_library_root(work_root: str | Path) -> Path:
    return Path(work_root) / PLAN_LIBRARY_DIRNAME


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Simple ``key: value`` lines between the first two ``---`` lines.

    A document without frontmatter (or with an unterminated block) comes back
    with empty fields and the text intact — the body is still readable.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            fields: dict[str, str] = {}
            for line in lines[1:index]:
                key, sep, value = line.partition(":")
                if sep and key.strip():
                    fields[key.strip().lower()] = value.strip()
            return fields, "\n".join(lines[index + 1:])
    return {}, text


def _upsert_frontmatter_field(text: str, key: str, value: str | None) -> str:
    """Set ``key: value`` in the document's frontmatter; ``None`` removes it.

    Documents without a frontmatter block get one prepended when a value is
    set. The body is never touched.
    """
    lines = text.splitlines(keepends=True)
    if text.startswith("---"):
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                head, body = lines[: index + 1], lines[index + 1 :]
                kept = [line for line in head[1:-1] if not line.strip().lower().startswith(f"{key.lower()}:")]
                if value is not None:
                    kept.append(f"{key}: {value}\n")
                return "---\n" + "".join(kept) + "---\n" + "".join(body)
    if value is None:
        return text
    return f"---\n{key}: {value}\n---\n{text}"


def normalize_plan_status(raw: str | None) -> str:
    """A frontmatter 状态 value as the library's four states; unknown → draft."""
    return _STATUS_ALIASES.get((raw or "").strip().lower(), "draft")


def _clean_segment(name: str, *, kind: str = "名称") -> str:
    """Validate one on-disk path segment (a file or folder name)."""
    cleaned = (name or "").strip().strip(".")
    if not cleaned:
        raise PlanLibraryError(f"{kind}不能为空")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned or ":" in cleaned:
        raise PlanLibraryError(f"{kind}不能包含路径分隔符")
    if re.search(r'[*?"<>|\x00-\x1f]', cleaned):
        raise PlanLibraryError(f"{kind}含有不允许的字符")
    return cleaned


def _clean_relative_dir(relative: str, *, kind: str = "文件夹名称") -> str:
    """Validate a folder path inside 「方案/」, one or more segments deep.

    ``归档`` and ``归档/这一期`` are both fine; every segment is checked on its
    own so a nested path can never smuggle in a separator, ``..`` or a reserved
    character.
    """
    cleaned = (relative or "").strip().replace("\\", "/").strip("/")
    segments = [segment for segment in cleaned.split("/") if segment.strip()]
    if not segments:
        raise PlanLibraryError(f"{kind}不能为空")
    return "/".join(_clean_segment(segment, kind=kind) for segment in segments)


def _resolve_library_path(work_root: str | Path, relative: str) -> Path:
    """Resolve a library-relative path (``方案/...``), contained to the folder."""
    root = plan_library_root(work_root).resolve()
    cleaned = (relative or "").strip().replace("\\", "/").strip("/")
    if not cleaned:
        raise PlanLibraryError("路径不能为空")
    target = (Path(work_root).resolve() / cleaned).resolve()
    try:
        target.relative_to(root)
    except ValueError as cause:
        raise PlanLibraryError("路径越出了方案文件夹") from cause
    if target == root:
        raise PlanLibraryError("路径不能是方案文件夹本身")
    return target


def _entry_for(path: Path, work_root: str | Path) -> dict[str, Any]:
    library_root = plan_library_root(work_root).resolve()
    stat = path.stat()
    title = path.stem
    summary = ""
    favorite = False
    plan_type = ""
    design_status = "draft"
    impl_status = "none"
    topic = ""
    related: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError):
        text = ""
    if text:
        fields, body = _parse_frontmatter(text)
        design_status, impl_status = _read_statuses(fields)
        summary = fields.get("摘要") or fields.get("summary") or ""
        favorite = fields.get("收藏", "").strip().lower() in _FAVORITE_TRUTHY
        title = _plan_title(body, path.name)
        topic = fields.get("专题") or fields.get("topic") or ""
        related = _split_related(fields.get("关联") or fields.get("related") or "")
        plan_type = normalize_plan_type(fields.get("类型") or fields.get("type"))
    if not plan_type:
        # 历史文档没有 类型 字段：按文件名/标题推断，仅用于读侧展示。
        plan_type = _infer_plan_type(path.name, title)
    folder = path.parent.resolve().relative_to(library_root).as_posix()
    return {
        "name": path.name,
        "path": f"{PLAN_LIBRARY_DIRNAME}/{folder}/{path.name}" if folder != "." else f"{PLAN_LIBRARY_DIRNAME}/{path.name}",
        "folder": "" if folder == "." else folder,
        "title": title,
        "type": plan_type,
        "type_label": plan_type_label(plan_type),
        "status": _derive_status(design_status, impl_status),
        "design_status": design_status,
        "impl_status": impl_status,
        "topic": topic,
        "related": related,
        "summary": summary,
        "favorite": favorite,
        "size": stat.st_size,
        "updated_at": int(stat.st_mtime),
    }


def _plan_title(body: str, filename: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return filename.removesuffix(".md")


def scan_plan_library(work_root: str | Path) -> list[dict[str, Any]]:
    """Every markdown file in 「方案/」 (recursively), newest first.

    A file that cannot be read degrades to a title-only draft entry rather than
    hiding from the list — the library shows what is on disk. ``folder`` is the
    file's directory inside 「方案/」 (empty for the top level).
    """
    root = plan_library_root(work_root)
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            entries.append(_entry_for(path, work_root))
        except (OSError, ValueError):
            continue  # a file vanishing or escaping mid-scan must not break the list
    entries.sort(key=lambda entry: (entry["updated_at"], entry["name"]), reverse=True)
    return entries


def _folder_entry(path: Path, work_root: str | Path) -> dict[str, Any]:
    """One folder as the library reports it, with its depth in 「方案/」."""
    library_root = plan_library_root(work_root).resolve()
    relative = path.resolve().relative_to(library_root).as_posix()
    count = sum(1 for _ in path.rglob("*.md"))
    return {
        "name": path.name,
        "path": f"{PLAN_LIBRARY_DIRNAME}/{relative}",
        # 与 entry.folder 同一口径：库内相对目录，根为 ""。
        "dir": relative,
        "parent": relative.rsplit("/", 1)[0] if "/" in relative else "",
        "count": count,
    }


def list_plan_folders(work_root: str | Path) -> list[dict[str, Any]]:
    """Every folder inside 「方案/」 at any depth, sorted by path.

    The flat list carries each folder's own ``dir`` and ``parent`` so any
    consumer can render one level at a time without a second round trip.
    """
    root = plan_library_root(work_root)
    if not root.is_dir():
        return []
    folders: list[dict[str, Any]] = []
    for current, dirnames, _ in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for name in dirnames:
            folders.append(_folder_entry(Path(current) / name, work_root))
    folders.sort(key=lambda folder: folder["dir"])
    return folders


def _resolve_folder(work_root: str | Path, folder: str, *, must_exist: bool = True) -> Path:
    """Resolve a (possibly nested) folder inside 「方案/」, refusing escapes."""
    relative = _clean_relative_dir(folder)
    target = _resolve_library_path(work_root, f"{PLAN_LIBRARY_DIRNAME}/{relative}")
    if must_exist and not target.is_dir():
        raise PlanLibraryError("目标文件夹不存在")
    return target


def create_plan(
    work_root: str | Path,
    name: str,
    *,
    folder: str = "",
    plan_type: str = "",
    topic: str = "",
) -> dict[str, Any]:
    """Create one skeleton plan document; refuses to overwrite.

    user:“用户创建一个简单方案：无需填写大量字段或经过复杂流程”+(类型与专题
    都可以不填；填了类型才按该类型的核心内容铺骨架)。
    """
    code = normalize_plan_type(plan_type) if plan_type else ""
    if plan_type and not code:
        raise PlanLibraryError("未知的方案类型")
    cleaned = _clean_segment(name, kind="方案名称")
    stem = cleaned if cleaned.lower().endswith(".md") else f"{cleaned}.md"
    title = stem[:-3]
    if folder:
        # 文件夹可以是任意深度，但必须是已经在那儿的一层；先校验再动盘。
        target = _resolve_folder(work_root, folder) / stem
    else:
        target = plan_library_root(work_root) / stem
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise PlanLibraryError("同名方案已存在")
    text = _skeleton_for(code, title)
    if topic:
        text = _upsert_frontmatter_field(text, "专题", topic.strip())
    target.write_text(text, encoding="utf-8")
    return _entry_for(target, work_root)


def create_folder(work_root: str | Path, path: str) -> dict[str, Any]:
    """Create one folder inside 「方案/」; nested paths build one level deeper."""
    root = plan_library_root(work_root).resolve()
    target = _resolve_library_path(work_root, f"{PLAN_LIBRARY_DIRNAME}/{_clean_relative_dir(path)}")
    if target.exists():
        raise PlanLibraryError("同名文件夹已存在")
    if target.parent == root:
        root.mkdir(parents=True, exist_ok=True)  # 「方案/」随第一次建夹产生
    elif not target.parent.is_dir():
        raise PlanLibraryError("上级文件夹不存在")
    target.mkdir()
    return _folder_entry(target, work_root)


def delete_folder(work_root: str | Path, path: str) -> dict[str, str]:
    """Delete one empty folder at any depth inside 「方案/」."""
    target = _resolve_library_path(work_root, path)
    if not target.is_dir():
        raise PlanLibraryError("文件夹不存在")
    if any(target.iterdir()):
        raise PlanLibraryError("文件夹不是空的，先移走或删除里面的内容")
    target.rmdir()
    return {"deleted": path}


def rename_plan(work_root: str | Path, path: str, new_name: str) -> dict[str, Any]:
    """Rename one plan document in place (same folder)."""
    target = _resolve_library_path(work_root, path)
    if not target.is_file() or target.suffix.lower() != ".md":
        raise PlanLibraryError("只有方案文档可以重命名")
    cleaned = _clean_segment(new_name, kind="方案名称")
    stem = cleaned if cleaned.lower().endswith(".md") else f"{cleaned}.md"
    renamed = target.with_name(stem)
    if renamed.exists():
        raise PlanLibraryError("同名方案已存在")
    renamed = renamed.resolve()
    renamed.relative_to(plan_library_root(work_root).resolve())
    target.rename(renamed)
    return _entry_for(renamed, work_root)


def move_plan(work_root: str | Path, path: str, folder: str = "") -> dict[str, Any]:
    """Move one plan document to the library root ('') or any existing folder."""
    target = _resolve_library_path(work_root, path)
    if not target.is_file() or target.suffix.lower() != ".md":
        raise PlanLibraryError("只有方案文档可以移动")
    destination_dir = _resolve_folder(work_root, folder) if folder else plan_library_root(work_root).resolve()
    destination = destination_dir / target.name
    if destination.exists():
        raise PlanLibraryError("目标文件夹里有同名方案")
    shutil.move(str(target), str(destination))
    return _entry_for(destination, work_root)


def set_plan_favorite(work_root: str | Path, path: str, *, favorite: bool) -> dict[str, Any]:
    """Star (or unstar) one plan by writing the 收藏 frontmatter field."""
    target = _resolve_library_path(work_root, path)
    if not target.is_file() or target.suffix.lower() != ".md":
        raise PlanLibraryError("只有方案文档可以收藏")
    text = target.read_text(encoding="utf-8")
    updated = _upsert_frontmatter_field(text, "收藏", "true" if favorite else None)
    if updated != text:
        target.write_text(updated, encoding="utf-8")
    return _entry_for(target, work_root)


def set_plan_meta(
    work_root: str | Path,
    path: str,
    *,
    plan_type: str | None = None,
    design_status: str | None = None,
    impl_status: str | None = None,
    topic: str | None = None,
    summary: str | None = None,
    related_sessions: list[str] | None = None,
) -> dict[str, Any]:
    """Edit one plan's frontmatter only — the body is never rewritten.

    user:“最小元数据”“优先复用现有 Library 元数据能力”“不建立复杂的方案对象
    模型”+(类型/专题/两条状态都落在同一份 Markdown 的 frontmatter 里；
    正文与其它未知字段原样保留，文件仍然是普通文档)。
    """
    target = _resolve_library_path(work_root, path)
    if not target.is_file() or target.suffix.lower() != ".md":
        raise PlanLibraryError("只有方案文档可以修改信息")
    text = target.read_text(encoding="utf-8")
    fields, _body = _parse_frontmatter(text)

    if plan_type is not None:
        if plan_type.strip():
            code = normalize_plan_type(plan_type)
            if not code:
                raise PlanLibraryError(f"未知的方案类型：{plan_type}")
            text = _upsert_frontmatter_field(text, "类型", code)
        else:
            text = _upsert_frontmatter_field(text, "类型", None)

    if design_status is not None:
        key = design_status.strip().lower()
        if key not in _DESIGN_ALIASES:
            raise PlanLibraryError(f"未知的设计状态：{design_status}")
        text = _upsert_frontmatter_field(text, "状态", _DESIGN_WRITE[_DESIGN_ALIASES[key]])

    if impl_status is not None:
        key = impl_status.strip().lower()
        if key not in _IMPL_ALIASES:
            raise PlanLibraryError(f"未知的实施状态：{impl_status}")
        text = _upsert_frontmatter_field(text, "实施", _IMPL_WRITE[_IMPL_ALIASES[key]])

    if topic is not None:
        text = _upsert_frontmatter_field(text, "专题", topic.strip() or None)
    if summary is not None:
        text = _upsert_frontmatter_field(text, "摘要", summary.strip() or None)

    if related_sessions:
        existing = _split_related(fields.get("关联") or fields.get("related") or "")
        for session_id in related_sessions:
            token = f"会话:{session_id.strip()}"
            if session_id.strip() and token not in existing:
                existing.append(token)
        text = _upsert_frontmatter_field(text, "关联", ", ".join(existing))

    target.write_text(text, encoding="utf-8")
    return _entry_for(target, work_root)


def import_plan(work_root: str | Path, source: str | Path, *, folder: str = "") -> dict[str, Any]:
    """Copy an existing markdown file into 「方案/」; the source stays untouched.

    user:“从现有文件导入方案”“不擅自删除历史文件”+(导入是复制，不是搬家；
    同名时自动加序号，绝不覆盖库里已有的方案)。
    """
    source_path = Path(source).expanduser()
    if not source_path.is_absolute():
        source_path = Path(work_root) / source_path
    if not source_path.is_file():
        raise PlanLibraryError("要导入的文件不存在")
    if source_path.suffix.lower() != ".md":
        raise PlanLibraryError("只支持导入 Markdown 文件（.md）")
    if source_path.stat().st_size > 2_000_000:
        raise PlanLibraryError("文件太大，不像一份方案文档")

    destination_dir = _resolve_folder(work_root, folder) if folder else plan_library_root(work_root)
    destination_dir.mkdir(parents=True, exist_ok=True)

    stem = re.sub(r'[*?"<>|\x00-\x1f/\\:]', "-", source_path.stem).strip().strip(".")
    if not stem:
        raise PlanLibraryError("文件名去掉非法字符后为空")
    candidate = destination_dir / f"{stem}.md"
    index = 2
    while candidate.exists():
        candidate = destination_dir / f"{stem} ({index}).md"
        index += 1
    shutil.copy2(source_path, candidate)
    return _entry_for(candidate, work_root)

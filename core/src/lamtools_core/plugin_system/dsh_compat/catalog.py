"""Pinned upstream inventory; candidate mappings are not working adapters.

user:“每一个地方 sunday 都有等价或者近似接口”+(完整记录逐项目标与缺口，后续逐项通过行为验收再升级兼容状态)。
"""

import json
from pathlib import Path


def load_surface() -> dict:
    return json.loads(Path(__file__).with_name("surface.json").read_text(encoding="utf-8"))


def render_matrix() -> str:
    catalog = load_surface()
    lines = [
        "# DSH → Sunday 宿主能力对照", "",
        'user:“每一个地方 sunday 都有等价或者近似接口”+(以固定上游版本逐项补齐，候选位置不代表已经兼容)。', "",
        f'上游提交：`{catalog["upstreamCommit"]}`。', "",
        "来源：[官方能力目录](" + catalog["source"] + ")。", "",
        "本表由 `python scripts/dsh_compat.py --matrix` 生成；修改同包 surface.json 后同步生成。", "",
        "candidate = 已找到可复用的 Sunday 位置，仍需公开契约、语义适配及验收；gap = 尚无已核实的等价公开接口。", "",
        "阶段 2：核心宿主；阶段 3：前端与 Remote；阶段 4：其余提供方、实验能力与真实插件。", "",
        "所有项目尚未获得 DSH 运行兼容认证。浏览器、React/Cordis 与 Python/Vue 的差异需显式处理。", "",
        "| DSH 服务 | 状态 | Sunday 候选 / 补齐方向 | 阶段 | 行为边界 |", "| --- | --- | --- | --- | --- |",
    ]
    for row in catalog["services"]:
        target = row["sunday"]
        evidence = ", ".join(f"[{p}](../{p})" for p in row["evidence"])
        lines.append(f'| `ctx.{row["dsh"]}` | {row["status"]} | {target}'
                     + (f"；{evidence}" if evidence else "")
                     + f' | {row["phase"]} | {row["boundary"]} |')
    lines += ["", "## 已验收的 Sunday 基础契约", ""]
    for name, contract in catalog.get("hostContracts", {}).items():
        lines += [f'- `{name}` v{contract["version"]}（{contract["status"]}）：[接口与限制](../{contract["documentation"]})。',
                  "  " + "、".join(f"`{api}`" for api in contract["apis"]) + "。"]
    lines += ["", "## 事件、Remote 和 UI 扩展点", "", catalog["extensionCoverage"], "",
              "| 类型 | 入口 | 已核对方法 | 阶段 | 行为边界 |", "| --- | --- | --- | --- | --- |"]
    for row in catalog["extensionPoints"]:
        methods = ", ".join(f"`{name}`" for name in row.get("methods", [])) or "—"
        lines.append(f'| {row["kind"]} | [`{row["name"]}`]({row["source"]}) | {methods} | {row["phase"]} | {row["boundary"]} |')
    return "\n".join(lines) + "\n"

"""Generate reproducible figures for the LamTools technical paper."""

from __future__ import annotations

from pathlib import Path
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "paper" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
CN_FONT = FontProperties(fname=r"C:\Windows\Fonts\Deng.ttf")
CN_BOLD = FontProperties(fname=r"C:\Windows\Fonts\Dengb.ttf")


def box(ax, xy, width, height, text, face, edge="#17324D", fontsize=10, fontproperties=None):
    patch = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.025",
        linewidth=1.2,
        edgecolor=edge,
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(
        xy[0] + width / 2,
        xy[1] + height / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontproperties=fontproperties,
        color="#1F2933",
        linespacing=1.25,
    )


def arrow(ax, start, end, color="#5B7083", style="-|>", connectionstyle="arc3"):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=13,
            linewidth=1.3,
            color=color,
            connectionstyle=connectionstyle,
        )
    )


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(10.5, 5.0), dpi=300)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis("off")

    box(ax, (0.35, 3.75), 1.8, 0.62, "Vue workbench\nCLI / HTTP / WebSocket", "#EAF2F8", fontsize=9)
    box(ax, (2.7, 3.55), 2.2, 1.0, "Core Loop Kernel\nmodel rounds · tools\napproval · retries · events", "#DCEAF4", fontsize=9.3)
    box(ax, (5.55, 3.75), 1.8, 0.62, "Provider / model\nadapters", "#EAF2F8", fontsize=9)
    box(ax, (2.7, 2.05), 2.2, 0.9, "Sub-agent runner\nnamed child session\nmodel + capability", "#EEF5E8", fontsize=9)
    box(ax, (5.55, 2.05), 1.8, 0.9, "Toolbox + plugins\nMCP / native tools\npermission modes", "#EEF5E8", fontsize=8.7)
    box(ax, (1.1, 0.55), 6.8, 0.82, "SQLite persistence\nthreads · events · checkpoints · rollback/fork · Arrange recovery", "#F8F1E5", fontsize=9.2)
    box(ax, (8.05, 2.0), 1.45, 1.0, "Attachment\nservice\nrecords", "#F6EAEA", fontsize=8.5)

    arrow(ax, (2.15, 4.06), (2.68, 4.06))
    arrow(ax, (4.92, 4.06), (5.52, 4.06))
    arrow(ax, (3.8, 3.52), (3.8, 2.98))
    arrow(ax, (4.92, 2.5), (5.52, 2.5))
    arrow(ax, (5.15, 3.8), (8.02, 2.72), connectionstyle="arc3,rad=-0.15")
    arrow(ax, (3.8, 2.02), (3.8, 1.4))
    arrow(ax, (6.45, 2.02), (5.95, 1.4))
    arrow(ax, (8.02, 2.3), (6.95, 1.4), connectionstyle="arc3,rad=0.15")

    ax.text(
        8.0,
        4.25,
        "local orchestration boundary",
        fontsize=8.5,
        color="#64748B",
        ha="center",
    )
    ax.plot([0.2, 9.8], [1.72, 1.72], color="#CBD5E1", linewidth=0.8, linestyle="--")
    ax.text(9.72, 1.78, "durable local state", fontsize=8, color="#64748B", ha="right")
    fig.tight_layout(pad=0.6)
    fig.savefig(OUT / "architecture.png", bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / "architecture.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def architecture_zh() -> None:
    fig, ax = plt.subplots(figsize=(10.5, 5.0), dpi=300)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis("off")
    box(ax, (0.35, 3.75), 1.8, 0.62, "Vue 工作台\nCLI / HTTP / WebSocket", "#EAF2F8", fontsize=9, fontproperties=CN_FONT)
    box(ax, (2.7, 3.55), 2.2, 1.0, "Core Loop Kernel\n模型回合·工具\n审批·重试·事件", "#DCEAF4", fontsize=9.3, fontproperties=CN_FONT)
    box(ax, (5.55, 3.75), 1.8, 0.62, "模型/提供商\n适配器", "#EAF2F8", fontsize=9, fontproperties=CN_FONT)
    box(ax, (2.7, 2.05), 2.2, 0.9, "子 Agent 运行器\n命名子会话\n模型+能力", "#EEF5E8", fontsize=9, fontproperties=CN_FONT)
    box(ax, (5.55, 2.05), 1.8, 0.9, "工具箱+插件\nMCP/原生工具\n权限模式", "#EEF5E8", fontsize=8.7, fontproperties=CN_FONT)
    box(ax, (1.1, 0.55), 6.8, 0.82, "SQLite 持久化\n线程·事件·检查点·回滚/分叉·Arrange 恢复", "#F8F1E5", fontsize=9.2, fontproperties=CN_FONT)
    box(ax, (8.05, 2.0), 1.45, 1.0, "附件服务\n记录", "#F6EAEA", fontsize=8.5, fontproperties=CN_FONT)
    arrow(ax, (2.15, 4.06), (2.68, 4.06))
    arrow(ax, (4.92, 4.06), (5.52, 4.06))
    arrow(ax, (3.8, 3.52), (3.8, 2.98))
    arrow(ax, (4.92, 2.5), (5.52, 2.5))
    arrow(ax, (5.15, 3.8), (8.02, 2.72), connectionstyle="arc3,rad=-0.15")
    arrow(ax, (3.8, 2.02), (3.8, 1.4))
    arrow(ax, (6.45, 2.02), (5.95, 1.4))
    arrow(ax, (8.02, 2.3), (6.95, 1.4), connectionstyle="arc3,rad=0.15")
    ax.text(8.0, 4.25, "本地编排边界", fontproperties=CN_FONT, fontsize=8.5, color="#64748B", ha="center")
    ax.plot([0.2, 9.8], [1.72, 1.72], color="#CBD5E1", linewidth=0.8, linestyle="--")
    ax.text(9.72, 1.78, "持久本地状态", fontproperties=CN_FONT, fontsize=8, color="#64748B", ha="right")
    fig.tight_layout(pad=0.6)
    fig.savefig(OUT / "architecture-zh.png", bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / "architecture-zh.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def retrieval_tradeoff() -> None:
    metrics = ["Any-gold R@1", "Any-gold R@5", "Any-gold R@10", "First-any-gold MRR"]
    bm25 = [0.786, 0.857, 0.857, 0.821]
    hybrid = [0.857, 1.000, 1.000, 0.917]

    fig, (ax_left, ax_right) = plt.subplots(
        1,
        2,
        figsize=(10.5, 3.8),
        dpi=300,
        gridspec_kw={"width_ratios": [2.2, 1]},
    )
    positions = list(range(len(metrics)))
    width = 0.36
    ax_left.bar([p - width / 2 for p in positions], bm25, width, label="BM25-only", color="#8BA8BC")
    ax_left.bar([p + width / 2 for p in positions], hybrid, width, label="Local hybrid", color="#17324D")
    ax_left.set_xticks(positions, metrics)
    ax_left.set_ylim(0, 1.12)
    ax_left.set_ylabel("Score")
    ax_left.grid(axis="y", alpha=0.25)
    ax_left.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, 1.0), ncol=2)
    for p, value in zip(positions, bm25):
        offset = 0.014 if p == 0 else 0.025
        ax_left.text(p - width / 2, value + offset, f"{value:.3f}", ha="center", fontsize=7.5)
    for p, value in zip(positions, hybrid):
        offset = 0.038 if p == 0 else 0.025
        ax_left.text(p + width / 2, value + offset, f"{value:.3f}", ha="center", fontsize=7.5)

    latencies = [1.75, 6.67]
    ax_right.bar([0, 1], latencies, color=["#8BA8BC", "#B85C5C"], width=0.55)
    ax_right.set_xticks([0, 1], ["BM25-only", "Local hybrid"], rotation=18, ha="right")
    ax_right.set_yscale("log")
    ax_right.set_ylabel("P95 latency (ms, log scale)")
    ax_right.grid(axis="y", alpha=0.25, which="both")
    for p, value in enumerate(latencies):
        label = "1.75 ms" if p == 0 else "6.67 ms"
        ax_right.text(p, value * 1.45, label, ha="center", fontsize=8)
    fig.tight_layout(pad=0.6)
    fig.savefig(OUT / "retrieval-tradeoff.png", bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / "retrieval-tradeoff.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def retrieval_tradeoff_zh() -> None:
    metrics = ["任一黄金文档 R@1", "任一黄金文档 R@5", "任一黄金文档 R@10", "首个任一黄金文档 MRR"]
    bm25 = [0.786, 0.857, 0.857, 0.821]
    hybrid = [0.857, 1.000, 1.000, 0.917]
    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(10.5, 3.8), dpi=300, gridspec_kw={"width_ratios": [2.2, 1]})
    positions = list(range(len(metrics)))
    width = 0.36
    ax_left.bar([p - width / 2 for p in positions], bm25, width, label="BM25-only", color="#8BA8BC")
    ax_left.bar([p + width / 2 for p in positions], hybrid, width, label="本地混合", color="#17324D")
    ax_left.set_xticks(positions, metrics, fontproperties=CN_FONT)
    ax_left.set_ylim(0, 1.12)
    ax_left.set_ylabel("分数", fontproperties=CN_FONT)
    ax_left.grid(axis="y", alpha=0.25)
    ax_left.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.0, 1.0), ncol=2, prop=CN_FONT)
    for p, value in zip(positions, bm25):
        offset = 0.014 if p == 0 else 0.025
        ax_left.text(p - width / 2, value + offset, f"{value:.3f}", ha="center", fontsize=7.5, fontproperties=CN_FONT)
    for p, value in zip(positions, hybrid):
        offset = 0.038 if p == 0 else 0.025
        ax_left.text(p + width / 2, value + offset, f"{value:.3f}", ha="center", fontsize=7.5, fontproperties=CN_FONT)
    latencies = [1.75, 6.67]
    ax_right.bar([0, 1], latencies, color=["#8BA8BC", "#B85C5C"], width=0.55)
    ax_right.set_xticks([0, 1], ["BM25-only", "本地混合"], rotation=18, ha="right", fontproperties=CN_FONT)
    ax_right.set_yscale("log")
    ax_right.set_ylabel("P95 延迟（毫秒，对数刻度）", fontproperties=CN_FONT)
    ax_right.grid(axis="y", alpha=0.25, which="both")
    for p, value in enumerate(latencies):
        label = "1.75 ms" if p == 0 else "6.67 ms"
        ax_right.text(p, value * 1.45, label, ha="center", fontsize=8, fontproperties=CN_FONT)
    fig.tight_layout(pad=0.6)
    fig.savefig(OUT / "retrieval-tradeoff-zh.png", bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / "retrieval-tradeoff-zh.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def delegation_sequence(zh: bool = False) -> None:
    """Draw the implemented parent-to-child delegation path."""
    fp = CN_FONT if zh else None
    labels = [
        "父 Agent" if zh else "Parent agent",
        "委派运行器" if zh else "Delegation runner",
        "子会话" if zh else "Child session",
        "SQLite / 工具箱" if zh else "SQLite / toolbox",
    ]
    steps = [
        "1 任务 + 模型 + 附件" if zh else "1  task + model + attachments",
        "2 解析规范模型 ID" if zh else "2  resolve canonical model ID",
        "3 按能力拆分附件" if zh else "3  split attachments by capability",
        "4 创建/恢复命名会话" if zh else "4  create/resume named session",
        "5 受限工具执行" if zh else "5  bounded tool execution",
        "6 事件与结果回投" if zh else "6  project events/results back",
    ]
    fig, ax = plt.subplots(figsize=(10.5, 5.5), dpi=300)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    xs = [1.25, 3.75, 6.25, 8.75]
    for x, label in zip(xs, labels):
        ax.text(x, 9.45, label, ha="center", va="center", fontsize=10,
                fontproperties=fp, fontweight="bold" if fp is None else None,
                color="#17324D")
        ax.plot([x, x], [0.65, 9.1], color="#AAB8C5", linewidth=1.0)
    ys = [8.45, 7.2, 5.95, 4.7, 3.45, 2.2]
    routes = [(0, 1), (1, 1), (1, 2), (1, 2), (2, 3), (2, 0)]
    colors_ = ["#17324D", "#5B7083", "#3E7C59", "#3E7C59", "#B85C5C", "#17324D"]
    for i, (y, (source, target), color) in enumerate(zip(ys, routes, colors_)):
        start = (xs[source] + (0.1 if target > source else -0.1), y)
        end = (xs[target] - (0.1 if target > source else -0.1), y)
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=12,
                                     linewidth=1.4, color=color,
                                     connectionstyle="arc3,rad=0"))
        ax.text((start[0] + end[0]) / 2, y + 0.18, steps[i], ha="center", va="bottom",
                fontsize=8.1, fontproperties=fp, color=color,
                bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none", alpha=0.92))
    ax.text(2.55, 1.0, "递归 sub_agent 被关闭；\n工具模式与审批状态随子会话持久化" if zh
            else "Recursive sub_agent calls are disabled;\ntool mode and approval state persist with the child.",
            ha="center", va="center", fontsize=7.8, fontproperties=fp, color="#64748B")
    ax.text(7.45, 1.0, "不支持的多模态内容延后，\n不静默伪装成已支持输入" if zh
            else "Unsupported multimodal content is deferred\nrather than silently re-labelled as supported.",
            ha="center", va="center", fontsize=7.8, fontproperties=fp, color="#64748B")
    fig.tight_layout(pad=0.6)
    fig.savefig(OUT / ("delegation-sequence-zh.png" if zh else "delegation-sequence.png"),
                bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / ("delegation-sequence-zh.svg" if zh else "delegation-sequence.svg"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


def evaluation_overview(zh: bool = False) -> None:
    """Summarize only recorded counts and derived retrieval deltas."""
    fp = CN_FONT if zh else None
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 3.7), dpi=300,
                                      gridspec_kw={"width_ratios": [1.15, 1.85]})
    suites = ["完整 Core" if zh else "Full Core", "定向机制" if zh else "Targeted mechanisms"]
    passed = [1481, 63]
    skipped = [2, 1]
    failed = [1, 0]
    x = range(2)
    left.bar(x, passed, color="#17324D", label="通过" if zh else "Passed")
    left.bar(x, skipped, bottom=passed, color="#D8A84E", label="跳过" if zh else "Skipped")
    left.bar(x, failed, bottom=[p + s for p, s in zip(passed, skipped)],
             color="#B5484A", label="失败" if zh else "Failed")
    left.set_xticks(list(x), suites, fontproperties=fp)
    left.set_ylabel("测试数" if zh else "Tests", fontproperties=fp)
    left.set_ylim(0, 1600)
    left.grid(axis="y", alpha=0.25)
    left.legend(frameon=False, prop=fp, loc="upper right")
    for i, (p, s, f) in enumerate(zip(passed, skipped, failed)):
        left.text(i, p + s + f + 34, f"{p} + {s} + {f}", ha="center", fontsize=8.5,
                  fontproperties=fp, color="#17324D")

    metrics = (["任一黄金文档 R@1", "任一黄金文档 R@5", "任一黄金文档 R@10", "首个任一黄金文档 MRR"]
               if zh else ["Any-gold R@1", "Any-gold R@5", "Any-gold R@10", "First-any-gold MRR"])
    base = [0.786, 0.857, 0.857, 0.821]
    local = [0.857, 1.0, 1.0, 0.917]
    delta = [b - a for a, b in zip(base, local)]
    right.barh(metrics, delta, color="#3E7C59")
    for label in right.get_yticklabels():
        label.set_fontproperties(fp)
    right.set_xlim(0, 0.18)
    right.set_xlabel("本地混合 - BM25-only" if zh else "Local hybrid - BM25-only", fontproperties=fp)
    right.grid(axis="x", alpha=0.25)
    for y, d in enumerate(delta):
        right.text(d + 0.004, y, f"+{d:.3f}", va="center", fontsize=8.2,
                   fontproperties=fp, color="#17324D")
    right.invert_yaxis()
    fig.tight_layout(pad=0.6)
    fig.savefig(OUT / ("evaluation-overview-zh.png" if zh else "evaluation-overview.png"),
                bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / ("evaluation-overview-zh.svg" if zh else "evaluation-overview.svg"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


def retrieval_per_query(zh: bool = False) -> None:
    """Plot the stored per-question rank and latency observations."""
    fp = CN_FONT if zh else None
    none = json.loads((ROOT / "e2e/rag-eval/reports/retrieval-none-20260815-095234.json").read_text(encoding="utf-8"))
    local = json.loads((ROOT / "e2e/rag-eval/reports/retrieval-local-20260815-101253.json").read_text(encoding="utf-8"))
    labels = [str(i + 1) for i in range(len(none["results"]))]
    rank_none = [r["rank"] or 0 for r in none["results"]]
    rank_local = [r["rank"] or 0 for r in local["results"]]
    latency_none = [r["ms"] for r in none["results"]]
    latency_local = [r["ms"] for r in local["results"]]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 4.2), dpi=300,
                                      gridspec_kw={"width_ratios": [1.25, 1]})
    y = list(range(len(labels)))
    left.plot(rank_none, y, "o-", color="#8BA8BC", label="BM25-only")
    left.plot(rank_local, y, "o-", color="#17324D", label="Local hybrid")
    left.set_yticks(y, labels)
    left.invert_yaxis()
    left.set_xlabel("Gold document rank (0 = not retrieved)", fontproperties=fp)
    left.set_ylabel("Question index", fontproperties=fp)
    left.set_xlim(-0.2, max(rank_local + rank_none) + 0.8)
    left.grid(axis="x", alpha=0.25)
    left.legend(frameon=False, prop=fp, loc="lower right")
    right.plot(latency_none, y, "o-", color="#8BA8BC", label="BM25-only")
    right.plot(latency_local, y, "o-", color="#B85C5C", label="Local hybrid")
    right.set_yticks(y, labels)
    right.invert_yaxis()
    right.set_xlabel("Per-question latency (ms)", fontproperties=fp)
    right.grid(axis="x", alpha=0.25)
    right.legend(frameon=False, prop=fp, loc="lower right")
    fig.tight_layout(pad=0.6)
    fig.savefig(OUT / ("retrieval-per-query-zh.png" if zh else "retrieval-per-query.png"),
                bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / ("retrieval-per-query-zh.svg" if zh else "retrieval-per-query.svg"),
                bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    architecture_zh()
    retrieval_tradeoff()
    retrieval_tradeoff_zh()
    delegation_sequence()
    delegation_sequence(True)
    evaluation_overview()
    evaluation_overview(True)
    retrieval_per_query()
    retrieval_per_query(True)

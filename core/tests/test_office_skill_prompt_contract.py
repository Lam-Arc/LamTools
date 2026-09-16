from __future__ import annotations

from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def _read(relative_path: str) -> str:
    return (SKILLS_ROOT / relative_path).read_text(encoding="utf-8")


def test_office_renderer_prompt_uses_direct_final_artifact_path_and_optional_check() -> None:
    skill = _read("office-renderer/SKILL.md")
    contract = _read("references/office-renderer-contract.md")

    assert "An environment preflight is optional" in skill
    assert "py -3.14 -m lamtools_core.cli office check" in skill
    assert "Office 应用已就绪 · Test Passed 3/3" in skill
    assert "Run `office validate` once against the final source" in skill
    assert "If validation passes, run `office render` once" in skill
    assert "环境预检不是必做步骤" in contract
    assert "唯一正常执行顺序" in contract
    assert "Office 应用已就绪 · Test Passed 3/3" in contract


def test_office_renderer_prompt_does_not_overclaim_sampled_visual_review() -> None:
    skill = _read("office-renderer/SKILL.md")
    contract = _read("references/office-renderer-contract.md")
    tooling = _read("references/tooling-contract.md")

    assert "inspect every generated page/sheet preview image once" in skill
    assert "it is not a whole-document visual pass" in skill
    assert "全部页面/工作表 PNG 必须各查看一次" in contract
    assert "自动 `visual=passed` 只表示渲染器程序化规则通过" in contract
    assert "scope: full | sampled | not_run" in contract
    assert "只看代表页必须报告为抽样检查并列出页码" in tooling


def test_tooling_contract_exposes_one_optional_readiness_command() -> None:
    tooling = _read("references/tooling-contract.md")

    assert "环境状态不明确时，可选运行一次" in tooling
    assert "py -3.14 -m lamtools_core.cli office check" in tooling
    assert "Office 应用已就绪 · Test Passed 3/3" in tooling

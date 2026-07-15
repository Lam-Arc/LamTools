from __future__ import annotations

from lamtools_core.kernel.policy import LoopPolicy
from lamtools_core.runtime.audit import build_kernel_audit


def test_kernel_audit_records_effective_policy_without_arbitrary_metadata(tmp_path):
    module = tmp_path / "kernel.py"
    module.write_text("# runtime\n", encoding="utf-8")
    policy = LoopPolicy(
        max_identical_tool_results=7,
        identical_tool_result_window=19,
        metadata={"api_key": "must-not-leak"},
    )

    audit = build_kernel_audit(policy=policy, kernel_module_path=str(module))

    assert audit["kernel_module_path"] == str(module.resolve())
    assert len(audit["kernel_module_sha256"]) == 64
    assert audit["loop_policy"]["max_identical_tool_results"] == 7
    assert audit["loop_policy"]["identical_tool_result_window"] == 19
    assert "must-not-leak" not in repr(audit)

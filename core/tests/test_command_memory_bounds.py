"""user:“该修修，该重构重构，有必要就重新设计架构或者迁到 Rust”+(命令持续或单行巨量输出时内存有界，仍正确结束和取消)。"""
import sys
import threading
import tracemalloc

import pytest

from lamtools_core.tool import command


@pytest.mark.parametrize("streaming", [False, True])
def test_large_unbroken_stdout_and_stderr_are_bounded(tmp_path, streaming):
    frames = []
    script = (
        "import os; "
        "os.write(1,b'HEAD\\n'); "
        "[(os.write(1,b'x'*65536),os.write(2,b'e'*65536)) for _ in range(64)]; "
        "os.write(1,b'\\nTAIL');os.write(2,b'\\nERROR-END')"
    )
    argv = [sys.executable, "-c", script]
    tracemalloc.start()
    try:
        if streaming:
            result = command.run_subprocess_streaming_blocking(argv, cwd=tmp_path, timeout=15,
                progress=lambda out, err: frames.append((len(out), len(err))))
        else:
            result = command.run_subprocess_blocking(argv, cwd=tmp_path, timeout=15)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.exit_code == 0, result.error
    limit = command.DEFAULT_MAX_TEXT_LENGTH + 200
    assert len(result.stdout) <= limit
    assert len(result.stderr) <= limit
    assert result.stdout.startswith("HEAD\n") and result.stdout.endswith("\nTAIL")
    assert result.stderr.endswith("\nERROR-END")
    assert "truncated" in result.stdout
    assert result.metadata["stdout_chars"] == 4 * 1024 * 1024 + 10
    assert peak < 6 * 1024 * 1024, f"parent captured output used {peak} bytes"
    assert all(max(frame) <= limit for frame in frames)


def test_progress_can_cancel_a_noisy_command_without_retaining_all_output(tmp_path):
    cancel = threading.Event()

    def progress(out, err):
        if "READY" in out:
            cancel.set()

    result = command.run_subprocess_streaming_blocking(
        [sys.executable, "-c", "import os,time;os.write(1,b'READY\\n');time.sleep(30)"],
        cwd=tmp_path, timeout=15, progress=progress, cancel_event=cancel,
    )
    assert result.error_type == "CancelledError"
    assert "READY" in result.stdout


def test_background_log_preview_reads_only_bounded_head_and_tail(tmp_path):
    path = tmp_path / "large.log"
    with path.open("wb") as handle:
        handle.write(b"HEAD\n")
        handle.seek(8 * 1024 * 1024)
        handle.write(b"\nTAIL")
    preview = command.read_command_log(path)
    assert preview.startswith("HEAD\n") and preview.endswith("\nTAIL")
    assert len(preview) <= command.DEFAULT_MAX_TEXT_LENGTH + 200
    assert "truncated" in preview


def test_chunked_utf8_and_windows_newlines_keep_text_semantics(tmp_path):
    payload = "你好🙂\r\n".encode("utf-8")
    result = command.run_subprocess_blocking([sys.executable, "-c",
        f"import os;os.write(1,{payload!r}*1500)"], cwd=tmp_path, timeout=10)
    assert result.exit_code == 0
    assert result.stdout == "你好🙂\n" * 1500

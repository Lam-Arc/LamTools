"""user:“都试一试”+(真实语音样本经过原版转写脚本，不以假结果替代解码与识别)。"""
import os
import subprocess
from pathlib import Path

import pytest


def test_real_local_transcription(tmp_path):
    interpreter, sample = os.environ.get("BILI_ACCEPTANCE_ASR_PYTHON"), os.environ.get("BILI_ACCEPTANCE_ASR_SAMPLE")
    if not interpreter or not sample:
        pytest.skip("set the ASR interpreter and synthetic speech sample for the live ASR acceptance")
    script = Path(__file__).resolve().parents[2] / "plugins/bili-scroll/vendor/asr.py"
    # Copy the unmodified upstream script to private storage: its cache and
    # temporary audio must never land in the published plugin code directory.
    private = tmp_path / "asr.py"
    private.write_bytes(script.read_bytes())
    output = tmp_path / "transcript.txt"
    environment = {**os.environ, "HF_HUB_DISABLE_XET": "1", "HF_ENDPOINT": "https://huggingface.co"}
    result = subprocess.run([interpreter, str(private), sample, "--model", "tiny", "--lang", "en", "-o", str(output)],
                            capture_output=True, text=True, encoding="utf-8", env=environment, timeout=180)
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8").lower()
    assert "speech recognition" in text and "plugin" in text, text

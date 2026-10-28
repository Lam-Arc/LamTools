"""user:“测试，提交打包发布”+(构建资源先生成到暂存目录，再替换，避免原地写入被映射文件)。"""
import runpy
from pathlib import Path

import pytest


def publisher():
    return runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/prepare-network-plugin.py"))["publish_ui_assets"]


def test_publish_replaces_complete_assets_without_truncating_old_files(tmp_path):
    publish = publisher()
    source, target = tmp_path / "build", tmp_path / "ui"
    source.mkdir(); target.mkdir()
    for name in ("page.mjs", "style.css"):
        (source / name).write_text("new")
        (target / name).write_text("old")
    publish(source, target)
    assert (target / "page.mjs").read_text() == "new"
    assert (target / "style.css").read_text() == "new"
    assert not list(target.glob("*.tmp"))


def test_missing_build_asset_preserves_existing_distribution(tmp_path):
    publish = publisher()
    source, target = tmp_path / "build", tmp_path / "ui"
    source.mkdir(); target.mkdir()
    (source / "style.css").write_text("new")
    for name in ("page.mjs", "style.css"):
        (target / name).write_text("old")
    with pytest.raises(FileNotFoundError):
        publish(source, target)
    assert (target / "page.mjs").read_text() == "old"

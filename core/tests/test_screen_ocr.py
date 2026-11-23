"""截图取字（screen_ocr）验收测试：裁剪边界、宿主契约、输出形状与错误码。

识别本身由桌面端的 Windows.Media.Ocr 完成（Rust 侧 ``src/ocr.rs`` 有自己的真实
识别测试），这里锁住的是 Python 这一层：截图复用、区域裁剪、给宿主的参数、
以及「缺语言包不能静默成空字符串」这条底线。

user:“先写测试：图像输入（用代码生成一张已知文字的图片，断言 OCR 结果包含该文字）、
语言缺失错误、区域裁剪边界、工具输出形状”+
(真实识别在 Rust 侧自证；这里用一张已知文字图验证裁剪后交给宿主的正是那块像素)。
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from lamtools_core.computer_use import capture, session, tools
from lamtools_core.tool import ToolCall

# Rust 与 Python 共用的样图：白底黑字 "Sunday OCR 2024"，文字在左半边。
SAMPLE = Path(__file__).resolve().parents[1] / "desktop" / "src-tauri" / "tests" / "fixtures" / "ocr-known-text.png"


def _call(**kwargs):
    return ToolCall(id="call-ocr", name="computer_use", arguments={"action": "ocr", **kwargs})


@pytest.fixture(autouse=True)
def _clean_session():
    session.clear()
    yield
    session.clear()


def _png(width: int, height: int, *, color: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _frame(width: int = 800, height: int = 400, *, scale: float = 2.0,
           origin: tuple[int, int] = (100, 50), png: bytes | None = None) -> capture.Frame:
    return capture.Frame(
        png=png if png is not None else _png(width, height),
        image_width=width,
        image_height=height,
        screen_width=int(width * scale),
        screen_height=int(height * scale),
        origin_x=origin[0],
        origin_y=origin[1],
    )


# ---------------------------------------------------------------------------
# 区域裁剪
# ---------------------------------------------------------------------------


class TestCropFrame:
    # user:“区域：支持整图与矩形裁剪（复用现有裁剪）”+(不传 area 就是整图，原样返回)。
    def test_no_area_keeps_the_whole_frame(self):
        frame = _frame()
        assert capture.crop_frame(frame, None) is frame

    def test_area_is_clipped_to_the_frame(self):
        cropped = capture.crop_frame(_frame(800, 400), [700, 300, 400, 400])
        assert (cropped.image_width, cropped.image_height) == (100, 100)

    def test_crop_keeps_screen_mapping(self):
        frame = _frame(800, 400, scale=2.0, origin=(100, 50))
        cropped = capture.crop_frame(frame, [200, 100, 300, 120])
        # 图内 200,100 在屏幕上就是原图同样的位置，裁剪不改变坐标语义。
        assert cropped.to_screen(0, 0) == frame.to_screen(200, 100)
        assert cropped.to_screen(300, 120) == frame.to_screen(500, 220)
        assert (cropped.screen_width, cropped.screen_height) == (600, 240)
        assert (cropped.origin_x, cropped.origin_y) == frame.to_screen(200, 100)

    def test_crop_only_keeps_the_requested_pixels(self):
        # 样图是白底黑字：文字块裁出来该有黑像素，纯白块裁出来必须还是纯白
        # （证明裁剪真的是按像素切的，不是整图缩放或错位）。
        sample = SAMPLE.read_bytes()
        frame = _frame(720, 200, scale=1.0, origin=(0, 0), png=sample)
        text = capture.crop_frame(frame, [40, 40, 380, 80])
        blank = capture.crop_frame(frame, [400, 0, 300, 30])
        text_image = Image.open(io.BytesIO(text.png))
        blank_image = Image.open(io.BytesIO(blank.png))
        assert text_image.size == (380, 80)
        assert blank_image.size == (300, 30)
        assert text_image.convert("L").getextrema()[0] < 128, "文字块里应当有黑字"
        assert blank_image.convert("L").getextrema() == (255, 255), "纯白块裁出来应当还是纯白"

    def test_area_outside_the_frame_is_rejected(self):
        with pytest.raises(ValueError) as error:
            capture.crop_frame(_frame(800, 400), [900, 500, 100, 100])
        assert "之外" in str(error.value)

    def test_area_with_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError) as error:
            capture.crop_frame(_frame(), [1, 2, 3])
        assert "area" in str(error.value)


# ---------------------------------------------------------------------------
# 工具输出形状与宿主契约
# ---------------------------------------------------------------------------


class _Host:
    """替身宿主：记录下发给桌面端的命令与参数，返回一份识别结果。"""

    def __init__(self, payload: dict | None = None, error: Exception | None = None):
        self.payload = payload if payload is not None else {
            "text": "Sunday OCR 2024",
            "lines": [{"text": "Sunday OCR 2024", "bounds": [10, 20, 300, 40]}],
            "language": "zh-Hans-CN",
            "image_width": 800,
            "image_height": 400,
            "max_image_dimension": 10000,
            "available_languages": ["zh-Hans-CN"],
        }
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, command, arguments, *, timeout):
        self.calls.append((command, arguments))
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.fixture()
def fake_grab(monkeypatch):
    """把截图换成固定的一张图，测试就不去碰真实屏幕。"""
    def _grab(args):
        return _frame(), "screen"
    monkeypatch.setattr(tools, "_grab", _grab)
    return _grab


@pytest.mark.asyncio
class TestOcrAction:
    async def test_reports_text_as_untrusted_content(self, tmp_path, fake_grab, monkeypatch):
        host = _Host()
        monkeypatch.setattr(tools.host_channel, "call", host)
        await tools.handle(ToolCall(id="c0", name="computer_use", arguments={"action": "start", "goal": "取字"}), work_root=tmp_path)

        result = await tools.handle(_call(), work_root=tmp_path)

        assert result.status == "ok"
        # user:“输出标注为「不可信内容」”+(屏幕上的字只能当数据，不能当指令)。
        assert result.metadata["trust"] == "untrusted"
        assert "不可信" in result.content
        assert "Sunday OCR 2024" in result.content
        assert result.metadata["language"] == "zh-Hans-CN"
        assert result.metadata["line_count"] == 1
        # 落盘证据能回看，路径是 work_root 相对路径。
        assert (tmp_path / result.metadata["path"]).is_file()

        command, arguments = host.calls[0]
        assert command == "ocr_image"
        # 整图识别：发给宿主的应当是这张 800x400 的图。
        sent = Image.open(io.BytesIO(base64.b64decode(arguments["image"])))
        assert sent.size == (800, 400)
        assert "language" not in arguments

    async def test_area_is_what_gets_recognized(self, tmp_path, fake_grab, monkeypatch):
        host = _Host()
        monkeypatch.setattr(tools.host_channel, "call", host)
        await tools.handle(ToolCall(id="c0", name="computer_use", arguments={"action": "start", "goal": "取字"}), work_root=tmp_path)

        result = await tools.handle(_call(area=[100, 50, 320, 160]), work_root=tmp_path)

        assert result.status == "ok"
        assert result.metadata["area"] == [100, 50, 320, 160]
        command, arguments = host.calls[0]
        sent = Image.open(io.BytesIO(base64.b64decode(arguments["image"])))
        assert sent.size == (320, 160)

    async def test_language_is_forwarded(self, tmp_path, fake_grab, monkeypatch):
        host = _Host()
        monkeypatch.setattr(tools.host_channel, "call", host)
        await tools.handle(ToolCall(id="c0", name="computer_use", arguments={"action": "start", "goal": "取字"}), work_root=tmp_path)
        await tools.handle(_call(language="en-US"), work_root=tmp_path)
        assert host.calls[0][1]["language"] == "en-US"

    async def test_empty_text_is_not_an_error(self, tmp_path, fake_grab, monkeypatch):
        host = _Host(payload={"text": "", "lines": [], "language": "zh-Hans-CN"})
        monkeypatch.setattr(tools.host_channel, "call", host)
        await tools.handle(ToolCall(id="c0", name="computer_use", arguments={"action": "start", "goal": "取字"}), work_root=tmp_path)

        result = await tools.handle(_call(), work_root=tmp_path)

        assert result.status == "ok"
        assert "没有识别到文字" in result.content

    # user:“语言包缺失错误码（不要静默空字符串）”+(缺包必须是失败 + 明确的错误码)。
    async def test_missing_language_pack_is_reported(self, tmp_path, fake_grab, monkeypatch):
        host = _Host(error=tools.host_channel.BrowserChannelError(
            "ocr_language_missing", "系统没有可用的 OCR 语言包"))
        monkeypatch.setattr(tools.host_channel, "call", host)
        await tools.handle(ToolCall(id="c0", name="computer_use", arguments={"action": "start", "goal": "取字"}), work_root=tmp_path)

        result = await tools.handle(_call(language="zz-ZZ"), work_root=tmp_path)

        assert result.status == "failed"
        assert result.metadata["error_code"] == "ocr_language_missing"
        assert "OCR 语言包" in result.error

    async def test_desktop_not_running_is_explained(self, tmp_path, fake_grab, monkeypatch):
        host = _Host(error=tools.host_channel.BrowserChannelError("unsupported", "桌面应用没有响应这条浏览器指令"))
        monkeypatch.setattr(tools.host_channel, "call", host)
        await tools.handle(ToolCall(id="c0", name="computer_use", arguments={"action": "start", "goal": "取字"}), work_root=tmp_path)

        result = await tools.handle(_call(), work_root=tmp_path)

        assert result.status == "failed"
        assert result.metadata["error_code"] == "desktop_unavailable"
        assert "桌面" in result.error

    async def test_ocr_requires_a_started_task(self, tmp_path, fake_grab, monkeypatch):
        host = _Host()
        monkeypatch.setattr(tools.host_channel, "call", host)
        result = await tools.handle(_call(), work_root=tmp_path)
        assert result.status == "blocked"
        assert host.calls == []

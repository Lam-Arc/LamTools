"""截图编码、缩放与标注。

模型的坐标按“截图像素”给，程序按 scale 换算回物理屏幕坐标。这样模型只需要
看图给数，不用心算缩放比例，少一个出错环节。

user:“查一下 computer use 功能怎么做”+(截图既要给模型看，也要落成证据给用户回看)。
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image, ImageDraw

# user:“按理说应该是 1440×2560 的 2K 屏，这里是不是设计没设计妥当”+
# (实测 2560x1440 缩到 2000 宽后 PNG 反而更大，坐标还要多一层换算；
#  改成只在超宽屏才缩，2K 保持原尺寸，截图坐标就等于物理像素坐标。)
MAX_MODEL_WIDTH = 2800


@dataclass
class Frame:
    png: bytes
    image_width: int
    image_height: int
    screen_width: int
    screen_height: int
    origin_x: int
    origin_y: int

    @property
    def scale_x(self) -> float:
        return self.screen_width / max(self.image_width, 1)

    @property
    def scale_y(self) -> float:
        return self.screen_height / max(self.image_height, 1)

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return (
            int(round(self.origin_x + x * self.scale_x)),
            int(round(self.origin_y + y * self.scale_y)),
        )

    def to_dict(self) -> dict:
        return {
            "image_width": self.image_width,
            "image_height": self.image_height,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "origin": [self.origin_x, self.origin_y],
            "scale_x": round(self.scale_x, 4),
            "scale_y": round(self.scale_y, 4),
        }


def rgba_to_image(width: int, height: int, rgba: bytes) -> Image.Image:
    return Image.frombytes("RGBA", (width, height), rgba, "raw", "BGRA")


MAX_MODEL_BYTES = 1_400_000


def encode_png(
    image: Image.Image,
    *,
    max_width: int = MAX_MODEL_WIDTH,
    max_bytes: int = MAX_MODEL_BYTES,
) -> tuple[bytes, int, int]:
    """编码成 PNG。先按宽度上限缩，超过体积阈值再逐步缩小，直到放得进模型。"""
    width = min(max_width or image.width, image.width)
    current = image
    if width < image.width:
        ratio = width / image.width
        current = image.resize((width, max(1, int(round(image.height * ratio)))), Image.LANCZOS)
    while True:
        buffer = io.BytesIO()
        current.save(buffer, format="PNG", optimize=True)
        png = buffer.getvalue()
        if len(png) <= max_bytes or current.width <= 1280:
            return png, current.width, current.height
        width = max(1280, int(current.width * 0.8))
        ratio = width / current.width
        current = current.resize(
            (width, max(1, int(round(current.height * ratio)))), Image.LANCZOS
        )

def annotate_grid(image: Image.Image, *, step: int = 200) -> Image.Image:
    """在截图上叠加坐标网格。模型反复点偏时用它建立坐标感。"""
    canvas = image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = canvas.size
    for x in range(step, width, step):
        draw.line([(x, 0), (x, height)], fill=(255, 60, 60, 70), width=1)
        draw.text((x + 3, 3), str(x), fill=(255, 60, 60, 220))
    for y in range(step, height, step):
        draw.line([(0, y), (width, y)], fill=(60, 120, 255, 70), width=1)
        draw.text((3, y + 1), str(y), fill=(60, 120, 255, 220))
    return Image.alpha_composite(canvas, overlay)


def annotate_target(image: Image.Image, x: int, y: int, *, label: str = "") -> Image.Image:
    """在截图上圈出上一次动作的落点，给用户和模型核对。"""
    canvas = image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    radius = 18
    draw.ellipse(
        [(x - radius, y - radius), (x + radius, y + radius)],
        outline=(255, 60, 60, 230), width=3,
    )
    draw.line([(x - 26, y), (x + 26, y)], fill=(255, 60, 60, 160), width=1)
    draw.line([(x, y - 26), (x, y + 26)], fill=(255, 60, 60, 160), width=1)
    if label:
        draw.text((x + 22, y - 8), label[:40], fill=(255, 60, 60, 230))
    return Image.alpha_composite(canvas, overlay)


def to_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def frame_difference(before: tuple[int, int, bytes], after: tuple[int, int, bytes]) -> float:
    """两张 RGBA 帧的平均绝对差，0 到 255。

    缩到 48x48 再比，既能忽略光标闪烁这类一像素变化，又足够判断界面有没有动。
    """
    width, height, raw = before
    if (width, height) != (after[0], after[1]):
        return 255.0
    left = Image.frombytes("RGBA", (width, height), raw, "raw", "BGRA").convert("L").resize((48, 48))
    right = Image.frombytes("RGBA", (after[0], after[1]), after[2], "raw", "BGRA").convert("L").resize((48, 48))
    left_bytes = left.tobytes()
    right_bytes = right.tobytes()
    if len(left_bytes) != len(right_bytes) or not left_bytes:
        return 255.0
    total = sum(abs(a - b) for a, b in zip(left_bytes, right_bytes))
    return total / len(left_bytes)


def preview_data_url(png: bytes, *, max_width: int = 720) -> str:
    """UI 里显示的缩略图，和给模型看的图分开，避免事件体积膨胀。"""
    image = Image.open(io.BytesIO(png))
    image.load()
    small, _, _ = encode_png(image, max_width=max_width)
    return to_data_url(small)

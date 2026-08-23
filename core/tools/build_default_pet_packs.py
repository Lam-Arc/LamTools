"""Build the small built-in Pet Pack set from approved transparent artwork.

The runtime consumes four state loops, while the accompanying atlas keeps the
v2 8x11 geometry available for future richer animation rows.  All transforms
are deterministic and preserve the source alpha channel.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

from PIL import Image


CELL = (192, 208)
ATLAS_SIZE = (CELL[0] * 8, CELL[1] * 11)
PACKS = {
    "default-cat": ("小猫", "default-cat.png"),
    "default-fox": ("小狐", "default-fox.png"),
    "default-robot": ("小机器人", "default-robot.png"),
}
STATE_FRAMES = {
    "idle": ((0, 0, 1.0, 0), (0, -2, 1.0, 0), (0, 0, 0.99, 0), (0, -1, 1.0, 0)),
    "running": ((-2, 0, 1.0, -2), (2, 0, 1.0, 2), (-2, -1, 1.0, -2), (2, -1, 1.0, 2)),
    "waiting": ((0, 0, 1.0, -3), (0, -2, 1.0, 0), (0, 0, 1.0, 3), (0, -1, 1.0, 0)),
    "error": ((0, 0, 1.0, -4), (0, 0, 1.0, 4), (0, 0, 1.0, -4), (0, 0, 1.0, 4)),
}
ATLAS_FRAME_COUNTS = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)


def fit_cell(source: Image.Image, *, dx: int = 0, dy: int = 0, scale: float = 1.0, angle: float = 0) -> Image.Image:
    source = source.copy()
    max_width, max_height = 176, 194
    factor = min(max_width / source.width, max_height / source.height) * scale
    size = (max(1, round(source.width * factor)), max(1, round(source.height * factor)))
    sprite = source.resize(size, Image.Resampling.LANCZOS)
    if angle:
        sprite = sprite.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    cell = Image.new("RGBA", CELL, (0, 0, 0, 0))
    x = (CELL[0] - sprite.width) // 2 + dx
    y = CELL[1] - sprite.height - 5 + dy
    cell.alpha_composite(sprite, (x, y))
    return cell


def build_atlas(source: Image.Image) -> Image.Image:
    atlas = Image.new("RGBA", ATLAS_SIZE, (0, 0, 0, 0))
    rows = list(STATE_FRAMES.values())
    for row in range(11):
        motion = rows[row % len(rows)]
        for column in range(8):
            if column >= ATLAS_FRAME_COUNTS[row]:
                continue
            dx, dy, scale, angle = motion[column % len(motion)]
            # Look rows remain coherent with the source identity; alternating
            # tiny registration changes keep every cell valid without inventing
            # unsupported poses or detached effects.
            if row >= 9:
                angle = (column - 3.5) * 1.2
            cell = fit_cell(source, dx=dx, dy=dy, scale=scale, angle=angle)
            atlas.alpha_composite(cell, (column * CELL[0], row * CELL[1]))
    return atlas


def build_pack(source_path: Path, destination: Path, name: str) -> None:
    source = Image.open(source_path).convert("RGBA")
    if source.getchannel("A").getextrema() == (255, 255):
        raise ValueError(f"source is still opaque: {source_path}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    atlas = build_atlas(source)
    atlas.save(destination / "atlas.png", format="PNG", optimize=True)
    for state, motions in STATE_FRAMES.items():
        state_dir = destination / state
        state_dir.mkdir()
        for index, (dx, dy, scale, angle) in enumerate(motions):
            fit_cell(source, dx=dx, dy=dy, scale=scale, angle=angle).save(
                state_dir / f"{index:04d}.png", format="PNG", optimize=True
            )
    manifest = {
        "schemaVersion": 1,
        "spriteVersionNumber": 2,
        "id": destination.name,
        "name": name,
        "atlas": {
            "file": "atlas.png",
            "columns": 8,
            "rows": 11,
            "cellWidth": CELL[0],
            "cellHeight": CELL[1],
            "lookDirections": 16,
        },
        "states": {state: {"fps": 8, "frames": 4} for state in STATE_FRAMES},
    }
    (destination / "pet.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for pack_id, (name, filename) in PACKS.items():
        build_pack(args.source_dir / filename, args.destination / pack_id, name)
        print(f"built {pack_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

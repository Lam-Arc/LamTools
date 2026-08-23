"""Remove baked checkerboard mattes from existing Pet artwork.

The original built-in Pet images were opaque PNGs with a checkerboard painted
into the background.  This repair keeps the artwork pixels and removes only
background-colored regions connected to the image border, so white fur and
other light parts inside the silhouette are not deleted by a global color
threshold.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from PIL import Image


def _background_candidate(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    chroma = max(rgb) - min(rgb)
    # The source matte is a light, almost-neutral checkerboard.  The lower
    # bound avoids treating the robot's dark body or colored outlines as matte.
    return min(rgb) >= 218 and chroma <= 18


def _border_background_mask(image: Image.Image) -> bytearray:
    width, height = image.size
    pixels = image.load()
    candidate = bytearray(width * height)
    for y in range(height):
        row = y * width
        for x in range(width):
            value = pixels[x, y]
            candidate[row + x] = _background_candidate((value[0], value[1], value[2]))

    # Flood only candidate pixels reachable from an image edge.  Enclosed
    # near-white areas therefore remain part of the character silhouette.
    matte = bytearray(width * height)
    queue: deque[int] = deque()
    for x in range(width):
        for y in (0, height - 1):
            index = y * width + x
            if candidate[index] and not matte[index]:
                matte[index] = 1
                queue.append(index)
    for y in range(height):
        for x in (0, width - 1):
            index = y * width + x
            if candidate[index] and not matte[index]:
                matte[index] = 1
                queue.append(index)

    while queue:
        index = queue.popleft()
        x = index % width
        y = index // width
        if x:
            neighbour = index - 1
            if candidate[neighbour] and not matte[neighbour]:
                matte[neighbour] = 1
                queue.append(neighbour)
        if x + 1 < width:
            neighbour = index + 1
            if candidate[neighbour] and not matte[neighbour]:
                matte[neighbour] = 1
                queue.append(neighbour)
        if y:
            neighbour = index - width
            if candidate[neighbour] and not matte[neighbour]:
                matte[neighbour] = 1
                queue.append(neighbour)
        if y + 1 < height:
            neighbour = index + width
            if candidate[neighbour] and not matte[neighbour]:
                matte[neighbour] = 1
                queue.append(neighbour)
    return matte


def repair(source: Path, destination: Path) -> tuple[int, int]:
    image = Image.open(source).convert("RGBA")
    matte = _border_background_mask(image)
    pixels = image.load()
    removed = 0
    kept = 0
    for index, is_matte in enumerate(matte):
        x = index % image.width
        y = index // image.width
        if is_matte:
            pixels[x, y] = (0, 0, 0, 0)
            removed += 1
        else:
            # Fully opaque source pixels stay opaque; this is intentionally a
            # conservative matte removal rather than a destructive recolor.
            pixels[x, y] = (pixels[x, y][0], pixels[x, y][1], pixels[x, y][2], 255)
            kept += 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)
    return removed, kept


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    removed, kept = repair(args.source, args.destination)
    print(f"{args.source.name}: removed={removed} kept={kept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

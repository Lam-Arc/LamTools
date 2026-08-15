"""sqlite 连接与 vec0 扩展加载（sqlite-vec，P0 实测项）。"""
from __future__ import annotations

import struct
import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """打开 rag.db（自动建表 + 加载 vec0 扩展）。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _load_vec(conn)
    from .schema import init_db

    init_db(conn)
    return conn


def _load_vec(conn: sqlite3.Connection) -> None:
    """每个连接都必须单独加载扩展（sqlite 扩展是连接级状态，
    不能像此前用全局标志跳过——第二次 connect 会报 no such module: vec0）。"""
    try:
        import sqlite_vec  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "缺少依赖 sqlite-vec：请先 plugin.deps-status 安装 "
            "(pip install 'sqlite-vec>=0.1.9')"
        ) from exc
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def encode_vector(vec: list[float]) -> bytes:
    """float32 小端字节序列（vec0 MATCH/INSERT 格式）。"""
    return struct.pack(f"<{len(vec)}f", *vec)


def l2_normalize(vec: list[float]) -> list[float]:
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return vec
    return [v / norm for v in vec]

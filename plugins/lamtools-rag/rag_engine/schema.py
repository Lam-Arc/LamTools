"""rag.db schema（v2 规格 §6）。

- documents：语料表（source 维度：workspace_doc / session_history / artifact）
- chunks：检索原子单位（消息级会话块：role/turn_index/message_id/ts/tool_names）
- chunks_fts：FTS5 全文（中文 trigram，BM25）
- chunks_vec：vec0 向量（512 维，cosine）
- extractions：结构化提取产物（表格/图片 + citation target）
"""
from __future__ import annotations

import sqlite3

SOURCES = ("workspace_doc", "session_history", "artifact")
EMB_DIM = 512

_DDL = """
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  path TEXT,
  title TEXT,
  sha256 TEXT,
  mtime REAL,
  document_format TEXT,
  pages INTEGER,
  status TEXT NOT NULL DEFAULT 'indexed',
  indexed_at REAL,
  version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id INTEGER PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id),
  source TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  turn_index INTEGER DEFAULT 0,
  message_id TEXT,
  role TEXT,
  page INTEGER,
  char_offset INTEGER,
  heading TEXT,
  block_type TEXT,
  context TEXT NOT NULL,
  tool_names TEXT,
  ts REAL,
  tokens INTEGER,
  table_id TEXT,
  image_id TEXT,
  emb_source TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
CREATE INDEX IF NOT EXISTS idx_chunks_message ON chunks(message_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  context, heading,
  chunk_id UNINDEXED, doc_id UNINDEXED, source UNINDEXED,
  role UNINDEXED, page UNINDEXED,
  tokenize='trigram'
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
  chunk_id INTEGER PRIMARY KEY,
  embedding float[{dim}] distance_metric=cosine
);

CREATE TABLE IF NOT EXISTS extractions (
  extraction_id TEXT PRIMARY KEY,
  doc_id TEXT,
  page INTEGER,
  kind TEXT,
  raw TEXT,
  structured TEXT,
  model_id TEXT,
  created_at REAL
);
""".format(dim=EMB_DIM)


def init_db(conn: sqlite3.Connection) -> None:
    """建表（幂等）。FTS5/vec0 虚拟表由 sqlite-vec + 内置 SQLite 提供。"""
    conn.executescript(_DDL)
    conn.commit()

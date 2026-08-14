"""embedding 双模式 + 降级（v2 §7）。

- local：fastembed + BAAI/bge-small-zh-v1.5（onnx，无 torch；P0 实测 onnxruntime py3.14）
- api：provider /embeddings（P3，需 embedding adapter）
- none / 缺失：可用性 False → 检索自动降级 BM25-only
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

EMB_DIM = 512


class Embedder:
    def __init__(self, source: str = "local") -> None:
        self._source = source
        self._model = None
        self._error = ""

    @property
    def source(self) -> str:
        return self._source

    @property
    def error(self) -> str:
        return self._error

    def available(self) -> bool:
        return self._load() is not None

    def _load(self):
        if self._model is not None:
            return self._model
        if self._source in ("none", "api"):
            self._error = f"embedding source '{self._source}' 当前不可用（api 需 P3 adapter）"
            return None
        try:
            from fastembed import TextEmbedding  # noqa: PLC0415

            self._model = TextEmbedding(
                model_name="BAAI/bge-small-zh-v1.5", max_length=512
            )
            _logger.info("[rag] embedding model loaded (local/bge-small-zh-v1.5)")
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            _logger.warning("[rag] embedding unavailable, fallback BM25-only: %s", exc)
            self._model = None
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """批量嵌入；不可用时返回 None（调用方降级 BM25-only）。"""
        model = self._load()
        if model is None:
            return None
        try:
            return [list(map(float, v)) for v in model.embed(texts)]
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            _logger.warning("[rag] embed failed, fallback BM25-only: %s", exc)
            return None

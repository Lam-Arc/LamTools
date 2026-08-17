"""embedding 双模式 + 降级（v2 §7）。

- local：fastembed + BAAI/bge-small-zh-v1.5（onnx，无 torch）
- api：provider /embeddings（P3，需 embedding adapter）
- none / 缺失：可用性 False → 检索自动降级 BM25-only

环境修复（2026-08-15 实测，详见 docs/rag-plugin-plan.md §6）：
- HF 直连本机不通：fastembed 每次构造都调 HF API 查 revision，卡网络超时 ~170s，
  且模型从未下载成功 → vec 腿静默失效（混合分数=BM25 复读的根因）；
- 修复：HF_ENDPOINT 走 hf-mirror.com 镜像 + HF_HUB_DISABLE_XET=1
  （镜像站 cas-server.xethub.hf.co 401）；
- providers 显式 CPUExecutionProvider（onnxruntime 1.28 的 AEP 排首位，
  默认会先尝试 Azure 硬件）。
"""
from __future__ import annotations

import logging
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

_logger = logging.getLogger(__name__)

EMB_DIM = 512
# 构造/单次嵌入耗时上限（评测自检门槛；本机实测 4.7s / 1-2ms）
INIT_LIMIT_S = 30.0
EMBED_LIMIT_MS = 5000.0


def _shared_instance(source: str) -> Embedder:
    """按 source 复用的共享实例（避免多次构造 ~0.5s 的模型加载）。"""
    if source not in _SHARED:
        _SHARED[source] = Embedder(source)
    return _SHARED[source]


_SHARED: dict[str, Embedder] = {}


class Embedder:
    def __init__(self, source: str = "local") -> None:
        self._source = source
        self._model = None
        self._error = ""
        self._attempts = 0
        self._failures = 0

    @property
    def source(self) -> str:
        return self._source

    @property
    def error(self) -> str:
        return self._error

    @property
    def stats(self) -> dict:
        """调用统计：attempts/failures/last_error——评测与工具结果可见，
        杜绝"vec 腿静默失效"（2026-08-15 教训：混合分数=BM25 复读）。"""
        return {
            "source": self._source,
            "available": self.available(),
            "attempts": self._attempts,
            "failures": self._failures,
            "last_error": self._error,
        }

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
                model_name="BAAI/bge-small-zh-v1.5",
                max_length=512,
                providers=["CPUExecutionProvider"],
            )
            _logger.info("[rag] embedding model loaded (local/bge-small-zh-v1.5)")
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            _logger.warning("[rag] embedding unavailable, fallback BM25-only: %s", exc)
            self._model = None
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """批量嵌入；不可用或失败时返回 None（调用方降级 BM25-only）。
        失败计数进 stats（评测自检用），不静默。"""
        self._attempts += 1
        model = self._load()
        if model is None:
            self._failures += 1
            return None
        try:
            return [list(map(float, v)) for v in model.embed(texts)]
        except Exception as exc:  # noqa: BLE001
            self._failures += 1
            self._error = f"{type(exc).__name__}: {exc}"
            _logger.warning("[rag] embed failed, fallback BM25-only: %s", exc)
            return None

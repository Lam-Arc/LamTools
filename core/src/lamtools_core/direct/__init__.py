"""API 直接调用：不进 Agent Loop，选模型、给输入、拿结果。

对外只有三个概念：
- :class:`DirectCallService` — 目录、发起、历史、保存为资产；
- :class:`DirectExecutor` — 按输出类型执行一次调用；
- :class:`DirectCallStore` — 记录落盘。

user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
+(模型与供应商配置、LLM 客户端、资料库都复用现有实现；这里只补直调这条缺的链路。)
"""
from __future__ import annotations

from .executor import DirectExecutor, DirectModelTarget
from .operations import build_direct_operation_catalog
from .service import MAX_PROMPTS, DirectCallService
from .store import DirectCallRecord, DirectCallResult, DirectCallStore

__all__ = [
    "DirectCallRecord",
    "DirectCallResult",
    "DirectCallService",
    "DirectCallStore",
    "DirectExecutor",
    "DirectModelTarget",
    "MAX_PROMPTS",
    "build_direct_operation_catalog",
]

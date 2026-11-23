"""搜索适配器：把「用真实浏览器搜索」变成一套结构化接口。

user:“无需配置搜索 API、无需关心不同搜索引擎的页面结构，直接让 Sunday 使用浏览器完成网页搜索与研究”+

分层：
- ``adapters``  每个引擎一页知识（选择器、等待标记、受阻标记、查询与分页）
- ``dom``       把页面取回来的片段解析成树（标准库，可离线测试）
- ``pipeline``  卡片 → 结构化结果（字段配对、去重、广告分离、校验）
- ``engine``    编排：开页 → 等待 → L1/L2/L3 → 状态与诊断
- ``reader``    正文读取（按结构挑容器、按层级切块、支持分段）
- ``sessions``  搜索会话与结果 ID（只在本次搜索内有效）
"""

from __future__ import annotations

from . import adapters, dom, engine, models, pipeline, reader, sessions, urls
from .models import RequestError, SearchRequest, SearchResponse
from .sessions import SessionError

__all__ = [
    "RequestError",
    "SearchRequest",
    "SearchResponse",
    "SessionError",
    "adapters",
    "dom",
    "engine",
    "models",
    "pipeline",
    "reader",
    "sessions",
    "urls",
]

"""lamtools-rag 引擎包。

v2 规格（docs/rag-plugin-design.md）：
- P1：工作区文档确定性索引 + FTS5/vec0 混合检索 + snippet
- P2：会话历史索引（core.db 只读） + rag_search_sessions
- P3：format router（VLM 页面图批量理解） + 表格文本化 + citation target
- P4：submit_answer 答案闸门（规则层 + 可选 LLM 层）
"""

__version__ = "0.1.0"

"""user:“宿主能力补齐和接口完善与文档更新”+(按当前调用上下文准备真实HTTP字段，不把回调放进JSON请求元数据)。"""
from contextvars import ContextVar


current_extensions = ContextVar("sunday_llm_extensions", default=None)


async def prepare_current(body, metadata):
    provider = current_extensions.get()
    return None if provider is None else await provider(body, metadata)

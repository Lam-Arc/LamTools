import asyncio
from app.core.writer.core_kernel_adapter import WriterKit
from lamtools_core.runtime import RuntimeState, RuntimeTurnInput

async def main():
    kit = WriterKit(work_root="E:\\test")
    state = RuntimeState(session_id="test")
    context = await kit.build_context(
        state,
        RuntimeTurnInput(user_message="开发一个食谱管理应用"),
        history=[],
        step_index=0,
    )
    request = await kit.build_model_request(state, context)
    msgs = request.messages
    print(f"Total messages: {len(msgs)}")
    for i, m in enumerate(msgs):
        print(f"  [{i}] {m.role}: {len(m.content)} chars")
        print(f"      {m.content[:120]}")

asyncio.run(main())

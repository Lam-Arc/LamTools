from lamtools_core.app import OperationResult
from lamtools_core.tool import ToolResult


async def echo(call):
    message = call.arguments.get("message")
    if not isinstance(message, str):
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="message must be a string")
    return ToolResult(call_id=call.id, name=call.name, status="ok", content=message)


async def status(request, *, context):
    runtime = context.service("lifecycle-demo")
    if runtime is None:
        return OperationResult(name=request.name, status="error", payload={"error": "Backend is unavailable"})
    return OperationResult(name=request.name, payload={"ticks": runtime.ticks})

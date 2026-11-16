"""user:“实现这个插件，也正好实验我们的新插件架构”+(UI RPC 与 Agent 工具分离，不新增重复 Agent 工具)。"""
async def dispatch(request, *, context):
    runtime = context.service('easynet')
    if runtime is None:
        raise RuntimeError('网络插件后台未就绪')
    method = request.name.removeprefix('easynet.').removeprefix('network-exploration.')
    if method == 'engine.install':
        return await runtime.install_engine(request.payload)
    return await runtime.call(method, request.payload)

"""user:“该修就修，不用停下”+(通过插件操作暴露工作区文件适配并保留冲突错误)。"""
from . import vault


def read(request, *, work_root):
    payload = request.payload or {}
    # user:“FileNotFoundError: [Errno 2] No such file or directory”+(缺失画图时返回可供界面处理的状态)。
    target = vault._path(work_root, payload.get('path'))
    try:
        return {'content': target.read_bytes().decode('utf-8')}
    except FileNotFoundError:
        return {'missing': True}


def write(request, *, work_root):
    payload = request.payload or {}
    vault.write_text(work_root, payload.get('path'), payload.get('content'), payload.get('original'))
    return {'saved': True}


def put_asset(request, *, work_root):
    return {'path': vault.put_asset(work_root, (request.payload or {}).get('dataURL'))}


def read_asset(request, *, work_root):
    payload = request.payload or {}
    data_url, resolved_path = vault.read_asset(work_root, payload.get('path'), payload.get('drawingPath'))
    return {'dataURL': data_url, 'path': resolved_path}


async def resolve_link(request, *, work_root):
    import asyncio
    payload = request.payload or {}
    path = await asyncio.to_thread(vault.resolve_link, work_root, payload.get('path'), payload.get('drawingPath'))
    return {'path': path}

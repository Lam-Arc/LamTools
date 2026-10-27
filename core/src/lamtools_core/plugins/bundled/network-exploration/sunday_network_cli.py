"""user:“实现这个插件，也正好实验我们的新插件架构”+(Agent 通过已有 command 调用运行中的插件，不增加 Agent 工具或启动第二个控制器)。"""
import json
import os
from pathlib import Path

from lamtools_core.app.live_client import CoreAppServerClient


async def network_call(args):
    payload = json.loads(Path(args.arguments_file).read_text(encoding='utf-8-sig')) if args.arguments_file else {}
    if not isinstance(payload, dict):
        raise ValueError('参数文件必须为 JSON 对象')
    client = CoreAppServerClient(args.base_url or os.environ.get('LAMTOOLS_CORE_API_URL', 'http://127.0.0.1:5172'), path=args.ws_path or os.environ.get('LAMTOOLS_CORE_WS_PATH', '/api/core/app-server'), token=os.environ.get('LAMTOOLS_CORE_TOKEN', ''))
    try:
        await client.connect()
        result = await client.request('network-exploration.' + args.method, payload)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    finally:
        await client.close()

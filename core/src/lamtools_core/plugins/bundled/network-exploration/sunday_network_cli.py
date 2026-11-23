"""user:“实现这个插件，也正好实验我们的新插件架构”+(Agent 通过已有 command 调用运行中的插件，不增加 Agent 工具或启动第二个控制器)。"""
import csv
import json
import os
import subprocess
import urllib.request
from pathlib import Path

from lamtools_core.app.live_client import CoreAppServerClient

DEFAULT_BASE_URL = 'http://127.0.0.1:5172'
DEFAULT_WS_PATH = '/api/core/app-server'
# user:“你需要确保插件内节点正确出现，延迟正常显示，可切换”+(命令必须真的连上正在运行的那个宿主，不能因为端口变成随机值就整体失效)。
HEALTH_MARKER = b'"agent_id":"core-agent"'


def _decode(raw: bytes) -> str:
    for encoding in ('mbcs', 'utf-8', 'gbk'):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode('utf-8', errors='replace')


def _listening_ports() -> list[tuple[int, int]]:
    """枚举本机回环监听端口及其所属进程 id。"""
    if os.name != 'nt':
        return []
    try:
        # user:“启动后台任务时会弹命令行窗，能不能隐藏掉？”+(网络插件读 netstat 也不许弹窗)。
        from lamtools_core.win_spawn import hidden_kwargs

        raw = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, timeout=10, **hidden_kwargs()).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[tuple[int, int]] = []
    for line in _decode(raw).splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[3].upper() != 'LISTENING':
            continue
        host, _, port = parts[1].rpartition(':')
        if not port.isdigit() or not parts[4].isdigit():
            continue
        if host.strip('[]') not in {'127.0.0.1', '0.0.0.0', '::', '::1'}:
            continue
        rows.append((int(port), int(parts[4])))
    return rows


def _process_names() -> dict[int, str]:
    if os.name != 'nt':
        return {}
    try:
        from lamtools_core.win_spawn import hidden_kwargs

        raw = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, timeout=10, **hidden_kwargs()).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    names: dict[int, str] = {}
    for line in _decode(raw).splitlines():
        try:
            fields = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            continue
        if len(fields) >= 2 and fields[1].strip().isdigit():
            names[int(fields[1].strip())] = fields[0].strip().lower()
    return names


def _looks_like_core(port: int) -> bool:
    """只认返回 health 指纹的那个宿主，避免把别的本地服务当成 app-server。"""
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/health')
    # 端口探测必须直连，不能继承系统代理环境变量。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=0.8) as response:
            if response.status != 200:
                return False
            return HEALTH_MARKER in response.read(4096)
    except Exception:  # noqa: BLE001 - 任何失败都只说明这个端口不是宿主
        return False


def discover_base_url(explicit: str = '') -> str:
    """按 显式参数 → 环境变量 → 运行中宿主 的顺序确定 app-server 地址。"""
    for candidate in (explicit, os.environ.get('LAMTOOLS_CORE_API_URL', '')):
        if candidate and candidate.strip():
            return candidate.strip().rstrip('/')
    endpoints = _listening_ports()
    if not endpoints:
        return DEFAULT_BASE_URL
    names = _process_names()
    # 宿主进程优先；同一台机器上还有别的 python 服务，必须排在后面逐一排除。
    def priority(item: tuple[int, int]) -> int:
        name = names.get(item[1], '')
        if name.startswith(('sunday-core', 'sunday-backend', 'sunday')):
            return 0
        if name.startswith('python'):
            return 1
        return 2
    candidates = sorted(endpoints, key=priority)
    tried: set[int] = set()
    for port, _pid in candidates:
        if port in tried or port == 0:
            continue
        tried.add(port)
        if _looks_like_core(port):
            return f'http://127.0.0.1:{port}'
        if len(tried) >= 24:
            break
    return DEFAULT_BASE_URL


async def network_call(args):
    payload = json.loads(Path(args.arguments_file).read_text(encoding='utf-8-sig')) if args.arguments_file else {}
    if not isinstance(payload, dict):
        raise ValueError('参数文件必须为 JSON 对象')
    base_url = discover_base_url(args.base_url)
    ws_path = args.ws_path or os.environ.get('LAMTOOLS_CORE_WS_PATH', DEFAULT_WS_PATH)
    client = CoreAppServerClient(base_url, path=ws_path, token=os.environ.get('LAMTOOLS_CORE_TOKEN', ''))
    try:
        await client.connect()
        result = await client.request('easynet.' + args.method, payload)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    finally:
        await client.close()

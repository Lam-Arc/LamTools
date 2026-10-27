"""user:“实现这个插件，也正好实验我们的新插件架构”+(宿主仅作生命周期和审批桥接，业务全部交由一个 Rust 控制器)。"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
import subprocess
from urllib.parse import unquote, urlparse

from lamtools_core.tool import ToolResult

ROOT = Path(__file__).resolve().parent


def _download_filename(url):
    """Derive the same safe filename the UI uses when only a URL is given."""
    try:
        parsed = urlparse(str(url or "").strip())
    except ValueError:
        return ''
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return ''
    name = unquote(parsed.path.rsplit('/', 1)[-1])
    name = ''.join('_' if ch in '\\/:*?"<>|' or ord(ch) < 32 else ch for ch in name)
    name = name.rstrip(' .')[:200]
    return name or 'download.bin'


class NetworkRuntime:
    def __init__(self, context):
        self.context = context
        self.data_dir = Path(context.app_data_dir or context.data_dir or ROOT) / 'plugins' / 'network-exploration' / 'data'
        self.process = None
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._stopping = False
        self._engine_lock = asyncio.Lock()
        self._job = None

    @property
    def lifecycle_processes(self):
        return [self.process] if self.process is not None and not self._stopping else []

    @property
    def tool_handlers(self):
        return {'network_download': self.network_download}

    async def network_download(self, call):
        # user:“把 download 给做成一个工具，传参下载链接，可指定为前台和后台，以及路径”+(薄封装现有 aria2 队列；后台立即返回，前台轮询到结束或超时)。
        args = call.arguments if isinstance(call.arguments, dict) else {}
        url = str(args.get('url') or '').strip()
        filename = str(args.get('filename') or '').strip() or _download_filename(url)
        if not filename:
            return ToolResult(call_id=call.id, name=call.name, status='failed', error='需要有效的 HTTP/HTTPS 下载链接')
        try:
            connections = int(args.get('connections') or 8)
        except (TypeError, ValueError):
            return ToolResult(call_id=call.id, name=call.name, status='failed', error='connections 必须是 1–16 的整数')
        if not 1 <= connections <= 16:
            return ToolResult(call_id=call.id, name=call.name, status='failed', error='connections 必须是 1–16 的整数')
        payload = {'url': url, 'filename': filename, 'connections': connections}
        directory = str(args.get('directory') or '').strip()
        if directory:
            path = Path(directory).expanduser()
            if not path.is_absolute():
                return ToolResult(call_id=call.id, name=call.name, status='failed', error='directory 必须是绝对路径')
            payload['directory'] = str(path)
        if args.get('proxy') is True:
            payload['proxy'] = True
        try:
            added = await self.call('transfer.add', payload)
        except Exception as exc:  # noqa: BLE001 - tool handlers report failures instead of raising
            return ToolResult(call_id=call.id, name=call.name, status='failed', error=str(exc))
        gid = str(added.get('gid') or '')
        directory = str(added.get('directory') or directory)
        result = {
            'gid': gid,
            'filename': str(added.get('filename') or filename),
            'directory': directory,
            'url': url,
        }
        if args.get('foreground') is not True:
            result['status'] = 'queued'
            return ToolResult(call_id=call.id, name=call.name, status='ok', content=json.dumps(result, ensure_ascii=False))
        try:
            wait_seconds = max(1, min(900, int(args.get('wait_seconds') or 300)))
        except (TypeError, ValueError):
            wait_seconds = 300
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                snapshot = await self.call('transfer.list', {})
            except Exception as exc:  # noqa: BLE001
                result.update({'status': 'unknown', 'error': str(exc)})
                return ToolResult(call_id=call.id, name=call.name, status='failed', content=json.dumps(result, ensure_ascii=False), error=str(exc))
            row = next((item for item in snapshot.get('tasks', []) if item.get('gid') == gid), None)
            status = str(row.get('status') or '') if row else ''
            if status == 'complete':
                result.update({
                    'status': 'complete',
                    'path': str(Path(directory) / result['filename']) if directory else result['filename'],
                    'total_bytes': row.get('totalLength', ''),
                })
                return ToolResult(call_id=call.id, name=call.name, status='ok', content=json.dumps(result, ensure_ascii=False))
            if status in {'error', 'removed'}:
                result['status'] = status
                result['error'] = str(row.get('errorCode') or '下载未完成')
                return ToolResult(call_id=call.id, name=call.name, status='failed', content=json.dumps(result, ensure_ascii=False), error=result['error'])
            await asyncio.sleep(1.5)
        result.update({'status': 'downloading', 'still_running': True, 'waited_seconds': wait_seconds})
        return ToolResult(call_id=call.id, name=call.name, status='ok', content=json.dumps(result, ensure_ascii=False))

    async def start(self, context):
        if self.process is not None and self.process.returncode is None:
            return
        if os.name != 'nt':
            raise RuntimeError('Network Exploration 当前仅支持 Windows 桌面端')
        binary = ROOT / 'bin' / 'sunday-network-controller.exe'
        if not binary.is_file():
            raise RuntimeError('缺少 Rust 控制器，请运行 scripts/build-network-controller.ps1 后重启 Sunday')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Credentials and the temporary Mihomo YAML are private to this Windows
        # account. No elevation, user profile configuration or system ACL is changed.
        account = await asyncio.create_subprocess_exec('whoami', '/user', '/fo', 'csv', '/nh', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        output, _ = await account.communicate()
        import csv
        sid = next(csv.reader(output.decode(errors='replace').strip().splitlines()))[-1]
        if not sid.startswith('S-1-'):
            raise RuntimeError('无法确认当前 Windows 用户，未启动网络服务')
        permissions = await asyncio.create_subprocess_exec('icacls.exe', str(self.data_dir), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        if await permissions.wait() != 0:
            raise RuntimeError('无法保护插件凭据目录，未启动网络服务')
        self._stopping = False
        self.process = await asyncio.create_subprocess_exec(str(binary), str(self.data_dir), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=5 * 1024 * 1024, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            from .process_job import ProcessJob
            self._job = ProcessJob(self.process.pid)
            state = await self.call('status', {})
            # user:“自动通过网络拓展加速（如果需要）”+(启用本机 CONNECT 加速并供宿主分发请求共享，不更改系统代理)。
            from lamtools_core.distribution import register_accelerator
            accelerator = await self.call('accelerator.start', {})
            register_accelerator(self, f"http://127.0.0.1:{int(accelerator['port'])}")
            if any(row.get('status') not in {'complete', 'removed'} for row in state.get('downloads', [])):
                await self.call('transfer.recover', {})
        except BaseException:
            await self.stop()
            raise

    async def call(self, method, params):
        # user:“建议还是集成一下吧，尽量不把这些安装操作留给用户”+(随插件提供并自动准备成熟内核，页面不要求用户安装)。
        if method in {'proxy.start', 'transfer.add', 'transfer.recover'}:
            from .engine_install import ensure_bundled_engine
            async with self._engine_lock:
                await ensure_bundled_engine(ROOT, self.data_dir, 'mihomo' if method == 'proxy.start' else 'aria2')
        async with self._lock:
            process = self.process
            if process is None or process.returncode is not None:
                raise RuntimeError('网络控制器未运行，请重新启用插件；原有状态会保留')
            self._sequence += 1
            request = json.dumps({'id': self._sequence, 'method': method, 'params': params}, ensure_ascii=False).encode() + b'\n'
            if len(request) > 2 * 1024 * 1024:
                raise ValueError('请求超过 2 MB')
            try:
                async with asyncio.timeout(90):
                    process.stdin.write(request)
                    await process.stdin.drain()
                    response = json.loads(await process.stdout.readline())
            except BaseException:
                # A cancelled read must never leave a response for the next call.
                # Closing stdin lets Rust restore its owned network settings.
                if process.stdin:
                    process.stdin.close()
                raise
            if response.get('id') != self._sequence:
                raise RuntimeError('网络控制器响应不匹配')
            if 'error' in response:
                raise ValueError(response['error'])
            result = response['result']
            # user:“自动通过网络拓展加速（如果需要）”+(手动启停加速器时同步宿主路由，避免保留过期端口)。
            if method == 'accelerator.start':
                from lamtools_core.distribution import register_accelerator
                register_accelerator(self, f"http://127.0.0.1:{int(result['port'])}")
            elif method == 'accelerator.stop':
                from lamtools_core.distribution import clear_accelerator
                clear_accelerator(self)
            return result

    async def install_engine(self, params):
        from .engine_install import install_engine
        return await install_engine(self.data_dir, params)

    async def stop(self, context=None):
        from lamtools_core.distribution import clear_accelerator
        clear_accelerator(self)
        self._stopping = True
        process = self.process
        if process is None or process.returncode is not None:
            if self._job:
                self._job.close()
                self._job = None
            self._check_restored()
            return
        if process.stdin:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 25)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        finally:
            if self._job:
                self._job.close()
                self._job = None
        self._check_restored()

    def _check_restored(self):
        state_file = self.data_dir / 'state.json'
        if state_file.is_file():
            state = json.loads(state_file.read_text(encoding='utf-8'))
            if any(row.get('status') in {'applied', 'prepared', 'recovery_required'} for row in state.get('transactions', [])):
                raise RuntimeError('网络配置尚未完全恢复；已保留快照，请在重新启用插件后核对恢复记录')


def create_plugin(context):
    runtime = NetworkRuntime(context)
    return {'runtime': runtime, 'tool_handlers': runtime.tool_handlers}


async def manifest_tool(call):
    return ToolResult(call_id=call.id, name=call.name, status='failed', error='网络运行时尚未启动，请重新启用网络插件')

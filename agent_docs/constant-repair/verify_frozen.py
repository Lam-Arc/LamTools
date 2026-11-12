"""Run the isolated frozen build and inspect it through code only."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
EXE = HERE / 'build/dist/SundayCore/SundayCore.exe'
WORK = Path('E:/SundayWorktrees/constant-repair-20261111')


async def verify_ws(port, network=False):
    import websockets
    async with websockets.connect(f'ws://127.0.0.1:{port}/api/core/app-server', open_timeout=5) as ws:
        calls = [(1, 'initialize', {'clientInfo': {'name': 'constant-repair-check', 'version': '1'},
            'threadId': 'acceptance', 'lastSeenSeq': 0}), (2, 'plugin.list', {})]
        if network:
            calls.extend([(3, 'network-exploration.status', {}), (4, 'plugin.system.disable', {'name': 'network-exploration'})])
        for request_id, method, params in calls:
            await ws.send(json.dumps({'id': request_id, 'method': method, 'params': params}))
            for _ in range(100):
                response = json.loads(await asyncio.wait_for(ws.recv(), 8))
                if response.get('id') == request_id:
                    assert 'result' in response, response.get('error')
                    break
            else:
                raise AssertionError('RPC response not received')


def main():
    # user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(只启动新产物及独立数据目录，验证健康、真实WebSocket和冻结插件，不触碰constant的进程和数据)。
    assert EXE.is_file(), EXE
    home = Path(tempfile.mkdtemp(prefix='frozen-acceptance-', dir=HERE / 'build'))
    plugin = home / 'plugins/constant-build-probe'
    plugin.mkdir(parents=True)
    (plugin / 'plugin.json').write_text(json.dumps({'name': 'constant-build-probe', 'version': '1.0.0',
        'defaultEnabled': True, 'backend': './backend.py'}), encoding='utf-8')
    shutil.copyfile(HERE / 'frozen_probe_backend.py', plugin / 'backend.py')
    states = {}
    for manifest in (WORK / 'core/src/lamtools_core/plugins/bundled').glob('*/plugin.json'):
        states[json.loads(manifest.read_text(encoding='utf-8'))['name']] = {'enabled': False}
    network = '--network' in sys.argv
    if network:
        states['network-exploration'] = {'enabled': True}
    (home / 'plugin-system.jsonc').write_text(json.dumps({'plugins': states}), encoding='utf-8')
    marker = home / 'frozen-probe.json'
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    env = os.environ.copy()
    env.update(LAMTOOLS_HOME=str(home), LAMTOOLS_CORE_DATA_DIR=str(home), LAMTOOLS_CORE_DB=str(home / 'core.db'),
        LAMTOOLS_CORE_CONFIG_ROOT=str(home / 'core'), LAMTOOLS_CORE_WORK_ROOT=str(home / 'workspace'),
        SUNDAY_CORE_HOST='127.0.0.1', LAMCORE_HOST='127.0.0.1', SUNDAY_CORE_PORT=str(port), LAMCORE_PORT=str(port),
        CONSTANT_REPAIR_PROBE_REPORT=str(marker))
    for key in ('LAMTOOLS_SAFE_MODE', 'LAMTOOLS_CORE_ALLOW_LAN', 'LAMTOOLS_CORE_API_TOKEN'):
        env.pop(key, None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result = {'exe': str(EXE), 'data_dir': str(home), 'ok': False}
    with (home / 'process.log').open('wb') as log:
        process = subprocess.Popen([str(EXE)], cwd=home, env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'isolated backend exited with {process.returncode}')
                try:
                    with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                        healthy = response.status == 200
                    if healthy and marker.is_file():
                        break
                except OSError:
                    pass
                time.sleep(0.25)
            else:
                raise RuntimeError('isolated backend did not complete readiness and plugin acceptance')
            probe = json.loads(marker.read_text(encoding='utf-8'))
            assert probe['ok']
            assert all('/core/src/' not in p.replace('\\', '/') for p in probe['origins'].values())
            asyncio.run(verify_ws(port, network=network))
            result.update(ok=True, probe=probe, websocket=True, network_controller=network)
        except Exception as error:
            result.update(error_type=type(error).__name__, error=str(error))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    name = 'frozen-acceptance-network.json' if network else 'frozen-acceptance.json'
    (HERE / name).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""user:“该修就修，该测就测”+(以真实子进程验收大响应、异常恢复、超时与并发启动)。"""
import asyncio
import json
import sys

import pytest

from lamtools_core.mcp.client import MCPClient, MCPError
from lamtools_core.mcp.schemas import MCPServerConfig


SERVER = r'''
import json, os, sys
from pathlib import Path
log = Path(sys.argv[1])
with log.open('a', encoding='utf-8') as f: f.write('start\n')
for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg: continue
    method = msg['method']
    params = msg.get('params') or {}
    name = params.get('name', '')
    if method == 'tools/call':
        with log.open('a', encoding='utf-8') as f: f.write(name + '\n')
    if name == 'silent': continue
    if name == 'large': text = '字' * 110000
    elif name == 'oversize': text = 'x' * 300000
    elif name == 'receipt': text = json.dumps({'success': True, 'data': {'msg_key': '7700000000000000001', 'msg_content': 'receipt proof'}})
    else: text = 'ok'
    result = {'content': [{'type': 'text', 'text': text}]} if method == 'tools/call' else {'capabilities': {}}
    sys.stdout.write(json.dumps({'jsonrpc':'2.0', 'id':msg['id'], 'result':result}, ensure_ascii=False) + '\n')
    sys.stdout.flush()
'''


@pytest.fixture
def server(tmp_path):
    path = tmp_path / 'server.py'
    path.write_text(SERVER, encoding='utf-8')
    log = tmp_path / 'calls.txt'
    return MCPServerConfig(name='probe', command=sys.executable, args=[str(path), str(log)],
                           env={'PYTHONUTF8': '1'}, transport='json_lines', timeout_seconds=2), log


@pytest.mark.asyncio
async def test_large_response_and_subsequent_call_work_in_same_process(server):
    config, log = server
    client = MCPClient(config)
    try:
        result = await client.call_tool('large', {})
        assert result['content'][0]['text'] == '字' * 110000
        process = client._proc
        assert (await client.call_tool('ping', {}))['content'][0]['text'] == 'ok'
        assert client._proc is process
        assert log.read_text().splitlines() == ['start', 'large', 'ping']
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_oversized_response_fails_without_repeating_write_and_next_call_recovers(server, monkeypatch):
    import lamtools_core.mcp.client as module
    monkeypatch.setattr(module, 'MAX_MESSAGE_BYTES', 256 * 1024)
    config, log = server
    client = MCPClient(config)
    try:
        with pytest.raises(MCPError, match='大小|上限|exceed'):
            await client.call_tool('oversize', {})
        assert log.read_text().splitlines().count('oversize') == 1
        assert (await client.call_tool('ping', {}))['content'][0]['text'] == 'ok'
        assert log.read_text().splitlines().count('start') == 2
        assert log.read_text().splitlines().count('oversize') == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_timeout_reports_unknown_outcome_and_does_not_repeat_call(server):
    config, log = server
    config.timeout_seconds = 0.3
    client = MCPClient(config)
    try:
        with pytest.raises(MCPError, match='超时') as error:
            await client.call_tool('silent', {})
        assert '可能已执行' in str(error.value)
        assert (await client.call_tool('ping', {}))['content'][0]['text'] == 'ok'
        assert log.read_text().splitlines() == ['start', 'silent', 'ping']
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_simultaneous_first_calls_share_one_server(server):
    config, log = server
    client = MCPClient(config)
    try:
        one, two = await asyncio.gather(client.call_tool('one', {}), client.call_tool('two', {}))
        assert one['content'][0]['text'] == two['content'][0]['text'] == 'ok'
        assert log.read_text().splitlines().count('start') == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_original_client_and_sunday_receive_same_write_receipt(server):
    # user:“假如说原本可以拿到回执，那么它也要能够拿到回执”+(同一进程协议及回执分别经原版与宿主解析)。
    from pathlib import Path
    config, log = server
    source = Path(__file__).resolve().parents[2] / 'plugins/bili-scroll/vendor/dsh-mcp.mjs'
    script = '''import { McpClient } from %s;
const c=new McpClient({command:%s,args:%s,env:{PYTHONUTF8:'1'}});
try { console.log(JSON.stringify(await c.call('receipt',{}, {timeoutMs:5000}))); } finally { c.stop(); }
''' % (json.dumps(source.as_uri()), json.dumps(config.command), json.dumps(config.args))
    proc = await asyncio.create_subprocess_exec('node', '--input-type=module', '-e', script,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), 10)
    assert proc.returncode == 0, stderr.decode('utf-8', errors='replace')
    original = json.loads(stdout)
    client = MCPClient(config)
    try:
        response = await client.call_tool('receipt', {})
        sunday = json.loads(response['content'][0]['text'])
        assert original == sunday == {'success': True, 'data': {'msg_key': '7700000000000000001', 'msg_content': 'receipt proof'}}
        assert log.read_text().splitlines().count('receipt') == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_concurrent_responses_keep_request_ids_after_large_payload(server):
    # user:“该修就修，该测就测”+(大响应与其他并发请求不能串回执)。
    config, _ = server
    client = MCPClient(config)
    try:
        large, small = await asyncio.gather(client.call_tool('large', {}), client.call_tool('ping', {}))
        assert large['content'][0]['text'] == '字' * 110000
        assert small['content'][0]['text'] == 'ok'
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_close_wakes_inflight_call_without_replaying(server):
    # user:“该修就修，该测就测”+(停止连接时进行中的请求立即失败，避免等待超时或重复写入)。
    config, log = server
    config.timeout_seconds = 10
    client = MCPClient(config)
    task = asyncio.create_task(client.call_tool('silent', {}))
    try:
        async with asyncio.timeout(3):
            while not log.exists() or 'silent' not in log.read_text():
                await asyncio.sleep(0.01)
        await client.close()
        with pytest.raises(MCPError, match='关闭'):
            await asyncio.wait_for(task, 2)
        assert log.read_text().splitlines().count('silent') == 1
    finally:
        if not task.done(): task.cancel()
        await client.close()

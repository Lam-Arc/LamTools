"""Read-only channel fallback, explicit recording-off and backup restoration."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from websockets.asyncio.client import connect

E = Path(__file__).resolve().parent
R = Path('E:/setuptest/rc-0.3.19-upgrade-v5')
os.environ['LAMTOOLS_CORE_CONFIG_ROOT'] = str(R/'channel-config')
from lamtools_core.update import checker
os.environ[checker.SITE_UPDATE_URL_ENV] = 'http://127.0.0.1:1/unavailable'
fallback = checker.check_update()
assert fallback['source'] == 'github', fallback
(E/'github-live-fallback.json').write_text(json.dumps(fallback,indent=2),encoding='utf-8')
print('PASS: live official-source failure falls back to GitHub',flush=True)

def start(executable, data, config, recording):
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); p=s.getsockname()[1]
    env = dict(os.environ,LAMCORE_PORT=str(p),LAMTOOLS_HOME=str(data),LAMTOOLS_CORE_DATA_DIR=str(data),LAMTOOLS_CORE_DB=str(data/'core.db'),LAMTOOLS_CORE_CONFIG_ROOT=str(config.parent),LAMTOOLS_LLM_RAW_RECORDING=recording,LAMTOOLS_LLM_FORENSIC_DIR=str(R/'recording-off'))
    proc = subprocess.Popen([str(executable)],env=env,cwd=data)
    client=httpx.Client(base_url=f'http://127.0.0.1:{p}',trust_env=False,timeout=30)
    for _ in range(120):
        try:
            if client.get('/api/health').is_success: return proc,client,p
        except httpx.HTTPError: pass
        time.sleep(1)
    proc.kill(); raise AssertionError('backend startup')

backup=R/'backup-restored'
shutil.copytree(R/'backup-0.3.18',backup,dirs_exist_ok=True)
proc,client,p=start(R/'installed/lamcore-backend/sunday-core.exe',backup,backup/'core/config','0')
try:
    messages=client.get('/api/core/sessions/upgrade-history/messages').json()
    assert [x['content'] for x in messages] == ['Remember alpha','Alpha remembered'], messages
    assert client.get('/api/core/projects').is_success
    print('PASS: prior stable backend opens restored pre-upgrade backup with history',flush=True)
finally:
    client.close();proc.terminate();proc.wait(30)

with sqlite3.connect(R/'backup-0.3.18/core.db') as before, sqlite3.connect(R/'installed/.lam/core.db') as after:
    old_schema=before.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    new_schema=after.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    assert old_schema==new_schema
    print('PASS: fixture Core table schema unchanged across 0.3.18/0.3.19',flush=True)

class Mock(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200);self.send_header('Content-Type','text/event-stream' if body.get('stream') else 'application/json');self.end_headers()
        if body.get('stream'):
            self.wfile.write(b'data: {"choices":[{"index":0,"delta":{"content":"Recording off acceptance"},"finish_reason":null}]}\n\ndata: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        else:
            self.wfile.write(b'{"choices":[{"message":{"role":"assistant","content":"Recording off acceptance"}}]}')
server=ThreadingHTTPServer(('127.0.0.1',0),Mock)
threading.Thread(target=server.serve_forever,daemon=True).start()
data=R/'recording-off-data';config=data/'core/config'
(config/'providers').mkdir(parents=True,exist_ok=True);(config/'models').mkdir(exist_ok=True)
(config/'providers/mock.jsonc').write_text(json.dumps({'id':'mock','name':'Mock','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'mock','api_type':'openai'}))
(config/'models/mock.jsonc').write_text(json.dumps({'id':'mock','model_id':'mock','provider_id':'mock','provider':'Mock','capability':'text'}))
proc,client,p=start(Path('E:/setuptest/0.3.19/lamcore-backend/sunday-core.exe'),data,config,'0')
async def run():
    async with connect(f'ws://127.0.0.1:{p}/api/core/app-server') as ws:
        async def rpc(i,method,params):
            await ws.send(json.dumps({'id':i,'method':method,'params':params}))
            while True:
                value=json.loads(await asyncio.wait_for(ws.recv(),30))
                if value.get('id')==i:
                    assert 'error' not in value,value
                    return value['result']
        await rpc(1,'initialize',{'clientInfo':{'name':'recording-off-acceptance'}})
        await rpc(2,'turn/start',{'thread_id':'recording-off-check','input':[{'type':'text','text':'Local test'}],'model_id':'mock','permission_preset':'full_access'})
        for i in range(3,63):
            result=await rpc(i,'thread/read',{'thread_id':'recording-off-check'})
            turns=result.get('snapshot',result).get('turns',{})
            if turns and all(t['status']=='completed' for t in turns.values()):break
            await asyncio.sleep(.5)
        assert turns and all(t['status']=='completed' for t in turns.values()),turns
        # A real pre-kernel model configuration error must be visible and must
        # leave the same thread available for another request.
        await rpc(100,'turn/start',{'thread_id':'setup-failure','input':[{'type':'text','text':'Local test'}],'model_id':'missing-model','permission_preset':'full_access'})
        for i in range(101,121):
            result=await rpc(i,'thread/read',{'thread_id':'setup-failure'})
            failed=result.get('snapshot',result).get('turns',{})
            if failed and all(t['status']=='failed' for t in failed.values()):break
            await asyncio.sleep(.5)
        assert failed and all(t['status']=='failed' for t in failed.values()),failed
        await rpc(121,'turn/start',{'thread_id':'setup-failure','input':[{'type':'text','text':'Retry'}],'model_id':'mock','permission_preset':'full_access'})
        for i in range(122,142):
            result=await rpc(i,'thread/read',{'thread_id':'setup-failure'})
            retried=result.get('snapshot',result).get('turns',{})
            if any(t['status']=='completed' for t in retried.values()):break
            await asyncio.sleep(.5)
        assert any(t['status']=='completed' for t in retried.values()),retried
        print('PASS: installed candidate reports model setup failure and permits successful retry',flush=True)
try:
    asyncio.run(run())
    assert not list((R/'recording-off').rglob('metadata.json'))
    print('PASS: installed candidate model test succeeds with recording disabled and creates no captures',flush=True)
finally:
    client.close();proc.terminate();proc.wait(30);server.shutdown()

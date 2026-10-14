"""Local, isolated production-backend and cross-version acceptance. No paid calls."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from websockets.asyncio.client import connect

REPO = Path('E:/LamTools')
EVIDENCE = Path(__file__).resolve().parent
ROOT = Path('E:/setuptest/rc-0.3.19-upgrade-v5')
INSTALL = ROOT / 'installed'
BUNDLE = REPO / 'core/desktop/src-tauri/target/release/bundle/inno'
assert ROOT.resolve().is_relative_to(Path('E:/setuptest'))
ROOT.mkdir(parents=True, exist_ok=True)

def check(condition, label):
    assert condition, label
    print('PASS:', label, flush=True)

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

class Model(BaseHTTPRequestHandler):
    count = 0
    blocked = threading.Event()
    def log_message(self, *args): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream' if body.get('stream') else 'application/json')
        self.end_headers()
        if not body.get('stream'):
            self.wfile.write(json.dumps({'choices':[{'message':{'role':'assistant','content':'Acceptance title'}}]}).encode())
            return
        Model.count += 1
        text = 'INCOMPLETE' if Model.count == 1 else 'Finished after resume'
        self.wfile.write(('data: ' + json.dumps({'choices':[{'index':0,'delta':{'content':text},'finish_reason':None}]}) + '\n\n').encode())
        self.wfile.flush()
        if Model.count == 1:
            Model.blocked.set()
            time.sleep(12)
        try:
            self.wfile.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        except (BrokenPipeError, ConnectionResetError): pass

mock = ThreadingHTTPServer(('127.0.0.1', 0), Model)
threading.Thread(target=mock.serve_forever, daemon=True).start()
config = INSTALL / '.lam/core/config'
env = dict(os.environ, LAMTOOLS_HOME=str(INSTALL / '.lam'), LAMTOOLS_CORE_CONFIG_ROOT=str(config.parent),
           LAMTOOLS_CORE_DATA_DIR=str(INSTALL / '.lam'), LAMTOOLS_CORE_DB=str(INSTALL / '.lam/core.db'),
           LAMTOOLS_LLM_RAW_RECORDING='1', LAMTOOLS_LLM_FORENSIC_DIR=str(ROOT / 'forensics'))
for k in list(env):
    if k.upper().endswith('_PROXY'): env.pop(k)

def install(version):
    setup = BUNDLE / f'Sunday_{version}_x64-setup.exe'
    result = subprocess.run([str(setup), '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/DIR={INSTALL}',f'/LOG={ROOT / (version + "-setup.log")}'], timeout=300)
    check(result.returncode == 0, f'{version} installer succeeds')

def start(version):
    p = port()
    env['LAMCORE_PORT'] = str(p)
    log = open(ROOT / f'{version}-backend-console.log', 'ab')
    proc = subprocess.Popen([str(INSTALL / 'lamcore-backend/sunday-core.exe')], cwd=INSTALL, env=env, stdout=log, stderr=log)
    client = httpx.Client(base_url=f'http://127.0.0.1:{p}', timeout=30, trust_env=False)
    for _ in range(120):
        if proc.poll() is not None: raise RuntimeError(f'{version} backend exited {proc.returncode}')
        try:
            if client.get('/api/health').status_code == 200:
                check(True, f'{version} installed backend startup')
                return proc, client, p
        except httpx.HTTPError: pass
        time.sleep(1)
    proc.kill()
    raise TimeoutError('backend health')

def stop(proc, client):
    client.close()
    proc.terminate()
    proc.wait(30)

def rest(client, method, path, data=None):
    r = client.request(method, '/api/core' + path, json=data)
    check(r.is_success, f'{method} {path}: {r.status_code}')
    return r.json()

async def rpc(ws, method, params={}):
    rpc.counter += 1
    ident = rpc.counter
    await ws.send(json.dumps({'id':ident,'method':method,'params':params}))
    while True:
        value = json.loads(await asyncio.wait_for(ws.recv(), 40))
        if value.get('id') == ident:
            check('error' not in value, f'RPC {method}: {value.get("error", "ok")}')
            return value['result']
rpc.counter = 0

async def session(p):
    ws = await connect(f'ws://127.0.0.1:{p}/api/core/app-server', max_size=32*1024*1024)
    await rpc(ws, 'initialize', {'clientInfo':{'name':'release-acceptance'}})
    return ws

async def packaged(p):
    ws = await session(p)
    try:
        provider = await rpc(ws,'config.provider.create',{'id':'local-mock','name':'Local mock','api_key':'mock-only','base_url':f'http://127.0.0.1:{mock.server_port}/v1','api_type':'openai'})
        check(provider['provider']['api_key'] == '********', 'provider read-back masks credentials')
        model = await rpc(ws,'config.model.create',{'provider_id':'local-mock','model_id':'mock','id':'mock','display_name':'Mock'})
        model_id = model['model']['id']
        result = await rpc(ws,'turn/start',{'thread_id':'resume-acceptance','input':[{'type':'text','text':'Local acceptance'}],'model_id':model_id,'permission_preset':'full_access'})
        turns = result['snapshot']['turns']
        turn = next(iter(turns))
        for _ in range(100):
            if Model.blocked.is_set(): break
            await asyncio.sleep(.1)
        check(Model.blocked.is_set(), 'packaged backend reached local mock stream')
        await rpc(ws,'turn/cancel',{'thread_id':'resume-acceptance','turn_id':turn})
        await asyncio.sleep(1)
        await rpc(ws,'turn/resume',{'thread_id':'resume-acceptance','turn_id':turn})
        for _ in range(60):
            read = await rpc(ws,'thread/read',{'thread_id':'resume-acceptance'})
            snapshot = read.get('snapshot', read)
            if snapshot.get('turns',{}).get(turn,{}).get('status') == 'completed': break
            await asyncio.sleep(.5)
        check(list(snapshot['turns']) == [turn] and snapshot['turns'][turn]['status'] == 'completed', 'Stop/Resume completes same turn in installed backend')
        listing = await rpc(ws,'plugin.list')
        check(any(x['name']=='lifecycle-demo' for x in listing['plugins']), 'external lifecycle plugin discovered')
        disabled = await rpc(ws,'plugin.disable',{'name':'lifecycle-demo'})
        check(not disabled['available'], 'plugin disable revokes availability')
        enabled = await rpc(ws,'plugin.enable',{'name':'lifecycle-demo'})
        check(enabled['available'], 'plugin enable reaches ready')
        await rpc(ws,'workflow.save',{'name':'release-persist','description':'isolated candidate fixture','nodes':[],'edges':[]})
        got = await rpc(ws,'workflow.get',{'name':'release-persist'})
        (ROOT/'workflow-before.json').write_text(json.dumps(got), encoding='utf-8')
    finally: await ws.close()

proc = client = None
try:
    install('0.3.18')
    proc, client, p = start('0.3.18')
    project_dir = INSTALL / 'lam_projects/acceptance'
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir/'keep.txt').write_text('project content',encoding='utf-8')
    project = rest(client,'POST','/projects',{'work_root':str(project_dir),'name':'Upgrade fixture'})
    rest(client,'POST','/sessions',{'id':'upgrade-history','member_id':'core','title':'Preserved history','status':'idle'})
    rest(client,'POST','/sessions/upgrade-history/messages',{'id':'upgrade-user','role':'user','content':'Remember alpha'})
    rest(client,'POST','/sessions/upgrade-history/messages',{'id':'upgrade-reply','role':'assistant','content':'Alpha remembered'})
    history = rest(client,'GET','/sessions/upgrade-history/messages')
    projects = rest(client,'GET','/projects')
    stop(proc,client); proc = client = None
    (config/'settings.jsonc').write_text('{"core":{"network":{"proxy":"","no_proxy":"","ca_cert":""},"keepAwake":false}}',encoding='utf-8')
    (config/'providers').mkdir(exist_ok=True)
    (config/'providers/upgrade-provider.jsonc').write_text('{"id":"upgrade-provider","name":"Upgrade provider","api_key":"isolated-secret","base_url":"http://127.0.0.1:1/v1"}',encoding='utf-8')
    (config/'models').mkdir(exist_ok=True)
    (config/'models/upgrade-model.jsonc').write_text('{"id":"upgrade-model","model_id":"upgrade-model","provider_id":"upgrade-provider","provider":"Upgrade provider"}',encoding='utf-8')
    protected = [config/'settings.jsonc',config/'providers/upgrade-provider.jsonc',config/'models/upgrade-model.jsonc',project_dir/'keep.txt']
    hashes = {str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in protected}
    shutil.copytree(INSTALL/'.lam',ROOT/'backup-0.3.18',dirs_exist_ok=True)
    install('0.3.19')
    check(all(hashlib.sha256(Path(x).read_bytes()).hexdigest()==h for x,h in hashes.items()), 'upgrade preserves configuration, provider and project bytes')
    proc, client, p = start('0.3.19')
    check(any(x['id']=='upgrade-provider' for x in rest(client,'GET','/config/providers')['providers']), 'upgraded provider configuration resolves')
    check(any(x['id']=='upgrade-model' for x in rest(client,'GET','/config/models')['models']), 'upgraded model configuration resolves')
    check(rest(client,'GET','/sessions/upgrade-history/messages') == history, '0.3.18 conversation history retained by 0.3.19')
    check(rest(client,'GET','/projects') == projects, 'project registry retained by upgrade')
    stop(proc,client); proc = client = None
    plugins = INSTALL/'.lam/plugins'
    for name, source in [('lifecycle-demo',REPO/'core/examples/plugins/lifecycle-demo'),('workflow',REPO/'core/src/lamtools_core/plugins/bundled/workflow')]:
        shutil.copytree(source,plugins/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    proc, client, p = start('0.3.19-functional')
    asyncio.run(packaged(p))
    stop(proc,client); proc = client = None
    manifests = list((ROOT/'forensics').rglob('metadata.json'))
    check(bool(manifests), 'recording enabled through installed backend environment')
    proc, client, p = start('0.3.19-reconnect')
    async def reconnect():
        ws = await session(p)
        try:
            got = await rpc(ws,'workflow.get',{'name':'release-persist'})
            check(got == json.loads((ROOT/'workflow-before.json').read_text()), 'Workflow persisted across packaged backend restart')
        finally: await ws.close()
    asyncio.run(reconnect())
    stop(proc,client); proc = client = None
    # Selecting the mock model intentionally updates modelSceneMemory. Compare
    # rollback against the latest settings, and preserve the original user fields.
    settings = json.loads((config/'settings.jsonc').read_text(encoding='utf-8'))
    check(settings['core']=={'network':{'proxy':'','no_proxy':'','ca_cert':''},'keepAwake':False}, 'functional writes retain original user settings')
    rollback_hashes = {str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in protected}
    install('0.3.18')
    proc, client, p = start('0.3.18-rollback')
    check(any(x['id']=='upgrade-provider' for x in rest(client,'GET','/config/providers')['providers']), 'rollback provider configuration resolves')
    check(any(x['id']=='upgrade-model' for x in rest(client,'GET','/config/models')['models']), 'rollback model configuration resolves')
    check(rest(client,'GET','/sessions/upgrade-history/messages') == history, 'rollback reads preserved history after candidate writes')
    check(rest(client,'GET','/projects') == projects, 'rollback retains project registry')
    stop(proc,client); proc = client = None
    check(all(hashlib.sha256(Path(x).read_bytes()).hexdigest()==h for x,h in rollback_hashes.items()), 'rollback preserves current protected files')
    print('PACKAGED AND CROSS-VERSION ACCEPTANCE PASSED',flush=True)
finally:
    if proc is not None: stop(proc,client)
    mock.shutdown()

"""user:“给我把 2 阶段做完，前端除外”+(DeepSeek实际授权协议、原DPAPI凭据及过期令牌CAS，不登录真实用户账户)。"""
import asyncio
import base64
import hashlib
import json
from urllib.parse import urlsplit,parse_qs

import pytest
from aiohttp import web

from lamtools_core.plugin_system import PluginContext
from lamtools_core.plugin_system.secrets import PluginSecretStore


@pytest.fixture
async def account_env(tmp_path):
    ctx=PluginContext(tmp_path,_secret_store=PluginSecretStore(tmp_path/'secrets'))
    ctx._begin_registration_scope('account-owner',1)
    try:
        yield ctx
    finally:
        await ctx._registration_scope.dispose()


@pytest.fixture
async def platform_server():
    state={'requests':[],'grant':'test-grant-one','profile_entered':asyncio.Event(),'profile_release':asyncio.Event(),'block_profile':False,'expire_profile':False}
    async def handle(request):
        body=await request.json() if request.can_read_body else None
        state['requests'].append((request.path,dict(request.headers),body))
        path=request.path
        if path.endswith('/auth_init'):
            state['init']=body
            data={'authorize_url':state['origin']+'/dsh/authorize?state='+body['state'],'authorize_id':'attempt-id','expires_in':60}
        elif path.endswith('/auth_exchange'):
            challenge=base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'].encode()).digest()).rstrip(b'=').decode()
            assert challenge==state['init']['code_challenge'] and body['redirect_uri']==state['init']['redirect_uri']
            data={'token':state['grant'],'authorized_url':state['origin']+'/dsh/authorized'}
        elif path.endswith('/users/current'):
            if state['block_profile']:
                state['profile_entered'].set()
                await state['profile_release'].wait()
            if state['expire_profile']:
                return web.Response(status=401)
            assert request.headers['x-dsh-auth-token']==state['grant']
            data={'id':'user-one','email':'test@example.invalid','id_profile':{'name':'Test','picture':None},'token':'must-not-project'}
        elif path.endswith('/get_user_summary'):
            data={'normal_wallets':[{'currency':'USD','balance':'1.5'}],'bonus_wallets':[]}
        else:
            data={}
        return web.json_response({'code':0,'data':{'biz_code':0,'biz_data':data}})
    app=web.Application()
    app.router.add_route('*','/{path:.*}',handle)
    runner=web.AppRunner(app,handler_cancellation=True,shutdown_timeout=0.5)
    await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0)
    await site.start()
    state['origin']='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
    try:
        yield state
    finally:
        state['profile_release'].set()
        await runner.cleanup()


def client(ctx,server):
    return ctx.deepseek_account.open(platform_origin=server['origin'],inference_origin=server['origin'],allow_loopback_http=True)


async def answer(request):
    return {'code':'test-code','state':parse_qs(urlsplit(request['authorize_url']).query)['state'][0]}


@pytest.mark.asyncio
async def test_credential_cas_has_one_winner_and_never_deletes_replacement(account_env):
    ctx=account_env
    results=await asyncio.gather(*[asyncio.to_thread(ctx.credentials.compare_exchange,'TEST_ACCOUNT',expected=None,value=value) for value in ['one','two']])
    assert sum(results)==1
    actual=ctx.credentials.resolve('TEST_ACCOUNT').value
    assert not ctx.credentials.compare_exchange('TEST_ACCOUNT',expected='stale',value=None)
    assert ctx.credentials.resolve('TEST_ACCOUNT').value==actual


@pytest.mark.asyncio
async def test_actual_pkce_exchange_persists_origin_bound_grant_and_safe_profile(account_env,platform_server):
    ctx=account_env
    api=client(ctx,platform_server)
    assert not (await api.get_state())['signed_in']
    result=await api.sign_in(callback_origin='http://127.0.0.1:8765',prompt=answer,timeout=5)
    assert result['signed_in'] and 'test-grant' not in str(result)
    assert await api.resolve_token(platform_server['origin']+'/v1/chat/completions')=='test-grant-one'
    assert await api.resolve_token('https://elsewhere.invalid/v1') is None
    profile=await api.get_profile()
    assert profile['id']=='user-one' and profile['name']=='Test' and 'token' not in profile
    balance=await api.get_balance()
    assert balance['normal_wallets'][0]['balance']=='1.5'
    await ctx._registration_scope.dispose()
    ctx._begin_registration_scope('account-owner',2)
    reloaded=client(ctx,platform_server)
    assert (await reloaded.get_state())['signed_in']
    assert not (await reloaded.sign_out())['signed_in']
    assert await reloaded.resolve_token(platform_server['origin']) is None


@pytest.mark.asyncio
async def test_wrong_callback_state_never_exchanges_or_commits(account_env,platform_server):
    from lamtools_core.plugin_system.account_access import AccountAccessError
    api=client(account_env,platform_server)
    async def wrong(request):
        return {'code':'test-code','state':'wrong-state'}
    with pytest.raises(AccountAccessError):
        await api.sign_in(callback_origin='http://127.0.0.1:8765',prompt=wrong,timeout=5)
    assert not (await api.get_state())['signed_in']
    assert not any(path.endswith('/auth_exchange') for path,_,_ in platform_server['requests'])


@pytest.mark.asyncio
async def test_cancel_authorization_and_expired_old_query_preserve_new_grant(account_env,platform_server):
    from lamtools_core.plugin_system.account_access import AccountAccessError
    api=client(account_env,platform_server)
    entered,finished=asyncio.Event(),asyncio.Event()
    async def wait(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
    task=asyncio.create_task(api.sign_in(callback_origin='http://127.0.0.1:8765',prompt=wait,timeout=10))
    await asyncio.wait_for(entered.wait(),3)
    await api.cancel_sign_in()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set() and not (await api.get_state())['signed_in']
    await api.sign_in(callback_origin='http://127.0.0.1:8765',prompt=answer,timeout=5)
    platform_server['block_profile']=platform_server['expire_profile']=True
    query=asyncio.create_task(api.get_profile())
    await asyncio.wait_for(platform_server['profile_entered'].wait(),3)
    saved=account_env.credentials.resolve(api._grant_key).value
    replacement=json.loads(saved);replacement['token']='test-grant-new'
    assert account_env.credentials.compare_exchange(api._grant_key,expected=saved,value=json.dumps(replacement))
    platform_server['profile_release'].set()
    with pytest.raises(AccountAccessError):
        await query
    assert await api.resolve_token(platform_server['origin'])=='test-grant-new'


@pytest.mark.asyncio
async def test_account_policy_rejects_unsafe_origins_and_owner_isolation(account_env,platform_server):
    from lamtools_core.plugin_system.account_access import AccountAccessError
    ctx=account_env
    for origin in ['http://platform.deepseek.com','https://user:password@host/','https://host/path','https://host/?secret=x']:
        with pytest.raises(AccountAccessError):
            ctx.deepseek_account.open(platform_origin=origin)
    api=client(ctx,platform_server)
    await api.sign_in(callback_origin='http://127.0.0.1:8765',prompt=answer,timeout=5)
    other=ctx.for_work_root(ctx.work_root)
    other._registration_scope=None
    other._begin_registration_scope('other-owner',1)
    try:
        assert not (await client(other,platform_server).get_state())['signed_in']
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_login_commit_does_not_overwrite_a_newer_grant(account_env,platform_server):
    from lamtools_core.plugin_system.account_access import AccountAccessError
    api=client(account_env,platform_server)
    replacement=json.dumps({'version':1,'issuer':platform_server['origin'],'token':'newer-grant'})
    async def changed(request):
        account_env.credentials.set(api._grant_key,replacement)
        return await answer(request)
    with pytest.raises(AccountAccessError):
        await api.sign_in(callback_origin='http://127.0.0.1:8765',prompt=changed,timeout=5)
    assert account_env.credentials.resolve(api._grant_key).value==replacement


@pytest.mark.asyncio
async def test_existing_authorization_commit_keeps_its_original_behavior(account_env):
    async def run(control):
        control.commit('legacy-value')
    account_env.authorization.register_flow('legacy',label='Legacy',methods=['key'],credential='LEGACY_TEST',run=run)
    result=await account_env.authorization.begin('legacy',method='key',timeout=3)
    assert result['status']=='authorized' and account_env.credentials.resolve('LEGACY_TEST').value=='legacy-value'


@pytest.mark.asyncio
async def test_account_query_holds_original_scope_until_caller_cancellation(account_env,platform_server):
    api=client(account_env,platform_server)
    await api.sign_in(callback_origin='http://127.0.0.1:8765',prompt=answer,timeout=5)
    platform_server['block_profile']=True
    query=asyncio.create_task(api.get_profile())
    await asyncio.wait_for(platform_server['profile_entered'].wait(),3)
    assert query in account_env._registration_scope._calls
    query.cancel()
    with pytest.raises(asyncio.CancelledError):
        await query
    assert query not in account_env._registration_scope._calls


@pytest.mark.asyncio
async def test_account_timeout_variants_share_grant_without_flow_collision(account_env,platform_server):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(不同请求期限可独立打开，仍共享同一来源凭据)。
    first=client(account_env,platform_server)
    second=account_env.deepseek_account.open(platform_origin=platform_server['origin'],
        inference_origin=platform_server['origin'],allow_loopback_http=True,request_timeout=3)
    assert second is not first
    assert second is account_env.deepseek_account.open(platform_origin=platform_server['origin'],
        inference_origin=platform_server['origin'],allow_loopback_http=True,request_timeout=3)
    await second.sign_in(callback_origin='http://127.0.0.1:8765',prompt=answer,timeout=5)
    assert (await first.get_state())['signed_in']
    await first.sign_out()
    assert not (await second.get_state())['signed_in']


@pytest.mark.asyncio
async def test_non_ascii_callback_state_is_protocol_error_and_cancels_remote_attempt(account_env,platform_server):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(无效回调须返回稳定协议错误并撤销已初始化授权)。
    from lamtools_core.plugin_system.account_access import AccountAccessError
    api=client(account_env,platform_server)
    async def malformed(request):
        return {'code':'test-code','state':'无效状态'}
    with pytest.raises(AccountAccessError) as error:
        await api.sign_in(callback_origin='http://127.0.0.1:8765',prompt=malformed,timeout=5)
    assert error.value.code=='account/protocol'
    paths=[path for path,_,_ in platform_server['requests']]
    assert any(path.endswith('/auth_cancel') for path in paths)
    assert not any(path.endswith('/auth_exchange') for path in paths)
    assert not (await api.get_state())['signed_in']

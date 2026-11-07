"""user:“给我把 2 阶段做完，前端除外”+(DeepSeek账户沿官方Platform协议、原授权控制器和加密凭据，不把普通key存储冒充登录)。"""
import asyncio
import base64
import hashlib
import hmac
from importlib.metadata import version,PackageNotFoundError
import json
import math
import platform
import re
import secrets
import time
from urllib.parse import urlsplit,urlunsplit
import uuid
from functools import wraps

import httpx

from lamtools_core.async_tasks import finish_on_cancel
from lamtools_core.config.network import httpx_client_kwargs
from .authorization_access import AuthorizationError


class AccountAccessError(RuntimeError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


def _error(code):
    return AccountAccessError('account/'+code,'DeepSeek account operation failed: '+code)


def _origin(value,allow_loopback,*,destination=False):
    try:
        if type(value) is not str or not 1<=len(value)<=4096 or any(c.isspace() or ord(c)<32 for c in value):
            raise ValueError
        p=urlsplit(value)
        if (not p.hostname or p.username is not None or p.password is not None or p.port==0
                or p.scheme not in {'http','https'} or (not destination and (p.path not in {'','/'} or p.query or p.fragment))):
            raise ValueError
        if p.scheme=='http' and not (allow_loopback and p.hostname in {'localhost','127.0.0.1','::1'}):
            raise ValueError
        host='['+p.hostname+']' if ':' in p.hostname else p.hostname
        port=p.port
        if port is not None and port!=(443 if p.scheme=='https' else 80):
            host+=':'+str(port)
        return p.scheme+'://'+host
    except (ValueError,TypeError):
        raise _error('invalid-origin') from None


def _browser_url(value,origin,path,allow_loopback):
    if _origin(value,allow_loopback,destination=True)!=origin:
        raise _error('protocol')
    parsed=urlsplit(value)
    if parsed.path!=path or parsed.fragment:
        raise _error('protocol')
    return value


def _callback(value):
    try:
        if type(value) is not str or len(value)>2048 or any(c.isspace() or ord(c)<32 for c in value):
            raise ValueError
        p=urlsplit(value)
        if (p.scheme!='http' or p.hostname not in {'localhost','127.0.0.1','::1'} or not p.port
                or p.path not in {'','/'} or p.query or p.fragment or p.username is not None or p.password is not None):
            raise ValueError
        host='['+p.hostname+']' if ':' in p.hostname else p.hostname
        return 'http://'+host+':'+str(p.port)
    except (TypeError,ValueError):
        raise _error('invalid-callback') from None


def _leased(method):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(普通账户HTTP查询也使用原作用域租约，停用不能先于已接收请求排空)。
    @wraps(method)
    async def call(self,*args,**kwargs):
        self._check()
        self._scope.acquire()
        try:
            return await method(self,*args,**kwargs)
        finally:
            self._scope.release()
    return call


class PluginDeepSeekAccountAPI:
    def __init__(self,context,scope):
        self._context,self._scope=context,scope

    def open(self,*,platform_origin='https://platform.deepseek.com',inference_origin='https://api.deepseek.com',
             allow_loopback_http=False,request_timeout=10,locale='en-US',client_version=None,timezone_offset_seconds=0):
        self._scope.check_open()
        if (type(allow_loopback_http) is not bool or type(request_timeout) not in {int,float}
                or not math.isfinite(request_timeout) or not 0<request_timeout<=30 or type(locale) is not str or len(locale)>32
                or type(timezone_offset_seconds) is not int or not -86400<=timezone_offset_seconds<=86400):
            raise _error('invalid-config')
        if client_version is None:
            try:
                client_version=version('lamtools-core')
            except PackageNotFoundError:
                client_version='0'
        if type(client_version) is not str or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}',client_version):
            raise _error('invalid-config')
        origin=_origin(platform_origin,allow_loopback_http)
        inference=_origin(inference_origin,allow_loopback_http)
        identity=(client_version,'zh_CN' if locale.lower().split('-')[0].split('_')[0]=='zh' else 'en_US',timezone_offset_seconds)
        cache=getattr(self._scope,'_deepseek_account_clients',None)
        if cache is None:
            cache={}
            self._scope._deepseek_account_clients=cache
        key=(str(self._context.work_root),origin,inference,allow_loopback_http,request_timeout,identity,id(self._context._secret_store))
        if key not in cache:
            if len(cache)>=8:
                raise _error('busy')
            cache[key]=DeepSeekAccountClient(self._context,self._scope,origin,inference,allow_loopback_http,request_timeout,identity)
        return cache[key]


class DeepSeekAccountClient:
    def __init__(self,context,scope,origin,inference,allow_loopback,timeout,identity):
        self._context,self._scope=context,scope
        self._credentials=context.credentials
        self._origin,self._inference,self._allow_loopback,self._timeout=origin,inference,allow_loopback,timeout
        owner=json.dumps([str(context.work_root),origin,inference])
        digest=hashlib.sha256(owner.encode()).hexdigest()[:24]
        self._grant_key,self._device_key='DEEPSEEK_ACCOUNT_'+digest,'DEEPSEEK_DEVICE_'+digest
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(授权流标识与客户端缓存配置一致，不同期限实例不能抢占同一注册；凭据仍按来源共享)。
        self._flow='dsa_'+hashlib.sha256(json.dumps([scope.owner,owner,identity,allow_loopback,timeout,id(context._secret_store)]).encode()).hexdigest()[:32]
        self._headers={'x-client-bundle-id':'','x-client-platform':'desktop-win','x-client-version':identity[0],
                       'x-client-locale':identity[1],'x-client-timezone-offset':str(identity[2])}
        self._task,self._options,self._attempt,self._profile=None,None,None,None
        context.authorization.register_flow(self._flow,label='DeepSeek account (account.sign_in)',methods=['browser-code'],
                                            credential=self._grant_key,run=self._authorize)

    def _check(self):
        self._scope.check_open()
        if self._context.credentials._store is not self._credentials._store:
            raise _error('host-changed')

    def _grant(self):
        self._check()
        observed=self._credentials.resolve(self._grant_key)
        if observed is None:
            return None,None
        try:
            grant=json.loads(observed.value)
            token=grant['token']
            if (type(grant) is not dict or type(grant.get('version')) is not int or grant.get('version')!=1 or grant.get('issuer')!=self._origin
                    or type(token) is not str or not re.fullmatch(r'[\x21-\x7e]{1,16384}',token)):
                raise ValueError
            return observed.value,grant
        except (ValueError,TypeError,KeyError):
            raise _error('storage') from None

    async def _http(self,path,*,body=None,token=None,method='POST'):
        headers=dict(self._headers)
        if token is not None:
            headers['x-dsh-auth-token']=token
        endpoint=self._origin+path
        kwargs={'trust_env':False} if urlsplit(self._origin).scheme=='http' else httpx_client_kwargs(endpoint)
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(timeout=self._timeout,follow_redirects=False,**kwargs) as client:
                    async with client.stream(method,endpoint,headers=headers,**({'json':body} if body is not None else {})) as response:
                        if token is not None and response.status_code==401:
                            raise _error('expired')
                        if not 200<=response.status_code<300:
                            raise _error('network')
                        data=bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data)>65536:
                                raise _error('protocol')
            payload=json.loads(data,parse_constant=lambda value:(_ for _ in ()).throw(ValueError()))
            if type(payload) is dict and payload.get('code')==40003 and token is not None:
                raise _error('expired')
            if (type(payload) is not dict or type(payload.get('code')) is not int or payload['code']!=0
                    or type(payload.get('data')) is not dict or type(payload['data'].get('biz_code')) is not int
                    or payload['data']['biz_code']!=0 or 'biz_data' not in payload['data']):
                raise _error('protocol')
            return payload['data']['biz_data']
        except AccountAccessError:
            raise
        except (ValueError,TypeError):
            raise _error('protocol') from None
        except (httpx.HTTPError,TimeoutError):
            raise _error('network') from None

    async def get_state(self):
        _,grant=self._grant()
        return {'signed_in':grant is not None,'issuer':self._origin,'attempt':dict(self._attempt) if self._attempt else None}

    async def sign_in(self,*,callback_origin,prompt,timeout=300):
        self._check()
        callback=_callback(callback_origin)
        if not callable(prompt):
            raise _error('interaction-unavailable')
        if self._task is not None and not self._task.done():
            raise _error('busy')
        self._options={'callback':callback,'expected':self._grant()[0]}
        self._task=asyncio.current_task()
        try:
            result=await self._context.authorization.begin(self._flow,method='browser-code',prompt=prompt,timeout=timeout)
        except AuthorizationError:
            raise _error('authorization-failed') from None
        finally:
            self._task,self._options,self._attempt=None,None,None
        state=await self.get_state()
        state['authorization_status']=result['status']
        return state

    async def _authorize(self,control):
        options=self._options
        if options is None:
            raise _error('interaction-unavailable')
        verifier=secrets.token_urlsafe(32)
        state=secrets.token_urlsafe(32)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        redirect=options['callback']+'/oauth/callback'
        authorize_id=None
        committed=False
        try:
            init=await self._http('/auth-api/v0/dsh/auth_init',body={'code_challenge':challenge,'code_challenge_method':'S256',
                'state':state,'redirect_uri':redirect,'locale':self._headers['x-client-locale'],'login_source':'desktop'})
            if (type(init) is not dict or type(init.get('authorize_id')) is not str or not init['authorize_id']
                    or type(init.get('expires_in')) not in {int,float} or not math.isfinite(init['expires_in']) or init['expires_in']<=0):
                raise _error('protocol')
            authorize_id=init['authorize_id']
            url=_browser_url(init.get('authorize_url'),self._origin,'/dsh/authorize',self._allow_loopback)
            expires=time.monotonic()+min(300,init['expires_in'])
            self._attempt={'phase':'waiting-browser','authorize_url':url}
            async with asyncio.timeout(max(0,expires-time.monotonic())):
                reply=await control.prompt({'authorize_url':url,'callback_uri':redirect})
            # user:“完成真实接口、参数/错误、作用域、取消/清理”+(先校验ASCII状态再恒时比较，异常回调不能泄漏内部TypeError)。
            if (type(reply) is not dict or type(reply.get('state')) is not str or not reply['state'].isascii() or not hmac.compare_digest(reply['state'],state)
                    or type(reply.get('code')) is not str or not re.fullmatch(r'[\x21-\x7e]{1,4096}',reply['code'])):
                raise _error('protocol')
            self._attempt={'phase':'exchanging'}
            device=self._credentials.resolve(self._device_key)
            if device is None:
                self._credentials.compare_exchange(self._device_key,expected=None,value=str(uuid.uuid4()))
                device=self._credentials.resolve(self._device_key)
            try:
                device_id=str(uuid.UUID(device.value))
            except (ValueError,AttributeError):
                raise _error('storage') from None
            result=await self._http('/auth-api/v0/dsh/auth_exchange',body={'code':reply['code'],'code_verifier':verifier,
                'redirect_uri':redirect,'device_id':device_id,'device_model':'win32-'+platform.machine().lower(),'os_version':platform.version()})
            if type(result) is not dict or type(result.get('token')) is not str or not re.fullmatch(r'[\x21-\x7e]{1,16384}',result['token']):
                raise _error('protocol')
            _browser_url(result.get('authorized_url'),self._origin,'/dsh/authorized',self._allow_loopback)
            if time.monotonic()>=expires:
                raise _error('expired')
            self._check()
            control.commit(json.dumps({'version':1,'issuer':self._origin,'token':result['token']}),expected_value=options['expected'])
            committed=True
        except TimeoutError:
            raise _error('expired') from None
        finally:
            if authorize_id is not None and not committed:
                try:
                    await self._http('/auth-api/v0/dsh/auth_cancel',body={'authorize_id':authorize_id,'code_verifier':verifier})
                except (AccountAccessError,asyncio.CancelledError):
                    pass

    async def cancel_sign_in(self):
        self._check()
        task=self._task
        if task is asyncio.current_task():
            raise _error('self-cancel')
        if task is not None and not task.done():
            task.cancel()
            async def settle():
                await asyncio.gather(task,return_exceptions=True)
            await finish_on_cancel(settle(),name='deepseek-account-cancel')
        return await self.get_state()

    async def resolve_token(self,url):
        self._check()
        try:
            if _origin(url,self._allow_loopback,destination=True)!=self._inference:
                return None
        except AccountAccessError:
            return None
        _,grant=self._grant()
        return grant['token'] if grant is not None else None

    async def reject_token(self,token):
        raw,grant=self._grant()
        if grant is not None and grant['token']==token:
            self._credentials.compare_exchange(self._grant_key,expected=raw,value=None)
            self._profile=None

    @_leased
    async def sign_out(self):
        self._check()
        await self.cancel_sign_in()
        raw,grant=self._grant()
        if grant is not None and self._credentials.compare_exchange(self._grant_key,expected=raw,value=None):
            self._profile=None
            try:
                await self._http('/auth-api/v0/users/logout',token=grant['token'])
            except AccountAccessError:
                pass
        return await self.get_state()

    async def _detail(self,path):
        raw,grant=self._grant()
        if grant is None:
            return None,None
        try:
            result=await self._http(path,token=grant['token'],method='GET')
        except AccountAccessError as error:
            if error.code=='account/expired':
                await self.reject_token(grant['token'])
            raise
        return (raw,result) if self._grant()[0]==raw else (None,None)

    @_leased
    async def get_profile(self):
        raw,value=await self._detail('/auth-api/v0/users/current')
        if value is None:
            return None
        if type(value) is not dict or type(value.get('email')) is not str or (value.get('id') is not None and type(value['id']) is not str):
            raise _error('protocol')
        identity=value.get('id_profile') or {}
        if type(identity) is not dict or any(identity.get(k) is not None and type(identity[k]) is not str for k in ('name','picture')):
            raise _error('protocol')
        contact=value.get('mobile') or value.get('mobile_number') or value['email'] or None
        if contact is not None and type(contact) is not str:
            raise _error('protocol')
        result={'id':value.get('id'),'name':identity.get('name') or None,'avatar_url':identity.get('picture') or None,'contact':contact}
        self._profile=(raw,result)
        return dict(result)

    @_leased
    async def get_balance(self):
        _,value=await self._detail('/api/v0/users/get_user_summary')
        if value is None:
            return None
        result={}
        for key in ('normal_wallets','bonus_wallets'):
            rows=value.get(key) if type(value) is dict else None
            if type(rows) is not list or len(rows)>256 or any(type(row) is not dict or type(row.get('currency')) is not str or row.get('currency') not in {'CNY','USD'}
                or type(row.get('balance')) is not str or not re.fullmatch(r'-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',row['balance']) for row in rows):
                raise _error('protocol')
            result[key]=[{'currency':row['currency'],'balance':row['balance']} for row in rows]
        return result

    async def get_platform_session(self):
        raw,grant=self._grant()
        if grant is None:
            return None
        return {'origin':self._origin,'token':grant['token'],'user_id':self._profile[1]['id'] if self._profile and self._profile[0]==raw else None}

    async def get_device_identity(self):
        self._check()
        device=self._credentials.resolve(self._device_key)
        raw,_=self._grant()
        return {'device_id':device.value if device else None,'user_id':self._profile[1]['id'] if self._profile and self._profile[0]==raw else None,
                'os_version':platform.version()}

"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(会话消息非法Unicode在原事务派发前拒绝)。"""
import pytest
from .test_plugin_session_control import host

@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['session_id', 'request_id', 'text', 'queue_item_id'])
async def test_invalid_unicode_is_rejected_before_native_session_write(host, monkeypatch, field):
    live, service = host
    await service.create(session_id='s')
    async def forbidden(*args, **kwargs): pytest.fail('invalid input reached native write')
    monkeypatch.setattr(live.host, 'execute', forbidden)
    with pytest.raises(ValueError, match='UTF-8'):
        if field == 'queue_item_id':
            await service.update_queue('s', '\ud800', text='valid')
        else:
            args={'session_id':'s','request_id':'valid','text':'valid'}; args[field]='\ud800'
            await service.prompt(**args)
    assert (await service.state('s')).queued_count == 0

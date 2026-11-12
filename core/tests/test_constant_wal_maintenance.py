import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.app.sqlite_write import wal_maintenance_once


# user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(读池耗尽时后台检查点仍可运行，避免错误相互放大；不能创建丢失的数据库)。
@pytest.mark.asyncio
async def test_checkpoint_does_not_need_a_free_read_pool_slot(tmp_path):
    path = tmp_path / 'core.db'
    engine = create_async_engine('sqlite+aiosqlite:///' + path.as_posix(),
                                  pool_size=1, max_overflow=0, pool_timeout=0.05)
    try:
        async with engine.begin() as session:
            await session.execute(text('PRAGMA journal_mode=WAL'))
            await session.execute(text('CREATE TABLE evidence (value TEXT)'))
            await session.execute(text("INSERT INTO evidence VALUES ('retained')"))
        async with engine.connect():
            result = await wal_maintenance_once(async_sessionmaker(engine))
            assert result['state'] == 'ok'
            assert result['pending'] == 0
        async with engine.connect() as connection:
            assert await connection.scalar(text('SELECT value FROM evidence')) == 'retained'
    finally:
        await engine.dispose()

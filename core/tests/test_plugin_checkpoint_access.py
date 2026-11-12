"""user:“继续，把 2 阶段都做完”+(检查点公开接口走原数据库与恢复操作，不恢复工作区文件、不伪造DSH日志)。"""
import pytest

from lamtools_core.checkpoint import register_checkpoint_operations
from lamtools_core.app.core_db import CoreRuntimeSession
from .test_plugin_working_directory import env
from .test_core_checkpoint_graph import _append_production_turn, _runtime, _tool_call_history








@pytest.fixture
async def setup(env):
    ctx, store, sessions, project = env
    db = store._db_provider()
    catalog = sessions._context().operations
    ctx.operation_catalog = catalog
    register_checkpoint_operations(catalog, session_factory=db.session_factory, default_work_root=project,
                                   app_event_store=db.event_store, thread_snapshot_store=db.snapshot_store)
    return ctx, store, sessions, project, db









"""user:“第二阶段结束后 就继续开展第三阶段”+(会话分叉复用原检查点且限制当前项目)。"""
import pytest
from .test_plugin_checkpoint_access import setup
from .test_plugin_working_directory import env
from .test_core_checkpoint_graph import _append_production_turn, _runtime, _tool_call_history
from lamtools_core.session import SessionRecord


@pytest.mark.asyncio
async def test_scoped_fork_unknown_boundary_rejected(setup):
    ctx,store,_,_,_=setup
    with pytest.raises(RuntimeError): await ctx.session_controller.fork('s',checkpoint_id='unknown',new_session_id='missing-fork')
    assert await store.get_readonly('missing-fork') is None

def test_fork_migration_recommends_bounded_original_operation(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.session.fork(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(r for r in report['remotes'] if r['name']=='session.fork')
    assert row['suggestedContract']=='context.session_controller.fork' and row['conversion']=='agent-required'





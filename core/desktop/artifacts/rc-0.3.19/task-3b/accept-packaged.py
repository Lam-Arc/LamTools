"""Reuse the verified isolated installer/backend harness with 3B assertions."""
from pathlib import Path

base = Path(__file__).resolve().parent.parent / 'accept-packaged.py'
code = base.read_text(encoding='utf-8')
code = code.replace("Path('E:/setuptest/rc-0.3.19-upgrade-v5')", "Path('E:/setuptest/task-3b-packaged-final')")
code = code.replace("import socket\n", "import socket\nimport sqlite3\n")
code = code.replace("    rpc.counter += 1\n", "    rpc.counter += 1\n    ack_started = time.perf_counter()\n")
code = code.replace("            return value['result']", """            if method in {'turn/start','turn/resume'}:
                elapsed = time.perf_counter() - ack_started
                check(elapsed < 5, f'{method} acknowledgement before execution completes: {elapsed:.3f}s')
            return value['result']""")
code = code.replace("    install('0.3.19')", """    with sqlite3.connect(INSTALL/'.lam/core.db') as db:
        check(not any(row[1]=='idx_core_events_client_message' for row in db.execute('PRAGMA index_list(core_app_events)')), 'previous stable lacks client lookup index')
    install('0.3.19')
    # Migration is applied by the installed candidate backend on startup.
""")
code = code.replace("    asyncio.run(packaged(p))", """    with sqlite3.connect(INSTALL/'.lam/core.db') as db:
        check(any(row[1]=='idx_core_events_client_message' for row in db.execute('PRAGMA index_list(core_app_events)')), 'installed upgrade adds client lookup index')
    asyncio.run(packaged(p))""")
code = code.replace("await rpc(ws,'turn/resume',{'thread_id':'resume-acceptance','turn_id':turn})", "await rpc(ws,'turn/resume',{'thread_id':'resume-acceptance','turn_id':turn,'client_message_id':'resume-once'})")
code = code.replace("        listing = await rpc(ws,'plugin.list')", """        before_retry = Model.count
        await rpc(ws,'turn/resume',{'thread_id':'resume-acceptance','turn_id':turn,'client_message_id':'resume-once'})
        check(Model.count == before_retry, 'lost Resume acknowledgement retry does not execute model again')
        listing = await rpc(ws,'plugin.list')""")
assert 'task-3b-packaged' in code
exec(compile(code,str(base),'exec'),{'__file__':str(Path(__file__).resolve()),'__name__':'__main__'})

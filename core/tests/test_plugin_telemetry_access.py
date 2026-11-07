"""user:“继续，无人值守模式，不要停下来”+(遥测必须默认关闭、遵守会话共享选择，实际OTLP发送及失败/清理可验证)。"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lamtools_core.plugin_system import PluginContext


@pytest.fixture
def collector():
    records = []
    response_status = [200]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            records.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(response_status[0])
            self.end_headers()
            self.wfile.write(b'{}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1/logs', records, response_status
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["sharing", "severity"])
@pytest.mark.parametrize("invalid", [[], {}])
async def test_telemetry_enum_shapes_reject_without_allocating_or_sending(tmp_path, collector, field, invalid):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(共享策略与严重级别先检查类型，拒绝前不分配报告器或发送记录，随后正常发送仍可用)。
    endpoint, records, _ = collector
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("telemetry-shapes", 1)
    api = ctx.otel
    try:
        if field == "sharing":
            with pytest.raises(ValueError):
                api.create_event_reporter(endpoint=endpoint, sharing=invalid)
            assert not api._reporters
        reporter = api.create_event_reporter(endpoint=endpoint, sharing="full")
        if field == "severity":
            with pytest.raises(ValueError):
                reporter.emit({"name": "rejected", "severity": invalid})
            assert reporter.status()["queued"] == 0
        assert not records
        assert reporter.emit({"name": "accepted", "severity": "INFO"})
        await reporter.flush(timeout=3)
        assert len(records) == 1
        wire = records[0]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        assert len(wire) == 1 and wire[0]["severityText"] == "INFO"
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_default_disabled_and_explicit_sharing_control_actual_otlp_http(tmp_path, collector):
    endpoint, records, _ = collector
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("telemetry", 1)
    disabled = ctx.otel.create_event_reporter()
    with pytest.raises(AttributeError):
        disabled.sharing = "full"
    assert not disabled.emit({"name": "not-shared", "body": "private"})
    reporter = ctx.otel.create_session_reporter(endpoint=endpoint, sharing="feedback-only")
    assert not reporter.emit({"name": "ordinary-log", "kind": "session", "body": "private"})
    assert reporter.emit({"name": "rating", "kind": "feedback", "body": "explicit feedback", "attributes": {"positive": True}})
    await reporter.flush(timeout=3)
    assert len(records) == 1
    wire = records[0]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert wire["body"]["stringValue"] == "explicit feedback"
    assert "private" not in str(records)
    assert reporter.status()["sent"] == 1
    await ctx._registration_scope.dispose()
    with pytest.raises(Exception):
        reporter.emit({"name": "late"})


@pytest.mark.asyncio
async def test_collector_rejection_is_counted_and_not_replayed(tmp_path, collector):
    endpoint, records, status = collector
    status[0] = 503
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("telemetry", 1)
    reporter = ctx.otel.create_event_reporter(endpoint=endpoint, sharing="full")
    reporter.emit({"name": "failure", "body": "selected data"})
    await reporter.flush(timeout=3)
    assert reporter.status()["failed"] == 1 and reporter.status()["sent"] == 0
    assert len(records) == 1
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_reporter_queue_limits_and_unload_drain_do_not_silently_accept_overflow(tmp_path, collector):
    endpoint, records, _ = collector
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("telemetry", 1)
    reporter = ctx.otel.create_event_reporter(endpoint=endpoint, sharing="full", queue_limit=2, batch_size=1)
    assert reporter.emit({"name": "one"})
    assert reporter.emit({"name": "two"})
    assert not reporter.emit({"name": "overflow"})
    assert reporter.status()["dropped"] == 1
    await ctx._registration_scope.dispose()
    assert reporter.status()["closed"] and reporter.status()["sent"] == 2
    assert len(records) == 2


@pytest.mark.asyncio
async def test_stalled_collector_shutdown_cancels_http_and_drains_queue(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            entered.set()
            release.wait(3)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope("telemetry", 1)
    try:
        reporter = ctx.otel.create_event_reporter(endpoint=f'http://127.0.0.1:{server.server_port}/v1/logs',
            sharing="full", timeout=10, shutdown_timeout=0.1)
        reporter.emit({"name": "slow"})
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.wait_for(reporter.shutdown(), 1)
        assert reporter._worker.done()
        assert reporter.status()["queued"] == 0 and reporter.status()["dropped"] == 1
    finally:
        release.set()
        await ctx._registration_scope.dispose()
        server.shutdown()
        server.server_close()
        thread.join(2)

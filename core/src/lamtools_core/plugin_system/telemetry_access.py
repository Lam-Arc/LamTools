"""user:“继续，无人值守模式，不要停下来”+(真实OTLP HTTP导出默认关闭，仅发送调用方明确选择的记录，队列与关闭有界)。"""
import asyncio
import json
import math
import time
from urllib.parse import urlsplit

import httpx

from lamtools_core.async_tasks import finish_on_cancel
from lamtools_core.config.network import httpx_client_kwargs
from .storage_access import _encode


def _duration(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= 30:
        raise ValueError("Telemetry deadline must be in (0, 30] seconds")
    return value


def _attribute(value):
    if type(value) is bool:
        return {"boolValue": value}
    if type(value) is int and -(2**63) <= value < 2**63:
        return {"intValue": str(value)}
    if type(value) is float:
        return {"doubleValue": value}
    return {"stringValue": value if type(value) is str else json.dumps(value, ensure_ascii=False, allow_nan=False)}


class PluginTelemetryAPI:
    def __init__(self, context, scope):
        self._context, self._scope, self._reporters = context, scope, set()

    def _create(self, *, session, endpoint, sharing, queue_limit, batch_size, timeout, shutdown_timeout, headers):
        self._scope.check_open()
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(先验证共享选项类型，错误不分配报告器或创建发送任务)。
        if type(sharing) is not str or sharing not in {"disabled", "feedback-only", "full"}:
            raise ValueError("sharing must be disabled, feedback-only or full")
        if sharing != "disabled":
            parsed = urlsplit(endpoint) if type(endpoint) is str else None
            if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("Enabled telemetry requires an explicit HTTP(S) collector without inline credentials")
        if type(queue_limit) is not int or not 1 <= queue_limit <= 128 or type(batch_size) is not int or not 1 <= batch_size <= 16:
            raise ValueError("Queue limit is 1–128 records and batch size is 1–16")
        headers = {} if headers is None else dict(headers)
        if len(headers) > 32 or any(type(k) is not str or type(v) is not str or not k or any(c in k + v for c in "\r\n\x00") for k, v in headers.items()) or len(_encode(headers).encode("utf8")) > 16384:
            raise ValueError("Use bounded string headers without control characters")
        if len(self._reporters) >= 8:
            raise ValueError("At most 8 telemetry reporters per plugin view")
        reporter = TelemetryReporter(self, session=session, endpoint=endpoint, sharing=sharing,
            queue_limit=queue_limit, batch_size=batch_size, timeout=_duration(timeout),
            shutdown_timeout=_duration(shutdown_timeout), headers=headers)
        self._reporters.add(reporter)
        self._scope.on_dispose(reporter.shutdown)
        return reporter

    def create_event_reporter(self, *, endpoint=None, sharing="disabled", queue_limit=128, batch_size=16, timeout=10, shutdown_timeout=10, headers=None):
        return self._create(session=False, endpoint=endpoint, sharing=sharing, queue_limit=queue_limit,
            batch_size=batch_size, timeout=timeout, shutdown_timeout=shutdown_timeout, headers=headers)

    def create_session_reporter(self, *, endpoint=None, sharing="disabled", queue_limit=128, batch_size=16, timeout=10, shutdown_timeout=10, headers=None):
        return self._create(session=True, endpoint=endpoint, sharing=sharing, queue_limit=queue_limit,
            batch_size=batch_size, timeout=timeout, shutdown_timeout=shutdown_timeout, headers=headers)


class TelemetryReporter:
    def __init__(self, api, *, session, endpoint, sharing, queue_limit, batch_size, timeout, shutdown_timeout, headers):
        self._api, self._session, self._sharing = api, session, sharing
        self._endpoint, self._headers = endpoint, headers
        self._batch_size, self._timeout, self._shutdown_timeout = batch_size, timeout, shutdown_timeout
        self._queue = asyncio.Queue(maxsize=queue_limit)
        self._closed, self._close_task = False, None
        self._sent = self._failed = self._dropped = 0
        self._worker = asyncio.create_task(self._run(), name="plugin-otlp-export") if sharing != "disabled" else None
        if self._worker is not None:
            self._worker.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    @property
    def sharing(self):
        # user:“继续，无人值守模式，不要停下来”+(共享策略在创建时固定，修改属性不能绕过关闭状态或启动未受管发送器)。
        return self._sharing

    def emit(self, record):
        self._api._scope.check_open()
        if self._closed or self._worker is not None and self._worker.done():
            raise RuntimeError("Telemetry reporter is closed or its worker failed")
        if self.sharing == "disabled" or self.sharing == "feedback-only" and (type(record) is not dict or record.get("kind") != "feedback"):
            self._dropped += 1
            return False
        encoded = _encode(record)
        if type(record) is not dict or len(encoded.encode("utf8")) > 65536:
            raise ValueError("Telemetry record must be a JSON object, at most 64 KiB")
        record = json.loads(encoded)
        name, attributes = record.get("name"), record.get("attributes", {})
        if type(name) is not str or not name or len(name) > 128 or type(attributes) is not dict or len(attributes) > 64:
            raise ValueError("Record needs a bounded name and at most 64 attributes")
        severity = record.get("severity", "INFO")
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(严重级别类型错误按原ValueError拒绝，不入队也不破坏后续发送)。
        if type(severity) is not str or severity not in {"DEBUG", "INFO", "WARN", "ERROR"}:
            raise ValueError("Unsupported severity")
        attributes["event.name"] = name
        body = record.get("body", "")
        wire = {"timeUnixNano": str(time.time_ns()), "severityText": severity,
                "body": {"stringValue": body if type(body) is str else json.dumps(body, ensure_ascii=False, allow_nan=False)},
                "attributes": [{"key": key, "value": _attribute(value)} for key, value in attributes.items()]}
        # JSON escaping / attribute envelopes may enlarge the caller's original payload.
        if len(json.dumps(wire, ensure_ascii=False).encode("utf8")) > 131072:
            raise ValueError("Encoded OTLP record exceeds 128 KiB")
        try:
            self._queue.put_nowait(wire)
            return True
        except asyncio.QueueFull:
            self._dropped += 1
            return False

    def status(self):
        return {"sharing": self.sharing, "closed": self._closed, "queued": self._queue.qsize(),
                "sent": self._sent, "failed": self._failed, "dropped": self._dropped}

    async def _run(self):
        while True:
            first = await self._queue.get()
            if first is None:
                self._queue.task_done()
                return
            batch, stop_after = [first], False
            while len(batch) < self._batch_size:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is None:
                    self._queue.task_done()
                    stop_after = True
                    break
                batch.append(item)
            payload = {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "SundayPlugin"}}]},
                "scopeLogs": [{"scope": {"name": "sunday.plugin." + self._api._scope.owner}, "logRecords": batch}]}]}
            try:
                async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False, **httpx_client_kwargs(self._endpoint)) as client:
                    async with asyncio.timeout(self._timeout):
                        async with client.stream("POST", self._endpoint, json=payload, headers=self._headers) as response:
                            # Do not buffer an untrusted collector response or replay an uncertain delivery.
                            success = 200 <= response.status_code < 300
                if success:
                    self._sent += len(batch)
                else:
                    self._failed += len(batch)
            except asyncio.CancelledError:
                self._dropped += len(batch)
                raise
            except Exception:
                self._failed += len(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()
            if stop_after:
                return

    async def flush(self, *, timeout=10):
        self._api._scope.acquire()
        try:
            async with asyncio.timeout(_duration(timeout)):
                await self._queue.join()
            return self.status()
        finally:
            self._api._scope.release()

    async def shutdown(self):
        self._closed = True
        async def close():
            try:
                if self._worker is not None:
                    try:
                        async with asyncio.timeout(self._shutdown_timeout):
                            await self._queue.put(None)
                            await asyncio.shield(self._worker)
                    except TimeoutError:
                        self._worker.cancel()
                        await asyncio.gather(self._worker, return_exceptions=True)
            finally:
                while not self._queue.empty():
                    if self._queue.get_nowait() is not None:
                        self._dropped += 1
                    self._queue.task_done()
                self._api._reporters.discard(self)
        if self._close_task is None:
            self._close_task = asyncio.create_task(close(), name="plugin-otlp-shutdown")
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        async def join():
            await asyncio.shield(self._close_task)
        await finish_on_cancel(join(), name="plugin-otlp-join")
        return self.status()

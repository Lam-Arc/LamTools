"""user:“对比原版，能力应当只增不减”+(真实宿主加载完整复刻并验证持久化、值守与原版能力面)。"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginContext, PluginHost
from lamtools_core.plugin_system.backend_runtime import register_manager
from lamtools_core.plugin_system.operations import register_plugin_system_operations
from lamtools_core.plugin_system.loading import load_module

SOURCE = Path(__file__).resolve().parents[2] / "plugins" / "bili-scroll"


@pytest.fixture
async def installed(tmp_path):
    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "state.json")
    context = PluginContext(work_root=tmp_path, data_dir=tmp_path)
    calls = []
    async def run_profile(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(decision="completed", error="")
    context.set_service("run_profile", run_profile)
    manager = register_manager(host, [], context)
    catalog = OperationCatalog()
    context.operation_catalog = catalog
    register_plugin_system_operations(catalog, host)
    result = await catalog.execute("plugin.system.install", {"path": str(SOURCE)})
    assert result.status == "ok", result.payload
    try:
        yield host, manager, catalog, calls
    finally:
        await manager.stop("bili-scroll")


@pytest.mark.asyncio
async def test_complete_source_capabilities_are_declared(installed):
    host, manager, catalog, calls = installed
    required = {"status", "config_get", "config_update", "setup", "install_asr", "login_start", "login_poll",
                "run_round", "stop_round", "watched", "report_read", "reports_list", "verify", "fav_folders",
                "fav_add_today", "dm_scan", "diagnose", "selfcheck", "check", "update_check", "open_home"}
    assert {f"bili-scroll.{name}" for name in required} <= set(catalog.list())
    listing = (await catalog.execute("plugin.system.list")).payload["plugins"][0]
    assert listing["available"] and not listing.get("capability_error")
    ui = (await catalog.execute("plugin.system.ui")).payload
    assert ui["pages"] and ui["windows"]


@pytest.mark.asyncio
async def test_configuration_reaches_runtime_and_survives_upgrade(installed, tmp_path):
    host, manager, catalog, calls = installed
    await catalog.execute("plugin.system.config.update", {"name": "bili-scroll", "config": {"perDay": 7, "keywords": ["测试关键词"]}})
    status = await catalog.execute("bili-scroll.status")
    assert status.payload["perDay"] == 7
    root = host.get("bili-scroll").root
    assert (root / "data").resolve() == host.data_path("bili-scroll")
    update = await catalog.execute("plugin.system.update", {"path": str(SOURCE)})
    assert update.status == "ok", update.payload
    assert (await catalog.execute("bili-scroll.status")).payload["perDay"] == 7
    assert manager.get("bili-scroll").value.running


@pytest.mark.asyncio
async def test_round_uses_host_profile_and_emits_empty_round_report(installed):
    host, manager, catalog, calls = installed
    result = await catalog.execute("bili-scroll.run_round")
    assert result.payload["started"], result.payload
    runtime = manager.get("bili-scroll").value
    await asyncio.wait_for(runtime.wait_round(), 3)
    assert calls and calls[0]["profile"] == "bili-scroll:duty"
    report = await catalog.execute("bili-scroll.report_read")
    assert "本轮" in report.payload["text"]
    assert not (host.data_path("bili-scroll") / "duty" / "running.lock").exists()


@pytest.mark.asyncio
async def test_charter_preserves_edits_but_updates_unmodified_copy(installed):
    host, manager, catalog, calls = installed
    common = load_module(host.get("bili-scroll").root, "common")
    path = common.DUTY / "duty.md"
    assert path.exists()
    common.ensure_charter("first charter")
    # The initial bundled charter was not edited, so it upgrades.
    assert path.read_text(encoding="utf-8") == "first charter"
    path.write_text("my custom charter", encoding="utf-8")
    common.ensure_charter("second charter")
    assert path.read_text(encoding="utf-8") == "my custom charter"
    assert path.with_suffix(".md.new").read_text(encoding="utf-8") == "second charter"


@pytest.mark.asyncio
async def test_watched_has_tier_state_filters_and_pagination(installed):
    host, manager, catalog, calls = installed
    common = load_module(host.get("bili-scroll").root, "common")
    rows = [{"bvid": f"BV{index:010d}", "tier": "A", "state": "picked", "title": f"Video {index}"} for index in range(5)]
    common.write_watched(rows)
    result = await catalog.execute("bili-scroll.watched", {"tier": "A", "state": "picked", "limit": 2, "offset": 2})
    assert result.payload["total"] == 5
    assert len(result.payload["items"]) == 2
    assert result.payload["items"][0]["bvid"] == rows[2]["bvid"]


@pytest.mark.asyncio
async def test_every_local_read_operation_works_through_host(installed):
    host, manager, catalog, calls = installed
    for name in ("status", "config_get", "reports_list", "seen_list", "watched", "diagnose", "selfcheck", "round_instruction"):
        result = await catalog.execute(f"bili-scroll.{name}")
        assert result.status == "ok", (name, result.payload)


@pytest.mark.asyncio
async def test_stopping_backend_waits_for_round_and_scheduler(installed):
    host, manager, catalog, calls = installed
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def long_round(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    manager.context.set_service("run_profile", long_round)
    result = await catalog.execute("bili-scroll.run_round")
    assert result.payload["started"]
    await asyncio.wait_for(started.wait(), 2)
    runtime = manager.get("bili-scroll").value
    result = await catalog.execute("plugin.system.disable", {"name": "bili-scroll"})
    assert result.status == "ok"
    assert cancelled.is_set()
    assert not runtime.running
    assert all(task.done() for task in runtime.lifecycle_tasks)
    assert not catalog.has("bili-scroll.status")


@pytest.mark.asyncio
async def test_dm_watcher_fetches_owner_message_and_does_not_reply_twice(installed, monkeypatch):
    host, manager, catalog, calls = installed
    root = host.get("bili-scroll").root
    common = load_module(root, "common")
    service = load_module(root, "service")
    await catalog.execute("bili-scroll.config_update", {"patch": {"dmUid": 42, "dmWatch": True}})
    monkeypatch.setattr(service, "_cred", lambda: {"sessdata": "test-only", "dedeuserid": "7"})
    def response(url, credential):
        if "get_sessions" in url:
            return {"session_list": [{"talker_id": 42, "unread_count": 1, "last_msg": {"timestamp": 1}},
                                     {"talker_id": 99, "unread_count": 1, "last_msg": {"timestamp": 2}}]}
        assert "talker_id=42" in url
        return {"messages": [{"msg_key": "owner-message-1", "sender_uid": 42, "timestamp": 1,
                              "content": json.dumps({"content": "请看看 BV1234567890"})}]}
    monkeypatch.setattr(service, "_dm_get", response)
    scanned = (await catalog.execute("bili-scroll.dm_scan")).payload
    assert scanned["unreadSessions"][0]["messages"][0]["text"] == "请看看 BV1234567890"
    runtime = manager.get("bili-scroll").value
    assert (await runtime.reply_dm(scanned))["started"]
    await runtime.wait_round()
    assert "请看看 BV1234567890" in calls[0]["task"]
    assert not (await runtime.reply_dm(scanned))["started"]


@pytest.mark.asyncio
async def test_round_finalization_runs_favorites_and_retains_failure_reason(installed, monkeypatch):
    host, manager, catalog, calls = installed
    service = load_module(host.get("bili-scroll").root, "service")
    invoked = []
    monkeypatch.setattr(service, "fav_add_today", lambda: invoked.append("favorite") or {"ok": True})
    await catalog.execute("bili-scroll.config_update", {"patch": {"favFolderId": 123}})
    await catalog.execute("bili-scroll.run_round")
    await manager.get("bili-scroll").value.wait_round()
    assert invoked == ["favorite"]
    service.finalize_round("test", "本轮服务不可用")
    report = (await catalog.execute("bili-scroll.report_read")).payload["text"]
    assert "本轮服务不可用" in report


@pytest.mark.asyncio
async def test_network_operation_keeps_host_event_loop_responsive(installed, monkeypatch):
    import threading
    host, manager, catalog, calls = installed
    service = load_module(host.get("bili-scroll").root, "service")
    entered, release = threading.Event(), threading.Event()
    def slow_login():
        entered.set()
        release.wait(2)
        return {"ok": True, "key": "test-key"}
    monkeypatch.setattr(service, "login_start", slow_login)
    task = asyncio.create_task(catalog.execute("bili-scroll.login_start"))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        assert not task.done(), "network call blocked the host event loop"
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_each_login_refresh_has_unique_url_and_qr_asset(installed, monkeypatch):
    from email.message import Message
    from io import BytesIO
    host, manager, catalog, calls = installed
    service = load_module(host.get("bili-scroll").root, "service")
    urls = []
    class Response(BytesIO):
        headers = Message()
    def get(url, timeout=20):
        urls.append(url)
        return Response(json.dumps({"data": {"qrcode_key": f"key-{len(urls)}", "url": "https://example.invalid/qr"}}).encode())
    assets = []
    def render(cfg, url, identity=""):
        assets.append(identity)
        return None
    monkeypatch.setattr(service, "_http_get", get)
    monkeypatch.setattr(service, "_render_qr", render)
    await catalog.execute("bili-scroll.login_start")
    await catalog.execute("bili-scroll.login_start")
    assert urls[0] != urls[1]
    assert len(set(assets)) == 2 and all(assets)


@pytest.mark.asyncio
async def test_per_video_notes_are_derived_from_full_report_without_extra_model_calls(installed):
    host, manager, catalog, calls = installed
    common = load_module(host.get("bili-scroll").root, "common")
    common.append(common.report_path(), "### BV1234567890\n一个具体视频\n档位：值得看\n为什么值得：完整笔记内容\n")
    watched = (await catalog.execute("bili-scroll.watched")).payload
    note = common.DUTY / "reports/BV1234567890.md"
    assert note.is_file() and "完整笔记内容" in note.read_text(encoding="utf-8")
    assert watched["items"][0]["note"]
    assert calls == []


@pytest.mark.asyncio
async def test_recipient_uid_can_be_resolved_from_original_nickname_setting(installed, monkeypatch):
    from io import BytesIO
    host, manager, catalog, calls = installed
    root = host.get("bili-scroll").root
    common, service = load_module(root, "common"), load_module(root, "service")
    await catalog.execute("bili-scroll.config_update", {"patch": {"mentionName": "测试主人", "dmUid": 0}})
    monkeypatch.setattr(service, "_http_get", lambda *args: BytesIO(json.dumps({"code": 0, "data": {"result": [{"uname": "测试主人", "mid": 42}]}}).encode()))
    result = await service.run_io(service.resolve_recipient)
    assert result["uid"] == 42
    assert common.load_config()["dmUidResolved"] == 42


@pytest.mark.asyncio
async def test_external_python_does_not_require_local_install_marker(installed):
    # user:“该调的模块就是该写的东西，都试一试”+(显式选择的外部环境不能被本地安装标记误拦)。
    import sys
    host, manager, catalog, calls = installed
    common = load_module(host.get("bili-scroll").root, "common")
    await catalog.execute("bili-scroll.config_update", {"patch": {"pythonPath": sys.executable}})
    assert not (common.DUTY / ".venv/requirements.ok").exists()
    assert common.venv_ready() and common.fav_ready()
    await catalog.execute("bili-scroll.config_update", {"patch": {"pythonPath": str(common.DATA / "absent.exe")}})
    assert not common.venv_ready()


@pytest.mark.asyncio
async def test_favorite_adapter_uses_supported_video_api(installed, monkeypatch):
    # user:“都试一试”+(收藏使用实际依赖公开 API，不依赖已不存在的收藏资源类)。
    import sys
    host, manager, catalog, calls = installed
    adapter = load_module(host.get("bili-scroll").root, "scripts.favops")
    observed = []
    class Video:
        def __init__(self, **kwargs): observed.append(kwargs)
        async def set_favorite(self, **kwargs):
            observed.append(kwargs)
            return {"prompt": True}
    monkeypatch.setitem(sys.modules, "bilibili_api", SimpleNamespace(video=SimpleNamespace(Video=Video)))
    monkeypatch.setattr(adapter, "load", lambda: ("private-credential", 123))
    assert (await adapter.add("BV1234567890", 42))["ok"]
    assert observed[-1] == {"add_media_ids": [42]}


@pytest.mark.asyncio
async def test_favorite_subprocess_uses_explicit_utf8(installed, monkeypatch):
    # user:“都试一试”+(Windows 子进程中文回执按统一编码读取)。
    import sys
    host, manager, catalog, calls = installed
    service = load_module(host.get("bili-scroll").root, "service")
    await catalog.execute("bili-scroll.config_update", {"patch": {"pythonPath": sys.executable}})
    def run(args, **kwargs):
        assert kwargs["encoding"] == "utf-8" and kwargs["env"]["PYTHONUTF8"] == "1"
        return SimpleNamespace(stdout='{"ok": true, "message": "收藏成功"}', stderr='', returncode=0)
    monkeypatch.setattr(service.subprocess, "run", run)
    assert service.fav_call(["add", "BV1234567890", "42"])["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("picture_url", ["https://i0.hdslb.com/probe.png", "http://i0.hdslb.com/probe.png"])
async def test_original_ui_cover_uses_real_host_operation(installed, monkeypatch, picture_url):
    # user:“就移植原版就行”+(原版卡片封面仍经宿主读取，不退化成缺图或直连防盗链图片)。
    from io import BytesIO
    host, manager, catalog, calls = installed
    service = load_module(host.get("bili-scroll").root, "service")
    monkeypatch.setattr(service, "_dm_get", lambda *args: {"pic": picture_url})
    class Image(BytesIO):
        headers = {"Content-Type": "image/png"}
    monkeypatch.setattr(service, "_http_get", lambda *args: Image(b"\x89PNG\r\n\x1a\nprobe"))
    result = await catalog.execute("bili-scroll.cover_data", {"bvid": "BV1234567890"})
    assert result.status == "ok" and result.payload["data_url"].startswith("data:image/png;base64,")
    invalid = await catalog.execute("bili-scroll.cover_data", {"bvid": "../../secret"})
    assert invalid.status == "error"

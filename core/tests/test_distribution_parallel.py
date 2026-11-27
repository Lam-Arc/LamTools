"""user:“sunday更新 可以优先 easy net 吗？这样更新的速度会快一些”+(多连接下载要真能拆、能合并、能取消，服务器不支持时安静回退)。"""
import hashlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lamtools_core import distribution as dist

PAYLOAD = bytes((index * 7 + 13) % 251 for index in range(5 * 1024 * 1024))


class _Handler(BaseHTTPRequestHandler):
    """Serves ``server.payload`` with optional range support and a slow trickle."""

    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 — http.server API
        server = self.server
        with server.guard:
            server.requests.append(dict(self.headers))
        data = server.payload
        raw_range = self.headers.get("Range", "")
        if raw_range and server.support_ranges and server.fail_ranges and raw_range != "bytes=0-0":
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start, end = 0, len(data) - 1
        if raw_range and server.support_ranges:
            unit, _, window = raw_range.partition("=")
            if unit.strip() == "bytes":
                first, _, last = window.partition("-")
                if first.strip().isdigit():
                    start = int(first)
                if last.strip().isdigit():
                    end = int(last)
                start = max(0, min(start, len(data) - 1))
                end = max(start, min(end, len(data) - 1))
            body = data[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            for offset in range(0, len(body), server.chunk):
                self.wfile.write(body[offset : offset + server.chunk])
                if server.delay:
                    time.sleep(server.delay)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    httpd.payload = PAYLOAD
    httpd.support_ranges = True
    httpd.fail_ranges = False
    httpd.chunk = 64 * 1024
    httpd.delay = 0.0
    httpd.requests = []
    httpd.guard = threading.Lock()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _url(httpd):
    return f"http://127.0.0.1:{httpd.server_address[1]}/Sunday_setup.exe"


def _digest():
    return hashlib.sha256(PAYLOAD).hexdigest()


def test_parallel_download_splits_ranges_and_assembles_in_order(server, tmp_path):
    target = tmp_path / "setup.part"
    progress = []
    result = dist.download_file(
        _url(server), target, expected_sha256=_digest(), max_bytes=len(PAYLOAD) + 1,
        connections=4, progress=lambda received, total: progress.append((received, total)),
    )
    assert result["bytes"] == len(PAYLOAD)
    assert result["sha256"] == _digest()
    assert target.read_bytes() == PAYLOAD
    ranges = [row.get("Range", "") for row in server.requests if row.get("Range")]
    assert len(ranges) >= 5  # one probe plus one request per part
    assert not list(tmp_path.glob("setup.part.part*"))
    assert progress and progress[-1][0] == len(PAYLOAD)
    assert [received for received, _ in progress] == sorted(received for received, _ in progress)


def test_server_without_ranges_falls_back_to_one_stream(server, tmp_path):
    server.support_ranges = False
    target = tmp_path / "setup.part"
    result = dist.download_file(
        _url(server), target, expected_sha256=_digest(), max_bytes=len(PAYLOAD) + 1, connections=4,
    )
    assert result["bytes"] == len(PAYLOAD)
    assert target.read_bytes() == PAYLOAD
    # probe + the single streamed body; never four parallel attempts against a server that cannot.
    assert len(server.requests) == 2
    assert not list(tmp_path.glob("setup.part.part*"))


def test_parallel_rejected_by_the_hop_falls_back_to_one_stream(server, tmp_path):
    # 代理限制并发时：同一条路由先用单连接重来，结果仍要完整、可校验。
    server.fail_ranges = True
    target = tmp_path / "setup.part"
    result = dist.download_file(
        _url(server), target, expected_sha256=_digest(), max_bytes=len(PAYLOAD) + 1, connections=4,
    )
    assert result["bytes"] == len(PAYLOAD)
    assert target.read_bytes() == PAYLOAD
    statuses = [row.get("Range", "") for row in server.requests]
    assert len([item for item in statuses if item]) >= 2  # probe plus the rejected parts
    assert not list(tmp_path.glob("setup.part.part*"))


def test_cancel_leaves_no_target_and_no_part_files(server, tmp_path):
    server.delay = 0.02

    class Cancelled(RuntimeError):
        pass

    state = {"received": 0}

    def cancel():
        if state["received"] > 1024 * 1024:
            raise Cancelled()

    def progress(received, _total):
        state["received"] = received

    target = tmp_path / "setup.part"
    with pytest.raises(Cancelled):
        dist.download_file(
            _url(server), target, expected_sha256=_digest(), max_bytes=len(PAYLOAD) + 1,
            connections=4, progress=progress, cancel=cancel,
        )
    assert not target.exists()
    assert not list(tmp_path.glob("setup.part.part*"))


def test_range_segments_cover_the_file_exactly():
    segments = dist._segments(10, 4)
    assert segments == [(0, 2), (3, 5), (6, 8), (9, 9)]
    assert dist._segments(3, 8) == [(0, 0), (1, 1), (2, 2)]


def test_route_kind_names_the_easynet_hop(monkeypatch):
    monkeypatch.setattr(dist, "httpx_client_kwargs", lambda url: {"trust_env": False})
    owner = object()
    dist.register_local_route(owner, "http://127.0.0.1:49152", kind="accelerator")
    try:
        route = dist.route_candidates("https://github.com/Lam-Arc/LamTools/releases/download/x.exe")[0]
        assert dist.route_kind(route) == "accelerator"
        dist.register_local_route(owner, "http://127.0.0.1:17890", kind="proxy")
        route = dist.route_candidates("https://ainarit.com/downloads/desktop-update.json")[0]
        assert dist.route_kind(route) == "proxy"
    finally:
        dist.clear_local_route(owner)
    assert dist.route_kind(dist.route_candidates("https://github.com/x")[0]) == "direct"


def test_update_download_asks_for_parallel_lanes_and_reports_the_route(tmp_path, monkeypatch):
    from lamtools_core.update import installer

    captured = {}

    def fake_download(url, target, **kwargs):
        captured.update(kwargs)
        target.write_bytes(b"installer")
        return {"bytes": 9, "sha256": "b" * 64}

    monkeypatch.setattr(dist, "download_file", fake_download)
    monkeypatch.setenv("LAMTOOLS_UPDATE_DIR", str(tmp_path))
    installer._CANCEL.clear()
    installer.download_update("https://github.com/Lam-Arc/LamTools/releases/download/v1/Sunday_setup.exe", "b" * 64, "Sunday_setup.exe")
    assert captured["connections"] == dist.DEFAULT_CONNECTIONS
    assert callable(captured["on_route"])
    captured["on_route"]("accelerator")
    assert installer.progress_snapshot()["route"] == "accelerator"

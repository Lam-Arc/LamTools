"""user:“这个打包版是最近打包过 刚更新的，就是你改完那一版”+“正常了”+
(入口 HTML 必须每次都是最新的一份：一旦被缓存复用，页面就继续引用上一版静态资源，
界面和公式都会停在旧版本——这正是那次「更新完 LaTeX 还是坏的、重载一次就好了」的原因。
带内容哈希的 /assets 反过来应该长期缓存。)"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lamtools_core.app.factory import _mount_frontend_assets, add_spa_fallback


def _client(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><div id=app></div>", encoding="utf-8")
    (frontend / "capture.html").write_text("<!doctype html><p>capture</p>", encoding="utf-8")
    (frontend / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    app = FastAPI()
    _mount_frontend_assets(app, frontend)
    add_spa_fallback(app, frontend)
    return TestClient(app)


def _no_store(response) -> bool:
    return "no-store" in response.headers.get("cache-control", "").lower()


def test_root_html_is_never_cached(tmp_path):
    client = _client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert _no_store(response)
    assert response.headers.get("pragma") == "no-cache"


def test_spa_fallback_html_is_never_cached(tmp_path):
    client = _client(tmp_path)
    response = client.get("/some/deep/client/route")
    assert response.status_code == 200
    assert _no_store(response)


def test_existing_html_entry_files_are_never_cached(tmp_path):
    client = _client(tmp_path)
    for path in ("/index.html", "/capture.html"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert _no_store(response), path


def test_hashed_assets_are_cacheable_forever(tmp_path):
    client = _client(tmp_path)
    response = client.get("/assets/app-abc123.js")
    assert response.status_code == 200
    assert "immutable" in response.headers.get("cache-control", "").lower()
    assert not _no_store(response)

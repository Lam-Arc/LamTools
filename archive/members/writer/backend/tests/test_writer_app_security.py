from app.app_server.security import (
    is_allowed_browser_origin,
    is_authorized_websocket,
    issue_app_server_token,
)


def test_browser_websocket_requires_local_origin_and_token():
    token = issue_app_server_token()

    assert is_authorized_websocket("http://127.0.0.1:7001", token)
    assert is_authorized_websocket("http://localhost:6174", token)
    assert not is_authorized_websocket("http://127.0.0.1:7001", "")
    assert not is_authorized_websocket("https://example.com", token)


def test_packaged_desktop_file_origin_requires_token():
    token = issue_app_server_token()

    assert is_allowed_browser_origin("file://")
    assert is_authorized_websocket("file://", token)
    assert not is_authorized_websocket("file://", "")


def test_non_browser_local_clients_can_connect_without_origin():
    assert is_allowed_browser_origin(None)
    assert is_authorized_websocket(None, None)

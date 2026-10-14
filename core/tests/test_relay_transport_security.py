import pytest

from lamtools_core.cli import normalize_remote_server_base_url


@pytest.mark.parametrize("url", ["http://relay.example", "http://192.168.1.20:8787", "http://[2001:db8::1]"])
def test_cli_refuses_plaintext_public_credentials_before_login(url):
    with pytest.raises(RuntimeError, match="HTTPS"):
        normalize_remote_server_base_url(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8787", "http://[::1]:8787", "https://relay.example"])
def test_local_development_and_https_remain_supported(url):
    assert normalize_remote_server_base_url(url + "/v1/auth/login") == url


def test_url_credentials_are_rejected_without_echoing_secret():
    with pytest.raises(RuntimeError) as error:
        normalize_remote_server_base_url("https://user:private-password@relay.example")
    assert "private-password" not in str(error.value)

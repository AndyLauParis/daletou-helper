"""安全层测试：响应头、异常请求拦截、限流、Cookie 会话、CSRF 与 HTTPS。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import security_layer
from helper import config
from helper.api import auth as auth_api
from helper_app import app

PASSWORD = "Str0ngPassw0rd"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    auth_api.reset_login_rate_limit()
    security_layer.reset_security_state()
    with TestClient(app) as test_client:
        yield test_client


def register(client, username="alice", password=PASSWORD, invite_code=None):
    payload = {"username": username, "password": password, "is_adult": True}
    if invite_code is not None:
        payload["invite_code"] = invite_code
    return client.post("/api/helper/auth/register", json=payload)


def test_security_headers(client):
    resp = client.get("/api/helper/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    csp = resp.headers["content-security-policy"]
    assert "script-src 'self';" in csp
    assert "object-src 'none'" in csp
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-request-id"]


def test_html_pages_do_not_cache(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert "content-security-policy" in resp.headers


@pytest.mark.parametrize(
    "path",
    [
        "/.git/config",
        "/.env",
        "/wp-admin/",
        "/phpmyadmin/index.php",
        "/static/%2e%2e/helper/config.py",
    ],
)
def test_blocked_paths_return_404(client, path):
    resp = client.get(path)
    assert resp.status_code == 404
    # 守卫返回纯文本 404，与路由层 JSON 404 区分，确保确实被安全层拦截
    assert resp.headers["content-type"].startswith("text/plain")


def test_scanner_user_agent_blocked(client):
    resp = client.get(
        "/api/helper/health", headers={"User-Agent": "sqlmap/1.7 (http://sqlmap.org)"}
    )
    assert resp.status_code == 403


def test_unsupported_method_blocked(client):
    assert client.request("TRACE", "/api/helper/health").status_code == 405


def test_body_size_limit(client, monkeypatch):
    monkeypatch.setattr(security_layer.SECURITY, "max_body_bytes", 1024)
    resp = client.post(
        "/api/helper/auth/login",
        json={"username": "a" * 2000, "password": "x" * 2000},
    )
    assert resp.status_code == 413


def test_auth_rate_limit(client, monkeypatch):
    monkeypatch.setattr(security_layer.SECURITY, "auth_rate_limit", 2)
    security_layer.reset_security_state()
    payload = {"username": "nobody", "password": "WrongPassw0rd"}
    for _ in range(2):
        assert client.post("/api/helper/auth/login", json=payload).status_code == 401
    limited = client.post("/api/helper/auth/login", json=payload)
    assert limited.status_code == 429
    assert "detail" in limited.json()


def test_cookie_session_and_logout(client):
    resp = register(client)
    assert resp.status_code == 201
    assert security_layer.SESSION_COOKIE_NAME in resp.cookies

    me = client.get("/api/helper/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"

    out = client.post("/api/helper/auth/logout")
    assert out.status_code == 200
    assert client.get("/api/helper/auth/me").status_code == 401


def test_session_cookie_flags(client):
    resp = register(client)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie


def test_csrf_rejects_cross_origin_cookie_request(client):
    register(client)
    bad = client.post(
        "/api/helper/auth/logout", headers={"Origin": "https://evil.example"}
    )
    assert bad.status_code == 403
    # 会话未被跨站请求注销
    assert client.get("/api/helper/auth/me").status_code == 200

    ok = client.post(
        "/api/helper/auth/logout", headers={"Origin": "http://testserver"}
    )
    assert ok.status_code == 200


def test_bearer_requests_are_not_csrf_blocked(client):
    token = register(client).json()["token"]
    # 即使浏览器带有旧 Cookie，显式 Bearer 请求也不受 Origin 校验影响
    resp = client.get(
        "/api/helper/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_hsts_only_when_https(client, monkeypatch):
    plain = client.get("/api/helper/health")
    assert "strict-transport-security" not in plain.headers

    monkeypatch.setattr(
        security_layer.SECURITY, "trusted_proxies", ("testclient",)
    )
    secure = client.get(
        "/api/helper/health", headers={"X-Forwarded-Proto": "https"}
    )
    assert "strict-transport-security" in secure.headers


def test_https_redirect(client, monkeypatch):
    monkeypatch.setattr(security_layer.SECURITY, "require_https", True)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == "https://testserver/"
    # 健康检查不受重定向影响
    assert client.get("/api/helper/health", follow_redirects=False).status_code == 200


def test_invite_registration(client, monkeypatch):
    monkeypatch.setattr(config, "REGISTRATION_MODE", "invite")
    monkeypatch.setattr(config, "INVITE_CODE", "s3cret-code")

    assert register(client, username="user_a").status_code == 403
    assert register(client, username="user_b", invite_code="wrong").status_code == 403
    assert (
        register(client, username="user_c", invite_code="s3cret-code").status_code
        == 201
    )


def test_closed_registration(client, monkeypatch):
    monkeypatch.setattr(config, "REGISTRATION_MODE", "closed")
    resp = register(client)
    assert resp.status_code == 403
    assert "注册暂未开放" in resp.json()["detail"]

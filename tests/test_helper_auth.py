"""账号系统 API 测试：注册、登录、会话、限流、改密、删号与令牌隔离。"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper.api import auth as auth_api
from helper_app import app

PASSWORD = "Str0ngPassw0rd"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    auth_api.reset_login_rate_limit()
    with TestClient(app) as test_client:
        yield test_client
    auth_api.reset_login_rate_limit()


def register(client, username="alice", password=PASSWORD, is_adult=True):
    return client.post(
        "/api/helper/auth/register",
        json={"username": username, "password": password, "is_adult": is_adult},
    )


def login(client, username="alice", password=PASSWORD):
    return client.post(
        "/api/helper/auth/login",
        json={"username": username, "password": password},
    )


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    resp = client.get("/api/helper/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "app": "helper"}


def test_register_success(client):
    resp = register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert isinstance(data["token"], str) and len(data["token"]) >= 32
    assert data["user"]["username"] == "alice"
    assert isinstance(data["user"]["id"], int)


def test_register_requires_adult_confirm(client):
    resp = register(client, is_adult=False)
    assert resp.status_code == 400
    assert "18" in resp.json()["detail"]


def test_register_duplicate_username(client):
    assert register(client).status_code == 201
    resp = register(client)
    assert resp.status_code == 409
    assert "已被注册" in resp.json()["detail"]


@pytest.mark.parametrize("username", ["ab", "a" * 33, "bad name", "bad-name", ""])
def test_register_invalid_username(client, username):
    resp = register(client, username=username)
    assert resp.status_code == 400


@pytest.mark.parametrize("password", ["short", "1234567", "x" * 129])
def test_register_weak_password(client, password):
    resp = register(client, password=password)
    assert resp.status_code == 400


def test_register_accepts_chinese_username(client):
    resp = register(client, username="彩民小张")
    assert resp.status_code == 201
    assert resp.json()["user"]["username"] == "彩民小张"


def test_passwords_and_tokens_are_hashed(client):
    data = register(client).json()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        user_row = conn.execute(
            "SELECT password_hash, password_salt FROM users WHERE username = 'alice'"
        ).fetchone()
        session_row = conn.execute(
            "SELECT token_hash FROM sessions WHERE user_id = "
            "(SELECT id FROM users WHERE username = 'alice')"
        ).fetchone()
    finally:
        conn.close()
    password_hash, salt = user_row
    assert password_hash != PASSWORD
    assert len(password_hash) == 64
    assert len(salt) == 32
    assert session_row[0] != data["token"]
    assert len(session_row[0]) == 64


def test_login_success_and_failure(client):
    register(client)
    ok = login(client)
    assert ok.status_code == 200
    assert ok.json()["user"]["username"] == "alice"
    assert ok.json()["token"]

    bad = login(client, password="WrongPassw0rd")
    assert bad.status_code == 401
    assert "用户名或密码错误" in bad.json()["detail"]

    missing = login(client, username="nobody")
    assert missing.status_code == 401


def test_login_rate_limit(client):
    register(client)
    for _ in range(config.LOGIN_FAIL_MAX):
        assert login(client, password="WrongPassw0rd").status_code == 401
    limited = login(client, password="WrongPassw0rd")
    assert limited.status_code == 429
    # 达到限流后，即使密码正确也暂时拒绝
    assert login(client).status_code == 429


def test_successful_login_clears_failure_counter(client):
    register(client)
    for _ in range(config.LOGIN_FAIL_MAX - 1):
        assert login(client, password="WrongPassw0rd").status_code == 401
    assert login(client).status_code == 200
    for _ in range(config.LOGIN_FAIL_MAX - 1):
        assert login(client, password="WrongPassw0rd").status_code == 401
    assert login(client).status_code == 200


def test_login_failure_tracking_is_bounded():
    """随机用户名不能无限扩张进程内的失败计数。"""
    auth_api.reset_login_rate_limit()
    try:
        for index in range(auth_api.MAX_FAILURE_KEYS + 20):
            auth_api.record_login_failure(("127.0.0.1", f"user{index}"))
        assert len(auth_api._failures) <= auth_api.MAX_FAILURE_KEYS
    finally:
        auth_api.reset_login_rate_limit()


def test_login_invalid_username_not_tracked(client):
    auth_api.reset_login_rate_limit()
    resp = login(client, username="bad name!")
    assert resp.status_code == 401
    assert auth_api._failures == {}


def test_me_requires_token(client):
    no_token = client.get("/api/helper/auth/me")
    assert no_token.status_code == 401
    assert no_token.json()["detail"] == "请先登录"

    bad_token = client.get("/api/helper/auth/me", headers=auth_header("not-a-token"))
    assert bad_token.status_code == 401
    assert bad_token.json()["detail"] == "请先登录"


def test_me_returns_current_user(client):
    token = register(client).json()["token"]
    resp = client.get("/api/helper/auth/me", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "alice"


def test_logout_invalidates_token(client):
    token = register(client).json()["token"]
    assert client.get("/api/helper/auth/me", headers=auth_header(token)).status_code == 200

    out = client.post("/api/helper/auth/logout", headers=auth_header(token))
    assert out.status_code == 200
    assert out.json() == {"ok": True}

    assert client.get("/api/helper/auth/me", headers=auth_header(token)).status_code == 401


def test_change_password_invalidates_sessions(client):
    token = register(client).json()["token"]
    new_password = "An0therPassw0rd"

    wrong = client.post(
        "/api/helper/auth/change-password",
        headers=auth_header(token),
        json={"old_password": "WrongPassw0rd", "new_password": new_password},
    )
    assert wrong.status_code == 400

    resp = client.post(
        "/api/helper/auth/change-password",
        headers=auth_header(token),
        json={"old_password": PASSWORD, "new_password": new_password},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "reauth": True}

    assert client.get("/api/helper/auth/me", headers=auth_header(token)).status_code == 401
    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password=new_password).status_code == 200


def test_change_password_rejects_weak_new_password(client):
    token = register(client).json()["token"]
    resp = client.post(
        "/api/helper/auth/change-password",
        headers=auth_header(token),
        json={"old_password": PASSWORD, "new_password": "short"},
    )
    assert resp.status_code == 400
    assert client.get("/api/helper/auth/me", headers=auth_header(token)).status_code == 200


def test_delete_account_requires_confirm_and_password(client):
    token = register(client).json()["token"]

    wrong_confirm = client.request(
        "DELETE",
        "/api/helper/auth/account",
        headers=auth_header(token),
        json={"password": PASSWORD, "confirm": "delete"},
    )
    assert wrong_confirm.status_code == 400

    wrong_password = client.request(
        "DELETE",
        "/api/helper/auth/account",
        headers=auth_header(token),
        json={"password": "WrongPassw0rd", "confirm": "DELETE"},
    )
    assert wrong_password.status_code == 403

    ok = client.request(
        "DELETE",
        "/api/helper/auth/account",
        headers=auth_header(token),
        json={"password": PASSWORD, "confirm": "DELETE"},
    )
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}

    assert client.get("/api/helper/auth/me", headers=auth_header(token)).status_code == 401
    assert login(client).status_code == 401


def test_token_isolation_between_users(client):
    token_a = register(client, username="user_a").json()["token"]
    token_b = register(client, username="user_b").json()["token"]

    me_a = client.get("/api/helper/auth/me", headers=auth_header(token_a)).json()
    me_b = client.get("/api/helper/auth/me", headers=auth_header(token_b)).json()
    assert me_a["user"]["username"] == "user_a"
    assert me_b["user"]["username"] == "user_b"
    assert me_a["user"]["id"] != me_b["user"]["id"]

    # 删除 A 的账号不影响 B 的会话
    assert client.request(
        "DELETE",
        "/api/helper/auth/account",
        headers=auth_header(token_a),
        json={"password": PASSWORD, "confirm": "DELETE"},
    ).status_code == 200

    assert client.get("/api/helper/auth/me", headers=auth_header(token_a)).status_code == 401
    assert client.get("/api/helper/auth/me", headers=auth_header(token_b)).status_code == 200


def test_logout_only_revokes_current_session(client):
    register(client)
    token_one = login(client).json()["token"]
    token_two = login(client).json()["token"]

    assert client.post(
        "/api/helper/auth/logout", headers=auth_header(token_one)
    ).status_code == 200
    assert client.get("/api/helper/auth/me", headers=auth_header(token_one)).status_code == 401
    assert client.get("/api/helper/auth/me", headers=auth_header(token_two)).status_code == 200

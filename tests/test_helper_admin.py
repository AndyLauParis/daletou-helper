"""管理员后台测试：权限边界、概览统计、用户脱敏与反馈处理。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper import db as db_module
from helper.api import auth as auth_api
from helper.security import hash_password, utc_now_iso
from helper_app import app

PASSWORD = "Str0ngPassw0rd"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    auth_api.reset_login_rate_limit()
    with TestClient(app) as test_client:
        yield test_client
    auth_api.reset_login_rate_limit()


def register(client, username="alice") -> str:
    resp = client.post(
        "/api/helper/auth/register",
        json={"username": username, "password": PASSWORD, "is_adult": True},
    )
    assert resp.status_code == 201
    return resp.json()["token"]


def login(client, username, password=PASSWORD) -> dict:
    resp = client.post(
        "/api/helper/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200
    return resp.json()


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_admin(username="root", password=PASSWORD) -> int:
    password_hash, salt_hex = hash_password(password)
    conn = db_module.connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users
                (username, password_hash, password_salt, is_adult, is_admin, created_at)
            VALUES (?, ?, ?, 1, 1, ?)
            """,
            (username, password_hash, salt_hex, utc_now_iso()),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def submit(client, token, content="页面上的按钮点击后没有反应，希望排查一下"):
    return client.post(
        "/api/helper/feedback",
        headers=auth_header(token),
        data={"category": "bug", "content": content},
    )


def test_anonymous_requires_auth(client):
    assert client.get("/api/helper/admin/overview").status_code == 401
    assert client.get("/api/helper/admin/users").status_code == 401
    assert client.get("/api/helper/admin/feedback").status_code == 401
    assert (
        client.patch(
            "/api/helper/admin/feedback/1", json={"status": "resolved"}
        ).status_code
        == 401
    )
    assert client.get("/api/helper/admin/feedback/1/screenshot").status_code == 401


def test_normal_user_forbidden(client):
    token = register(client, "bob")
    headers = auth_header(token)
    assert client.get("/api/helper/admin/overview", headers=headers).status_code == 403
    assert client.get("/api/helper/admin/users", headers=headers).status_code == 403
    assert client.get("/api/helper/admin/feedback", headers=headers).status_code == 403
    assert (
        client.patch(
            "/api/helper/admin/feedback/1",
            headers=headers,
            json={"status": "resolved"},
        ).status_code
        == 403
    )


def test_login_and_me_expose_admin_flag(client):
    make_admin("root")
    data = login(client, "root")
    assert data["user"]["is_admin"] is True
    me = client.get("/api/helper/auth/me", headers=auth_header(data["token"]))
    assert me.status_code == 200
    assert me.json()["user"]["is_admin"] is True


def test_overview_counts_and_user_list_is_sanitized(client):
    bob_token = register(client, "bob")
    submit(client, bob_token)
    make_admin("root")
    root_token = login(client, "root")["token"]
    headers = auth_header(root_token)

    overview = client.get("/api/helper/admin/overview", headers=headers)
    assert overview.status_code == 200
    data = overview.json()
    assert data["users"]["total"] == 2
    assert data["users"]["admins"] == 1
    assert data["feedback"]["total"] == 1
    assert data["feedback"]["open"] == 1
    assert data["numbers"] == 0
    assert data["expenses"]["total"] == 0
    assert any(user["username"] == "bob" for user in data["recent_users"])

    users = client.get("/api/helper/admin/users", headers=headers)
    assert users.status_code == 200
    body = users.json()
    assert body["total"] == 2
    for item in body["items"]:
        assert "password_hash" not in item
        assert "password_salt" not in item
    bob = next(item for item in body["items"] if item["username"] == "bob")
    assert bob["is_admin"] is False
    assert bob["feedback_count"] == 1


def test_feedback_status_update_and_filter(client):
    bob_token = register(client, "bob")
    feedback_id = submit(client, bob_token).json()["id"]
    make_admin("root")
    headers = auth_header(login(client, "root")["token"])

    listing = client.get("/api/helper/admin/feedback", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["username"] == "bob"
    assert listing.json()["items"][0]["status"] == "open"

    updated = client.patch(
        f"/api/helper/admin/feedback/{feedback_id}",
        headers=headers,
        json={"status": "resolved"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "resolved"

    open_items = client.get(
        "/api/helper/admin/feedback?status=open", headers=headers
    ).json()
    assert open_items["total"] == 0
    resolved_items = client.get(
        "/api/helper/admin/feedback?status=resolved", headers=headers
    ).json()
    assert resolved_items["total"] == 1
    assert resolved_items["counts"]["open"] == 0

    assert (
        client.patch(
            f"/api/helper/admin/feedback/{feedback_id}",
            headers=headers,
            json={"status": "unknown"},
        ).status_code
        == 400
    )
    assert (
        client.patch(
            "/api/helper/admin/feedback/9999",
            headers=headers,
            json={"status": "resolved"},
        ).status_code
        == 404
    )


def test_admin_can_read_any_feedback_screenshot(client):
    bob_token = register(client, "bob")
    resp = client.post(
        "/api/helper/feedback",
        headers=auth_header(bob_token),
        data={"category": "bug", "content": "截图反馈：上传后无法显示缩略图"},
        files={"screenshot": ("shot.png", PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 201
    feedback_id = resp.json()["id"]

    make_admin("root")
    headers = auth_header(login(client, "root")["token"])
    shot = client.get(
        f"/api/helper/admin/feedback/{feedback_id}/screenshot", headers=headers
    )
    assert shot.status_code == 200
    assert shot.headers["content-type"].startswith("image/png")

    carol_token = register(client, "carol")
    denied = client.get(
        f"/api/helper/admin/feedback/{feedback_id}/screenshot",
        headers=auth_header(carol_token),
    )
    assert denied.status_code == 403


def test_init_db_migration_is_idempotent(client):
    db_module.init_db()
    db_module.init_db()
    conn = db_module.connect()
    try:
        user_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(users)")
        }
        feedback_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(feedback)")
        }
    finally:
        conn.close()
    assert "is_admin" in user_columns
    assert "status" in feedback_columns

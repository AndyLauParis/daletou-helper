"""反馈 API 测试：登录要求、分类与内容校验、截图校验、跨用户隔离与清理。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper import feedback as feedback_store
from helper.api import auth as auth_api
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


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def submit(client, token, **overrides):
    body = {"category": "bug", "content": "选择娱乐选号后页面没有显示结果"}
    body.update({key: value for key, value in overrides.items() if key != "screenshot"})
    files = None
    if "screenshot" in overrides:
        files = {"screenshot": ("shot.png", overrides["screenshot"], "image/png")}
    return client.post(
        "/api/helper/feedback",
        headers=auth_header(token),
        data=body,
        files=files,
    )


def test_requires_login(client):
    assert client.get("/api/helper/feedback").status_code == 401
    assert submit(client, "bad-token").status_code == 401
    assert client.get("/api/helper/feedback/1/screenshot").status_code == 401


def test_submit_and_list_feedback(client):
    token = register(client)
    resp = submit(client, token)
    assert resp.status_code == 201
    item = resp.json()
    assert item["category"] == "bug"
    assert item["category_label"] == "问题反馈"
    assert item["content"] == "选择娱乐选号后页面没有显示结果"
    assert item["has_screenshot"] is False
    assert item["created_at"]

    listing = client.get("/api/helper/feedback", headers=auth_header(token))
    assert listing.status_code == 200
    data = listing.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == item["id"]


def test_submit_with_screenshot_and_read_it(client):
    token = register(client)
    resp = submit(client, token, screenshot=PNG_BYTES)
    assert resp.status_code == 201
    item = resp.json()
    assert item["has_screenshot"] is True

    files = list(feedback_store.upload_dir().iterdir())
    assert len(files) == 1

    shot = client.get(
        f"/api/helper/feedback/{item['id']}/screenshot",
        headers=auth_header(token),
    )
    assert shot.status_code == 200
    assert shot.headers["content-type"].startswith("image/png")
    assert shot.content == PNG_BYTES
    assert shot.headers["x-content-type-options"] == "nosniff"


def test_validation_rejects_bad_input(client, monkeypatch):
    token = register(client)
    assert submit(client, token, category="unknown").status_code == 400
    assert submit(client, token, content="短").status_code == 400
    assert submit(client, token, content="字" * 1001).status_code == 400
    assert submit(client, token, screenshot=b"not-an-image").status_code == 400

    monkeypatch.setattr(feedback_store, "MAX_SCREENSHOT_BYTES", 16)
    assert submit(client, token, screenshot=PNG_BYTES).status_code == 413
    assert list(feedback_store.upload_dir().iterdir()) == []


def test_feedback_is_isolated_between_users(client):
    alice = register(client, "alice")
    item = submit(client, alice, screenshot=PNG_BYTES).json()
    bob = register(client, "bob")

    listing = client.get("/api/helper/feedback", headers=auth_header(bob))
    assert listing.status_code == 200
    assert listing.json()["total"] == 0
    shot = client.get(
        f"/api/helper/feedback/{item['id']}/screenshot",
        headers=auth_header(bob),
    )
    assert shot.status_code == 404


def test_account_deletion_removes_screenshots(client):
    token = register(client)
    item = submit(client, token, screenshot=PNG_BYTES).json()
    assert item["has_screenshot"] is True
    assert len(list(feedback_store.upload_dir().iterdir())) == 1

    resp = client.request(
        "DELETE",
        "/api/helper/auth/account",
        headers=auth_header(token),
        json={"password": PASSWORD, "confirm": "DELETE"},
    )
    assert resp.status_code == 200
    assert list(feedback_store.upload_dir().iterdir()) == []


def test_feedback_upload_allows_larger_body_than_json_limit(client, monkeypatch):
    """安全层默认 256KB；反馈上传路径应单独放宽，避免正常截图被拦截。"""
    import security_layer

    monkeypatch.setattr(security_layer.SECURITY, "max_body_bytes", 1024)
    token = register(client)
    payload = b"\x89PNG\r\n\x1a\n" + b"0" * 4096
    resp = submit(client, token, screenshot=payload)
    assert resp.status_code == 201

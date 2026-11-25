"""号码本 API 测试：鉴权、跨用户隔离、500 条上限、筛选与号码校验。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper.api import auth as auth_api
from helper.api import records as records_api
from helper_app import app

PASSWORD = "Str0ngPassw0rd"
DTL_PAYLOAD = {"front": [1, 2, 3, 4, 5], "back": [1, 2]}


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


def create_record(client, token, **overrides):
    body = {
        "game_code": "dlt",
        "name": "周末一注",
        "play_type": None,
        "payload": dict(DTL_PAYLOAD),
    }
    body.update(overrides)
    return client.post("/api/helper/numbers", headers=auth_header(token), json=body)


def test_requires_login(client):
    assert client.get("/api/helper/numbers").status_code == 401
    assert create_record(client, "bad-token").status_code == 401
    assert client.put(
        "/api/helper/numbers/1", headers=auth_header("bad-token"), json={"name": "x"}
    ).status_code == 401
    assert client.delete(
        "/api/helper/numbers/1", headers=auth_header("bad-token")
    ).status_code == 401


def test_create_list_and_filter(client):
    token = register(client)
    first = create_record(client, token)
    assert first.status_code == 201
    item = first.json()
    assert item["game_code"] == "dlt"
    assert item["game_name"] == "大乐透"
    assert item["name"] == "周末一注"
    assert item["payload"] == DTL_PAYLOAD
    assert item["created_at"] and item["updated_at"]

    second = create_record(
        client,
        token,
        game_code="ssq",
        name="双色球",
        play_type="单式",
        payload={"red": [1, 2, 3, 4, 5, 6], "blue": [7]},
    )
    assert second.status_code == 201

    listed = client.get("/api/helper/numbers", headers=auth_header(token))
    assert listed.status_code == 200
    data = listed.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    codes = {row["game_code"] for row in data["items"]}
    assert codes == {"dlt", "ssq"}

    filtered = client.get(
        "/api/helper/numbers", headers=auth_header(token), params={"game_code": "dlt"}
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["game_code"] == "dlt"


def test_filter_by_category(client):
    token = register(client)
    assert create_record(client, token, game_code="dlt", name="体彩号码").status_code == 201
    assert create_record(
        client,
        token,
        game_code="ssq",
        name="福彩号码",
        payload={"red": [1, 2, 3, 4, 5, 6], "blue": [7]},
    ).status_code == 201
    assert create_record(
        client,
        token,
        game_code="sfc14",
        name="足彩赛果",
        payload={"picks": ["3"] * 14},
    ).status_code == 201

    ticai = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"category": "ticai_number"},
    ).json()
    assert ticai["total"] == 1
    assert [row["game_code"] for row in ticai["items"]] == ["dlt"]

    fucai = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"category": "fucai_number"},
    ).json()
    assert fucai["total"] == 1
    assert [row["game_code"] for row in fucai["items"]] == ["ssq"]

    zucai = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"category": "zucai"},
    ).json()
    assert zucai["total"] == 1
    assert [row["game_code"] for row in zucai["items"]] == ["sfc14"]


def test_filter_by_days(client):
    token = register(client)
    recent_id = create_record(client, token, name="最近记录").json()["id"]
    old_id = create_record(client, token, name="较早记录").json()["id"]

    old_stamp = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(
        timespec="seconds"
    )
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            "UPDATE number_sets SET created_at = ? WHERE id = ?", (old_stamp, old_id)
        )
        conn.commit()
    finally:
        conn.close()

    within_30 = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"days": 30},
    ).json()
    assert within_30["total"] == 1
    assert [row["id"] for row in within_30["items"]] == [recent_id]

    within_7 = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"days": 7},
    ).json()
    assert within_7["total"] == 1
    assert [row["id"] for row in within_7["items"]] == [recent_id]

    within_90 = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"days": 90},
    ).json()
    assert within_90["total"] == 2


def test_combined_filters_and_total(client):
    token = register(client)
    assert create_record(client, token, game_code="dlt", name="体彩近期").status_code == 201
    old_dlt_id = create_record(
        client, token, game_code="dlt", name="体彩较早"
    ).json()["id"]
    assert create_record(
        client,
        token,
        game_code="ssq",
        name="福彩近期",
        payload={"red": [1, 2, 3, 4, 5, 6], "blue": [7]},
    ).status_code == 201

    old_stamp = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat(
        timespec="seconds"
    )
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            "UPDATE number_sets SET created_at = ? WHERE id = ?",
            (old_stamp, old_dlt_id),
        )
        conn.commit()
    finally:
        conn.close()

    combined = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"category": "ticai_number", "days": 30, "limit": 1, "offset": 0},
    ).json()
    assert combined["total"] == 1
    assert len(combined["items"]) == 1
    assert combined["items"][0]["game_code"] == "dlt"

    contradictory = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"category": "ticai_number", "game_code": "ssq"},
    ).json()
    assert contradictory == {"total": 0, "items": []}

    matched = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"category": "fucai_number", "game_code": "ssq", "days": 7},
    ).json()
    assert matched["total"] == 1
    assert matched["items"][0]["game_code"] == "ssq"

    first_page = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"limit": 1, "offset": 0},
    ).json()
    second_page = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"limit": 1, "offset": 1},
    ).json()
    assert first_page["total"] == 3
    assert second_page["total"] == 3
    assert len(first_page["items"]) == 1
    assert len(second_page["items"]) == 1


def test_unknown_category_rejected(client):
    token = register(client)
    resp = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"category": "unknown"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "未知游戏类别"


def test_pagination(client):
    token = register(client)
    for index in range(3):
        assert create_record(client, token, name=f"第{index}注").status_code == 201

    page = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"limit": 2, "offset": 0},
    ).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2

    tail = client.get(
        "/api/helper/numbers",
        headers=auth_header(token),
        params={"limit": 2, "offset": 2},
    ).json()
    assert tail["total"] == 3
    assert len(tail["items"]) == 1


def test_ordered_by_updated_at_desc(client):
    token = register(client)
    first_id = create_record(client, token, name="旧记录").json()["id"]
    second_id = create_record(client, token, name="新记录").json()["id"]

    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            "UPDATE number_sets SET updated_at = '2026-01-01T00:00:00+00:00' WHERE id = ?",
            (first_id,),
        )
        conn.execute(
            "UPDATE number_sets SET updated_at = '2026-02-01T00:00:00+00:00' WHERE id = ?",
            (second_id,),
        )
        conn.commit()
    finally:
        conn.close()

    items = client.get("/api/helper/numbers", headers=auth_header(token)).json()["items"]
    assert [row["id"] for row in items] == [second_id, first_id]


def test_payload_must_be_json_object(client):
    token = register(client)
    resp = create_record(client, token, payload="不是对象")
    assert resp.status_code == 400
    assert "JSON 对象" in resp.json()["detail"]

    missing = client.post(
        "/api/helper/numbers",
        headers=auth_header(token),
        json={"game_code": "dlt", "name": "空记录"},
    )
    assert missing.status_code == 400


def test_record_name_and_payload_size_limits(client):
    token = register(client)

    long_name = create_record(
        client, token, name="名" * (records_api.MAX_NAME_LENGTH + 1)
    )
    assert long_name.status_code == 400
    assert "名称最多" in long_name.json()["detail"]

    huge_payload = create_record(
        client,
        token,
        payload={"text": "x" * (records_api.MAX_PAYLOAD_BYTES + 1)},
    )
    assert huge_payload.status_code == 400
    assert "payload 内容过大" in huge_payload.json()["detail"]

    record_id = create_record(client, token).json()["id"]
    updated = client.put(
        f"/api/helper/numbers/{record_id}",
        headers=auth_header(token),
        json={"name": "名" * (records_api.MAX_NAME_LENGTH + 1)},
    )
    assert updated.status_code == 400
    assert "名称最多" in updated.json()["detail"]


def test_unknown_game_rejected(client):
    token = register(client)
    resp = create_record(client, token, game_code="not-a-game")
    assert resp.status_code == 400
    assert "未找到" in resp.json()["detail"]


def test_record_limit(client, monkeypatch):
    token = register(client)
    monkeypatch.setattr(records_api, "MAX_RECORDS_PER_USER", 3)
    for _ in range(3):
        assert create_record(client, token).status_code == 201

    over = create_record(client, token)
    assert over.status_code == 400
    assert "号码本最多保存" in over.json()["detail"]


def test_invalid_numbers_rejected(client):
    token = register(client)

    missing_back = create_record(
        client,
        token,
        payload={"front": [1, 2, 3, 4, 5], "back": [1]},
    )
    assert missing_back.status_code == 400
    assert missing_back.json()["detail"].startswith("号码格式不正确：")
    assert "后区需要 2 个号码" in missing_back.json()["detail"]

    out_of_range = create_record(
        client,
        token,
        payload={"front": [1, 2, 3, 4, 36], "back": [1, 2]},
    )
    assert out_of_range.status_code == 400
    assert "前区号码范围应为 1-35" in out_of_range.json()["detail"]

    duplicate = create_record(
        client,
        token,
        payload={"front": [1, 1, 3, 4, 5], "back": [1, 2]},
    )
    assert duplicate.status_code == 400
    assert "前区号码不能重复" in duplicate.json()["detail"]

    assert client.get("/api/helper/numbers", headers=auth_header(token)).json() == {
        "total": 0,
        "items": [],
    }


def test_invalid_play_type_rejected(client):
    token = register(client)
    resp = create_record(
        client,
        token,
        game_code="pl3",
        play_type="不存在的玩法",
        payload={"digits": [1, 2, 3]},
    )
    assert resp.status_code == 400
    assert "不支持的玩法" in resp.json()["detail"]
    assert client.get("/api/helper/numbers", headers=auth_header(token)).json()["total"] == 0


def test_catalog_game_accepts_any_payload(client, monkeypatch):
    class StrictAdapter:
        @staticmethod
        def validate_ticket(payload, play_type=None):
            return {"ok": False, "errors": ["不应被调用"]}

    monkeypatch.setattr(records_api.registry, "get_adapter", lambda code: StrictAdapter())
    token = register(client)
    resp = create_record(client, token, game_code="dgg", payload={"text": "一张刮刮乐"})
    assert resp.status_code == 201
    assert "warning" not in resp.json()
    assert resp.json()["payload"] == {"text": "一张刮刮乐"}


def test_update_own_record(client):
    token = register(client)
    record_id = create_record(client, token).json()["id"]

    new_payload = {"front": [1, 2, 3, 4, 6], "back": [3, 4]}
    updated = client.put(
        f"/api/helper/numbers/{record_id}",
        headers=auth_header(token),
        json={"name": "改名", "play_type": "复式", "payload": new_payload},
    )
    assert updated.status_code == 200
    data = updated.json()
    assert data["name"] == "改名"
    assert data["play_type"] == "复式"
    assert data["payload"] == new_payload

    partial = client.put(
        f"/api/helper/numbers/{record_id}",
        headers=auth_header(token),
        json={"name": "只改名称"},
    ).json()
    assert partial["name"] == "只改名称"
    assert partial["play_type"] == "复式"


def test_update_invalid_payload_rejected(client):
    token = register(client)
    record_id = create_record(client, token).json()["id"]

    invalid = client.put(
        f"/api/helper/numbers/{record_id}",
        headers=auth_header(token),
        json={"payload": {"front": [1, 2, 3, 4, 5], "back": [1]}},
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"].startswith("号码格式不正确：")

    unchanged = client.get(
        "/api/helper/numbers", headers=auth_header(token)
    ).json()["items"][0]
    assert unchanged["payload"] == DTL_PAYLOAD
    assert unchanged["name"] == "周末一注"

    valid = client.put(
        f"/api/helper/numbers/{record_id}",
        headers=auth_header(token),
        json={"payload": {"front": [6, 7, 8, 9, 10], "back": [5, 6]}},
    )
    assert valid.status_code == 200
    assert valid.json()["payload"] == {"front": [6, 7, 8, 9, 10], "back": [5, 6]}


def test_update_rejects_non_object_payload(client):
    token = register(client)
    record_id = create_record(client, token).json()["id"]
    resp = client.put(
        f"/api/helper/numbers/{record_id}",
        headers=auth_header(token),
        json={"payload": [1, 2, 3]},
    )
    assert resp.status_code == 400


def test_delete_own_record(client):
    token = register(client)
    record_id = create_record(client, token).json()["id"]
    resp = client.delete(f"/api/helper/numbers/{record_id}", headers=auth_header(token))
    assert resp.status_code == 204
    assert client.get("/api/helper/numbers", headers=auth_header(token)).json()["total"] == 0
    missing = client.delete(f"/api/helper/numbers/{record_id}", headers=auth_header(token))
    assert missing.status_code == 404


def test_cross_user_isolation(client):
    token_a = register(client, "user_a")
    token_b = register(client, "user_b")
    record_id = create_record(client, token_a).json()["id"]

    assert client.get("/api/helper/numbers", headers=auth_header(token_b)).json() == {
        "total": 0,
        "items": [],
    }

    update = client.put(
        f"/api/helper/numbers/{record_id}",
        headers=auth_header(token_b),
        json={"name": "越权改名"},
    )
    assert update.status_code == 404
    assert update.json()["detail"] == "未找到该记录"

    delete = client.delete(
        f"/api/helper/numbers/{record_id}", headers=auth_header(token_b)
    )
    assert delete.status_code == 404
    assert delete.json()["detail"] == "未找到该记录"

    still_there = client.get("/api/helper/numbers", headers=auth_header(token_a)).json()
    assert still_there["total"] == 1
    assert still_there["items"][0]["name"] == "周末一注"

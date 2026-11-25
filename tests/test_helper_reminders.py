"""提醒 API 测试：16 个游戏、上下期时间计算、提前分钟边界与 upcoming 窗口。"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper.api import auth as auth_api
from helper.api import reminders as reminders_api
from helper.games import registry
from helper_app import app

PASSWORD = "Str0ngPassw0rd"
TZ = reminders_api.TZ
NO_FIXED_CODES = {"sfc14", "rx9", "jq4", "bqc6", "jczq", "jclq", "dgg", "ggl"}


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


def put_reminder(client, token, code, enabled=True, lead_minutes=60):
    return client.put(
        f"/api/helper/reminders/{code}",
        headers=auth_header(token),
        json={"enabled": enabled, "lead_minutes": lead_minutes},
    )


def test_requires_login(client):
    assert client.get("/api/helper/reminders").status_code == 401
    assert client.get("/api/helper/reminders/upcoming").status_code == 401
    assert put_reminder(client, "bad-token", "dlt").status_code == 401


def test_lists_all_games_with_defaults(client):
    token = register(client)
    resp = client.get("/api/helper/reminders", headers=auth_header(token))
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert [item["game_code"] for item in items] == [meta.code for meta in registry.list_games()]
    assert len(items) == 16

    by_code = {item["game_code"]: item for item in items}
    dlt = by_code["dlt"]
    assert dlt["game_name"] == "大乐透"
    assert dlt["category_label"] == "体彩数字型"
    assert dlt["enabled"] is False
    assert dlt["lead_minutes"] == 60
    assert dlt["schedule_text"] == "周一、周三、周六 20:30"
    assert dlt["next_draw_at"]
    assert dlt["note"] is None

    for code in NO_FIXED_CODES:
        item = by_code[code]
        assert item["next_draw_at"] is None
        assert item["next_draw_text"] is None
        assert item["note"] == "按赛程，无固定开奖时间"


def test_unknown_game_returns_404(client):
    token = register(client)
    resp = put_reminder(client, token, "not-a-game")
    assert resp.status_code == 404
    assert "未找到" in resp.json()["detail"]


@pytest.mark.parametrize("lead", [4, 0, -10, 181, 5000])
def test_lead_minutes_out_of_range(client, lead):
    token = register(client)
    resp = put_reminder(client, token, "dlt", lead_minutes=lead)
    assert resp.status_code == 400
    assert "5" in resp.json()["detail"] and "180" in resp.json()["detail"]


def test_upsert_and_boundaries(client):
    token = register(client)
    assert put_reminder(client, token, "dlt", enabled=True, lead_minutes=5).status_code == 200
    assert put_reminder(client, token, "dlt", enabled=True, lead_minutes=180).status_code == 200

    enabled = put_reminder(client, token, "dlt", enabled=True, lead_minutes=30)
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["lead_minutes"] == 30

    disabled = put_reminder(client, token, "dlt", enabled=False, lead_minutes=30)
    assert disabled.json()["enabled"] is False

    items = {
        item["game_code"]: item
        for item in client.get(
            "/api/helper/reminders", headers=auth_header(token)
        ).json()
    }
    assert items["dlt"]["enabled"] is False
    assert items["dlt"]["lead_minutes"] == 30


def test_settings_isolated_between_users(client):
    token_a = register(client, "user_a")
    token_b = register(client, "user_b")
    assert put_reminder(client, token_a, "dlt", enabled=True, lead_minutes=30).status_code == 200

    items_b = {
        item["game_code"]: item
        for item in client.get(
            "/api/helper/reminders", headers=auth_header(token_b)
        ).json()
    }
    assert items_b["dlt"]["enabled"] is False
    assert items_b["dlt"]["lead_minutes"] == 60


def test_next_draw_calculation_from_registry(client, monkeypatch):
    # 2026-11-24 是周二
    monkeypatch.setattr(
        reminders_api, "_now", lambda: datetime(2026, 11, 24, 21, 0, tzinfo=TZ)
    )
    token = register(client)
    items = {
        item["game_code"]: item
        for item in client.get(
            "/api/helper/reminders", headers=auth_header(token)
        ).json()
    }
    # 大乐透周一/三/六 20:30，周二晚之后应为周三
    assert items["dlt"]["next_draw_at"] == "2026-11-25T20:30:00+08:00"
    # 双色球周二/四/日 21:15，周二 21:00 已过 21:15 前？未到 21:15，应为当天
    assert items["ssq"]["next_draw_at"] == "2026-11-24T21:15:00+08:00"
    # 七星彩周二/五/日 20:30，已过，应为周五
    assert items["qxc"]["next_draw_at"] == "2026-11-27T20:30:00+08:00"


def test_next_draw_skips_current_exact_time(client, monkeypatch):
    # 周三 20:30:00 整点应计算下一期（周六），而不是当前时刻
    monkeypatch.setattr(
        reminders_api, "_now", lambda: datetime(2026, 11, 25, 20, 30, tzinfo=TZ)
    )
    token = register(client)
    items = {
        item["game_code"]: item
        for item in client.get(
            "/api/helper/reminders", headers=auth_header(token)
        ).json()
    }
    assert items["dlt"]["next_draw_at"] == "2026-11-28T20:30:00+08:00"


def test_upcoming_window(client, monkeypatch):
    # 周三 19:50，大乐透 20:30 开奖，距开奖 40 分钟
    monkeypatch.setattr(
        reminders_api, "_now", lambda: datetime(2026, 11, 25, 19, 50, tzinfo=TZ)
    )
    token = register(client)
    assert put_reminder(client, token, "dlt", enabled=True, lead_minutes=60).status_code == 200
    assert put_reminder(client, token, "sfc14", enabled=True, lead_minutes=60).status_code == 200

    resp = client.get("/api/helper/reminders/upcoming", headers=auth_header(token))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    entry = items[0]
    assert entry["game_code"] == "dlt"
    assert entry["game_name"] == "大乐透"
    assert entry["next_draw_at"] == "2026-11-25T20:30:00+08:00"
    assert entry["minutes_left"] == 40
    assert "大乐透" in entry["message"]
    assert "40" in entry["message"]


def test_upcoming_respects_lead_minutes_and_disabled(client, monkeypatch):
    monkeypatch.setattr(
        reminders_api, "_now", lambda: datetime(2026, 11, 25, 19, 50, tzinfo=TZ)
    )
    token = register(client)

    # 未启用时不出现在 upcoming
    assert client.get(
        "/api/helper/reminders/upcoming", headers=auth_header(token)
    ).json() == []

    # 提前 5 分钟，距离开奖 40 分钟，尚不在窗口内
    assert put_reminder(client, token, "dlt", enabled=True, lead_minutes=5).status_code == 200
    assert client.get(
        "/api/helper/reminders/upcoming", headers=auth_header(token)
    ).json() == []

    # 调大窗口到 180 分钟后出现，再关闭提醒后消失
    assert put_reminder(client, token, "dlt", enabled=True, lead_minutes=180).status_code == 200
    assert len(
        client.get("/api/helper/reminders/upcoming", headers=auth_header(token)).json()
    ) == 1
    assert put_reminder(client, token, "dlt", enabled=False, lead_minutes=180).status_code == 200
    assert client.get(
        "/api/helper/reminders/upcoming", headers=auth_header(token)
    ).json() == []


def test_upcoming_ignores_games_without_fixed_schedule(client, monkeypatch):
    monkeypatch.setattr(
        reminders_api, "_now", lambda: datetime(2026, 11, 24, 10, 0, tzinfo=TZ)
    )
    token = register(client)
    for code in NO_FIXED_CODES:
        assert put_reminder(client, token, code, enabled=True, lead_minutes=180).status_code == 200
    assert client.get(
        "/api/helper/reminders/upcoming", headers=auth_header(token)
    ).json() == []

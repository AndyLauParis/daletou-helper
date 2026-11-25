"""预算与支出 API 测试：金额/日期边界、分游戏汇总、超支与跨用户隔离。"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper.api import auth as auth_api
from helper.api import budget as budget_api
from helper_app import app

PASSWORD = "Str0ngPassw0rd"
TODAY = date(2026, 11, 24)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(budget_api, "_today", lambda: TODAY)
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


def set_budget(client, token, value):
    return client.put(
        "/api/helper/budget", headers=auth_header(token), json={"monthly_budget": value}
    )


def add_expense(client, token, amount=20.0, game_code="dlt", spent_on="2026-11-20", note=""):
    return client.post(
        "/api/helper/expenses",
        headers=auth_header(token),
        json={
            "game_code": game_code,
            "amount": amount,
            "spent_on": spent_on,
            "note": note,
        },
    )


def test_requires_login(client):
    assert client.get("/api/helper/budget").status_code == 401
    assert set_budget(client, "bad-token", 100).status_code == 401
    assert client.get("/api/helper/expenses").status_code == 401
    assert add_expense(client, "bad-token").status_code == 401
    assert client.delete(
        "/api/helper/expenses/1", headers=auth_header("bad-token")
    ).status_code == 401
    assert client.get("/api/helper/budget/summary").status_code == 401


def test_budget_default_and_upsert(client):
    token = register(client)
    default = client.get("/api/helper/budget", headers=auth_header(token)).json()
    assert default["monthly_budget"] == 0.0
    assert default["updated_at"] is None

    assert set_budget(client, token, 1200.5).status_code == 200
    saved = client.get("/api/helper/budget", headers=auth_header(token)).json()
    assert saved["monthly_budget"] == 1200.5
    assert saved["updated_at"]

    assert set_budget(client, token, 800).status_code == 200
    assert client.get(
        "/api/helper/budget", headers=auth_header(token)
    ).json()["monthly_budget"] == 800.0


@pytest.mark.parametrize("value", [-0.01, -100, 1_000_000.01, 5_000_000])
def test_budget_out_of_range(client, value):
    token = register(client)
    resp = set_budget(client, token, value)
    assert resp.status_code == 400
    assert "月度预算" in resp.json()["detail"]


def test_budget_boundaries_and_rounding(client):
    token = register(client)
    assert set_budget(client, token, 0).json()["monthly_budget"] == 0.0
    assert set_budget(client, token, 1_000_000).status_code == 200
    assert set_budget(client, token, 100.556).json()["monthly_budget"] == 100.56


def test_expense_validation(client):
    token = register(client)
    assert add_expense(client, token, amount=0).status_code == 400
    assert add_expense(client, token, amount=-5).status_code == 400
    assert add_expense(client, token, amount=100_000.01).status_code == 400
    assert add_expense(client, token, amount=100_000).status_code == 201

    future = add_expense(client, token, spent_on="2026-11-25")
    assert future.status_code == 400
    assert "不能晚于今天" in future.json()["detail"]

    bad_date = add_expense(client, token, spent_on="2026/11/20")
    assert bad_date.status_code == 400
    assert "YYYY-MM-DD" in bad_date.json()["detail"]

    long_note = add_expense(client, token, note="备" * 201)
    assert long_note.status_code == 400
    assert "200" in long_note.json()["detail"]

    unknown_game = add_expense(client, token, game_code="nope")
    assert unknown_game.status_code == 400

    boundary_date = add_expense(client, token, spent_on="2026-11-24")
    assert boundary_date.status_code == 201


def test_create_and_list_expenses(client):
    token = register(client)
    first = add_expense(client, token, amount=30, game_code="dlt", spent_on="2026-11-10", note="体彩")
    assert first.status_code == 201
    data = first.json()
    assert data["game_name"] == "大乐透"
    assert data["amount"] == 30.0
    assert data["spent_on"] == "2026-11-10"
    assert data["note"] == "体彩"

    assert add_expense(client, token, amount=20, game_code="ssq", spent_on="2026-11-20").status_code == 201
    assert add_expense(client, token, amount=50, game_code="ssq", spent_on="2026-10-15").status_code == 201

    current = client.get(
        "/api/helper/expenses", headers=auth_header(token), params={"month": "2026-11"}
    ).json()
    assert current["total"] == 2
    assert [row["spent_on"] for row in current["items"]] == ["2026-11-20", "2026-11-10"]

    only_ssq = client.get(
        "/api/helper/expenses",
        headers=auth_header(token),
        params={"month": "2026-11", "game_code": "ssq"},
    ).json()
    assert only_ssq["total"] == 1
    assert only_ssq["items"][0]["game_code"] == "ssq"

    all_months = client.get("/api/helper/expenses", headers=auth_header(token)).json()
    assert all_months["total"] == 3

    assert client.get(
        "/api/helper/expenses", headers=auth_header(token), params={"month": "2026-13"}
    ).status_code == 400


def test_delete_expense_only_own(client):
    token_a = register(client, "user_a")
    token_b = register(client, "user_b")
    expense_id = add_expense(client, token_a).json()["id"]

    assert client.delete(
        f"/api/helper/expenses/{expense_id}", headers=auth_header(token_b)
    ).status_code == 404
    assert client.get(
        "/api/helper/expenses", headers=auth_header(token_b)
    ).json()["total"] == 0

    assert client.delete(
        f"/api/helper/expenses/{expense_id}", headers=auth_header(token_a)
    ).status_code == 204
    assert client.get(
        "/api/helper/expenses", headers=auth_header(token_a)
    ).json()["total"] == 0


def test_budget_summary(client):
    token = register(client)
    assert set_budget(client, token, 1000).status_code == 200
    assert add_expense(client, token, amount=30.5, game_code="dlt").status_code == 201
    assert add_expense(client, token, amount=20.25, game_code="ssq").status_code == 201
    assert add_expense(client, token, amount=99, game_code="dlt", spent_on="2026-10-15").status_code == 201

    summary = client.get(
        "/api/helper/budget/summary",
        headers=auth_header(token),
        params={"month": "2026-11"},
    )
    assert summary.status_code == 200
    data = summary.json()
    assert data["month"] == "2026-11"
    assert data["monthly_budget"] == 1000.0
    assert data["total_spent"] == 50.75
    assert data["remaining"] == 949.25
    assert data["over_budget"] is False
    assert data["entry_count"] == 2
    assert data["by_game"][0] == {
        "game_code": "dlt",
        "game_name": "大乐透",
        "amount": 30.5,
        "count": 1,
    }
    assert data["by_game"][1]["game_code"] == "ssq"

    default_summary = client.get(
        "/api/helper/budget/summary", headers=auth_header(token)
    ).json()
    assert default_summary["month"] == "2026-11"

    assert set_budget(client, token, 50).status_code == 200
    over = client.get(
        "/api/helper/budget/summary",
        headers=auth_header(token),
        params={"month": "2026-11"},
    ).json()
    assert over["over_budget"] is True
    assert over["remaining"] == -0.75


def test_summary_empty_month(client):
    token = register(client)
    data = client.get(
        "/api/helper/budget/summary",
        headers=auth_header(token),
        params={"month": "2026-01"},
    ).json()
    assert data["monthly_budget"] == 0.0
    assert data["total_spent"] == 0.0
    assert data["remaining"] == 0.0
    assert data["over_budget"] is False
    assert data["by_game"] == []
    assert data["entry_count"] == 0


def test_budget_data_isolated_between_users(client):
    token_a = register(client, "user_a")
    token_b = register(client, "user_b")
    assert set_budget(client, token_a, 500).status_code == 200
    assert add_expense(client, token_a, amount=10).status_code == 201

    budget_b = client.get("/api/helper/budget", headers=auth_header(token_b)).json()
    assert budget_b["monthly_budget"] == 0.0
    expenses_b = client.get("/api/helper/expenses", headers=auth_header(token_b)).json()
    assert expenses_b["total"] == 0
    summary_b = client.get(
        "/api/helper/budget/summary", headers=auth_header(token_b)
    ).json()
    assert summary_b["total_spent"] == 0.0
    assert summary_b["monthly_budget"] == 0.0

"""娱乐选号：接口契约、组合规则与页面免责约束。"""

from __future__ import annotations

import random
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from helper import config, lab
from helper.api import auth as auth_api
from helper.games import cache
from helper_app import app

STATIC_DIR = Path(config.STATIC_DIR)

DISCLAIMER = (
    "本工具所有预测结果仅供娱乐和参考，不构成任何购彩建议，"
    "彩票有风险，购彩需理性"
)

METHOD_KEYS = (
    "random",
    "hot",
    "cold",
    "omission",
    "odd_even",
    "sum_range",
    "zone_balance",
)


def _dlt_draws(count: int = 80) -> list[dict]:
    rng = random.Random(20260101)
    start = date(2026, 1, 1)
    draws = []
    for index in range(count):
        draws.append(
            {
                "issue": f"26{index + 1:03d}",
                "date": (start + timedelta(days=index * 2)).isoformat(),
                "numbers": {
                    "front": sorted(rng.sample(range(1, 36), 5)),
                    "back": sorted(rng.sample(range(1, 13), 2)),
                },
            }
        )
    return list(reversed(draws))  # 新 -> 旧


def _pl3_draws(count: int = 40) -> list[dict]:
    rng = random.Random(7)
    start = date(2026, 3, 1)
    draws = []
    for index in range(count):
        draws.append(
            {
                "issue": f"26{index + 1:03d}",
                "date": (start + timedelta(days=index)).isoformat(),
                "numbers": {"digits": [rng.randrange(10) for _ in range(3)]},
            }
        )
    return list(reversed(draws))


@pytest.fixture()
def picker_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(lab, "_core_dlt_draws", lambda: [])
    cache.save_cache("dlt", _dlt_draws(), source="test")
    cache.save_cache("pl3", _pl3_draws(), source="test")
    with TestClient(app) as test_client:
        yield test_client


def _generate(client: TestClient, game: str, method: str, tickets: int = 1):
    return client.post(
        "/api/helper/picker/generate",
        json={"game": game, "method": method, "tickets": tickets},
    )


def _values(group: dict) -> list[int]:
    return [number["value"] for number in group["numbers"]]


# ---------------------------------------------------------------------------
# 选项与接口契约
# ---------------------------------------------------------------------------


def test_picker_options_list_games_and_methods(picker_env):
    payload = picker_env.get("/api/helper/picker/options").json()

    assert [method["key"] for method in payload["methods"]] == list(METHOD_KEYS)
    assert payload["disclaimer"] == DISCLAIMER
    assert "不提高中奖概率" in payload["notice"]

    games = {game["code"]: game for game in payload["games"]}
    assert {"dlt", "pl3"} <= set(games)
    assert games["dlt"]["digit_mode"] is False
    assert games["pl3"]["digit_mode"] is True


@pytest.mark.parametrize("method", METHOD_KEYS)
def test_each_method_generates_valid_dlt_tickets(picker_env, method):
    resp = _generate(picker_env, "dlt", method, tickets=3)
    assert resp.status_code == 200
    data = resp.json()

    assert data["disclaimer"] == DISCLAIMER
    assert data["game"]["code"] == "dlt"
    assert data["method"]["key"] == method
    assert "不改变任何一注彩票的中奖概率" in data["method"]["caveat"]
    assert len(data["tickets"]) == 3

    for ticket in data["tickets"]:
        assert [group["key"] for group in ticket] == ["front", "back"]
        front = _values(ticket[0])
        back = _values(ticket[1])
        assert len(front) == 5
        assert len(set(front)) == 5
        assert all(1 <= value <= 35 for value in front)
        assert len(back) == 2
        assert len(set(back)) == 2
        assert all(1 <= value <= 12 for value in back)
        assert all(len(number["display"]) == 2 for number in ticket[0]["numbers"])
        assert all(len(number["display"]) == 2 for number in ticket[1]["numbers"])

    if method in ("hot", "cold", "omission", "sum_range"):
        assert data["data"]["window"] == 80
        assert data["data"]["latest_issue"]
        assert data["method"]["fallback"] is False


def test_digit_game_generates_one_digit_per_position(picker_env):
    resp = _generate(picker_env, "pl3", "random", tickets=2)
    assert resp.status_code == 200
    data = resp.json()

    assert data["game"]["digit_mode"] is True
    for ticket in data["tickets"]:
        assert [group["key"] for group in ticket] == ["p1", "p2", "p3"]
        for group in ticket:
            values = _values(group)
            assert len(values) == 1
            assert 0 <= values[0] <= 9
            assert group["numbers"][0]["display"] == str(values[0])


def test_odd_even_keeps_each_ticket_balanced(picker_env):
    resp = _generate(picker_env, "dlt", "odd_even", tickets=5)
    assert resp.status_code == 200
    for ticket in resp.json()["tickets"]:
        odds = sum(1 for value in _values(ticket[0]) if value % 2)
        assert odds in (2, 3)


def test_zone_balance_spreads_front_numbers_across_zones(picker_env):
    resp = _generate(picker_env, "dlt", "zone_balance", tickets=3)
    assert resp.status_code == 200
    for ticket in resp.json()["tickets"]:
        front = _values(ticket[0])
        counts = [
            sum(1 for value in front if 1 <= value <= 12),
            sum(1 for value in front if 13 <= value <= 23),
            sum(1 for value in front if 24 <= value <= 35),
        ]
        assert sorted(counts) == [1, 2, 2]


def test_picker_rejects_invalid_requests(picker_env):
    assert _generate(picker_env, "unknown", "random").status_code == 404
    assert _generate(picker_env, "dlt", "unknown-method").status_code == 400
    assert _generate(picker_env, "pl3", "zone_balance").status_code == 400
    assert _generate(picker_env, "dlt", "random", tickets=0).status_code == 422
    assert _generate(picker_env, "dlt", "random", tickets=11).status_code == 422


def test_picker_falls_back_to_random_without_history(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "empty-cache")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(lab, "_core_dlt_draws", lambda: [])

    with TestClient(app) as client:
        resp = _generate(client, "dlt", "hot", tickets=2)

    assert resp.status_code == 200
    data = resp.json()
    assert data["method"]["effective"] == "random"
    assert data["method"]["fallback"] is True
    assert data["data"]["window"] == 0
    assert any("样本不足" in note for note in data["constraints"])


# ---------------------------------------------------------------------------
# 页面与入口
# ---------------------------------------------------------------------------


def test_picker_page_shows_disclaimer_top_and_bottom(picker_env):
    resp = picker_env.get("/picker")
    assert resp.status_code == 200
    html = resp.text

    assert html.count(DISCLAIMER) >= 2
    top = html.index(DISCLAIMER)
    bottom = html.rindex(DISCLAIMER)
    assert top < bottom
    assert "/static/js/picker.js" in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert "onclick=" not in html
    for misleading in ("保证中奖", "必中", "包中", "稳赚"):
        assert misleading not in html

    script = picker_env.get("/static/js/picker.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"].lower()


def test_picker_entries_exist_in_nav_landing_and_workbench():
    common_js = (STATIC_DIR / "js" / "common.js").read_text(encoding="utf-8")
    assert 'href: "/picker"' in common_js
    assert 'label: "娱乐选号"' in common_js

    landing = (STATIC_DIR / "landing.html").read_text(encoding="utf-8")
    assert 'href="/picker"' in landing

    workbench = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'href="/picker"' in workbench


def test_compliance_page_mentions_entertainment_picking():
    html = (STATIC_DIR / "compliance.html").read_text(encoding="utf-8")
    assert "娱乐选号" in html
    assert "不承诺中奖" in html
    assert "不预测开奖" in html

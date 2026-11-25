"""历史数据实验室：统计口径、接口契约与页面约束。"""

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
def lab_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(lab, "_core_dlt_draws", lambda: [])
    auth_api.reset_login_rate_limit()
    cache.save_cache("dlt", _dlt_draws(), source="test")
    cache.save_cache("pl3", _pl3_draws(), source="test")
    with TestClient(app) as test_client:
        yield test_client
    auth_api.reset_login_rate_limit()


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


def test_lab_games_lists_only_analyzable_numbers_games(lab_env):
    resp = lab_env.get("/api/helper/lab/games")
    assert resp.status_code == 200
    payload = resp.json()
    codes = {game["code"] for game in payload["games"]}
    assert {"dlt", "ssq", "pl3", "kl8"} <= codes
    assert "jczq" not in codes

    dlt = next(game for game in payload["games"] if game["code"] == "dlt")
    assert dlt["draw_count"] == 80
    assert dlt["budget_supported"] is True
    pl3 = next(game for game in payload["games"] if game["code"] == "pl3")
    assert pl3["budget_supported"] is False
    assert "不预测" in payload["notice"]


def test_lab_analysis_combines_frequency_shape_tests_and_backtest(lab_env):
    resp = lab_env.get("/api/helper/lab/analysis?game=dlt&window=40")
    assert resp.status_code == 200
    data = resp.json()

    assert data["window_used"] == 40
    assert data["window_requested"] == 40
    assert data["available_draws"] == 80
    assert data["latest_issue"]
    assert "不能预测" in data["note"]

    assert len(data["recent"]) == 10
    assert data["recent"][0]["issue"] > data["recent"][-1]["issue"]

    assert [group["key"] for group in data["frequency"]] == ["front", "back"]
    assert len(data["frequency"][0]["numbers"]) == 35
    assert len(data["frequency"][1]["numbers"]) == 12
    assert data["frequency"][0]["numbers"][0]["expected_rate"] == pytest.approx(5 / 35)

    assert data["shape"]["sum"]["theoretical_mean"] == pytest.approx(90.0)
    assert data["shape"]["zones"][0]["expected"] == pytest.approx(5 / 3)

    tests = data["randomness"]["tests"]
    assert [item["key"] for item in tests] == [
        "chi_square",
        "entropy",
        "sum_stdev",
        "repeat_mean",
        "runs_z",
    ]
    for item in tests:
        assert 0 < item["p_value"] <= 1
        assert item["null_p05"] <= item["null_p95"]

    backtest = data["backtest"]
    assert [item["key"] for item in backtest["strategies"]] == [
        "hot",
        "cold",
        "random",
    ]
    assert backtest["expected_hits"] == pytest.approx(
        5 * 5 / 35 + 2 * 2 / 12, abs=1e-4
    )
    assert backtest["expected_by_group"][0]["expected_hits"] == pytest.approx(
        25 / 35, abs=1e-4
    )
    assert "不能改变下一期的中奖概率" in backtest["note"]


def test_lab_analysis_is_deterministic_for_same_request(lab_env):
    first = lab_env.get("/api/helper/lab/analysis?game=dlt&window=30").json()
    second = lab_env.get("/api/helper/lab/analysis?game=dlt&window=30").json()
    assert first["randomness"]["tests"] == second["randomness"]["tests"]
    assert first["backtest"]["strategies"] == second["backtest"]["strategies"]


def test_lab_analysis_supports_digit_games(lab_env):
    resp = lab_env.get("/api/helper/lab/analysis?game=pl3&window=30")
    assert resp.status_code == 200
    data = resp.json()
    assert [group["key"] for group in data["frequency"]] == ["p1", "p2", "p3"]
    assert len(data["frequency"][0]["numbers"]) == 10
    assert data["shape"]["pick_total"] == 3
    assert data["shape"]["sum"]["theoretical_mean"] == pytest.approx(13.5)
    assert data["game"]["budget_supported"] is False


def test_lab_analysis_rejects_unknown_or_unsupported_games(lab_env):
    assert lab_env.get("/api/helper/lab/analysis?game=unknown").status_code == 404
    assert lab_env.get("/api/helper/lab/analysis?game=jczq").status_code == 400


def test_lab_analysis_requires_minimum_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(lab, "_core_dlt_draws", lambda: [])
    cache.save_cache("dlt", _dlt_draws(5), source="test")

    with TestClient(app) as client:
        resp = client.get("/api/helper/lab/analysis?game=dlt&window=30")
    assert resp.status_code == 409
    assert "样本不足" in resp.json()["detail"]


def test_lab_budget_reports_loss_distribution(lab_env):
    resp = lab_env.get("/api/helper/lab/budget?game=dlt&periods=20&tickets=2")
    assert resp.status_code == 200
    data = resp.json()

    assert data["spend"] == pytest.approx(80.0)
    assert data["p_loss"] + data["p_profit"] + data["p_even"] == pytest.approx(1.0)
    assert sum(row["share"] for row in data["distribution"]) == pytest.approx(1.0)
    assert data["net_percentiles"]["p05"] <= data["net_percentiles"]["p50"]
    assert data["net_percentiles"]["p50"] <= data["net_percentiles"]["p95"]
    assert "浮动奖" in data["note"]
    assert 0 < data["per_ticket_any_prize"] < 1


def test_lab_budget_rejects_unsupported_game(lab_env):
    resp = lab_env.get("/api/helper/lab/budget?game=pl3&periods=10&tickets=1")
    assert resp.status_code == 400
    assert lab_env.get("/api/helper/lab/budget?game=unknown").status_code == 404


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


def test_lab_page_available_and_uses_external_script(lab_env):
    resp = lab_env.get("/lab")
    assert resp.status_code == 200
    html = resp.text
    assert "历史数据实验室" in html
    assert "不预测号码" in html
    assert "/static/js/lab.js" in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert "onclick=" not in html

    script = lab_env.get("/static/js/lab.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"].lower()


def test_lab_entries_exist_in_nav_landing_and_workbench():
    common_js = (STATIC_DIR / "js" / "common.js").read_text(encoding="utf-8")
    assert 'href: "/lab"' in common_js
    landing = (STATIC_DIR / "landing.html").read_text(encoding="utf-8")
    assert 'href="/lab"' in landing
    workbench = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'href="/lab"' in workbench


# ---------------------------------------------------------------------------
# 统计口径
# ---------------------------------------------------------------------------


def test_frequency_omission_matches_constructed_sequence():
    profile = lab.PROFILES["pl3"]
    sequence = []
    for index, digits in enumerate(([1, 2, 3], [4, 5, 6], [7, 8, 9])):
        sequence.append(
            {
                "draw": {"issue": str(index), "date": "2026-01-01"},
                "groups": lab.extract_groups(
                    profile, {"numbers": {"digits": digits}}
                ),
            }
        )

    table = lab.frequency_table(profile, sequence)
    first_position = {row["number"]: row for row in table[0]["numbers"]}
    assert first_position[1]["count"] == 1
    assert first_position[1]["current_omission"] == 2
    assert first_position[7]["current_omission"] == 0
    assert first_position[0]["count"] == 0
    assert first_position[0]["max_omission"] == 3


def test_extract_groups_rejects_out_of_range_numbers():
    profile = lab.PROFILES["dlt"]
    assert (
        lab.extract_groups(
            profile, {"numbers": {"front": [1, 2, 3, 4, 36], "back": [1, 2]}}
        )
        is None
    )
    assert (
        lab.extract_groups(profile, {"numbers": {"front": [1, 2, 3, 4], "back": [1, 2]}})
        is None
    )
    assert (
        lab.extract_groups(
            profile, {"numbers": {"front": [1, 2, 3, 4, 5], "back": [1, 2]}}
        )
        is not None
    )


def test_backtest_uses_only_prior_draws(lab_env):
    data = lab_env.get("/api/helper/lab/analysis?game=pl3&window=30").json()
    backtest = data["backtest"]
    assert backtest["test_size"] <= 30
    assert backtest["lookback"] <= 30
    for strategy in backtest["strategies"]:
        assert strategy["tickets"] == backtest["test_size"]
        assert strategy["avg_hits"] <= 3
        assert sum(row["count"] for row in strategy["hit_histogram"]) == strategy["tickets"]


def test_budget_simulation_is_reproducible():
    first = lab.simulate_budget("ssq", periods=10, tickets_per_period=1, trials=300)
    second = lab.simulate_budget("ssq", periods=10, tickets_per_period=1, trials=300)
    assert first["p_loss"] == second["p_loss"]
    assert first["net_percentiles"] == second["net_percentiles"]
    assert first["spend"] == pytest.approx(20.0)


def test_lab_module_has_no_network_or_heavy_dependencies():
    source = Path(lab.__file__).read_text(encoding="utf-8")
    for forbidden in ("requests", "httpx", "numpy", "scipy", "pandas", "urllib"):
        assert forbidden not in source

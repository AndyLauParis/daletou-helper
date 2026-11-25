"""AI 辅助解读测试：登录、配置、限流、提示词与上游错误映射。"""

from __future__ import annotations

import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from helper import config, llm
from helper.api import auth as auth_api
from helper.api import lab as lab_api
from helper_app import app
from security_layer import reset_security_state

PASSWORD = "Str0ngPassw0rd"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    auth_api.reset_login_rate_limit()
    reset_security_state()
    llm.clear_cache()
    with TestClient(app) as test_client:
        yield test_client
    auth_api.reset_login_rate_limit()
    reset_security_state()
    llm.clear_cache()


@pytest.fixture()
def llm_config(monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(config, "LLM_PROVIDER", "测试接口")
    monkeypatch.setattr(config, "LLM_RATE_LIMIT", 8)
    monkeypatch.setattr(config, "LLM_RATE_WINDOW_SECONDS", 600)


def register(client, username="alice") -> str:
    resp = client.post(
        "/api/helper/auth/register",
        json={"username": username, "password": PASSWORD, "is_adult": True},
    )
    assert resp.status_code == 201
    return resp.json()["token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def fake_analysis(budget_supported: bool = True) -> dict:
    return {
        "game": {
            "code": "dlt",
            "name": "超级大乐透",
            "format_summary": "前区 35 选 5 + 后区 12 选 2",
            "category_label": "乐透型",
            "budget_supported": budget_supported,
        },
        "window_requested": 100,
        "window_used": 100,
        "available_draws": 200,
        "date_range": {"from": "2025-01-01", "to": "2025-06-01"},
        "latest_issue": "25060",
        "frequency": [
            {
                "key": "front",
                "label": "前区",
                "pool": 35,
                "pick": 5,
                "numbers": [
                    {
                        "number": number,
                        "count": 20 - (number % 7),
                        "rate": (20 - (number % 7)) / 100,
                        "expected_rate": 5 / 35,
                        "current_omission": number % 9,
                        "max_omission": number % 12,
                    }
                    for number in range(1, 8)
                ],
            }
        ],
        "shape": {
            "sum": {
                "mean": 90.2,
                "theoretical_mean": 90.0,
                "stdev": 18.4,
                "min": 45,
                "max": 141,
            },
            "odd": {"mean": 2.5, "theoretical_mean": 2.5},
            "repeat": {"mean": 0.71, "theoretical_mean": 0.71},
            "zones": [
                {"label": "01-12", "avg": 1.7, "expected": 1.67},
                {"label": "13-24", "avg": 1.6, "expected": 1.67},
                {"label": "25-35", "avg": 1.7, "expected": 1.67},
            ],
            "consecutive": {"mean": 0.61},
        },
        "randomness": {
            "trials": 200,
            "tests": [
                {
                    "key": "chi_square",
                    "label": "号码频率卡方",
                    "observed": 33.2,
                    "null_mean": 34.0,
                    "null_p05": 24.1,
                    "null_p95": 46.2,
                    "p_value": 0.831,
                    "verdict": "未发现显著偏离均匀分布",
                },
                {
                    "key": "runs_z",
                    "label": "和值游程检验",
                    "observed": 0.12,
                    "null_mean": 0.0,
                    "null_p05": -1.64,
                    "null_p95": 1.64,
                    "p_value": 0.761,
                    "verdict": "和值游程与随机模拟接近",
                },
            ],
        },
        "backtest": {
            "test_size": 30,
            "lookback": 30,
            "expected_hits": 1.0476,
            "strategies": [
                {
                    "key": "hot",
                    "label": "追热号",
                    "avg_hits": 1.03,
                    "diff_from_expected": -0.0176,
                    "max_hits": 3,
                },
                {
                    "key": "random",
                    "label": "随机选号",
                    "avg_hits": 1.05,
                    "diff_from_expected": 0.0024,
                    "max_hits": 3,
                },
            ],
        },
        "note": "仅描述历史样本。",
    }


def fake_budget() -> dict:
    return {
        "periods": 100,
        "tickets_per_period": 1,
        "spend": 200.0,
        "trials": 2000,
        "avg_return": 55.0,
        "avg_net": -145.0,
        "p_loss": 0.975,
        "p_even": 0.01,
        "p_profit": 0.015,
        "net_percentiles": {
            "p05": -200.0,
            "p25": -180.0,
            "p50": -150.0,
            "p75": -120.0,
            "p95": -20.0,
        },
        "distribution": [
            {"label": "无返奖", "share": 0.4},
            {"label": "< 10%", "share": 0.2},
        ],
    }


def test_status_disabled_by_default(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "LLM_MODEL", "")
    resp = client.get("/api/helper/lab/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["model"] == ""
    assert "test-key" not in resp.text


def test_status_hides_api_key(client, llm_config):
    resp = client.get("/api/helper/lab/llm/status")
    data = resp.json()
    assert data["enabled"] is True
    assert data["model"] == "test-model"
    assert "test-key" not in resp.text


def test_interpret_requires_login(client, llm_config):
    resp = client.post(
        "/api/helper/lab/interpret", json={"game": "dlt", "window": 30}
    )
    assert resp.status_code == 401


def test_interpret_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "LLM_MODEL", "")
    token = register(client)
    resp = client.post(
        "/api/helper/lab/interpret",
        headers=auth_header(token),
        json={"game": "dlt", "window": 30},
    )
    assert resp.status_code == 503
    assert "尚未配置" in resp.json()["detail"]


def test_interpret_passes_budget_and_returns_text(
    client, llm_config, monkeypatch
):
    token = register(client)
    captured = {}

    monkeypatch.setattr(lab_api.lab, "analyze", lambda code, window: fake_analysis())
    monkeypatch.setattr(
        lab_api.lab,
        "simulate_budget",
        lambda code, periods, tickets_per_period: fake_budget(),
    )

    def fake_request(analysis, budget=None):
        captured["budget"] = budget
        return {
            "text": "这是模型解读。\n以上仅是对历史样本的统计解释。",
            "model": "test-model",
            "provider": "测试接口",
            "generated_at": "2026-11-25T12:00:00+08:00",
            "cached": False,
        }

    monkeypatch.setattr(lab_api.llm, "request_interpretation", fake_request)
    resp = client.post(
        "/api/helper/lab/interpret",
        headers=auth_header(token),
        json={"game": "dlt", "window": 100, "periods": 100, "tickets": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"].startswith("这是模型解读")
    assert data["model"] == "test-model"
    assert data["provider"] == "测试接口"
    assert data["game"]["code"] == "dlt"
    assert data["window_used"] == 100
    assert "不预测" in data["notice"]
    assert captured["budget"] is not None


def test_interpret_skips_budget_for_unsupported_game(
    client, llm_config, monkeypatch
):
    token = register(client)
    captured = {}

    monkeypatch.setattr(
        lab_api.lab,
        "analyze",
        lambda code, window: fake_analysis(budget_supported=False),
    )

    def fake_request(analysis, budget=None):
        captured["budget"] = budget
        return {
            "text": "解读",
            "model": "test-model",
            "provider": "测试接口",
            "generated_at": "2026-11-25T12:00:00+08:00",
            "cached": False,
        }

    monkeypatch.setattr(lab_api.llm, "request_interpretation", fake_request)
    resp = client.post(
        "/api/helper/lab/interpret",
        headers=auth_header(token),
        json={"game": "dlt", "window": 30, "include_budget": True},
    )
    assert resp.status_code == 200
    assert captured["budget"] is None


def test_interpret_rate_limited_per_user(client, llm_config, monkeypatch):
    token = register(client)
    monkeypatch.setattr(config, "LLM_RATE_LIMIT", 1)
    monkeypatch.setattr(lab_api.lab, "analyze", lambda code, window: fake_analysis())
    monkeypatch.setattr(
        lab_api.lab,
        "simulate_budget",
        lambda code, periods, tickets_per_period: fake_budget(),
    )
    monkeypatch.setattr(
        lab_api.llm,
        "request_interpretation",
        lambda analysis, budget=None: {
            "text": "解读",
            "model": "test-model",
            "provider": "测试接口",
            "generated_at": "2026-11-25T12:00:00+08:00",
            "cached": False,
        },
    )

    payload = {"game": "dlt", "window": 30}
    first = client.post(
        "/api/helper/lab/interpret", headers=auth_header(token), json=payload
    )
    second = client.post(
        "/api/helper/lab/interpret", headers=auth_header(token), json=payload
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1


def test_prompt_contains_guardrails_and_statistics():
    messages = llm.build_messages(fake_analysis(), fake_budget())
    system = messages[0]["content"]
    user = messages[1]["content"]
    assert messages[0]["role"] == "system"
    assert "不得预测" in system
    assert "不推荐" in system or "推荐任何未来开奖号码" in system
    assert "23%" in system
    assert "不构成投注建议" in system
    assert "超级大乐透" in user
    assert "号码频率卡方" in user
    assert "和值游程检验" in user
    assert "随机选号" in user
    assert "预算模拟" in user
    assert "亏损概率" in user
    assert len(user) < 6000


def test_http_error_mapping(monkeypatch, llm_config):
    llm.clear_cache()

    def raise_401(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://llm.example.com/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            None,
        )

    monkeypatch.setattr(llm.urllib.request, "urlopen", raise_401)
    with pytest.raises(llm.LLMError) as excinfo:
        llm.request_interpretation(fake_analysis(), fake_budget())
    assert "鉴权" in str(excinfo.value)


def test_response_is_cached(monkeypatch, llm_config):
    llm.clear_cache()
    calls = {"count": 0}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "test-model",
                    "choices": [
                        {"message": {"content": "**缓存测试解读**"}}
                    ],
                    "usage": {"completion_tokens": 42},
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        calls["count"] += 1
        return FakeResponse()

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    first = llm.request_interpretation(fake_analysis(), fake_budget())
    second = llm.request_interpretation(fake_analysis(), fake_budget())
    assert first["text"] == "缓存测试解读"
    assert first["cached"] is False
    assert second["cached"] is True
    assert calls["count"] == 1


def test_unknown_game_returns_404(client, llm_config):
    token = register(client)
    resp = client.post(
        "/api/helper/lab/interpret",
        headers=auth_header(token),
        json={"game": "nope", "window": 30},
    )
    assert resp.status_code == 404


def test_window_validation(client, llm_config):
    token = register(client)
    resp = client.post(
        "/api/helper/lab/interpret",
        headers=auth_header(token),
        json={"game": "dlt", "window": 3},
    )
    assert resp.status_code == 422


def test_lab_page_has_ai_section_without_inline_script(client):
    html = (config.STATIC_DIR / "lab.html").read_text(encoding="utf-8")
    assert "AI 辅助解读" in html
    assert 'id="ai-run"' in html
    assert "onclick=" not in html
    assert "<script>" not in html

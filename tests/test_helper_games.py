"""游戏注册表、独立缓存与目录/开奖/核对 API 测试。"""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from helper import config
from helper.api import games as games_api
from helper.games import cache, registry
from helper_app import ROUTER_MODULES, app

EXPECTED_ORDER = [
    "dlt",
    "pl3",
    "pl5",
    "qxc",
    "ssq",
    "fc3d",
    "qlc",
    "kl8",
    "sfc14",
    "rx9",
    "jq4",
    "bqc6",
    "jczq",
    "jclq",
    "dgg",
    "ggl",
]
EXPECTED_CATEGORIES = ["ticai_number", "fucai_number", "zucai", "jingcai", "jikai"]
EXPECTED_CATEGORY_LABELS = ["体彩数字型", "福彩数字型", "足彩", "竞彩", "即开型"]
CATALOG_CODES = {"jczq", "jclq", "dgg", "ggl"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "helper.db"))
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    games_api.reset_refresh_state()
    with TestClient(app) as test_client:
        yield test_client
    games_api.reset_refresh_state()


def make_draw(issue: str, date: str, marker: str | None = None) -> dict:
    return {
        "issue": issue,
        "date": date,
        "numbers": {"front": [1, 2, 3, 4, 5], "back": [1, 2]},
        "extra": {"marker": marker} if marker else {},
    }


class BrokenAdapter:
    """抓取必然失败的适配器。"""

    SOURCE_NAME = "测试源"

    @staticmethod
    def fetch_draws(limit: int = 30) -> list[dict]:
        raise RuntimeError("模拟数据源不可用")

    @staticmethod
    def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
        return {"ok": True, "normalized": payload, "errors": []}

    @staticmethod
    def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
        return {"ok": True, "hit": False, "prize_level": None, "detail": {}, "message": ""}


class FakeAdapter:
    """返回固定开奖数据的适配器，用于验证成功路径。"""

    SOURCE_NAME = "测试数据源"

    @staticmethod
    def fetch_draws(limit: int = 30) -> list[dict]:
        assert limit == 30
        return [make_draw("26135", "2026-11-24", "fetch")]

    @staticmethod
    def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
        return {"ok": True, "normalized": payload, "errors": []}

    @staticmethod
    def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
        return {
            "ok": True,
            "hit": True,
            "prize_level": "测试奖级",
            "detail": {
                "issue": draw["issue"],
                "payload": payload,
                "play_type": play_type,
            },
            "message": "仅用于测试",
        }


# ---------- 注册表 ----------


def test_registry_has_sixteen_games_in_fixed_order():
    assert len(registry.GAMES) == 16
    assert list(registry.GAMES) == EXPECTED_ORDER
    assert set(registry.GAMES) == set(EXPECTED_ORDER)


def test_registry_groups_and_labels_in_fixed_order():
    groups = registry.catalog_groups()
    assert [group["category"] for group in groups] == EXPECTED_CATEGORIES
    assert [group["category_label"] for group in groups] == EXPECTED_CATEGORY_LABELS
    assert [len(group["games"]) for group in groups] == [4, 4, 4, 2, 2]

    for group in groups:
        for meta in group["games"]:
            assert meta.category == group["category"]
            assert meta.category_label == group["category_label"]


def test_registry_catalog_games():
    catalog = {
        code
        for code, meta in registry.GAMES.items()
        if meta.support_level == "catalog"
    }
    assert catalog == CATALOG_CODES
    for code in CATALOG_CODES:
        assert registry.GAMES[code].adapter_module is None
    for code, meta in registry.GAMES.items():
        if code not in CATALOG_CODES:
            assert meta.support_level == "full"
            assert meta.adapter_module == f"helper.games.{code}"


def test_registry_unknown_game():
    assert registry.get_game("nope") is None
    assert registry.get_adapter("nope") is None


# ---------- 目录 API ----------


def test_games_directory_api(client):
    resp = client.get("/api/helper/games")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 16
    assert [group["category"] for group in data["groups"]] == EXPECTED_CATEGORIES

    codes = [
        game["code"]
        for group in data["groups"]
        for game in group["games"]
    ]
    assert codes == EXPECTED_ORDER

    for group in data["groups"]:
        for game in group["games"]:
            status = game["data_status"]
            assert isinstance(status["has_data"], bool)
            assert "latest_issue" in status
            assert "latest_date" in status
            assert "updated_at" in status
            assert status["status"] in {"ok", "stale", "empty", "unavailable"}


def test_game_detail_and_unknown(client):
    resp = client.get("/api/helper/games/dlt")
    assert resp.status_code == 200
    game = resp.json()["game"]
    assert game["code"] == "dlt"
    assert game["name"] == "大乐透"
    assert game["support_level"] == "full"
    assert "data_status" in game

    missing = client.get("/api/helper/games/nope")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "未找到该彩票游戏"


# ---------- 开奖接口降级 ----------


def test_catalog_game_draws_returns_catalog_only(client):
    for code in CATALOG_CODES:
        resp = client.get(f"/api/helper/games/{code}/draws")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "catalog_only"
        assert body["draws"] == []
        assert body["notice"] == "该游戏暂只提供目录与支出记录"


def test_full_game_without_adapter_returns_unavailable(client, monkeypatch):
    monkeypatch.setattr(registry, "get_adapter", lambda code: None)
    resp = client.get("/api/helper/games/dlt/draws")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["draws"] == []
    assert body["notice"] == "开奖数据接入中"

    refreshed = client.post("/api/helper/games/dlt/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["ok"] is False
    assert refreshed.json()["status"] == "unavailable"


def test_check_rejects_catalog_and_unknown(client):
    catalog = client.post(
        "/api/helper/check",
        json={"game_code": "jczq", "play_type": None, "payload": {}},
    )
    assert catalog.status_code == 400
    assert catalog.json()["detail"] == "该游戏暂不支持号码核对"

    unknown = client.post(
        "/api/helper/check",
        json={"game_code": "nope", "play_type": None, "payload": {}},
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "未找到该彩票游戏"


def test_check_without_adapter_rejected(client, monkeypatch):
    monkeypatch.setattr(registry, "get_adapter", lambda code: None)
    resp = client.post(
        "/api/helper/check",
        json={"game_code": "dlt", "play_type": None, "payload": {}},
    )
    assert resp.status_code == 400


# ---------- 缓存 ----------


def test_merge_draws_dedupes_and_sorts():
    old = [
        make_draw("26001", "2026-01-01", "old"),
        make_draw("26002", "2026-01-02", "old"),
    ]
    new = [
        make_draw("26002", "2026-01-02", "new"),
        make_draw("26003", "2026-01-03", "new"),
    ]
    merged = cache.merge_draws(old, new)
    assert [draw["issue"] for draw in merged] == ["26003", "26002", "26001"]
    assert merged[1]["extra"]["marker"] == "new"
    assert merged[2]["extra"]["marker"] == "old"


def test_save_cache_atomic_and_limits_draws(client):
    draws = [
        make_draw(f"26{index:03d}", "2026-01-01")
        for index in range(1, 251)
    ]
    saved = cache.save_cache("dlt", draws, "测试源")
    assert saved is not None

    path = cache.cache_path("dlt")
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["code"] == "dlt"
    assert data["source"] == "测试源"
    assert data["status"] == "ok"
    assert data["updated_at"]
    assert len(data["draws"]) == cache.MAX_DRAWS

    status = cache.status_for("dlt")
    assert status["has_data"] is True
    assert status["draw_count"] == cache.MAX_DRAWS
    assert status["latest_issue"]
    assert status["status"] == "ok"


def test_corrupted_cache_is_tolerated(client):
    path = cache.cache_path("dlt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken json", encoding="utf-8")

    payload = cache.load_cache("dlt")
    assert payload["draws"] == []
    assert payload["status"] == "empty"
    assert payload["last_error"]


def test_refresh_failure_keeps_old_cache(client, monkeypatch):
    saved = cache.save_cache(
        "dlt",
        [
            make_draw("26001", "2026-01-01", "old"),
            make_draw("26002", "2026-01-02", "old"),
        ],
        "旧缓存",
    )
    assert saved is not None
    before = cache.load_cache("dlt")

    monkeypatch.setattr(registry, "get_adapter", lambda code: BrokenAdapter)

    resp = client.post("/api/helper/games/dlt/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["status"] == "stale"
    assert body["latest_issue"] == "26002"

    after = cache.load_cache("dlt")
    assert after["source"] == "旧缓存"
    assert after["updated_at"] == before["updated_at"]
    assert [draw["issue"] for draw in after["draws"]] == ["26002", "26001"]

    # 手动刷新有 30 秒节流；这里清理节流状态以验证 draws?refresh=true 的降级路径
    games_api.reset_refresh_state()
    fallback = client.get("/api/helper/games/dlt/draws", params={"refresh": "true"})
    assert fallback.status_code == 200
    fallback_body = fallback.json()
    assert fallback_body["status"] == "stale"
    assert fallback_body["notice"] == "数据源暂不可用，已显示上次缓存"
    assert [draw["issue"] for draw in fallback_body["draws"]] == ["26002", "26001"]


def test_check_without_cache_and_fetch_failure_returns_409(client, monkeypatch):
    monkeypatch.setattr(registry, "get_adapter", lambda code: BrokenAdapter)
    resp = client.post(
        "/api/helper/check",
        json={"game_code": "dlt", "play_type": None, "payload": {}},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "暂无开奖数据，请稍后重试"


def test_manual_refresh_is_throttled(client, monkeypatch):
    """连续手动刷新只抓取一次，后续请求返回 busy 而不是继续冲击上游。"""
    games_api.reset_refresh_state()
    calls: list[int] = []

    class CountingAdapter(FakeAdapter):
        @staticmethod
        def fetch_draws(limit: int = 30) -> list[dict]:
            calls.append(limit)
            return [make_draw(f"2613{len(calls)}", "2026-11-24")]

    monkeypatch.setattr(registry, "get_adapter", lambda code: CountingAdapter)

    first = client.post("/api/helper/games/dlt/refresh")
    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert len(calls) == 1

    second = client.post("/api/helper/games/dlt/refresh")
    assert second.status_code == 200
    body = second.json()
    assert body["ok"] is False
    assert body["status"] == "busy"
    assert "刷新过于频繁" in body["message"]
    assert body["latest_issue"] == first.json()["latest_issue"]
    assert len(calls) == 1


def test_all_router_modules_exist():
    for module_name in ROUTER_MODULES:
        assert importlib.import_module(module_name) is not None


def test_draws_reads_cache_only_once(client, monkeypatch):
    cache.save_cache("dlt", [make_draw("26100", "2026-11-20")], "测试源")
    calls: list[str] = []
    original = cache.load_cache

    def counting(code: str):
        calls.append(code)
        return original(code)

    monkeypatch.setattr(cache, "load_cache", counting)
    resp = client.get("/api/helper/games/dlt/draws")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert calls == ["dlt"]


# ---------- 适配器成功路径 ----------


def test_fake_adapter_draws_refresh_and_check(client, monkeypatch):
    monkeypatch.setattr(
        registry,
        "get_adapter",
        lambda code: FakeAdapter if code == "dlt" else None,
    )

    resp = client.get("/api/helper/games/dlt/draws")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["source"] == "测试数据源"
    assert body["notice"] is None
    assert [draw["issue"] for draw in body["draws"]] == ["26135"]

    cached = cache.load_cache("dlt")
    assert cached["status"] == "ok"
    assert cached["source"] == "测试数据源"
    assert cached["draws"][0]["issue"] == "26135"

    # 缓存新鲜时再次请求仍返回同一期
    again = client.get("/api/helper/games/dlt/draws")
    assert again.status_code == 200
    assert [draw["issue"] for draw in again.json()["draws"]] == ["26135"]

    refreshed = client.post("/api/helper/games/dlt/refresh")
    assert refreshed.status_code == 200
    refresh_body = refreshed.json()
    assert refresh_body["ok"] is True
    assert refresh_body["status"] == "ok"
    assert refresh_body["latest_issue"] == "26135"

    checked = client.post(
        "/api/helper/check",
        json={
            "game_code": "dlt",
            "play_type": None,
            "payload": {"front": [1, 2, 3, 4, 5], "back": [1, 2]},
        },
    )
    assert checked.status_code == 200
    checked_body = checked.json()
    assert checked_body["game_code"] == "dlt"
    assert checked_body["draw"] == {"issue": "26135", "date": "2026-11-24"}
    assert checked_body["result"]["hit"] is True
    assert checked_body["result"]["prize_level"] == "测试奖级"

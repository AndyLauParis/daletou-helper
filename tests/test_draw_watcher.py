"""开奖自动更新模块的调度逻辑测试。"""

import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from helper import draw_watcher
from helper.games import cache, registry

TZ = ZoneInfo("Asia/Shanghai")


def _meta(**overrides):
    values = {
        "code": "dlt",
        "name": "超级大乐透",
        "support_level": "full",
        "schedule_weekdays": (0, 2, 5),  # 周一、周三、周六
        "draw_time": "21:25",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _payload(date: str | None, updated_at: str | None = None) -> dict:
    draws = [{"issue": "26137", "date": date}] if date else []
    return {"draws": draws, "updated_at": updated_at}


def test_last_draw_at_returns_most_recent_scheduled_time():
    meta = _meta()
    now = datetime(2026, 11, 25, 21, 30, tzinfo=TZ)  # 周三
    assert draw_watcher.last_draw_at(meta, now) == datetime(
        2026, 11, 25, 21, 25, tzinfo=TZ
    )

    before = datetime(2026, 11, 25, 21, 0, tzinfo=TZ)
    assert draw_watcher.last_draw_at(meta, before) == datetime(
        2026, 11, 23, 21, 25, tzinfo=TZ
    )
    assert draw_watcher.last_draw_at(_meta(schedule_weekdays=None), now) is None


def test_watch_once_skips_when_latest_draw_present(monkeypatch):
    meta = _meta()
    monkeypatch.setattr(registry, "list_games", lambda: [meta])
    monkeypatch.setattr(registry, "get_adapter", lambda code: object())
    monkeypatch.setattr(cache, "load_cache", lambda code: _payload("2026-11-25"))
    monkeypatch.setattr(draw_watcher, "_last_attempt", {})

    calls = []
    refreshed = draw_watcher.watch_once(
        now=datetime(2026, 11, 25, 21, 30, tzinfo=TZ),
        fetch=lambda meta, adapter: calls.append(meta.code),
    )
    assert refreshed == []
    assert calls == []


def test_watch_once_fetches_missing_latest_draw(monkeypatch):
    meta = _meta()
    monkeypatch.setattr(registry, "list_games", lambda: [meta])
    monkeypatch.setattr(registry, "get_adapter", lambda code: object())
    monkeypatch.setattr(cache, "load_cache", lambda code: _payload("2026-11-23"))
    monkeypatch.setattr(draw_watcher, "_last_attempt", {})

    calls = []
    refreshed = draw_watcher.watch_once(
        now=datetime(2026, 11, 25, 21, 30, tzinfo=TZ),
        fetch=lambda meta, adapter: calls.append(meta.code),
    )
    assert refreshed == ["dlt"]
    assert calls == ["dlt"]


def test_watch_once_skips_outside_window_and_catalog_games(monkeypatch):
    fixed = _meta()
    catalog = _meta(code="dgg", support_level="catalog_only")
    monkeypatch.setattr(registry, "list_games", lambda: [fixed, catalog])
    monkeypatch.setattr(registry, "get_adapter", lambda code: object())
    monkeypatch.setattr(cache, "load_cache", lambda code: _payload(None))
    monkeypatch.setattr(draw_watcher, "_last_attempt", {})

    calls = []
    refreshed = draw_watcher.watch_once(
        now=datetime(2026, 11, 26, 0, 0, tzinfo=TZ),  # 距 21:25 已超过 2 小时
        fetch=lambda meta, adapter: calls.append(meta.code),
    )
    assert refreshed == []
    assert calls == []


def test_watch_once_respects_retry_interval(monkeypatch):
    meta = _meta()
    monkeypatch.setattr(registry, "list_games", lambda: [meta])
    monkeypatch.setattr(registry, "get_adapter", lambda code: object())
    monkeypatch.setattr(cache, "load_cache", lambda code: _payload(None))
    monkeypatch.setattr(
        draw_watcher, "_last_attempt", {"dlt": time.monotonic()}
    )

    calls = []
    refreshed = draw_watcher.watch_once(
        now=datetime(2026, 11, 25, 21, 30, tzinfo=TZ),
        fetch=lambda meta, adapter: calls.append(meta.code),
    )
    assert refreshed == []
    assert calls == []

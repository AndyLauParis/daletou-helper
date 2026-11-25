"""开奖数据后台轮询：在开奖后的一段时间内自动抓取最新一期。

只处理有固定开奖时间的彩种；足彩、竞彩、即开型仍由用户手动刷新。
抓取复用开奖 API 的互斥与并发限制，不会绕过节流直接冲击上游。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from .games import cache, registry

logger = logging.getLogger("helper.draw_watcher")

TZ = ZoneInfo("Asia/Shanghai")

# 后台检查间隔（秒）
WATCH_INTERVAL_SECONDS = 60
# 开奖后持续尝试的窗口（分钟）
WATCH_WINDOW_MINUTES = 120
# 同一彩种两次抓取的最小间隔（秒）
RETRY_SECONDS = 180
# 缓存刚更新过时不重复抓取（秒）
MIN_CACHE_AGE_SECONDS = 60

_last_attempt: dict[str, float] = {}
_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _enabled() -> bool:
    if os.environ.get("HELPER_DRAW_WATCH", "1") == "0":
        return False
    # 测试环境不启动常驻线程，避免每个 TestClient 实例都留下后台任务
    return "pytest" not in sys.modules


def last_draw_at(meta, now: datetime) -> datetime | None:
    """最近一次已经到点的开奖时间；没有固定开奖时间时返回 None。"""
    if not meta.schedule_weekdays or not meta.draw_time:
        return None
    try:
        hour_text, minute_text = meta.draw_time.split(":")
        draw_time = dtime(int(hour_text), int(minute_text))
    except (TypeError, ValueError):
        return None

    days = {int(day) for day in meta.schedule_weekdays}
    for offset in range(0, 8):
        day = (now - timedelta(days=offset)).date()
        candidate = datetime.combine(day, draw_time, tzinfo=TZ)
        if day.weekday() in days and candidate <= now:
            return candidate
    return None


def _parse_updated_at(value) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=TZ)
    return stamp


def _has_draw_on_or_after(payload: dict, day) -> bool:
    target = day.isoformat()
    for draw in payload.get("draws") or []:
        date_text = str(draw.get("date") or "")
        if date_text and date_text >= target:
            return True
    return False


def _should_try(meta, now: datetime, payload: dict, last_attempt: float) -> bool:
    draw_at = last_draw_at(meta, now)
    if draw_at is None:
        return False
    if now - draw_at > timedelta(minutes=WATCH_WINDOW_MINUTES):
        return False
    if _has_draw_on_or_after(payload, draw_at.date()):
        return False
    if time.monotonic() - last_attempt < RETRY_SECONDS:
        return False
    updated = _parse_updated_at(payload.get("updated_at"))
    if updated is not None:
        age = (now - updated).total_seconds()
        if 0 <= age < MIN_CACHE_AGE_SECONDS:
            return False
    return True


def watch_once(now: datetime | None = None, fetch=None) -> list[str]:
    """检查一轮需要更新的彩种，返回本次成功抓取的游戏代码。"""
    current = now or datetime.now(TZ)
    if fetch is None:
        from .api.games import _fetch_with_guard

        def default_fetch(meta, adapter):
            return _fetch_with_guard(meta, adapter, explicit=False)

        fetch = default_fetch

    refreshed: list[str] = []
    for meta in registry.list_games():
        if meta.support_level != "full":
            continue
        adapter = registry.get_adapter(meta.code)
        if adapter is None:
            continue
        payload = cache.load_cache(meta.code)
        if not _should_try(
            meta, current, payload, _last_attempt.get(meta.code, 0.0)
        ):
            continue

        _last_attempt[meta.code] = time.monotonic()
        try:
            fetch(meta, adapter)
        except Exception:
            logger.debug("%s 自动更新失败，将在下个周期重试", meta.code, exc_info=True)
            continue

        refreshed.append(meta.code)
        logger.info("%s 已自动更新开奖数据", meta.code)
    return refreshed


def _run() -> None:
    while not _stop_event.is_set():
        try:
            watch_once()
        except Exception:
            logger.exception("开奖自动更新轮询异常")
        _stop_event.wait(WATCH_INTERVAL_SECONDS)


def start_draw_watcher() -> threading.Thread | None:
    """启动后台线程；关闭或测试环境返回 None。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    if not _enabled():
        return None
    _stop_event.clear()
    _thread = threading.Thread(target=_run, name="draw-watcher", daemon=True)
    _thread.start()
    logger.info(
        "开奖自动更新已启动：每 %s 秒检查一次，开奖后 %s 分钟内持续重试",
        WATCH_INTERVAL_SECONDS,
        WATCH_WINDOW_MINUTES,
    )
    return _thread


def stop_draw_watcher() -> None:
    _stop_event.set()
    thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)

"""多游戏提醒 API：按注册表开奖节奏计算下期时间，并提供站内提醒窗口。

提醒只在站内展示，不接短信、推送或其他外部通知。
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_db
from ..deps import get_current_user
from ..games import registry
from ..security import utc_now_iso

router = APIRouter(prefix="/api/helper/reminders", tags=["helper-reminders"])

TZ = ZoneInfo("Asia/Shanghai")

WEEK_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

DEFAULT_LEAD_MINUTES = 60
MIN_LEAD_MINUTES = 5
MAX_LEAD_MINUTES = 180

NO_FIXED_SCHEDULE_NOTE = "按赛程，无固定开奖时间"
UPCOMING_WINDOW_HOURS = 24


class ReminderUpdate(BaseModel):
    enabled: bool
    lead_minutes: int


def _now() -> datetime:
    """当前时间（Asia/Shanghai）；测试可通过 monkeypatch 覆盖。"""
    return datetime.now(TZ)


def _has_fixed_schedule(meta) -> bool:
    return bool(meta.schedule_weekdays) and bool(meta.draw_time)


def _next_draw(meta, now: datetime | None = None) -> datetime | None:
    """按 schedule_weekdays（0=周一）与 draw_time 计算下一次开奖时间。"""
    if not _has_fixed_schedule(meta):
        return None
    try:
        hour_text, minute_text = meta.draw_time.split(":")
        draw_at = time(int(hour_text), int(minute_text))
    except (ValueError, TypeError):
        return None

    days = {int(day) for day in meta.schedule_weekdays}
    current = now if now is not None else _now()
    for offset in range(0, 8):
        day = (current + timedelta(days=offset)).date()
        candidate = datetime.combine(day, draw_at, tzinfo=TZ)
        if day.weekday() in days and candidate > current:
            return candidate
    return None


def _schedule_text(meta) -> str:
    if not _has_fixed_schedule(meta):
        return NO_FIXED_SCHEDULE_NOTE
    names = "、".join(WEEK_LABELS[int(day)] for day in meta.schedule_weekdays)
    return f"{names} {meta.draw_time}"


def _draw_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return f"{value.month}月{value.day}日 {value.strftime('%H:%M')}"


def _settings_map(db, user_id: int) -> dict[str, dict]:
    rows = db.execute(
        "SELECT * FROM reminder_settings WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {row["game_code"]: row for row in rows}


def _reminder_item(meta, setting, now: datetime) -> dict:
    enabled = bool(setting["enabled"]) if setting is not None else False
    lead_minutes = (
        int(setting["lead_minutes"]) if setting is not None else DEFAULT_LEAD_MINUTES
    )
    next_draw = _next_draw(meta, now)
    return {
        "game_code": meta.code,
        "game_name": meta.name,
        "category_label": meta.category_label,
        "enabled": enabled,
        "lead_minutes": lead_minutes,
        "schedule_text": _schedule_text(meta),
        "next_draw_at": next_draw.isoformat() if next_draw is not None else None,
        "next_draw_text": _draw_text(next_draw),
        "note": None if _has_fixed_schedule(meta) else NO_FIXED_SCHEDULE_NOTE,
    }


@router.get("")
def list_reminders(current=Depends(get_current_user), db=Depends(get_db)):
    now = _now()
    settings = _settings_map(db, current["id"])
    return [
        _reminder_item(meta, settings.get(meta.code), now)
        for meta in registry.list_games()
    ]


@router.get("/upcoming")
def upcoming_reminders(current=Depends(get_current_user), db=Depends(get_db)):
    now = _now()
    settings = _settings_map(db, current["id"])
    items = []
    for meta in registry.list_games():
        setting = settings.get(meta.code)
        if setting is None or not bool(setting["enabled"]):
            continue
        next_draw = _next_draw(meta, now)
        if next_draw is None:
            continue
        seconds_left = (next_draw - now).total_seconds()
        if seconds_left < 0 or seconds_left > UPCOMING_WINDOW_HOURS * 3600:
            continue
        minutes_left = int(math.ceil(seconds_left / 60))
        if minutes_left > int(setting["lead_minutes"]):
            continue
        items.append(
            {
                "game_code": meta.code,
                "game_name": meta.name,
                "next_draw_at": next_draw.isoformat(),
                "minutes_left": minutes_left,
                "message": (
                    f"{meta.name} 将于 {_draw_text(next_draw)} 开奖，"
                    f"还有约 {minutes_left} 分钟"
                ),
            }
        )
    items.sort(key=lambda item: item["next_draw_at"])
    return items


@router.put("/{game_code}")
def update_reminder(
    game_code: str,
    body: ReminderUpdate,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    meta = registry.get_game(game_code)
    if meta is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")
    if not MIN_LEAD_MINUTES <= body.lead_minutes <= MAX_LEAD_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"提醒提前时间需为 {MIN_LEAD_MINUTES}–{MAX_LEAD_MINUTES} 分钟",
        )

    db.execute(
        """
        INSERT INTO reminder_settings
            (user_id, game_code, enabled, lead_minutes, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, game_code) DO UPDATE SET
            enabled = excluded.enabled,
            lead_minutes = excluded.lead_minutes,
            updated_at = excluded.updated_at
        """,
        (
            current["id"],
            meta.code,
            1 if body.enabled else 0,
            body.lead_minutes,
            utc_now_iso(),
        ),
    )
    db.commit()
    setting = db.execute(
        "SELECT * FROM reminder_settings WHERE user_id = ? AND game_code = ?",
        (current["id"], meta.code),
    ).fetchone()
    return _reminder_item(meta, setting, _now())

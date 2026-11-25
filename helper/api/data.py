"""数据可携带 API：导出当前用户的全部记录（不包含密码与令牌）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from ..db import get_db
from ..deps import get_current_user
from ..security import utc_now_iso

router = APIRouter(prefix="/api/helper/data", tags=["helper-data"])


def _payload(raw) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {"value": value}


@router.get("/export")
def export_data(current=Depends(get_current_user), db=Depends(get_db)):
    """导出当前用户的账号、号码本、预算、支出与提醒设置。

    只返回业务数据；密码哈希、盐与会话令牌哈希不会被导出。
    """
    user_id = current["id"]

    user_row = db.execute(
        "SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    number_rows = db.execute(
        "SELECT * FROM number_sets WHERE user_id = ? ORDER BY id ASC", (user_id,)
    ).fetchall()
    expense_rows = db.execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY id ASC", (user_id,)
    ).fetchall()
    reminder_rows = db.execute(
        "SELECT * FROM reminder_settings WHERE user_id = ? ORDER BY game_code ASC",
        (user_id,),
    ).fetchall()
    budget_row = db.execute(
        "SELECT monthly_budget, updated_at FROM budget_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    return {
        "user": (
            {
                "id": user_row["id"],
                "username": user_row["username"],
                "created_at": user_row["created_at"],
            }
            if user_row is not None
            else {"id": current["id"], "username": current["username"], "created_at": None}
        ),
        "number_sets": [
            {
                "id": row["id"],
                "game_code": row["game_code"],
                "name": row["name"],
                "play_type": row["play_type"],
                "payload": _payload(row["payload_json"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in number_rows
        ],
        "budget": (
            {
                "monthly_budget": round(float(budget_row["monthly_budget"]), 2),
                "updated_at": budget_row["updated_at"],
            }
            if budget_row is not None
            else {"monthly_budget": 0.0, "updated_at": None}
        ),
        "expenses": [
            {
                "id": row["id"],
                "game_code": row["game_code"],
                "amount": round(float(row["amount"]), 2),
                "spent_on": row["spent_on"],
                "note": row["note"],
                "created_at": row["created_at"],
            }
            for row in expense_rows
        ],
        "reminders": [
            {
                "game_code": row["game_code"],
                "enabled": bool(row["enabled"]),
                "lead_minutes": int(row["lead_minutes"]),
                "updated_at": row["updated_at"],
            }
            for row in reminder_rows
        ],
        "exported_at": utc_now_iso(),
    }

"""预算与支出 API：月度总预算、手动支出记录与分游戏汇总。

金额只做记录与统计，不涉及充值、支付或下单。
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from ..db import get_db
from ..deps import get_current_user
from ..games import registry
from ..security import utc_now_iso

router = APIRouter(prefix="/api/helper", tags=["helper-budget"])

TZ = ZoneInfo("Asia/Shanghai")

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
MAX_MONTHLY_BUDGET = 1_000_000.0
MAX_EXPENSE_AMOUNT = 100_000.0
MAX_NOTE_LENGTH = 200


class BudgetUpdate(BaseModel):
    monthly_budget: float


class ExpenseCreate(BaseModel):
    game_code: str
    amount: float
    spent_on: str
    note: str = ""


def _now() -> datetime:
    return datetime.now(TZ)


def _today() -> date:
    return _now().date()


def _current_month() -> str:
    return _today().strftime("%Y-%m")


def _require_month(value: str | None) -> str:
    month = (value or "").strip() or _current_month()
    valid = False
    if MONTH_RE.fullmatch(month):
        try:
            datetime.strptime(month, "%Y-%m")
            valid = True
        except ValueError:
            valid = False
    if not valid:
        raise HTTPException(status_code=400, detail="月份格式需为 YYYY-MM")
    return month


def _require_game(code: str):
    meta = registry.get_game(code)
    if meta is None:
        raise HTTPException(status_code=400, detail="未找到该彩票游戏，请从游戏目录中选择")
    return meta


def _game_name(code: str) -> str:
    meta = registry.get_game(code)
    return meta.name if meta is not None else code


def _expense_row(row) -> dict:
    return {
        "id": row["id"],
        "game_code": row["game_code"],
        "game_name": _game_name(row["game_code"]),
        "amount": round(float(row["amount"]), 2),
        "spent_on": row["spent_on"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


@router.get("/budget")
def get_budget(current=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(
        "SELECT monthly_budget, updated_at FROM budget_settings WHERE user_id = ?",
        (current["id"],),
    ).fetchone()
    if row is None:
        return {"monthly_budget": 0.0, "updated_at": None}
    return {
        "monthly_budget": round(float(row["monthly_budget"]), 2),
        "updated_at": row["updated_at"],
    }


@router.put("/budget")
def set_budget(
    body: BudgetUpdate,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    value = body.monthly_budget
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
        or float(value) > MAX_MONTHLY_BUDGET
    ):
        raise HTTPException(
            status_code=400,
            detail="月度预算需为 0–1,000,000 之间的数字",
        )
    amount = round(float(value), 2)
    now = utc_now_iso()
    db.execute(
        """
        INSERT INTO budget_settings (user_id, monthly_budget, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            monthly_budget = excluded.monthly_budget,
            updated_at = excluded.updated_at
        """,
        (current["id"], amount, now),
    )
    db.commit()
    return {"monthly_budget": amount, "updated_at": now}


@router.get("/expenses")
def list_expenses(
    month: str | None = None,
    game_code: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    where = "user_id = ?"
    params: list = [current["id"]]
    if month is not None and month.strip():
        where += " AND spent_on LIKE ?"
        params.append(_require_month(month) + "-%")
    code = (game_code or "").strip().lower()
    if code:
        if registry.get_game(code) is None:
            raise HTTPException(status_code=400, detail="未找到该彩票游戏")
        where += " AND game_code = ?"
        params.append(code)

    total = db.execute(
        f"SELECT COUNT(*) AS n FROM expenses WHERE {where}", params
    ).fetchone()["n"]
    rows = db.execute(
        f"""
        SELECT * FROM expenses
        WHERE {where}
        ORDER BY spent_on DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return {
        "items": [_expense_row(row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.post("/expenses", status_code=201)
def create_expense(
    body: ExpenseCreate,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    meta = _require_game(body.game_code)

    amount = body.amount
    if (
        not math.isfinite(float(amount))
        or float(amount) <= 0
        or float(amount) > MAX_EXPENSE_AMOUNT
    ):
        raise HTTPException(
            status_code=400,
            detail="支出金额需大于 0 且不超过 100,000 元",
        )

    try:
        spent_on = date.fromisoformat((body.spent_on or "").strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="支出日期格式需为 YYYY-MM-DD"
        ) from exc
    if spent_on > _today():
        raise HTTPException(status_code=400, detail="支出日期不能晚于今天")

    note = (body.note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise HTTPException(status_code=400, detail="备注最多 200 字")

    cursor = db.execute(
        """
        INSERT INTO expenses (user_id, game_code, amount, spent_on, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            current["id"],
            meta.code,
            round(float(amount), 2),
            spent_on.isoformat(),
            note,
            utc_now_iso(),
        ),
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM expenses WHERE id = ?", (int(cursor.lastrowid),)
    ).fetchone()
    return _expense_row(row)


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: int,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    cursor = db.execute(
        "DELETE FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, current["id"]),
    )
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="未找到该记录")
    return Response(status_code=204)


@router.get("/budget/summary")
def budget_summary(
    month: str | None = None,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    month_value = _require_month(month)
    user_id = current["id"]

    budget_row = db.execute(
        "SELECT monthly_budget FROM budget_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    monthly_budget = (
        round(float(budget_row["monthly_budget"]), 2) if budget_row is not None else 0.0
    )

    rows = db.execute(
        """
        SELECT game_code, amount FROM expenses
        WHERE user_id = ? AND spent_on LIKE ?
        """,
        (user_id, month_value + "-%"),
    ).fetchall()

    grouped: dict[str, dict] = {}
    total_spent = 0.0
    for row in rows:
        code = row["game_code"]
        amount = float(row["amount"])
        total_spent += amount
        entry = grouped.setdefault(
            code,
            {"game_code": code, "game_name": _game_name(code), "amount": 0.0, "count": 0},
        )
        entry["amount"] += amount
        entry["count"] += 1

    by_game = sorted(grouped.values(), key=lambda item: item["amount"], reverse=True)
    for entry in by_game:
        entry["amount"] = round(entry["amount"], 2)

    total_spent = round(total_spent, 2)
    remaining = round(monthly_budget - total_spent, 2)
    return {
        "month": month_value,
        "monthly_budget": monthly_budget,
        "total_spent": total_spent,
        "remaining": remaining,
        "over_budget": monthly_budget > 0 and total_spent >= monthly_budget,
        "by_game": by_game,
        "entry_count": len(rows),
    }

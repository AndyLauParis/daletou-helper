"""管理员后台 API：概览统计、用户列表、反馈处理与截图查看。

所有接口依赖 require_admin：未登录 401，普通用户 403。
用户列表只返回脱敏字段，不包含密码哈希、盐或会话信息。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from security_layer import client_ip

from .. import feedback as store
from ..db import get_db
from ..deps import require_admin

logger = logging.getLogger("helper.api.admin")

router = APIRouter(prefix="/api/helper/admin", tags=["helper-admin"])

FEEDBACK_STATUSES = {"open", "resolved"}


class FeedbackStatusRequest(BaseModel):
    status: str


def _audit(event: str, request: Request, actor: dict, detail: str = "") -> None:
    safe = (detail or "").replace("\r", " ").replace("\n", " ")[:120]
    logger.info(
        "admin_event=%s actor=%s ip=%s detail=%s",
        event,
        actor.get("username", "-"),
        client_ip(request),
        safe or "-",
    )


def _feedback_payload(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "category": row["category"],
        "category_label": store.CATEGORIES.get(row["category"], row["category"]),
        "content": row["content"],
        "has_screenshot": bool(row["screenshot_name"]),
        "status": row["status"],
        "created_at": row["created_at"],
    }


@router.get("/overview")
def overview(
    admin=Depends(require_admin),
    db=Depends(get_db),
):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = today[:7]

    def scalar(sql: str, params: tuple = ()) -> int:
        row = db.execute(sql, params).fetchone()
        return int(row[0]) if row is not None else 0

    recent_rows = db.execute(
        """
        SELECT id, username, is_admin, created_at
        FROM users
        ORDER BY id DESC
        LIMIT 8
        """
    ).fetchall()

    return {
        "users": {
            "total": scalar("SELECT COUNT(*) FROM users"),
            "today": scalar(
                "SELECT COUNT(*) FROM users WHERE substr(created_at, 1, 10) = ?",
                (today,),
            ),
            "admins": scalar("SELECT COUNT(*) FROM users WHERE is_admin = 1"),
        },
        "numbers": scalar("SELECT COUNT(*) FROM number_sets"),
        "expenses": {
            "total": round(
                float(scalar("SELECT COALESCE(SUM(amount), 0) FROM expenses")), 2
            ),
            "month": round(
                float(
                    scalar(
                        "SELECT COALESCE(SUM(amount), 0) FROM expenses "
                        "WHERE substr(spent_on, 1, 7) = ?",
                        (month,),
                    )
                ),
                2,
            ),
        },
        "reminders_enabled": scalar(
            "SELECT COUNT(*) FROM reminder_settings WHERE enabled = 1"
        ),
        "feedback": {
            "total": scalar("SELECT COUNT(*) FROM feedback"),
            "open": scalar("SELECT COUNT(*) FROM feedback WHERE status = 'open'"),
        },
        "recent_users": [
            {
                "id": row["id"],
                "username": row["username"],
                "is_admin": bool(row["is_admin"]),
                "created_at": row["created_at"],
            }
            for row in recent_rows
        ],
    }


@router.get("/users")
def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin=Depends(require_admin),
    db=Depends(get_db),
):
    total = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
    rows = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.is_admin,
            u.is_adult,
            u.created_at,
            (SELECT COUNT(*) FROM number_sets n WHERE n.user_id = u.id)
                AS number_count,
            (SELECT COUNT(*) FROM feedback f WHERE f.user_id = u.id)
                AS feedback_count
        FROM users u
        ORDER BY u.id DESC
        LIMIT ? OFFSET ?
        """,
        (page_size, (page - 1) * page_size),
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "username": row["username"],
                "is_admin": bool(row["is_admin"]),
                "is_adult": bool(row["is_adult"]),
                "created_at": row["created_at"],
                "number_count": row["number_count"],
                "feedback_count": row["feedback_count"],
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/feedback")
def list_feedback(
    status: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin=Depends(require_admin),
    db=Depends(get_db),
):
    if status != "all" and status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="无效的反馈状态")

    where = "" if status == "all" else "WHERE f.status = ?"
    params: list = [] if status == "all" else [status]
    total = db.execute(
        f"SELECT COUNT(*) AS count FROM feedback f {where}", tuple(params)
    ).fetchone()["count"]
    rows = db.execute(
        f"""
        SELECT
            f.id,
            f.user_id,
            u.username,
            f.category,
            f.content,
            f.screenshot_name,
            f.status,
            f.created_at
        FROM feedback f
        JOIN users u ON u.id = f.user_id
        {where}
        ORDER BY f.id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (page_size, (page - 1) * page_size),
    ).fetchall()

    def count_by(value: str) -> int:
        return db.execute(
            "SELECT COUNT(*) AS count FROM feedback WHERE status = ?", (value,)
        ).fetchone()["count"]

    return {
        "items": [_feedback_payload(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "counts": {
            "all": db.execute("SELECT COUNT(*) AS count FROM feedback").fetchone()[
                "count"
            ],
            "open": count_by("open"),
            "resolved": count_by("resolved"),
        },
    }


@router.patch("/feedback/{feedback_id}")
def update_feedback_status(
    feedback_id: int,
    payload: FeedbackStatusRequest,
    request: Request,
    admin=Depends(require_admin),
    db=Depends(get_db),
):
    if payload.status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="无效的反馈状态")
    row = db.execute(
        "SELECT id FROM feedback WHERE id = ?", (feedback_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    db.execute(
        "UPDATE feedback SET status = ? WHERE id = ?",
        (payload.status, feedback_id),
    )
    db.commit()
    _audit("feedback_status", request, admin, f"id={feedback_id} status={payload.status}")
    return {"ok": True, "id": feedback_id, "status": payload.status}


@router.get("/feedback/{feedback_id}/screenshot")
def get_feedback_screenshot(
    feedback_id: int,
    request: Request,
    admin=Depends(require_admin),
    db=Depends(get_db),
):
    row = db.execute(
        "SELECT screenshot_name, screenshot_mime FROM feedback WHERE id = ?",
        (feedback_id,),
    ).fetchone()
    if row is None or not row["screenshot_name"]:
        raise HTTPException(status_code=404, detail="截图不存在")

    path = store.screenshot_path(row["screenshot_name"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="截图不存在")
    _audit("feedback_screenshot", request, admin, f"id={feedback_id}")
    return FileResponse(
        path,
        media_type=row["screenshot_mime"] or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )

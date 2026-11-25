"""用户反馈 API：提交反馈（可带截图）、查看历史、读取截图。

反馈必须登录后提交，历史记录仅本人可见；截图按账号隔离读取。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .. import feedback as store
from ..db import get_db
from ..deps import get_current_user
from ..security import utc_now_iso

logger = logging.getLogger("helper.api.feedback")

router = APIRouter(prefix="/api/helper/feedback", tags=["helper-feedback"])


def _row_payload(row) -> dict:
    return {
        "id": row["id"],
        "category": row["category"],
        "category_label": store.CATEGORIES.get(row["category"], row["category"]),
        "content": row["content"],
        "has_screenshot": bool(row["screenshot_name"]),
        "created_at": row["created_at"],
    }


@router.post("", status_code=201)
async def create_feedback(
    category: str = Form(...),
    content: str = Form(...),
    screenshot: UploadFile | None = File(default=None),
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    if category not in store.CATEGORIES:
        raise HTTPException(status_code=400, detail="请选择有效的问题类型")

    text = (content or "").strip()
    if len(text) < store.MIN_CONTENT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"反馈内容至少需要 {store.MIN_CONTENT_LENGTH} 个字符",
        )
    if len(text) > store.MAX_CONTENT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"反馈内容最多 {store.MAX_CONTENT_LENGTH} 个字符",
        )

    screenshot_name = None
    screenshot_mime = None
    if screenshot is not None and screenshot.filename:
        data = await screenshot.read(store.MAX_SCREENSHOT_BYTES + 1)
        if not data:
            raise HTTPException(status_code=400, detail="截图文件为空，请重新选择")
        if len(data) > store.MAX_SCREENSHOT_BYTES:
            raise HTTPException(status_code=413, detail="截图不能超过 5 MB")
        detected = store.detect_image(data)
        if detected is None:
            raise HTTPException(
                status_code=400, detail="截图仅支持 PNG、JPG 或 WebP 格式"
            )
        ext, mime = detected
        screenshot_name = store.save_screenshot(data, ext)
        screenshot_mime = mime

    try:
        cursor = db.execute(
            """
            INSERT INTO feedback
                (user_id, category, content, screenshot_name, screenshot_mime, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                current["id"],
                category,
                text,
                screenshot_name,
                screenshot_mime,
                utc_now_iso(),
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        store.delete_screenshot(screenshot_name)
        logger.exception("反馈写入失败 user_id=%s", current["id"])
        raise HTTPException(status_code=500, detail="反馈提交失败，请稍后重试")

    row = db.execute(
        """
        SELECT id, category, content, screenshot_name, created_at
        FROM feedback WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return _row_payload(row)


@router.get("")
def list_feedback(
    limit: int = Query(default=20, ge=1, le=50),
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    rows = db.execute(
        """
        SELECT id, category, content, screenshot_name, created_at
        FROM feedback
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (current["id"], limit),
    ).fetchall()
    total = db.execute(
        "SELECT COUNT(*) AS count FROM feedback WHERE user_id = ?",
        (current["id"],),
    ).fetchone()["count"]
    return {"items": [_row_payload(row) for row in rows], "total": total}


@router.get("/{feedback_id}/screenshot")
def get_screenshot(
    feedback_id: int,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    row = db.execute(
        """
        SELECT screenshot_name, screenshot_mime
        FROM feedback WHERE id = ? AND user_id = ?
        """,
        (feedback_id, current["id"]),
    ).fetchone()
    if row is None or not row["screenshot_name"]:
        raise HTTPException(status_code=404, detail="截图不存在")

    path = store.screenshot_path(row["screenshot_name"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="截图不存在")
    return FileResponse(
        path,
        media_type=row["screenshot_mime"] or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )

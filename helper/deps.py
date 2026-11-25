"""FastAPI 公共依赖：会话令牌解析（Bearer 或 HttpOnly Cookie）与当前用户。"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from security_layer import SESSION_COOKIE_NAME

from .db import get_db
from .security import hash_token, utc_now_iso

UNAUTHORIZED_DETAIL = "请先登录"


def get_session_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    """优先使用 Authorization: Bearer，其次使用 HttpOnly Cookie 会话。

    保留 Bearer 以兼容脚本、API 客户端与现有测试。
    """
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
        return token.strip()
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if cookie_token:
        return cookie_token
    raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)


def get_current_user(
    token: str = Depends(get_session_token),
    db=Depends(get_db),
) -> dict:
    row = db.execute(
        """
        SELECT u.id AS id, u.username AS username
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at > ?
        """,
        (hash_token(token), utc_now_iso()),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
    return {"id": row["id"], "username": row["username"]}

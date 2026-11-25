"""FastAPI 公共依赖：Bearer 令牌解析与当前用户。"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from .db import get_db
from .security import hash_token, utc_now_iso

UNAUTHORIZED_DETAIL = "请先登录"


def get_bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
    return token.strip()


def get_current_user(
    token: str = Depends(get_bearer_token),
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

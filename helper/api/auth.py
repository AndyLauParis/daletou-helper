"""账号 API：注册、登录、退出、当前用户、修改密码、删除账号。"""

from __future__ import annotations

import hmac
import logging
import re
import sqlite3
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from security_layer import (
    clear_session_cookie,
    client_ip,
    set_session_cookie,
)

from .. import config
from ..db import get_db
from ..deps import get_current_user, get_session_token
from ..feedback import delete_user_screenshots
from ..security import (
    hash_password,
    hash_token,
    new_session_token,
    session_expiry,
    utc_now_iso,
    verify_password,
)

logger = logging.getLogger("helper.auth")

router = APIRouter(prefix="/api/helper/auth", tags=["helper-auth"])

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,32}$")

# 登录失败限流（单进程内存字典）：key = (客户端IP, username)
_failures: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()

# 失败计数最多保留的 key 数量，避免随机用户名导致进程内存无界增长
MAX_FAILURE_KEYS = 1024

# 用户不存在时也执行一次同成本的密码校验，避免通过响应时间枚举用户名
_DUMMY_PASSWORD_HASH, _DUMMY_PASSWORD_SALT = hash_password("timing-equalizer")


class RegisterRequest(BaseModel):
    username: str
    password: str
    is_adult: bool = False
    invite_code: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class DeleteAccountRequest(BaseModel):
    password: str
    confirm: str


def _validate_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail="用户名需为 3–32 位字母、数字、下划线或中文",
        )
    return value


def _validate_password(password: str) -> str:
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise HTTPException(status_code=400, detail="密码长度需为 8–128 位")
    return password


def _check_registration_allowed(payload: RegisterRequest, request: Request) -> None:
    """按配置控制注册开放程度：open / invite / closed。"""
    mode = config.REGISTRATION_MODE
    if mode == "open":
        return
    if mode != "invite":
        _audit("register_closed", request, payload.username)
        raise HTTPException(status_code=403, detail="注册暂未开放")
    expected = config.INVITE_CODE or ""
    provided = payload.invite_code or ""
    if not expected or not hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        _audit("register_bad_invite", request, payload.username)
        raise HTTPException(status_code=403, detail="邀请码无效")


def _client_ip(request: Request) -> str:
    return client_ip(request)


def _audit(event: str, request: Request, username: str = "") -> None:
    """安全审计日志：记录事件、客户端 IP 与用户名（过滤换行防日志注入）。"""
    safe_user = (username or "").replace("\r", " ").replace("\n", " ")[:64]
    logger.info(
        "auth_event=%s ip=%s user=%s ua=%s",
        event,
        _client_ip(request),
        safe_user or "-",
        request.headers.get("user-agent", "-")[:120],
    )


def _prune(bucket: list[float], now: float) -> list[float]:
    cutoff = now - config.LOGIN_FAIL_WINDOW_SECONDS
    return [ts for ts in bucket if ts > cutoff]


def _prune_all(now: float) -> None:
    """清理所有已过失败窗口的 key，必须持有 _lock 调用。"""
    for key in list(_failures):
        bucket = _prune(_failures[key], now)
        if bucket:
            _failures[key] = bucket
        else:
            del _failures[key]


def check_login_rate_limit(key: tuple[str, str]) -> None:
    now = time.time()
    with _lock:
        bucket = _prune(_failures.get(key, []), now)
        if bucket:
            _failures[key] = bucket
        else:
            _failures.pop(key, None)
        limited = len(bucket) >= config.LOGIN_FAIL_MAX
    if limited:
        raise HTTPException(
            status_code=429,
            detail="登录失败次数过多，请稍后再试",
        )


def record_login_failure(key: tuple[str, str]) -> None:
    now = time.time()
    with _lock:
        bucket = _prune(_failures.get(key, []), now)
        bucket.append(now)
        if key not in _failures and len(_failures) >= MAX_FAILURE_KEYS:
            _prune_all(now)
            if len(_failures) >= MAX_FAILURE_KEYS:
                oldest = min(_failures, key=lambda item: _failures[item][-1])
                _failures.pop(oldest, None)
        _failures[key] = bucket


def clear_login_failures(key: tuple[str, str]) -> None:
    with _lock:
        _failures.pop(key, None)


def reset_login_rate_limit() -> None:
    """清空限流状态（供测试使用）。"""
    with _lock:
        _failures.clear()


def _issue_session(db: sqlite3.Connection, user_id: int) -> str:
    token = new_session_token()
    db.execute(
        """
        INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            hash_token(token),
            utc_now_iso(),
            session_expiry(config.SESSION_TTL_DAYS),
        ),
    )
    db.commit()
    return token


def _user_payload(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
    }


@router.post("/register", status_code=201)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db=Depends(get_db),
):
    if not payload.is_adult:
        raise HTTPException(
            status_code=400,
            detail="请确认已年满 18 周岁并已阅读合规声明",
        )
    _check_registration_allowed(payload, request)
    username = _validate_username(payload.username)
    password = _validate_password(payload.password)

    exists = db.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    if exists is not None:
        raise HTTPException(status_code=409, detail="该用户名已被注册")

    password_hash, salt_hex = hash_password(password)
    try:
        cursor = db.execute(
            """
            INSERT INTO users (username, password_hash, password_salt, is_adult, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (username, password_hash, salt_hex, utc_now_iso()),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该用户名已被注册") from exc

    user_id = int(cursor.lastrowid)
    token = _issue_session(db, user_id)
    set_session_cookie(
        response, token, request, config.SESSION_TTL_DAYS * 24 * 60 * 60
    )
    _audit("register_ok", request, username)
    return {
        "token": token,
        "user": {"id": user_id, "username": username, "is_admin": False},
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db=Depends(get_db),
):
    username = (payload.username or "").strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="请输入用户名和密码")
    if not USERNAME_RE.fullmatch(username):
        # 不合法的用户名不可能注册成功，直接拒绝且不写入失败计数
        _audit("login_bad_username", request, username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    key = (_client_ip(request), username)
    try:
        check_login_rate_limit(key)
    except HTTPException:
        _audit("login_rate_limited", request, username)
        raise

    row = db.execute(
        """
        SELECT id, username, password_hash, password_salt, is_admin
        FROM users WHERE username = ?
        """,
        (username,),
    ).fetchone()
    if row is None:
        # 用户不存在也走一次 scrypt，保持与真实用户相近的响应时间
        verify_password(payload.password, _DUMMY_PASSWORD_HASH, _DUMMY_PASSWORD_SALT)
        record_login_failure(key)
        _audit("login_failed", request, username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(payload.password, row["password_hash"], row["password_salt"]):
        record_login_failure(key)
        _audit("login_failed", request, username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    clear_login_failures(key)
    token = _issue_session(db, int(row["id"]))
    set_session_cookie(
        response, token, request, config.SESSION_TTL_DAYS * 24 * 60 * 60
    )
    _audit("login_ok", request, username)
    return {"token": token, "user": _user_payload(row)}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current=Depends(get_current_user),
    token: str = Depends(get_session_token),
    db=Depends(get_db),
):
    db.execute(
        "DELETE FROM sessions WHERE user_id = ? AND token_hash = ?",
        (current["id"], hash_token(token)),
    )
    db.commit()
    clear_session_cookie(response, request)
    _audit("logout", request, current["username"])
    return {"ok": True}


@router.get("/me")
def me(current=Depends(get_current_user)):
    return {"user": current}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    new_password = _validate_password(payload.new_password)
    row = db.execute(
        "SELECT password_hash, password_salt FROM users WHERE id = ?",
        (current["id"],),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if not verify_password(payload.old_password, row["password_hash"], row["password_salt"]):
        _audit("change_password_failed", request, current["username"])
        raise HTTPException(status_code=400, detail="旧密码不正确")

    password_hash, salt_hex = hash_password(new_password)
    db.execute(
        "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
        (password_hash, salt_hex, current["id"]),
    )
    db.execute("DELETE FROM sessions WHERE user_id = ?", (current["id"],))
    db.commit()
    clear_session_cookie(response, request)
    _audit("change_password_ok", request, current["username"])
    return {"ok": True, "reauth": True}


@router.delete("/account")
def delete_account(
    payload: DeleteAccountRequest,
    request: Request,
    response: Response,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    if payload.confirm != "DELETE":
        raise HTTPException(status_code=400, detail="请输入 DELETE 以确认删除账号")
    row = db.execute(
        "SELECT password_hash, password_salt FROM users WHERE id = ?",
        (current["id"],),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if not verify_password(payload.password, row["password_hash"], row["password_salt"]):
        _audit("delete_account_failed", request, current["username"])
        raise HTTPException(status_code=403, detail="密码不正确")

    delete_user_screenshots(db, current["id"])
    db.execute("DELETE FROM users WHERE id = ?", (current["id"],))
    db.commit()
    clear_session_cookie(response, request)
    _audit("delete_account_ok", request, current["username"])
    return {"ok": True}

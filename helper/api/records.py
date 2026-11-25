"""号码本 API：按游戏保存/编辑/删除/筛选号码或投注内容。

号码只做记录，不代购、不出票；payload 以 JSON 对象保存。
已实现适配器的游戏会严格校验号码格式，非法内容不写入数据库。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from ..db import get_db
from ..deps import get_current_user
from ..games import registry
from ..security import utc_now_iso

logger = logging.getLogger("helper.api.records")

router = APIRouter(prefix="/api/helper/numbers", tags=["helper-numbers"])

# 单账号号码本上限
MAX_RECORDS_PER_USER = 500


class RecordCreate(BaseModel):
    game_code: str
    name: str = ""
    play_type: str | None = None
    payload: Any = None


class RecordUpdate(BaseModel):
    name: str | None = None
    play_type: str | None = None
    payload: Any = None


def _require_game(code: str):
    meta = registry.get_game(code)
    if meta is None:
        raise HTTPException(status_code=400, detail="未找到该彩票游戏，请从游戏目录中选择")
    return meta


def _require_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="payload 需为 JSON 对象，例如 {\"text\": \"01 02 03\"}",
        )
    return payload


def _validate_or_400(meta, payload: dict, play_type: str | None) -> None:
    """用已实现适配器严格校验号码；不合法时抛 400，避免写入脏数据。"""
    if meta.support_level != "full":
        return
    adapter = registry.get_adapter(meta.code)
    if adapter is None or not hasattr(adapter, "validate_ticket"):
        return
    try:
        result = adapter.validate_ticket(payload, play_type)
    except Exception:  # 适配器异常不影响记录保存
        logger.warning("号码格式校验失败：%s", meta.code, exc_info=True)
        return
    if not isinstance(result, dict) or result.get("ok", True):
        return
    errors = result.get("errors")
    messages = (
        [str(item) for item in errors if str(item).strip()]
        if isinstance(errors, list)
        else []
    )
    detail = "号码格式不正确"
    if messages:
        detail += "：" + "；".join(messages[:3])
    raise HTTPException(status_code=400, detail=detail)


def _record(row) -> dict:
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        payload = {}
    meta = registry.get_game(row["game_code"])
    return {
        "id": row["id"],
        "game_code": row["game_code"],
        "game_name": meta.name if meta is not None else row["game_code"],
        "name": row["name"],
        "play_type": row["play_type"],
        "payload": payload,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _fetch_record(db, user_id: int, record_id: int):
    return db.execute(
        "SELECT * FROM number_sets WHERE id = ? AND user_id = ?",
        (record_id, user_id),
    ).fetchone()


@router.get("")
def list_records(
    game_code: str | None = None,
    category: str | None = None,
    days: int | None = Query(default=None, ge=1, le=3650),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    user_id = current["id"]
    where = "user_id = ?"
    params: list[Any] = [user_id]

    code = (game_code or "").strip().lower()
    if code:
        where += " AND game_code = ?"
        params.append(code)

    category_value = (category or "").strip().lower()
    if category_value:
        if category_value not in registry.CATEGORY_LABELS:
            raise HTTPException(status_code=400, detail="未知游戏类别")
        codes = [
            meta.code
            for meta in registry.list_games()
            if meta.category == category_value
        ]
        placeholders = ",".join("?" for _ in codes)
        where += f" AND game_code IN ({placeholders})"
        params.extend(codes)

    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        where += " AND created_at >= ?"
        params.append(cutoff)

    total = db.execute(
        f"SELECT COUNT(*) AS n FROM number_sets WHERE {where}", params
    ).fetchone()["n"]
    rows = db.execute(
        f"""
        SELECT * FROM number_sets
        WHERE {where}
        ORDER BY updated_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    return {"total": int(total), "items": [_record(row) for row in rows]}


@router.post("", status_code=201)
def create_record(
    body: RecordCreate,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    user_id = current["id"]
    meta = _require_game(body.game_code)
    payload = _require_payload(body.payload)
    play_type = (body.play_type or "").strip() or None
    _validate_or_400(meta, payload, play_type)

    count = db.execute(
        "SELECT COUNT(*) AS n FROM number_sets WHERE user_id = ?", (user_id,)
    ).fetchone()["n"]
    if int(count) >= MAX_RECORDS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"号码本最多保存 {MAX_RECORDS_PER_USER} 条",
        )

    now = utc_now_iso()
    cursor = db.execute(
        """
        INSERT INTO number_sets
            (user_id, game_code, name, play_type, payload_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            meta.code,
            (body.name or "").strip(),
            play_type,
            json.dumps(payload, ensure_ascii=False),
            now,
            now,
        ),
    )
    db.commit()

    row = _fetch_record(db, user_id, int(cursor.lastrowid))
    return _record(row)


@router.put("/{record_id}")
def update_record(
    record_id: int,
    body: RecordUpdate,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    user_id = current["id"]
    row = _fetch_record(db, user_id, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到该记录")

    provided = body.model_fields_set
    name = row["name"]
    play_type = row["play_type"]
    payload_json = row["payload_json"]
    payload = None

    if "name" in provided:
        name = (body.name or "").strip()
    if "play_type" in provided:
        play_type = (body.play_type or "").strip() or None
    if "payload" in provided:
        payload = _require_payload(body.payload)
        payload_json = json.dumps(payload, ensure_ascii=False)

    if "payload" in provided or "play_type" in provided:
        meta = registry.get_game(row["game_code"])
        if meta is not None:
            if payload is None:
                try:
                    payload = json.loads(payload_json)
                except (TypeError, ValueError):
                    payload = {}
            _validate_or_400(meta, payload, play_type)

    db.execute(
        """
        UPDATE number_sets
        SET name = ?, play_type = ?, payload_json = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (name, play_type, payload_json, utc_now_iso(), record_id, user_id),
    )
    db.commit()

    updated = _fetch_record(db, user_id, record_id)
    return _record(updated)


@router.delete("/{record_id}", status_code=204)
def delete_record(
    record_id: int,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    cursor = db.execute(
        "DELETE FROM number_sets WHERE id = ? AND user_id = ?",
        (record_id, current["id"]),
    )
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="未找到该记录")
    return Response(status_code=204)

"""识别结果积累：校验、去重、状态标记、查询、统计、导出与同步。

所有记录按用户隔离；写入使用指纹唯一约束去重，并由后台任务异步落库，
不阻塞主识别流程。confidence 低于阈值的记录标记为 review（待人工审核），
号码校验失败或期号缺失的记录标记为 anomaly（异常）。
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone

from . import config, db
from .games import registry
from .security import utc_now_iso

logger = logging.getLogger("helper.recognition")

STATUS_VALID = "valid"
STATUS_REVIEW = "review"
STATUS_ANOMALY = "anomaly"
STATUSES = (STATUS_VALID, STATUS_REVIEW, STATUS_ANOMALY)
STATUS_LABELS = {
    STATUS_VALID: "有效",
    STATUS_REVIEW: "待人工审核",
    STATUS_ANOMALY: "异常",
}

ISSUE_RE = re.compile(r"^\d{3,12}$")
MAX_EXPORT_ROWS = 10000
MAX_SYNC_BATCH = 200


class RecognitionError(ValueError):
    """识别数据不满足入库条件。"""


def _clamp_confidence(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def normalize_issue(raw) -> str:
    text = str(raw or "").strip()
    text = text.replace("第", "").replace("期", "").strip()
    if not ISSUE_RE.fullmatch(text):
        raise RecognitionError("期号格式不正确，应为 3–12 位数字")
    return text


def normalize_play_type(raw) -> str | None:
    text = str(raw or "").strip()
    return text[:32] or None


def _fmt_numbers(values) -> str:
    parts = []
    for value in values or []:
        try:
            parts.append(f"{int(value):02d}")
        except (TypeError, ValueError):
            parts.append(str(value))
    return " ".join(parts)


def numbers_text(game_code: str, payload: dict) -> str:
    """生成便于展示、搜索与导出的号码文本。"""
    if not isinstance(payload, dict):
        return str(payload)[:200]
    if game_code == "dlt":
        return f"前区 {_fmt_numbers(payload.get('front'))} + 后区 {_fmt_numbers(payload.get('back'))}"
    if game_code == "ssq":
        return f"红球 {_fmt_numbers(payload.get('red'))} + 蓝球 {_fmt_numbers(payload.get('blue'))}"
    if game_code == "qxc":
        front = payload.get("front")
        front_text = "".join(str(value) for value in front) if isinstance(front, list) else str(front or "")
        return f"前区 {front_text} + 后区 {payload.get('back')}"
    if game_code == "qlc":
        return "基本 " + _fmt_numbers(payload.get("basic"))
    if game_code == "kl8":
        return f"{payload.get('play_type') or '选号'}：{_fmt_numbers(payload.get('picks'))}"
    if game_code in {"pl3", "pl5", "fc3d"}:
        digits = payload.get("digits") or []
        text = "".join(str(value) for value in digits)
        play = payload.get("play_type")
        return f"{text}（{play}）" if play else text
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)[:200]


def build_fingerprint(
    user_id: int, game_code: str, issue: str, play_type: str | None, payload, ticket_no: str | None
) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    raw = "|".join(
        [
            str(user_id),
            game_code,
            issue,
            play_type or "",
            ticket_no or "",
            canonical,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_record(
    game_code: str,
    issue: str,
    payload,
    play_type: str | None = None,
    confidence: float = 0.0,
    field_confidence: dict | None = None,
) -> dict:
    """校验并归一化一条识别数据；返回可入库的结构。

    结构性错误不抛异常，而是标记为 anomaly，便于后台保留异常数据。
    彩票类型不存在、号码完全缺失等无法归属的错误抛出 RecognitionError。
    """
    code = str(game_code or "").strip().lower()
    meta = registry.get_game(code)
    adapter = registry.get_adapter(code) if meta is not None else None
    if meta is None:
        raise RecognitionError("未找到该彩票游戏")
    if adapter is None or not hasattr(adapter, "validate_ticket"):
        raise RecognitionError("该游戏暂不支持号码校验")
    if payload is None:
        raise RecognitionError("缺少识别到的号码")

    issue_text = str(issue or "").strip().replace("第", "").replace("期", "")
    errors: list[str] = []
    if not ISSUE_RE.fullmatch(issue_text):
        errors.append("期号格式不正确")
        issue_text = issue_text[:20] or "unknown"

    validation = adapter.validate_ticket(payload, play_type)
    if not validation.get("ok"):
        errors.extend(validation.get("errors") or ["号码格式不合法"])
    normalized = validation.get("normalized") or payload
    play_type_norm = None
    if isinstance(normalized, dict):
        play_type_norm = normalize_play_type(normalized.get("play_type") or play_type)

    total_confidence = _clamp_confidence(confidence)
    fields = {
        str(key)[:32]: _clamp_confidence(value)
        for key, value in (field_confidence or {}).items()
    }
    threshold = config.OCR_CONFIDENCE_THRESHOLD
    low_fields = [key for key, value in fields.items() if value < threshold]

    if errors:
        status = STATUS_ANOMALY
        reason = "；".join(dict.fromkeys(errors))
    elif total_confidence < threshold:
        status = STATUS_REVIEW
        reason = f"总体置信度 {total_confidence:.2f} 低于阈值 {threshold:.2f}"
    elif low_fields:
        status = STATUS_REVIEW
        reason = "分项置信度偏低：" + "、".join(low_fields)
    else:
        status = STATUS_VALID
        reason = ""

    return {
        "game_code": meta.code,
        "game_name": meta.name,
        "issue": issue_text,
        "play_type": play_type_norm,
        "payload": normalized,
        "numbers_text": numbers_text(meta.code, normalized),
        "confidence": total_confidence,
        "field_confidence": fields,
        "status": status,
        "anomaly_reason": reason,
        "errors": errors,
    }


def public_payload(prepared: dict) -> dict:
    """把校验结果转为接口返回结构（不含内部 errors 细节以外的字段）。"""
    return {
        "game_code": prepared["game_code"],
        "game_name": prepared.get("game_name"),
        "issue": prepared["issue"],
        "play_type": prepared.get("play_type"),
        "payload": prepared["payload"],
        "numbers_text": prepared["numbers_text"],
        "confidence": prepared["confidence"],
        "field_confidence": prepared["field_confidence"],
        "status": prepared["status"],
        "status_label": STATUS_LABELS.get(prepared["status"], prepared["status"]),
        "anomaly_reason": prepared["anomaly_reason"],
    }


def _row_payload(row, *, detail: bool = False) -> dict:
    meta = registry.get_game(row["game_code"])
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        payload = {}
    try:
        field_confidence = json.loads(row["field_confidence_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        field_confidence = {}
    item = {
        "id": row["id"],
        "game_code": row["game_code"],
        "game_name": meta.name if meta is not None else row["game_code"],
        "issue": row["issue"],
        "play_type": row["play_type"],
        "payload": payload,
        "numbers_text": row["numbers_text"],
        "confidence": row["confidence"],
        "field_confidence": field_confidence,
        "status": row["status"],
        "status_label": STATUS_LABELS.get(row["status"], row["status"]),
        "anomaly_reason": row["anomaly_reason"],
        "review_note": row["review_note"],
        "reviewed": bool(row["reviewed"]),
        "source": row["source"],
        "ticket_no": row["ticket_no"],
        "seen_count": row["seen_count"],
        "revision": row["revision"],
        "recognized_at": row["recognized_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if detail:
        item["raw_text"] = row["raw_text"]
    return item


def upsert_record(
    conn: sqlite3.Connection,
    user_id: int,
    prepared: dict,
    *,
    source: str = "ocr",
    ticket_no: str | None = None,
    raw_text: str = "",
    recognized_at: str | None = None,
    count_seen: bool = True,
    updated_at: str | None = None,
) -> dict:
    """写入或合并一条识别记录（依赖 (user_id, fingerprint) 唯一约束）。"""
    fingerprint = build_fingerprint(
        user_id,
        prepared["game_code"],
        prepared["issue"],
        prepared.get("play_type"),
        prepared["payload"],
        ticket_no,
    )
    now = utc_now_iso()
    recognized = recognized_at or now
    updated = updated_at or now
    threshold = config.OCR_CONFIDENCE_THRESHOLD
    seen_increment = 1 if count_seen else 0

    conn.execute(
        """
        INSERT INTO recognition_records (
            user_id, fingerprint, game_code, issue, play_type, payload_json,
            numbers_text, confidence, field_confidence_json, status,
            anomaly_reason, review_note, reviewed, source, ticket_no, raw_text,
            seen_count, revision, recognized_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0, ?, ?, ?, 1, 1, ?, ?, ?)
        ON CONFLICT(user_id, fingerprint) DO UPDATE SET
            seen_count = recognition_records.seen_count + ?,
            confidence = MAX(recognition_records.confidence, excluded.confidence),
            status = CASE
                WHEN recognition_records.status = 'anomaly'
                     OR excluded.status = 'anomaly' THEN 'anomaly'
                WHEN MAX(recognition_records.confidence, excluded.confidence) >= ?
                    THEN 'valid'
                ELSE 'review'
            END,
            anomaly_reason = CASE
                WHEN recognition_records.status = 'anomaly'
                    THEN recognition_records.anomaly_reason
                WHEN excluded.status = 'anomaly' THEN excluded.anomaly_reason
                WHEN MAX(recognition_records.confidence, excluded.confidence) >= ?
                    THEN ''
                ELSE excluded.anomaly_reason
            END,
            ticket_no = COALESCE(excluded.ticket_no, recognition_records.ticket_no),
            raw_text = CASE WHEN excluded.raw_text <> ''
                THEN excluded.raw_text ELSE recognition_records.raw_text END,
            recognized_at = MAX(recognition_records.recognized_at, excluded.recognized_at),
            revision = recognition_records.revision + 1,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            fingerprint,
            prepared["game_code"],
            prepared["issue"],
            prepared.get("play_type"),
            json.dumps(prepared["payload"], ensure_ascii=False, sort_keys=True),
            prepared["numbers_text"],
            prepared["confidence"],
            json.dumps(prepared["field_confidence"], ensure_ascii=False, sort_keys=True),
            prepared["status"],
            prepared["anomaly_reason"],
            source[:16],
            ticket_no,
            (raw_text or "")[:2000],
            recognized,
            now,
            updated,
            seen_increment,
            threshold,
            threshold,
        ),
    )
    row = conn.execute(
        "SELECT * FROM recognition_records WHERE user_id = ? AND fingerprint = ?",
        (user_id, fingerprint),
    ).fetchone()
    if row is None:
        raise RecognitionError("识别记录写入失败")
    action = "created" if row["seen_count"] == 1 and row["revision"] == 1 else "merged"
    return {"action": action, "record": _row_payload(row)}


def persist_record(
    user_id: int,
    prepared: dict,
    *,
    source: str = "ocr",
    ticket_no: str | None = None,
    raw_text: str = "",
    recognized_at: str | None = None,
) -> dict | None:
    """后台任务入口：独立连接落库，失败只记录日志，不影响主流程。"""
    conn = db.connect()
    try:
        result = upsert_record(
            conn,
            user_id,
            prepared,
            source=source,
            ticket_no=ticket_no,
            raw_text=raw_text,
            recognized_at=recognized_at,
        )
        conn.commit()
        logger.info(
            "识别记录已%s user_id=%s id=%s game=%s issue=%s status=%s",
            "创建" if result["action"] == "created" else "合并",
            user_id,
            result["record"]["id"],
            prepared["game_code"],
            prepared["issue"],
            prepared["status"],
        )
        return result
    except Exception:
        conn.rollback()
        logger.exception("识别记录落库失败 user_id=%s", user_id)
        return None
    finally:
        conn.close()


def _filters(
    user_id: int,
    *,
    game_code: str = "",
    issue: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    keyword: str = "",
) -> tuple[str, list]:
    clauses = ["user_id = ?"]
    params: list = [user_id]
    if game_code:
        clauses.append("game_code = ?")
        params.append(game_code)
    if issue:
        clauses.append("issue = ?")
        params.append(issue)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if date_from:
        clauses.append("substr(recognized_at, 1, 10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(recognized_at, 1, 10) <= ?")
        params.append(date_to)
    if keyword:
        clauses.append("(numbers_text LIKE ? OR issue LIKE ? OR ticket_no LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    return " AND ".join(clauses), params


def list_records(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
    **filters,
) -> dict:
    where, params = _filters(user_id, **filters)
    total = conn.execute(
        f"SELECT COUNT(*) AS count FROM recognition_records WHERE {where}",
        tuple(params),
    ).fetchone()["count"]
    rows = conn.execute(
        f"""
        SELECT * FROM recognition_records
        WHERE {where}
        ORDER BY recognized_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (page_size, (page - 1) * page_size),
    ).fetchall()
    return {
        "items": [_row_payload(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def stats(conn: sqlite3.Connection, user_id: int) -> dict:
    def scalar(sql: str, params: tuple = ()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row is not None else 0

    by_status = {status: 0 for status in STATUSES}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS count FROM recognition_records "
        "WHERE user_id = ? GROUP BY status",
        (user_id,),
    ):
        by_status[row["status"]] = row["count"]

    by_game = []
    for row in conn.execute(
        """
        SELECT game_code, COUNT(*) AS count, AVG(confidence) AS avg_confidence
        FROM recognition_records
        WHERE user_id = ?
        GROUP BY game_code
        ORDER BY count DESC
        """,
        (user_id,),
    ):
        meta = registry.get_game(row["game_code"])
        by_game.append(
            {
                "game_code": row["game_code"],
                "game_name": meta.name if meta is not None else row["game_code"],
                "count": row["count"],
                "avg_confidence": round(float(row["avg_confidence"] or 0), 3),
            }
        )

    top_issues = [
        {"issue": row["issue"], "count": row["count"]}
        for row in conn.execute(
            """
            SELECT issue, COUNT(*) AS count
            FROM recognition_records
            WHERE user_id = ?
            GROUP BY issue
            ORDER BY count DESC, issue DESC
            LIMIT 5
            """,
            (user_id,),
        )
    ]

    average = conn.execute(
        "SELECT AVG(confidence) AS value FROM recognition_records WHERE user_id = ?",
        (user_id,),
    ).fetchone()["value"]
    duplicates = scalar(
        "SELECT COALESCE(SUM(seen_count - 1), 0) FROM recognition_records WHERE user_id = ?",
        (user_id,),
    )
    return {
        "total": scalar(
            "SELECT COUNT(*) FROM recognition_records WHERE user_id = ?", (user_id,)
        ),
        "by_status": by_status,
        "by_game": by_game,
        "top_issues": top_issues,
        "avg_confidence": round(float(average or 0), 3),
        "duplicate_hits": duplicates,
        "latest_recognized_at": conn.execute(
            "SELECT MAX(recognized_at) AS value FROM recognition_records WHERE user_id = ?",
            (user_id,),
        ).fetchone()["value"],
    }


def export_rows(
    conn: sqlite3.Connection, user_id: int, **filters
) -> list[dict]:
    where, params = _filters(user_id, **filters)
    rows = conn.execute(
        f"""
        SELECT * FROM recognition_records
        WHERE {where}
        ORDER BY recognized_at DESC, id DESC
        LIMIT ?
        """,
        tuple(params) + (MAX_EXPORT_ROWS,),
    ).fetchall()
    return [_row_payload(row, detail=True) for row in rows]


def export_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "ID",
            "彩票类型",
            "游戏代码",
            "期号",
            "玩法",
            "号码",
            "总体置信度",
            "状态",
            "异常原因",
            "来源",
            "票号",
            "出现次数",
            "识别时间",
            "更新时间",
        ]
    )
    for item in rows:
        writer.writerow(
            [
                item["id"],
                item["game_name"],
                item["game_code"],
                item["issue"],
                item["play_type"] or "",
                item["numbers_text"],
                f"{item['confidence']:.2f}",
                item["status_label"],
                item["anomaly_reason"],
                item["source"],
                item["ticket_no"] or "",
                item["seen_count"],
                item["recognized_at"],
                item["updated_at"],
            ]
        )
    return "\ufeff" + buffer.getvalue()


def changes(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    since: str | None = None,
    cursor: int = 0,
    page_size: int = 200,
    full: bool = False,
) -> dict:
    """增量（按 updated_at + id）或全量（按 id）同步。"""
    if full:
        rows = conn.execute(
            "SELECT * FROM recognition_records WHERE user_id = ? AND id > ? "
            "ORDER BY id LIMIT ?",
            (user_id, cursor, page_size),
        ).fetchall()
        next_cursor = rows[-1]["id"] if rows else cursor
        return {
            "full": True,
            "items": [_row_payload(row, detail=True) for row in rows],
            "has_more": len(rows) == page_size,
            "next_cursor": next_cursor,
            "server_time": utc_now_iso(),
        }

    since_value = since or "1970-01-01T00:00:00+00:00"
    rows = conn.execute(
        """
        SELECT * FROM recognition_records
        WHERE user_id = ? AND (updated_at > ? OR (updated_at = ? AND id > ?))
        ORDER BY updated_at, id
        LIMIT ?
        """,
        (user_id, since_value, since_value, cursor, page_size),
    ).fetchall()
    next_since = rows[-1]["updated_at"] if rows else since_value
    next_cursor = rows[-1]["id"] if rows else cursor
    return {
        "full": False,
        "items": [_row_payload(row, detail=True) for row in rows],
        "has_more": len(rows) == page_size,
        "next_since": next_since,
        "next_cursor": next_cursor,
        "server_time": utc_now_iso(),
    }


def merge_sync(
    conn: sqlite3.Connection, user_id: int, records: list[dict]
) -> dict:
    """批量合并客户端记录：updated_at 较新者覆盖，较旧者跳过。"""
    inserted = updated = skipped = 0
    errors: list[str] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            errors.append(f"第 {index + 1} 条不是对象")
            continue
        try:
            prepared = validate_record(
                raw.get("game_code", ""),
                raw.get("issue", ""),
                raw.get("payload"),
                raw.get("play_type"),
                raw.get("confidence", 0),
                raw.get("field_confidence") or {},
            )
        except RecognitionError as exc:
            errors.append(f"第 {index + 1} 条：{exc}")
            continue

        ticket_no = str(raw.get("ticket_no") or "").strip()[:64] or None
        fingerprint = build_fingerprint(
            user_id,
            prepared["game_code"],
            prepared["issue"],
            prepared.get("play_type"),
            prepared["payload"],
            ticket_no,
        )
        existing = conn.execute(
            "SELECT id, updated_at FROM recognition_records "
            "WHERE user_id = ? AND fingerprint = ?",
            (user_id, fingerprint),
        ).fetchone()
        incoming_updated = str(raw.get("updated_at") or utc_now_iso())[:40]
        if existing is not None and existing["updated_at"] >= incoming_updated:
            skipped += 1
            continue

        result = upsert_record(
            conn,
            user_id,
            prepared,
            source=str(raw.get("source") or "sync")[:16],
            ticket_no=ticket_no,
            raw_text=str(raw.get("raw_text") or "")[:2000],
            recognized_at=str(raw.get("recognized_at") or utc_now_iso())[:40],
            count_seen=False,
            updated_at=incoming_updated,
        )
        if existing is None:
            inserted += 1
        else:
            updated += 1
        del result
    conn.commit()
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


def revalidate(conn: sqlite3.Connection, user_id: int) -> dict:
    """重新校验未被人工复核的记录，修复阈值调整后的状态。"""
    rows = conn.execute(
        "SELECT * FROM recognition_records WHERE user_id = ? AND reviewed = 0",
        (user_id,),
    ).fetchall()
    changed = 0
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
            field_confidence = json.loads(row["field_confidence_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        prepared = validate_record(
            row["game_code"],
            row["issue"],
            payload,
            row["play_type"],
            row["confidence"],
            field_confidence,
        )
        if (
            prepared["status"] != row["status"]
            or prepared["anomaly_reason"] != row["anomaly_reason"]
        ):
            conn.execute(
                "UPDATE recognition_records SET status = ?, anomaly_reason = ?, "
                "revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (
                    prepared["status"],
                    prepared["anomaly_reason"],
                    utc_now_iso(),
                    row["id"],
                    user_id,
                ),
            )
            changed += 1
    conn.commit()
    return {"checked": len(rows), "changed": changed}

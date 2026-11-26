"""票面识别结果积累 API：扫描识别、查询、复核、统计、导出与同步。

识别成功后由后台任务异步落库；接口立即返回归一化预览，不阻塞主流程。
所有记录按登录用户隔离。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field

from .. import config, feedback as feedback_store
from .. import ocr, recognition
from ..db import get_db
from ..deps import get_current_user
from ..security import utc_now_iso

logger = logging.getLogger("helper.api.recognition")

router = APIRouter(prefix="/api/helper/recognition", tags=["helper-recognition"])

DATE_RE = r"^\d{4}-\d{2}-\d{2}$"


class RecognitionCreate(BaseModel):
    game_code: str
    issue: str = ""
    play_type: str | None = None
    payload: Any
    confidence: float = 0.0
    field_confidence: dict[str, float] = Field(default_factory=dict)
    source: str = "manual"
    ticket_no: str | None = None
    recognized_at: str | None = None


class RecordUpdate(BaseModel):
    status: str | None = None
    review_note: str | None = None


class SyncRequest(BaseModel):
    records: list[dict] = Field(default_factory=list)


def _prepare(
    game_code: str,
    issue: str,
    payload: Any,
    play_type: str | None,
    confidence: float,
    field_confidence: dict,
) -> dict:
    try:
        return recognition.validate_record(
            game_code, issue, payload, play_type, confidence, field_confidence
        )
    except recognition.RecognitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _sync_filters(
    game_code: str,
    issue: str,
    status: str,
    date_from: str,
    date_to: str,
    keyword: str,
) -> dict:
    if status and status not in recognition.STATUSES:
        raise HTTPException(status_code=400, detail="无效的记录状态")
    return {
        "game_code": game_code.strip(),
        "issue": issue.strip(),
        "status": status.strip(),
        "date_from": date_from.strip(),
        "date_to": date_to.strip(),
        "keyword": keyword.strip()[:60],
    }


@router.get("/config")
def get_config(current=Depends(get_current_user)):
    return ocr.public_status()


@router.post("/scan", status_code=202)
async def scan_ticket(
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    game_code: str = Form(default=""),
    issue: str = Form(default=""),
    current=Depends(get_current_user),
):
    data = await image.read(config.OCR_MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="请上传彩票图片")
    if len(data) > config.OCR_MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片不能超过 8 MB")
    detected = feedback_store.detect_image(data)
    if detected is None:
        raise HTTPException(status_code=400, detail="仅支持 PNG、JPG 或 WebP 图片")

    _, mime = detected
    hint = (game_code or "").strip().lower()
    try:
        result = ocr.recognize_ticket(data, mime, game_hint=hint or None)
    except ocr.OcrNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ocr.OcrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    prepared = _prepare(
        result["game_code"],
        (issue or "").strip() or result["issue"],
        result["payload"],
        result.get("play_type"),
        result.get("confidence", 0.0),
        result.get("field_confidence") or {},
    )

    recognized_at = utc_now_iso()
    background_tasks.add_task(
        recognition.persist_record,
        current["id"],
        prepared,
        source="ocr",
        ticket_no=result.get("ticket_no"),
        raw_text=result.get("raw_text") or "",
        recognized_at=recognized_at,
    )
    return {
        "queued": True,
        "record": recognition.public_payload(prepared),
        "ocr": {
            "model": result.get("model"),
            "provider": result.get("provider"),
            "recognized_at": recognized_at,
        },
    }


@router.post("/records", status_code=202)
def create_record(
    payload: RecognitionCreate,
    background_tasks: BackgroundTasks,
    current=Depends(get_current_user),
):
    prepared = _prepare(
        payload.game_code,
        payload.issue,
        payload.payload,
        payload.play_type,
        payload.confidence,
        payload.field_confidence,
    )
    recognized_at = (payload.recognized_at or "").strip()[:40] or utc_now_iso()
    background_tasks.add_task(
        recognition.persist_record,
        current["id"],
        prepared,
        source=payload.source or "manual",
        ticket_no=(payload.ticket_no or "").strip()[:64] or None,
        raw_text="",
        recognized_at=recognized_at,
    )
    return {"queued": True, "record": recognition.public_payload(prepared)}


@router.get("/records")
def list_records(
    game_code: str = Query(default=""),
    issue: str = Query(default=""),
    status: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    filters = _sync_filters(game_code, issue, status, date_from, date_to, keyword)
    return recognition.list_records(
        db, current["id"], page=page, page_size=page_size, **filters
    )


@router.get("/records/{record_id}")
def get_record(
    record_id: int,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM recognition_records WHERE id = ? AND user_id = ?",
        (record_id, current["id"]),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="识别记录不存在")
    return recognition._row_payload(row, detail=True)


@router.patch("/records/{record_id}")
def update_record(
    record_id: int,
    payload: RecordUpdate,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    if payload.status is not None and payload.status not in recognition.STATUSES:
        raise HTTPException(status_code=400, detail="无效的记录状态")
    if payload.status is None and payload.review_note is None:
        raise HTTPException(status_code=400, detail="没有需要更新的内容")

    row = db.execute(
        "SELECT id FROM recognition_records WHERE id = ? AND user_id = ?",
        (record_id, current["id"]),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="识别记录不存在")

    note = payload.review_note
    if note is not None:
        note = note.strip()[:200]
    db.execute(
        """
        UPDATE recognition_records
        SET status = COALESCE(?, status),
            anomaly_reason = CASE WHEN ? = 'valid' THEN '' ELSE anomaly_reason END,
            review_note = COALESCE(?, review_note),
            reviewed = 1,
            revision = revision + 1,
            updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            payload.status,
            payload.status,
            note,
            utc_now_iso(),
            record_id,
            current["id"],
        ),
    )
    db.commit()
    updated = db.execute(
        "SELECT * FROM recognition_records WHERE id = ? AND user_id = ?",
        (record_id, current["id"]),
    ).fetchone()
    return recognition._row_payload(updated, detail=True)


@router.post("/revalidate")
def revalidate_records(
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    return recognition.revalidate(db, current["id"])


@router.get("/stats")
def get_stats(current=Depends(get_current_user), db=Depends(get_db)):
    return recognition.stats(db, current["id"])


@router.get("/export")
def export_records(
    format: str = Query(default="csv"),
    game_code: str = Query(default=""),
    issue: str = Query(default=""),
    status: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    keyword: str = Query(default=""),
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    if format not in {"csv", "json"}:
        raise HTTPException(status_code=400, detail="仅支持 csv 或 json 导出")
    filters = _sync_filters(game_code, issue, status, date_from, date_to, keyword)
    rows = recognition.export_rows(db, current["id"], **filters)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    if format == "json":
        body = json.dumps(
            {
                "exported_at": utc_now_iso(),
                "count": len(rows),
                "items": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        return Response(
            content=body,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="recognition-{stamp}.json"',
                "Cache-Control": "no-store",
            },
        )
    return Response(
        content=recognition.export_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="recognition-{stamp}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/sync")
def sync_records(
    full: bool = Query(default=False),
    since: str = Query(default=""),
    cursor: int = Query(default=0, ge=0),
    page_size: int = Query(default=200, ge=1, le=500),
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    return recognition.changes(
        db,
        current["id"],
        since=(since or "").strip()[:40] or None,
        cursor=cursor,
        page_size=page_size,
        full=full,
    )


@router.post("/sync")
def merge_records(
    payload: SyncRequest,
    current=Depends(get_current_user),
    db=Depends(get_db),
):
    if len(payload.records) > recognition.MAX_SYNC_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多同步 {recognition.MAX_SYNC_BATCH} 条记录",
        )
    return recognition.merge_sync(db, current["id"], payload.records)

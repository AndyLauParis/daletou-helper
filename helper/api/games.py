"""游戏目录、开奖缓存与号码核对 API（全部公开，不要求登录）。"""

from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..games import cache, registry
from ..games.base import GameMeta

logger = logging.getLogger("helper.api.games")

router = APIRouter(prefix="/api/helper", tags=["helper-games"])

# 每次抓取默认取最近 30 期
FETCH_LIMIT = 30

# 缓存有效期（秒）
CACHE_TTL_SECONDS = cache.DEFAULT_TTL_SECONDS

# 同一游戏同时只允许一个抓取任务；全局最多 4 个上游抓取并发
MAX_CONCURRENT_FETCHES = 4

# 手动刷新（refresh=true 或 POST /refresh）的最小间隔（秒）
MIN_REFRESH_INTERVAL_SECONDS = 30


class CheckRequest(BaseModel):
    game_code: str
    play_type: str | None = None
    payload: dict = Field(default_factory=dict)


def _game_dict(meta: GameMeta) -> dict:
    data = meta.to_dict()
    data["has_adapter"] = registry.has_adapter(meta.code)
    return data


def _game_with_status(meta: GameMeta) -> dict:
    data = _game_dict(meta)
    data["data_status"] = cache.status_for(meta.code)
    return data


def _source_of(meta: GameMeta, adapter) -> str | None:
    return (
        getattr(adapter, "SOURCE_NAME", None)
        or getattr(adapter, "source_name", None)
        or meta.source_name
    )


def _fetch(adapter) -> list[dict]:
    """调用适配器抓取开奖数据，并校验返回类型。"""
    draws = adapter.fetch_draws(limit=FETCH_LIMIT)
    if not isinstance(draws, list):
        raise ValueError("适配器返回格式异常")
    return draws


def _fetch_and_save(meta: GameMeta, adapter) -> tuple[list[dict], dict | None]:
    """抓取并与旧缓存合并保存，返回 (合并后的开奖列表, 保存载荷或 None)。"""
    old = cache.load_cache(meta.code)
    fetched = _fetch(adapter)
    merged = cache.merge_draws(old.get("draws"), fetched)
    if not merged:
        return [], None
    saved = cache.save_cache(
        meta.code,
        merged,
        _source_of(meta, adapter),
        status="ok",
    )
    return merged, saved


_refresh_locks: dict[str, threading.Lock] = {}
_refresh_guard = threading.Lock()
_last_refresh_at: dict[str, float] = {}
_fetch_slots = threading.BoundedSemaphore(MAX_CONCURRENT_FETCHES)


class RefreshBusy(Exception):
    """当前无法立即开始抓取：正在刷新、过于频繁或并发已满。"""


def _game_lock(code: str) -> threading.Lock:
    with _refresh_guard:
        lock = _refresh_locks.get(code)
        if lock is None:
            lock = threading.Lock()
            _refresh_locks[code] = lock
        return lock


def reset_refresh_state() -> None:
    """清空手动刷新节流状态（供测试使用）。"""
    with _refresh_guard:
        _last_refresh_at.clear()


def _fetch_with_guard(meta: GameMeta, adapter, *, explicit: bool):
    """带互斥、频率与并发上限的抓取；拿不到资源时立即失败，不占线程排队。"""
    lock = _game_lock(meta.code)
    if not lock.acquire(blocking=False):
        raise RefreshBusy("该游戏正在更新，请稍后重试")
    try:
        if explicit:
            now = time.monotonic()
            with _refresh_guard:
                last = _last_refresh_at.get(meta.code, 0.0)
            if now - last < MIN_REFRESH_INTERVAL_SECONDS:
                wait = int(MIN_REFRESH_INTERVAL_SECONDS - (now - last)) + 1
                raise RefreshBusy(f"刷新过于频繁，请 {wait} 秒后再试")
        if not _fetch_slots.acquire(blocking=False):
            raise RefreshBusy("当前更新任务较多，请稍后重试")
        try:
            if explicit:
                with _refresh_guard:
                    _last_refresh_at[meta.code] = time.monotonic()
            return _fetch_and_save(meta, adapter)
        finally:
            _fetch_slots.release()
    finally:
        lock.release()


@router.get("/games")
def list_games():
    """全部游戏目录，按类别固定分组，并附带各游戏缓存状态。"""
    groups = []
    total = 0
    for group in registry.catalog_groups():
        games = []
        for meta in group["games"]:
            games.append(_game_with_status(meta))
            total += 1
        groups.append(
            {
                "category": group["category"],
                "category_label": group["category_label"],
                "games": games,
            }
        )
    return {"total": total, "groups": groups}


@router.get("/games/{code}")
def game_detail(code: str):
    """单个游戏详情与缓存状态。"""
    meta = registry.get_game(code)
    if meta is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")
    return {"game": _game_with_status(meta)}


@router.get("/games/{code}/draws")
def game_draws(
    code: str,
    limit: int = Query(default=30, ge=1, le=200),
    refresh: bool = False,
):
    """某游戏最近开奖。

    缓存新鲜时直接返回缓存；缓存为空或过期时尝试抓取，失败则回退旧缓存。
    无适配器的游戏返回空列表与说明，不伪造数据。
    """
    meta = registry.get_game(code)
    if meta is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")

    if meta.support_level != "full":
        return _empty_draws_response(
            meta,
            "catalog_only",
            "该游戏暂只提供目录与支出记录",
        )

    adapter = registry.get_adapter(meta.code)
    if adapter is None:
        return _empty_draws_response(meta, "unavailable", "开奖数据接入中")

    payload = cache.load_cache(meta.code)
    if not refresh and cache.is_fresh_payload(payload, CACHE_TTL_SECONDS):
        return _draws_response(meta, payload, "ok", limit, None)

    try:
        merged, saved = _fetch_with_guard(meta, adapter, explicit=refresh)
    except RefreshBusy as exc:
        return _draws_response(meta, payload, "busy", limit, str(exc))
    except Exception as exc:  # 单个游戏抓取失败不影响其他游戏
        logger.warning("抓取 %s 开奖数据失败：%s", meta.code, exc)
        if payload.get("draws"):
            return _draws_response(
                meta,
                payload,
                "stale",
                limit,
                "数据源暂不可用，已显示上次缓存",
            )
        return _draws_response(
            meta,
            payload,
            "unavailable",
            limit,
            "数据源暂不可用，暂无缓存",
        )

    if saved is not None:
        payload = saved
    else:
        payload = dict(payload)
        payload["draws"] = merged
        payload["status"] = "ok"
    return _draws_response(meta, payload, "ok", limit, None)


@router.post("/games/{code}/refresh")
def refresh_game(code: str):
    """强制抓取最近 30 期并合并保存；失败时保留旧缓存，HTTP 仍返回 200。"""
    meta = registry.get_game(code)
    if meta is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")

    if meta.support_level != "full":
        return {
            "ok": False,
            "status": "catalog_only",
            "message": "该游戏暂只提供目录与支出记录",
            "updated_at": None,
            "latest_issue": None,
        }

    adapter = registry.get_adapter(meta.code)
    if adapter is None:
        return {
            "ok": False,
            "status": "unavailable",
            "message": "开奖数据接入中",
            "updated_at": None,
            "latest_issue": None,
        }

    old = cache.load_cache(meta.code)
    try:
        merged, saved = _fetch_with_guard(meta, adapter, explicit=True)
    except RefreshBusy as exc:
        latest = old["draws"][0] if old.get("draws") else None
        return {
            "ok": False,
            "status": "busy",
            "message": str(exc),
            "updated_at": old.get("updated_at"),
            "latest_issue": latest.get("issue") if latest else None,
        }
    except Exception as exc:
        logger.warning("刷新 %s 开奖数据失败：%s", meta.code, exc)
        latest = old["draws"][0] if old.get("draws") else None
        return {
            "ok": False,
            "status": "stale" if old.get("draws") else "unavailable",
            "message": (
                "数据源暂不可用，已保留上次缓存"
                if old.get("draws")
                else "数据源暂不可用，暂无缓存"
            ),
            "updated_at": old.get("updated_at"),
            "latest_issue": latest.get("issue") if latest else None,
        }

    latest = merged[0] if merged else None
    return {
        "ok": True,
        "status": "ok",
        "message": f"已更新，共 {len(merged)} 期开奖数据",
        "updated_at": (
            saved.get("updated_at") if saved is not None else old.get("updated_at")
        ),
        "latest_issue": latest.get("issue") if latest else None,
    }


@router.post("/check")
def check_ticket(body: CheckRequest):
    """用最新一期开奖核对号码/赛果；具体规则由各游戏适配器实现。"""
    meta = registry.get_game(body.game_code)
    if meta is None:
        raise HTTPException(status_code=404, detail="未找到该彩票游戏")

    if meta.support_level != "full":
        raise HTTPException(status_code=400, detail="该游戏暂不支持号码核对")

    adapter = registry.get_adapter(meta.code)
    if adapter is None:
        raise HTTPException(status_code=400, detail="该游戏暂不支持号码核对")

    payload = cache.load_cache(meta.code)
    if not payload.get("draws"):
        try:
            merged, saved = _fetch_with_guard(meta, adapter, explicit=False)
        except RefreshBusy as exc:
            raise HTTPException(
                status_code=503, detail="开奖数据正在更新，请稍后重试"
            ) from exc
        except Exception as exc:
            logger.warning("核对前抓取 %s 开奖数据失败：%s", meta.code, exc)
            merged, saved = [], None
        if saved is not None:
            payload = saved
        elif merged:
            payload = dict(payload)
            payload["draws"] = merged
            payload["status"] = "ok"

    if not payload.get("draws"):
        raise HTTPException(status_code=409, detail="暂无开奖数据，请稍后重试")

    draw = payload["draws"][0]
    try:
        result = adapter.check_ticket(body.payload, body.play_type, draw)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("核对 %s 号码失败", meta.code)
        raise HTTPException(
            status_code=500, detail="号码核对失败，请稍后重试"
        ) from exc

    return {
        "game_code": meta.code,
        "draw": {"issue": draw.get("issue"), "date": draw.get("date")},
        "result": result,
    }


def _draws_response(
    meta: GameMeta,
    payload: dict,
    status: str,
    limit: int,
    notice: str | None,
) -> dict:
    return {
        "game": _game_dict(meta),
        "status": status,
        "source": payload.get("source"),
        "updated_at": payload.get("updated_at"),
        "draws": (payload.get("draws") or [])[:limit],
        "notice": notice,
    }


def _empty_draws_response(meta: GameMeta, status: str, notice: str) -> dict:
    return {
        "game": _game_dict(meta),
        "status": status,
        "source": None,
        "updated_at": None,
        "draws": [],
        "notice": notice,
    }

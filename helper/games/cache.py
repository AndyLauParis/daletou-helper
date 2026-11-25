"""按游戏隔离的开奖缓存。

每个游戏一个 JSON 文件：`<CACHE_DIR>/<code>.json`。某个游戏读写失败只影响
自身，不会抛出到其他游戏或上层业务；写入采用临时文件 + `os.replace` 原子替换，
避免中断时破坏旧缓存。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import config

logger = logging.getLogger("helper.games.cache")

# 缓存目录可用环境变量 HELPER_CACHE_DIR 覆盖；测试可 monkeypatch 本模块的 CACHE_DIR。
CACHE_DIR = Path(
    os.environ.get("HELPER_CACHE_DIR")
    or (Path(config.PROJECT_ROOT) / "data" / "cache")
)

# 单个游戏最多保留的开奖期数
MAX_DRAWS = 200

# 默认缓存有效期：6 小时
DEFAULT_TTL_SECONDS = 6 * 60 * 60

VALID_STATUSES = ("ok", "stale", "empty", "unavailable")

_CODE_RE = re.compile(r"^[a-z0-9_]{1,20}$")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _empty_payload(code: str) -> dict:
    return {
        "code": code,
        "source": None,
        "updated_at": None,
        "status": "empty",
        "last_error": None,
        "draws": [],
    }


def cache_path(code: str) -> Path:
    """返回某游戏的缓存文件路径；游戏代码非法时抛出 ValueError。"""
    value = (code or "").strip().lower()
    if not _CODE_RE.fullmatch(value):
        raise ValueError("非法游戏代码")
    return Path(CACHE_DIR) / f"{value}.json"


def _clean_draws(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [
        dict(item)
        for item in value
        if isinstance(item, dict) and str(item.get("issue") or "").strip()
    ]


def load_cache(code: str) -> dict:
    """读取缓存；文件不存在、损坏或格式异常时返回空缓存，不抛异常。"""
    payload = _empty_payload(code)
    try:
        path = cache_path(code)
    except ValueError as exc:
        logger.warning("读取开奖缓存失败：%s", exc)
        payload["last_error"] = str(exc)
        return payload

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return payload
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 %s 开奖缓存失败：%s", code, exc)
        payload["last_error"] = "缓存文件损坏或不可读"
        return payload

    if not isinstance(data, dict):
        payload["last_error"] = "缓存文件格式异常"
        return payload

    draws = _clean_draws(data.get("draws"))
    status = data.get("status")
    if status not in VALID_STATUSES:
        status = "empty"
    if draws and status == "empty":
        status = "ok"
    payload.update(
        {
            "source": data.get("source"),
            "updated_at": data.get("updated_at"),
            "status": status,
            "last_error": data.get("last_error"),
            "draws": draws,
        }
    )
    return payload


def save_cache(
    code: str,
    draws: list[dict],
    source: str | None,
    status: str = "ok",
    error: str | None = None,
) -> dict | None:
    """原子写入缓存，返回写入的载荷；写入失败时保留旧文件并返回 None。"""
    cleaned = merge_draws([], draws)
    if status not in VALID_STATUSES:
        status = "ok"
    if not cleaned and status in ("ok", "stale"):
        status = "empty"

    payload = {
        "code": code,
        "source": source,
        "updated_at": _now_iso(),
        "status": status,
        "last_error": error,
        "draws": cleaned,
    }

    tmp_path: Path | None = None
    try:
        path = cache_path(code)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp_path, path)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("写入 %s 开奖缓存失败：%s", code, exc)
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return None
    return payload


def merge_draws(old: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """按期号去重（新数据优先），按 date/issue 倒序，并限制最多 200 期。"""
    by_issue: dict[str, dict] = {}
    for draw in list(old or []):
        if isinstance(draw, dict) and str(draw.get("issue") or "").strip():
            by_issue[str(draw["issue"])] = dict(draw)
    for draw in list(new or []):
        if isinstance(draw, dict) and str(draw.get("issue") or "").strip():
            by_issue[str(draw["issue"])] = dict(draw)

    ordered = sorted(
        by_issue.values(),
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("issue") or ""),
        ),
        reverse=True,
    )
    return ordered[:MAX_DRAWS]


def is_fresh(meta, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    """判断某游戏的缓存是否仍在有效期内且有数据。"""
    payload = load_cache(meta.code)
    if not payload.get("draws"):
        return False
    updated_at = payload.get("updated_at")
    if not updated_at:
        return False
    try:
        stamp = datetime.fromisoformat(updated_at)
    except (TypeError, ValueError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.now().astimezone().tzinfo)
    age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
    return age <= ttl_seconds


def status_for(code: str) -> dict:
    """目录 API 使用的轻量状态（不返回完整开奖列表）。"""
    payload = load_cache(code)
    draws = payload.get("draws") or []
    latest = draws[0] if draws else None
    return {
        "code": code,
        "has_data": bool(draws),
        "draw_count": len(draws),
        "latest_issue": latest.get("issue") if latest else None,
        "latest_date": latest.get("date") if latest else None,
        "updated_at": payload.get("updated_at"),
        "status": payload.get("status") or "empty",
    }

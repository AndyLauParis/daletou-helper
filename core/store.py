"""大乐透历史开奖数据抓取、解析与本地缓存。

数据源：https://datachart.500.com/dlt/history/newinc/history.php
缓存：data/dlt_history.json（按期号去重，按日期倒序）
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import requests

from .constants import POOL_THRESHOLD

BASE_URL = "https://datachart.500.com/dlt/history/newinc/history.php"
SOURCE_URL = f"{BASE_URL}?start=07001&end={{end}}"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / "data" / "dlt_history.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 30
RETRIES = 2

_ROW_RE = re.compile(r'<tr[^>]*class="t_tr1"[^>]*>.*?</tr>', re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ISSUE_RE = re.compile(r"\d{5}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUM_RE = re.compile(r"\d[\d,]*")

_lock = threading.Lock()
_cache: dict | None = None


class DataFetchError(RuntimeError):
    """抓取或解析历史数据失败。"""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _current_end() -> str:
    """当前年份 + 999，例如 2026 -> 26999。"""
    return f"{datetime.now().year % 100:02d}999"


def _clean_cell(raw: str) -> str:
    return _TAG_RE.sub("", raw).replace("\xa0", " ").strip()


def parse_history_html(html: str) -> list[dict]:
    """从 500.com 历史页面 HTML 中解析开奖记录。

    按期号正则（5 位数字）与日期正则（YYYY-MM-DD）定位关键单元格，
    不依赖固定下标，避免页面列顺序调整导致解析失败。
    """
    draws: list[dict] = []
    seen: set[str] = set()
    for row_html in _ROW_RE.findall(html):
        cells = [_clean_cell(c) for c in _TD_RE.findall(row_html)]
        issue_idx = next(
            (i for i, c in enumerate(cells) if _ISSUE_RE.fullmatch(c)), None
        )
        date_idx = next(
            (i for i, c in enumerate(cells) if _DATE_RE.fullmatch(c)), None
        )
        if issue_idx is None or date_idx is None or issue_idx >= date_idx:
            continue
        numbers = [
            int(c.replace(",", ""))
            for c in cells[issue_idx + 1 : date_idx]
            if _NUM_RE.fullmatch(c)
        ]
        if len(numbers) < 11:
            continue
        front = numbers[0:5]
        back = numbers[5:7]
        if len(set(front)) != 5 or not all(1 <= n <= 35 for n in front):
            continue
        if len(set(back)) != 2 or not all(1 <= n <= 12 for n in back):
            continue
        pool, first_count, first_amount, second_count, second_amount, sales = (
            numbers[7:13]
        )
        issue = cells[issue_idx]
        if issue in seen:
            continue
        seen.add(issue)
        draws.append(
            {
                "issue": issue,
                "date": cells[date_idx],
                "front": sorted(front),
                "back": sorted(back),
                "pool": pool,
                "sales": sales,
                "first_prize_count": first_count,
                "first_prize_amount": first_amount,
                "second_prize_count": second_count,
                "second_prize_amount": second_amount,
            }
        )
    if not draws:
        raise DataFetchError("数据源页面结构异常：未解析到任何开奖记录")
    return sort_draws(draws)


def sort_draws(draws: list[dict]) -> list[dict]:
    """按日期倒序、同期号倒序。"""
    return sorted(draws, key=lambda d: (d["date"], d["issue"]), reverse=True)


def dedupe_draws(draws: list[dict]) -> list[dict]:
    """按期号去重（后出现的覆盖先出现的），并排序。"""
    by_issue: dict[str, dict] = {}
    for draw in draws:
        by_issue[draw["issue"]] = draw
    return sort_draws(list(by_issue.values()))


def fetch_draws() -> tuple[list[dict], str]:
    """抓取全量历史数据，返回 (draws, source_url)。失败重试 2 次后抛异常。"""
    url = SOURCE_URL.format(end=_current_end())
    last_error: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            html = resp.content.decode("utf-8", errors="replace")
            return parse_history_html(html), url
        except Exception as exc:  # 网络、状态码、解析异常统一重试
            last_error = exc
    raise DataFetchError(f"抓取历史数据失败：{last_error}")


def _read_cache_file() -> dict | None:
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("draws"):
        return None
    return payload


def _write_cache_file(payload: dict) -> None:
    """原子写入缓存，避免中断时破坏旧文件。"""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CACHE_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp_path, CACHE_PATH)


def _fallback_payload() -> dict:
    from .fallback_data import FALLBACK_DRAWS

    draws = dedupe_draws([dict(d) for d in FALLBACK_DRAWS])
    return {
        "source": "内置兜底样例（500.com 最近 30 期）",
        "fetched_at": _now_iso(),
        "offline": True,
        "draws": draws,
    }


def _load_cache() -> dict:
    """加载缓存到内存；无缓存时抓取或使用兜底样例。须在锁内调用。"""
    global _cache
    if _cache is not None:
        return _cache
    payload = _read_cache_file()
    if payload is not None:
        payload["draws"] = dedupe_draws(payload["draws"])
        payload.setdefault("offline", False)
        payload.setdefault("source", SOURCE_URL.format(end=_current_end()))
        payload.setdefault("fetched_at", _now_iso())
        _cache = payload
        return _cache
    try:
        draws, url = fetch_draws()
        payload = {
            "source": url,
            "fetched_at": _now_iso(),
            "offline": False,
            "draws": draws,
        }
    except Exception:
        payload = _fallback_payload()
    _write_cache_file(payload)
    _cache = payload
    return _cache


def ensure_data() -> dict:
    """确保数据可用：读缓存 -> 抓取 -> 兜底样例。返回状态摘要。"""
    with _lock:
        _load_cache()
    return get_status()


def refresh() -> dict:
    """抓取全量数据并与旧缓存按 issue 合并；失败时抛异常且不破坏旧缓存。"""
    global _cache
    draws, url = fetch_draws()  # 锁外抓取，失败直接抛出
    fetched_at = _now_iso()
    with _lock:
        old_payload = _read_cache_file() or _cache or {"draws": []}
        old_draws = old_payload.get("draws", [])
        old_issues = {d["issue"] for d in old_draws}
        merged = dedupe_draws(list(old_draws) + list(draws))
        added = len({d["issue"] for d in draws} - old_issues)
        payload = {
            "source": url,
            "fetched_at": fetched_at,
            "offline": False,
            "draws": merged,
        }
        _write_cache_file(payload)
        _cache = payload
    latest = merged[0] if merged else None
    return {
        "added": added,
        "total": len(merged),
        "latest_issue": latest["issue"] if latest else None,
        "latest_date": latest["date"] if latest else None,
        "fetched_at": fetched_at,
        "source": url,
        "offline": False,
    }


def get_draws() -> list[dict]:
    """返回按日期倒序的开奖列表（副本）。"""
    with _lock:
        payload = _load_cache()
        return [dict(d) for d in payload["draws"]]


def _pool_mode(pool: int | float | None) -> str:
    return "high" if (pool or 0) >= POOL_THRESHOLD else "normal"


def get_status() -> dict:
    """数据源状态摘要。"""
    with _lock:
        payload = _load_cache()
        draws = payload["draws"]
    latest = draws[0] if draws else None
    return {
        "count": len(draws),
        "latest_issue": latest["issue"] if latest else None,
        "latest_date": latest["date"] if latest else None,
        "latest_pool": latest["pool"] if latest else None,
        "fetched_at": payload.get("fetched_at"),
        "source": payload.get("source"),
        "offline": bool(payload.get("offline", False)),
        "pool_mode": _pool_mode(latest["pool"] if latest else None),
    }

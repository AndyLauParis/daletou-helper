"""双色球适配器。

数据源：中国福利彩票发行管理中心官方开奖公告接口
`https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=ssq`
返回字段：`code`（期号）、`date`（形如 2026-11-22(日)）、`red`（逗号分隔）、`blue`。

本模块只做开奖数据解析、号码校验和奖级核对，不预测、不推荐、不代购、不支付、
不出票、不承诺中奖；奖级与奖金以官方公告为准。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import _datachart500

SOURCE_NAME = "中国福利彩票官网"
API_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
TIMEOUT = 10
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.cwl.gov.cn/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

_RED_MAX = 33
_BLUE_MAX = 16
_RED_COUNT = 6
_BLUE_COUNT = 1

# 奖级表（中国福利彩票“双色球”游戏规则）：
# 6+1 一等奖、6+0 二等奖、5+1 三等奖、5+0/4+1 四等奖、
# 4+0/3+1 五等奖、2+1/1+1/0+1 六等奖。
# 一、二等奖为浮动奖金；三至六等奖为固定奖金。金额均以官方公告为准。
_PRIZE_TABLE: dict[tuple[int, bool], tuple[str, int | None]] = {
    (6, True): ("一等奖", None),
    (6, False): ("二等奖", None),
    (5, True): ("三等奖", 3000),
    (5, False): ("四等奖", 200),
    (4, True): ("四等奖", 200),
    (4, False): ("五等奖", 10),
    (3, True): ("五等奖", 10),
    (2, True): ("六等奖", 5),
    (1, True): ("六等奖", 5),
    (0, True): ("六等奖", 5),
}

_NOTE = "本工具仅作兑奖参考，不代购、不支付、不出票；奖级与奖金以官方公告为准。"


def _build_url(limit: int) -> str:
    count = max(1, min(int(limit or 30), 100))
    return f"{API_URL}?name=ssq&issueCount={count}"


def _request_json(url: str) -> dict:
    """发起一次 HTTP 请求并解析 JSON；测试通过 monkeypatch 本函数隔离网络。"""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("双色球开奖数据源返回格式异常")
    return data


def _split_numbers(value) -> list[int]:
    """把 "01,02"、[1, 2]、8 等写法统一解析为整数列表。"""
    if isinstance(value, bool):
        raise ValueError("号码字段格式异常")
    if isinstance(value, (int, float)):
        return [int(value)]
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        text = str(value or "").replace("，", ",").replace("、", " ")
        parts = [part for part in re.split(r"[\s,]+", text) if part]
    numbers: list[int] = []
    for part in parts:
        try:
            numbers.append(int(str(part).strip()))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"号码 {part!r} 不是有效数字") from exc
    return numbers


def _parse_date(value) -> str:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value or "").strip())
    if match is None:
        raise ValueError("双色球开奖日期字段异常")
    return match.group(1)


def _fetch_official(limit: int = 30) -> list[dict]:
    """抓取最近若干期开奖，按日期、期号倒序返回；字段缺失时抛异常。"""
    data = _request_json(_build_url(limit))
    if data.get("state") != 0:
        raise ValueError("双色球开奖数据源返回异常状态")
    items = data.get("result")
    if not isinstance(items, list):
        raise ValueError("双色球开奖数据源缺少 result 列表")

    draws: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("双色球开奖记录格式异常")
        issue = str(item.get("code") or "").strip()
        if not issue:
            raise ValueError("双色球开奖记录缺少期号")
        try:
            red = _split_numbers(item.get("red"))
            blue = _split_numbers(item.get("blue"))
        except ValueError as exc:
            raise ValueError(f"双色球第 {issue} 期开奖号码不完整") from exc
        if len(red) != _RED_COUNT or len(blue) != _BLUE_COUNT:
            raise ValueError(f"双色球第 {issue} 期开奖号码不完整")
        if len(set(red)) != _RED_COUNT or any(
            number < 1 or number > _RED_MAX for number in red
        ):
            raise ValueError(f"双色球第 {issue} 期红球号码异常")
        if not 1 <= blue[0] <= _BLUE_MAX:
            raise ValueError(f"双色球第 {issue} 期蓝球号码异常")

        draws.append(
            {
                "issue": issue,
                "date": _parse_date(item.get("date")),
                "numbers": {"red": sorted(red), "blue": blue},
                "extra": {"week": str(item.get("week") or "")},
            }
        )

    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws


def _fetch_fallback(limit: int = 30) -> list[dict]:
    draws: list[dict] = []
    for cells in _datachart500.fetch_rows("ssq"):
        found = _datachart500.row_issue(cells, r"\d{5}")
        if found is None:
            continue
        index, raw_issue = found
        date = _datachart500.row_date(cells)
        numbers: list[int] = []
        for cell in cells[index + 1 :]:
            numbers.extend(int(token) for token in re.findall(r"(?<!\d)\d{2}(?!\d)", cell))
            if len(numbers) >= _RED_COUNT + _BLUE_COUNT:
                break
        if date is None or len(numbers) < _RED_COUNT + _BLUE_COUNT:
            continue
        red = numbers[:_RED_COUNT]
        blue = numbers[_RED_COUNT]
        if len(set(red)) != _RED_COUNT or any(
            number < 1 or number > _RED_MAX for number in red
        ):
            continue
        if not 1 <= blue <= _BLUE_MAX:
            continue
        draws.append(
            {
                "issue": _datachart500.expand_issue(raw_issue),
                "date": date,
                "numbers": {"red": sorted(red), "blue": [blue]},
                "extra": {"week": ""},
            }
        )
        if len(draws) >= limit:
            break
    if not draws:
        raise ValueError("500.com 备用源未返回可用的双色球数据")
    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws


def fetch_draws(limit: int = 30) -> list[dict]:
    try:
        return _fetch_official(limit)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        try:
            return _fetch_fallback(limit)
        except Exception as fallback_exc:
            raise ValueError(f"双色球开奖数据源不可用，备用源也失败：{fallback_exc}") from exc


def _parse_text(text: str) -> tuple[list[int], list[int]]:
    parts = [part.strip() for part in str(text).replace("＋", "+").split("+")]
    if len(parts) != 2:
        raise ValueError(
            "号码格式应为“红球 + 蓝球”，例如 01 02 03 04 05 06 + 07"
        )
    return _split_numbers(parts[0]), _split_numbers(parts[1])


def _extract_ticket(payload) -> tuple[list[int], list[int]]:
    if isinstance(payload, str):
        return _parse_text(payload)
    if isinstance(payload, dict):
        if "red" in payload or "blue" in payload:
            return (
                _split_numbers(payload.get("red")),
                _split_numbers(payload.get("blue")),
            )
        for key in ("ticket", "text", "numbers"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _parse_text(value)
            if isinstance(value, (list, tuple)) and len(value) == 2:
                return _split_numbers(value[0]), _split_numbers(value[1])
    raise ValueError("请提供红球和蓝球号码，例如 01 02 03 04 05 06 + 07")


def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
    """校验双色球号码：红球 6 个不重复（1-33）、蓝球 1 个（1-16）。"""
    try:
        red, blue = _extract_ticket(payload)
    except ValueError as exc:
        return {"ok": False, "normalized": {}, "errors": [str(exc)]}

    errors: list[str] = []
    if len(red) != _RED_COUNT:
        errors.append("红球必须选择 6 个号码")
    if len(set(red)) != len(red):
        errors.append("红球号码不能重复")
    if any(number < 1 or number > _RED_MAX for number in red):
        errors.append("红球号码必须在 1-33 之间")
    if len(blue) != _BLUE_COUNT:
        errors.append("蓝球必须选择 1 个号码")
    elif not 1 <= blue[0] <= _BLUE_MAX:
        errors.append("蓝球号码必须在 1-16 之间")

    normalized = {"red": sorted(red), "blue": sorted(blue)}
    return {"ok": not errors, "normalized": normalized, "errors": errors}


def _draw_numbers(draw: dict) -> tuple[list[int], list[int]]:
    numbers = (draw or {}).get("numbers") if isinstance(draw, dict) else None
    if not isinstance(numbers, dict):
        raise ValueError("双色球开奖数据缺少号码")
    try:
        red = _split_numbers(numbers.get("red"))
        blue = _split_numbers(numbers.get("blue"))
    except ValueError as exc:
        raise ValueError("双色球开奖号码格式异常") from exc
    if len(red) != _RED_COUNT or len(blue) != _BLUE_COUNT:
        raise ValueError("双色球开奖号码不完整")
    return red, blue


def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
    """按官方 6 个奖级核对双色球号码。"""
    validation = validate_ticket(payload, play_type)
    if not validation["ok"]:
        return {
            "ok": False,
            "hit": False,
            "prize_level": None,
            "detail": {"errors": validation["errors"]},
            "message": "号码格式不合法：" + "；".join(validation["errors"]),
        }

    normalized = validation["normalized"]
    red, blue = _draw_numbers(draw)
    red_hits = len(set(normalized["red"]) & set(red))
    blue_hit = normalized["blue"][0] == blue[0]

    prize_level, prize_amount = _PRIZE_TABLE.get(
        (red_hits, blue_hit), (None, None)
    )
    hit = prize_level is not None

    if hit:
        message = (
            f"命中红球 {red_hits} 个、蓝球{'命中' if blue_hit else '未命中'}；"
            f"对应{prize_level}，参考奖金"
            f"{'以官方公告为准' if prize_amount is None else f'{prize_amount} 元'}。"
            + _NOTE
        )
    else:
        message = (
            f"命中红球 {red_hits} 个、蓝球{'命中' if blue_hit else '未命中'}；"
            "未达到官方奖级条件。" + _NOTE
        )

    return {
        "ok": True,
        "hit": hit,
        "prize_level": prize_level,
        "detail": {
            "red_hits": red_hits,
            "blue_hit": blue_hit,
            "prize_amount": prize_amount,
            "prize_note": (
                "一、二等奖为浮动奖金"
                if prize_level in ("一等奖", "二等奖")
                else "固定奖金" if prize_level else ""
            ),
        },
        "message": message,
    }

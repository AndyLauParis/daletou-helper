"""七乐彩适配器。

数据源：中国福利彩票发行管理中心官方开奖公告接口
`https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=qlc`
返回字段：`code`（期号）、`date`、`red`（7 个基本号码，逗号分隔）、
`blue`（1 个特别号码）。

奖级（中国福利彩票“七乐彩”游戏规则）：
7 个基本号 -> 一等奖；6 个基本号 + 特别号 -> 二等奖；6 个基本号 -> 三等奖；
5 个基本号 + 特别号 -> 四等奖（200 元）；5 个基本号 -> 五等奖（50 元）；
4 个基本号 + 特别号 -> 六等奖（10 元）；4 个基本号 -> 七等奖（5 元）。
一至三等奖为浮动奖金，以官方公告为准。本模块只做核对，不预测、不推荐、
不代购、不支付、不出票。
"""

from __future__ import annotations

import json
import re
import urllib.request

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

_BASIC_COUNT = 7
_NUMBER_MAX = 30

# 奖级表：键为 (基本号命中个数, 是否命中特别号)，值为 (奖级, 固定奖金或 None)。
_PRIZE_TABLE: dict[tuple[int, bool], tuple[str, int | None]] = {
    (7, False): ("一等奖", None),
    (6, True): ("二等奖", None),
    (6, False): ("三等奖", None),
    (5, True): ("四等奖", 200),
    (5, False): ("五等奖", 50),
    (4, True): ("六等奖", 10),
    (4, False): ("七等奖", 5),
}

_NOTE = "本工具仅作兑奖参考，不代购、不支付、不出票；奖金以官方公告为准。"


def _build_url(limit: int) -> str:
    count = max(1, min(int(limit or 30), 100))
    return f"{API_URL}?name=qlc&issueCount={count}"


def _request_json(url: str) -> dict:
    """发起一次 HTTP 请求并解析 JSON；测试通过 monkeypatch 本函数隔离网络。"""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("七乐彩开奖数据源返回格式异常")
    return data


def _split_numbers(value) -> list[int]:
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
        raise ValueError("七乐彩开奖日期字段异常")
    return match.group(1)


def fetch_draws(limit: int = 30) -> list[dict]:
    """抓取最近若干期开奖，按日期、期号倒序返回；字段缺失时抛异常。"""
    data = _request_json(_build_url(limit))
    if data.get("state") != 0:
        raise ValueError("七乐彩开奖数据源返回异常状态")
    items = data.get("result")
    if not isinstance(items, list):
        raise ValueError("七乐彩开奖数据源缺少 result 列表")

    draws: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("七乐彩开奖记录格式异常")
        issue = str(item.get("code") or "").strip()
        if not issue:
            raise ValueError("七乐彩开奖记录缺少期号")
        try:
            basic = _split_numbers(item.get("red"))
            special = _split_numbers(item.get("blue"))
        except ValueError as exc:
            raise ValueError(f"七乐彩第 {issue} 期开奖号码不完整") from exc
        if len(basic) != _BASIC_COUNT or len(special) != 1:
            raise ValueError(f"七乐彩第 {issue} 期开奖号码不完整")
        if len(set(basic)) != _BASIC_COUNT or any(
            number < 1 or number > _NUMBER_MAX for number in basic
        ):
            raise ValueError(f"七乐彩第 {issue} 期基本号码异常")
        if not 1 <= special[0] <= _NUMBER_MAX:
            raise ValueError(f"七乐彩第 {issue} 期特别号码异常")

        draws.append(
            {
                "issue": issue,
                "date": _parse_date(item.get("date")),
                "numbers": {"basic": sorted(basic), "special": special[0]},
                "extra": {"week": str(item.get("week") or "")},
            }
        )

    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws


def _extract_ticket(payload) -> list[int]:
    if isinstance(payload, dict):
        for key in ("basic", "numbers", "picks"):
            if key in payload:
                return _split_numbers(payload.get(key))
        for key in ("ticket", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _split_numbers(value)
        raise ValueError("请提供 7 个基本号码，例如 01 02 03 04 05 06 07")
    return _split_numbers(payload)


def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
    """校验七乐彩投注：7 个不重复号码，范围 1-30。"""
    try:
        basic = _extract_ticket(payload)
    except ValueError as exc:
        return {"ok": False, "normalized": {}, "errors": [str(exc)]}

    errors: list[str] = []
    if len(basic) != _BASIC_COUNT:
        errors.append("必须选择 7 个基本号码")
    if len(set(basic)) != len(basic):
        errors.append("基本号码不能重复")
    if any(number < 1 or number > _NUMBER_MAX for number in basic):
        errors.append("基本号码必须在 1-30 之间")

    normalized = {"basic": sorted(basic)}
    return {"ok": not errors, "normalized": normalized, "errors": errors}


def _draw_numbers(draw: dict) -> tuple[list[int], int]:
    numbers = (draw or {}).get("numbers") if isinstance(draw, dict) else None
    if not isinstance(numbers, dict):
        raise ValueError("七乐彩开奖数据缺少号码")
    try:
        basic = _split_numbers(numbers.get("basic"))
        special = _split_numbers(numbers.get("special"))
    except ValueError as exc:
        raise ValueError("七乐彩开奖号码格式异常") from exc
    if len(basic) != _BASIC_COUNT or len(special) != 1:
        raise ValueError("七乐彩开奖号码不完整")
    return basic, special[0]


def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
    """按官方 7 个奖级核对七乐彩号码（基本号 + 特别号）。"""
    validation = validate_ticket(payload, play_type)
    if not validation["ok"]:
        return {
            "ok": False,
            "hit": False,
            "prize_level": None,
            "detail": {"errors": validation["errors"]},
            "message": "号码格式不合法：" + "；".join(validation["errors"]),
        }

    bet = set(validation["normalized"]["basic"])
    basic, special = _draw_numbers(draw)
    basic_hits = len(bet & set(basic))
    special_hit = special in bet

    prize_level, prize_amount = _PRIZE_TABLE.get(
        (basic_hits, special_hit), (None, None)
    )
    hit = prize_level is not None

    if hit:
        message = (
            f"命中基本号 {basic_hits} 个，"
            f"特别号{'命中' if special_hit else '未命中'}；"
            f"对应{prize_level}，参考奖金"
            f"{'以官方公告为准' if prize_amount is None else f'{prize_amount} 元'}。"
            + _NOTE
        )
    else:
        message = (
            f"命中基本号 {basic_hits} 个，"
            f"特别号{'命中' if special_hit else '未命中'}；"
            "未达到官方奖级条件。" + _NOTE
        )

    return {
        "ok": True,
        "hit": hit,
        "prize_level": prize_level,
        "detail": {
            "basic_hits": basic_hits,
            "special_hit": special_hit,
            "prize_amount": prize_amount,
            "prize_note": (
                "一至三等奖为浮动奖金"
                if prize_level in ("一等奖", "二等奖", "三等奖")
                else "固定奖金" if prize_level else ""
            ),
        },
        "message": message,
    }

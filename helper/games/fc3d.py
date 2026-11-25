"""福彩3D适配器。

数据源：中国福利彩票发行管理中心官方开奖公告接口
`https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=3d`
返回字段：`code`（期号）、`date`、`red`（逗号分隔的 3 位数字，按百/十/个位顺序）。

玩法：`zhixuan` 直选（固定奖金 1040 元）、`zu3` 组选3（346 元）、
`zu6` 组选6（173 元），默认直选。奖金以官方公告为准；本模块只做核对，
不预测、不推荐、不代购、不支付、不出票。
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

_DIGIT_COUNT = 3

# 固定奖金（中国福利彩票“3D”游戏规则），以官方公告为准。
_PRIZES: dict[str, tuple[str, int]] = {
    "zhixuan": ("直选", 1040),
    "zu3": ("组选3", 346),
    "zu6": ("组选6", 173),
}

_PLAY_ALIASES: dict[str, str] = {
    "zhixuan": "zhixuan",
    "直选": "zhixuan",
    "单选": "zhixuan",
    "zu3": "zu3",
    "组选3": "zu3",
    "组三": "zu3",
    "zu6": "zu6",
    "组选6": "zu6",
    "组六": "zu6",
}

_NOTE = "本工具仅作兑奖参考，不代购、不支付、不出票；奖金以官方公告为准。"


def _build_url(limit: int) -> str:
    count = max(1, min(int(limit or 30), 100))
    return f"{API_URL}?name=3d&issueCount={count}"


def _request_json(url: str) -> dict:
    """发起一次 HTTP 请求并解析 JSON；测试通过 monkeypatch 本函数隔离网络。"""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("福彩3D开奖数据源返回格式异常")
    return data


def _parse_date(value) -> str:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value or "").strip())
    if match is None:
        raise ValueError("福彩3D开奖日期字段异常")
    return match.group(1)


def _parse_digits(value) -> list[int]:
    """把 "3,4,6"、[3, 4, 6]、"346" 统一解析为 3 个整数。"""
    if isinstance(value, bool):
        raise ValueError("福彩3D号码字段格式异常")
    if isinstance(value, (int, float)):
        parts = [str(int(value))]
    elif isinstance(value, (list, tuple)):
        parts = [str(part) for part in value]
    else:
        text = str(value or "").replace("，", ",").replace("、", " ")
        parts = [part for part in re.split(r"[\s,]+", text) if part]

    if len(parts) == 1 and len(parts[0]) == _DIGIT_COUNT and parts[0].isdigit():
        parts = list(parts[0])
    if len(parts) != _DIGIT_COUNT:
        raise ValueError("福彩3D号码应为 3 位数字，例如 3 4 6")

    digits: list[int] = []
    for part in parts:
        text = str(part).strip()
        if not text.isdigit():
            raise ValueError("福彩3D号码必须是 0-9 的数字")
        digits.append(int(text))
    return digits


def _normalise_play_type(value) -> str:
    if value is None or str(value).strip() == "":
        return "zhixuan"
    key = str(value).strip().lower()
    if key not in _PLAY_ALIASES:
        raise ValueError("不支持的玩法，仅支持直选、组选3、组选6")
    return _PLAY_ALIASES[key]


def fetch_draws(limit: int = 30) -> list[dict]:
    """抓取最近若干期开奖，按日期、期号倒序返回；字段缺失时抛异常。"""
    data = _request_json(_build_url(limit))
    if data.get("state") != 0:
        raise ValueError("福彩3D开奖数据源返回异常状态")
    items = data.get("result")
    if not isinstance(items, list):
        raise ValueError("福彩3D开奖数据源缺少 result 列表")

    draws: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("福彩3D开奖记录格式异常")
        issue = str(item.get("code") or "").strip()
        if not issue:
            raise ValueError("福彩3D开奖记录缺少期号")
        try:
            digits = _parse_digits(item.get("red"))
        except ValueError as exc:
            raise ValueError(f"福彩3D第 {issue} 期开奖号码不完整") from exc

        draws.append(
            {
                "issue": issue,
                "date": _parse_date(item.get("date")),
                "numbers": {"digits": digits},
                "extra": {"week": str(item.get("week") or "")},
            }
        )

    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws


def _extract_digits(payload) -> list[int]:
    if isinstance(payload, dict):
        for key in ("digits", "numbers"):
            if key in payload:
                return _parse_digits(payload.get(key))
        raise ValueError("请提供 3 位开奖/投注数字，例如 3 4 6")
    return _parse_digits(payload)


def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
    """校验福彩3D投注：3 位数字 0-9，并按玩法检查组合形态。"""
    try:
        play = _normalise_play_type(play_type)
        digits = _extract_digits(payload)
    except ValueError as exc:
        return {"ok": False, "normalized": {}, "errors": [str(exc)]}

    errors: list[str] = []
    if any(digit < 0 or digit > 9 for digit in digits):
        errors.append("数字必须在 0-9 之间")

    unique = len(set(digits))
    if play == "zu3" and unique != 2:
        errors.append("组选3要求 3 位数字中恰好有两位相同")
    if play == "zu6" and unique != 3:
        errors.append("组选6要求 3 位数字互不相同")

    normalized = {"digits": digits, "play_type": play}
    return {"ok": not errors, "normalized": normalized, "errors": errors}


def _draw_digits(draw: dict) -> list[int]:
    numbers = (draw or {}).get("numbers") if isinstance(draw, dict) else None
    if not isinstance(numbers, dict):
        raise ValueError("福彩3D开奖数据缺少号码")
    try:
        return _parse_digits(numbers.get("digits"))
    except ValueError as exc:
        raise ValueError("福彩3D开奖号码格式异常") from exc


def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
    """按所选玩法核对福彩3D：直选逐位、组选按多重集比较。"""
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
    bet = normalized["digits"]
    play = normalized["play_type"]
    draw_digits = _draw_digits(draw)

    if play == "zhixuan":
        hit = bet == draw_digits
    elif play == "zu3":
        hit = len(set(draw_digits)) == 2 and sorted(bet) == sorted(draw_digits)
    else:
        hit = len(set(draw_digits)) == 3 and sorted(bet) == sorted(draw_digits)

    label, amount = _PRIZES[play]
    if hit:
        message = (
            f"按{label}核对命中，固定奖金 {amount} 元。" + _NOTE
        )
    else:
        message = f"按{label}核对未中奖。" + _NOTE

    return {
        "ok": True,
        "hit": hit,
        "prize_level": label if hit else None,
        "detail": {
            "play_type": play,
            "digits": bet,
            "draw_digits": draw_digits,
            "prize_amount": amount if hit else None,
        },
        "message": message,
    }

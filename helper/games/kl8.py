"""快乐8适配器。

数据源：中国福利彩票发行管理中心官方开奖公告接口
`https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=kl8`
返回字段：`code`（期号）、`date`、`red`（20 个开奖号码，逗号分隔）。

投注：从 1-80 中选 1-10 个号码，`play_type` 为 `select1`…`select10`，
也可省略并由号码个数推断。奖级表来源：中国福彩网《中国福利彩票快乐8游戏规则》
（2025-12-29 修订）奖金对照表，选十中十为浮动奖、封顶 500 万元，选九中九
封顶 25 万元，其余为固定奖金。所有奖金以官方公告为准；本模块只做核对，
不预测、不推荐、不代购、不支付、不出票。
"""

from __future__ import annotations

import json
import re
import urllib.error
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

_DRAW_COUNT = 20
_NUMBER_MAX = 80
_MIN_PICKS = 1
_MAX_PICKS = 10

# 官方奖金对照表：{选号个数: {命中个数: 单注奖金（元）}}
# 来源：https://www.cwl.gov.cn/fcpz/yxjs/kl8/ 《中国福利彩票快乐8游戏规则》。
_PRIZE_TABLE: dict[int, dict[int, float]] = {
    10: {10: 5000000, 9: 8000, 8: 720, 7: 80, 6: 5, 5: 3, 0: 2},
    9: {9: 250000, 8: 2000, 7: 225, 6: 22, 5: 5, 4: 3, 0: 2},
    8: {8: 50000, 7: 800, 6: 80, 5: 10, 4: 3, 0: 2},
    7: {7: 8500, 6: 300, 5: 30, 4: 4, 0: 2},
    6: {6: 2880, 5: 30, 4: 10, 3: 3},
    5: {5: 1000, 4: 20, 3: 3},
    4: {4: 93, 3: 5, 2: 3},
    3: {3: 52, 2: 3},
    2: {2: 19},
    1: {1: 4.5},
}

# 选十中十、选九中九为浮动奖，表中为封顶金额。
_CAPPED: dict[tuple[int, int], str] = {
    (10, 10): "最高 500 万元（封顶）",
    (9, 9): "最高 25 万元（封顶）",
}

_CN_NUMBERS = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}

_NOTE = "本工具仅作兑奖参考，不代购、不支付、不出票；奖金以官方公告为准。"


def _build_url(limit: int) -> str:
    count = max(1, min(int(limit or 30), 100))
    return f"{API_URL}?name=kl8&issueCount={count}"


KL8_PAGE_URL = "https://kaijiang.500.com/kl8.shtml"
KL8_XML_URL = "https://kaijiang.500.com/static/info/kaijiang/xml/kl8/{issue}.xml"
_ISSUE_LINK_RE = re.compile(r"/shtml/kl8/(\d{7})\.shtml")


def _request_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://kaijiang.500.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("gb18030", errors="replace")


def _parse_500_xml(text: str) -> dict | None:
    def tag(name: str) -> str:
        match = re.search(rf"<{name}>([^<]+)</{name}>", text)
        return match.group(1).strip() if match else ""

    issue = tag("PeriodicalNum") or tag("PeriodicalNO")
    result = tag("Result")
    opened_at = tag("ResultTime") or tag("ResultDate")
    numbers = [int(part) for part in re.split(r"[,\s]+", result) if part.isdigit()]
    date_match = re.match(r"\d{4}-\d{2}-\d{2}", opened_at)
    if (
        not issue
        or len(numbers) != _DRAW_COUNT
        or len(set(numbers)) != _DRAW_COUNT
        or date_match is None
    ):
        return None
    if any(number < 1 or number > _NUMBER_MAX for number in numbers):
        return None
    return {
        "issue": issue,
        "date": date_match.group(0),
        "numbers": {"draw": sorted(numbers)},
        "extra": {"week": ""},
    }


def _fetch_fallback(limit: int = 30) -> list[dict]:
    page = _request_text(KL8_PAGE_URL)
    issues = list(dict.fromkeys(_ISSUE_LINK_RE.findall(page)))
    draws: list[dict] = []
    for issue in issues:
        try:
            draw = _parse_500_xml(_request_text(KL8_XML_URL.format(issue=issue)))
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        if draw is not None:
            draws.append(draw)
        if len(draws) >= limit:
            break
    if not draws:
        raise ValueError("500.com 备用源未返回可用的快乐8数据")
    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws


def _request_json(url: str) -> dict:
    """发起一次 HTTP 请求并解析 JSON；测试通过 monkeypatch 本函数隔离网络。"""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("快乐8开奖数据源返回格式异常")
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
        raise ValueError("快乐8开奖日期字段异常")
    return match.group(1)


def _fetch_official(limit: int = 30) -> list[dict]:
    """抓取最近若干期开奖，按日期、期号倒序返回；字段缺失时抛异常。"""
    data = _request_json(_build_url(limit))
    if data.get("state") != 0:
        raise ValueError("快乐8开奖数据源返回异常状态")
    items = data.get("result")
    if not isinstance(items, list):
        raise ValueError("快乐8开奖数据源缺少 result 列表")

    draws: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("快乐8开奖记录格式异常")
        issue = str(item.get("code") or "").strip()
        if not issue:
            raise ValueError("快乐8开奖记录缺少期号")
        try:
            draw_numbers = _split_numbers(item.get("red"))
        except ValueError as exc:
            raise ValueError(f"快乐8第 {issue} 期开奖号码不完整") from exc
        if len(draw_numbers) != _DRAW_COUNT or len(set(draw_numbers)) != _DRAW_COUNT:
            raise ValueError(f"快乐8第 {issue} 期开奖号码不完整")
        if any(number < 1 or number > _NUMBER_MAX for number in draw_numbers):
            raise ValueError(f"快乐8第 {issue} 期开奖号码异常")

        draws.append(
            {
                "issue": issue,
                "date": _parse_date(item.get("date")),
                "numbers": {"draw": sorted(draw_numbers)},
                "extra": {"week": str(item.get("week") or "")},
            }
        )

    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws


def fetch_draws(limit: int = 30) -> list[dict]:
    try:
        return _fetch_official(limit)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        try:
            return _fetch_fallback(limit)
        except Exception as fallback_exc:
            raise ValueError(f"快乐8开奖数据源不可用，备用源也失败：{fallback_exc}") from exc


def _extract_picks(payload) -> list[int]:
    if isinstance(payload, dict):
        for key in ("picks", "numbers"):
            if key in payload:
                return _split_numbers(payload.get(key))
        for key in ("ticket", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _split_numbers(value)
        raise ValueError("请提供 1-10 个投注号码，例如 01 05 10")
    return _split_numbers(payload)


def _normalise_play_type(value, pick_count: int) -> str:
    expected = f"select{pick_count}"
    if value is None or str(value).strip() == "":
        return expected
    key = str(value).strip().lower()
    aliases = {f"select{number}": number for number in range(1, 11)}
    aliases.update(
        {f"选{_CN_NUMBERS[number]}": number for number in range(1, 11)}
    )
    if key not in aliases:
        raise ValueError("不支持的玩法，仅支持 select1 至 select10")
    if aliases[key] != pick_count:
        raise ValueError("玩法与所选号码个数不一致")
    return expected


def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
    """校验快乐8投注：1-10 个不重复号码（1-80），玩法需与个数一致。"""
    try:
        picks = _extract_picks(payload)
    except ValueError as exc:
        return {"ok": False, "normalized": {}, "errors": [str(exc)]}

    errors: list[str] = []
    if len(picks) < _MIN_PICKS or len(picks) > _MAX_PICKS:
        errors.append("快乐8投注号码个数必须为 1-10 个")
    if len(set(picks)) != len(picks):
        errors.append("投注号码不能重复")
    if any(number < 1 or number > _NUMBER_MAX for number in picks):
        errors.append("投注号码必须在 1-80 之间")

    resolved = f"select{len(picks)}" if _MIN_PICKS <= len(picks) <= _MAX_PICKS else ""
    if not errors:
        try:
            resolved = _normalise_play_type(play_type, len(picks))
        except ValueError as exc:
            errors.append(str(exc))

    normalized = (
        {"picks": sorted(picks), "play_type": resolved, "pick_count": len(picks)}
        if not errors
        else {}
    )
    return {"ok": not errors, "normalized": normalized, "errors": errors}


def _draw_numbers(draw: dict) -> list[int]:
    numbers = (draw or {}).get("numbers") if isinstance(draw, dict) else None
    if not isinstance(numbers, dict):
        raise ValueError("快乐8开奖数据缺少号码")
    try:
        draw_numbers = _split_numbers(numbers.get("draw"))
    except ValueError as exc:
        raise ValueError("快乐8开奖号码格式异常") from exc
    if len(draw_numbers) != _DRAW_COUNT:
        raise ValueError("快乐8开奖号码不完整")
    return draw_numbers


def _format_amount(amount: float) -> str:
    return f"{amount:g}"


def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
    """统计命中个数，按官方固定奖级表返回奖级与奖金。"""
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
    picks = normalized["picks"]
    pick_count = normalized["pick_count"]
    hits = len(set(picks) & set(_draw_numbers(draw)))

    amount = _PRIZE_TABLE.get(pick_count, {}).get(hits)
    hit = amount is not None
    prize_level = (
        f"选{_CN_NUMBERS[pick_count]}中{_CN_NUMBERS[hits]}" if hit else None
    )

    if hit:
        capped = _CAPPED.get((pick_count, hits))
        prize_text = capped or f"{_format_amount(amount)} 元"
        message = (
            f"命中 {hits} 个号码；{prize_level}，单注奖金 {prize_text}。"
            + _NOTE
        )
    else:
        message = f"命中 {hits} 个号码；未达到该玩法官方奖级条件。" + _NOTE

    return {
        "ok": True,
        "hit": hit,
        "prize_level": prize_level,
        "detail": {
            "hits": hits,
            "pick_count": pick_count,
            "play_type": normalized["play_type"],
            "prize_amount": amount,
            "prize_note": (
                _CAPPED.get((pick_count, hits), "固定奖金")
                if hit
                else ""
            ),
        },
        "message": message,
    }

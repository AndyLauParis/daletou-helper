"""七星彩适配器：前 6 位 0-9 + 最后 1 位 0-14。

主数据源：500.com 七星彩历史开奖页面（GB18030 编码）。
备用数据源：中国体彩网（sporttery）历史开奖接口。
奖级按官方《7星彩游戏规则》编码（一等奖至六等奖互不兼得）。
"""

from __future__ import annotations

import re
from datetime import datetime

import requests

SOURCE_NAME = "500.com / 国家体彩中心"

SOURCE_URL = "https://datachart.500.com/qxc/history/inc/history.php"
FALLBACK_URL = (
    "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
    "?gameNo=04&provinceId=0&pageSize=30&isVerify=1&pageNo=1"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REFERER = "https://datachart.500.com/"
TIMEOUT = 10

FRONT_LENGTH = 6
BACK_MAX = 14

# (奖级名称, 固定奖金)；一、二等奖为浮动奖。
PRIZE_INFO: dict[int, tuple[str, int | None]] = {
    1: ("一等奖", None),
    2: ("二等奖", None),
    3: ("三等奖", 3000),
    4: ("四等奖", 500),
    5: ("五等奖", 30),
    6: ("六等奖", 5),
}

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_SEPARATORS_RE = re.compile(r"[\s,，+\-|]+")
_ROW_RE = re.compile(r'<tr[^>]*class="t_tr1"[^>]*>.*?</tr>', re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ISSUE_RE = re.compile(r"\d{5}")
_DATE_CELL_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DIGITS_CELL_RE = re.compile(r"\d(?:\s+\d){5}\s+\d{1,2}")


class DataFetchError(RuntimeError):
    """抓取或解析七星彩开奖数据失败。"""


def _request(url: str):
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": REFERER},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response


def _history_url() -> str:
    """近两个日历年的期号范围，例如 2026 年取 25001 至 26999。"""
    year = datetime.now().year
    start = f"{(year - 1) % 100:02d}001"
    end = f"{year % 100:02d}999"
    return f"{SOURCE_URL}?start={start}&end={end}"


def _decode_html(response) -> str:
    content = getattr(response, "content", None)
    if content is None:
        return getattr(response, "text", "")
    return content.decode("gb18030", errors="replace")


def _clean_cell(raw: str) -> str:
    return _TAG_RE.sub("", raw).replace("\xa0", " ").strip()


def _normalize_date(value) -> str | None:
    match = _DATE_RE.match(str(value or "").strip())
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _to_int(value) -> int | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    return int(text) if text.isdigit() else None


def _front_from(raw) -> tuple[list[int], list[str]]:
    if raw is None:
        return [], ["缺少前区号码"]
    if isinstance(raw, str):
        compact = _SEPARATORS_RE.sub("", raw.strip())
        if compact.isdigit() and len(compact) == FRONT_LENGTH:
            return [int(char) for char in compact], []
        tokens: list = re.findall(r"\d+", raw)
    elif isinstance(raw, (list, tuple)):
        tokens = list(raw)
    else:
        return [], ["前区号码格式不正确"]

    digits: list[int] = []
    for token in tokens:
        if isinstance(token, bool):
            return [], ["前区号码格式不正确"]
        if isinstance(token, int):
            digits.append(token)
            continue
        if isinstance(token, str) and token.strip().isdigit():
            digits.append(int(token.strip()))
            continue
        return [], ["前区号码格式不正确"]
    return digits, []


def _back_from(raw) -> tuple[int | None, list[str]]:
    if isinstance(raw, bool):
        return None, ["后区号码格式不正确"]
    if isinstance(raw, int):
        return raw, []
    if isinstance(raw, (list, tuple)):
        if len(raw) != 1:
            return None, ["后区需要 1 个号码"]
        return _back_from(raw[0])
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip()), []
    return None, ["后区号码格式不正确"]


def _extract(payload) -> tuple[list[int], int | None, list[str]]:
    if isinstance(payload, dict):
        front, front_errors = _front_from(payload.get("front"))
        back, back_errors = _back_from(payload.get("back"))
        return front, back, front_errors + back_errors

    if isinstance(payload, str):
        text = payload.strip()
        if text.isdigit() and len(text) in (7, 8):
            return [int(char) for char in text[:6]], int(text[6:]), []
        tokens = re.findall(r"\d+", text)
        if len(tokens) == 7:
            return [int(token) for token in tokens[:6]], int(tokens[6]), []
        if len(tokens) == 2 and len(tokens[0]) == 6:
            return [int(char) for char in tokens[0]], int(tokens[1]), []
        return [], None, ["需要前区 6 位数字和后区 1 位数字"]

    return [], None, ["号码格式不正确"]


def validate_ticket(payload, play_type: str | None = None) -> dict:
    """校验前区 6 位 0-9、后区 1 位 0-14；各位置允许重复。"""
    front, back, errors = _extract(payload)
    if not errors:
        if len(front) != FRONT_LENGTH:
            errors.append("前区需要 6 位数字")
        elif any(number < 0 or number > 9 for number in front):
            errors.append("前区号码范围应为 0-9")
        if back is None:
            errors.append("缺少后区号码")
        elif not 0 <= back <= BACK_MAX:
            errors.append("后区号码范围应为 0-14")

    return {
        "ok": not errors,
        "normalized": {"front": front, "back": back, "play_type": None},
        "errors": errors,
    }


def _tier_for_hits(front_hits: int, back_hits: int) -> int | None:
    """官方规则：各奖级不兼中兼得，按最高奖级返回。"""
    if front_hits == 6 and back_hits == 1:
        return 1
    if front_hits == 6:
        return 2
    if front_hits == 5 and back_hits == 1:
        return 3
    if (front_hits == 5 and back_hits == 0) or (
        front_hits == 4 and back_hits == 1
    ):
        return 4
    if (front_hits == 4 and back_hits == 0) or (
        front_hits == 3 and back_hits == 1
    ):
        return 5
    if (
        (front_hits == 3 and back_hits == 0)
        or (front_hits == 2 and back_hits == 1)
        or (front_hits == 1 and back_hits == 1)
        or (front_hits == 0 and back_hits == 1)
    ):
        return 6
    return None


def check_ticket(payload, play_type: str | None, draw: dict) -> dict:
    validation = validate_ticket(payload, play_type)
    if not validation["ok"]:
        return {
            "ok": False,
            "hit": False,
            "prize_level": None,
            "detail": {},
            "message": "；".join(validation["errors"]),
        }

    numbers = (draw or {}).get("numbers") or {}
    draw_front = numbers.get("front") or []
    draw_back = numbers.get("back")
    if (
        len(draw_front) != FRONT_LENGTH
        or any(
            not isinstance(number, int) or not 0 <= number <= 9
            for number in draw_front
        )
        or not isinstance(draw_back, int)
        or not 0 <= draw_back <= BACK_MAX
    ):
        return {
            "ok": False,
            "hit": False,
            "prize_level": None,
            "detail": {},
            "message": "开奖数据不完整，无法核对",
        }

    normalized = validation["normalized"]
    front_hits = sum(
        1
        for pick, actual in zip(normalized["front"], draw_front)
        if pick == actual
    )
    back_hits = 1 if normalized["back"] == draw_back else 0
    tier = _tier_for_hits(front_hits, back_hits)
    label, amount = PRIZE_INFO.get(tier, (None, None))

    if label:
        message = (
            f"命中前区 {front_hits} 位、后区 {back_hits} 位，中得{label}；"
            "奖金以官方公告为准，请通过官方线下渠道兑奖。"
        )
    else:
        message = f"命中前区 {front_hits} 位、后区 {back_hits} 位，未中奖。"

    return {
        "ok": True,
        "hit": tier is not None,
        "prize_level": label,
        "detail": {
            "front_hits": front_hits,
            "back_hits": back_hits,
            "tier": tier,
            "prize_amount": amount,
        },
        "message": message,
    }


def _parse_html(html: str, limit: int) -> list[dict]:
    """解析 500.com 七星彩历史页面（6 位前区 + 1 位后区）。"""
    draws: list[dict] = []
    seen: set[str] = set()
    for row_html in _ROW_RE.findall(html):
        cells = [_clean_cell(cell) for cell in _TD_RE.findall(row_html)]
        issue = next(
            (cell for cell in cells if _ISSUE_RE.fullmatch(cell)), None
        )
        date = next(
            (cell for cell in cells if _DATE_CELL_RE.fullmatch(cell)), None
        )
        digits_cell = next(
            (cell for cell in cells if _DIGITS_CELL_RE.fullmatch(cell)), None
        )
        if not issue or not date or not digits_cell or issue in seen:
            continue
        values = [int(value) for value in digits_cell.split()]
        if len(values) != 7:
            continue
        front, back = values[:6], values[6]
        if any(number < 0 or number > 9 for number in front):
            continue
        if not 0 <= back <= BACK_MAX:
            continue
        seen.add(issue)
        numeric = [
            _to_int(cell)
            for cell in cells
            if cell not in (issue, date, digits_cell)
        ]
        numeric = [value for value in numeric if value is not None]
        draws.append(
            {
                "issue": issue,
                "date": date,
                "numbers": {"front": front, "back": back},
                "extra": {"sales": max(numeric) if numeric else None},
            }
        )

    if not draws:
        raise DataFetchError("数据源页面结构异常：未解析到开奖记录")

    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws[: max(0, int(limit))]


def _parse_draw_list(data, limit: int) -> list[dict]:
    if not isinstance(data, dict):
        raise DataFetchError("数据源返回格式异常")
    if data.get("success") is False:
        raise DataFetchError(str(data.get("errorMessage") or "数据源返回失败"))

    value = data.get("value")
    if not isinstance(value, dict):
        raise DataFetchError("数据源返回格式异常：缺少 value")
    rows = value.get("list")
    if not isinstance(rows, list):
        raise DataFetchError("数据源返回格式异常：缺少开奖列表")

    draws: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        issue = str(row.get("lotteryDrawNum") or "").strip()
        date = _normalize_date(row.get("lotteryDrawTime"))
        front, back, errors = _extract(str(row.get("lotteryDrawResult") or ""))
        if not issue or not date or errors:
            continue
        if len(front) != FRONT_LENGTH or any(
            number < 0 or number > 9 for number in front
        ):
            continue
        if back is None or not 0 <= back <= BACK_MAX:
            continue
        if issue in seen:
            continue
        seen.add(issue)
        draws.append(
            {
                "issue": issue,
                "date": date,
                "numbers": {"front": front, "back": back},
                "extra": {
                    "sales": _to_int(row.get("lotterySaleAmount")),
                    "pool": _to_int(row.get("poolBalanceAfterdraw")),
                },
            }
        )

    if not draws:
        raise DataFetchError("数据源返回格式异常：未解析到开奖记录")

    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws[: max(0, int(limit))]


def fetch_draws(limit: int = 30) -> list[dict]:
    """优先 500.com，失败时尝试一次 sporttery 备用源。"""
    primary_error: Exception | None = None
    try:
        html = _decode_html(_request(_history_url()))
        return _parse_html(html, limit)
    except Exception as exc:
        primary_error = exc

    try:
        data = _request(FALLBACK_URL).json()
        return _parse_draw_list(data, limit)
    except Exception as exc:
        raise DataFetchError(
            f"主数据源失败：{primary_error}；备用数据源失败：{exc}"
        ) from exc

"""排列3适配器：直选 / 组选3 / 组选6。

主数据源：500.com 排列3历史开奖页面（GB18030 编码）。
备用数据源：中国体彩网（sporttery）历史开奖接口。
"""

from __future__ import annotations

import re
from datetime import datetime

import requests

SOURCE_NAME = "500.com / 国家体彩中心"

SOURCE_URL = "https://datachart.500.com/pls/history/inc/history.php"
FALLBACK_URL = (
    "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
    "?gameNo=35&provinceId=0&pageSize=30&isVerify=1&pageNo=1"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REFERER = "https://datachart.500.com/"
TIMEOUT = 10

PLAY_TYPE_LABELS: dict[str, str] = {
    "zhixuan": "直选",
    "zu3": "组选3",
    "zu6": "组选6",
}
PRIZE_AMOUNTS: dict[str, int] = {
    "zhixuan": 1040,
    "zu3": 346,
    "zu6": 173,
}

_PLAY_ALIASES = {
    "": "zhixuan",
    "zhixuan": "zhixuan",
    "直选": "zhixuan",
    "zu3": "zu3",
    "组选3": "zu3",
    "组选三": "zu3",
    "zu6": "zu6",
    "组选6": "zu6",
    "组选六": "zu6",
}
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_ROW_RE = re.compile(r'<tr[^>]*class="t_tr1"[^>]*>.*?</tr>', re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ISSUE_RE = re.compile(r"\d{5}")
_DATE_CELL_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DIGITS_CELL_RE = re.compile(r"\d(?:\s+\d){2}")


class DataFetchError(RuntimeError):
    """抓取或解析排列3开奖数据失败。"""


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


def _to_digits(payload) -> tuple[list[int], list[str]]:
    if isinstance(payload, dict):
        raw = payload.get("digits")
        if raw is None:
            return [], ["缺少号码"]
    elif isinstance(payload, str):
        raw = payload
    else:
        return [], ["号码格式不正确"]

    if isinstance(raw, str):
        text = raw.strip()
        if text.isdigit():
            return [int(char) for char in text], []
        tokens: list = re.split(r"[\s,，]+", text)
    elif isinstance(raw, (list, tuple)):
        tokens = list(raw)
    else:
        return [], ["号码格式不正确"]

    digits: list[int] = []
    for token in tokens:
        if token == "":
            continue
        if isinstance(token, bool):
            return [], ["号码格式不正确"]
        if isinstance(token, int):
            if not 0 <= token <= 9:
                return [], ["号码范围应为 0-9"]
            digits.append(token)
            continue
        if isinstance(token, str) and token.strip().isdigit():
            value = int(token.strip())
            if not 0 <= value <= 9:
                return [], ["号码范围应为 0-9"]
            digits.append(value)
            continue
        return [], ["号码格式不正确"]
    return digits, []


def _normalize_play_type(play_type) -> str | None:
    text = "" if play_type is None else str(play_type).strip().lower()
    return _PLAY_ALIASES.get(text)


def validate_ticket(payload, play_type: str | None = None) -> dict:
    """按玩法校验 3 个 0-9 数字；组选3/组选6 额外校验号码结构。"""
    play = _normalize_play_type(play_type)
    errors: list[str] = []
    if play is None:
        errors.append("不支持的玩法")

    digits, parse_errors = _to_digits(payload)
    errors.extend(parse_errors)
    if not parse_errors:
        if len(digits) != 3:
            errors.append("需要 3 个数字")
        elif play == "zu3" and len(set(digits)) != 2:
            errors.append("组选3 号码必须有两个数字相同")
        elif play == "zu6" and len(set(digits)) != 3:
            errors.append("组选6 号码必须三个数字互不相同")

    return {
        "ok": not errors,
        "normalized": {"digits": digits, "play_type": play or "zhixuan"},
        "errors": errors,
    }


def check_ticket(payload, play_type: str | None, draw: dict) -> dict:
    """按所选玩法核对，不把不同玩法的中奖条件混用。"""
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
    draw_digits = numbers.get("digits") or []
    if len(draw_digits) != 3 or any(
        not isinstance(number, int) or not 0 <= number <= 9
        for number in draw_digits
    ):
        return {
            "ok": False,
            "hit": False,
            "prize_level": None,
            "detail": {},
            "message": "开奖数据不完整，无法核对",
        }

    digits = validation["normalized"]["digits"]
    play = validation["normalized"]["play_type"]
    hit = False
    if play == "zhixuan":
        hit = digits == draw_digits
    elif play == "zu3":
        hit = len(set(draw_digits)) == 2 and sorted(digits) == sorted(draw_digits)
    elif play == "zu6":
        hit = len(set(draw_digits)) == 3 and sorted(digits) == sorted(draw_digits)

    label = PLAY_TYPE_LABELS[play]
    amount = PRIZE_AMOUNTS[play] if hit else None
    if hit:
        message = (
            f"中得{label}（固定奖金 {amount} 元）；"
            "固定奖金，以官方公告为准，请通过官方线下渠道兑奖。"
        )
    else:
        message = f"未中得{label}，本注未中奖。"

    return {
        "ok": True,
        "hit": hit,
        "prize_level": label if hit else None,
        "detail": {
            "digits": digits,
            "draw_digits": list(draw_digits),
            "play_type": play,
            "prize_amount": amount,
        },
        "message": message,
    }


def _parse_html(html: str, limit: int) -> list[dict]:
    """解析 500.com 排列3历史页面。"""
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
        digits = [int(value) for value in digits_cell.split()]
        if len(digits) != 3 or any(number < 0 or number > 9 for number in digits):
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
                "numbers": {"digits": digits},
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
        digits, errors = _to_digits(row.get("lotteryDrawResult"))
        if not issue or not date or errors or len(digits) != 3:
            continue
        if issue in seen:
            continue
        seen.add(issue)
        draws.append(
            {
                "issue": issue,
                "date": date,
                "numbers": {"digits": digits},
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

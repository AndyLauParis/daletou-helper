"""排列5适配器。

数据源：500.com 排列5历史开奖页面（HTML 表格，gb2312 编码）。
"""

from __future__ import annotations

import re
from datetime import datetime

import requests

SOURCE_NAME = "国家体彩中心 / 500.com"

BASE_URL = "https://datachart.500.com/plw/history/inc/history.php"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 10

_ROW_RE = re.compile(r'<tr[^>]*class="t_tr1"[^>]*>.*?</tr>', re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ISSUE_RE = re.compile(r"\d{5}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DIGITS_RE = re.compile(r"\d(?:\s+\d){4}")
_MONEY_RE = re.compile(r"\d{1,3}(?:,\d{3})+")


class DataFetchError(RuntimeError):
    """抓取或解析排列5开奖数据失败。"""


def _request(url: str):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    response.raise_for_status()
    return response


def _history_url() -> str:
    """近两个日历年的期号范围，例如 2026 年取 25001 至 26999。"""
    year = datetime.now().year
    start = f"{(year - 1) % 100:02d}001"
    end = f"{year % 100:02d}999"
    return f"{BASE_URL}?start={start}&end={end}"


def _clean_cell(raw: str) -> str:
    return _TAG_RE.sub("", raw).replace("\xa0", " ").strip()


def _parse_history(html: str, limit: int) -> list[dict]:
    draws: list[dict] = []
    seen: set[str] = set()
    for row_html in _ROW_RE.findall(html):
        cells = [_clean_cell(cell) for cell in _TD_RE.findall(row_html)]
        issue = next(
            (cell for cell in cells if _ISSUE_RE.fullmatch(cell)), None
        )
        date = next(
            (cell for cell in cells if _DATE_RE.fullmatch(cell)), None
        )
        digits_cell = next(
            (cell for cell in cells if _DIGITS_RE.fullmatch(cell)), None
        )
        if not issue or not date or not digits_cell or issue in seen:
            continue
        digits = [int(value) for value in digits_cell.split()]
        if len(digits) != 5 or any(number < 0 or number > 9 for number in digits):
            continue
        seen.add(issue)
        sales_cell = next(
            (cell for cell in cells if _MONEY_RE.fullmatch(cell)), None
        )
        draws.append(
            {
                "issue": issue,
                "date": date,
                "numbers": {"digits": digits},
                "extra": {
                    "sales": (
                        int(sales_cell.replace(",", ""))
                        if sales_cell is not None
                        else None
                    )
                },
            }
        )

    if not draws:
        raise DataFetchError("数据源页面结构异常：未解析到开奖记录")

    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws[: max(0, int(limit))]


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


def validate_ticket(payload, play_type: str | None = None) -> dict:
    """排列5 固定 5 位，每注号码允许重复数字。"""
    digits, errors = _to_digits(payload)
    if not errors and len(digits) != 5:
        errors.append("需要 5 个数字")
    return {
        "ok": not errors,
        "normalized": {"digits": digits, "play_type": None},
        "errors": errors,
    }


def check_ticket(payload, play_type: str | None, draw: dict) -> dict:
    """逐位相同即一等奖，否则未中奖。"""
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
    if len(draw_digits) != 5 or any(
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
    hit = digits == draw_digits
    message = (
        "中得一等奖（固定奖金 100000 元）；"
        "固定奖金，以官方公告为准，请通过官方线下渠道兑奖。"
        if hit
        else "未中奖。"
    )
    return {
        "ok": True,
        "hit": hit,
        "prize_level": "一等奖" if hit else None,
        "detail": {
            "digits": digits,
            "draw_digits": list(draw_digits),
            "prize_amount": 100000 if hit else None,
        },
        "message": message,
    }


def fetch_draws(limit: int = 30) -> list[dict]:
    response = _request(_history_url())
    content = getattr(response, "content", None)
    if content is None:
        html = response.text
    else:
        html = content.decode("gb2312", errors="replace")
    return _parse_history(html, limit)

"""500.com 开奖数据备用源。

福彩官网对部分机房出口 IP 返回 403（网宿云安全），因此为双色球、七乐彩、
福彩3D 提供 500.com 历史页解析；快乐8 使用 500.com 的单期 XML。
仅在官网出现网络/HTTP 错误时启用，官网返回数据格式异常时仍按原逻辑报错。
"""

from __future__ import annotations

import re
from datetime import datetime

import requests

SOURCE_NAME = "500.com"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REFERER = "https://datachart.500.com/"
TIMEOUT = 10

_ROW_RE = re.compile(r'<tr[^>]*class="t_tr1"[^>]*>.*?</tr>', re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def history_url(game: str) -> str:
    """近两个日历年的历史页；福彩3D（sd）使用 7 位期号，其余用 5 位。"""
    year = datetime.now().year
    if game == "sd":
        start = f"{year - 1}001"
        end = f"{year}999"
    else:
        start = f"{(year - 1) % 100:02d}001"
        end = f"{year % 100:02d}999"
    return (
        "https://datachart.500.com/"
        f"{game}/history/inc/history.php?start={start}&end={end}"
    )


def _clean_cell(raw: str) -> str:
    return _TAG_RE.sub("", raw).replace("\xa0", " ").strip()


def fetch_rows(game: str) -> list[list[str]]:
    """抓取历史页并返回表格行（每行为清理后的单元格文本）。"""
    response = requests.get(
        history_url(game),
        headers={"User-Agent": USER_AGENT, "Referer": REFERER},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    html = response.content.decode("gb18030", errors="replace")
    rows = []
    for row in _ROW_RE.findall(html):
        cells = [_clean_cell(cell) for cell in _TD_RE.findall(row)]
        if cells:
            rows.append(cells)
    return rows


def row_date(cells: list[str]) -> str | None:
    for cell in cells:
        match = _DATE_RE.search(cell)
        if match:
            return match.group(0)
    return None


def row_issue(cells: list[str], pattern: str) -> tuple[int, str] | None:
    regex = re.compile(pattern)
    for index, cell in enumerate(cells):
        if regex.fullmatch(cell):
            return index, cell
    return None


def expand_issue(issue: str) -> str:
    """500.com 的双色球/七乐彩使用 5 位期号，统一为官方 7 位。"""
    text = str(issue or "").strip()
    if len(text) == 5 and text.isdigit():
        return "20" + text
    return text

"""把纯文本 OCR 结果解析为彩票结构化数据。

MiniCPM-OCR 等接口只返回票面文字，本模块按游戏关键字、期号标签与号码
布局做启发式解析；解析不确定时降低置信度，交由上层标记为待人工审核。
"""

from __future__ import annotations

import re
import unicodedata

MAX_RAW_TEXT = 2000

GAME_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dlt", ("超级大乐透", "大乐透")),
    ("ssq", ("双色球",)),
    ("qlc", ("七乐彩",)),
    ("kl8", ("快乐8", "快乐八")),
    ("qxc", ("七星彩",)),
    ("pl5", ("排列5", "排列五")),
    ("pl3", ("排列3", "排列三")),
    ("fc3d", ("福彩3D", "福彩3d", "福彩 3D")),
)

GAME_NAMES = {
    "dlt": "超级大乐透",
    "ssq": "双色球",
    "qlc": "七乐彩",
    "kl8": "快乐8",
    "qxc": "七星彩",
    "pl5": "排列5",
    "pl3": "排列3",
    "fc3d": "福彩3D",
}

DATE_RE = re.compile(r"\d{4}\s*[-/年.]\s*\d{1,2}\s*[-/月.]\s*\d{1,2}\s*日?")
TIME_RE = re.compile(r"\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?")
ISSUE_RE = re.compile(r"第\s*(\d{3,12})\s*期")
ISSUE_LABEL_RE = re.compile(r"期号\s*[:：]?\s*(\d{3,12})")
ISSUE_LINE_RE = re.compile(r"(?m)^\s*(\d{4,7})\s*$")
TICKET_RE = re.compile(r"[A-Z]{1,3}\d{6,}")

# 含数字的游戏名称会在解析号码前移除，避免把名称里的数字当成号码。
GAME_NAME_NOISE = ("排列3", "排列5", "福彩3D", "快乐8", "3D")

LABEL_MARKERS = (
    "前区",
    "后区",
    "红区",
    "蓝区",
    "红球",
    "蓝球",
    "基本号码",
    "期号",
    "开奖",
    "投注",
    "票号",
    "金额",
    "\n",
)

FRONT_LABELS = {
    "dlt": ("前区", "红区", "红球"),
    "ssq": ("红球", "前区", "红区"),
}
BACK_LABELS = {
    "dlt": ("后区", "蓝区", "蓝球"),
    "ssq": ("蓝球", "后区", "蓝区"),
}


class TicketParseError(ValueError):
    """票面文字无法解析为彩票数据。"""


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return normalized.upper().replace("＋", "+")


def detect_game(text: str, hint: str | None = None) -> tuple[str, float]:
    for code, keywords in GAME_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return code, 0.95
    hint_code = (hint or "").strip().lower()
    if hint_code in GAME_NAMES:
        return hint_code, 0.7
    raise TicketParseError("未能识别彩票类型，请换一张更清晰的照片或手动选择类型")


def extract_issue(text: str) -> tuple[str, float]:
    match = ISSUE_RE.search(text) or ISSUE_LABEL_RE.search(text) or ISSUE_LINE_RE.search(text)
    if match:
        return match.group(1), 0.9
    return "", 0.3


def extract_ticket_no(text: str) -> str | None:
    match = TICKET_RE.search(text)
    if match:
        return match.group(0)[:64]
    candidates = re.findall(r"\d{8,}", text)
    return max(candidates, key=len)[:64] if candidates else None


def _clean_text(text: str, issue: str) -> str:
    cleaned = text
    for name in GAME_NAME_NOISE:
        cleaned = cleaned.replace(name, " ")
    cleaned = DATE_RE.sub(" ", cleaned)
    cleaned = TIME_RE.sub(" ", cleaned)
    cleaned = TICKET_RE.sub(" ", cleaned)
    if issue:
        cleaned = cleaned.replace(issue, " ")
    return cleaned


def _segment(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        index = text.find(label)
        if index < 0:
            continue
        rest = text[index + len(label) :]
        stop = len(rest)
        for marker in LABEL_MARKERS:
            position = rest.find(marker)
            if position >= 0:
                stop = min(stop, position)
        return rest[:stop]
    return ""


def _two_digit_numbers(segment: str) -> list[int]:
    segment = DATE_RE.sub(" ", TIME_RE.sub(" ", segment))
    numbers: list[int] = []
    for token in re.findall(r"\d+", segment):
        if len(token) == 2:
            numbers.append(int(token))
        elif 4 <= len(token) <= 20 and len(token) % 2 == 0:
            numbers.extend(int(token[index : index + 2]) for index in range(0, len(token), 2))
    return numbers


def _global_numbers(cleaned: str) -> list[int]:
    numbers: list[int] = []
    for token in re.findall(r"\d+", cleaned):
        if len(token) == 2:
            numbers.append(int(token))
        elif 4 <= len(token) <= 20 and len(token) % 2 == 0:
            numbers.extend(int(token[index : index + 2]) for index in range(0, len(token), 2))
    return numbers


def _parse_two_zone(text: str, cleaned: str, game: str) -> tuple[dict, bool]:
    front_segment = _segment(text, FRONT_LABELS[game])
    back_segment = _segment(text, BACK_LABELS[game])
    front_count, back_count = (5, 2) if game == "dlt" else (6, 1)
    front_max, back_max = (35, 12) if game == "dlt" else (33, 16)

    if front_segment.strip() and back_segment.strip():
        front = [n for n in _two_digit_numbers(front_segment) if 1 <= n <= front_max]
        back = [n for n in _two_digit_numbers(back_segment) if 1 <= n <= back_max]
        if len(front) >= front_count and len(back) >= back_count:
            front = front[:front_count]
            back = back[:back_count]
            if game == "dlt":
                return {"front": front, "back": back}, True
            return {"red": front, "blue": back}, True

    numbers = _global_numbers(cleaned)
    if len(numbers) >= front_count + back_count:
        front = numbers[:front_count]
        back = numbers[front_count : front_count + back_count]
        if game == "dlt":
            return {"front": front, "back": back}, False
        return {"red": front, "blue": back}, False
    return {}, False


def _parse_digits(cleaned: str, length: int) -> tuple[list[int], bool]:
    for token in re.findall(r"\d+", cleaned):
        if len(token) == length:
            return [int(char) for char in token], True
    singles = re.findall(r"(?<!\d)\d(?!\d)", cleaned)
    if len(singles) >= length:
        return [int(char) for char in singles[:length]], False
    return [], False


def _parse_play_type(text: str, game: str) -> str | None:
    if game == "dlt":
        return "standard"
    if game in {"pl3", "fc3d"}:
        if re.search(r"组选\s*3|组三", text):
            return "zu3"
        if re.search(r"组选\s*6|组六", text):
            return "zu6"
        return "zhixuan"
    if game == "kl8":
        return None
    return None


def parse_ticket_text(
    text: str,
    hint: str | None = None,
    *,
    model: str = "",
    provider: str = "",
) -> dict:
    """把 OCR 文本解析为识别结果；无法判断类型时抛出 TicketParseError。"""
    raw = normalize_text(text)
    if not raw.strip():
        raise TicketParseError("票面没有可识别的文字")

    game, game_confidence = detect_game(raw, hint)
    issue, issue_confidence = extract_issue(raw)
    cleaned = _clean_text(raw, issue)
    ticket_no = extract_ticket_no(raw)
    labeled = False
    payload: dict | None = None
    payload_confidence = 0.2

    if game in {"dlt", "ssq"}:
        payload, labeled = _parse_two_zone(raw, cleaned, game)
        expected = 7
    elif game == "qlc":
        basic, labeled = _parse_basic_numbers(raw, cleaned)
        payload = {"basic": basic} if basic else {}
        expected = 7
    elif game == "kl8":
        picks = _global_numbers(cleaned)[:10]
        payload = {"picks": picks} if picks else {}
        expected = len(picks)
    elif game == "qxc":
        digits, labeled = _parse_qxc(raw, cleaned)
        payload = digits
        expected = 7
    elif game == "pl5":
        values, labeled = _parse_digits(cleaned, 5)
        payload = {"digits": values} if values else {}
        expected = 5
    else:  # pl3 / fc3d
        values, labeled = _parse_digits(cleaned, 3)
        payload = {"digits": values} if values else {}
        expected = 3

    actual = _payload_count(game, payload)
    if actual and actual == expected:
        payload_confidence = 0.92 if labeled else 0.78
    elif actual:
        payload_confidence = 0.4
    else:
        payload_confidence = 0.2

    field_confidence = {
        "game_code": game_confidence,
        "issue": issue_confidence,
        "payload": payload_confidence,
    }
    confidence = min(field_confidence.values())
    return {
        "game_code": game,
        "issue": issue,
        "play_type": _parse_play_type(raw, game),
        "payload": payload or {},
        "confidence": round(confidence, 3),
        "field_confidence": field_confidence,
        "ticket_no": ticket_no,
        "raw_text": raw[:MAX_RAW_TEXT],
        "model": model,
        "provider": provider,
    }


def _payload_count(game: str, payload: dict) -> int:
    if not isinstance(payload, dict):
        return 0
    if game == "dlt":
        return len(payload.get("front") or []) + len(payload.get("back") or [])
    if game == "ssq":
        return len(payload.get("red") or []) + len(payload.get("blue") or [])
    if game == "qlc":
        return len(payload.get("basic") or [])
    if game == "kl8":
        return len(payload.get("picks") or [])
    if game == "qxc":
        front = payload.get("front") or []
        return len(front) + (1 if payload.get("back") is not None else 0)
    return len(payload.get("digits") or [])


def _parse_basic_numbers(text: str, cleaned: str) -> tuple[list[int], bool]:
    segment = _segment(text, ("基本号码", "基本号", "号码"))
    if segment.strip():
        numbers = [n for n in _two_digit_numbers(segment) if 1 <= n <= 30]
        if len(numbers) >= 7:
            return numbers[:7], True
    numbers = [n for n in _global_numbers(cleaned) if 1 <= n <= 30]
    return (numbers[:7], False) if len(numbers) >= 7 else ([], False)


def _parse_qxc(text: str, cleaned: str) -> tuple[dict, bool]:
    front_segment = _segment(text, ("前区", "第一位"))
    back_segment = _segment(text, ("后区", "最后一位"))
    if front_segment.strip() and back_segment.strip():
        front = [int(char) for char in re.findall(r"\d", front_segment)[:6]]
        back_digits = re.findall(r"\d", back_segment)
        if len(front) == 6 and back_digits:
            return {"front": front, "back": back_digits[0]}, True
    for token in re.findall(r"\d+", cleaned):
        if len(token) == 7:
            return {"front": [int(char) for char in token[:6]], "back": token[6]}, False
    return {}, False

"""胜负彩14场适配器：赛果抓取、投注内容校验与逐场核对。

数据源为 500.com 足彩开奖页（GB18030 编码）与同站按期的赛果 XML 明细。
只提取期号、开奖日期、球队、比分与 3/1/0 赛果，不采集盘口类数据；
奖金以官方公告为准，本工具仅用于记录与核对。
"""

from __future__ import annotations

import html as html_module
import re
import xml.etree.ElementTree as ET

import requests

SOURCE_NAME = "国家体彩中心 / 500.com"

LATEST_URL = "https://kaijiang.500.com/sfc.shtml"
HISTORY_URL = "https://kaijiang.500.com/shtml/sfc/{issue}.shtml"
XML_URL = "https://kaijiang.500.com/static/info/kaijiang/xml/sfc/{issue}.xml"

MATCH_COUNT = 14
DEFAULT_LIMIT = 30
MAX_HISTORY_ISSUES = 3
TIMEOUT_SECONDS = 10
PRIZE_NOTE = "奖金以官方公告为准，请通过官方线下渠道兑奖"

RESULTS = ("3", "1", "0")
GOAL_BUCKETS = ("0", "1", "2", "3+")

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_CONTENT_TABLE_RE = re.compile(
    r'<table\b[^>]*class="kj_tablelist02"[^>]*>(.*?)</table>',
    re.S | re.I,
)
_TD_TAG_RE = re.compile(r"<td\b[^>]*>", re.I)
_CLASS_ATTR_RE = re.compile(r'class="([^"]*)"', re.I)
_TITLE_ATTR_RE = re.compile(r'title="([^"]*)"', re.I)
_RESULT_SPAN_RE = re.compile(
    r'<span\b[^>]*class="cfont5[^"]*"[^>]*>\s*([^<]*?)\s*</span>',
    re.I,
)
_ISSUE_LINK_RE = re.compile(
    r'href="[^"]*?/shtml/([a-z0-9]+)/(\d+)\.shtml"',
    re.I,
)


# ---------------------------------------------------------------------------
# 通用文本与抓取
# ---------------------------------------------------------------------------


def _clean_text(value) -> str:
    """去标签、反转义并压缩空白。"""
    if value is None:
        return ""
    text = html_module.unescape(str(value))
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _plain_pick(value) -> str:
    """把单个选择值归一化为去空白的字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def _three_way(value) -> str | None:
    """归一化 3/1/0 赛果，无法识别时返回 None。"""
    text = _clean_text(value)
    return text if text in RESULTS else None


def _goal_bucket(value) -> str | None:
    """归一化进球档位，3 与 3+ 统一为 3+。"""
    text = _clean_text(value).replace("＋", "+")
    if text in ("3", "3+", "+3"):
        return "3+"
    if text in ("0", "1", "2"):
        return text
    return None


def _bucket_for_total(total: int) -> str:
    """总进球档位：0/1/2，3 球及以上统一为 3+。"""
    return "3+" if total >= 3 else str(total)


def _combine_buckets(home_value, away_value) -> str | None:
    """把主客队各自的进球档位合并为一场总进球档位。

    主客队档位中的 3+ 表示“3 球及以上”，只有在另一队也有进球时才能确定
    总进球超过 3 球；若另一队为 0，则总进球可能是 3 也可能是 4+，此时返回
    None，交由赛果 XML 的具体比分补全，避免推断。
    """
    home = _goal_bucket(home_value)
    away = _goal_bucket(away_value)
    if home is None or away is None:
        return None
    if home != "3+" and away != "3+":
        return _bucket_for_total(int(home) + int(away))
    if home == "3+" and away == "3+":
        return "3+"
    if (home == "3+" and away != "0") or (away == "3+" and home != "0"):
        return "3+"
    return None


def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _score_text(value) -> str | None:
    text = _clean_text(value)
    return text if re.fullmatch(r"\d+:\d+", text) else None


def _fetch_text(url: str, encoding: str = "gb18030") -> str:
    """抓取页面或 XML；页面按 GB18030 解码。"""
    response = requests.get(url, headers=_HEADERS, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    response.encoding = encoding
    return response.text


def _try_fetch_xml(issue: str, xml_url: str) -> str | None:
    try:
        return _fetch_text(xml_url.format(issue=issue), encoding="utf-8")
    except Exception:  # 明细不可用时仅保留页面赛果
        return None


# ---------------------------------------------------------------------------
# 页面解析
# ---------------------------------------------------------------------------


def _first_result_table(page_html: str) -> str:
    match = _CONTENT_TABLE_RE.search(page_html or "")
    return match.group(1) if match else ""


def _parse_issue(table_html: str) -> str | None:
    match = re.search(r"第\s*(\d{4,8})\s*期", _clean_text(table_html))
    return match.group(1) if match else None


def _parse_date(table_html: str) -> str:
    text = _clean_text(table_html)
    match = re.search(
        r"开奖日期[：:]?\s*(\d{4})年(\d{1,2})月(\d{1,2})日",
        text,
    )
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return ""


def _team_titles(table_html: str) -> list[str]:
    titles: list[str] = []
    for tag in _TD_TAG_RE.findall(table_html):
        class_match = _CLASS_ATTR_RE.search(tag)
        if not class_match or "div_shupai" not in class_match.group(1):
            continue
        title_match = _TITLE_ATTR_RE.search(tag)
        if title_match:
            titles.append(_clean_text(title_match.group(1)))
    return titles


def _result_tokens(table_html: str) -> list[str]:
    return [_clean_text(value) for value in _RESULT_SPAN_RE.findall(table_html)]


def _split_teams(title: str) -> tuple[str, str]:
    text = _clean_text(title)
    parts = re.split(r"\s*VS\s*", text, flags=re.I)
    if len(parts) >= 2:
        return parts[0].strip(), parts[-1].strip()
    return "", ""


def _page_sfc_matches(
    titles: list[str], tokens: list[str], expected: int
) -> list[dict]:
    matches: list[dict] = []
    for index in range(expected):
        home, away = _split_teams(titles[index])
        result = _three_way(tokens[index]) if index < len(tokens) else None
        matches.append(
            {
                "index": index + 1,
                "home": home,
                "away": away,
                "score": None,
                "half_score": None,
                "result": result,
                "half_result": None,
            }
        )
    return matches


def _page_jq4_matches(
    titles: list[str], tokens: list[str], expected: int
) -> list[dict] | None:
    if len(titles) >= expected * 2:
        pair_titles = [titles[index * 2] for index in range(expected)]
    elif len(titles) >= expected:
        pair_titles = titles[:expected]
    else:
        return None

    matches: list[dict] = []
    for index in range(expected):
        home, away = _split_teams(pair_titles[index])
        result: str | None = None
        if len(tokens) >= expected * 2:
            result = _combine_buckets(tokens[index * 2], tokens[index * 2 + 1])
        elif len(tokens) >= expected:
            result = _goal_bucket(tokens[index])
        matches.append(
            {
                "index": index + 1,
                "home": home,
                "away": away,
                "score": None,
                "half_score": None,
                "result": result,
                "half_result": None,
            }
        )
    return matches


def _page_zc6_matches(
    titles: list[str], tokens: list[str], expected: int
) -> list[dict] | None:
    if len(titles) < expected:
        return None
    matches: list[dict] = []
    for index in range(expected):
        home, away = _split_teams(titles[index])
        half_result: str | None = None
        result: str | None = None
        if len(tokens) >= expected * 2:
            half_result = _three_way(tokens[index * 2])
            result = _three_way(tokens[index * 2 + 1])
        elif len(tokens) >= expected:
            result = _three_way(tokens[index])
        matches.append(
            {
                "index": index + 1,
                "home": home,
                "away": away,
                "score": None,
                "half_score": None,
                "result": result,
                "half_result": half_result,
            }
        )
    return matches


def _parse_issue_links(page_html: str, kind: str) -> list[str]:
    issues: list[str] = []
    for code, issue in _ISSUE_LINK_RE.findall(page_html or ""):
        if code.lower() != kind:
            continue
        if issue not in issues:
            issues.append(issue)
    return issues


def _build_page_draw(page_html: str, kind: str, expected: int) -> dict | None:
    table = _first_result_table(page_html)
    if not table:
        return None
    issue = _parse_issue(table)
    if not issue:
        return None
    titles = _team_titles(table)
    tokens = _result_tokens(table)
    if kind == "jq4":
        matches = _page_jq4_matches(titles, tokens, expected)
    elif kind == "zc6":
        matches = _page_zc6_matches(titles, tokens, expected)
    else:
        if len(titles) < expected:
            return None
        matches = _page_sfc_matches(titles, tokens, expected)
    if matches is None:
        return None
    return _new_draw(issue, _parse_date(table), matches, kind)


# ---------------------------------------------------------------------------
# XML 明细解析
# ---------------------------------------------------------------------------


def _date_from_xml(value) -> str:
    text = _clean_text(value)
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _pair_entries(entries: list) -> list[list]:
    """把进球彩按 FixtureID 配对成 4 场；无该属性时按顺序两两配对。"""
    if not entries:
        return []
    if all(entry.get("FixtureID") is None for entry in entries):
        return [entries[index : index + 2] for index in range(0, len(entries) - 1, 2)]
    grouped: dict[str, list] = {}
    order: list[str] = []
    for entry in entries:
        key = entry.get("FixtureID") or ""
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(entry)
    return [grouped[key] for key in order if len(grouped[key]) == 2]


def _xml_sfc_matches(entries: list, expected: int) -> list[dict] | None:
    if len(entries) != expected:
        return None
    matches: list[dict] = []
    for index, entry in enumerate(entries):
        matches.append(
            {
                "index": index + 1,
                "home": _clean_text(entry.get("HomeTeamName")),
                "away": _clean_text(entry.get("GuestTeamName")),
                "score": _score_text(entry.get("MatchScore")),
                "half_score": None,
                "result": _three_way(entry.get("Result")),
                "half_result": None,
            }
        )
    return matches


def _xml_jq4_matches(entries: list, expected: int) -> list[dict] | None:
    pairs = _pair_entries(entries)
    if len(pairs) != expected:
        return None
    matches: list[dict] = []
    for index, pair in enumerate(pairs):
        home_entry, away_entry = pair[0], pair[1]
        home_goals = _int_or_none(home_entry.get("MatchScore"))
        away_goals = _int_or_none(away_entry.get("MatchScore"))
        if home_goals is not None and away_goals is not None:
            score = f"{home_goals}:{away_goals}"
            result = _bucket_for_total(home_goals + away_goals)
        else:
            score = None
            result = _combine_buckets(
                home_entry.get("Result"), away_entry.get("Result")
            )
        matches.append(
            {
                "index": index + 1,
                "home": _clean_text(home_entry.get("TeamName")),
                "away": _clean_text(away_entry.get("TeamName")),
                "score": score,
                "half_score": None,
                "result": result,
                "half_result": None,
            }
        )
    return matches


def _xml_zc6_matches(entries: list, expected: int) -> list[dict] | None:
    if len(entries) != expected:
        return None
    matches: list[dict] = []
    for index, entry in enumerate(entries):
        matches.append(
            {
                "index": index + 1,
                "home": _clean_text(entry.get("HomeTeamName")),
                "away": _clean_text(entry.get("GuestTeamName")),
                "score": _score_text(entry.get("MatchScore")),
                "half_score": _score_text(entry.get("HalfMatchScore")),
                "result": _three_way(entry.get("Result")),
                "half_result": _three_way(entry.get("HalfResult")),
            }
        )
    return matches


def _draw_from_xml(xml_text: str, kind: str, expected: int) -> dict | None:
    if not isinstance(xml_text, str) or not xml_text.strip():
        return None
    try:
        root = ET.fromstring(xml_text.lstrip("\ufeff \t\r\n"))
    except (ET.ParseError, ValueError):
        return None

    issue = _clean_text(root.findtext("PeriodicalNO"))
    if not issue:
        return None
    entries = root.findall("MatchTeams/MatchTeam")
    if kind == "jq4":
        matches = _xml_jq4_matches(entries, expected)
    elif kind == "zc6":
        matches = _xml_zc6_matches(entries, expected)
    else:
        matches = _xml_sfc_matches(entries, expected)
    if matches is None:
        return None
    return _new_draw(issue, _date_from_xml(root.findtext("ResultTime")), matches, kind)


# ---------------------------------------------------------------------------
# 记录构造与合并
# ---------------------------------------------------------------------------


def _new_draw(issue: str, date: str, matches: list[dict], kind: str) -> dict:
    draw = {
        "issue": issue,
        "date": date or "",
        "numbers": {},
        "matches": matches,
        "extra": {"prize_note": PRIZE_NOTE},
    }
    _finalize(draw, kind)
    return draw


def _finalize(draw: dict, kind: str) -> None:
    """按玩法检查赛果是否完整，并写入 extra 标记。"""
    incomplete_indexes: list[int] = []
    for match in draw.get("matches") or []:
        if kind == "zc6":
            valid = (
                match.get("result") in RESULTS
                and match.get("half_result") in RESULTS
            )
        elif kind == "jq4":
            valid = match.get("result") in GOAL_BUCKETS
        else:
            valid = match.get("result") in RESULTS
        if not valid:
            incomplete_indexes.append(match.get("index"))

    extra = draw.setdefault("extra", {})
    extra["prize_note"] = PRIZE_NOTE
    extra["incomplete"] = bool(incomplete_indexes)
    if incomplete_indexes:
        extra["incomplete_indexes"] = incomplete_indexes
    else:
        extra.pop("incomplete_indexes", None)


def _merge_xml(draw: dict, xml_draw: dict, kind: str) -> None:
    """用 XML 明细补充页面缺失的比分与赛果，不覆盖已有的球队展示名。"""
    page_matches = draw.get("matches") or []
    xml_matches = xml_draw.get("matches") or []
    if len(page_matches) != len(xml_matches):
        return
    for page_match, xml_match in zip(page_matches, xml_matches):
        if xml_match.get("score"):
            page_match["score"] = xml_match["score"]
        if xml_match.get("half_score"):
            page_match["half_score"] = xml_match["half_score"]
        if xml_match.get("result") is not None:
            page_match["result"] = xml_match["result"]
        if kind == "zc6" and xml_match.get("half_result") is not None:
            page_match["half_result"] = xml_match["half_result"]
        if not page_match.get("home"):
            page_match["home"] = xml_match.get("home") or ""
        if not page_match.get("away"):
            page_match["away"] = xml_match.get("away") or ""
    if not draw.get("date") and xml_draw.get("date"):
        draw["date"] = xml_draw["date"]
    _finalize(draw, kind)


# ---------------------------------------------------------------------------
# 抓取入口
# ---------------------------------------------------------------------------


def _load_issue(
    issue: str,
    history_url: str,
    xml_url: str,
    kind: str,
    expected: int,
) -> dict | None:
    xml_text = _try_fetch_xml(issue, xml_url)
    if xml_text:
        draw = _draw_from_xml(xml_text, kind, expected)
        if draw is not None:
            return draw
    try:
        page_html = _fetch_text(history_url.format(issue=issue))
    except Exception:
        return None
    draw = _build_page_draw(page_html, kind, expected)
    if draw is None or draw.get("issue") != issue:
        return None
    return draw


def _collect(
    kind: str,
    latest_url: str,
    history_url: str,
    xml_url: str,
    expected: int,
    limit: int,
) -> list[dict]:
    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = DEFAULT_LIMIT
    requested = max(1, min(requested, DEFAULT_LIMIT))

    page_html = _fetch_text(latest_url)
    latest = _build_page_draw(page_html, kind, expected)
    if latest is None:
        raise ValueError("未能解析赛果页面，请稍后重试")

    issues = _parse_issue_links(page_html, kind)
    ordered_issues = [latest["issue"]] + [
        issue for issue in issues if issue != latest["issue"]
    ]
    # 单次刷新只取最新一期 + 最多 3 个历史期，避免请求过多导致超时；
    # 缓存会随多次刷新逐步累积。
    ordered_issues = ordered_issues[: 1 + MAX_HISTORY_ISSUES]

    draws: list[dict] = []
    for issue in ordered_issues:
        if len(draws) >= requested:
            break
        if issue == latest["issue"]:
            draw = latest
            xml_text = _try_fetch_xml(issue, xml_url)
            if xml_text:
                xml_draw = _draw_from_xml(xml_text, kind, expected)
                if xml_draw is not None:
                    _merge_xml(draw, xml_draw, kind)
        else:
            draw = _load_issue(issue, history_url, xml_url, kind, expected)
        if draw is None:
            continue
        draws.append(draw)

    if not draws:
        raise ValueError("暂无可用赛果数据，请稍后重试")

    draws.sort(
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("issue") or ""),
        ),
        reverse=True,
    )
    return draws[:requested]


def fetch_draws(limit: int = 30) -> list[dict]:
    """返回按时间倒序的胜负彩赛果，至少包含最新一期。"""
    return _collect(
        "sfc",
        LATEST_URL,
        HISTORY_URL,
        XML_URL,
        MATCH_COUNT,
        limit,
    )


# ---------------------------------------------------------------------------
# 投注内容校验与核对
# ---------------------------------------------------------------------------


def _raw_items(payload) -> list | None:
    """把 dict/字符串/列表形式的投注内容展开为逐项列表。"""
    if isinstance(payload, str):
        value = payload
    elif isinstance(payload, dict):
        value = payload.get("picks")
        if value is None:
            value = payload.get("ticket")
    elif isinstance(payload, (list, tuple)):
        value = payload
    else:
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if re.search(r"[\s,/|]", text):
            return [part for part in re.split(r"[\s,/|]+", text) if part]
        return list(text)
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _normalize_single_pick_payload(
    payload,
    count: int,
    index_max: int,
    allowed: tuple[str, ...],
    coerce=None,
) -> tuple[dict | None, list[str]]:
    items = _raw_items(payload)
    if items is None:
        return None, ["投注内容格式不正确"]

    errors: list[str] = []
    if len(items) != count:
        errors.append(f"需要选择 {count} 场，当前为 {len(items)} 场")

    picks: list[dict] = []
    seen: set[int] = set()
    for position, item in enumerate(items):
        if isinstance(item, dict):
            index_raw = item.get("index", position + 1)
            value = item.get("pick")
        else:
            index_raw = position + 1
            value = item

        try:
            index = int(str(index_raw).strip())
        except (TypeError, ValueError):
            errors.append(f"第 {position + 1} 条场次序号无效")
            continue
        if index < 1 or index > index_max:
            errors.append(f"场次序号需在 1–{index_max} 之间")
            continue
        if index in seen:
            errors.append(f"场次 {index} 重复选择")
            continue
        seen.add(index)

        pick = coerce(value) if coerce else _plain_pick(value)
        if pick not in allowed:
            errors.append(f"第 {index} 场选择需为 {'/'.join(allowed)}")
            continue
        picks.append({"index": index, "pick": pick})

    if errors:
        return None, errors
    picks.sort(key=lambda item: item["index"])
    return {"picks": picks}, []


def _incomplete_result(draw: dict, detail: dict | None = None) -> dict:
    payload = {
        "ok": False,
        "hit": False,
        "prize_level": None,
        "detail": {"issue": (draw or {}).get("issue"), "reason": "incomplete"},
        "message": "赛果不完整，暂时无法核对，请稍后重试",
    }
    if detail:
        payload["detail"].update(detail)
    return payload


def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
    """校验 14 场是否全覆盖且每场为 3/1/0。"""
    normalized, errors = _normalize_single_pick_payload(
        payload, MATCH_COUNT, MATCH_COUNT, RESULTS
    )
    if errors:
        return {"ok": False, "normalized": normalized or {}, "errors": errors}
    return {"ok": True, "normalized": normalized or {}, "errors": []}


def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
    """逐场比对赛果：14 场全中一等奖、13 场二等奖，其余未中奖。"""
    validation = validate_ticket(payload, play_type)
    if not validation["ok"]:
        return {
            "ok": False,
            "hit": False,
            "prize_level": None,
            "detail": {"errors": validation["errors"]},
            "message": "投注内容有误：" + "；".join(validation["errors"]),
        }

    results: dict[int, str | None] = {}
    for match in (draw or {}).get("matches") or []:
        try:
            index = int(match.get("index"))
        except (TypeError, ValueError):
            continue
        results[index] = match.get("result")

    if any(results.get(index) not in RESULTS for index in range(1, MATCH_COUNT + 1)):
        return _incomplete_result(draw)

    picks = validation["normalized"]["picks"]
    hits = 0
    wrong_indexes: list[int] = []
    for item in picks:
        if results.get(item["index"]) == item["pick"]:
            hits += 1
        else:
            wrong_indexes.append(item["index"])

    if hits == MATCH_COUNT:
        prize_level = "一等奖"
    elif hits == MATCH_COUNT - 1:
        prize_level = "二等奖"
    else:
        prize_level = None
    hit = prize_level is not None

    detail = {
        "issue": (draw or {}).get("issue"),
        "hits": hits,
        "total": MATCH_COUNT,
        "wrong_indexes": wrong_indexes,
    }
    if hit:
        message = f"命中 {hits} 场，中得{prize_level}；奖金以官方公告为准"
    else:
        message = f"命中 {hits} 场，未中奖；奖金以官方公告为准"
    return {
        "ok": True,
        "hit": hit,
        "prize_level": prize_level,
        "detail": detail,
        "message": message,
    }

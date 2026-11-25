"""6场半全场适配器：每场同时记录半场与全场结果（3/1/0）。

页面直接给出版半场/全场结果；同站赛果 XML 若提供比分，则补充比分明细。
核对时半场与全场共 12 个选择全部命中为一等奖。
"""

from __future__ import annotations

from . import sfc14

SOURCE_NAME = sfc14.SOURCE_NAME

LATEST_URL = "https://kaijiang.500.com/zc6.shtml"
HISTORY_URL = "https://kaijiang.500.com/shtml/zc6/{issue}.shtml"
XML_URL = "https://kaijiang.500.com/static/info/kaijiang/xml/zc6/{issue}.xml"

MATCH_COUNT = 6
SELECT_COUNT = MATCH_COUNT * 2
RESULTS = sfc14.RESULTS
MAX_HISTORY_ISSUES = 3
FALLBACK_HISTORY = 5


def _issue_from_page(url: str) -> str | None:
    """从页面表格读取期号；页面被拦截或结构异常时返回 None。"""
    try:
        page_html = sfc14._fetch_text(url)
    except Exception:
        return None
    table = sfc14._first_result_table(page_html or "")
    if not table:
        return None
    return sfc14._parse_issue(table)


def _expand_issues(base: str, history: int = FALLBACK_HISTORY) -> list[str]:
    try:
        value = int(base)
    except (TypeError, ValueError):
        return [base]
    return [f"{value - offset:05d}" for offset in range(history + 1)]


def _candidate_issues() -> list[str]:
    """优先使用 zc6 页面期号，其次用胜负彩最新期号，再向前展开。"""
    bases: list[str] = []
    page_issue = _issue_from_page(LATEST_URL)
    if page_issue:
        bases.append(page_issue)
    sfc_issue = _issue_from_page(sfc14.LATEST_URL)
    if sfc_issue and sfc_issue not in bases:
        bases.append(sfc_issue)

    candidates: list[str] = []
    for base in bases:
        for issue in _expand_issues(base):
            if issue not in candidates:
                candidates.append(issue)
    return candidates


def fetch_draws(limit: int = 30) -> list[dict]:
    """XML 优先抓取 6 场半全场赛果；页面被拦截时不影响 XML 路径。"""
    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = sfc14.DEFAULT_LIMIT
    requested = max(1, min(requested, sfc14.DEFAULT_LIMIT))
    target = min(requested, 1 + MAX_HISTORY_ISSUES)

    draws: list[dict] = []
    for issue in _candidate_issues():
        if len(draws) >= target:
            break
        xml_text = sfc14._try_fetch_xml(issue, XML_URL)
        if not xml_text:
            continue
        draw = sfc14._draw_from_xml(xml_text, "zc6", MATCH_COUNT)
        if draw is not None:
            draws.append(draw)

    # 页面仅作为补充：XML 全部不可用时再尝试解析 zc6 页面。
    if not draws:
        try:
            page_html = sfc14._fetch_text(LATEST_URL)
        except Exception:
            page_html = ""
        draw = (
            sfc14._build_page_draw(page_html, "zc6", MATCH_COUNT)
            if page_html
            else None
        )
        if draw is not None:
            draws.append(draw)

    if not draws:
        raise ValueError("未能获取 6 场半全场赛果，请稍后重试")

    draws.sort(
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("issue") or ""),
        ),
        reverse=True,
    )
    return draws[:requested]


def _normalize_items(payload) -> tuple[list | None, list[str]]:
    items = sfc14._raw_items(payload)
    if items is None:
        return None, ["投注内容格式不正确"]
    if len(items) == SELECT_COUNT and all(not isinstance(item, dict) for item in items):
        items = [
            {
                "index": position // 2 + 1,
                "half": items[position],
                "full": items[position + 1],
            }
            for position in range(0, SELECT_COUNT, 2)
        ]
    elif len(items) == MATCH_COUNT and all(
        isinstance(item, str) and len(item.strip()) == 2 for item in items
    ):
        items = [
            {
                "index": position + 1,
                "half": item.strip()[0],
                "full": item.strip()[1],
            }
            for position, item in enumerate(items)
        ]
    return items, []


def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
    """校验 6 场是否全覆盖，且每场半场、全场结果均为 3/1/0。"""
    items, errors = _normalize_items(payload)
    if errors:
        return {"ok": False, "normalized": {}, "errors": errors}

    if len(items) != MATCH_COUNT:
        errors.append(f"需要选择 {MATCH_COUNT} 场，当前为 {len(items)} 场")

    picks: list[dict] = []
    seen: set[int] = set()
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"第 {position + 1} 条投注内容格式不正确")
            continue
        try:
            index = int(str(item.get("index", position + 1)).strip())
        except (TypeError, ValueError):
            errors.append(f"第 {position + 1} 条场次序号无效")
            continue
        if index < 1 or index > MATCH_COUNT:
            errors.append(f"场次序号需在 1–{MATCH_COUNT} 之间")
            continue
        if index in seen:
            errors.append(f"场次 {index} 重复选择")
            continue
        seen.add(index)

        half = sfc14._plain_pick(item.get("half"))
        full = sfc14._plain_pick(item.get("full"))
        valid = True
        if half not in RESULTS:
            errors.append(f"第 {index} 场半场选择需为 3/1/0")
            valid = False
        if full not in RESULTS:
            errors.append(f"第 {index} 场全场选择需为 3/1/0")
            valid = False
        if valid:
            picks.append({"index": index, "half": half, "full": full})

    if errors:
        return {"ok": False, "normalized": {}, "errors": errors}
    picks.sort(key=lambda item: item["index"])
    return {"ok": True, "normalized": {"picks": picks}, "errors": []}


def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
    """半场与全场共 12 个选择全部命中为一等奖，其余未中奖。"""
    validation = validate_ticket(payload, play_type)
    if not validation["ok"]:
        return {
            "ok": False,
            "hit": False,
            "prize_level": None,
            "detail": {"errors": validation["errors"]},
            "message": "投注内容有误：" + "；".join(validation["errors"]),
        }

    matches: dict[int, dict] = {}
    for match in (draw or {}).get("matches") or []:
        try:
            index = int(match.get("index"))
        except (TypeError, ValueError):
            continue
        matches[index] = match

    for index in range(1, MATCH_COUNT + 1):
        match = matches.get(index) or {}
        if (
            match.get("result") not in RESULTS
            or match.get("half_result") not in RESULTS
        ):
            return sfc14._incomplete_result(draw)

    picks = validation["normalized"]["picks"]
    hits = 0
    detail_matches: list[dict] = []
    for item in picks:
        match = matches[item["index"]]
        half_hit = match.get("half_result") == item["half"]
        full_hit = match.get("result") == item["full"]
        hits += int(half_hit) + int(full_hit)
        detail_matches.append(
            {
                "index": item["index"],
                "half_hit": half_hit,
                "full_hit": full_hit,
                "half_pick": item["half"],
                "full_pick": item["full"],
                "half_result": match.get("half_result"),
                "full_result": match.get("result"),
            }
        )

    hit = hits == SELECT_COUNT
    prize_level = "一等奖" if hit else None
    detail = {
        "issue": (draw or {}).get("issue"),
        "hits": hits,
        "total": SELECT_COUNT,
        "matches": detail_matches,
    }
    if hit:
        message = f"命中 {hits} 个选择，中得一等奖；奖金以官方公告为准"
    else:
        message = f"命中 {hits} 个选择，未中奖；奖金以官方公告为准"
    return {
        "ok": True,
        "hit": hit,
        "prize_level": prize_level,
        "detail": detail,
        "message": message,
    }

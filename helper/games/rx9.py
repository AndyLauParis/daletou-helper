"""任选9场适配器：与胜负彩14场共用同一期、同一份 14 场赛果。

只从中选择 9 场核对；抓取与解析直接复用 `sfc14`，避免重复实现。
"""

from __future__ import annotations

from . import sfc14

SOURCE_NAME = sfc14.SOURCE_NAME

SELECT_COUNT = 9
INDEX_MAX = sfc14.MATCH_COUNT
RESULTS = sfc14.RESULTS


def fetch_draws(limit: int = 30) -> list[dict]:
    """任选9场与胜负彩共用同一期赛果。"""
    return sfc14.fetch_draws(limit=limit)


def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
    """校验是否恰好选择 9 场，场次 1–14 不重复，且每场为 3/1/0。"""
    normalized, errors = sfc14._normalize_single_pick_payload(
        payload, SELECT_COUNT, INDEX_MAX, RESULTS
    )
    if errors:
        return {"ok": False, "normalized": normalized or {}, "errors": errors}
    return {"ok": True, "normalized": normalized or {}, "errors": []}


def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
    """所选 9 场全部命中即中奖（任选9场只设一个奖级）。"""
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

    picks = validation["normalized"]["picks"]
    if any(results.get(item["index"]) not in RESULTS for item in picks):
        return sfc14._incomplete_result(draw)

    hits = 0
    wrong_indexes: list[int] = []
    for item in picks:
        if results.get(item["index"]) == item["pick"]:
            hits += 1
        else:
            wrong_indexes.append(item["index"])

    hit = hits == SELECT_COUNT
    prize_level = "任选9场" if hit else None

    detail = {
        "issue": (draw or {}).get("issue"),
        "hits": hits,
        "total": SELECT_COUNT,
        "wrong_indexes": wrong_indexes,
    }
    if hit:
        message = f"命中 {hits} 场，中得任选9场奖；奖金以官方公告为准"
    else:
        message = f"命中 {hits} 场，未中奖；奖金以官方公告为准"
    return {
        "ok": True,
        "hit": hit,
        "prize_level": prize_level,
        "detail": detail,
        "message": message,
    }

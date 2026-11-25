"""4场进球适配器：每场按总进球档位 0/1/2/3+ 记录与核对。

页面按主客队分别给出进球档位，模块把两队档位合并为该场总进球档位；
同站的赛果 XML 若提供具体比分，则直接由比分计算更精确的总进球档位。
"""

from __future__ import annotations

from . import sfc14

SOURCE_NAME = sfc14.SOURCE_NAME

LATEST_URL = "https://kaijiang.500.com/jq4.shtml"
HISTORY_URL = "https://kaijiang.500.com/shtml/jq4/{issue}.shtml"
XML_URL = "https://kaijiang.500.com/static/info/kaijiang/xml/jq4/{issue}.xml"

MATCH_COUNT = 4
GOAL_BUCKETS = sfc14.GOAL_BUCKETS


def _coerce_bucket(value) -> str:
    bucket = sfc14._goal_bucket(value)
    return bucket if bucket is not None else sfc14._plain_pick(value)


def fetch_draws(limit: int = 30) -> list[dict]:
    """返回按时间倒序的 4 场进球赛果。"""
    return sfc14._collect(
        "jq4",
        LATEST_URL,
        HISTORY_URL,
        XML_URL,
        MATCH_COUNT,
        limit,
    )


def validate_ticket(payload: dict, play_type: str | None = None) -> dict:
    """校验 4 场是否全覆盖，且每场总进球档位为 0/1/2/3+。"""
    normalized, errors = sfc14._normalize_single_pick_payload(
        payload,
        MATCH_COUNT,
        MATCH_COUNT,
        GOAL_BUCKETS,
        coerce=_coerce_bucket,
    )
    if errors:
        return {"ok": False, "normalized": normalized or {}, "errors": errors}
    return {"ok": True, "normalized": normalized or {}, "errors": []}


def check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict:
    """4 场总进球档位全部命中为一等奖，其余未中奖。"""
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

    if any(results.get(index) not in GOAL_BUCKETS for index in range(1, MATCH_COUNT + 1)):
        return sfc14._incomplete_result(draw)

    picks = validation["normalized"]["picks"]
    hits = 0
    wrong_indexes: list[int] = []
    for item in picks:
        if results.get(item["index"]) == item["pick"]:
            hits += 1
        else:
            wrong_indexes.append(item["index"])

    hit = hits == MATCH_COUNT
    prize_level = "一等奖" if hit else None

    detail = {
        "issue": (draw or {}).get("issue"),
        "hits": hits,
        "total": MATCH_COUNT,
        "wrong_indexes": wrong_indexes,
    }
    if hit:
        message = f"命中 {hits} 场，中得一等奖；奖金以官方公告为准"
    else:
        message = f"命中 {hits} 场，未中奖；奖金以官方公告为准"
    return {
        "ok": True,
        "hit": hit,
        "prize_level": prize_level,
        "detail": detail,
        "message": message,
    }

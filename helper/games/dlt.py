"""大乐透（超级大乐透）适配器。

只读复用现有 `core.store` 的开奖数据与 `core.rules` 的奖级规则，不改变其行为。
"""

from __future__ import annotations

import re

from core import store as core_store
from core.rules import tier_for_hits

SOURCE_NAME = "国家体彩中心 / 500.com"

FRONT_POOL = 35
BACK_POOL = 12
FRONT_PICK = 5
BACK_PICK = 2

PRIZE_LABELS: dict[int, str] = {
    1: "一等奖",
    2: "二等奖",
    3: "三等奖",
    4: "四等奖",
    5: "五等奖",
    6: "六等奖",
    7: "七等奖",
}


class DataFetchError(RuntimeError):
    """读取大乐透开奖数据失败。"""


def _as_int_list(raw) -> tuple[list[int], list[str]]:
    if raw is None:
        return [], ["缺少号码"]
    if isinstance(raw, str):
        tokens: list = re.split(r"[\s,，]+", raw.strip())
    elif isinstance(raw, (list, tuple)):
        tokens = list(raw)
    else:
        return [], ["号码格式不正确"]

    values: list[int] = []
    for token in tokens:
        if token == "":
            continue
        if isinstance(token, bool):
            return [], ["号码格式不正确"]
        if isinstance(token, int):
            values.append(token)
            continue
        if isinstance(token, str) and token.strip().isdigit():
            values.append(int(token.strip()))
            continue
        return [], ["号码格式不正确"]
    return values, []


def _extract_sides(payload) -> tuple[list[int], list[int], list[str]]:
    """把 dict 或字符串投注内容拆成前区、后区号码。"""
    if isinstance(payload, dict):
        front, front_errors = _as_int_list(payload.get("front"))
        back, back_errors = _as_int_list(payload.get("back"))
        return front, back, front_errors + back_errors

    if isinstance(payload, str):
        text = payload.strip().replace("，", " ").replace(",", " ")
        if "+" in text:
            left, right = text.split("+", 1)
            front, front_errors = _as_int_list(left)
            back, back_errors = _as_int_list(right)
            return front, back, front_errors + back_errors
        tokens = text.split()
        if len(tokens) != FRONT_PICK + BACK_PICK:
            return [], [], ["需要前区 5 个号码和后区 2 个号码"]
        front, front_errors = _as_int_list(tokens[:FRONT_PICK])
        back, back_errors = _as_int_list(tokens[FRONT_PICK:])
        return front, back, front_errors + back_errors

    return [], [], ["号码格式不正确"]


def _is_additional(play_type) -> bool:
    text = "" if play_type is None else str(play_type).strip().lower()
    return text in {"additional", "追加", "add"}


def validate_ticket(payload, play_type: str | None = None) -> dict:
    """校验号码个数、范围与去重；追加投注仅作标记。"""
    front, back, parse_errors = _extract_sides(payload)
    if parse_errors:
        return {
            "ok": False,
            "normalized": {"front": [], "back": [], "play_type": None},
            "errors": parse_errors,
        }

    errors: list[str] = []
    if len(front) != FRONT_PICK:
        errors.append("前区需要 5 个号码")
    elif any(number < 1 or number > FRONT_POOL for number in front):
        errors.append("前区号码范围应为 1-35")
    elif len(set(front)) != FRONT_PICK:
        errors.append("前区号码不能重复")

    if len(back) != BACK_PICK:
        errors.append("后区需要 2 个号码")
    elif any(number < 1 or number > BACK_POOL for number in back):
        errors.append("后区号码范围应为 1-12")
    elif len(set(back)) != BACK_PICK:
        errors.append("后区号码不能重复")

    return {
        "ok": not errors,
        "normalized": {
            "front": sorted(front),
            "back": sorted(back),
            "play_type": "additional" if _is_additional(play_type) else None,
        },
        "errors": errors,
    }


def check_ticket(payload, play_type: str | None, draw: dict) -> dict:
    """按 `core.rules.tier_for_hits` 核对奖级，不编造奖金金额。"""
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
    draw_back = numbers.get("back") or []
    if len(draw_front) != FRONT_PICK or len(draw_back) != BACK_PICK:
        return {
            "ok": False,
            "hit": False,
            "prize_level": None,
            "detail": {},
            "message": "开奖数据不完整，无法核对",
        }

    normalized = validation["normalized"]
    front_hits = len(set(normalized["front"]) & set(draw_front))
    back_hits = len(set(normalized["back"]) & set(draw_back))
    tier = tier_for_hits(front_hits, back_hits)
    label = PRIZE_LABELS.get(tier)

    if label:
        message = (
            f"命中前区 {front_hits} 个、后区 {back_hits} 个，中得{label}；"
            "奖金以官方公告为准，请通过官方线下渠道兑奖。"
        )
    else:
        message = f"命中前区 {front_hits} 个、后区 {back_hits} 个，未中奖。"
    if normalized["play_type"] == "additional":
        message += "追加奖金以官方规则为准。"

    return {
        "ok": True,
        "hit": tier is not None,
        "prize_level": label,
        "detail": {
            "front_hits": front_hits,
            "back_hits": back_hits,
            "tier": tier,
        },
        "message": message,
    }


def fetch_draws(limit: int = 30) -> list[dict]:
    """从 `core.store` 读取最近开奖，映射为统一结构（时间倒序）。"""
    try:
        core_store.ensure_data()
        raw_draws = core_store.get_draws()
    except Exception as exc:  # 由框架决定降级或使用旧缓存
        raise DataFetchError(f"读取大乐透开奖数据失败：{exc}") from exc

    if not raw_draws:
        raise DataFetchError("暂无大乐透开奖数据")

    draws: list[dict] = []
    for item in raw_draws:
        try:
            front = sorted(int(number) for number in item["front"])
            back = sorted(int(number) for number in item["back"])
            issue = str(item["issue"]).strip()
            date = str(item["date"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not issue or not date:
            continue
        if len(front) != FRONT_PICK or len(back) != BACK_PICK:
            continue
        draws.append(
            {
                "issue": issue,
                "date": date,
                "numbers": {"front": front, "back": back},
                "extra": {"pool": item.get("pool")},
            }
        )

    if not draws:
        raise DataFetchError("开奖数据格式异常：未解析到有效记录")

    draws.sort(key=lambda draw: (draw["date"], draw["issue"]), reverse=True)
    return draws[: max(0, int(limit))]

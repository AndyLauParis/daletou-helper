"""娱乐选号：按用户选择的组合规则生成号码。

这里生成的是随机组合，不是预测结果。所有方法只改变号码的组合方式，
不会改变任何一注彩票的中奖概率。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean, pstdev

from . import lab
from .games import cache, registry

DISCLAIMER = (
    "本工具所有预测结果仅供娱乐和参考，不构成任何购彩建议，"
    "彩票有风险，购彩需理性"
)

NOTICE = (
    "所有号码组合的中奖概率相同。本工具不预测开奖，也不提高中奖概率；"
    "请理性购彩，未成年人不得使用。"
)


@dataclass(frozen=True)
class PickerMethod:
    key: str
    label: str
    description: str
    scope: str = "all"  # all | lottery


METHODS: tuple[PickerMethod, ...] = (
    PickerMethod(
        "random",
        "纯随机",
        "每个号码等概率抽取，不使用任何历史数据加权。",
    ),
    PickerMethod(
        "hot",
        "历史热号",
        "按历史出现次数加权，出现越多的号码被抽中的权重越高。"
        "历史频率不改变下一期概率，本方式只用于生成娱乐组合。",
    ),
    PickerMethod(
        "cold",
        "历史冷号",
        "按历史出现次数反向加权，出现越少的号码权重越高。"
        "冷号并不“该出”，本方式只用于生成娱乐组合。",
    ),
    PickerMethod(
        "omission",
        "遗漏周期",
        "优先抽取当前遗漏接近历史平均遗漏的号码。"
        "遗漏周期不代表开奖节奏，本方式不构成预测。",
    ),
    PickerMethod(
        "odd_even",
        "奇偶均衡",
        "按号码池的奇偶比例确定每注的奇数个数，再随机抽取。"
        "比例均衡只是组合规则，不提高中奖概率。",
    ),
    PickerMethod(
        "sum_range",
        "和值区间",
        "在历史和值的常见区间内随机组合，避开极端和值。"
        "和值区间不预测开奖，也不提高中奖概率。",
    ),
    PickerMethod(
        "zone_balance",
        "分区均衡",
        "把号码池分为前中后三区，按区均衡分配号码。"
        "分区只是组合约束，不提高中奖概率。",
        scope="lottery",
    ),
)

METHODS_BY_KEY = {method.key: method for method in METHODS}


class PickerError(ValueError):
    """选号参数或历史数据不可用。"""


def _display_width(group: lab.Group) -> int:
    return 2 if group.pool > 10 else 1


def _display(value: int, group: lab.Group) -> str:
    return f"{value:0{_display_width(group)}d}"


def _load_history(code: str, window: int = 100) -> dict | None:
    """读取历史缓存并计算频次、当前遗漏与和值分布；样本不足时返回 None。"""
    draws = lab.load_draws(code, limit=200)
    profile = lab.PROFILES.get(code)
    if profile is None or not draws:
        return None

    valid: list[dict[str, list[int]]] = []
    issues: list[str] = []
    for draw in draws[:window]:
        groups = lab.extract_groups(profile, draw)
        if groups is None:
            continue
        valid.append(groups)
        issues.append(str(draw.get("issue") or ""))
    if len(valid) < 10:
        return None

    counts: dict[str, dict[int, int]] = {}
    omissions: dict[str, dict[int, int]] = {}
    sums: list[int] = []
    for group in profile.groups:
        counts[group.key] = {number: 0 for number in group.numbers}
        omissions[group.key] = {number: 0 for number in group.numbers}

    for index, groups in enumerate(valid):
        for group in profile.groups:
            values = groups.get(group.key) or []
            for number in values:
                if number in counts[group.key]:
                    counts[group.key][number] += 1
                    if omissions[group.key][number] == 0:
                        omissions[group.key][number] = index
        sums.append(sum(sum(groups.get(group.key) or []) for group in profile.groups))

    # 当前遗漏：最新一期已出现记为 0，否则为距离最新一期的期数
    for group in profile.groups:
        for number in group.numbers:
            position = None
            for index, groups in enumerate(valid):
                if number in (groups.get(group.key) or []):
                    position = index
                    break
            omissions[group.key][number] = position if position is not None else len(valid)

    return {
        "draw_count": len(draws),
        "window": len(valid),
        "latest_issue": issues[0] if issues else None,
        "counts": counts,
        "omissions": omissions,
        "sum_mean": fmean(sums) if sums else 0.0,
        "sum_stdev": pstdev(sums) if len(sums) > 1 else 0.0,
    }


def _weights(method: str, group: lab.Group, history: dict | None) -> list[float]:
    numbers = group.numbers
    if not history:
        return [1.0] * len(numbers)
    counts = history["counts"].get(group.key) or {}
    omissions = history["omissions"].get(group.key) or {}
    if method == "hot":
        return [float((counts.get(number, 0) + 1) ** 2) for number in numbers]
    if method == "cold":
        highest = max(counts.values(), default=0) + 1
        return [float(highest - counts.get(number, 0) + 1) for number in numbers]
    if method == "omission":
        mean_omission = fmean(omissions.values()) if omissions else 0.0
        return [
            1.0 / (1.0 + abs(omissions.get(number, 0) - mean_omission))
            for number in numbers
        ]
    return [1.0] * len(numbers)


def _weighted_sample(
    rng: random.Random,
    numbers: list[int],
    weights: list[float],
    pick: int,
) -> list[int]:
    pool = list(zip(numbers, weights))
    chosen: list[int] = []
    while len(chosen) < pick and pool:
        total = sum(weight for _, weight in pool)
        if total <= 0:
            index = rng.randrange(len(pool))
        else:
            point = rng.random() * total
            accumulated = 0.0
            index = len(pool) - 1
            for position, (_, weight) in enumerate(pool):
                accumulated += weight
                if point <= accumulated:
                    index = position
                    break
        chosen.append(pool.pop(index)[0])
    return sorted(chosen)


def _odd_target(group: lab.Group, rng: random.Random) -> int:
    odd_count = sum(1 for number in group.numbers if number % 2)
    expected = group.ticket * odd_count / group.pool
    base = int(expected)
    return base + (1 if rng.random() < expected - base else 0)


def _sample_odd_even(
    rng: random.Random, group: lab.Group
) -> list[int]:
    odds = [number for number in group.numbers if number % 2]
    evens = [number for number in group.numbers if number % 2 == 0]
    target = min(_odd_target(group, rng), len(odds))
    even_target = min(group.ticket - target, len(evens))
    chosen = rng.sample(odds, target) + rng.sample(evens, even_target)
    if len(chosen) < group.ticket:
        remaining = [
            number
            for number in group.numbers
            if number not in set(chosen)
        ]
        chosen += rng.sample(remaining, group.ticket - len(chosen))
    return sorted(chosen)


def _zones(numbers: list[int]) -> tuple[list[int], list[int], list[int]]:
    first = round(len(numbers) / 3)
    second = round(len(numbers) * 2 / 3)
    return numbers[:first], numbers[first:second], numbers[second:]


def _sample_zones(rng: random.Random, group: lab.Group) -> list[int]:
    zones = _zones(group.numbers)
    base, extra = divmod(group.ticket, 3)
    counts = [base + (1 if index < extra else 0) for index in range(3)]
    chosen: list[int] = []
    for zone, count in zip(zones, counts):
        if count > len(zone):
            # 极端小号码池时退回整体随机，避免无法凑够号码
            return rng.sample(group.numbers, group.ticket)
        chosen.extend(rng.sample(zone, count))
    return sorted(chosen)


def _sample_groups(
    profile: lab.Profile,
    method: str,
    history: dict | None,
    rng: random.Random,
) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for group in profile.groups:
        if method == "odd_even":
            result[group.key] = _sample_odd_even(rng, group)
        elif method == "zone_balance":
            # 只对每注至少 3 个号码、号码池足够大的分组做分区；
            # 后区、特别号等单号分组保持整体随机，避免固定偏向第一区。
            if group.ticket >= 3 and len(group.numbers) >= 9:
                result[group.key] = _sample_zones(rng, group)
            else:
                result[group.key] = rng.sample(group.numbers, group.ticket)
        else:
            numbers = group.numbers
            weights = _weights(method, group, history)
            result[group.key] = _weighted_sample(
                rng, numbers, weights, group.ticket
            )
    return result


def _ticket_sum(ticket: dict[str, list[int]]) -> int:
    return sum(sum(values) for values in ticket.values())


def _sum_range_ticket(
    profile: lab.Profile,
    history: dict | None,
    rng: random.Random,
) -> tuple[dict[str, list[int]], bool]:
    """按历史和值区间做拒绝采样；返回 (号码, 是否放宽区间)。"""
    if not history or history["sum_stdev"] <= 0:
        return _sample_groups(profile, "random", history, rng), True
    low = history["sum_mean"] - 0.5 * history["sum_stdev"]
    high = history["sum_mean"] + 0.5 * history["sum_stdev"]
    best: dict[str, list[int]] | None = None
    best_distance = float("inf")
    for _ in range(400):
        candidate = _sample_groups(profile, "random", history, rng)
        total = _ticket_sum(candidate)
        if low <= total <= high:
            return candidate, False
        distance = min(abs(total - low), abs(total - high))
        if distance < best_distance:
            best = candidate
            best_distance = distance
    return best or _sample_groups(profile, "random", history, rng), True


def _ticket_payload(
    profile: lab.Profile, values: dict[str, list[int]]
) -> list[dict]:
    groups = []
    for group in profile.groups:
        numbers = values.get(group.key) or []
        groups.append(
            {
                "key": group.key,
                "label": group.label,
                "numbers": [
                    {"value": number, "display": _display(number, group)}
                    for number in numbers
                ],
            }
        )
    return groups


def generate(
    code: str,
    method_key: str,
    tickets: int = 1,
    rng: random.Random | None = None,
) -> dict:
    profile = lab.PROFILES.get(code)
    if profile is None:
        raise PickerError("该游戏暂不支持娱乐选号")
    method = METHODS_BY_KEY.get(method_key)
    if method is None:
        raise PickerError("未知的选号方式")
    if method.scope == "lottery" and profile.digit_mode:
        raise PickerError("该选号方式仅适用于乐透型游戏")
    if not 1 <= tickets <= 10:
        raise PickerError("生成注数需在 1 到 10 之间")

    rng = rng or random.Random()
    history = _load_history(code)
    fallback = False
    effective = method_key
    reason = None

    if method_key in ("hot", "cold", "omission", "sum_range") and not history:
        effective = "random"
        fallback = True
        reason = "历史样本不足，本次已按纯随机生成"

    generated: list[list[dict]] = []
    seen: set[tuple] = set()
    relaxed = False
    attempts = 0
    while len(generated) < tickets and attempts < tickets * 40:
        attempts += 1
        if effective == "sum_range":
            values, relaxed_once = _sum_range_ticket(profile, history, rng)
            relaxed = relaxed or relaxed_once
        else:
            values = _sample_groups(profile, effective, history, rng)
        signature = tuple(
            tuple(values.get(group.key) or []) for group in profile.groups
        )
        if signature in seen:
            continue
        seen.add(signature)
        generated.append(_ticket_payload(profile, values))

    if not generated:
        raise PickerError("生成失败，请重试")

    data = {
        "draw_count": history["draw_count"] if history else 0,
        "window": history["window"] if history else 0,
        "latest_issue": history["latest_issue"] if history else None,
        "fallback": fallback,
    }
    constraints = []
    if fallback and reason:
        constraints.append(reason)
    if relaxed:
        constraints.append("和值区间未能完全满足，已放宽约束")

    return {
        "game": {
            "code": code,
            "name": getattr(registry.get_game(code), "name", code),
            "format_summary": getattr(
                registry.get_game(code), "format_summary", ""
            ),
            "digit_mode": profile.digit_mode,
        },
        "method": {
            "key": method.key,
            "label": method.label,
            "description": method.description,
            "caveat": "该方式只改变号码组合规则，不改变任何一注彩票的中奖概率。",
            "effective": effective,
            "fallback": fallback,
        },
        "tickets": generated,
        "data": data,
        "constraints": constraints,
        "disclaimer": DISCLAIMER,
        "notice": NOTICE,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def options() -> dict:
    games = []
    for code, profile in lab.PROFILES.items():
        meta = registry.get_game(code)
        if meta is None:
            continue
        payload = cache.load_cache(code)
        games.append(
            {
                "code": code,
                "name": meta.name,
                "format_summary": meta.format_summary,
                "digit_mode": profile.digit_mode,
                "draw_count": len(payload.get("draws") or []),
            }
        )
    return {
        "games": games,
        "methods": [
            {
                "key": method.key,
                "label": method.label,
                "description": method.description,
                "scope": method.scope,
            }
            for method in METHODS
        ],
        "disclaimer": DISCLAIMER,
        "notice": NOTICE,
    }

"""大乐透奖级规则引擎（2026-02-02 起，7 个奖级 / 13 个中奖条件）。

组合数口径：前区命中 f 个的组合数 = C(5,f)·C(30,5-f)；
后区命中 b 个的组合数 = C(2,b)·C(10,2-b)；两者相乘即为该条件的注数。
"""

from __future__ import annotations

import math

from .constants import (
    BACK_COMBOS,
    BACK_PICK,
    BACK_POOL,
    CURRENT_PRIZE_RATE,
    FRONT_COMBOS,
    FRONT_PICK,
    FRONT_POOL,
    JACKPOT_CAP_ADDON,
    JACKPOT_CAP_BASIC,
    POOL_THRESHOLD,
    RETURN_RATE,
    TICKET_PRICE,
    TOTAL_COMBOS,
)

MODEL_NOTE = (
    "视频/文档使用 9 个奖级与 51% 返奖率口径；本表按 2026-02-02 起 7 个奖级官方规则计算，结论一致。"
)

# (奖级, 名称, 中奖条件列表[(前区命中, 后区命中)])
TIER_CONDITIONS: list[tuple[int, str, list[tuple[int, int]]]] = [
    (1, "一等奖", [(5, 2)]),
    (2, "二等奖", [(5, 1)]),
    (3, "三等奖", [(5, 0), (4, 2)]),
    (4, "四等奖", [(4, 1)]),
    (5, "五等奖", [(4, 0), (3, 2)]),
    (6, "六等奖", [(3, 1), (2, 2)]),
    (7, "七等奖", [(3, 0), (2, 1), (1, 2), (0, 2)]),
]

# 固定奖两档：奖池 < 8 亿 / ≥ 8 亿
FIXED_PRIZES_NORMAL: dict[int, int] = {3: 5000, 4: 300, 5: 150, 6: 15, 7: 5}
FIXED_PRIZES_HIGH: dict[int, int] = {3: 6666, 4: 380, 5: 200, 6: 18, 7: 7}

# 官方公布的各奖级组合数，用于自检
EXPECTED_TIER_COMBOS = [1, 20, 195, 3000, 11100, 127600, 1287281]
EXPECTED_ANY_PRIZE_COMBOS = 1_429_197


def conditioned_combos(front_hits: int, back_hits: int) -> int:
    """单一中奖条件对应的注数。"""
    return (
        math.comb(FRONT_PICK, front_hits)
        * math.comb(FRONT_POOL - FRONT_PICK, FRONT_PICK - front_hits)
        * math.comb(BACK_PICK, back_hits)
        * math.comb(BACK_POOL - BACK_PICK, BACK_PICK - back_hits)
    )


def tier_combos() -> dict[int, int]:
    """每个奖级的注数（同一奖级多个条件求和）。"""
    return {
        tier: sum(conditioned_combos(f, b) for f, b in conditions)
        for tier, _label, conditions in TIER_CONDITIONS
    }


def _condition_text(conditions: list[tuple[int, int]]) -> str:
    return " 或 ".join(f"{f}+{b}" for f, b in conditions)


def fixed_prize_map(pool: float | None = None) -> dict[int, float]:
    """按奖池档位返回三至七等奖的固定奖金。"""
    effective_pool = float(pool or 0)
    source = FIXED_PRIZES_HIGH if effective_pool >= POOL_THRESHOLD else FIXED_PRIZES_NORMAL
    return {tier: float(prize) for tier, prize in source.items()}


def tier_for_hits(front_hits: int, back_hits: int) -> int | None:
    """命中数 -> 奖级；未中奖返回 None。"""
    for tier, _label, conditions in TIER_CONDITIONS:
        if (front_hits, back_hits) in conditions:
            return tier
    return None


def get_rule_table(pool: float | None = None, mode: str = "rules") -> dict:
    """当前 7 奖级规则表（组合数、概率、固定奖、口径说明）。"""
    effective_pool = float(pool or 0)
    fixed = fixed_prize_map(effective_pool)
    combos_by_tier = tier_combos()

    assert [combos_by_tier[t] for t in range(1, 8)] == EXPECTED_TIER_COMBOS, combos_by_tier
    any_prize_combos = sum(combos_by_tier.values())
    assert any_prize_combos == EXPECTED_ANY_PRIZE_COMBOS, any_prize_combos

    tiers = []
    for tier, label, conditions in TIER_CONDITIONS:
        combos = combos_by_tier[tier]
        is_fixed = tier >= 3
        tiers.append(
            {
                "tier": tier,
                "label": label,
                "conditions": [[f, b] for f, b in conditions],
                "condition_text": _condition_text(conditions),
                "combos": combos,
                "probability": combos / TOTAL_COMBOS,
                "prize": fixed[tier] if is_fixed else None,
                "prize_type": "固定" if is_fixed else "浮动",
            }
        )

    return {
        "mode": mode,
        "pool": effective_pool,
        "pool_mode": "high" if effective_pool >= POOL_THRESHOLD else "normal",
        "pool_threshold": POOL_THRESHOLD,
        "ticket_price": TICKET_PRICE,
        "front_pool": FRONT_POOL,
        "back_pool": BACK_POOL,
        "front_combos": FRONT_COMBOS,
        "back_combos": BACK_COMBOS,
        "total_combos": TOTAL_COMBOS,
        "jackpot_probability": 1 / TOTAL_COMBOS,
        "any_prize_combos": any_prize_combos,
        "any_prize_rate": any_prize_combos / TOTAL_COMBOS,
        "return_rate": RETURN_RATE,
        "current_prize_rate": CURRENT_PRIZE_RATE,
        "jackpot_cap_basic": JACKPOT_CAP_BASIC,
        "jackpot_cap_addon": JACKPOT_CAP_ADDON,
        "tiers": tiers,
        "fixed_prizes": fixed,
        "mode_note": MODEL_NOTE,
    }

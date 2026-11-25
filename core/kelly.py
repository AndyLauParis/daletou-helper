"""模型一：期望值与凯利公式。

同时给出两种口径：
- 规则明细口径：逐奖级 组合数 × 奖金 / 总组合数 求和；
- 返奖率口径：单注价格 × 51% 奖金计提。
"""

from __future__ import annotations

import math

from .constants import (
    CURRENT_PRIZE_RATE,
    JACKPOT_CAP_ADDON,
    JACKPOT_CAP_BASIC,
    RETURN_RATE,
    TOTAL_COMBOS,
)
from .rules import fixed_prize_map, get_rule_table

GROWTH_CURVE_POINTS = 200
GROWTH_F_MAX = 0.999
GROWTH_DECIMALS = 8
GROWTH_POINT_FS = [0.0, 0.001, 0.01, 0.05, 0.5, 1.0]
GROWTH_FORMULA = "g(f) = p·ln(1+b·f) + q·ln(1−f)"


def _growth(p: float, q: float, b: float, f: float) -> float | None:
    """对数增长率；f = 1 时无定义（JSON 不能存 Infinity），返回 None。"""
    if f >= 1:
        return None
    return p * math.log(1 + b * f) + q * math.log(1 - f)


def _kelly(jackpot: float, price: float) -> dict:
    p = 1 / TOTAL_COMBOS
    q = 1 - p
    b = jackpot / price
    p_b = p * b
    f_star_raw = (p_b - q) / b
    critical_jackpot = price / p
    return {
        "p": p,
        "q": q,
        "b": b,
        "p_b": p_b,
        "f_star_raw": f_star_raw,
        "f_star": max(0.0, f_star_raw),
        "critical_jackpot": critical_jackpot,
        "cap_basic": float(JACKPOT_CAP_BASIC),
        "cap_addon": float(JACKPOT_CAP_ADDON),
        "critical_multiple": critical_jackpot / jackpot,
    }


def _growth_block(p: float, q: float, b: float) -> dict:
    curve = []
    for index in range(GROWTH_CURVE_POINTS):
        f = GROWTH_F_MAX * index / (GROWTH_CURVE_POINTS - 1)
        g = _growth(p, q, b, f)
        curve.append([round(f, 6), round(g, GROWTH_DECIMALS)])

    points = []
    for f in GROWTH_POINT_FS:
        g = _growth(p, q, b, f)
        points.append({"f": f, "g": None if g is None else round(g, GROWTH_DECIMALS)})

    return {"curve": curve, "points": points, "formula": GROWTH_FORMULA}


def analyze_model1(
    jackpot: float,
    second_prize: float,
    pool: float,
    price: float = 2.0,
    mode: str = "rules",
) -> dict:
    jackpot = float(jackpot)
    second_prize = float(second_prize)
    effective_pool = float(pool or 0)
    price = float(price)
    if price <= 0:
        raise ValueError("单注价格必须大于 0")
    if jackpot < 0 or second_prize < 0:
        raise ValueError("奖金不能为负数")
    mode = mode if mode in ("rules", "video") else "rules"

    table = get_rule_table(pool=effective_pool, mode=mode)
    fixed = fixed_prize_map(effective_pool)

    breakdown = []
    total_return = 0.0
    for tier in table["tiers"]:
        tier_no = tier["tier"]
        if tier_no == 1:
            prize = jackpot
        elif tier_no == 2:
            prize = second_prize
        else:
            prize = fixed[tier_no]
        ev_contribution = tier["combos"] * prize / TOTAL_COMBOS
        total_return += ev_contribution
        breakdown.append(
            {
                "tier": tier_no,
                "label": tier["label"],
                "condition_text": tier["condition_text"],
                "combos": tier["combos"],
                "probability": tier["probability"],
                "prize": prize,
                "ev_contribution": ev_contribution,
            }
        )

    jackpot_ev = breakdown[0]["ev_contribution"]
    second_ev = breakdown[1]["ev_contribution"]
    fixed_rebate = sum(item["ev_contribution"] for item in breakdown[2:])
    ev = total_return - price
    payout_rate = total_return / price

    statutory_ev = price * RETURN_RATE - price
    statutory = {
        "return_rate": RETURN_RATE,
        "current_prize_rate": CURRENT_PRIZE_RATE,
        "ev": statutory_ev,
        "payout_rate": RETURN_RATE,
    }

    if mode == "video":
        display_ev = statutory_ev
        display_payout_rate = RETURN_RATE
        display_label = "视频口径（51% 返奖率，头奖 500 万）"
    else:
        display_ev = ev
        display_payout_rate = payout_rate
        display_label = "当前 7 奖级明细口径"

    kelly = _kelly(jackpot, price)
    growth = _growth_block(kelly["p"], kelly["q"], kelly["b"])

    rules_slope = payout_rate - 1
    statutory_slope = RETURN_RATE - 1
    if rules_slope < 0 and statutory_slope < 0:
        multi_verdict = (
            f"g'(0) = Σpᵢbᵢ = 返奖率 − 1：规则明细口径 {rules_slope:+.4f}、"
            f"返奖率口径 {statutory_slope:+.2f}，两者均为负。"
            "7 个奖级加总后斜率仍为负，最优仓位为 0。"
        )
    else:
        multi_verdict = (
            f"g'(0) = Σpᵢbᵢ = 返奖率 − 1：规则明细口径 {rules_slope:+.4f}、"
            f"返奖率口径 {statutory_slope:+.2f}。"
            "仅当明细口径为正时数学上才存在正仓位，但仍受单注上限与头奖封顶约束。"
        )

    notes = [
        f"规则明细口径：7 个奖级逐项相加，每注期望奖金 {total_return:.4f} 元，"
        f"EV = {ev:+.4f} 元，返奖率 {payout_rate:.4%}。",
        f"返奖率口径：奖金计提 {RETURN_RATE:.0%}（当期奖金 {CURRENT_PRIZE_RATE:.0%} + 调节基金 2%），"
        f"EV = {price:.2f} × {RETURN_RATE:.2f} − {price:.2f} = {statutory_ev:+.2f} 元。",
        f"凯利临界头奖 = 单注价格 / 头奖概率 = {kelly['critical_jackpot']:,.0f} 元"
        f"（约 {kelly['critical_jackpot'] / 1e4:,.0f} 万元），"
        f"是当前头奖的 {kelly['critical_multiple']:.2f} 倍。",
        f"当前单注头奖上限：基本 {JACKPOT_CAP_BASIC / 1e4:,.0f} 万元、"
        f"追加 {JACKPOT_CAP_ADDON / 1e4:,.0f} 万元，"
        f"均远低于临界头奖 {kelly['critical_jackpot'] / 1e4:,.0f} 万元。",
        f"未钳制 f* = {kelly['f_star_raw']:.3e}，按 max(0, f*) 取 {kelly['f_star']:.0f}；"
        "头奖翻数倍仍不足以让 f* 转正。",
    ]

    return {
        "input": {
            "jackpot": jackpot,
            "second_prize": second_prize,
            "pool": effective_pool,
            "price": price,
            "mode": mode,
        },
        "mode": mode,
        "pool_mode": table["pool_mode"],
        "rules": {
            "ev": ev,
            "payout_rate": payout_rate,
            "total_return": total_return,
            "fixed_rebate": fixed_rebate,
            "jackpot_ev": jackpot_ev,
            "second_ev": second_ev,
            "breakdown": breakdown,
        },
        "statutory": statutory,
        "display_ev": display_ev,
        "display_payout_rate": display_payout_rate,
        "display_label": display_label,
        "kelly": kelly,
        "growth": growth,
        "multi_tier": {
            "rules_slope": rules_slope,
            "statutory_slope": statutory_slope,
            "verdict": multi_verdict,
        },
        "verdict": "不投" if display_ev < 0 else "理论正期望，但受单注上限约束",
        "notes": notes,
        "warnings": [],
    }

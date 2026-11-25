"""模型二：曼德尔全包号成本、固定奖回血、盈亏平衡头奖与可行性判定。

口径：当前官方规则（7 个奖级，固定奖分正常/高奖池两档）。
"""

from __future__ import annotations

# 与 core.constants 保持一致（本模块自包含，避免并行开发时的导入依赖）
TOTAL_COMBOS = 21_425_712
TICKET_PRICE = 2
POOL_THRESHOLD = 800_000_000
JACKPOT_CAP_BASIC = 10_000_000
JACKPOT_CAP_ADDON = 18_000_000

SECOND_PRIZE_TICKETS = 20

# 固定奖各奖级组合数：三等 195、四等 3000、五等 11100、六等 127600、七等 1,287,281
FIXED_COMBOS = {3: 195, 4: 3_000, 5: 11_100, 6: 127_600, 7: 1_287_281}

FIXED_PRIZES = {
    "normal": {3: 5_000, 4: 300, 5: 150, 6: 15, 7: 5},
    "high": {3: 6_666, 4: 380, 5: 200, 6: 18, 7: 7},
}

VIRGINIA_CASE = {
    "year": 1992,
    "cost_usd": 7_060_000,
    "jackpot_usd": 27_030_000,
    "profit_usd": 20_000_000,
    "note": (
        "1992 年弗吉尼亚州彩票允许一次性买下全部组合，当期购买者少且头奖可分期领取，"
        "才出现理论正收益。当代大乐透有单注封顶、同号多人分摊与追加投注限制，该模式不可复制。"
    ),
}


def _num(value: float) -> float | int:
    """四舍五入到 2 位小数，整数则返回 int，保证 JSON 安全。"""
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def _fixed_breakdown(pool_mode: str) -> tuple[list[dict], float]:
    prizes = FIXED_PRIZES[pool_mode]
    breakdown = []
    total = 0.0
    for tier in sorted(FIXED_COMBOS):
        combos = FIXED_COMBOS[tier]
        prize = prizes[tier]
        amount = combos * prize
        total += amount
        breakdown.append(
            {"tier": tier, "combos": combos, "prize": prize, "amount": _num(amount)}
        )
    return breakdown, total


def analyze_model2(
    jackpot: float,
    second_prize: float,
    pool: float,
    tickets_per_sec: float = 1.0,
    price: float = 2.0,
) -> dict:
    """计算全包号模型的成本、回血、盈亏平衡头奖与可行性。

    参数:
        jackpot: 单注一等奖税前金额（元）
        second_prize: 单注二等奖税前金额（元）
        pool: 当前奖池（元），>= 8 亿时固定奖进入高档位
        tickets_per_sec: 每秒出票注数
        price: 单注价格（元）
    """
    jackpot = float(jackpot)
    second_prize = float(second_prize)
    pool = float(pool or 0)
    tickets_per_sec = float(tickets_per_sec)
    price = float(price)

    pool_mode = "high" if pool >= POOL_THRESHOLD else "normal"

    cost = TOTAL_COMBOS * price
    fixed_breakdown, fixed_rebate = _fixed_breakdown(pool_mode)
    second_rebate = SECOND_PRIZE_TICKETS * second_prize
    revenue = jackpot + second_rebate + fixed_rebate
    net = revenue - cost
    break_even_jackpot = cost - fixed_rebate - second_rebate
    gap_to_basic = break_even_jackpot - JACKPOT_CAP_BASIC
    gap_to_addon = break_even_jackpot - JACKPOT_CAP_ADDON

    effective_tps = max(tickets_per_sec, 0.0001)
    printing_seconds = TOTAL_COMBOS / effective_tps
    printing_days = printing_seconds / 86400

    reasons: list[str] = []
    if break_even_jackpot > JACKPOT_CAP_BASIC:
        reasons.append(
            f"盈亏平衡头奖约 {break_even_jackpot / 10000:.0f} 万元，"
            f"高于基本单注上限 {JACKPOT_CAP_BASIC // 10000} 万元"
        )
    elif break_even_jackpot > JACKPOT_CAP_ADDON:
        reasons.append(
            f"盈亏平衡头奖约 {break_even_jackpot / 10000:.0f} 万元，"
            f"高于追加单注上限 {JACKPOT_CAP_ADDON // 10000} 万元"
        )
    else:
        reasons.append(
            "理论盈亏平衡头奖虽低于单注封顶，但全包会产生海量中奖票，"
            "头奖按注均分会把单注奖金大幅摊薄"
        )
    reasons.append(
        f"按每秒 {tickets_per_sec:g} 注出票需约 {printing_days:.0f} 天，"
        "远超单期销售窗口"
    )
    if break_even_jackpot <= JACKPOT_CAP_ADDON:
        reasons.append(
            "中奖金额需缴纳 20% 偶然所得税，且同号多买会与普通彩民分摊头奖，"
            "实际回血远低于理论值"
        )

    return {
        "input": {
            "jackpot": _num(jackpot),
            "second_prize": _num(second_prize),
            "pool": _num(pool),
            "tickets_per_sec": _num(tickets_per_sec),
        },
        "pool_mode": pool_mode,
        "cost": {
            "total_combos": TOTAL_COMBOS,
            "price": _num(price),
            "amount": _num(cost),
        },
        "rebate": {
            "fixed": _num(fixed_rebate),
            "second": _num(second_rebate),
            "jackpot": _num(jackpot),
            "total": _num(revenue),
            "fixed_breakdown": fixed_breakdown,
        },
        "net": _num(net),
        "break_even_jackpot": _num(break_even_jackpot),
        "cap": {
            "basic": JACKPOT_CAP_BASIC,
            "addon": JACKPOT_CAP_ADDON,
            "gap_to_basic": _num(gap_to_basic),
            "gap_to_addon": _num(gap_to_addon),
        },
        "printing": {
            "tickets": TOTAL_COMBOS,
            "tickets_per_sec": _num(tickets_per_sec),
            "seconds": _num(printing_seconds),
            "days": round(printing_days, 1),
        },
        # 无论封顶是否够，出票窗口、分票与税费都使全包在现实中不可执行
        "feasible": False,
        "verdict": "不适用",
        "reasons": reasons,
        "virginia_case": VIRGINIA_CASE,
        "notes": [
            "全包 21,425,712 注即买下所有前区 5 号与后区 2 号组合，彩票中心并未限制单注重复售出，"
            "无法阻止他人同号分摊。",
            "默认口径：头奖 500 万元、二等奖 10 万元、奖池 < 8 亿的正常档位。",
            "奖池 ≥ 8 亿时固定奖回血提高约 408 万元，但盈亏平衡头奖仍约 2488 万元，依旧高于封顶。",
            "二等奖按固定 20 注估算（5+1 组合中与头奖号码重叠的注数），实际注数会随开奖号码浮动。",
        ],
    }

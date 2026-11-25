"""模型三：鞅策略（倍投）资金需求表与蒙特卡洛破产模拟。

说明：采用对鞅最有利的 1:1 净回本假设——每次中奖可收回此前全部累计亏损，
这是真实彩票远达不到的理想情形。即便如此，有限本金下破产概率仍随轮数趋近 1。
"""

from __future__ import annotations

import numpy as np

MAX_SIMULATIONS = 5_000
MAX_SAMPLE_PATHS = 5
MAX_PATH_POINTS = 100
STREAK_BUCKET_CAP = 20  # 直方图中 streak=20 表示 ">= 20"

ASSUMPTION = (
    "理想化假设：每次中奖按 1:1 净赔付并可覆盖此前累计亏损；"
    "真实彩票多数奖项不足以回本，实际更差。"
)


def _num(value: float) -> float | int:
    """四舍五入到 2 位小数，整数则返回 int，保证 JSON 安全。"""
    rounded = round(float(value), 2)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def _capital_row(k: int, base_bet: float, multiplier: float) -> dict:
    invested = base_bet * (multiplier**k - 1) / (multiplier - 1)
    next_bet = base_bet * multiplier**k
    return {
        "k": k,
        "invested": _num(invested),
        "next_bet": _num(next_bet),
        "total": _num(invested + next_bet),
    }


def _downsample(points: list[list[float]], limit: int = MAX_PATH_POINTS) -> list[list]:
    if len(points) <= limit:
        return points
    idx = np.linspace(0, len(points) - 1, limit).round().astype(int)
    return [points[int(i)] for i in idx]


def _simulate(
    base_bet: float,
    multiplier: float,
    bankroll: float,
    rounds: int,
    simulations: int,
    p_win: float,
    seed: int,
) -> dict:
    n = int(min(max(int(simulations), 1), MAX_SIMULATIONS))
    rng = np.random.default_rng(int(seed))

    bankrolls = np.full(n, float(bankroll), dtype=float)
    bets = np.full(n, float(base_bet), dtype=float)
    streaks = np.zeros(n, dtype=np.int64)
    max_streaks = np.zeros(n, dtype=np.int64)
    ruin_round = np.full(n, -1, dtype=np.int64)

    n_paths = min(MAX_SAMPLE_PATHS, n)
    paths: list[list[list[float]]] = [[] for _ in range(n_paths)]
    for path in paths:
        path.append([0, _num(bankroll)])

    for rnd in range(1, max(int(rounds), 0) + 1):
        active = ruin_round < 0
        can_bet = active & (bankrolls >= bets)
        # 本金已不足下一注 → 本局破产
        capital_out = active & ~can_bet
        ruin_round[capital_out] = rnd
        bankrolls[capital_out] = 0.0

        draws = rng.random(n)
        win = can_bet & (draws < p_win)
        lose = can_bet & ~win

        bankrolls[win] += bets[win]
        bets[win] = base_bet
        streaks[win] = 0

        bankrolls[lose] -= bets[lose]
        bets[lose] *= multiplier
        streaks[lose] += 1
        max_streaks = np.where(lose, np.maximum(max_streaks, streaks), max_streaks)

        dead = can_bet & (bankrolls <= 0)
        ruin_round[dead] = rnd
        bankrolls[dead] = 0.0

        for i, path in enumerate(paths):
            path.append([rnd, _num(bankrolls[i])])

    ruined = ruin_round >= 0
    ruin_probability = float(ruined.mean())
    if ruined.any():
        median_ruin_round: float | int | None = _num(np.median(ruin_round[ruined]))
    else:
        median_ruin_round = None

    capped = np.minimum(max_streaks, STREAK_BUCKET_CAP)
    counts = np.bincount(capped, minlength=STREAK_BUCKET_CAP + 1)
    hist = [{"streak": k, "count": int(counts[k])} for k in range(STREAK_BUCKET_CAP + 1)]

    return {
        "ruin_probability": round(ruin_probability, 4),
        "median_ruin_round": median_ruin_round,
        "mean_final_bankroll": _num(bankrolls.mean()),
        "max_streak_mean": _num(max_streaks.mean()),
        "max_streak_hist": hist,
        "sample_paths": [
            {"name": f"路径 {i + 1}", "data": _downsample(paths[i])}
            for i in range(n_paths)
        ],
        "params": {
            "base_bet": _num(base_bet),
            "multiplier": _num(multiplier),
            "bankroll": _num(bankroll),
            "rounds": int(rounds),
            "simulations": n,
            "p_win": _num(p_win),
            "seed": int(seed),
        },
        "assumption": ASSUMPTION,
    }


def analyze_model3(
    base_bet: float = 2,
    multiplier: float = 2,
    bankroll: float = 10000,
    rounds: int = 100,
    simulations: int = 1000,
    p_win: float = 0.0667,
    seed: int = 42,
) -> dict:
    """倍投资金需求表 + 蒙特卡洛破产模拟。"""
    base_bet = float(base_bet)
    multiplier = float(multiplier)
    bankroll = float(bankroll)
    p_win = float(p_win)

    if multiplier <= 1:
        raise ValueError("倍投倍数必须大于 1")

    key_ks = [10, 16, 20]
    capital_table = [_capital_row(k, base_bet, multiplier) for k in key_ks]
    full_table = [_capital_row(k, base_bet, multiplier) for k in range(1, 21)]

    simulation = _simulate(
        base_bet=base_bet,
        multiplier=multiplier,
        bankroll=bankroll,
        rounds=rounds,
        simulations=simulations,
        p_win=p_win,
        seed=seed,
    )

    return {
        "input": {
            "base_bet": _num(base_bet),
            "multiplier": _num(multiplier),
            "bankroll": _num(bankroll),
            "rounds": int(rounds),
            "simulations": int(min(max(int(simulations), 1), MAX_SIMULATIONS)),
            "p_win": _num(p_win),
            "seed": int(seed),
        },
        "capital_table": capital_table,
        "full_table": full_table,
        "simulation": simulation,
        "verdict": "必亏",
        "notes": [
            "倍投只改变亏损路径，不改变每注的负期望；拉长轮数只会让有限本金暴露在更多连黑里。",
            "默认胜率 0.0667 指任意奖级中奖率，且已按对鞅最有利的 1:1 回本假设模拟。",
            "最大连黑直方图中 streak=20 表示连黑 ≥ 20 次；破产局在破产后资金按 0 记。",
            "真实彩票低奖级奖金远低于累计投入，连黑后靠小奖回本并不成立，实际亏损会更快。",
        ],
    }

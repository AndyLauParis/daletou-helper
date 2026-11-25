"""历史开奖统计检验：卡方均匀性、冷热号、遗漏、选号策略对照。

所有结论只用于检验“号码是否能被历史规律预测”，不提供任何选号建议。
"""

from __future__ import annotations

import math
import random

from scipy import stats

from .constants import (
    ANY_PRIZE_RATE,
    BACK_EXPECTED_HITS,
    BACK_PICK,
    BACK_POOL,
    FRONT_EXPECTED_HITS,
    FRONT_PICK,
    FRONT_POOL,
)

FRONT_P = FRONT_PICK / FRONT_POOL  # 1/7
BACK_P = BACK_PICK / BACK_POOL  # 1/6

BASELINE_FRONT = FRONT_EXPECTED_HITS  # 0.7142857...
BASELINE_BACK = BACK_EXPECTED_HITS  # 0.3333333...
BASELINE_ANY = ANY_PRIZE_RATE  # 0.066704...

STRATEGY_PERIODS_MIN = 100
STRATEGY_PERIODS_MAX = 1000
STRATEGY_WINDOW = 50
RANDOM_TICKETS = 20
RANDOM_SEED = 42
RECENT_WINDOWS = (1000, 500, 300, 100)


def prize_tier(front_hits: int, back_hits: int) -> int | None:
    """按当前 7 奖级规则返回奖级（1-7），未中奖返回 None。"""
    if front_hits == 5:
        if back_hits == 2:
            return 1
        if back_hits == 1:
            return 2
        return 3
    if front_hits == 4:
        if back_hits == 2:
            return 3
        if back_hits == 1:
            return 4
        return 5
    if front_hits == 3:
        if back_hits == 2:
            return 5
        if back_hits == 1:
            return 6
        return 7
    if front_hits == 2:
        if back_hits == 2:
            return 6
        if back_hits == 1:
            return 7
        return None
    if front_hits in (0, 1) and back_hits == 2:
        return 7
    return None


def _f(value, digits: int = 6) -> float | None:
    """JSON 安全浮点数：NaN/Infinity 返回 None，其余四舍五入。"""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def _counts(draws: list[dict], key: str, pool: int) -> dict[int, int]:
    counts = {n: 0 for n in range(1, pool + 1)}
    for draw in draws:
        for number in draw.get(key, ()):
            if number in counts:
                counts[number] += 1
    return counts


def _chi_square_block(counts: dict[int, int], pool: int, pick: int, n: int) -> dict:
    p = pick / pool
    expected = n * p
    variance = n * p * (1 - p)
    sigma = math.sqrt(variance) if variance > 0 else 0.0
    df = pool - 1
    if expected > 0:
        stat = sum((c - expected) ** 2 / expected for c in counts.values())
        p_value = float(stats.chi2.sf(stat, df))
    else:
        stat = 0.0
        p_value = 1.0
    critical = float(stats.chi2.ppf(0.95, df))
    observed = []
    for number in range(1, pool + 1):
        count = counts[number]
        z = (count - expected) / sigma if sigma > 0 else 0.0
        observed.append(
            {
                "number": number,
                "count": count,
                "expected": _f(expected, 4),
                "z": _f(z, 4),
                "lower": _f(max(0.0, expected - 2 * sigma), 4),
                "upper": _f(expected + 2 * sigma, 4),
            }
        )
    if p_value > 0.05:
        conclusion = "不拒绝均匀（p > 0.05）"
    else:
        conclusion = "拒绝均匀（p ≤ 0.05）"
    return {
        "stat": _f(stat, 4),
        "df": df,
        "p_value": _f(p_value, 10),
        "critical_0_05": _f(critical, 4),
        "conclusion": conclusion,
        "expected": _f(expected, 4),
        "sigma": _f(sigma, 4),
        "observed": observed,
    }


def _hot_cold_block(counts: dict[int, int], pool: int, pick: int, n: int) -> dict:
    p = pick / pool
    sigma = math.sqrt(n * p * (1 - p)) if n else 0.0

    def entry(number: int, rank: int) -> dict:
        count = counts[number]
        z = (count - n * p) / sigma if sigma > 0 else 0.0
        return {
            "number": number,
            "count": count,
            "z": _f(z, 4),
            "rank": rank,
        }

    hot_numbers = sorted(counts, key=lambda num: (-counts[num], num))[:5]
    cold_numbers = sorted(counts, key=lambda num: (counts[num], num))[:5]
    hot = [entry(num, i + 1) for i, num in enumerate(hot_numbers)]
    cold = [entry(num, i + 1) for i, num in enumerate(cold_numbers)]
    band_note = (
        f"{pool} 个号码的期望频次为 N×{pick}/{pool}，±2σ 带（σ=√(N·p·(1−p))）"
        f"约等于随机波动范围。同时比较 {pool} 个号码属于多重比较，"
        f"纯随机下平均约有 {pool * 0.05:.1f} 个号码越界，"
        "因此“热号”“冷号”只是事后挑选的错觉，不能作为预测依据。"
    )
    return {"hot": hot, "cold": cold, "band_note": band_note}


def _omission_block(draws_asc: list[dict], key: str, pool: int, pick: int) -> dict:
    p = pick / pool
    expected_gap = 1 / p
    n = len(draws_asc)
    positions: dict[int, list[int]] = {num: [] for num in range(1, pool + 1)}
    for idx, draw in enumerate(draws_asc):
        for number in draw.get(key, ()):
            if number in positions:
                positions[number].append(idx)

    numbers = []
    for number in range(1, pool + 1):
        seen_at = positions[number]
        current = n - 1 - seen_at[-1] if seen_at else n
        gaps = [b - a for a, b in zip(seen_at, seen_at[1:])]
        average = sum(gaps) / len(gaps) if gaps else None
        max_gap = max(gaps) if gaps else None
        numbers.append(
            {
                "number": number,
                "current": current,
                "average": _f(average, 4),
                "max": max_gap,
                "percentile": _f((1 - p) ** current, 6),
            }
        )
    area = "前区" if key == "front" else "后区"
    note = (
        f"{area}单号每期出现概率 p={pick}/{pool}，理论平均间隔 1/p={expected_gap:g} 期，"
        f"当前遗漏达到 k 期且此前未出现的概率为 (1−p)^k。"
        "遗漏是几何分布的正常表现，“历史不欠你”，冷号不会因为久未出现就“该出了”。"
    )
    return {"expected_gap": int(expected_gap), "numbers": numbers, "note": note}


def _recent_chi_checks(draws: list[dict]) -> list[dict]:
    """对最近若干窗口重做前区卡方检验，判断偏离是否集中在早期样本。"""
    checks = []
    for window in RECENT_WINDOWS:
        if window >= len(draws):
            continue
        sample = draws[:window]
        block = _chi_square_block(
            _counts(sample, "front", FRONT_POOL), FRONT_POOL, FRONT_PICK, window
        )
        checks.append(
            {
                "window": window,
                "stat": block["stat"],
                "p_value": block["p_value"],
                "conclusion": block["conclusion"],
            }
        )
    return checks


def _format_p(p_value: float | None) -> str:
    if p_value is None:
        return "—"
    if p_value < 0.001:
        return f"{p_value:.2e}"
    return f"{p_value:.3f}"


def _pick_numbers(counts: dict[int, int], k: int, hottest: bool) -> list[int]:
    if hottest:
        return sorted(counts, key=lambda num: (-counts[num], num))[:k]
    return sorted(counts, key=lambda num: (counts[num], num))[:k]


def _verdict(diff: float, se: float) -> str:
    return "在随机误差内" if abs(diff) <= 2 * se else "偏离基线（需谨慎解读）"


def _strategy_block(draws: list[dict], periods: int) -> dict:
    try:
        periods = int(periods)
    except (TypeError, ValueError):
        periods = 300
    periods = max(STRATEGY_PERIODS_MIN, min(STRATEGY_PERIODS_MAX, periods))

    n = len(draws)
    limit = min(periods, n)
    # draws 为日期倒序；i 越大越早。按时间正序（旧→新）回测。
    test_indices = [i for i in range(limit) if i + 1 < n]
    test_indices.sort(reverse=True)
    samples = len(test_indices)

    front_var = (
        FRONT_PICK
        * (FRONT_PICK / FRONT_POOL)
        * ((FRONT_POOL - FRONT_PICK) / FRONT_POOL)
        * ((FRONT_POOL - FRONT_PICK) / (FRONT_POOL - 1))
    )
    back_var = (
        BACK_PICK
        * (BACK_PICK / BACK_POOL)
        * ((BACK_POOL - BACK_PICK) / BACK_POOL)
        * ((BACK_POOL - BACK_PICK) / (BACK_POOL - 1))
    )

    def finalize(
        key: str, name: str, front_hits: float, back_hits: float,
        any_rate: float, sample_count: int,
    ) -> dict:
        front_se = math.sqrt(front_var / sample_count) if sample_count else 0.0
        back_se = math.sqrt(back_var / sample_count) if sample_count else 0.0
        any_se = (
            math.sqrt(ANY_PRIZE_RATE * (1 - ANY_PRIZE_RATE) / sample_count)
            if sample_count
            else 0.0
        )
        front_verdict = _verdict(front_hits - BASELINE_FRONT, front_se)
        back_verdict = _verdict(back_hits - BASELINE_BACK, back_se)
        any_verdict = _verdict(any_rate - BASELINE_ANY, any_se)
        if (
            front_verdict == "在随机误差内"
            and back_verdict == "在随机误差内"
            and any_verdict == "在随机误差内"
        ):
            verdict = "在随机误差内（三项指标均不显著）"
        else:
            verdict = "偏离基线（需谨慎解读）"
        return {
            "key": key,
            "name": name,
            "front_hits": _f(front_hits, 6),
            "back_hits": _f(back_hits, 6),
            "any_prize_rate": _f(any_rate, 6),
            "front_se": _f(front_se, 6),
            "back_se": _f(back_se, 6),
            "any_se": _f(any_se, 6),
            "samples": sample_count,
            "verdict": verdict,
        }

    if samples == 0:
        return {
            "periods": periods,
            "window": STRATEGY_WINDOW,
            "baseline": {
                "front_hits": _f(BASELINE_FRONT, 7),
                "back_hits": _f(BASELINE_BACK, 7),
                "any_prize_rate": _f(BASELINE_ANY, 6),
            },
            "strategies": [],
            "note": "样本不足，无法进行策略对照",
        }

    sums = {
        "hot": [0.0, 0.0, 0],
        "cold": [0.0, 0.0, 0],
        "repeat": [0.0, 0.0, 0],
    }
    rng = random.Random(RANDOM_SEED)
    random_front_sum = 0.0
    random_back_sum = 0.0
    random_prize = 0
    random_samples = 0

    for i in test_indices:
        target = draws[i]
        window_draws = draws[i + 1 : i + 1 + STRATEGY_WINDOW]
        actual_front = set(target.get("front", ()))
        actual_back = set(target.get("back", ()))

        front_counts = _counts(window_draws, "front", FRONT_POOL)
        back_counts = _counts(window_draws, "back", BACK_POOL)

        picks = {
            "hot": (
                _pick_numbers(front_counts, FRONT_PICK, True),
                _pick_numbers(back_counts, BACK_PICK, True),
            ),
            "cold": (
                _pick_numbers(front_counts, FRONT_PICK, False),
                _pick_numbers(back_counts, BACK_PICK, False),
            ),
            "repeat": (
                list(draws[i + 1].get("front", ())),
                list(draws[i + 1].get("back", ())),
            ),
        }
        for key, (front_pick, back_pick) in picks.items():
            front_hits = len(set(front_pick) & actual_front)
            back_hits = len(set(back_pick) & actual_back)
            sums[key][0] += front_hits
            sums[key][1] += back_hits
            if prize_tier(front_hits, back_hits) is not None:
                sums[key][2] += 1

        for _ in range(RANDOM_TICKETS):
            front_pick = rng.sample(range(1, FRONT_POOL + 1), FRONT_PICK)
            back_pick = rng.sample(range(1, BACK_POOL + 1), BACK_PICK)
            front_hits = len(set(front_pick) & actual_front)
            back_hits = len(set(back_pick) & actual_back)
            random_front_sum += front_hits
            random_back_sum += back_hits
            if prize_tier(front_hits, back_hits) is not None:
                random_prize += 1
            random_samples += 1

    strategies = [
        finalize(
            "random", "机选",
            random_front_sum / random_samples,
            random_back_sum / random_samples,
            random_prize / random_samples,
            random_samples,
        ),
        finalize("hot", "热号", sums["hot"][0] / samples, sums["hot"][1] / samples,
                 sums["hot"][2] / samples, samples),
        finalize("cold", "冷号", sums["cold"][0] / samples, sums["cold"][1] / samples,
                 sums["cold"][2] / samples, samples),
        finalize("repeat", "上期重号", sums["repeat"][0] / samples,
                 sums["repeat"][1] / samples, sums["repeat"][2] / samples, samples),
    ]

    max_excess = 0.0
    se_keys = {
        "front_hits": "front_se",
        "back_hits": "back_se",
        "any_prize_rate": "any_se",
    }
    baselines = {
        "front_hits": BASELINE_FRONT,
        "back_hits": BASELINE_BACK,
        "any_prize_rate": BASELINE_ANY,
    }
    for item in strategies:
        for key, se_key in se_keys.items():
            se = item[se_key]
            diff = abs(item[key] - baselines[key])
            if se:
                max_excess = max(max_excess, diff / se)

    if max_excess > 3:
        note = "个别指标差异超过 3 倍标准误，可能来自样本波动或数据异常，需谨慎解读"
    else:
        note = "未发现稳定优势"

    return {
        "periods": periods,
        "window": STRATEGY_WINDOW,
        "baseline": {
            "front_hits": _f(BASELINE_FRONT, 7),
            "back_hits": _f(BASELINE_BACK, 7),
            "any_prize_rate": _f(BASELINE_ANY, 6),
        },
        "strategies": strategies,
        "note": note,
    }


def analyze_history(
    draws: list[dict],
    window: int | None = None,
    periods: int = 300,
) -> dict:
    """对历史开奖做统计检验，返回前端约定的完整结构。"""
    all_draws = list(draws or [])
    try:
        window_value = int(window) if window is not None else None
    except (TypeError, ValueError):
        window_value = None

    if window_value is None:
        sample = all_draws
    else:
        sample = all_draws[: max(0, window_value)]

    n = len(sample)
    newest = sample[0] if sample else None
    oldest = sample[-1] if sample else None

    front_counts = _counts(sample, "front", FRONT_POOL)
    back_counts = _counts(sample, "back", BACK_POOL)

    draws_asc = list(reversed(sample))
    front_omission = _omission_block(draws_asc, "front", FRONT_POOL, FRONT_PICK)
    back_omission = _omission_block(draws_asc, "back", BACK_POOL, BACK_PICK)

    chi_front = _chi_square_block(front_counts, FRONT_POOL, FRONT_PICK, n)
    chi_back = _chi_square_block(back_counts, BACK_POOL, BACK_PICK, n)
    recent_checks = _recent_chi_checks(sample)

    hot_cold_front = _hot_cold_block(front_counts, FRONT_POOL, FRONT_PICK, n)
    hot_cold_back = _hot_cold_block(back_counts, BACK_POOL, BACK_PICK, n)

    strategy = _strategy_block(all_draws, periods)

    conclusion = [
        f"前区卡方统计量 {chi_front['stat']}（df=34，p={chi_front['p_value']}），"
        f"{chi_front['conclusion']}。",
        f"后区卡方统计量 {chi_back['stat']}（df=11，p={chi_back['p_value']}），"
        f"{chi_back['conclusion']}。",
    ]
    if chi_front["p_value"] is not None and chi_front["p_value"] <= 0.05:
        top = max(chi_front["observed"], key=lambda item: abs(item["z"] or 0.0))
        conclusion.append(
            f"全样本前区偏离主要来自 {top['number']} 号：出现 {top['count']} 次，"
            f"期望 {top['expected']:.1f} 次，z≈{top['z']:.2f}；"
            "个别号码的高频属于事后可见的历史波动，不能据此判断下一期。"
        )
    if recent_checks:
        parts = "、".join(
            f"最近 {item['window']} 期 p={_format_p(item['p_value'])}"
            for item in recent_checks
        )
        if all((item["p_value"] or 0) > 0.05 for item in recent_checks):
            conclusion.append(
                f"{parts}，均不拒绝均匀；说明全样本偏离集中在更早的样本区间，"
                "把窗口缩短后差异不再显著，不能外推为预测能力。"
            )
        else:
            conclusion.append(
                f"{parts}；近期窗口仍有偏离，需继续观察，但同样不能作为预测依据。"
            )
    conclusion.extend([
        "冷热号只反映历史频次；即使个别号码落在 ±2σ 带外，也需考虑多重比较，"
        "且滚动回测未把这种偏差转化为稳定命中优势，不能据此预测下一期。",
        "遗漏期数符合几何分布，“冷号该出了”是赌徒谬误。",
    ])
    if strategy["note"] == "未发现稳定优势":
        deviating = [
            item["name"]
            for item in strategy["strategies"]
            if item["verdict"].startswith("偏离")
        ]
        if deviating:
            conclusion.append(
                f"最近 {strategy['periods']} 期对照中，多数指标与理论基线一致；"
                f"{'、'.join(deviating)}的个别指标略超 2 倍标准误，"
                "但整体未发现可稳定复现的优势。"
            )
        else:
            conclusion.append(
                f"最近 {strategy['periods']} 期对照中，热号/冷号/重号/机选与理论基线"
                "差异均在随机误差内，未发现稳定优势。"
            )
    else:
        conclusion.append(
            f"策略对照出现个别偏离：{strategy['note']}。"
        )

    return {
        "sample": {
            "draws": n,
            "window": window_value,
            "start_issue": oldest["issue"] if oldest else None,
            "end_issue": newest["issue"] if newest else None,
            "start_date": oldest["date"] if oldest else None,
            "end_date": newest["date"] if newest else None,
        },
        "chi_square": {"front": chi_front, "back": chi_back},
        "recent_checks": recent_checks,
        "hot_cold": {"front": hot_cold_front, "back": hot_cold_back},
        "omission": {"front": front_omission, "back": back_omission},
        "strategy": strategy,
        "conclusion": conclusion,
        "limitations": [
            "卡方检验只检验均匀性，不严格证明各期独立；结合开奖机制结论仍成立。",
            "策略对照为历史回测，样本量与多重比较会影响显著性判断，不能外推为未来收益。",
            "遗漏与冷热号均为事后统计，不构成任何投注建议；彩票是负期望游戏。",
        ],
    }

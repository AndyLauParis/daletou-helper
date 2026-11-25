"""历史数据实验室：描述性统计、随机性检验、策略回测与预算模拟。

设计原则：
- 只读取已经缓存的历史开奖数据，不做网络抓取；
- 只回答“历史样本长什么样”，不预测未来开奖、不推荐号码；
- 随机性检验使用蒙特卡洛方法，结论只描述样本，不代表开奖机器公平与否；
- 预算模拟只计入官方固定奖级，不含浮动奖与追加投注，不展示“预期盈利”。

依赖仅限 Python 标准库（math / random / statistics / pathlib）。
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path

from .games import cache, registry

# 最少样本期数；低于该值时拒绝出统计结论
MIN_SAMPLE = 10

# 蒙特卡洛默认次数
DEFAULT_TRIALS = 200

# 固定随机种子，保证同一请求重复执行结果一致
DEFAULT_SEED = "helper-lab-2026"


@dataclass(frozen=True)
class Group:
    """一个号码组：组合型的一个区，或数字型的一位。"""

    key: str
    label: str
    pool: int
    pick: int
    ticket: int
    offset: int = 1

    @property
    def numbers(self) -> list[int]:
        return list(range(self.offset, self.offset + self.pool))


@dataclass(frozen=True)
class Profile:
    """单个游戏的分析口径。"""

    code: str
    groups: tuple[Group, ...]
    shape_groups: tuple[str, ...]
    digit_mode: bool
    budget_model: str | None = None


def _digit_groups(count: int) -> tuple[Group, ...]:
    return tuple(
        Group(key=f"p{index}", label=f"第 {index} 位", pool=10, pick=1, ticket=1, offset=0)
        for index in range(1, count + 1)
    )


_PROFILES: tuple[Profile, ...] = (
    Profile(
        code="dlt",
        groups=(
            Group("front", "前区", 35, 5, 5),
            Group("back", "后区", 12, 2, 2),
        ),
        shape_groups=("front",),
        digit_mode=False,
        budget_model="dlt",
    ),
    Profile(
        code="ssq",
        groups=(
            Group("red", "红球", 33, 6, 6),
            Group("blue", "蓝球", 16, 1, 1),
        ),
        shape_groups=("red",),
        digit_mode=False,
        budget_model="ssq",
    ),
    Profile(
        code="qlc",
        groups=(
            Group("basic", "基本号", 30, 7, 7),
            Group("special", "特别号", 30, 1, 1),
        ),
        shape_groups=("basic",),
        digit_mode=False,
    ),
    Profile(
        code="kl8",
        groups=(Group("draw", "开出号码", 80, 20, 10),),
        shape_groups=("draw",),
        digit_mode=False,
    ),
    Profile(code="pl3", groups=_digit_groups(3), shape_groups=("p1", "p2", "p3"), digit_mode=True),
    Profile(code="fc3d", groups=_digit_groups(3), shape_groups=("p1", "p2", "p3"), digit_mode=True),
    Profile(
        code="pl5",
        groups=_digit_groups(5),
        shape_groups=("p1", "p2", "p3", "p4", "p5"),
        digit_mode=True,
    ),
    Profile(
        code="qxc",
        groups=_digit_groups(6) + (Group("back", "后区", 15, 1, 1, offset=0),),
        shape_groups=("p1", "p2", "p3", "p4", "p5", "p6"),
        digit_mode=True,
    ),
)

PROFILES: dict[str, Profile] = {profile.code: profile for profile in _PROFILES}

# 预算模拟支持的完整奖级模型
BUDGET_CODES = ("dlt", "ssq")


class LabDataError(RuntimeError):
    """历史样本不足或数据格式不可用。"""


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------


def _core_dlt_draws() -> list[dict]:
    """只读复用 core.store 的大乐透全量历史；文件不存在时不触发网络抓取。"""
    try:
        from core import store as core_store

        if not Path(core_store.CACHE_PATH).exists():
            return []
        raw = core_store.get_draws()
    except Exception:
        return []

    draws: list[dict] = []
    for item in raw:
        try:
            front = sorted(int(number) for number in item["front"])
            back = sorted(int(number) for number in item["back"])
            issue = str(item["issue"]).strip()
            date = str(item["date"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not issue or not date:
            continue
        if len(front) != 5 or len(back) != 2:
            continue
        draws.append(
            {
                "issue": issue,
                "date": date,
                "numbers": {"front": front, "back": back},
            }
        )
    return draws


def load_draws(code: str, limit: int = 200) -> list[dict]:
    """读取某游戏最近的开奖缓存（时间倒序），不发起网络请求。

    大乐透会额外合入 core.store 的本地历史文件，以获得更长的样本。
    """
    payload = cache.load_cache(code)
    draws = list(payload.get("draws") or [])
    if code == "dlt":
        draws = cache.merge_draws(draws, _core_dlt_draws())
    return draws[: max(0, int(limit))]


def _as_int_list(value) -> list[int] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return [value]
    if isinstance(value, (list, tuple)):
        values: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                return None
            values.append(item)
        return values
    return None


def extract_groups(profile: Profile, draw: dict) -> dict[str, list[int]] | None:
    """从统一开奖结构提取各号码组；字段缺失或越界时返回 None。"""
    numbers = (draw or {}).get("numbers")
    if not isinstance(numbers, dict):
        return None

    raw: dict[str, list[int] | None] = {}
    if profile.code == "dlt":
        raw = {
            "front": _as_int_list(numbers.get("front")),
            "back": _as_int_list(numbers.get("back")),
        }
    elif profile.code == "ssq":
        raw = {
            "red": _as_int_list(numbers.get("red")),
            "blue": _as_int_list(numbers.get("blue")),
        }
    elif profile.code == "qlc":
        raw = {
            "basic": _as_int_list(numbers.get("basic")),
            "special": _as_int_list(numbers.get("special")),
        }
    elif profile.code == "kl8":
        raw = {"draw": _as_int_list(numbers.get("draw"))}
    elif profile.code == "qxc":
        front = _as_int_list(numbers.get("front")) or []
        back = _as_int_list(numbers.get("back")) or []
        raw = {f"p{index}": [value] for index, value in enumerate(front, start=1)}
        raw["back"] = back
    else:
        digits = _as_int_list(numbers.get("digits")) or []
        raw = {
            f"p{index}": [value] for index, value in enumerate(digits, start=1)
        }

    result: dict[str, list[int]] = {}
    for group in profile.groups:
        values = raw.get(group.key)
        if values is None or len(values) != group.pick:
            return None
        lower = group.offset
        upper = group.offset + group.pool - 1
        if any(value < lower or value > upper for value in values):
            return None
        if len(set(values)) != group.pick:
            return None
        result[group.key] = sorted(values)
    return result


def _load_sequence(code: str, window: int) -> tuple[Profile, list[dict], list[dict]]:
    profile = PROFILES.get(code)
    if profile is None:
        raise KeyError(code)
    available = len(load_draws(code, 200))
    draws = load_draws(code, window)
    sequence: list[dict] = []
    for draw in reversed(draws):  # 旧 -> 新，便于计算遗漏与相邻重号
        groups = extract_groups(profile, draw)
        if groups is None:
            continue
        sequence.append({"draw": draw, "groups": groups})
    return profile, available, sequence


# ---------------------------------------------------------------------------
# 基础统计
# ---------------------------------------------------------------------------


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[index]


def _histogram(values: list[int], bins: int = 10) -> list[dict]:
    """整数直方图；返回包含区间标签与计数的列表。"""
    if not values:
        return []
    low, high = min(values), max(values)
    if low == high:
        return [{"label": str(low), "count": len(values)}]
    step = max(1, math.ceil((high - low + 1) / bins))
    result: list[dict] = []
    start = low
    while start <= high:
        end = min(high, start + step - 1)
        count = sum(1 for value in values if start <= value <= end)
        result.append(
            {"label": str(start) if start == end else f"{start}-{end}", "count": count}
        )
        start = end + 1
    return result


def _category_histogram(values: list[int], categories: list[int]) -> list[dict]:
    return [
        {"label": str(category), "count": sum(1 for value in values if value == category)}
        for category in categories
    ]


def frequency_table(profile: Profile, sequence: list[dict]) -> list[dict]:
    """各号码组的历史频次与遗漏（遗漏按“期”计）。"""
    total = len(sequence)
    groups: list[dict] = []
    for group in profile.groups:
        counts = dict.fromkeys(group.numbers, 0)
        first_seen: dict[int, int] = {}
        last_seen: dict[int, int] = {}
        gaps: dict[int, list[int]] = {number: [] for number in group.numbers}

        for index, item in enumerate(sequence):
            for number in item["groups"][group.key]:
                counts[number] += 1
                if number in last_seen:
                    gaps[number].append(index - last_seen[number] - 1)
                else:
                    first_seen[number] = index
                last_seen[number] = index

        rows = []
        for number in group.numbers:
            seen = number in last_seen
            current_omission = (total - 1 - last_seen[number]) if seen else total
            before_first = first_seen.get(number, total)
            between = max(gaps[number]) if gaps[number] else 0
            rows.append(
                {
                    "number": number,
                    "count": counts[number],
                    "rate": counts[number] / total if total else 0.0,
                    "expected_rate": group.pick / group.pool,
                    "current_omission": current_omission,
                    "max_omission": max(before_first, between, current_omission),
                }
            )

        groups.append(
            {
                "key": group.key,
                "label": group.label,
                "pool": group.pool,
                "pick": group.pick,
                "total": total,
                "numbers": rows,
            }
        )
    return groups


def _shape_profile(profile: Profile) -> tuple[int, int]:
    """形态分析的号码池大小与起点（数字型合并所有位）。"""
    if profile.digit_mode:
        return 10, 0
    group = next(group for group in profile.groups if group.key == profile.shape_groups[0])
    return group.pool, group.offset


def _shape_values(profile: Profile, groups: dict[str, list[int]]) -> list[int]:
    values: list[int] = []
    for key in profile.shape_groups:
        values.extend(groups[key])
    return values


def _zone_index(value: int, offset: int, pool: int) -> int:
    return min(2, max(0, (value - offset) * 3 // pool))


def _overlap(profile: Profile, left: dict[str, list[int]], right: dict[str, list[int]]) -> int:
    return sum(
        len(set(left[group.key]) & set(right[group.key])) for group in profile.groups
    )


def shape_stats(profile: Profile, sequence: list[dict]) -> dict:
    """和值、跨度、奇偶、大小、分区、连号与相邻期重号。"""
    sums: list[int] = []
    spans: list[int] = []
    odds: list[int] = []
    highs: list[int] = []
    consecutives: list[int] = []
    repeats: list[int] = []
    zone_counts = [0, 0, 0]
    zones: list[list[int]] = [[], [], []]

    pool, offset = _shape_profile(profile)
    previous: dict[str, list[int]] | None = None
    for item in sequence:
        groups = item["groups"]
        values = _shape_values(profile, groups)
        sums.append(sum(values))
        spans.append(max(values) - min(values))
        odds.append(sum(1 for value in values if value % 2 == 1))
        highs.append(
            sum(1 for value in values if value >= offset + pool / 2)
        )
        for value in values:
            index = _zone_index(value, offset, pool)
            zone_counts[index] += 1
        for index in range(3):
            zones[index].append(
                sum(1 for value in values if _zone_index(value, offset, pool) == index)
            )
        if not profile.digit_mode:
            ordered = sorted(values)
            consecutives.append(
                sum(1 for left, right in zip(ordered, ordered[1:]) if right - left == 1)
            )
        if previous is not None:
            repeats.append(_overlap(profile, groups, previous))
        previous = groups

    pick_total = len(_shape_values(profile, sequence[0]["groups"])) if sequence else 0
    zone_labels = []
    for index in range(3):
        numbers = [
            number
            for number in range(offset, offset + pool)
            if _zone_index(number, offset, pool) == index
        ]
        zone_labels.append(
            f"{min(numbers):02d}-{max(numbers):02d}" if numbers else f"区{index + 1}"
        )

    return {
        "sample": len(sequence),
        "pick_total": pick_total,
        "sum": {
            "mean": statistics.fmean(sums) if sums else 0.0,
            "median": statistics.median(sums) if sums else 0.0,
            "stdev": statistics.pstdev(sums) if len(sums) > 1 else 0.0,
            "min": min(sums) if sums else 0,
            "max": max(sums) if sums else 0,
            "theoretical_mean": pick_total * (offset + (pool - 1) / 2),
            "histogram": _histogram(sums),
        },
        "span": {
            "mean": statistics.fmean(spans) if spans else 0.0,
            "min": min(spans) if spans else 0,
            "max": max(spans) if spans else 0,
            "histogram": _histogram(spans),
        },
        "odd": {
            "mean": statistics.fmean(odds) if odds else 0.0,
            "theoretical_mean": pick_total / 2,
            "histogram": _category_histogram(odds, list(range(pick_total + 1))),
        },
        "high": {
            "mean": statistics.fmean(highs) if highs else 0.0,
            "theoretical_mean": pick_total / 2,
            "histogram": _category_histogram(highs, list(range(pick_total + 1))),
        },
        "zones": [
            {
                "label": zone_labels[index],
                "avg": zone_counts[index] / len(sequence) if sequence else 0.0,
                "expected": pick_total / 3,
                "share": (
                    zone_counts[index]
                    / (len(sequence) * pick_total)
                    if sequence and pick_total
                    else 0.0
                ),
            }
            for index in range(3)
        ],
        "consecutive": (
            {
                "mean": statistics.fmean(consecutives) if consecutives else 0.0,
                "histogram": _category_histogram(
                    consecutives, list(range(max(1, pick_total)))
                ),
            }
            if not profile.digit_mode
            else None
        ),
        "repeat": {
            "mean": statistics.fmean(repeats) if repeats else 0.0,
            "theoretical_mean": sum(
                group.pick * group.pick / group.pool for group in profile.groups
            ),
            "histogram": _histogram(repeats) if repeats else [],
        },
    }


def _stats_snapshot(profile: Profile, sequence: list[dict]) -> dict:
    """用于随机性检验的统计量：卡方、归一化熵、和值标准差、相邻重号、游程。"""
    counts: dict[str, dict[int, int]] = {}
    for group in profile.groups:
        group_counts = dict.fromkeys(group.numbers, 0)
        for item in sequence:
            for number in item["groups"][group.key]:
                group_counts[number] += 1
        counts[group.key] = group_counts

    total = len(sequence)
    chi_square = 0.0
    entropies: list[float] = []
    for group in profile.groups:
        expected = total * group.pick / group.pool
        if expected <= 0:
            continue
        chi_square += sum(
            (count - expected) ** 2 / expected for count in counts[group.key].values()
        )
        observed_total = total * group.pick
        entropy = 0.0
        for count in counts[group.key].values():
            if count:
                probability = count / observed_total
                entropy -= probability * math.log2(probability)
        entropies.append(entropy / math.log2(group.pool))

    sums = [sum(_shape_values(profile, item["groups"])) for item in sequence]
    repeats = [
        _overlap(profile, sequence[index]["groups"], sequence[index - 1]["groups"])
        for index in range(1, len(sequence))
    ]

    # 游程检验：和值高于/低于中位数视为两种状态，观察连续段个数
    median = statistics.median(sums) if sums else 0
    binary = [1 if value > median else 0 for value in sums if value != median]
    ones = sum(binary)
    zeros = len(binary) - ones
    runs_z = 0.0
    if ones and zeros:
        runs = 1 + sum(
            1 for left, right in zip(binary, binary[1:]) if left != right
        )
        total = ones + zeros
        expected = 1 + 2 * ones * zeros / total
        variance = (
            2
            * ones
            * zeros
            * (2 * ones * zeros - total)
            / (total * total * (total - 1))
        )
        if variance > 0:
            runs_z = (runs - expected) / math.sqrt(variance)

    return {
        "chi_square": chi_square,
        "entropy": statistics.fmean(entropies) if entropies else 0.0,
        "sum_stdev": statistics.pstdev(sums) if len(sums) > 1 else 0.0,
        "repeat_mean": statistics.fmean(repeats) if repeats else 0.0,
        "runs_z": runs_z,
    }


def _random_snapshot(profile: Profile, rng: random.Random) -> dict:
    groups: dict[str, list[int]] = {}
    for group in profile.groups:
        groups[group.key] = sorted(
            rng.sample(group.numbers, group.pick)
        )
    return {"groups": groups}


def randomness_tests(
    profile: Profile,
    sequence: list[dict],
    *,
    trials: int = DEFAULT_TRIALS,
    seed: str = DEFAULT_SEED,
) -> dict:
    """蒙特卡洛随机性检验：把观测统计量与同规则随机模拟对比。"""
    observed = _stats_snapshot(profile, sequence)
    rng = random.Random(f"{seed}:{profile.code}:{len(sequence)}")
    null: dict[str, list[float]] = {
        "chi_square": [],
        "entropy": [],
        "sum_stdev": [],
        "repeat_mean": [],
        "runs_z": [],
    }
    for _ in range(max(20, trials)):
        simulated = [_random_snapshot(profile, rng) for _ in range(len(sequence))]
        snapshot = _stats_snapshot(profile, simulated)
        for key in null:
            null[key].append(snapshot[key])

    definitions = [
        {
            "key": "chi_square",
            "label": "号码频率卡方",
            "tail": "upper",
            "detail": "检验各号码出现次数是否接近均匀期望；样本越大越稳定。",
            "pass_text": "未发现显著偏离均匀分布",
            "fail_text": "与随机模拟存在偏离，仍可能由样本波动造成",
        },
        {
            "key": "entropy",
            "label": "归一化信息熵",
            "tail": "two-sided",
            "detail": "衡量号码分布的分散程度，1 表示完全均匀。",
            "pass_text": "分布分散度与随机模拟接近",
            "fail_text": "分散度偏离随机模拟，但不足以用于预测",
        },
        {
            "key": "sum_stdev",
            "label": "和值标准差",
            "tail": "two-sided",
            "detail": "衡量和值的波动幅度，检验其离散程度是否异常。",
            "pass_text": "和值波动与随机模拟接近",
            "fail_text": "和值波动偏离随机模拟，可能只是抽样波动",
        },
        {
            "key": "repeat_mean",
            "label": "相邻期重号",
            "tail": "two-sided",
            "detail": "相邻两期号码的平均重合个数，用于观察期间独立性。",
            "pass_text": "相邻期重号与随机模拟接近",
            "fail_text": "相邻期重号偏离随机模拟，不代表存在规律",
        },
        {
            "key": "runs_z",
            "label": "和值游程检验",
            "tail": "two-sided",
            "detail": "把每期和值按是否高于中位数分成两种状态，观察连续段个数是否符合随机序列。",
            "pass_text": "和值游程与随机模拟接近",
            "fail_text": "和值游程偏离随机模拟，可能只是抽样波动",
        },
    ]

    results = []
    for definition in definitions:
        key = definition["key"]
        values = null[key]
        mean = statistics.fmean(values) if values else 0.0
        if definition["tail"] == "upper":
            exceed = sum(1 for value in values if value >= observed[key] - 1e-12)
        else:
            distance = abs(observed[key] - mean)
            exceed = sum(1 for value in values if abs(value - mean) >= distance - 1e-12)
        p_value = (1 + exceed) / (1 + len(values))
        results.append(
            {
                "key": key,
                "label": definition["label"],
                "detail": definition["detail"],
                "observed": round(observed[key], 4),
                "null_mean": round(mean, 4),
                "null_p05": round(_percentile(values, 0.05) or 0.0, 4),
                "null_p95": round(_percentile(values, 0.95) or 0.0, 4),
                "p_value": round(p_value, 4),
                "verdict": (
                    definition["pass_text"]
                    if p_value >= 0.05
                    else definition["fail_text"]
                ),
            }
        )

    return {
        "trials": max(20, trials),
        "method": "蒙特卡洛模拟：按相同号码池与选号个数生成随机样本，与历史统计量对比。",
        "tests": results,
        "note": (
            "随机性检验只描述历史样本的形态，不能证明开奖是否公平，"
            "也不能据此预测下一期号码；p 值小于 0.05 也不等于存在可利用规律。"
        ),
    }


# ---------------------------------------------------------------------------
# 策略回测
# ---------------------------------------------------------------------------


def _pick_hot_cold(group: Group, history: list[dict], hot: bool) -> list[int]:
    counts = dict.fromkeys(group.numbers, 0)
    for item in history:
        for number in item["groups"][group.key]:
            counts[number] += 1
    if hot:
        ordered = sorted(group.numbers, key=lambda number: (-counts[number], number))
    else:
        ordered = sorted(group.numbers, key=lambda number: (counts[number], number))
    return sorted(ordered[: group.ticket])


def run_backtest(
    profile: Profile,
    sequence: list[dict],
    *,
    test_size: int = 30,
    lookback: int = 30,
    seed: str = DEFAULT_SEED,
) -> dict:
    """历史走查：用过去 lookback 期选号，核对最近 test_size 期。

    策略只使用当期之前的开奖数据；随机策略使用固定种子，保证结果可复现。
    """
    total = len(sequence)
    if total < 3:
        raise LabDataError("历史样本不足，无法回测")
    test_size = max(1, min(int(test_size), total - 2))
    lookback = max(1, min(int(lookback), total - 1))
    start = total - test_size
    rng = random.Random(f"{seed}:backtest:{profile.code}:{total}")

    strategies = [
        ("hot", "追热号", "按历史频次从高到低选号"),
        ("cold", "选冷号", "按历史频次从低到高选号"),
        ("random", "随机选号", "在号码池内均匀随机选号（基线）"),
    ]
    metrics = {
        key: {
            "hits": [],
            "by_group": {group.key: [] for group in profile.groups},
        }
        for key, _label, _detail in strategies
    }

    for index in range(start, total):
        history = sequence[max(0, index - lookback) : index]
        actual = sequence[index]["groups"]
        for key, _label, _detail in strategies:
            total_hits = 0
            for group in profile.groups:
                if key == "hot":
                    picks = _pick_hot_cold(group, history, True)
                elif key == "cold":
                    picks = _pick_hot_cold(group, history, False)
                else:
                    picks = sorted(rng.sample(group.numbers, group.ticket))
                hits = len(set(picks) & set(actual[group.key]))
                total_hits += hits
                metrics[key]["by_group"][group.key].append(hits)
            metrics[key]["hits"].append(total_hits)

    max_total = sum(group.ticket for group in profile.groups)
    expected_by_group = {
        group.key: group.pick * group.ticket / group.pool for group in profile.groups
    }
    expected_hits = sum(expected_by_group.values())

    output = []
    for key, label, detail in strategies:
        hits = metrics[key]["hits"]
        output.append(
            {
                "key": key,
                "label": label,
                "detail": detail,
                "tickets": len(hits),
                "avg_hits": round(statistics.fmean(hits), 4) if hits else 0.0,
                "max_hits": max(hits) if hits else 0,
                "diff_from_expected": (
                    round(statistics.fmean(hits) - expected_hits, 4) if hits else 0.0
                ),
                "by_group": [
                    {
                        "key": group.key,
                        "label": group.label,
                        "avg_hits": (
                            round(statistics.fmean(metrics[key]["by_group"][group.key]), 4)
                            if metrics[key]["by_group"][group.key]
                            else 0.0
                        ),
                        "expected_hits": round(expected_by_group[group.key], 4),
                    }
                    for group in profile.groups
                ],
                "hit_histogram": _category_histogram(
                    hits, list(range(max_total + 1))
                ),
            }
        )

    return {
        "test_size": test_size,
        "lookback": lookback,
        "expected_hits": round(expected_hits, 4),
        "expected_by_group": [
            {
                "key": group.key,
                "label": group.label,
                "expected_hits": round(expected_by_group[group.key], 4),
            }
            for group in profile.groups
        ],
        "strategies": output,
        "note": (
            "回测只比较不同选号方式在历史样本中的平均命中个数，"
            "命中差异属于抽样波动；随机选号是基线，任何策略都不能改变下一期的中奖概率。"
        ),
    }


# ---------------------------------------------------------------------------
# 预算模拟
# ---------------------------------------------------------------------------

_TICKET_PRICE = {"dlt": 2.0, "ssq": 2.0}

# 双色球固定奖级（三至六等奖）；一、二等奖为浮动奖金，不计入模拟
_SSQ_FIXED = {
    (5, True): 3000.0,
    (5, False): 200.0,
    (4, True): 200.0,
    (4, False): 10.0,
    (3, True): 10.0,
    (2, True): 5.0,
    (1, True): 5.0,
    (0, True): 5.0,
}


def _outcome_table(code: str) -> list[tuple[float, float, str]]:
    """返回 [(概率, 固定奖金, 说明)]；浮动奖与追加投注不计入。"""
    if code == "dlt":
        from core.rules import FIXED_PRIZES_NORMAL, tier_for_hits

        front_total = math.comb(35, 5)
        back_total = math.comb(12, 2)
        table: list[tuple[float, float, str]] = []
        for front_hits in range(6):
            front_probability = (
                math.comb(5, front_hits) * math.comb(30, 5 - front_hits) / front_total
            )
            for back_hits in range(3):
                back_probability = (
                    math.comb(2, back_hits)
                    * math.comb(10, 2 - back_hits)
                    / back_total
                )
                probability = front_probability * back_probability
                tier = tier_for_hits(front_hits, back_hits)
                amount = float(FIXED_PRIZES_NORMAL.get(tier, 0) or 0) if tier else 0.0
                if tier in (1, 2):
                    note = "浮动奖，未计入"
                elif tier:
                    note = f"{tier} 等奖"
                else:
                    note = "未中奖"
                table.append((probability, amount, note))
        return table

    if code == "ssq":
        red_total = math.comb(33, 6)
        table = []
        for red_hits in range(7):
            red_probability = (
                math.comb(6, red_hits) * math.comb(27, 6 - red_hits) / red_total
            )
            for blue_hit in (True, False):
                probability = red_probability * (1 / 16 if blue_hit else 15 / 16)
                if (red_hits, blue_hit) in ((6, True), (6, False)):
                    amount, note = 0.0, "浮动奖，未计入"
                else:
                    amount = _SSQ_FIXED.get((red_hits, blue_hit), 0.0)
                    note = "固定奖" if amount else "未中奖"
                table.append((probability, amount, note))
        return table

    raise LabDataError("该游戏暂不支持预算模拟")


def simulate_budget(
    code: str,
    *,
    periods: int,
    tickets_per_period: int,
    trials: int = 2000,
    seed: str = DEFAULT_SEED,
) -> dict:
    """模拟连续购彩的净支出分布。

    每注独立随机，只计入官方固定奖级；结果为分布描述，不构成购彩建议。
    """
    if code not in BUDGET_CODES:
        raise LabDataError("该游戏暂不支持预算模拟")
    periods = max(1, min(int(periods), 520))
    tickets_per_period = max(1, min(int(tickets_per_period), 20))
    trials = max(200, min(int(trials), 5000))

    table = _outcome_table(code)
    prizes = [amount for _probability, amount, _note in table]
    weights = [probability for probability, _amount, _note in table]
    per_ticket_any = sum(
        probability for probability, amount, _note in table if amount > 0
    )
    price = _TICKET_PRICE[code]
    spend = round(periods * tickets_per_period * price, 2)

    rng = random.Random(f"{seed}:budget:{code}:{periods}:{tickets_per_period}")
    nets: list[float] = []
    returns: list[float] = []
    any_win = 0
    for _ in range(trials):
        winnings = sum(
            rng.choices(prizes, weights=weights, k=periods * tickets_per_period)
        )
        returns.append(winnings)
        nets.append(winnings - spend)
        if winnings > 0:
            any_win += 1

    ordered_nets = sorted(nets)
    p_loss = sum(1 for value in nets if value < 0) / trials
    p_profit = sum(1 for value in nets if value > 0) / trials
    p_even = 1 - p_loss - p_profit

    bucket_defs = [
        ("无返奖", 0.0, 0.10, True),
        ("< 10%", 0.0, 0.10, False),
        ("10%–25%", 0.10, 0.25, False),
        ("25%–50%", 0.25, 0.50, False),
        ("50%–100%", 0.50, 1.0, False),
        ("≥ 100%", 1.0, float("inf"), False),
    ]
    distribution = []
    for label, low, high, only_zero in bucket_defs:
        if only_zero:
            count = sum(1 for value in returns if value == 0)
        elif high == float("inf"):
            count = sum(1 for value in returns if value >= spend)
        else:
            count = sum(
                1
                for value in returns
                if value > 0 and low <= value / spend < high
            )
        distribution.append(
            {
                "label": label,
                "count": count,
                "share": round(count / trials, 4),
            }
        )

    return {
        "periods": periods,
        "tickets_per_period": tickets_per_period,
        "ticket_price": price,
        "trials": trials,
        "spend": spend,
        "per_ticket_any_prize": round(per_ticket_any, 6),
        "p_any_win": round(any_win / trials, 4),
        "p_loss": round(p_loss, 4),
        "p_profit": round(p_profit, 4),
        "p_even": round(p_even, 4),
        "avg_return": round(statistics.fmean(returns), 2),
        "avg_net": round(statistics.fmean(nets), 2),
        "net_percentiles": {
            "p05": round(_percentile(ordered_nets, 0.05) or 0.0, 2),
            "p25": round(_percentile(ordered_nets, 0.25) or 0.0, 2),
            "p50": round(_percentile(ordered_nets, 0.50) or 0.0, 2),
            "p75": round(_percentile(ordered_nets, 0.75) or 0.0, 2),
            "p95": round(_percentile(ordered_nets, 0.95) or 0.0, 2),
        },
        "distribution": distribution,
        "note": (
            "模拟只计入官方固定奖级，一、二等奖等浮动奖与追加投注未计入；"
            "结果用于说明长期投入的亏损分布，不构成任何购彩建议。"
        ),
    }


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def _recent_draws(profile: Profile, sequence: list[dict], limit: int = 10) -> list[dict]:
    items: list[dict] = []
    for index in range(max(0, len(sequence) - limit), len(sequence)):
        item = sequence[index]
        groups = item["groups"]
        values = _shape_values(profile, groups)
        repeat = (
            _overlap(profile, groups, sequence[index - 1]["groups"])
            if index > 0
            else None
        )
        items.append(
            {
                "issue": str(item["draw"].get("issue") or ""),
                "date": str(item["draw"].get("date") or ""),
                "groups": [
                    {
                        "key": group.key,
                        "label": group.label,
                        "numbers": groups[group.key],
                    }
                    for group in profile.groups
                ],
                "sum": sum(values),
                "span": max(values) - min(values),
                "odd": sum(1 for value in values if value % 2 == 1),
                "repeat": repeat,
            }
        )
    items.reverse()
    return items


def game_summary(code: str) -> dict | None:
    """实验室可分析游戏的概览（用于前端下拉框）。"""
    profile = PROFILES.get(code)
    if profile is None:
        return None
    meta = registry.get_game(code)
    if meta is None:
        return None
    draws = load_draws(code, 200)
    latest = draws[0] if draws else None
    return {
        "code": code,
        "name": meta.name,
        "format_summary": meta.format_summary,
        "category_label": meta.category_label,
        "draw_count": len(draws),
        "latest_issue": latest.get("issue") if latest else None,
        "latest_date": latest.get("date") if latest else None,
        "budget_supported": profile.budget_model in BUDGET_CODES,
    }


def list_games() -> list[dict]:
    items = [game_summary(code) for code in PROFILES]
    return [item for item in items if item is not None]


def analyze(
    code: str,
    *,
    window: int = 100,
    trials: int = DEFAULT_TRIALS,
) -> dict:
    """完整分析结果；样本不足时抛出 LabDataError。"""
    profile, available, sequence = _load_sequence(code, max(MIN_SAMPLE, int(window)))
    if len(sequence) < MIN_SAMPLE:
        raise LabDataError(
            f"可用开奖样本不足（当前 {len(sequence)} 期，至少需要 {MIN_SAMPLE} 期）"
        )

    meta = registry.get_game(code)
    if meta is None:
        raise KeyError(code)

    adjusted_trials = trials if len(sequence) <= 120 else max(80, int(trials * 0.7))
    shape = shape_stats(profile, sequence)
    return {
        "game": {
            "code": code,
            "name": meta.name,
            "format_summary": meta.format_summary,
            "category_label": meta.category_label,
            "budget_supported": profile.budget_model in BUDGET_CODES,
        },
        "window_requested": int(window),
        "window_used": len(sequence),
        "available_draws": available,
        "date_range": {
            "from": str(sequence[0]["draw"].get("date") or ""),
            "to": str(sequence[-1]["draw"].get("date") or ""),
        },
        "latest_issue": str(sequence[-1]["draw"].get("issue") or ""),
        "recent": _recent_draws(profile, sequence),
        "frequency": frequency_table(profile, sequence),
        "shape": shape,
        "randomness": randomness_tests(
            profile, sequence, trials=adjusted_trials
        ),
        "backtest": run_backtest(profile, sequence),
        "note": (
            "以下内容全部来自历史开奖样本的统计描述，只能说明过去，"
            "不能预测未来开奖，也不构成投注建议。"
        ),
    }

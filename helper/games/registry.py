"""全品类彩票游戏注册表（固定顺序）。

支持级别：
- `full`：完整核对，适配器实现后提供开奖数据与号码/赛果核对。
- `catalog`：仅目录 + 支出记录，不提供赔率、预测或核对。

开奖节奏以官方公告为准；无法确定的时间填写 None，不做推测。
"""

from __future__ import annotations

import importlib
import logging

from .base import GameMeta

logger = logging.getLogger("helper.games.registry")

CATEGORY_LABELS: dict[str, str] = {
    "ticai_number": "体彩数字型",
    "fucai_number": "福彩数字型",
    "zucai": "足彩",
    "jingcai": "竞彩",
    "jikai": "即开型",
}

CATEGORY_ORDER: tuple[str, ...] = tuple(CATEGORY_LABELS)


def _game(
    code: str,
    name: str,
    category: str,
    support_level: str,
    format_summary: str,
    rule_summary: str,
    schedule_weekdays: tuple[int, ...] | None,
    draw_time: str | None,
    price_note: str,
    source_name: str | None,
) -> GameMeta:
    adapter_module = None if support_level == "catalog" else f"helper.games.{code}"
    return GameMeta(
        code=code,
        name=name,
        category=category,
        category_label=CATEGORY_LABELS[category],
        support_level=support_level,
        format_summary=format_summary,
        rule_summary=rule_summary,
        schedule_weekdays=schedule_weekdays,
        draw_time=draw_time,
        price_note=price_note,
        adapter_module=adapter_module,
        source_name=source_name,
    )


GAMES: dict[str, GameMeta] = {
    # 体彩数字型
    "dlt": _game(
        "dlt",
        "大乐透",
        "ticai_number",
        "full",
        "前区 5/35 + 后区 2/12",
        "前区从 35 个号码中选 5 个、后区从 12 个号码中选 2 个组成一注，奖级以官方公告为准。",
        (0, 2, 5),
        "20:30",
        "2 元/注，追加 1 元",
        "国家体彩中心 / 500.com",
    ),
    "pl3": _game(
        "pl3",
        "排列3",
        "ticai_number",
        "full",
        "3 位数字 0–9",
        "可选择直选、组选3、组选6 三种玩法，按所选玩法分别核对，奖级以官方公告为准。",
        (0, 1, 2, 3, 4, 5, 6),
        "20:30",
        "2 元/注",
        "国家体彩中心 / 500.com",
    ),
    "pl5": _game(
        "pl5",
        "排列5",
        "ticai_number",
        "full",
        "5 位数字 0–9",
        "按位选择 5 个数字组成一注，奖级以官方公告为准。",
        (0, 1, 2, 3, 4, 5, 6),
        "20:30",
        "2 元/注",
        "国家体彩中心 / 500.com",
    ),
    "qxc": _game(
        "qxc",
        "七星彩",
        "ticai_number",
        "full",
        "前区 6 位 0–9 + 后区 1 位 0–14",
        "前区 6 位数字加后区 1 位数字组成一注，奖级以官方公告为准。",
        (1, 4, 6),
        "20:30",
        "2 元/注",
        "国家体彩中心 / 500.com",
    ),
    # 福彩数字型
    "ssq": _game(
        "ssq",
        "双色球",
        "fucai_number",
        "full",
        "红球 6/33 + 蓝球 1/16",
        "红球从 33 个号码中选 6 个、蓝球从 16 个号码中选 1 个组成一注，奖级以官方公告为准。",
        (1, 3, 6),
        "21:15",
        "2 元/注",
        "中国福利彩票 / 500.com",
    ),
    "fc3d": _game(
        "fc3d",
        "福彩3D",
        "fucai_number",
        "full",
        "3 位数字 0–9",
        "可选择直选、组选3、组选6 三种玩法，按所选玩法分别核对，奖级以官方公告为准。",
        (0, 1, 2, 3, 4, 5, 6),
        "21:15",
        "2 元/注",
        "中国福利彩票 / 500.com",
    ),
    "qlc": _game(
        "qlc",
        "七乐彩",
        "fucai_number",
        "full",
        "基本号 7/30 + 特别号 1/30",
        "基本号从 30 个号码中选 7 个，另开 1 个特别号，奖级以官方公告为准。",
        (0, 2, 4),
        "21:15",
        "2 元/注",
        "中国福利彩票 / 500.com",
    ),
    "kl8": _game(
        "kl8",
        "快乐8",
        "fucai_number",
        "full",
        "20/80，选 1–10 个号码",
        "每期开出 20 个号码，按选中个数对应官方奖级，奖金以官方公告为准。",
        (0, 1, 2, 3, 4, 5, 6),
        "21:30",
        "2 元/注",
        "中国福利彩票 / 500.com",
    ),
    # 足彩
    "sfc14": _game(
        "sfc14",
        "胜负彩14场",
        "zucai",
        "full",
        "14 场，每场 3/1/0",
        "对 14 场比赛逐场选择主胜/平/客胜，全部命中为一等奖，奖级以官方公告为准。",
        None,
        None,
        "2 元/注",
        "国家体彩中心 / 500.com",
    ),
    "rx9": _game(
        "rx9",
        "任选9场",
        "zucai",
        "full",
        "14 场中选 9 场，每场 3/1/0",
        "从 14 场比赛中任选 9 场，所选 9 场全部命中即中奖，奖级以官方公告为准。",
        None,
        None,
        "2 元/注",
        "国家体彩中心 / 500.com",
    ),
    "jq4": _game(
        "jq4",
        "4场进球",
        "zucai",
        "full",
        "4 场，每场 0/1/2/3+",
        "预测 4 场比赛的总进球数档位，奖级以官方公告为准。",
        None,
        None,
        "2 元/注",
        "国家体彩中心 / 500.com",
    ),
    "bqc6": _game(
        "bqc6",
        "6场半全场",
        "zucai",
        "full",
        "6 场 × 半场/全场，各 3/1/0",
        "预测 6 场比赛的半场与全场结果，奖级以官方公告为准。",
        None,
        None,
        "2 元/注",
        "国家体彩中心 / 500.com",
    ),
    # 竞彩（仅目录 + 支出）
    "jczq": _game(
        "jczq",
        "竞彩足球",
        "jingcai",
        "catalog",
        "赔率型，无固定号码格式",
        "按官方赛程选择场次与玩法，本工具仅记录目录与支出，不展示赔率走势或推荐。",
        None,
        None,
        "以官方渠道为准",
        None,
    ),
    "jclq": _game(
        "jclq",
        "竞彩篮球",
        "jingcai",
        "catalog",
        "赔率型，无固定号码格式",
        "按官方赛程选择场次与玩法，本工具仅记录目录与支出，不展示赔率走势或推荐。",
        None,
        None,
        "以官方渠道为准",
        None,
    ),
    # 即开型（仅目录 + 支出）
    "dgg": _game(
        "dgg",
        "顶呱刮",
        "jikai",
        "catalog",
        "即开即兑，无开奖数据",
        "即开型彩票，票面奖项与兑奖规则以官方为准，本工具仅记录目录与支出。",
        None,
        None,
        "以票面为准",
        None,
    ),
    "ggl": _game(
        "ggl",
        "刮刮乐",
        "jikai",
        "catalog",
        "即开即兑，无开奖数据",
        "即开型彩票，票面奖项与兑奖规则以官方为准，本工具仅记录目录与支出。",
        None,
        None,
        "以票面为准",
        None,
    ),
}


def get_game(code: str) -> GameMeta | None:
    """按代码取游戏元数据，未知代码返回 None。"""
    if not code:
        return None
    return GAMES.get(code.strip().lower())


def list_games() -> list[GameMeta]:
    """按固定顺序返回全部游戏。"""
    return list(GAMES.values())


def catalog_groups() -> list[dict]:
    """按固定类别顺序分组返回游戏。"""
    groups = []
    for category in CATEGORY_ORDER:
        games = [meta for meta in GAMES.values() if meta.category == category]
        groups.append(
            {
                "category": category,
                "category_label": CATEGORY_LABELS[category],
                "games": games,
            }
        )
    return groups


def get_adapter(code: str):
    """懒加载适配器模块；游戏未知、无适配器或模块尚未实现时返回 None。"""
    meta = get_game(code)
    if meta is None or not meta.adapter_module:
        return None
    try:
        return importlib.import_module(meta.adapter_module)
    except ModuleNotFoundError as exc:
        if exc.name != meta.adapter_module:
            logger.warning(
                "适配器 %s 缺少依赖 %s", meta.adapter_module, exc.name
            )
        return None
    except ImportError:
        logger.warning("加载 %s 适配器失败", meta.adapter_module, exc_info=True)
        return None


def has_adapter(code: str) -> bool:
    """是否已有可用适配器。"""
    return get_adapter(code) is not None

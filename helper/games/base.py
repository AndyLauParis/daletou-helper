"""游戏元数据与适配器协议。

适配器由 `helper/games/<code>.py` 模块实现，需提供以下接口（可用模块级函数）：

- `SOURCE_NAME: str`：数据源名称，写入缓存并在页面展示。
- `fetch_draws(limit: int = 30) -> list[dict]`：返回按时间倒序的开奖列表。
- `validate_ticket(payload: dict, play_type: str | None = None) -> dict`：
  返回 `{"ok": bool, "normalized": dict, "errors": [str]}`。
- `check_ticket(payload: dict, play_type: str | None, draw: dict) -> dict`：
  返回 `{"ok": bool, "hit": bool, "prize_level": str | None, "detail": dict, "message": str}`。

统一开奖记录最低字段（数字型）：

    {"issue": "26134", "date": "2026-11-24", "numbers": {...}, "extra": {...}}

足彩可为：

    {"issue": "26134", "date": "2026-11-24", "matches": [...], "extra": {...}}

`numbers` / `matches` / `extra` 的内部结构由各适配器决定，但必须可 JSON 序列化。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GameMeta:
    """单个彩票游戏的静态元数据。"""

    code: str
    name: str
    category: str
    category_label: str
    support_level: str
    format_summary: str
    rule_summary: str
    schedule_weekdays: tuple[int, ...] | None
    draw_time: str | None
    price_note: str
    adapter_module: str | None
    source_name: str | None

    @property
    def supports_check(self) -> bool:
        """是否支持号码/赛果核对（仅完整核对级别的游戏）。"""
        return self.support_level == "full"

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的字典。"""
        return {
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "category_label": self.category_label,
            "support_level": self.support_level,
            "format_summary": self.format_summary,
            "rule_summary": self.rule_summary,
            "schedule_weekdays": (
                list(self.schedule_weekdays)
                if self.schedule_weekdays is not None
                else None
            ),
            "draw_time": self.draw_time,
            "price_note": self.price_note,
            "adapter_module": self.adapter_module,
            "source_name": self.source_name,
        }


class GameAdapter(Protocol):
    """适配器协议（仅用于类型说明，运行时不做强制校验）。"""

    SOURCE_NAME: str

    def fetch_draws(self, limit: int = 30) -> list[dict]: ...

    def validate_ticket(
        self, payload: dict, play_type: str | None = None
    ) -> dict: ...

    def check_ticket(
        self, payload: dict, play_type: str | None, draw: dict
    ) -> dict: ...

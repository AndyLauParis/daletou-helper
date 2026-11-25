"""购彩辅助工具的运行时配置。

数据库路径支持环境变量 HELPER_DB_PATH 覆盖（测试通过 monkeypatch 本模块的
DB_PATH 实现隔离，因此运行时必须动态读取 config.DB_PATH）。
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = os.environ.get("HELPER_DB_PATH") or str(PROJECT_ROOT / "data" / "helper.db")

STATIC_DIR = PROJECT_ROOT / "helper_static"

# 会话有效期（天）
SESSION_TTL_DAYS = 30

# 登录失败限流：窗口内最大失败次数
LOGIN_FAIL_WINDOW_SECONDS = 5 * 60
LOGIN_FAIL_MAX = 5

APP_TITLE = "全国彩票购彩辅助工具"

"""购彩辅助工具的运行时配置。

数据库路径支持环境变量 HELPER_DB_PATH 覆盖（测试通过 monkeypatch 本模块的
DB_PATH 实现隔离，因此运行时必须动态读取 config.DB_PATH）。
所有安全相关配置均可通过环境变量覆盖，便于公网部署时收紧。
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_llm_env() -> None:
    """从项目根目录 .env 读取 HELPER_LLM_* 配置，已存在的环境变量优先。"""
    path = PROJECT_ROOT / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.startswith("HELPER_LLM_"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_llm_env()

DB_PATH = os.environ.get("HELPER_DB_PATH") or str(PROJECT_ROOT / "data" / "helper.db")

STATIC_DIR = PROJECT_ROOT / "helper_static"

# 会话有效期（天）。公网部署建议 1–7 天，并配合 HTTPS。
SESSION_TTL_DAYS = _env_int("HELPER_SESSION_TTL_DAYS", 7)

# 登录失败限流：窗口内最大失败次数（按 IP + 用户名）
LOGIN_FAIL_WINDOW_SECONDS = _env_int("HELPER_LOGIN_FAIL_WINDOW_SECONDS", 5 * 60)
LOGIN_FAIL_MAX = _env_int("HELPER_LOGIN_FAIL_MAX", 5)

# 注册模式：open（默认，兼容现有测试）/ invite（需邀请码）/ closed（关闭注册）
REGISTRATION_MODE = (
    os.environ.get("HELPER_REGISTRATION_MODE", "open").strip().lower() or "open"
)
INVITE_CODE = os.environ.get("HELPER_INVITE_CODE", "")

# 大模型辅助解读（OpenAI 兼容接口）。三项都配置后才启用。
LLM_BASE_URL = (os.environ.get("HELPER_LLM_BASE_URL") or "").strip().rstrip("/")
LLM_API_KEY = (os.environ.get("HELPER_LLM_API_KEY") or "").strip()
LLM_MODEL = (os.environ.get("HELPER_LLM_MODEL") or "").strip()
LLM_PROVIDER = (os.environ.get("HELPER_LLM_PROVIDER") or "OpenAI 兼容").strip()
LLM_TIMEOUT_SECONDS = _env_int("HELPER_LLM_TIMEOUT_SECONDS", 45)
LLM_MAX_TOKENS = _env_int("HELPER_LLM_MAX_TOKENS", 900)
LLM_RATE_LIMIT = _env_int("HELPER_LLM_RATE_LIMIT", 8)
LLM_RATE_WINDOW_SECONDS = _env_int("HELPER_LLM_RATE_WINDOW_SECONDS", 600)

APP_TITLE = "全国彩票购彩辅助工具"

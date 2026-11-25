"""用户反馈：分类定义、截图校验与附件存储。

截图只保存在本地数据目录，按随机文件名落盘；数据库仅记录文件名与 MIME。
校验不信任客户端 Content-Type，改为读取文件头判断真实图片类型。
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path

from . import config

# 分类 key -> 展示名称（与前端表单保持一致）
CATEGORIES = {
    "suggestion": "功能建议",
    "bug": "问题反馈",
    "experience": "体验问题",
    "other": "其他",
}

MIN_CONTENT_LENGTH = 5
MAX_CONTENT_LENGTH = 1000

# 单张截图上限 5 MB；安全层为该接口单独放宽请求体上限。
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024

# 按文件头识别真实格式：(魔数, 扩展名, MIME)
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
)


def upload_dir() -> Path:
    """截图目录与数据库同目录，测试切换 DB_PATH 时自然隔离。"""
    path = Path(config.DB_PATH).parent / "feedback_uploads"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def detect_image(data: bytes) -> tuple[str, str] | None:
    """返回 (扩展名, MIME)，无法识别时返回 None。"""
    for magic, ext, mime in _IMAGE_SIGNATURES:
        if data.startswith(magic):
            return ext, mime
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def save_screenshot(data: bytes, ext: str) -> str:
    """原子写入随机文件名，返回文件名（不含目录）。"""
    name = secrets.token_hex(16) + "." + ext
    path = upload_dir() / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return name


def screenshot_path(name: str) -> Path:
    # 统一取 basename，避免历史数据或异常输入造成目录穿越
    return upload_dir() / Path(name).name


def delete_screenshot(name: str | None) -> None:
    if not name:
        return
    try:
        screenshot_path(name).unlink()
    except OSError:
        pass


def delete_user_screenshots(db: sqlite3.Connection, user_id: int) -> None:
    """删除账号前清理该用户的全部截图文件（数据库行由外键级联删除）。"""
    rows = db.execute(
        "SELECT screenshot_name FROM feedback WHERE user_id = ? AND screenshot_name IS NOT NULL",
        (user_id,),
    ).fetchall()
    for row in rows:
        delete_screenshot(row["screenshot_name"])

"""管理员账号命令行工具。

用法（在项目根目录、服务端虚拟环境中执行）：
    python -m helper.admin create <用户名> [--generate | --password 密码]
    python -m helper.admin promote <用户名>
    python -m helper.admin demote <用户名>
    python -m helper.admin list

create 默认生成一次性随机密码并打印到终端，请首次登录后立即修改。
"""

from __future__ import annotations

import argparse
import secrets
import sys

from .api.auth import USERNAME_RE
from .db import connect, init_db
from .security import hash_password, utc_now_iso


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _create(args) -> int:
    username = (args.username or "").strip()
    if not USERNAME_RE.fullmatch(username):
        return _fail("用户名需为 3–32 位字母、数字、下划线或中文")

    generated = not args.password
    password = args.password or secrets.token_urlsafe(12)
    if not 8 <= len(password) <= 128:
        return _fail("密码长度需为 8–128 位")

    conn = connect()
    try:
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists is not None:
            return _fail(f"用户名已存在：{username}")
        password_hash, salt_hex = hash_password(password)
        conn.execute(
            """
            INSERT INTO users
                (username, password_hash, password_salt, is_adult, is_admin, created_at)
            VALUES (?, ?, ?, 1, 1, ?)
            """,
            (username, password_hash, salt_hex, utc_now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"已创建管理员：{username}")
    if generated:
        print(f"一次性密码：{password}")
        print("请立即登录并在“设置”页修改密码；该密码不会再次显示。")
    return 0


def _set_admin(username: str, value: int) -> int:
    conn = connect()
    try:
        cursor = conn.execute(
            "UPDATE users SET is_admin = ? WHERE username = ?",
            (value, username),
        )
        conn.commit()
    finally:
        conn.close()
    if cursor.rowcount == 0:
        return _fail(f"用户不存在：{username}")
    print(("已设为管理员：" if value else "已取消管理员：") + username)
    return 0


def _promote(args) -> int:
    return _set_admin((args.username or "").strip(), 1)


def _demote(args) -> int:
    return _set_admin((args.username or "").strip(), 0)


def _list(args) -> int:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("尚无用户")
        return 0
    for row in rows:
        role = "管理员" if row["is_admin"] else "普通用户"
        print(f"{row['id']:>4}  {row['username']:<24} {role}  {row['created_at']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helper.admin", description="管理员账号管理工具"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create", help="创建管理员账号")
    create_parser.add_argument("username")
    create_parser.add_argument(
        "--generate", action="store_true", help="生成一次性随机密码（默认行为）"
    )
    create_parser.add_argument("--password", default="", help="指定密码（不推荐）")
    create_parser.set_defaults(handler=_create)

    promote_parser = sub.add_parser("promote", help="将已有用户设为管理员")
    promote_parser.add_argument("username")
    promote_parser.set_defaults(handler=_promote)

    demote_parser = sub.add_parser("demote", help="取消用户的管理员权限")
    demote_parser.add_argument("username")
    demote_parser.set_defaults(handler=_demote)

    list_parser = sub.add_parser("list", help="列出全部用户与角色")
    list_parser.set_defaults(handler=_list)

    args = parser.parse_args(argv)
    init_db()
    return int(args.handler(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

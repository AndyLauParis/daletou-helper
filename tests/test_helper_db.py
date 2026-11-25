"""SQLite 连接线程归属的回归测试。

FastAPI 的同步依赖与路由可能在不同线程中执行，若连接保留 sqlite3 默认的
线程检查，会出现 “SQLite objects created in a thread can only be used in
that same thread” 的 500 错误。
"""

from __future__ import annotations

import threading

from helper import config, db


def test_connection_usable_across_threads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "thread.db"))
    db.init_db()

    conn = db.connect()
    result: dict[str, int] = {}

    def work() -> None:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        result["n"] = int(row["n"])

    worker = threading.Thread(target=work)
    worker.start()
    worker.join(timeout=10)

    try:
        assert not worker.is_alive()
        assert result["n"] == 0
    finally:
        conn.close()

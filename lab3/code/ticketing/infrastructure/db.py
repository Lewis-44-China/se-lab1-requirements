"""SQLite 连接与事务封装（对应设计基线中的 S2 持久化与并发）。

关键点：
- isolation_level=None：关闭 sqlite3 模块的隐式事务，由 transaction() 显式控制；
- transaction() 默认 BEGIN IMMEDIATE：写事务一开始就拿写锁，避免“先读后写”的竞态；
- 名额扣减使用带条件的 UPDATE，由数据库保证原子性（ADR-03）。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

# db.py 位于 code/ticketing/infrastructure/，向上三层才是 code/
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema.sql"


class Database:
    """一个 Database 实例持有一个 sqlite3 连接。

    多线程并发测试时，每个线程应各自创建 Database（连接不能跨线程共享）。
    """

    def __init__(self, path: str | Path = "ticketing.db") -> None:
        self.path = str(path)
        self.conn = self._connect()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        if self.path != ":memory:":
            # WAL 让读写不互相阻塞；并发写仍由 SQLite 的写锁串行化
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def initialize(self) -> None:
        """建表；schema.sql 使用 IF NOT EXISTS，可重复执行。"""
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    @contextmanager
    def transaction(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """显式事务；异常回滚，正常提交。"""
        begin = "BEGIN IMMEDIATE" if immediate else "BEGIN"
        self.conn.execute(begin)
        try:
            yield self.conn
        except Exception:
            self.conn.rollback()
            raise
        self.conn.commit()

    def query_one(
        self, sql: str, params: Sequence[object] = ()
    ) -> sqlite3.Row | None:
        """查询单行。"""
        return self.conn.execute(sql, params).fetchone()

    def query_all(
        self, sql: str, params: Sequence[object] = ()
    ) -> list[sqlite3.Row]:
        """查询多行。"""
        return self.conn.execute(sql, params).fetchall()

    def execute(
        self, sql: str, params: Sequence[object] = ()
    ) -> sqlite3.Cursor:
        """单条自动提交语句；业务写入应优先使用 transaction()。"""
        return self.conn.execute(sql, params)

    def close(self) -> None:
        """关闭连接。"""
        self.conn.close()

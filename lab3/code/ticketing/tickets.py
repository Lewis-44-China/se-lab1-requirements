"""票种与容量服务（对应设计基线 D2）。

名额扣减是“不超发”的核心：
    UPDATE ticket_type
       SET occupied = occupied + 1
     WHERE id = ? AND occupied < capacity
影响行数为 1 表示成功，0 表示已满。判断和扣减由同一条 SQL 完成，
不存在“先查余票再更新”的竞态（ADR-03）。
"""

from __future__ import annotations

import sqlite3

from .db import Database
from .errors import Conflict, NotFound, ValidationError
from .models import TicketKind, TicketType


class TicketService:
    """票种查询、原子占用与释放。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_ticket_type(self, ticket_type_id: int) -> TicketType:
        """按 id 取票种。"""
        row = self.db.query_one(
            "SELECT * FROM ticket_type WHERE id = ?", (ticket_type_id,)
        )
        if row is None:
            raise NotFound("票种不存在")
        return TicketType.from_row(row)

    def list_for_session(self, session_id: int) -> list[TicketType]:
        """列出一个场次的票种。"""
        rows = self.db.query_all(
            "SELECT * FROM ticket_type WHERE session_id = ? ORDER BY kind DESC",
            (session_id,),
        )
        return [TicketType.from_row(row) for row in rows]

    def find_for_session_kind(
        self, session_id: int, kind: TicketKind
    ) -> TicketType | None:
        """按场次 + 票种类型查票种。"""
        row = self.db.query_one(
            "SELECT * FROM ticket_type WHERE session_id = ? AND kind = ?",
            (session_id, kind.value),
        )
        return TicketType.from_row(row) if row else None

    def try_occupy(self, conn: sqlite3.Connection, ticket_type_id: int) -> bool:
        """原子占用一个名额；成功返回 True。"""
        cursor = conn.execute(
            """
            UPDATE ticket_type
               SET occupied = occupied + 1
             WHERE id = ? AND occupied < capacity
            """,
            (ticket_type_id,),
        )
        return cursor.rowcount == 1

    def release(self, conn: sqlite3.Connection, ticket_type_id: int) -> None:
        """释放一个名额；用于退票、强制退票和活动取消。"""
        cursor = conn.execute(
            """
            UPDATE ticket_type
               SET occupied = occupied - 1
             WHERE id = ? AND occupied > 0
            """,
            (ticket_type_id,),
        )
        if cursor.rowcount != 1:
            raise Conflict("名额释放失败：票种占用数异常")

    def update_ticket(
        self,
        conn: sqlite3.Connection,
        ticket_type_id: int,
        price_cents: int,
        capacity: int,
    ) -> None:
        """修改票价与容量；容量不得低于当前已占用数。"""
        if price_cents < 0:
            raise ValidationError("票价不能为负数")
        ticket = self.get_ticket_type(ticket_type_id)
        if capacity < ticket.occupied:
            raise ValidationError(
                f"容量不能小于已占用名额（当前已占用 {ticket.occupied}）"
            )
        conn.execute(
            "UPDATE ticket_type SET price_cents = ?, capacity = ? WHERE id = ?",
            (price_cents, capacity, ticket_type_id),
        )

    def session_statistics(self, session_id: int) -> tuple[int, int]:
        """返回 (总容量, 已占用)。"""
        row = self.db.query_one(
            """
            SELECT COALESCE(SUM(capacity), 0) AS total,
                   COALESCE(SUM(occupied), 0) AS used
              FROM ticket_type
             WHERE session_id = ?
            """,
            (session_id,),
        )
        return int(row["total"]), int(row["used"])

    def session_is_full(self, session_id: int) -> bool:
        """场次所有票种都满时返回 True。"""
        total, used = self.session_statistics(session_id)
        return 0 < total <= used

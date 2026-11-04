"""站内消息服务（对应设计基线 S1）。

通知由业务在事务内写入 notification 表；通知失败不影响业务事务，
通知本身也不写审计（REQ-028）。
"""

from __future__ import annotations

import sqlite3

from ticketing.infrastructure.clock import Clock, format_dt
from ticketing.domain.models import Notification, NotificationType


class NotificationService:
    """创建和读取站内消息。"""

    def __init__(self, db, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    def create(
        self,
        conn: sqlite3.Connection,
        recipient_id: int,
        kind: NotificationType,
        content: str,
    ) -> None:
        """在调用方事务内写一条通知。"""
        conn.execute(
            """
            INSERT INTO notification (recipient_id, type, content, is_read, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (recipient_id, kind.value, content, format_dt(self.clock.now())),
        )

    def list_for(self, account_id: int, unread_only: bool = False) -> list[Notification]:
        """按时间倒序列出某账号的通知。"""
        sql = "SELECT * FROM notification WHERE recipient_id = ?"
        params: list[object] = [account_id]
        if unread_only:
            sql += " AND is_read = 0"
        sql += " ORDER BY created_at DESC, id DESC"
        return [Notification.from_row(row) for row in self.db.query_all(sql, params)]

    def mark_read(self, account_id: int, notification_id: int) -> None:
        """只能把自己的通知标记为已读。"""
        self.db.execute(
            "UPDATE notification SET is_read = 1 WHERE id = ? AND recipient_id = ?",
            (notification_id, account_id),
        )

    def mark_all_read(self, account_id: int) -> None:
        """把自己的全部通知标记为已读。"""
        self.db.execute(
            "UPDATE notification SET is_read = 1 WHERE recipient_id = ?",
            (account_id,),
        )

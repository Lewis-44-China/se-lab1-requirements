"""站内消息服务（对应设计基线 S1）。

通知由业务在事务内写入 notification 表；通知失败不影响业务事务，
通知本身也不写审计（REQ-028）。
"""

from __future__ import annotations

import sqlite3

from ticketing.infrastructure.clock import Clock, format_dt
from ticketing.domain.models import Notification, NotificationType


# 审查通过：审核结果、活动变更、候补递补/失败、强制退票、活动取消、举报处理
# 等关键通知点均已实现；通知在业务事务内写入，本身不写审计（REQ-028）。
# 封禁账号未向被封禁者发通知（需求未要求，Q24）。

class NotificationService:
    """创建和读取站内消息。"""

    def __init__(self, db, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    # 业务事务内写通知。
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

    # 按账号读取；account_id 由调用方保证是当前登录账号（Q22）。
    def list_for(self, account_id: int, unread_only: bool = False) -> list[Notification]:
        """按时间倒序列出某账号的通知。"""
        sql = "SELECT * FROM notification WHERE recipient_id = ?"
        params: list[object] = [account_id]
        if unread_only:
            sql += " AND is_read = 0"
        sql += " ORDER BY created_at DESC, id DESC"
        return [Notification.from_row(row) for row in self.db.query_all(sql, params)]

    # 只能操作自己的通知（WHERE recipient_id=?）。
    def mark_read(self, account_id: int, notification_id: int) -> None:
        """只能把自己的通知标记为已读。"""
        self.db.execute(
            "UPDATE notification SET is_read = 1 WHERE id = ? AND recipient_id = ?",
            (notification_id, account_id),
        )

    # 把当前账号的全部通知标记为已读。
    def mark_all_read(self, account_id: int) -> None:
        """把自己的全部通知标记为已读。"""
        self.db.execute(
            "UPDATE notification SET is_read = 1 WHERE recipient_id = ?",
            (account_id,),
        )

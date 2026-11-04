"""审计留痕服务（对应设计基线 M7）。

- 审计只追加，不提供更新/删除接口；
- 关键业务操作必须在同一事务内调用 record()，业务回滚时审计一起回滚；
- 预期失败（名额已满、重复报名等）由调用方在回滚后用 record_standalone()
  单独记录失败原因，满足 REQ-039“报名失败也必须留痕”。
"""

from __future__ import annotations

import sqlite3

from ticketing.infrastructure.clock import Clock, format_dt
from ticketing.domain.models import AuditLog


class AuditService:
    """写审计记录。"""

    def __init__(self, db, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    def record(
        self,
        conn: sqlite3.Connection,
        operator_id: int | None,
        object_type: str,
        object_id: int,
        action: str,
        description: str,
        before_status: str | None = None,
        after_status: str | None = None,
    ) -> None:
        """在调用方事务内写一条留痕。operator_id 为 None 表示系统任务。"""
        conn.execute(
            """
            INSERT INTO audit_log (
                operator_id, operated_at, object_type, object_id,
                action, before_status, after_status, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operator_id,
                format_dt(self.clock.now()),
                object_type,
                object_id,
                action,
                before_status,
                after_status,
                description,
            ),
        )

    def record_standalone(
        self,
        operator_id: int | None,
        object_type: str,
        object_id: int,
        action: str,
        description: str,
        before_status: str | None = None,
        after_status: str | None = None,
    ) -> None:
        """在独立事务中写留痕，用于业务事务已经回滚的失败场景。"""
        with self.db.transaction() as conn:
            self.record(
                conn,
                operator_id,
                object_type,
                object_id,
                action,
                description,
                before_status,
                after_status,
            )

    @staticmethod
    def to_model(row) -> AuditLog:
        """把数据库行转成 AuditLog。"""
        return AuditLog.from_row(row)

"""审计留痕服务（对应设计基线 M7）。

- 审计只追加，不提供更新/删除接口；
- 关键业务操作必须在同一事务内调用 record()，业务回滚时审计一起回滚；
- 预期失败（名额已满、重复报名等）由调用方在回滚后用 record_standalone()
  单独记录失败原因，满足 REQ-039“报名失败也必须留痕”。
"""

from __future__ import annotations

import sqlite3

from ticketing.infrastructure_基础设施.clock import Clock, format_dt
from ticketing.domain_共享能力层.models import AuditLog

# 审查通过：对照 REQ-039，活动/审核/报名/退票/候补/检票/账号/举报的关键操作
# 均已留痕；报名失败用独立事务记录原因；通知本身不写审计（REQ-028）。
# 场次自动状态刷新不写审计（需求未明确要求，Q23）。

# 第二轮审查：对照 REQ-039/REQ-040 逐项核对覆盖范围——
# 活动创建/修改/提交审核/取消、管理员审核通过/驳回/直接取消、活动状态变更；
# 时间/地点/票价/容量修改；报名成功/失败、退票、强制退票；候补加入/递补/取消/
# 失败；检票发起/通过/异常；封禁/解封、举报提交/处理，均有对应 action。
# 管理员强行取消活动走 RefundService.cancel_activity_conn，记 ACTIVITY_CANCELLED。
# 修改类操作的变更值保存在 review_application.payload，审计描述记录变更项（Q37）。
# 每条记录包含 REQ-040 的操作人、时间、对象、action、前后状态和描述。


class AuditService:
    """写审计记录。"""

    def __init__(self, db, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    # 同事务留痕；operator_id=None 表示系统任务；创建类操作前状态可为空。
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

    # 业务回滚后的失败留痕，独立事务。
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

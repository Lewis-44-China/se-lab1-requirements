"""参与者举报活动（A1）与举报查询。

管理员处理举报的入口在 AdminService；这里只负责提交和查看自己的举报。
"""

from __future__ import annotations

from ticketing.common.audit import AuditService
from ticketing.infrastructure.clock import Clock, format_dt
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import NotFound, ValidationError
from ticketing.domain.models import Activity, ActivityStatus, Report, ReportStatus, Role
from ticketing.common.permissions import PermissionService

# 审查通过：提交举报直接 INSERT report（PENDING）并写审计；
# 管理员处理时只更新该条记录的状态/处理人/结果/时间，不删除记录。
# 第二轮审查（2026-11-05）：核实举报的活动状态范围，只排除未公开活动（Q64）。

class ReportService:
    """举报提交与个人举报查询。"""

    def __init__(self, db: Database, clock: Clock, audit: AuditService) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit

    # 参与者提交举报：只能举报已公开/已结束/已取消的活动；原因必填；同事务写审计。
    # 第二轮审查 Q64：REQ-002/018 没有限制举报时的活动状态，只要求活动对参与者
    # 可见；因此排除未公开的 DRAFT/PENDING_REVIEW，允许对已结束/已取消活动举报
    # （用于事后追责），是否属实由管理员处理。
    def submit_report(self, participant, activity_id: int, reason: str) -> Report:
        """参与者举报一个已公开活动。"""
        PermissionService.require_role(participant, Role.PARTICIPANT)
        if not reason.strip():
            raise ValidationError("请填写举报理由")
        row = self.db.query_one(
            "SELECT * FROM activity WHERE id = ?", (activity_id,)
        )
        if row is None:
            raise NotFound("活动不存在")
        activity = Activity.from_row(row)
        if activity.status in (
            ActivityStatus.DRAFT,
            ActivityStatus.PENDING_REVIEW,
        ):
            raise ValidationError("只能举报已公开的活动")
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO report (
                    reporter_id, activity_id, reason, status,
                    handler_id, result, handled_at, created_at
                ) VALUES (?, ?, ?, ?, NULL, '', NULL, ?)
                """,
                (
                    participant.id,
                    activity_id,
                    reason.strip(),
                    ReportStatus.PENDING.value,
                    format_dt(self.clock.now()),
                ),
            )
            report_id = int(cursor.lastrowid)
            self.audit.record(
                conn,
                participant.id,
                "REPORT",
                report_id,
                "REPORT_SUBMITTED",
                f"举报活动《{activity.name}》：{reason.strip()}",
                None,
                ReportStatus.PENDING.value,
            )
        return self.get_report(report_id)

    # 参与者只查看自己提交的举报。
    def list_for_account(self, participant) -> list[Report]:
        """参与者查看自己提交的举报。"""
        PermissionService.require_role(participant, Role.PARTICIPANT)
        rows = self.db.query_all(
            "SELECT * FROM report WHERE reporter_id = ? ORDER BY id DESC",
            (participant.id,),
        )
        return [Report.from_row(row) for row in rows]

    def get_report(self, report_id: int) -> Report:
        """按 id 取举报。"""
        row = self.db.query_one("SELECT * FROM report WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("举报不存在")
        return Report.from_row(row)

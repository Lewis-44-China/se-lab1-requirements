"""参与者举报活动（A1）与举报查询。

管理员处理举报的入口在 AdminService；这里只负责提交和查看自己的举报。
"""

from __future__ import annotations

from .audit import AuditService
from .clock import Clock, format_dt
from .db import Database
from .errors import NotFound, ValidationError
from .models import Activity, ActivityStatus, Report, ReportStatus, Role
from .permissions import PermissionService


class ReportService:
    """举报提交与个人举报查询。"""

    def __init__(self, db: Database, clock: Clock, audit: AuditService) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit

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

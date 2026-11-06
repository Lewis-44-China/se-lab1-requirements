"""管理员审核与处置（对应设计基线 A4）。

审核申请由组织者创建，管理员在这里审批：
- 发布审核：通过 → 公开；驳回 → 草稿；
- 修改审核：通过 → 应用 payload；驳回 → 保持原样；
- 取消申请：通过 → 调用退票服务批量退款；驳回 → 保持原样。

另外提供：创建检票账号、分配检票活动、封禁/解封、举报处理。
"""


# 审查通过：管理员编排分为审核、检票分配、封禁、举报四块。
# 封禁规则对照 REQ-018：组织者封禁 → 其活动自动取消并退款；
# 参与者封禁 → 已购票保留、不退款，仅取消候补，后续不能新增购票。
# 审核与举报的状态更新、审计、通知都在同一事务内。

from __future__ import annotations

import json
import sqlite3

from ticketing.domain_共享能力层.activities import ActivityService
from ticketing.common_横切能力.audit import AuditService
from ticketing.domain_共享能力层.auth import AuthService
from ticketing.infrastructure_基础设施.clock import Clock, format_dt
from ticketing.infrastructure_基础设施.db import Database
from ticketing.domain_共享能力层.errors import Conflict, NotFound, PermissionDenied, ValidationError
from ticketing.domain_共享能力层.models import (
    Activity,
    ActivityStatus,
    NotificationType,
    Report,
    ReportStatus,
    ReviewApplication,
    ReviewStatus,
    ReviewType,
    Role,
)
from ticketing.common_横切能力.notifications import NotificationService
from ticketing.common_横切能力.permissions import PermissionService
from ticketing.domain_共享能力层.queries import QueryService
from ticketing.domain_共享能力层.refunds import RefundService
from ticketing.domain_共享能力层.waitlist import WaitlistService


class AdminService:
    """管理员审核、账号处置与举报处理。"""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        audit: AuditService,
        auth: AuthService,
        activities: ActivityService,
        refunds: RefundService,
        waitlist: WaitlistService,
        notifications: NotificationService,
        queries: QueryService,
    ) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit
        self.auth = auth
        self.activities = activities
        self.refunds = refunds
        self.waitlist = waitlist
        self.notifications = notifications
        self.queries = queries

    # ---------- 审核 ----------

    def list_pending_reviews(self, admin) -> list[ReviewApplication]:
        """待审队列。"""
        PermissionService.require_role(admin, Role.ADMIN)
        return self.activities.list_pending_reviews()

    # 审核入口：校验管理员、审核单仍 PENDING、驳回必须填意见；
    # 事务内先执行领域动作（发布/修改/取消），再更新审核单并写审计；
    # 审核单 UPDATE 检查 rowcount，防止并发重复审核/重复通知。
    def review(
        self, admin, review_id: int, approve: bool, comment: str = ""
    ) -> ReviewApplication:
        """审批一条审核申请。"""
        PermissionService.require_role(admin, Role.ADMIN)
        review = self.activities.get_review(review_id)
        if review.status is not ReviewStatus.PENDING:
            raise Conflict("该审核申请已处理")
        if not approve and not comment.strip():
            raise ValidationError("驳回时必须填写审核意见")
        activity = self.activities.get_activity(review.activity_id)
        with self.db.transaction() as conn:
            self._apply_review(conn, admin, review, activity, approve, comment)
            new_status = (
                ReviewStatus.APPROVED if approve else ReviewStatus.REJECTED
            )
            cursor = conn.execute(
                """
                UPDATE review_application
                   SET status = ?, reviewer_id = ?, comment = ?, reviewed_at = ?
                 WHERE id = ? AND status = 'PENDING'
                """,
                (
                    new_status.value,
                    admin.id,
                    comment.strip(),
                    format_dt(self.clock.now()),
                    review.id,
                ),
            )
            if cursor.rowcount != 1:
                raise Conflict("该审核申请已处理")
            self.audit.record(
                conn,
                admin.id,
                "REVIEW_APPLICATION",
                review.id,
                "REVIEW_APPROVED" if approve else "REVIEW_REJECTED",
                f"{review.type.value} 审核：{comment.strip() or '无意见'}",
                ReviewStatus.PENDING.value,
                new_status.value,
            )
        return self.activities.get_review(review_id)

    # 按审核类型分派领域动作：PUBLISH/MODIFY 由 activities 执行，
    # CANCEL 批准时调 refunds.cancel_activity_conn（批量退款+候补失败）。
    # 本方法不自开事务，由 review 在事务内调用。
    # 第二轮审查 Q66：审计分两层——领域动作写 ACTIVITY（发布/修改/取消/退款），
    # review() 再写 REVIEW_APPLICATION；对象不同，不是重复。驳回只写审核单并
    # 通知组织者；CANCEL 的报名/候补退款审计由 cancel_activity_conn 写。
    def _apply_review(
        self,
        conn: sqlite3.Connection,
        admin,
        review: ReviewApplication,
        activity: Activity,
        approve: bool,
        comment: str,
    ) -> None:
        """根据审核类型执行通过/驳回动作。"""
        if review.type is ReviewType.PUBLISH:
            if approve:
                self.activities.approve_publish(conn, activity, admin.id)
            else:
                self.activities.reject_publish(conn, activity, admin.id, comment)
            return
        if review.type is ReviewType.MODIFY:
            if approve:
                self.activities.apply_modification(
                    conn, activity, review.payload, admin.id
                )
            self.notifications.create(
                conn,
                activity.organizer_id,
                NotificationType.REVIEW_RESULT,
                f"活动《{activity.name}》的修改审核"
                + ("已通过。" if approve else f"被驳回：{comment.strip()}。"),
            )
            return
        if review.type is ReviewType.CANCEL:
            if approve:
                reason = json.loads(review.payload).get(
                    "reason", "组织者申请取消"
                )
                self.refunds.cancel_activity_conn(
                    conn, admin.id, activity, reason
                )
            else:
                self.notifications.create(
                    conn,
                    activity.organizer_id,
                    NotificationType.REVIEW_RESULT,
                    f"活动《{activity.name}》的取消申请被驳回：{comment.strip()}。",
                )
            return
        raise ValidationError("未知的审核类型")

    # ---------- 检票账号与分配 ----------
    # 第二轮审查 Q67：重复分配必须拒绝，否则 INSERT OR IGNORE 不会改表，
    # 但仍会重复写 INSPECTOR_ASSIGNED 审计。用 rowcount 判断是否真的插入。
    def create_inspector(self, admin, phone: str, password: str, name: str):
        """创建检票员账号。"""
        return self.auth.create_inspector(admin, phone, password, name)

    def list_inspectors(self, admin):
        """列出检票员。"""
        PermissionService.require_role(admin, Role.ADMIN)
        return self.auth.list_accounts(Role.INSPECTOR)

    # 分配检票员到活动（管理员）；INSERT OR IGNORE 幂等，重复分配不报错。
    def assign_inspector(self, admin, inspector_id: int, activity_id: int) -> None:
        """把检票员分配到活动。"""
        PermissionService.require_role(admin, Role.ADMIN)
        inspector = self.auth.get_account(inspector_id)
        if inspector.role is not Role.INSPECTOR:
            raise ValidationError("目标账号不是检票员")
        activity = self.activities.get_activity(activity_id)
        # 第二轮审查 Q57：草稿/待审活动未公开，只允许组织者与管理员可见（REQ-003），
        # 不能把检票员分配到这类活动上，否则会通过“已分配活动”看到未公开内容。
        if activity.status in (
            ActivityStatus.DRAFT,
            ActivityStatus.PENDING_REVIEW,
        ):
            raise Conflict("只能给已公开的活动分配检票员")
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO activity_inspector (
                    inspector_id, activity_id, assigned_at
                ) VALUES (?, ?, ?)
                """,
                (inspector_id, activity_id, format_dt(self.clock.now())),
            )
            if cursor.rowcount != 1:
                raise Conflict("该检票员已被分配到该活动")
            self.audit.record(
                conn,
                admin.id,
                "ACTIVITY",
                activity.id,
                "INSPECTOR_ASSIGNED",
                f"分配检票员 {inspector.name} 到活动《{activity.name}》",
                None,
                None,
            )

    # ---------- 封禁 / 解封 ----------

    # 封禁/解封入口：管理员、原因必填、不能封管理员/自己；
    # 事务内调用 _ban_account_conn 完成账号状态与关联业务。
    def ban_account(self, admin, account_id: int, reason: str, ban: bool = True) -> None:
        """封禁或解封账号；封禁组织者会取消其活动，封禁参与者会取消其候补。"""
        PermissionService.require_role(admin, Role.ADMIN)
        if not reason.strip():
            raise ValidationError("请填写封禁/解封原因")
        target = self.auth.get_account(account_id)
        if target.role is Role.ADMIN:
            raise PermissionDenied("不能封禁管理员账号")
        if target.id == admin.id:
            raise PermissionDenied("不能封禁自己")
        with self.db.transaction() as conn:
            self._ban_account_conn(conn, admin, target, reason, ban)

    # 封禁规则对照 REQ-018：
    #   组织者 → 其所有非终态活动自动取消，并按 REQ-037 向报名者退款；
    #   参与者 → 保留已购票（可正常入场、不退款），只取消 WAITING 候补；
    #   检票员 → 只封账号，分配记录保留（无法登录，无实际影响）。
    def _ban_account_conn(
        self, conn: sqlite3.Connection, admin, target, reason: str, ban: bool
    ) -> None:
        """在调用方事务内更新账号状态并处理关联业务。"""
        new_status = "BANNED" if ban else "NORMAL"
        # 第二轮测试补充：状态没变化时不再重复写封禁/解封审计。
        cursor = conn.execute(
            "UPDATE account SET status = ? WHERE id = ? AND status != ?",
            (new_status, target.id, new_status),
        )
        if cursor.rowcount != 1:
            raise Conflict("账号状态未变化，无需重复操作")
        self.audit.record(
            conn,
            admin.id,
            "ACCOUNT",
            target.id,
            "ACCOUNT_BANNED" if ban else "ACCOUNT_UNBANNED",
            f"{'封禁' if ban else '解封'}账号：{reason}",
            target.status.value,
            new_status,
        )
        if not ban:
            return
        if target.role is Role.ORGANIZER:
            rows = conn.execute(
                """
                SELECT * FROM activity
                 WHERE organizer_id = ? AND status NOT IN ('CANCELLED', 'ENDED')
                """,
                (target.id,),
            ).fetchall()
            for row in rows:
                self.refunds.cancel_activity_conn(
                    conn,
                    admin.id,
                    Activity.from_row(row),
                    f"组织者被封禁：{reason}",
                )
        elif target.role is Role.PARTICIPANT:
            self.waitlist.cancel_waiting_for_account_conn(
                conn, target.id, admin.id, f"账号被封禁：{reason}"
            )

    # ---------- 举报 ----------

    def list_reports(self, admin, pending_only: bool = False) -> list[Report]:
        """举报列表。"""
        PermissionService.require_role(admin, Role.ADMIN)
        sql = "SELECT * FROM report"
        params: list[object] = []
        if pending_only:
            sql += " WHERE status = ?"
            params.append(ReportStatus.PENDING.value)
        sql += " ORDER BY created_at DESC, id DESC"
        return [Report.from_row(row) for row in self.db.query_all(sql, params)]

    def get_report(self, report_id: int) -> Report:
        """按 id 取举报。"""
        row = self.db.query_one("SELECT * FROM report WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("举报不存在")
        return Report.from_row(row)

    # 举报处理：举报必须仍 PENDING；可选择取消活动或封禁组织者（封禁优先）；
    # 全部在同一事务内，最后更新举报状态并通知举报人。
    # 举报状态 UPDATE 检查 rowcount，防止并发重复处理。
    def handle_report(
        self,
        admin,
        report_id: int,
        *,
        dismiss: bool,
        result: str,
        cancel_activity: bool = False,
        ban_organizer: bool = False,
    ) -> None:
        """处理举报；可选择取消活动或封禁组织者。"""
        PermissionService.require_role(admin, Role.ADMIN)
        if not result.strip():
            raise ValidationError("请填写处理结果")
        report = self.get_report(report_id)
        if report.status is not ReportStatus.PENDING:
            raise Conflict("该举报已处理")
        activity = self.activities.get_activity(report.activity_id)
        with self.db.transaction() as conn:
            if not dismiss:
                if ban_organizer:
                    organizer = self.auth.get_account(activity.organizer_id)
                    self._ban_account_conn(
                        conn, admin, organizer, f"举报处理：{result.strip()}", True
                    )
                elif cancel_activity:
                    self.refunds.cancel_activity_conn(
                        conn, admin.id, activity, f"举报处理：{result.strip()}"
                    )
            new_status = (
                ReportStatus.DISMISSED if dismiss else ReportStatus.RESOLVED
            )
            cursor = conn.execute(
                """
                UPDATE report
                   SET status = ?, handler_id = ?, result = ?, handled_at = ?
                 WHERE id = ? AND status = 'PENDING'
                """,
                (
                    new_status.value,
                    admin.id,
                    result.strip(),
                    format_dt(self.clock.now()),
                    report.id,
                ),
            )
            if cursor.rowcount != 1:
                raise Conflict("该举报已处理")
            self.audit.record(
                conn,
                admin.id,
                "REPORT",
                report.id,
                "REPORT_HANDLED",
                f"举报处理：{result.strip()}",
                ReportStatus.PENDING.value,
                new_status.value,
            )
            self.notifications.create(
                conn,
                report.reporter_id,
                NotificationType.REVIEW_RESULT,
                f"您的举报已处理：{result.strip()}",
            )

    # ---------- 管理员查询入口 ----------

    def all_activities(self, admin) -> list[Activity]:
        """管理员查看全部活动（含草稿）。"""
        PermissionService.require_role(admin, Role.ADMIN)
        rows = self.db.query_all("SELECT * FROM activity ORDER BY id DESC")
        return [Activity.from_row(row) for row in rows]

    def list_accounts(self, admin):
        """管理员查看全部账号。"""
        PermissionService.require_role(admin, Role.ADMIN)
        return self.auth.list_accounts()

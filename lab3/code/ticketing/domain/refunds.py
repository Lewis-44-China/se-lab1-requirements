"""退票、强制退票与活动取消退款（对应设计基线 D4）。

三个入口的前置条件不同，但底层共用 _refund_registration_conn：
- 参与者退票：本人、已购票、未过退票截止；
- 管理员强制退票：管理员、已购票、需原因、需通知；
- 活动取消：批量处理已购票和已检票记录，全部退款。
参与者/管理员退票会写 CapacityReleased 事件，触发候补递补；
活动取消不再递补，因此不写事件。
"""

# 审查说明：本类有 3 个退款入口 + 1 个事务内批量取消 + 1 个共用退款动作：
#   refund_by_participant  参与者本人退票（入口）
#   force_refund           管理员强制退票（入口）
#   cancel_activity        管理员直接取消活动（入口）
#   cancel_activity_conn   取消活动的事务内版本，供审核/封禁/举报复用
#   _refund_registration_conn  以上入口最终都调用的“单条报名退款”动作
# 入口负责权限、前置校验、开事务；*_conn 方法假设调用方已开事务。
# 所有退款共用 _refund_registration_conn，避免三处重复。

from __future__ import annotations

import json
import sqlite3

from ticketing.common.audit import AuditService
from ticketing.infrastructure.clock import Clock, format_dt, parse_dt
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import Conflict, DeadlinePassed, NotFound, ValidationError
from ticketing.domain.models import (
    Activity,
    ActivityStatus,
    NotificationType,
    Registration,
    RegistrationStatus,
    Role,
    SessionStatus,
    WaitlistRecord,
)
from ticketing.common.notifications import NotificationService
from ticketing.common.permissions import PermissionService
from ticketing.domain.tickets import TicketService
from ticketing.domain.waitlist import WaitlistService


class RefundService:
    """退票与活动取消。"""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        audit: AuditService,
        tickets: TicketService,
        notifications: NotificationService,
        waitlist: WaitlistService,
    ) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit
        self.tickets = tickets
        self.notifications = notifications
        self.waitlist = waitlist

    # 入口 1：参与者本人退票。校验参与者角色、本人、已购票、未过退票截止。
    # 自己开事务；write_event=True 会在释放名额后写 CapacityReleased，
    # 由 Scheduler.tick → PromotionService 触发候补递补。
    def refund_by_participant(self, participant, registration_id: int) -> Registration:
        """参与者退票：退票截止前、本人、已购票。"""
        registration = self.get_registration(registration_id)
        PermissionService.require_role(participant, Role.PARTICIPANT)
        PermissionService.require_owner(
            participant, registration.account_id, "报名记录"
        )
        activity = self.get_activity(registration.activity_id)
        if registration.status is not RegistrationStatus.PURCHASED:
            raise Conflict("只有“已购票”状态的报名可以退票")
        if self.clock.now() > parse_dt(activity.refund_deadline):
            raise DeadlinePassed("已超过退票截止时间")
        with self.db.transaction() as conn:
            self._refund_registration_conn(
                conn,
                registration,
                RegistrationStatus.SELF_CANCELLED,
                participant.id,
                "参与者退票",
                write_event=True,
            )
        return self.get_registration(registration_id)

    # 入口 2：管理员强制退票。管理员角色、原因必填、仅“已购票”可退。
    # 同样写 CapacityReleased 触发候补递补，并额外发 FORCE_REFUND 通知。
    # 备注：报名状态仍记 SELF_CANCELLED，审计 action 通过通知类型区分为 FORCE_REFUND。
    def force_refund(
        self, admin, registration_id: int, reason: str
    ) -> Registration:
        """管理员强制退票（REQ-048）：退款、通知、留痕、释放名额。"""
        PermissionService.require_role(admin, Role.ADMIN)
        if not reason.strip():
            raise ValidationError("请填写强制退票原因")
        registration = self.get_registration(registration_id)
        if registration.status is not RegistrationStatus.PURCHASED:
            raise Conflict("只能对“已购票”状态执行强制退票")
        with self.db.transaction() as conn:
            self._refund_registration_conn(
                conn,
                registration,
                RegistrationStatus.SELF_CANCELLED,
                admin.id,
                f"管理员强制退票：{reason.strip()}",
                write_event=True,
                notify=NotificationType.FORCE_REFUND,
                notify_content=f"您的报名已被管理员强制退票，退款原因：{reason.strip()}。",
            )
        return self.get_registration(registration_id)

    # 入口 3：管理员直接紧急取消活动（公开入口）。
    # 只做管理员权限与原因校验，然后开事务；真正的批量逻辑在 cancel_activity_conn。
    def cancel_activity(self, admin, activity_id: int, reason: str) -> int:
        """管理员紧急取消活动；返回受影响的报名记录数。"""
        PermissionService.require_role(admin, Role.ADMIN)
        if not reason.strip():
            raise ValidationError("请填写取消原因")
        activity = self.get_activity(activity_id)
        with self.db.transaction() as conn:
            return self.cancel_activity_conn(conn, admin.id, activity, reason)

    # 批量取消活动的“事务内版本”：不自开事务，假设调用方已开事务并完成权限/原因校验。
    # 被三类调用方复用：
    #   - cancel_activity（管理员直接取消）
    #   - AdminService.review 的“取消申请审核通过”
    #   - AdminService 封禁组织者 / 举报处理联动取消
    # 做四件事：活动/场次置 CANCELLED；已购票/已检票批量退款；
    # WAITING 候补转 FAILED 并退款；写活动审计、通知组织者。
    # write_event=False：活动已取消，候补不再递补。
    def cancel_activity_conn(
        self,
        conn: sqlite3.Connection,
        operator_id: int,
        activity: Activity,
        reason: str,
    ) -> int:
        """在调用方事务内取消活动并批量退款。

        AdminService 审批“取消申请”时也调用本方法，保证审核状态和
        业务取消在同一事务里完成。
        """
        if activity.status is ActivityStatus.CANCELLED:
            raise Conflict("活动已取消")
        if activity.status is ActivityStatus.ENDED:
            raise Conflict("活动已结束，不能取消")
        conn.execute(
            "UPDATE activity SET status = ? WHERE id = ?",
            (ActivityStatus.CANCELLED.value, activity.id),
        )
        conn.execute(
            "UPDATE activity_session SET status = ? WHERE activity_id = ?",
            (SessionStatus.CANCELLED.value, activity.id),
        )
        registrations = conn.execute(
            """
            SELECT * FROM registration
             WHERE activity_id = ?
               AND status IN ('PURCHASED', 'CHECKED_IN')
            """,
            (activity.id,),
        ).fetchall()
        for row in registrations:
            registration = Registration.from_row(row)
            self._refund_registration_conn(
                conn,
                registration,
                RegistrationStatus.ACTIVITY_CANCELLED,
                operator_id,
                f"活动取消：{reason}",
                write_event=False,
                notify=NotificationType.ACTIVITY_CANCELLED,
                notify_content=f"活动《{activity.name}》已取消，票款将全额退还。",
            )
        waitlist_rows = conn.execute(
            """
            SELECT * FROM waitlist_record
             WHERE activity_id = ? AND status = 'WAITING'
            """,
            (activity.id,),
        ).fetchall()
        for row in waitlist_rows:
            self.waitlist.mark_failed_conn(
                conn,
                WaitlistRecord.from_row(row),
                f"活动取消：{reason}",
                operator_id,
            )
        self.audit.record(
            conn,
            operator_id,
            "ACTIVITY",
            activity.id,
            "ACTIVITY_CANCELLED",
            f"取消活动并退款：{reason}",
            activity.status.value,
            ActivityStatus.CANCELLED.value,
        )
        self.notifications.create(
            conn,
            activity.organizer_id,
            NotificationType.ACTIVITY_CANCELLED,
            f"活动《{activity.name}》已被取消，原因：{reason}。",
        )
        return len(registrations)

    # 所有退款入口共用的“单条报名退款”动作（事务内）：
    # 1) 条件 UPDATE 改终态 + 记录退款金额/时间，rowcount 必须为 1；
    # 2) 原记录占名额则释放（退票/活动取消都要还名额）；
    # 3) 写报名审计；
    # 4) write_event=True 时写 Outbox，触发候补递补；notify 非空时发站内消息。
    # 状态区分：参与者/强制退票传 SELF_CANCELLED；活动取消传 ACTIVITY_CANCELLED。
    def _refund_registration_conn(
        self,
        conn: sqlite3.Connection,
        registration: Registration,
        new_status: RegistrationStatus,
        operator_id: int,
        reason: str,
        *,
        write_event: bool,
        notify: NotificationType | None = None,
        notify_content: str = "",
    ) -> None:
        """共用退款逻辑：改状态、退款、释放名额、审计、可选事件/通知。"""
        now = format_dt(self.clock.now())
        cursor = conn.execute(
            """
            UPDATE registration
               SET status = ?, refund_amount_cents = payment_amount_cents,
                   refund_time = ?
             WHERE id = ? AND status IN ('PURCHASED', 'CHECKED_IN')
            """,
            (new_status.value, now, registration.id),
        )
        if cursor.rowcount != 1:
            raise Conflict("报名记录状态已变化，退款失败")
        if registration.occupies_seat:
            self.tickets.release(conn, registration.ticket_type_id)
        action = (
            "FORCE_REFUND"
            if notify is NotificationType.FORCE_REFUND
            else "REFUND"
        )
        self.audit.record(
            conn,
            operator_id,
            "REGISTRATION",
            registration.id,
            action,
            reason,
            registration.status.value,
            new_status.value,
        )
        if write_event:
            payload = json.dumps(
                {
                    "ticket_type_id": registration.ticket_type_id,
                    "registration_id": registration.id,
                },
                ensure_ascii=False,
            )
            conn.execute(
                """
                INSERT INTO outbox_message (
                    event_type, payload, status, retry_count, created_at
                ) VALUES ('CapacityReleased', ?, 'NEW', 0, ?)
                """,
                (payload, now),
            )
        if notify is not None:
            self.notifications.create(
                conn,
                registration.account_id,
                notify,
                notify_content,
            )

    # 查询辅助：按 id 取报名，不存在抛 NotFound；入口和外部调用复用。
    def get_registration(self, registration_id: int) -> Registration:
        """取报名记录。"""
        row = self.db.query_one(
            "SELECT * FROM registration WHERE id = ?", (registration_id,)
        )
        if row is None:
            raise NotFound("报名记录不存在")
        return Registration.from_row(row)

    # 查询辅助：按 id 取活动，不存在抛 NotFound；入口和外部调用复用。
    def get_activity(self, activity_id: int) -> Activity:
        """取活动。"""
        row = self.db.query_one("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise NotFound("活动不存在")
        return Activity.from_row(row)

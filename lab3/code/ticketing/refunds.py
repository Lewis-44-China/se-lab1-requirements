"""退票、强制退票与活动取消退款（对应设计基线 D4）。

三个入口的前置条件不同，但底层共用 _refund_registration_conn：
- 参与者退票：本人、已购票、未过退票截止；
- 管理员强制退票：管理员、已购票、需原因、需通知；
- 活动取消：批量处理已购票和已检票记录，全部退款。
参与者/管理员退票会写 CapacityReleased 事件，触发候补递补；
活动取消不再递补，因此不写事件。
"""

from __future__ import annotations

import json
import sqlite3

from .audit import AuditService
from .clock import Clock, format_dt, parse_dt
from .db import Database
from .errors import Conflict, DeadlinePassed, NotFound, ValidationError
from .models import (
    Activity,
    ActivityStatus,
    NotificationType,
    Registration,
    RegistrationStatus,
    Role,
    SessionStatus,
    WaitlistRecord,
)
from .notifications import NotificationService
from .permissions import PermissionService
from .tickets import TicketService
from .waitlist import WaitlistService


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

    def cancel_activity(self, admin, activity_id: int, reason: str) -> int:
        """管理员紧急取消活动；返回受影响的报名记录数。"""
        PermissionService.require_role(admin, Role.ADMIN)
        if not reason.strip():
            raise ValidationError("请填写取消原因")
        activity = self.get_activity(activity_id)
        with self.db.transaction() as conn:
            return self.cancel_activity_conn(conn, admin.id, activity, reason)

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

    def get_registration(self, registration_id: int) -> Registration:
        """取报名记录。"""
        row = self.db.query_one(
            "SELECT * FROM registration WHERE id = ?", (registration_id,)
        )
        if row is None:
            raise NotFound("报名记录不存在")
        return Registration.from_row(row)

    def get_activity(self, activity_id: int) -> Activity:
        """取活动。"""
        row = self.db.query_one("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise NotFound("活动不存在")
        return Activity.from_row(row)

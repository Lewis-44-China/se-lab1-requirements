"""候补队列（对应设计基线 D4）。

每个票种一条队列，记录按 join_time、id 升序 FIFO：
- 入队在队尾；
- 退票释放名额后写 CapacityReleased 事件，由递补编排器取队首；
- 候补取消、候补截止失败都退全款；
- 同一账号同一场次同时只允许一条“候补中”记录。
"""

# 第二轮审查（2026-11-05）：对照 REQ-019/020/023/049 复核入队条件、FIFO、
# 取消/截止失败退款与状态迁移；补并发唯一约束兜底和队列创建竞态处理（Q48）。

from __future__ import annotations

import sqlite3

from ticketing.common_横切能力.audit import AuditService
from ticketing.infrastructure_基础设施.clock import Clock, format_dt, parse_dt
from ticketing.infrastructure_基础设施.db import Database
from ticketing.domain_共享能力层.errors import (
    AppError,
    Conflict,
    DeadlinePassed,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from ticketing.domain_共享能力层.models import (
    Account,
    Activity,
    ActivityStatus,
    NotificationType,
    PaymentStatus,
    Role,
    Session,
    TicketKind,
    WaitlistRecord,
    WaitlistStatus,
)
from ticketing.common_横切能力.notifications import NotificationService
from ticketing.common_横切能力.permissions import PermissionService
from ticketing.infrastructure_基础设施.security import normalize_phone
from ticketing.domain_共享能力层.tickets import TicketService


class WaitlistService:
    """候补入队、取消、失败退款与查询。"""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        audit: AuditService,
        tickets: TicketService,
        notifications: NotificationService,
    ) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit
        self.tickets = tickets
        self.notifications = notifications

    def enqueue(
        self,
        participant,
        session_id: int,
        kind: TicketKind,
        request_id: str,
        buyer_name: str,
        buyer_phone: str,
    ) -> WaitlistRecord:
        """名额已满时加入候补队列。"""
        try:
            return self._enqueue_impl(
                participant, session_id, kind, request_id, buyer_name, buyer_phone
            )
        except AppError as exc:
            self.audit.record_standalone(
                participant.id,
                "SESSION",
                session_id,
                "WAITLIST_JOIN_FAILED",
                f"候补失败：{exc.message}",
            )
            raise

    def _enqueue_impl(
        self,
        participant,
        session_id: int,
        kind: TicketKind,
        request_id: str,
        buyer_name: str,
        buyer_phone: str,
    ) -> WaitlistRecord:
        participant = self._fresh_account(participant.id)
        PermissionService.require_role(participant, Role.PARTICIPANT)
        # 第二轮审查：这里的 require_active 不是重复检查——CLI 用的是登录时的
        # 账号对象，可能在会话期间被封禁；重新读库才能让封禁立即生效（REQ-018）。
        PermissionService.require_active(participant)
        if not buyer_name.strip():
            raise ValidationError("候补人姓名不能为空")
        if normalize_phone(buyer_phone) != participant.phone:
            raise ValidationError("候补人手机号必须与当前账号一致")
        request_id = request_id.strip()
        if not request_id:
            raise ValidationError("请求编号不能为空")
        existing = self.find_by_request_id(request_id)
        if existing is not None:
            if existing.account_id != participant.id:
                raise Conflict("请求编号已被其他账号使用")
            return existing

        session = self._get_session(session_id)
        activity = self._get_activity(session.activity_id)
        if activity.status not in (ActivityStatus.PUBLISHED, ActivityStatus.ONGOING):
            raise PermissionDenied("活动尚未公开或已结束，不能候补")
        now = self.clock.now()
        # 第二轮最终复核 Q77：截止瞬间也拒绝入队，与 expire_due 的
        # “截止时仍未递补即失败”口径一致，避免最后一刻入队后立刻失败。
        if now >= parse_dt(activity.waitlist_deadline):
            raise DeadlinePassed("候补已截止")
        # 第三轮缺陷 BUG-03：即使读到历史数据（候补截止晚于售票截止），
        # 售票截止后也不能再加入候补；新数据由创建校验保证两者相等。
        if now >= parse_dt(activity.sale_end):
            raise DeadlinePassed("售票已截止，不能加入候补")
        if now >= parse_dt(session.end_time):
            raise DeadlinePassed("场次已结束")
        if not session.allow_waitlist:
            raise Conflict("该场次不允许候补")
        if self._has_registration(participant.id, session_id):
            raise Conflict("该账号在此场次已有报名记录")
        if self.active_for_account_session(participant.id, session_id):
            raise Conflict("该账号在此场次已有候补记录")

        ticket = self.tickets.find_for_session_kind(session_id, kind)
        if ticket is None:
            raise NotFound("该场次没有此票种")
        if ticket.remaining > 0:
            raise Conflict("该票种仍有余票，请直接报名")
        try:
            with self.db.transaction() as conn:
                waitlist_id = self._ensure_waitlist(conn, ticket.id)
                cursor = conn.execute(
                    """
                    INSERT INTO waitlist_record (
                        waitlist_id, account_id, activity_id, session_id, join_time,
                        payment_status, payment_amount_cents, status,
                        refund_amount_cents, refund_time, request_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                    """,
                    (
                        waitlist_id,
                        participant.id,
                        activity.id,
                        session_id,
                        format_dt(now),
                        PaymentStatus.PAID.value,
                        ticket.price_cents,
                        WaitlistStatus.WAITING.value,
                        request_id,
                        format_dt(now),
                    ),
                )
                record_id = int(cursor.lastrowid)
                self.audit.record(
                    conn,
                    participant.id,
                    "WAITLIST_RECORD",
                    record_id,
                    "WAITLIST_JOINED",
                    f"加入候补：《{activity.name}》{session.session_no} {kind.value}",
                    None,
                    WaitlistStatus.WAITING.value,
                )
            return self.get_record(record_id)
        except sqlite3.IntegrityError as exc:
            # 第二轮审查 Q48：并发下唯一约束兜底，与报名链路保持一致。
            # 先确认 request_id 归属，避免把其他账号的记录当幂等结果返回。
            existing = self.find_by_request_id(request_id)
            if existing is not None and existing.account_id != participant.id:
                raise Conflict("请求编号已被其他账号使用") from exc
            if existing is None:
                existing = self.active_for_account_session(participant.id, session_id)
            if existing is not None:
                return existing
            raise Conflict("候补冲突，请重试") from exc

    def cancel(self, participant, record_id: int) -> WaitlistRecord:
        """参与者取消候补，退全款。"""
        record = self.get_record(record_id)
        PermissionService.require_role(participant, Role.PARTICIPANT)
        PermissionService.require_owner(participant, record.account_id, "候补记录")
        if record.status is not WaitlistStatus.WAITING:
            raise Conflict("只有候补中的记录可以取消")
        with self.db.transaction() as conn:
            self._mark_self_cancelled(conn, record, participant.id)
        return self.get_record(record_id)


    # 审查通过：三种失败场景最终都走 mark_failed_conn：
    #   - 候补截止 / 场次结束 → 本方法（expire_due）扫描 WAITING 记录；
    #   - 活动取消 → RefundService.cancel_activity_conn 扫描 WAITING 记录；
    #   - 账号封禁 → cancel_waiting_for_account_conn 扫描 WAITING 记录。
    # mark_failed_conn 用条件 UPDATE（WHERE status='WAITING'）+ rowcount 检查，
    # 同一记录只会成功退款一次；已递补/已取消/已失败的记录不会重复退款。
    def expire_due(self) -> int:
        """候补截止或场次结束后，把仍在等待的记录转为候补失败并退款。"""
        rows = self.db.query_all(
            """
            SELECT w.*, a.waitlist_deadline, s.end_time
              FROM waitlist_record w
              JOIN activity a ON a.id = w.activity_id
              JOIN activity_session s ON s.id = w.session_id
             WHERE w.status = 'WAITING'
            """
        )
        count = 0
        now = self.clock.now()
        for row in rows:
            deadline = parse_dt(row["waitlist_deadline"])
            session_end = parse_dt(row["end_time"])
            if now < deadline and now < session_end:
                continue
            record = WaitlistRecord.from_row(row)
            with self.db.transaction() as conn:
                if self.mark_failed_conn(conn, record, "候补截止仍未递补", None):
                    count += 1
        return count
    # 审查通过：失败时统一发 WAITLIST_FAILED 站内通知（reason 文案区分截止/
    # 场次结束/活动取消/账号封禁），同时写审计、退全款；参与者主动取消走
    # _mark_self_cancelled，只退款和写审计，不发通知（用户自己的操作）。
    def mark_failed_conn(
        self,
        conn: sqlite3.Connection,
        record: WaitlistRecord,
        reason: str,
        operator_id: int | None,
    ) -> bool:
        """在调用方事务内把候补记录置为失败并退全款。"""
        now = self.clock.now()
        cursor = conn.execute(
            """
            UPDATE waitlist_record
               SET status = ?, refund_amount_cents = payment_amount_cents,
                   refund_time = ?
             WHERE id = ? AND status = 'WAITING'
            """,
            (WaitlistStatus.FAILED.value, format_dt(now), record.id),
        )
        if cursor.rowcount != 1:
            return False
        self.audit.record(
            conn,
            operator_id,
            "WAITLIST_RECORD",
            record.id,
            "WAITLIST_FAILED",
            f"候补失败并退款：{reason}",
            WaitlistStatus.WAITING.value,
            WaitlistStatus.FAILED.value,
        )
        self.notifications.create(
            conn,
            record.account_id,
            NotificationType.WAITLIST_FAILED,
            f"候补未能成功，已全额退款：{reason}。",
        )
        return True

    def mark_promoted_conn(
        self,
        conn: sqlite3.Connection,
        record: WaitlistRecord,
        operator_id: int | None,
    ) -> None:
        """在调用方事务内把候补记录置为已递补。"""
        cursor = conn.execute(
            """
            UPDATE waitlist_record
               SET status = ?, refund_amount_cents = NULL, refund_time = NULL
             WHERE id = ? AND status = 'WAITING'
            """,
            (WaitlistStatus.PROMOTED.value, record.id),
        )
        if cursor.rowcount != 1:
            raise Conflict("候补记录状态已变化")
        self.audit.record(
            conn,
            operator_id,
            "WAITLIST_RECORD",
            record.id,
            "WAITLIST_PROMOTED",
            "候补递补成功，已生成报名记录",
            WaitlistStatus.WAITING.value,
            WaitlistStatus.PROMOTED.value,
        )
        self.notifications.create(
            conn,
            record.account_id,
            NotificationType.WAITLIST_PROMOTED,
            "您已候补成功，系统已自动生成报名记录（已购票）。",
        )

    def cancel_waiting_for_account_conn(
        self, conn: sqlite3.Connection, account_id: int, operator_id: int, reason: str
    ) -> int:
        """封禁账号时取消其全部候补中记录并退款。"""
        rows = conn.execute(
            """
            SELECT * FROM waitlist_record
             WHERE account_id = ? AND status = 'WAITING'
            """,
            (account_id,),
        ).fetchall()
        count = 0
        for row in rows:
            record = WaitlistRecord.from_row(row)
            if self.mark_failed_conn(conn, record, reason, operator_id):
                count += 1
        return count

    def get_record(self, record_id: int) -> WaitlistRecord:
        """按 id 取候补记录。"""
        row = self.db.query_one(
            "SELECT * FROM waitlist_record WHERE id = ?", (record_id,)
        )
        if row is None:
            raise NotFound("候补记录不存在")
        return WaitlistRecord.from_row(row)

    def find_by_request_id(self, request_id: str) -> WaitlistRecord | None:
        """按请求幂等号查找候补记录。"""
        row = self.db.query_one(
            "SELECT * FROM waitlist_record WHERE request_id = ?", (request_id,)
        )
        return WaitlistRecord.from_row(row) if row else None

    def active_for_account_session(
        self, account_id: int, session_id: int
    ) -> WaitlistRecord | None:
        """查某账号在某场次是否已有“候补中”记录。"""
        row = self.db.query_one(
            """
            SELECT * FROM waitlist_record
             WHERE account_id = ? AND session_id = ? AND status = 'WAITING'
            """,
            (account_id, session_id),
        )
        return WaitlistRecord.from_row(row) if row else None

    def list_for_account(self, account_id: int) -> list[WaitlistRecord]:
        """某账号的全部候补记录，时间倒序。"""
        rows = self.db.query_all(
            """
            SELECT * FROM waitlist_record
             WHERE account_id = ?
             ORDER BY join_time DESC, id DESC
            """,
            (account_id,),
        )
        return [WaitlistRecord.from_row(row) for row in rows]

    def list_for_ticket_type(self, ticket_type_id: int) -> list[WaitlistRecord]:
        """按 FIFO 顺序列出某票种的候补记录（含历史）。"""
        waitlist = self._get_waitlist(ticket_type_id)
        rows = self.db.query_all(
            """
            SELECT * FROM waitlist_record
             WHERE waitlist_id = ?
             ORDER BY join_time, id
            """,
            (waitlist["id"],),
        )
        return [WaitlistRecord.from_row(row) for row in rows]

    def head(self, ticket_type_id: int) -> WaitlistRecord | None:
        """取队首（最早的候补中记录）。"""
        waitlist = self._get_waitlist(ticket_type_id)
        row = self.db.query_one(
            """
            SELECT * FROM waitlist_record
             WHERE waitlist_id = ? AND status = 'WAITING'
             ORDER BY join_time, id
             LIMIT 1
            """,
            (waitlist["id"],),
        )
        return WaitlistRecord.from_row(row) if row else None

    def _mark_self_cancelled(
        self, conn: sqlite3.Connection, record: WaitlistRecord, operator_id: int
    ) -> None:
        """参与者取消候补：状态改为自行取消并退全款。"""
        now = format_dt(self.clock.now())
        cursor = conn.execute(
            """
            UPDATE waitlist_record
               SET status = ?, refund_amount_cents = payment_amount_cents,
                   refund_time = ?
             WHERE id = ? AND status = 'WAITING'
            """,
            (WaitlistStatus.SELF_CANCELLED.value, now, record.id),
        )
        if cursor.rowcount != 1:
            raise Conflict("候补记录状态已变化")
        self.audit.record(
            conn,
            operator_id,
            "WAITLIST_RECORD",
            record.id,
            "WAITLIST_CANCELLED",
            "参与者取消候补，全额退款",
            WaitlistStatus.WAITING.value,
            WaitlistStatus.SELF_CANCELLED.value,
        )

    def _fresh_account(self, account_id: int) -> Account:
        """重新读取账号，确保封禁状态立即生效。"""
        row = self.db.query_one("SELECT * FROM account WHERE id = ?", (account_id,))
        if row is None:
            raise NotFound("账号不存在")
        return Account.from_row(row)

    def _ensure_waitlist(self, conn: sqlite3.Connection, ticket_type_id: int) -> int:
        """确保票种存在一条候补队列，返回队列 id。"""
        # 第二轮审查 Q48：并发首次入队时用 INSERT OR IGNORE，避免两个事务
        # 同时 SELECT 不到队列、又同时 INSERT 触发唯一约束。
        conn.execute(
            "INSERT OR IGNORE INTO waitlist (ticket_type_id, created_at) "
            "VALUES (?, ?)",
            (ticket_type_id, format_dt(self.clock.now())),
        )
        row = conn.execute(
            "SELECT id FROM waitlist WHERE ticket_type_id = ?", (ticket_type_id,)
        ).fetchone()
        return int(row["id"])

    def _get_waitlist(self, ticket_type_id: int):
        row = self.db.query_one(
            "SELECT * FROM waitlist WHERE ticket_type_id = ?", (ticket_type_id,)
        )
        if row is None:
            raise NotFound("该票种没有候补队列")
        return row

    def _get_session(self, session_id: int) -> Session:
        row = self.db.query_one(
            "SELECT * FROM activity_session WHERE id = ?", (session_id,)
        )
        if row is None:
            raise NotFound("场次不存在")
        return Session.from_row(row)

    def _get_activity(self, activity_id: int) -> Activity:
        row = self.db.query_one("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise NotFound("活动不存在")
        return Activity.from_row(row)

    def _has_registration(self, account_id: int, session_id: int) -> bool:
        row = self.db.query_one(
            "SELECT 1 FROM registration WHERE account_id = ? AND session_id = ?",
            (account_id, session_id),
        )
        return row is not None

# 第二轮审查：入队要求“活动公开/进行中 + 未过候补截止 + 场次未结束 +
# 场次允许候补 + 票种已满 + 无报名/无候补中记录”，与 REQ-019/049 一致；
# FIFO 由 head() 的 (join_time, id) 排序保证；取消/截止失败都退全款并留痕。

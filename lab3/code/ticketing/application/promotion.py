"""候补递补编排器（D3/D4 事件解耦的关键）。

退票释放名额后，D4 只往 Outbox 写 CapacityReleased 事件，不直接调用 D3；
本类消费事件：取该票种队首 → 原子占用名额 → 生成报名记录 → 更新候补状态。
这样编译期依赖只有 D3 → D4，D4 不反向依赖 D3。
"""

# 嗯我看了 就是这边还是很保守的防护的，对于其实我们刚开始允许进入候补时候的条件这边又进行了判断，确保没问题还是很严谨的
# 审查通过：_process_event 在消费时再次检查账号状态、队首、原子占名额和重复报名，
# 与入队条件形成双保险；失败事件重试 5 次后丢弃，避免卡死。
# 第二轮审查 Q49：账号不可用/已有报名导致某人无法递补时，事件保持 NEW，
# 下一次继续尝试下一位，避免“队首失败就丢掉名额”的问题。

from __future__ import annotations

import json
import sqlite3
from typing import Mapping, Any

from ticketing.common.audit import AuditService
from ticketing.infrastructure.clock import Clock, format_dt
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import AppError
from ticketing.domain.models import (
    Activity,
    PaymentStatus,
    RegistrationStatus,
    Session,
    TicketType,
)
from ticketing.infrastructure.security import new_request_id
from ticketing.domain.tickets import TicketService
from ticketing.domain.waitlist import WaitlistService


class PromotionService:
    """消费 Outbox，把候补队首递补为已购票。"""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        audit: AuditService,
        tickets: TicketService,
        waitlist: WaitlistService,
    ) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit
        self.tickets = tickets
        self.waitlist = waitlist

    def dispatch_pending(self, limit: int = 50) -> int:
        """处理待消费事件，返回成功处理的事件数。"""
        rows = self.db.query_all(
            """
            SELECT * FROM outbox_message
             WHERE status = 'NEW'
             ORDER BY id
             LIMIT ?
            """,
            (limit,),
        )
        processed = 0
        for row in rows:
            if self._process_event(row):
                processed += 1
        return processed

    def _process_event(self, event: Mapping[str, Any]) -> bool:
        """处理一条 CapacityReleased 事件。"""
        payload = json.loads(event["payload"])
        ticket_type_id = int(payload["ticket_type_id"])
        try:
            with self.db.transaction() as conn:
                record = self.waitlist.head(ticket_type_id)
                if record is None:
                    self._mark_processed(conn, int(event["id"]))
                    return True
                account = conn.execute(
                    "SELECT * FROM account WHERE id = ?", (record.account_id,)
                ).fetchone()
                if account is None or account["status"] == "BANNED":
                    self.waitlist.mark_failed_conn(
                        conn, record, "账号不可用", None
                    )
                    # 第二轮审查 Q49：失败者转 FAILED 后不消费事件，留到下一次
                    # 继续尝试队首的下一位，符合 REQ-020“直到无人补上为止”。
                    return False
                if not self.tickets.try_occupy(conn, ticket_type_id):
                    # 名额已被其他请求占用，等下一次释放事件
                    self._mark_processed(conn, int(event["id"]))
                    return True
                created = self._create_registration(conn, record, account)
                if not created:
                    self.tickets.release(conn, ticket_type_id)
                    self.waitlist.mark_failed_conn(
                        conn, record, "该账号已有报名记录", None
                    )
                    # 同上：让事件保持 NEW，下一次尝试下一位候补者。
                    return False
                self._mark_processed(conn, int(event["id"]))
                return True
        except (sqlite3.Error, AppError):
            # 第二轮审查 Q49：业务冲突（如并发导致候补状态变化）也按可重试处理，
            # 不把异常抛到调度循环。
            self._retry_or_drop(int(event["id"]))
            return False

    def _create_registration(self, conn, record, account) -> bool:
        """为候补记录生成一条“已购票/已支付”报名记录。"""
        # waitlist_id 是队列 id，不是票种 id；由队列反查票种
        ticket = self._ticket_for_waitlist(record.waitlist_id)
        session = self._get_session(ticket.session_id)
        activity = self._get_activity(session.activity_id)
        try:
            cursor = conn.execute(
                """
                INSERT INTO registration (
                    account_id, activity_id, session_id, ticket_type_id,
                    buyer_name, buyer_phone, ticket_kind, status,
                    payment_status, payment_amount_cents,
                    refund_amount_cents, refund_time, request_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    record.account_id,
                    activity.id,
                    session.id,
                    ticket.id,
                    account["name"],
                    account["phone"],
                    ticket.kind.value,
                    RegistrationStatus.PURCHASED.value,
                    PaymentStatus.PAID.value,
                    record.payment_amount_cents,
                    new_request_id("PROMO"),
                    format_dt(self.clock.now()),
                ),
            )
            registration_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return False
        self.waitlist.mark_promoted_conn(conn, record, None)
        self.audit.record(
            conn,
            None,
            "REGISTRATION",
            registration_id,
            "REGISTRATION_CREATED",
            f"候补递补自动生成报名：《{activity.name}》{session.session_no}",
            None,
            RegistrationStatus.PURCHASED.value,
        )
        return True

    def _ticket_for_waitlist(self, waitlist_id: int) -> TicketType:
        row = self.db.query_one(
            "SELECT * FROM waitlist WHERE id = ?", (waitlist_id,)
        )
        if row is None:
            raise sqlite3.IntegrityError("候补队列不存在")
        return self.tickets.get_ticket_type(int(row["ticket_type_id"]))

    def _get_session(self, session_id: int) -> Session:
        row = self.db.query_one(
            "SELECT * FROM activity_session WHERE id = ?", (session_id,)
        )
        if row is None:
            raise sqlite3.IntegrityError("场次不存在")
        return Session.from_row(row)

    def _get_activity(self, activity_id: int) -> Activity:
        row = self.db.query_one("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise sqlite3.IntegrityError("活动不存在")
        return Activity.from_row(row)

    def _mark_processed(self, conn: sqlite3.Connection, event_id: int) -> None:
        conn.execute(
            """
            UPDATE outbox_message
               SET status = 'PROCESSED', processed_at = ?
             WHERE id = ?
            """,
            (format_dt(self.clock.now()), event_id),
        )

    def _retry_or_drop(self, event_id: int) -> None:
        """处理失败时增加重试次数；超过 5 次丢弃，避免事件卡死。"""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE outbox_message SET retry_count = retry_count + 1 WHERE id = ?",
                (event_id,),
            )
            row = conn.execute(
                "SELECT retry_count FROM outbox_message WHERE id = ?", (event_id,)
            ).fetchone()
            if row is not None and int(row["retry_count"]) >= 5:
                conn.execute(
                    "UPDATE outbox_message SET status = 'PROCESSED' WHERE id = ?",
                    (event_id,),
                )

# 第二轮审查：事件只存 ticket_type_id/registration_id，场次与活动由票种反查；
# 消费顺序为“取队首 → 二次校验账号 → 原子占位 → 生成报名 → 改候补状态”，
# 事务失败回滚并由 _retry_or_drop 控制重试次数。

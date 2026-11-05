"""报名与支付标记（对应设计基线 D3）。

报名流程的顺序（与活动图/时序图一致）：
1. 校验角色、账号状态、购票人信息；
2. 幂等：同一 request_id 直接返回首次结果；同一账号同一场次只允许一条记录；
3. 校验活动公开、售票时间、场次未结束；
4. 原子扣减名额（D2）；
5. 创建报名记录（已购票/已支付/金额快照）并写审计；
6. 事务提交后才返回成功。
"""

# 第二轮审查（2026-11-05）：复核报名顺序、双重幂等、售票窗口、原子占位、
# 事务回滚与失败审计，结论通过；补 IntegrityError 兜底分支的 request_id
# 归属检查（Q43）。已知边界：活动状态在事务外校验，多进程同时取消与报名
# 之间存在时间窗口（Q44）；当前单进程菜单模型不触发。

from __future__ import annotations

import sqlite3

from ticketing.common.audit import AuditService
from ticketing.infrastructure.clock import Clock, format_dt, parse_dt
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import (
    AppError,
    CapacityFull,
    Conflict,
    DeadlinePassed,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from ticketing.domain.models import (
    Account,
    Activity,
    ActivityStatus,
    PaymentStatus,
    Registration,
    RegistrationStatus,
    Role,
    Session,
    SessionStatus,
    TicketKind,
)
from ticketing.common.permissions import PermissionService
from ticketing.infrastructure.security import normalize_phone
from ticketing.domain.tickets import TicketService


class RegistrationService:
    """报名购票、查询与取消入口。"""

    def __init__(
        self, db: Database, clock: Clock, audit: AuditService, tickets: TicketService
    ) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit
        self.tickets = tickets

    def register(
        self,
        participant,
        session_id: int,
        kind: TicketKind,
        request_id: str,
        buyer_name: str,
        buyer_phone: str,
    ) -> Registration:
        """报名即购票；失败也写一条审计（REQ-039）。"""
        try:
            return self._register_impl(
                participant, session_id, kind, request_id, buyer_name, buyer_phone
            )
        except AppError as exc:
            self.audit.record_standalone(
                participant.id,
                "SESSION",
                session_id,
                "REGISTRATION_FAILED",
                f"报名失败：{exc.message}",
            )
            raise

    def _register_impl(
        self,
        participant,
        session_id: int,
        kind: TicketKind,
        request_id: str,
        buyer_name: str,
        buyer_phone: str,
    ) -> Registration:
        # 每次交易都从数据库重新读取账号状态，避免使用登录时的过期对象
        participant = self._fresh_account(participant.id)
        PermissionService.require_role(participant, Role.PARTICIPANT)
        PermissionService.require_active(participant)
        self._validate_buyer(participant, buyer_name, buyer_phone)
        request_id = request_id.strip()
        if not request_id:
            raise ValidationError("请求编号不能为空")

        existing = self._find_by_request_id(request_id)
        if existing is not None:
            if existing.account_id != participant.id:
                raise Conflict("请求编号已被其他账号使用")
            return existing

        session = self.get_session(session_id)
        activity = self.get_activity(session.activity_id)
        self._check_sale_window(activity, session)
        same_session = self._find_by_account_session(participant.id, session_id)
        if same_session is not None:
            raise Conflict("同一账号在同一场次只能报名一次")
        if self._has_active_waitlist(participant.id, session_id):
            raise Conflict("该账号在此场次已有候补记录，不能重复报名")

        ticket = self.tickets.find_for_session_kind(session_id, kind)
        if ticket is None:
            raise NotFound("该场次没有此票种")
        if ticket.remaining <= 0:
            raise CapacityFull("该票种已售罄，可尝试候补", ticket.id)

        try:
            with self.db.transaction() as conn:
                if not self.tickets.try_occupy(conn, ticket.id):
                    # 审查通过：这里只抛 CapacityFull，不自动候补；CLI 捕获后询问用户，
                    # 用户确认才调用 WaitlistService.enqueue。
                    raise CapacityFull("该票种已售罄，可尝试候补", ticket.id)
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
                        participant.id,
                        activity.id,
                        session_id,
                        ticket.id,
                        buyer_name.strip(),
                        normalize_phone(buyer_phone),
                        kind.value,
                        RegistrationStatus.PURCHASED.value,
                        PaymentStatus.PAID.value,
                        ticket.price_cents,
                        request_id,
                        format_dt(self.clock.now()),
                    ),
                )
                registration_id = int(cursor.lastrowid)
                self.audit.record(
                    conn,
                    participant.id,
                    "REGISTRATION",
                    registration_id,
                    "REGISTRATION_CREATED",
                    f"报名成功：《{activity.name}》{session.session_no} {kind.value}",
                    None,
                    RegistrationStatus.PURCHASED.value,
                )
                if self.tickets.session_is_full(session_id):
                    conn.execute(
                        """
                        UPDATE activity_session SET status = ?
                         WHERE id = ? AND status = 'OPEN'
                        """,
                        (SessionStatus.FULL.value, session_id),
                    )
        except sqlite3.IntegrityError as exc:
            # 并发下唯一约束兜底：如果已有记录，按幂等处理。
            # 第二轮审查：必须先确认 request_id 属于当前账号，避免并发同号时
            # 把其他账号的报名记录当作幂等结果返回（数据泄露）。
            existing = self._find_by_request_id(request_id)
            if existing is not None and existing.account_id != participant.id:
                raise Conflict("请求编号已被其他账号使用") from exc
            if existing is None:
                existing = self._find_by_account_session(participant.id, session_id)
            if existing is not None:
                return existing
            raise Conflict("报名冲突，请重试") from exc
        return self.get_registration(registration_id)

    def get_registration(self, registration_id: int) -> Registration:
        """按 id 取报名记录。"""
        row = self.db.query_one(
            "SELECT * FROM registration WHERE id = ?", (registration_id,)
        )
        if row is None:
            raise NotFound("报名记录不存在")
        return Registration.from_row(row)

    def get_session(self, session_id: int) -> Session:
        """取场次。"""
        row = self.db.query_one(
            "SELECT * FROM activity_session WHERE id = ?", (session_id,)
        )
        if row is None:
            raise NotFound("场次不存在")
        return Session.from_row(row)

    def get_activity(self, activity_id: int) -> Activity:
        """取活动。"""
        row = self.db.query_one("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise NotFound("活动不存在")
        return Activity.from_row(row)

    def list_for_account(self, account_id: int) -> list[Registration]:
        """某账号的全部报名记录，时间倒序。"""
        rows = self.db.query_all(
            "SELECT * FROM registration WHERE account_id = ? ORDER BY created_at DESC, id DESC",
            (account_id,),
        )
        return [Registration.from_row(row) for row in rows]

    def _fresh_account(self, account_id: int) -> Account:
        """重新读取账号，确保封禁等状态变更立即生效。"""
        row = self.db.query_one("SELECT * FROM account WHERE id = ?", (account_id,))
        if row is None:
            raise NotFound("账号不存在")
        return Account.from_row(row)

    def _check_sale_window(self, activity: Activity, session: Session) -> None:
        """活动必须公开/进行中，且当前处于售票窗口内。"""
        if activity.status not in (ActivityStatus.PUBLISHED, ActivityStatus.ONGOING):
            raise PermissionDenied("活动尚未公开或已结束，不能报名")
        now = self.clock.now()
        if now < parse_dt(activity.sale_start):
            raise DeadlinePassed("售票尚未开始")
        if now > parse_dt(activity.sale_end):
            raise DeadlinePassed("售票已截止")
        if now >= parse_dt(session.end_time):
            raise DeadlinePassed("场次已结束")
        if session.status in (SessionStatus.CANCELLED, SessionStatus.ENDED):
            raise DeadlinePassed("场次不可报名")

    def _find_by_request_id(self, request_id: str) -> Registration | None:
        row = self.db.query_one(
            "SELECT * FROM registration WHERE request_id = ?", (request_id,)
        )
        return Registration.from_row(row) if row else None

    def _find_by_account_session(
        self, account_id: int, session_id: int
    ) -> Registration | None:
        row = self.db.query_one(
            """
            SELECT * FROM registration
             WHERE account_id = ? AND session_id = ?
            """,
            (account_id, session_id),
        )
        return Registration.from_row(row) if row else None

    def _has_active_waitlist(self, account_id: int, session_id: int) -> bool:
        row = self.db.query_one(
            """
            SELECT 1 FROM waitlist_record
             WHERE account_id = ? AND session_id = ? AND status = 'WAITING'
            """,
            (account_id, session_id),
        )
        return row is not None

    @staticmethod
    def _validate_buyer(participant, buyer_name: str, buyer_phone: str) -> None:
        """不支持代报名：购票人手机号必须与账号一致。"""
        if not buyer_name.strip():
            raise ValidationError("购票人姓名不能为空")
        if normalize_phone(buyer_phone) != participant.phone:
            raise ValidationError("购票人手机号必须与当前账号一致（不支持代报名）")

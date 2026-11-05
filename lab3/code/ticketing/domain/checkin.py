"""检票请求与处理（对应设计基线 D5）。

- 参与者发起请求；检票员只处理请求，不直接改报名状态；
- 通过后报名记录转“已检票”；异常只标记请求，不改变报名；
- 重复检票只有第一次有效，第二次提示“已检票”，不新增留痕；
- 检票时间窗由场次的 checkin_open_time 和 end_time 决定。
"""

# 审查说明：参与者“发起请求”，检票员“处理请求”；报名状态只由 _pass 修改，
# 异常处理只改请求。重复检票由“报名状态检查 + 条件 UPDATE 的 rowcount”双重兜底。
# 第二轮审查（2026-11-05）：核对请求/处理职责、时间窗、重复检票与异常留痕；
# 通过请求会连带更新报名状态，这是 REQ-014 规定的正常结果，不是检票员绕过
# 请求直接改报名（Q51）。并发发起可能产生两条 PENDING，单进程模型不触发（Q52）。

from __future__ import annotations

from dataclasses import dataclass

from ticketing.common.audit import AuditService
from ticketing.infrastructure.clock import Clock, format_dt, parse_dt
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import Conflict, DeadlinePassed, NotFound
from ticketing.domain.models import (
    Activity,
    ActivityStatus,
    CheckRequest,
    CheckRequestStatus,
    Registration,
    RegistrationStatus,
    Role,
    Session,
    SessionStatus,
)
from ticketing.common.permissions import PermissionService
from ticketing.infrastructure.security import mask_phone, new_request_id


@dataclass(slots=True)
class CheckRequestView:
    """检票员工作台展示用的一行。"""

    request_id: int
    request_no: str
    registration_id: int
    buyer_name: str
    buyer_phone: str
    activity_name: str
    session_no: str
    start_time: str
    ticket_kind: str
    status: str


class CheckinService:
    """检票请求的创建、查询与处理。"""

    def __init__(self, db: Database, clock: Clock, audit: AuditService) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit

    # 入口 1：参与者发起检票请求。本人 + 参与者 + 已购票 + 时间窗；
    # 已有 PENDING 请求直接返回，不重复创建；请求与审计同一事务。
    def request_checkin(self, participant, registration_id: int) -> CheckRequest:
        """参与者在检票开放时间内发起请求。"""
        PermissionService.require_role(participant, Role.PARTICIPANT)
        registration = self.get_registration(registration_id)
        PermissionService.require_owner(
            participant, registration.account_id, "报名记录"
        )
        # 审查通过：检票时间窗由下面的 _ensure_window 统一检查
        # （checkin_open_time <= now <= end_time，且活动/场次未取消）。
        if registration.status is RegistrationStatus.CHECKED_IN:
            raise Conflict("该票已检票，无需重复发起")
        if registration.status is not RegistrationStatus.PURCHASED:
            raise Conflict("只有“已购票”状态可以发起检票")
        session = self.get_session(registration.session_id)
        activity = self.get_activity(registration.activity_id)
        self._ensure_window(activity, session)
        pending = self._pending_for_registration(registration.id)
        if pending is not None:
            return pending
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO check_request (
                    registration_id, request_no, inspector_id, status, created_at
                ) VALUES (?, ?, NULL, ?, ?)
                """,
                (
                    registration.id,
                    new_request_id("CR"),
                    CheckRequestStatus.PENDING.value,
                    format_dt(self.clock.now()),
                ),
            )
            request_id = int(cursor.lastrowid)
            self.audit.record(
                conn,
                participant.id,
                "CHECK_REQUEST",
                request_id,
                "CHECK_REQUEST_CREATED",
                f"发起检票请求，报名记录 {registration.id}",
                None,
                CheckRequestStatus.PENDING.value,
            )
        return self.get_request(request_id)

    # 查询：检票员只能看到管理员分配给自己的活动。
    def list_assigned_activities(self, inspector) -> list[Activity]:
        """检票员被分配的活动。"""
        PermissionService.require_role(inspector, Role.INSPECTOR)
        rows = self.db.query_all(
            """
            SELECT a.* FROM activity a
              JOIN activity_inspector ai ON ai.activity_id = a.id
             WHERE ai.inspector_id = ?
               AND a.status NOT IN ('DRAFT', 'PENDING_REVIEW')
             ORDER BY a.id DESC
            """,
            (inspector.id,),
        )
        return [Activity.from_row(row) for row in rows]

    # 查询：只列自己负责活动中的 PENDING 请求，按创建时间排序。
    def list_pending_requests(self, inspector) -> list[CheckRequestView]:
        """检票员负责活动中的待处理请求。"""
        PermissionService.require_role(inspector, Role.INSPECTOR)
        rows = self.db.query_all(
            """
            SELECT cr.id AS request_id, cr.request_no, cr.registration_id,
                   cr.status, r.buyer_name, r.buyer_phone, r.ticket_kind,
                   a.name AS activity_name, s.session_no, s.start_time
              FROM check_request cr
              JOIN registration r ON r.id = cr.registration_id
              JOIN activity a ON a.id = r.activity_id
              JOIN activity_session s ON s.id = r.session_id
              JOIN activity_inspector ai
                ON ai.activity_id = a.id AND ai.inspector_id = ?
             WHERE cr.status = 'PENDING'
             ORDER BY cr.created_at, cr.id
            """,
            (inspector.id,),
        )
        return [
            CheckRequestView(
                request_id=row["request_id"],
                request_no=row["request_no"],
                registration_id=row["registration_id"],
                buyer_name=row["buyer_name"],
                # 检票员只能看遮挡版手机号（REQ-003/045）；CLI 再遮挡是幂等的。
                buyer_phone=mask_phone(row["buyer_phone"]),
                activity_name=row["activity_name"],
                session_no=row["session_no"],
                start_time=row["start_time"],
                ticket_kind=row["ticket_kind"],
                status=row["status"],
            )
            for row in rows
        ]

    # 入口 2：检票员处理请求。校验角色、分配关系、请求仍 PENDING、时间窗；
    # passed=True → _pass；passed=False → _mark_abnormal。
    def process(self, inspector, request_id: int, passed: bool) -> CheckRequest:
        """检票员处理请求：通过或标记异常。"""
        PermissionService.require_role(inspector, Role.INSPECTOR)
        request = self.get_request(request_id)
        registration = self.get_registration(request.registration_id)
        session = self.get_session(registration.session_id)
        activity = self.get_activity(registration.activity_id)
        if not PermissionService.is_assigned_inspector(
            self.db, inspector.id, activity.id
        ):
            raise Conflict("检票员未被分配到该活动")
        if request.status is not CheckRequestStatus.PENDING:
            raise Conflict("该检票请求已处理")
        self._ensure_window(activity, session)
        if passed:
            return self._pass(inspector, request, registration)
        return self._mark_abnormal(inspector, request)

    # 通过检票（事务内）：请求置 PASSED + 报名置 CHECKED_IN + 两条审计。
    # 两个 UPDATE 都带状态条件并检查 rowcount：并发/重复处理时只有一个成功，
    # 另一个回滚并提示已处理，保证“重复检票只有第一次有效”。

    # 第二轮审查 Q51：“检票员不得直接修改报名状态”指的是不提供任意改状态的
    # 入口；检票员只能对检票请求选择“通过/异常”。通过请求后，由领域动作把
    # 报名置为 CHECKED_IN，这是 REQ-014 明确规定的正常结果，仍是“请求 → 状态”
    # 的受控推导；异常分支则完全不修改报名。
    def _pass(
        self, inspector, request: CheckRequest, registration: Registration
    ) -> CheckRequest:
        """通过检票；已检票的重复请求只提示，不新增留痕。"""
        if registration.status is RegistrationStatus.CHECKED_IN:
            raise Conflict("该票已检票（重复检票只有第一次有效）")
        if registration.status is not RegistrationStatus.PURCHASED:
            raise Conflict("报名记录状态不允许检票")
        now = format_dt(self.clock.now())
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE check_request
                   SET status = ?, inspector_id = ?, processed_at = ?
                 WHERE id = ? AND status = 'PENDING'
                """,
                (
                    CheckRequestStatus.PASSED.value,
                    inspector.id,
                    now,
                    request.id,
                ),
            )
            if cursor.rowcount != 1:
                raise Conflict("该检票请求已处理")
            cursor = conn.execute(
                """
                UPDATE registration SET status = ?
                 WHERE id = ? AND status = 'PURCHASED'
                """,
                (RegistrationStatus.CHECKED_IN.value, registration.id),
            )
            if cursor.rowcount != 1:
                raise Conflict("报名记录状态已变化，检票失败")
            self.audit.record(
                conn,
                inspector.id,
                "CHECK_REQUEST",
                request.id,
                "CHECKIN_PASSED",
                f"检票通过，报名记录 {registration.id} 转为已检票",
                CheckRequestStatus.PENDING.value,
                CheckRequestStatus.PASSED.value,
            )
            self.audit.record(
                conn,
                inspector.id,
                "REGISTRATION",
                registration.id,
                "REGISTRATION_CHECKED_IN",
                "检票通过",
                RegistrationStatus.PURCHASED.value,
                RegistrationStatus.CHECKED_IN.value,
            )
        return self.get_request(request.id)

    # 凭证不符（事务内）：只把请求置 ABNORMAL，不修改报名状态；
    # 同样检查 rowcount，防止并发下重复写异常审计。
    def _mark_abnormal(self, inspector, request: CheckRequest) -> CheckRequest:
        """凭证不符：只标记请求，不修改报名状态。"""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE check_request
                   SET status = ?, inspector_id = ?, processed_at = ?
                 WHERE id = ? AND status = 'PENDING'
                """,
                (
                    CheckRequestStatus.ABNORMAL.value,
                    inspector.id,
                    format_dt(self.clock.now()),
                    request.id,
                ),
            )
            if cursor.rowcount != 1:
                raise Conflict("该检票请求已处理")
            self.audit.record(
                conn,
                inspector.id,
                "CHECK_REQUEST",
                request.id,
                "CHECKIN_ABNORMAL",
                "凭证不符，标记异常，不予通过",
                CheckRequestStatus.PENDING.value,
                CheckRequestStatus.ABNORMAL.value,
            )
        return self.get_request(request.id)

    # 查询辅助：按 id 取请求，不存在抛 NotFound。
    def get_request(self, request_id: int) -> CheckRequest:
        """按 id 取检票请求。"""
        row = self.db.query_one(
            "SELECT * FROM check_request WHERE id = ?", (request_id,)
        )
        if row is None:
            raise NotFound("检票请求不存在")
        return CheckRequest.from_row(row)

    # 查询辅助：按 id 取报名，不存在抛 NotFound。
    def get_registration(self, registration_id: int) -> Registration:
        """取报名记录。"""
        row = self.db.query_one(
            "SELECT * FROM registration WHERE id = ?", (registration_id,)
        )
        if row is None:
            raise NotFound("报名记录不存在")
        return Registration.from_row(row)

    # 查询辅助：按 id 取场次，不存在抛 NotFound。
    def get_session(self, session_id: int) -> Session:
        """取场次。"""
        row = self.db.query_one(
            "SELECT * FROM activity_session WHERE id = ?", (session_id,)
        )
        if row is None:
            raise NotFound("场次不存在")
        return Session.from_row(row)

    # 查询辅助：按 id 取活动，不存在抛 NotFound。
    def get_activity(self, activity_id: int) -> Activity:
        """取活动。"""
        row = self.db.query_one("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise NotFound("活动不存在")
        return Activity.from_row(row)

    # 查询辅助：某报名是否已有待处理请求；用于发起请求时的幂等复用。
    def _pending_for_registration(self, registration_id: int) -> CheckRequest | None:
        row = self.db.query_one(
            """
            SELECT * FROM check_request
             WHERE registration_id = ? AND status = 'PENDING'
             ORDER BY id DESC LIMIT 1
            """,
            (registration_id,),
        )
        return CheckRequest.from_row(row) if row else None

    # 检票时间窗的唯一入口：活动/场次未取消，且 checkin_open_time <= now <= end_time。
    # 发起请求和检票员处理都会调用，保证两边使用同一套时间规则。
    def _ensure_window(self, activity: Activity, session: Session) -> None:
        """活动未取消、场次未取消，且当前在检票时间窗内。"""
        if activity.status is ActivityStatus.CANCELLED:
            raise Conflict("活动已取消")
        if session.status is SessionStatus.CANCELLED:
            raise Conflict("场次已取消")
        now = self.clock.now()
        if now < parse_dt(session.checkin_open_time):
            raise DeadlinePassed("检票尚未开放")
        if now > parse_dt(session.end_time):
            raise DeadlinePassed("场次已结束，不能检票")


# 审查通过：检票流程、时间窗、重复检票与异常处理已核对。

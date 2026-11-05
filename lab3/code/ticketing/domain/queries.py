"""只读查询与统计（对应设计基线 Q1）。

Q1 只读，不产生业务副作用；数据范围与字段脱敏在这里统一处理：
- 参与者只能查公开活动、自己的报名/候补/审计；
- 组织者只能查自己的活动、名单与统计；
- 检票员只能查被分配活动的请求；
- 管理员可查全平台数据和全部审计。
"""

# 审查通过：数据范围按角色在 browse_activities / _check_activity_visible /
# _audit_scope 等处分别实现；被封禁账号仍可查看已有票和候补，新增交易由服务层阻止。
# 组合查询（关键词/时间/状态/票种）和 ORDER BY 排序已实现。
# 实验二 UI-04 的“我的票”筛选分类（待检票/已检票/已结束/已取消）在当前终端界面未实现，
# 留到 CLI 初审时补（属表现层筛选，不改变系统状态）。

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ticketing.infrastructure.clock import Clock, parse_dt
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import NotFound, PermissionDenied
from ticketing.domain.models import (
    Activity,
    ActivityStatus,
    AuditLog,
    Registration,
    RegistrationStatus,
    Role,
    Session,
    TicketKind,
    TicketType,
    WaitlistRecord,
)
from ticketing.common.permissions import PermissionService
from ticketing.infrastructure.security import mask_phone


@dataclass(slots=True)
class ActivityView:
    """活动浏览列表的一行。"""

    activity: Activity
    first_session: str
    last_session: str
    min_price_cents: int
    max_price_cents: int
    remaining: int
    capacity: int
    session_count: int


@dataclass(slots=True)
class ActivityDetail:
    """活动详情：活动 + 场次 + 每个场次的票种。"""

    activity: Activity
    sessions: list[Session]
    tickets: dict[int, list[TicketType]]


@dataclass(slots=True)
class RegistrationView:
    """我的票 / 管理员查询用的一行。"""

    registration: Registration
    activity_name: str
    session_no: str
    location: str
    start_time: str
    end_time: str
    price_cents: int
    can_refund: bool
    refund_deadline: str


@dataclass(slots=True)
class WaitlistView:
    """我的候补列表的一行。"""

    record: WaitlistRecord
    activity_name: str
    session_no: str
    ticket_kind: str
    price_cents: int


@dataclass(slots=True)
class RosterEntry:
    """报名名单的一行；手机号已按组织者视角遮挡。"""

    registration_id: int
    buyer_name: str
    phone_masked: str
    session_no: str
    ticket_kind: str
    status: str


@dataclass(slots=True)
class StatsRow:
    """一组统计口径（按活动或按场次）。"""

    label: str
    registered: int
    attended: int
    refunded: int
    attendance_rate: float
    refund_rate: float


@dataclass(slots=True)
class Statistics:
    """活动统计结果。"""

    open: bool
    message: str
    overall: StatsRow | None
    per_session: list[StatsRow]


class QueryService:
    """活动查询、名单、统计、审计查询。"""

    def __init__(self, db: Database, clock: Clock) -> None:
        self.db = db
        self.clock = clock

    # ---------- 活动查询 ----------

    # 活动浏览：参与者看公开/进行中/已结束/已取消；管理员可看全部；
    # 支持关键词/时间/状态/票种组合，按最早场次倒序。
    def browse_activities(
        self,
        viewer,
        *,
        keyword: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
        kind: TicketKind | None = None,
    ) -> list[ActivityView]:
        """参与者查公开活动；管理员可查全部。组织者不提供公开查询。"""
        if viewer.role is Role.ORGANIZER:
            raise PermissionDenied("组织者不提供公开活动查询，只能查看自己的活动")
        if viewer.role not in (Role.PARTICIPANT, Role.ADMIN):
            raise PermissionDenied("当前角色不能查询活动")
        conditions: list[str] = []
        params: list[object] = []
        if viewer.role is Role.PARTICIPANT:
            conditions.append(
                "a.status IN ('PUBLISHED', 'ONGOING', 'ENDED', 'CANCELLED')"
            )
        if keyword.strip():
            like = f"%{keyword.strip()}%"
            conditions.append(
                "(a.name LIKE ? OR a.description LIKE ? OR a.location LIKE ?)"
            )
            params.extend([like, like, like])
        if status:
            conditions.append("a.status = ?")
            params.append(status)
        if date_from:
            conditions.append(
                """
                EXISTS (SELECT 1 FROM activity_session s
                         WHERE s.activity_id = a.id AND s.start_time >= ?)
                """
            )
            params.append(date_from)
        if date_to:
            conditions.append(
                """
                EXISTS (SELECT 1 FROM activity_session s
                         WHERE s.activity_id = a.id AND s.start_time <= ?)
                """
            )
            params.append(date_to)
        if kind is not None:
            conditions.append(
                """
                EXISTS (SELECT 1 FROM activity_session s
                          JOIN ticket_type t ON t.session_id = s.id
                         WHERE s.activity_id = a.id AND t.kind = ?)
                """
            )
            params.append(kind.value)
        where = " AND ".join(conditions) if conditions else "1 = 1"
        rows = self.db.query_all(
            f"""
            SELECT a.* FROM activity a
             WHERE {where}
             ORDER BY (
                 SELECT MIN(s.start_time) FROM activity_session s
                  WHERE s.activity_id = a.id
             ) DESC, a.id DESC
            """,
            params,
        )
        result: list[ActivityView] = []
        for row in rows:
            view = self._activity_view(Activity.from_row(row))
            if view is not None:
                result.append(view)
        return result

    def activity_detail(self, viewer, activity_id: int) -> ActivityDetail:
        """按角色校验后返回活动详情。"""
        activity = self.get_activity(activity_id)
        self._check_activity_visible(viewer, activity)
        sessions = self.get_sessions(activity_id)
        tickets = {
            session.id: self.get_tickets(session.id) for session in sessions
        }
        return ActivityDetail(activity=activity, sessions=sessions, tickets=tickets)

    def get_activity(self, activity_id: int) -> Activity:
        """取活动。"""
        row = self.db.query_one("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise NotFound("活动不存在")
        return Activity.from_row(row)

    def get_sessions(self, activity_id: int) -> list[Session]:
        """取场次。"""
        rows = self.db.query_all(
            "SELECT * FROM activity_session WHERE activity_id = ? ORDER BY start_time, id",
            (activity_id,),
        )
        return [Session.from_row(row) for row in rows]

    def get_tickets(self, session_id: int) -> list[TicketType]:
        """取票种。"""
        rows = self.db.query_all(
            "SELECT * FROM ticket_type WHERE session_id = ? ORDER BY kind DESC",
            (session_id,),
        )
        return [TicketType.from_row(row) for row in rows]

    def _activity_view(self, activity: Activity) -> ActivityView | None:
        """汇总活动的时间、价格、余票。"""
        sessions = self.get_sessions(activity.id)
        if not sessions:
            return None
        tickets = [item for s in sessions for item in self.get_tickets(s.id)]
        if not tickets:
            return None
        return ActivityView(
            activity=activity,
            first_session=sessions[0].start_time,
            last_session=sessions[-1].end_time,
            min_price_cents=min(item.price_cents for item in tickets),
            max_price_cents=max(item.price_cents for item in tickets),
            remaining=sum(item.remaining for item in tickets),
            capacity=sum(item.capacity for item in tickets),
            session_count=len(sessions),
        )

    # 活动详情数据范围：管理员全部；参与者非草稿/待审；组织者仅自己；检票员仅分配活动。
    def _check_activity_visible(self, viewer, activity: Activity) -> None:
        """活动详情的数据范围。"""
        if viewer.role is Role.ADMIN:
            return
        if viewer.role is Role.PARTICIPANT:
            if activity.status in (
                ActivityStatus.DRAFT,
                ActivityStatus.PENDING_REVIEW,
            ):
                raise PermissionDenied("未公开活动仅组织者与管理员可见")
            return
        if viewer.role is Role.ORGANIZER:
            PermissionService.require_activity_owner(viewer, activity.organizer_id)
            return
        if viewer.role is Role.INSPECTOR:
            if not PermissionService.is_assigned_inspector(
                self.db, viewer.id, activity.id
            ):
                raise PermissionDenied("检票员只能查看被分配的活动")
            return
        raise PermissionDenied("当前角色不能查看该活动")

    # ---------- 我的票与候补 ----------

    # 我的票：只返回当前参与者自己的报名，按创建时间倒序；
    # can_refund 由“已购票 + 未过退票截止”共同决定。
    def my_registrations(self, participant) -> list[RegistrationView]:
        """参与者自己的报名记录。"""
        PermissionService.require_role(participant, Role.PARTICIPANT)
        rows = self.db.query_all(
            """
            SELECT r.*, a.name AS activity_name, a.location, a.refund_deadline,
                   s.session_no, s.start_time, s.end_time
              FROM registration r
              JOIN activity a ON a.id = r.activity_id
              JOIN activity_session s ON s.id = r.session_id
             WHERE r.account_id = ?
             ORDER BY r.created_at DESC, r.id DESC
            """,
            (participant.id,),
        )
        now = self.clock.now()
        result: list[RegistrationView] = []
        for row in rows:
            registration = Registration.from_row(row)
            can_refund = (
                registration.status is RegistrationStatus.PURCHASED
                and now <= parse_dt(row["refund_deadline"])
            )
            result.append(
                RegistrationView(
                    registration=registration,
                    activity_name=row["activity_name"],
                    session_no=row["session_no"],
                    location=row["location"],
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    price_cents=registration.payment_amount_cents,
                    can_refund=can_refund,
                    refund_deadline=row["refund_deadline"],
                )
            )
        return result

    # 我的候补：只返回当前参与者自己的候补记录。
    def my_waitlists(self, participant) -> list[WaitlistView]:
        """参与者自己的候补记录。"""
        PermissionService.require_role(participant, Role.PARTICIPANT)
        rows = self.db.query_all(
            """
            SELECT w.*, a.name AS activity_name, s.session_no,
                   t.kind AS ticket_kind, t.price_cents
              FROM waitlist_record w
              JOIN activity a ON a.id = w.activity_id
              JOIN activity_session s ON s.id = w.session_id
              JOIN ticket_type t ON t.id = (
                  SELECT t2.id FROM waitlist q
                    JOIN ticket_type t2 ON t2.id = q.ticket_type_id
                   WHERE q.id = w.waitlist_id
              )
             WHERE w.account_id = ?
             ORDER BY w.join_time DESC, w.id DESC
            """,
            (participant.id,),
        )
        return [
            WaitlistView(
                record=WaitlistRecord.from_row(row),
                activity_name=row["activity_name"],
                session_no=row["session_no"],
                ticket_kind=row["ticket_kind"],
                price_cents=row["price_cents"],
            )
            for row in rows
        ]

    # ---------- 组织者名单与统计 ----------

    # 组织者名单：仅活动所有者；手机号遮挡；只含有效/终态报名。
    def organizer_roster(self, organizer, activity_id: int) -> list[RosterEntry]:
        """组织者查看本活动有效报名名单；手机号遮挡。"""
        activity = self.get_activity(activity_id)
        PermissionService.require_activity_owner(organizer, activity.organizer_id)
        rows = self.db.query_all(
            """
            SELECT r.id, r.buyer_name, r.buyer_phone, r.ticket_kind, r.status,
                   s.session_no
              FROM registration r
              JOIN activity_session s ON s.id = r.session_id
             WHERE r.activity_id = ?
               AND r.status IN ('PURCHASED', 'CHECKED_IN', 'NORMAL_END', 'NO_SHOW')
             ORDER BY s.start_time, r.id
            """,
            (activity_id,),
        )
        return [
            RosterEntry(
                registration_id=row["id"],
                buyer_name=row["buyer_name"],
                phone_masked=mask_phone(row["buyer_phone"]),
                session_no=row["session_no"],
                ticket_kind=row["ticket_kind"],
                status=row["status"],
            )
            for row in rows
        ]

    # 导出名单：仅姓名/场次/票种，不含手机号。
    def export_roster_csv(self, organizer, activity_id: int, path: str | Path) -> int:
        """导出姓名、场次、票种三列；不含完整手机号（REQ-031）。"""
        roster = self.organizer_roster(organizer, activity_id)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["姓名", "场次", "票种"])
            for entry in roster:
                kind_label = "VIP" if entry.ticket_kind == "VIP" else "普通票"
                writer.writerow([entry.buyer_name, entry.session_no, kind_label])
        return len(roster)

    # 统计：仅活动所有者；全部场次结束后开放；按活动/场次计算出席率/退票率。
    def activity_statistics(self, organizer, activity_id: int) -> Statistics:
        """全部场次结束后才统计；已取消/候补不计入。"""
        activity = self.get_activity(activity_id)
        PermissionService.require_activity_owner(organizer, activity.organizer_id)
        sessions = self.get_sessions(activity_id)
        if not sessions:
            return Statistics(False, "活动没有场次", None, [])
        latest_end = max(parse_dt(item.end_time) for item in sessions)
        if self.clock.now() < latest_end:
            return Statistics(False, "全部场次结束后才可查看统计", None, [])
        rows = self.db.query_all(
            """
            SELECT session_id, status, COUNT(*) AS amount
              FROM registration
             WHERE activity_id = ?
             GROUP BY session_id, status
            """,
            (activity_id,),
        )
        counts: dict[int, dict[str, int]] = {s.id: {} for s in sessions}
        for row in rows:
            counts.setdefault(int(row["session_id"]), {})[row["status"]] = int(
                row["amount"]
            )
        overall_counts: dict[str, int] = {}
        for session_counts in counts.values():
            for status, amount in session_counts.items():
                overall_counts[status] = overall_counts.get(status, 0) + amount
        per_session = [
            self._stats_row(f"{session.session_no}（{session.start_time}）", counts[session.id])
            for session in sessions
        ]
        return Statistics(
            True,
            "",
            self._stats_row("整个活动", overall_counts),
            per_session,
        )

    @staticmethod
    def _stats_row(label: str, counts: dict[str, int]) -> StatsRow:
        """按统一口径计算一行统计。"""
        valid_statuses = {
            RegistrationStatus.PURCHASED.value,
            RegistrationStatus.CHECKED_IN.value,
            RegistrationStatus.NORMAL_END.value,
            RegistrationStatus.NO_SHOW.value,
        }
        attended_statuses = {
            RegistrationStatus.CHECKED_IN.value,
            RegistrationStatus.NORMAL_END.value,
        }
        refunded_statuses = {
            RegistrationStatus.SELF_CANCELLED.value,
            RegistrationStatus.ACTIVITY_CANCELLED.value,
        }
        registered = sum(counts.get(s, 0) for s in valid_statuses)
        attended = sum(counts.get(s, 0) for s in attended_statuses)
        refunded = sum(counts.get(s, 0) for s in refunded_statuses)
        attendance_rate = attended / registered * 100 if registered else 0.0
        denominator = registered + refunded
        refund_rate = refunded / denominator * 100 if denominator else 0.0
        return StatsRow(
            label=label,
            registered=registered,
            attended=attended,
            refunded=refunded,
            attendance_rate=attendance_rate,
            refund_rate=refund_rate,
        )

    # ---------- 管理员查询 ----------

    def platform_summary(self, admin) -> dict[str, object]:
        """管理员全平台概览。"""
        PermissionService.require_role(admin, Role.ADMIN)
        role_rows = self.db.query_all(
            "SELECT role, COUNT(*) AS amount FROM account GROUP BY role"
        )
        status_rows = self.db.query_all(
            "SELECT status, COUNT(*) AS amount FROM activity GROUP BY status"
        )
        registration_row = self.db.query_one(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN status IN ('PURCHASED', 'CHECKED_IN',
                                                    'NORMAL_END', 'NO_SHOW')
                                     THEN payment_amount_cents ELSE 0 END), 0) AS revenue
              FROM registration
            """
        )
        waitlist_row = self.db.query_one(
            "SELECT COUNT(*) AS total FROM waitlist_record WHERE status = 'WAITING'"
        )
        return {
            "accounts": {row["role"]: row["amount"] for row in role_rows},
            "activities": {row["status"]: row["amount"] for row in status_rows},
            "registrations": registration_row["total"],
            "revenue_cents": registration_row["revenue"],
            "waiting": waitlist_row["total"],
        }

    def admin_search_registrations(self, admin, keyword: str = "") -> list[RegistrationView]:
        """管理员按姓名/手机号/编号查报名，手机号可见完整版。"""
        PermissionService.require_role(admin, Role.ADMIN)
        like = f"%{keyword.strip()}%"
        rows = self.db.query_all(
            """
            SELECT r.*, a.name AS activity_name, a.location, a.refund_deadline,
                   s.session_no, s.start_time, s.end_time
              FROM registration r
              JOIN activity a ON a.id = r.activity_id
              JOIN activity_session s ON s.id = r.session_id
             WHERE r.buyer_name LIKE ? OR r.buyer_phone LIKE ?
                OR CAST(r.id AS TEXT) = ?
             ORDER BY r.created_at DESC, r.id DESC
             LIMIT 100
            """,
            (like, like, keyword.strip()),
        )
        return [
            RegistrationView(
                registration=Registration.from_row(row),
                activity_name=row["activity_name"],
                session_no=row["session_no"],
                location=row["location"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                price_cents=row["payment_amount_cents"],
                can_refund=False,
                refund_deadline=row["refund_deadline"],
            )
            for row in rows
        ]

    # ---------- 审计查询 ----------

    def audit_query(
        self,
        viewer,
        *,
        object_type: str | None = None,
        action: str | None = None,
        operator_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
    ) -> list[AuditLog]:
        """按角色数据范围查询留痕。"""
        conditions: list[str] = []
        params: list[object] = []
        scope = self._audit_scope(viewer)
        if scope:
            conditions.append(f"({scope[0]})")
            params.extend(scope[1:])
        if object_type:
            conditions.append("object_type = ?")
            params.append(object_type)
        if action:
            conditions.append("action = ?")
            params.append(action)
        if operator_id is not None:
            conditions.append("operator_id = ?")
            params.append(operator_id)
        if date_from:
            conditions.append("operated_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("operated_at <= ?")
            params.append(date_to)
        where = " AND ".join(conditions) if conditions else "1 = 1"
        safe_limit = max(1, min(int(limit), 1000))
        rows = self.db.query_all(
            f"""
            SELECT * FROM audit_log
             WHERE {where}
             ORDER BY operated_at DESC, id DESC
             LIMIT {safe_limit}
            """,
            params,
        )
        return [AuditLog.from_row(row) for row in rows]

    # 审计数据范围：管理员全部；组织者本活动相关；参与者本人报名/候补/检票/举报；
    # 检票员本人处理的请求。
    def _audit_scope(self, viewer) -> tuple[str, ...] | None:
        """返回 (SQL 条件, 参数...)，None 表示管理员看全部。"""
        if viewer.role is Role.ADMIN:
            return None
        if viewer.role is Role.ORGANIZER:
            return (
                """
                (object_type = 'ACTIVITY' AND object_id IN
                    (SELECT id FROM activity WHERE organizer_id = ?))
                OR (object_type = 'SESSION' AND object_id IN
                    (SELECT s.id FROM activity_session s
                       JOIN activity a ON a.id = s.activity_id
                      WHERE a.organizer_id = ?))
                OR (object_type = 'TICKET_TYPE' AND object_id IN
                    (SELECT t.id FROM ticket_type t
                       JOIN activity_session s ON s.id = t.session_id
                       JOIN activity a ON a.id = s.activity_id
                      WHERE a.organizer_id = ?))
                OR (object_type = 'REVIEW_APPLICATION' AND object_id IN
                    (SELECT r.id FROM review_application r
                       JOIN activity a ON a.id = r.activity_id
                      WHERE a.organizer_id = ?))
                OR (object_type = 'REPORT' AND object_id IN
                    (SELECT r.id FROM report r
                       JOIN activity a ON a.id = r.activity_id
                      WHERE a.organizer_id = ?))
                OR (object_type = 'ACCOUNT' AND object_id = ?)
                """,
                viewer.id,
                viewer.id,
                viewer.id,
                viewer.id,
                viewer.id,
                viewer.id,
            )
        if viewer.role is Role.PARTICIPANT:
            return (
                """
                (object_type = 'REGISTRATION' AND object_id IN
                    (SELECT id FROM registration WHERE account_id = ?))
                OR (object_type = 'WAITLIST_RECORD' AND object_id IN
                    (SELECT id FROM waitlist_record WHERE account_id = ?))
                OR (object_type = 'CHECK_REQUEST' AND object_id IN
                    (SELECT cr.id FROM check_request cr
                       JOIN registration r ON r.id = cr.registration_id
                      WHERE r.account_id = ?))
                OR (object_type = 'REPORT' AND object_id IN
                    (SELECT id FROM report WHERE reporter_id = ?))
                OR (object_type = 'ACCOUNT' AND object_id = ?)
                """,
                viewer.id,
                viewer.id,
                viewer.id,
                viewer.id,
                viewer.id,
            )
        if viewer.role is Role.INSPECTOR:
            return (
                """
                object_type = 'CHECK_REQUEST' AND object_id IN
                    (SELECT id FROM check_request WHERE inspector_id = ?)
                """,
                viewer.id,
            )
        return ("0 = 1",)

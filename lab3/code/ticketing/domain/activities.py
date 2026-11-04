"""活动、场次与审核（对应设计基线 D1）。

职责：
- 组织者创建活动（含场次、票种），提交发布审核；
- 组织者修改活动：表面信息直接生效，时间/地点/开售前容量票价走修改审核；
- 组织者申请取消，管理员审批；
- 时间推动活动状态（公开 → 进行中 → 已结束）；
- 审核申请的创建与“通过后如何落库”的领域逻辑。

管理员审核的编排放在 admin.py，避免 D1 直接依赖退票/候补服务。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from ticketing.common.audit import AuditService
from ticketing.infrastructure.clock import Clock, format_dt, parse_dt
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import Conflict, NotFound, PermissionDenied, ValidationError
from ticketing.domain.models import (
    Activity,
    ActivityStatus,
    NotificationType,
    ReviewApplication,
    ReviewStatus,
    ReviewType,
    Role,
    Session,
    SessionStatus,
    TicketKind,
)
from ticketing.common.notifications import NotificationService
from ticketing.common.permissions import PermissionService
from ticketing.domain.tickets import TicketService


@dataclass(slots=True)
class TicketDraft:
    """创建活动时的一种票。"""

    kind: TicketKind
    price_cents: int
    capacity: int


@dataclass(slots=True)
class SessionDraft:
    """创建活动时的一个场次。"""

    start_time: datetime
    end_time: datetime
    checkin_open_time: datetime
    allow_waitlist: bool = True
    session_no: str = ""
    tickets: list[TicketDraft] = field(default_factory=list)


@dataclass(slots=True)
class ActivityDraft:
    """创建活动的完整输入。"""

    name: str
    description: str
    location: str
    estimated_participants: int
    sale_start: datetime
    sale_end: datetime
    refund_deadline: datetime
    sessions: list[SessionDraft]
    cover: str = ""
    tags: str = ""


class ActivityService:
    """活动、场次、票种的写操作与状态推进。"""

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

    # ---------- 创建与查询 ----------

    def create_activity(self, organizer, draft: ActivityDraft) -> Activity:
        """组织者创建草稿活动。"""
        PermissionService.require_role(organizer, Role.ORGANIZER)
        self._validate_draft(draft)
        created_at = format_dt(self.clock.now())
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO activity (
                    organizer_id, name, description, location,
                    estimated_participants, sale_start, sale_end,
                    waitlist_deadline, refund_deadline, cover, tags,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organizer.id,
                    draft.name.strip(),
                    draft.description.strip(),
                    draft.location.strip(),
                    draft.estimated_participants,
                    format_dt(draft.sale_start),
                    format_dt(draft.sale_end),
                    format_dt(draft.sale_end),
                    format_dt(draft.refund_deadline),
                    draft.cover.strip(),
                    draft.tags.strip(),
                    ActivityStatus.DRAFT.value,
                    created_at,
                ),
            )
            activity_id = int(cursor.lastrowid)
            self._insert_sessions(conn, activity_id, draft.sessions, created_at)
            self.audit.record(
                conn,
                organizer.id,
                "ACTIVITY",
                activity_id,
                "ACTIVITY_CREATED",
                f"创建活动《{draft.name.strip()}》",
                None,
                ActivityStatus.DRAFT.value,
            )
        return self.get_activity(activity_id)

    def get_activity(self, activity_id: int) -> Activity:
        """按 id 取活动。"""
        row = self.db.query_one("SELECT * FROM activity WHERE id = ?", (activity_id,))
        if row is None:
            raise NotFound("活动不存在")
        return Activity.from_row(row)

    def get_sessions(self, activity_id: int) -> list[Session]:
        """按开始时间列出活动的场次。"""
        rows = self.db.query_all(
            "SELECT * FROM activity_session WHERE activity_id = ? ORDER BY start_time, id",
            (activity_id,),
        )
        return [Session.from_row(row) for row in rows]

    def get_session(self, session_id: int) -> Session:
        """按 id 取场次。"""
        row = self.db.query_one(
            "SELECT * FROM activity_session WHERE id = ?", (session_id,)
        )
        if row is None:
            raise NotFound("场次不存在")
        return Session.from_row(row)

    def list_by_organizer(self, organizer_id: int) -> list[Activity]:
        """组织者自己的活动（含草稿、待审核）。"""
        rows = self.db.query_all(
            "SELECT * FROM activity WHERE organizer_id = ? ORDER BY id DESC",
            (organizer_id,),
        )
        return [Activity.from_row(row) for row in rows]

    def get_review(self, review_id: int) -> ReviewApplication:
        """按 id 取审核申请。"""
        row = self.db.query_one(
            "SELECT * FROM review_application WHERE id = ?", (review_id,)
        )
        if row is None:
            raise NotFound("审核申请不存在")
        return ReviewApplication.from_row(row)

    def list_pending_reviews(self) -> list[ReviewApplication]:
        """管理员待审队列，按提交时间升序。"""
        rows = self.db.query_all(
            """
            SELECT * FROM review_application
             WHERE status = 'PENDING'
             ORDER BY submitted_at, id
            """
        )
        return [ReviewApplication.from_row(row) for row in rows]

    def list_reviews_for_activity(self, activity_id: int) -> list[ReviewApplication]:
        """某活动的全部审核申请，时间倒序。"""
        rows = self.db.query_all(
            """
            SELECT * FROM review_application
             WHERE activity_id = ?
             ORDER BY id DESC
            """,
            (activity_id,),
        )
        return [ReviewApplication.from_row(row) for row in rows]

    # ---------- 发布审核与修改审核 ----------

    def submit_for_review(self, organizer, activity_id: int) -> ReviewApplication:
        """草稿提交发布审核。"""
        activity = self.get_activity(activity_id)
        PermissionService.require_activity_owner(organizer, activity.organizer_id)
        if activity.status is not ActivityStatus.DRAFT:
            raise Conflict("只有草稿状态的活动可以提交发布审核")
        if self._has_pending_review(activity_id, ReviewType.PUBLISH):
            raise Conflict("该活动已有待处理的发布审核")
        with self.db.transaction() as conn:
            review_id = self._insert_review(
                conn, activity_id, ReviewType.PUBLISH, {}
            )
            conn.execute(
                "UPDATE activity SET status = ? WHERE id = ?",
                (ActivityStatus.PENDING_REVIEW.value, activity_id),
            )
            self.audit.record(
                conn,
                organizer.id,
                "ACTIVITY",
                activity_id,
                "PUBLISH_REVIEW_SUBMITTED",
                f"提交发布审核：{activity.name}",
                activity.status.value,
                ActivityStatus.PENDING_REVIEW.value,
            )
        return self.get_review(review_id)

    def modify_activity(
        self,
        organizer,
        activity_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        cover: str | None = None,
        tags: str | None = None,
        location: str | None = None,
        session_updates: list[dict] | None = None,
        ticket_updates: list[dict] | None = None,
    ) -> ReviewApplication | None:
        """修改活动。

        返回 None 表示只改了表面信息；返回审核申请表示有待审修改。
        """
        activity = self.get_activity(activity_id)
        PermissionService.require_activity_owner(organizer, activity.organizer_id)
        if activity.status in {ActivityStatus.CANCELLED, ActivityStatus.ENDED}:
            raise Conflict("已取消或已结束的活动不能修改")
        if activity.status is ActivityStatus.PENDING_REVIEW:
            raise Conflict("活动正在审核中，不能同时修改")

        direct_changes: dict[str, str] = {}
        for key, value in (
            ("name", name),
            ("description", description),
            ("cover", cover),
            ("tags", tags),
        ):
            if value is not None and value.strip():
                direct_changes[key] = value.strip()
        if name is not None and not name.strip():
            raise ValidationError("活动名称不能为空")

        payload: dict[str, object] = {}
        if location is not None:
            if not location.strip():
                raise ValidationError("地点不能为空")
            payload["location"] = location.strip()
        if session_updates:
            payload["sessions"] = self._build_session_updates(
                activity_id, session_updates
            )
        if ticket_updates:
            payload["tickets"] = self._build_ticket_updates(
                activity, ticket_updates
            )
        if payload and self._has_pending_review(activity_id, ReviewType.MODIFY):
            raise Conflict("该活动已有待处理的修改审核")

        with self.db.transaction() as conn:
            if direct_changes:
                self._apply_direct_changes(conn, activity, direct_changes, organizer.id)
            review_id = None
            if payload:
                review_id = self._insert_review(
                    conn, activity_id, ReviewType.MODIFY, payload
                )
                self.audit.record(
                    conn,
                    organizer.id,
                    "ACTIVITY",
                    activity_id,
                    "MODIFY_REVIEW_SUBMITTED",
                    f"提交修改审核：{activity.name}",
                    activity.status.value,
                    activity.status.value,
                )
        return self.get_review(review_id) if review_id is not None else None

    def request_cancel(self, organizer, activity_id: int, reason: str) -> ReviewApplication:
        """组织者申请取消活动，需管理员审批。"""
        activity = self.get_activity(activity_id)
        PermissionService.require_activity_owner(organizer, activity.organizer_id)
        if activity.status in {ActivityStatus.CANCELLED, ActivityStatus.ENDED}:
            raise Conflict("活动已取消或已结束")
        if not reason.strip():
            raise ValidationError("请填写取消原因")
        if self._has_pending_review(activity_id, ReviewType.CANCEL):
            raise Conflict("该活动已有待处理的取消申请")
        with self.db.transaction() as conn:
            review_id = self._insert_review(
                conn, activity_id, ReviewType.CANCEL, {"reason": reason.strip()}
            )
            self.audit.record(
                conn,
                organizer.id,
                "ACTIVITY",
                activity_id,
                "CANCEL_REVIEW_SUBMITTED",
                f"申请取消活动：{reason.strip()}",
                activity.status.value,
                activity.status.value,
            )
        return self.get_review(review_id)

    # ---------- 审核通过后的领域动作 ----------

    def approve_publish(
        self, conn: sqlite3.Connection, activity: Activity, admin_id: int
    ) -> None:
        """发布审核通过：活动变为公开。"""
        conn.execute(
            "UPDATE activity SET status = ? WHERE id = ?",
            (ActivityStatus.PUBLISHED.value, activity.id),
        )
        self.audit.record(
            conn,
            admin_id,
            "ACTIVITY",
            activity.id,
            "PUBLISH_APPROVED",
            f"发布审核通过：{activity.name}",
            activity.status.value,
            ActivityStatus.PUBLISHED.value,
        )
        self.notifications.create(
            conn,
            activity.organizer_id,
            NotificationType.REVIEW_RESULT,
            f"活动《{activity.name}》发布审核已通过，现已公开。",
        )

    def reject_publish(
        self,
        conn: sqlite3.Connection,
        activity: Activity,
        admin_id: int,
        comment: str,
    ) -> None:
        """发布审核驳回：退回草稿。"""
        conn.execute(
            "UPDATE activity SET status = ? WHERE id = ?",
            (ActivityStatus.DRAFT.value, activity.id),
        )
        self.audit.record(
            conn,
            admin_id,
            "ACTIVITY",
            activity.id,
            "PUBLISH_REJECTED",
            f"发布审核驳回：{comment or '未填写意见'}",
            activity.status.value,
            ActivityStatus.DRAFT.value,
        )
        self.notifications.create(
            conn,
            activity.organizer_id,
            NotificationType.REVIEW_RESULT,
            f"活动《{activity.name}》发布审核被驳回，原因：{comment or '未填写'}。",
        )

    def apply_modification(
        self,
        conn: sqlite3.Connection,
        activity: Activity,
        payload: str,
        admin_id: int,
    ) -> None:
        """修改审核通过后，把 payload 中的修改真正落库。"""
        data = json.loads(payload)
        changes: list[str] = []
        if "location" in data:
            conn.execute(
                "UPDATE activity SET location = ? WHERE id = ?",
                (data["location"], activity.id),
            )
            changes.append(f"地点改为 {data['location']}")
        for item in data.get("sessions", []):
            self._apply_session_update(conn, activity.id, item)
            changes.append(f"场次 {item['session_id']} 时间调整")
        for item in data.get("tickets", []):
            self.tickets.update_ticket(
                conn,
                int(item["ticket_type_id"]),
                int(item["price_cents"]),
                int(item["capacity"]),
            )
            changes.append(f"票种 {item['ticket_type_id']} 价格/容量调整")
        if changes:
            self._notify_registrants(
                conn,
                activity,
                f"活动《{activity.name}》信息已变更：" + "；".join(changes),
            )
            self.audit.record(
                conn,
                admin_id,
                "ACTIVITY",
                activity.id,
                "MODIFICATION_APPROVED",
                "；".join(changes),
                activity.status.value,
                activity.status.value,
            )

    # ---------- 时间推动 ----------

    def refresh_statuses(self) -> None:
        """按服务器时间推进活动和场次状态；每次菜单循环都会调用。"""
        now = self.clock.now()
        rows = self.db.query_all(
            """
            SELECT * FROM activity
             WHERE status IN ('PUBLISHED', 'ONGOING')
             ORDER BY id
            """
        )
        for row in rows:
            activity = Activity.from_row(row)
            sessions = self.get_sessions(activity.id)
            if not sessions:
                continue
            max_end = max(parse_dt(item.end_time) for item in sessions)
            min_checkin = min(parse_dt(item.checkin_open_time) for item in sessions)
            if now >= max_end:
                self._set_activity_status(
                    activity, ActivityStatus.ENDED, "活动时间结束"
                )
            elif activity.status is ActivityStatus.PUBLISHED and now >= min_checkin:
                self._set_activity_status(
                    activity, ActivityStatus.ONGOING, "最早场次检票开放"
                )
        self._refresh_all_session_statuses(now)

    def _set_activity_status(
        self, activity: Activity, new_status: ActivityStatus, reason: str
    ) -> None:
        """系统时间推动的状态转换，写一条系统审计。"""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE activity SET status = ? WHERE id = ?",
                (new_status.value, activity.id),
            )
            self.audit.record(
                conn,
                None,
                "ACTIVITY",
                activity.id,
                "ACTIVITY_STATUS_CHANGED",
                f"系统推进活动状态：{reason}",
                activity.status.value,
                new_status.value,
            )

    def _refresh_all_session_statuses(self, now: datetime) -> None:
        """刷新所有未取消活动的场次状态。"""
        rows = self.db.query_all(
            """
            SELECT s.*, a.status AS activity_status, a.sale_start, a.sale_end
              FROM activity_session s
              JOIN activity a ON a.id = s.activity_id
             WHERE a.status != 'CANCELLED'
            """
        )
        for row in rows:
            new_status = self._session_status_for(row, now)
            if new_status.value != row["status"]:
                self.db.execute(
                    "UPDATE activity_session SET status = ? WHERE id = ?",
                    (new_status.value, row["id"]),
                )

    def _session_status_for(self, row, now: datetime) -> SessionStatus:
        """计算场次应有的状态。"""
        if row["activity_status"] == ActivityStatus.ENDED.value:
            return SessionStatus.ENDED
        if now >= parse_dt(row["end_time"]):
            return SessionStatus.ENDED
        if row["activity_status"] in (
            ActivityStatus.DRAFT.value,
            ActivityStatus.PENDING_REVIEW.value,
        ):
            return SessionStatus.NOT_OPEN
        if now < parse_dt(row["sale_start"]):
            return SessionStatus.NOT_OPEN
        if now > parse_dt(row["sale_end"]):
            return SessionStatus.CLOSED
        if self.tickets.session_is_full(int(row["id"])):
            return SessionStatus.FULL
        return SessionStatus.OPEN

    # ---------- 内部工具 ----------

    def _insert_sessions(
        self,
        conn: sqlite3.Connection,
        activity_id: int,
        sessions: list[SessionDraft],
        created_at: str,
    ) -> None:
        """插入场次、票种和每个票种的候补队列。"""
        used_numbers: set[str] = set()
        for index, session_draft in enumerate(sessions):
            session_no = session_draft.session_no.strip() or f"S{index + 1}"
            if session_no in used_numbers:
                raise ValidationError(f"场次号重复：{session_no}")
            used_numbers.add(session_no)
            cursor = conn.execute(
                """
                INSERT INTO activity_session (
                    activity_id, session_no, start_time, end_time,
                    checkin_open_time, allow_waitlist, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activity_id,
                    session_no,
                    format_dt(session_draft.start_time),
                    format_dt(session_draft.end_time),
                    format_dt(session_draft.checkin_open_time),
                    int(session_draft.allow_waitlist),
                    SessionStatus.NOT_OPEN.value,
                ),
            )
            session_id = int(cursor.lastrowid)
            for ticket in session_draft.tickets:
                ticket_cursor = conn.execute(
                    """
                    INSERT INTO ticket_type (
                        session_id, kind, price_cents, capacity, occupied
                    ) VALUES (?, ?, ?, ?, 0)
                    """,
                    (
                        session_id,
                        ticket.kind.value,
                        ticket.price_cents,
                        ticket.capacity,
                    ),
                )
                conn.execute(
                    "INSERT INTO waitlist (ticket_type_id, created_at) VALUES (?, ?)",
                    (int(ticket_cursor.lastrowid), created_at),
                )

    def _validate_draft(self, draft: ActivityDraft) -> None:
        """创建活动前的完整校验。"""
        if not draft.name.strip():
            raise ValidationError("活动名称不能为空")
        if not draft.description.strip():
            raise ValidationError("活动描述不能为空")
        if not draft.location.strip():
            raise ValidationError("活动地点不能为空")
        if draft.estimated_participants <= 0:
            raise ValidationError("参与人数估计必须大于 0")
        if draft.sale_start >= draft.sale_end:
            raise ValidationError("售票开始时间必须早于售票截止时间")
        if not draft.sessions:
            raise ValidationError("至少需要一个场次")
        first_start = min(item.start_time for item in draft.sessions)
        if not draft.sale_start <= draft.refund_deadline <= first_start:
            raise ValidationError("退票截止必须不早于开售时间，且不晚于最早场次开始")
        for session in draft.sessions:
            if not session.start_time < session.end_time:
                raise ValidationError("场次开始时间必须早于结束时间")
            if not (
                draft.sale_start
                <= session.checkin_open_time
                <= session.start_time
            ):
                raise ValidationError("检票开放时间必须不早于开售时间且不晚于场次开始")
            if not session.tickets:
                raise ValidationError("每个场次至少需要一个票种")
            kinds = [ticket.kind for ticket in session.tickets]
            if len(kinds) != len(set(kinds)):
                raise ValidationError("同一场次的票种不能重复")
            for ticket in session.tickets:
                if ticket.price_cents < 0:
                    raise ValidationError("票价不能为负数")
                if ticket.capacity <= 0:
                    raise ValidationError("票种容量必须大于 0")

    def _has_pending_review(self, activity_id: int, review_type: ReviewType) -> bool:
        """判断活动是否已有同类型待审申请。"""
        row = self.db.query_one(
            """
            SELECT 1 FROM review_application
             WHERE activity_id = ? AND type = ? AND status = 'PENDING'
            """,
            (activity_id, review_type.value),
        )
        return row is not None

    def _insert_review(
        self,
        conn: sqlite3.Connection,
        activity_id: int,
        review_type: ReviewType,
        payload: dict,
    ) -> int:
        """插入一条待审核申请。"""
        cursor = conn.execute(
            """
            INSERT INTO review_application (
                activity_id, type, payload, status, submitted_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                activity_id,
                review_type.value,
                json.dumps(payload, ensure_ascii=False),
                ReviewStatus.PENDING.value,
                format_dt(self.clock.now()),
            ),
        )
        return int(cursor.lastrowid)

    def _apply_direct_changes(
        self,
        conn: sqlite3.Connection,
        activity: Activity,
        changes: dict[str, str],
        operator_id: int,
    ) -> None:
        """表面信息直接生效，不需要审核。"""
        columns = ", ".join(f"{key} = ?" for key in changes)
        values = list(changes.values()) + [activity.id]
        conn.execute(f"UPDATE activity SET {columns} WHERE id = ?", values)
        self.audit.record(
            conn,
            operator_id,
            "ACTIVITY",
            activity.id,
            "ACTIVITY_UPDATED",
            "直接修改表面信息：" + "、".join(changes.keys()),
            activity.status.value,
            activity.status.value,
        )

    def _build_session_updates(
        self, activity_id: int, updates: list[dict]
    ) -> list[dict]:
        """校验并序列化场次时间修改。"""
        result: list[dict] = []
        for update in updates:
            session = self.get_session(int(update["session_id"]))
            if session.activity_id != activity_id:
                raise ValidationError("场次不属于该活动")
            start = update["start_time"]
            end = update["end_time"]
            checkin = update.get("checkin_open_time", session.checkin_open_time)
            checkin_dt = (
                checkin if isinstance(checkin, datetime) else parse_dt(checkin)
            )
            if not start < end:
                raise ValidationError("场次开始时间必须早于结束时间")
            if not checkin_dt <= start:
                raise ValidationError("检票开放时间不能晚于场次开始")
            result.append(
                {
                    "session_id": session.id,
                    "start_time": format_dt(start),
                    "end_time": format_dt(end),
                    "checkin_open_time": format_dt(checkin_dt),
                }
            )
        return result

    def _build_ticket_updates(
        self, activity: Activity, updates: list[dict]
    ) -> list[dict]:
        """校验容量/票价修改：开售后禁止。"""
        if self.clock.now() >= parse_dt(activity.sale_start):
            raise PermissionDenied("开售后禁止修改容量与票价")
        result: list[dict] = []
        for update in updates:
            ticket = self.tickets.get_ticket_type(int(update["ticket_type_id"]))
            session = self.get_session(ticket.session_id)
            if session.activity_id != activity.id:
                raise ValidationError("票种不属于该活动")
            price = int(update["price_cents"])
            capacity = int(update["capacity"])
            if price < 0 or capacity <= 0:
                raise ValidationError("票价不能为负，容量必须大于 0")
            if capacity < ticket.occupied:
                raise ValidationError("容量不能小于已占用名额")
            result.append(
                {
                    "ticket_type_id": ticket.id,
                    "price_cents": price,
                    "capacity": capacity,
                }
            )
        return result

    def _apply_session_update(
        self, conn: sqlite3.Connection, activity_id: int, item: dict
    ) -> None:
        """修改审核通过后更新场次时间。"""
        conn.execute(
            """
            UPDATE activity_session
               SET start_time = ?, end_time = ?, checkin_open_time = ?
             WHERE id = ? AND activity_id = ?
            """,
            (
                item["start_time"],
                item["end_time"],
                item["checkin_open_time"],
                int(item["session_id"]),
                activity_id,
            ),
        )

    def _notify_registrants(
        self,
        conn: sqlite3.Connection,
        activity: Activity,
        content: str,
    ) -> None:
        """给活动的有效购票人发时间/地点变更通知。"""
        rows = conn.execute(
            """
            SELECT DISTINCT account_id FROM registration
             WHERE activity_id = ?
               AND status IN ('PURCHASED', 'CHECKED_IN')
            """,
            (activity.id,),
        ).fetchall()
        for row in rows:
            self.notifications.create(
                conn,
                int(row["account_id"]),
                NotificationType.ACTIVITY_CHANGED,
                content,
            )

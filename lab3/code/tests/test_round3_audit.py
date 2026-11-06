"""第三轮补充检测（2026-11-06）。

目的：在第二轮 85 个测试之外，按实验一需求（REQ-xxx）和实验二设计，从
角色权限、状态机、候补/检票生命周期、审计可见性等角度补充检测。

约定：
- 普通测试断言“需求规定的正确行为”，应全部通过；
- 以 ``test_bugXX_`` 开头并带 ``@unittest.expectedFailure`` 的测试是本次
  确认的缺陷；当前会显示为 expected failure。修复后它们会变成
  “unexpected success”，届时删除对应的 expectedFailure 装饰器即可。
"""
# pylint: disable=missing-function-docstring,too-many-public-methods

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path

from ticketing.domain_共享能力层.activities import (
    ActivityDraft,
    SessionDraft,
    TicketDraft,
)
from ticketing.domain_共享能力层.errors import (
    AppError,
    CapacityFull,
    Conflict,
    DeadlinePassed,
    PermissionDenied,
    ValidationError,
)
from ticketing.domain_共享能力层.models import (
    ActivityStatus,
    NotificationType,
    PaymentStatus,
    RegistrationStatus,
    Role,
    SessionStatus,
    TicketKind,
    WaitlistStatus,
)
from ticketing.infrastructure_基础设施.security import mask_phone, new_request_id

from .helpers import ServiceTestCase


class _AuditBase(ServiceTestCase):
    """本文件共用的构造辅助。"""

    def _publish(self, activity, assign_inspector: bool = True):
        review = self.s.activities.submit_for_review(self.organizer, activity.id)
        self.s.admin.review(self.admin, review.id, True, "通过")
        if assign_inspector:
            self.s.admin.assign_inspector(self.admin, self.inspector.id, activity.id)
        return self.s.activities.get_activity(activity.id)

    def _custom_activity(
        self,
        name: str,
        kinds: list[TicketKind],
        *,
        capacity: int = 2,
        allow_waitlist: bool = True,
        sale_start: datetime | None = None,
        sale_end: datetime | None = None,
        waitlist_deadline: datetime | None = None,
        refund_deadline: datetime | None = None,
        session_start: datetime | None = None,
        session_end: datetime | None = None,
        checkin_open: datetime | None = None,
        publish: bool = True,
        assign_inspector: bool = True,
    ):
        now = self.clock.now()
        sale_start = sale_start or now - timedelta(days=1)
        sale_end = sale_end or now + timedelta(hours=1)
        session_start = session_start or now + timedelta(days=1)
        session_end = session_end or session_start + timedelta(hours=2)
        checkin_open = checkin_open or session_start - timedelta(hours=1)
        draft = ActivityDraft(
            name=name,
            description=f"{name} 的描述",
            location="检测地点",
            estimated_participants=50,
            sale_start=sale_start,
            sale_end=sale_end,
            waitlist_deadline=waitlist_deadline or sale_end,
            refund_deadline=refund_deadline or sale_end,
            sessions=[
                SessionDraft(
                    start_time=session_start,
                    end_time=session_end,
                    checkin_open_time=checkin_open,
                    allow_waitlist=allow_waitlist,
                    session_no="S1",
                    tickets=[
                        TicketDraft(kind, 5000, capacity) for kind in kinds
                    ],
                )
            ],
        )
        activity = self.s.activities.create_activity(self.organizer, draft)
        if publish:
            activity = self._publish(activity, assign_inspector)
        return activity

    def _checkin_ready_activity(self, name: str = "检票窗口活动"):
        """检票窗口已开放、退票截止尚未到达的活动。"""
        now = self.clock.now()
        return self._custom_activity(
            name,
            [TicketKind.NORMAL],
            capacity=1,
            sale_end=now + timedelta(hours=1),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now - timedelta(hours=1),
        )


class RolePermissionAuditTests(_AuditBase):
    """REQ-002 / REQ-003 / REQ-018 / REQ-045：角色与数据范围。"""

    def test_req002_admin_cannot_self_register(self) -> None:
        with self.assertRaises(ValidationError):
            self.s.auth.register("13500000000", "Pass@123", "伪管理员", Role.ADMIN)

    def test_req002_phone_is_unique_across_roles(self) -> None:
        with self.assertRaises(Conflict):
            self.s.auth.register(
                self.organizer.phone, "Pass@123", "重复身份", Role.PARTICIPANT
            )

    def test_req002_admin_cannot_be_banned(self) -> None:
        with self.assertRaises(PermissionDenied):
            self.s.admin.ban_account(self.admin, self.admin.id, "越权测试")

    def test_req002_organizer_cannot_touch_other_organizer(self) -> None:
        activity = self.make_activity()
        self.register(self.people[0], activity)
        other = self.s.auth.register(
            "13700000099", "Org@123", "其他组织者", Role.ORGANIZER
        )
        with self.assertRaises(PermissionDenied):
            self.s.queries.activity_detail(other, activity.id)
        with self.assertRaises(PermissionDenied):
            self.s.queries.organizer_roster(other, activity.id)
        with self.assertRaises(PermissionDenied):
            self.s.queries.activity_statistics(other, activity.id)
        with self.assertRaises(PermissionDenied):
            self.s.activities.request_cancel(other, activity.id, "越权取消")

    def test_req003_inspector_cannot_read_roster_or_export(self) -> None:
        activity = self.make_activity()
        self.register(self.people[0], activity)
        with self.assertRaises(PermissionDenied):
            self.s.queries.organizer_roster(self.inspector, activity.id)
        target = Path(self.temp_dir.name) / "roster.csv"
        with self.assertRaises(PermissionDenied):
            self.s.queries.export_roster_csv(self.inspector, activity.id, target)
        self.assertFalse(target.exists())

    def test_req045_phone_visibility_follows_role(self) -> None:
        activity = self._checkin_ready_activity()
        registration = self.register(self.people[0], activity)
        roster = self.s.queries.organizer_roster(self.organizer, activity.id)
        self.assertEqual(roster[0].phone_masked, mask_phone(self.people[0].phone))
        self.assertNotEqual(roster[0].phone_masked, self.people[0].phone)

        request = self.s.checkin.request_checkin(self.people[0], registration.id)
        pending = self.s.checkin.list_pending_requests(self.inspector)
        target = next(item for item in pending if item.request_id == request.id)
        self.assertNotEqual(target.buyer_phone, self.people[0].phone)
        self.assertIn("****", target.buyer_phone)

        admin_view = self.s.queries.admin_search_registrations(
            self.admin, self.people[0].phone
        )
        self.assertEqual(
            admin_view[0].registration.buyer_phone, self.people[0].phone
        )


class RegistrationAuditTests(_AuditBase):
    """REQ-012 / REQ-022 / REQ-026 / REQ-048：报名与退票边界。"""

    def test_req012_buyer_must_match_account(self) -> None:
        activity = self.make_activity()
        session_id = self.session_id(activity)
        for name, phone in (
            (self.people[0].name, self.people[1].phone),
            (self.people[0].name, ""),
            ("   ", self.people[0].phone),
        ):
            with self.assertRaises(ValidationError):
                self.s.registrations.register(
                    self.people[0],
                    session_id,
                    TicketKind.NORMAL,
                    new_request_id("AUDIT"),
                    name,
                    phone,
                )

    def test_req014_checkin_requires_own_purchased_ticket(self) -> None:
        activity = self._checkin_ready_activity()
        registration = self.register(self.people[0], activity)
        with self.assertRaises(PermissionDenied):
            self.s.checkin.request_checkin(self.people[1], registration.id)
        self.s.refunds.refund_by_participant(self.people[0], registration.id)
        with self.assertRaises(Conflict):
            self.s.checkin.request_checkin(self.people[0], registration.id)

    def test_req022_terminal_registration_cannot_change(self) -> None:
        activity = self._checkin_ready_activity()
        registration = self.register(self.people[0], activity)
        self.s.refunds.refund_by_participant(self.people[0], registration.id)
        with self.assertRaises(Conflict):
            self.s.refunds.refund_by_participant(self.people[0], registration.id)
        with self.assertRaises(Conflict):
            self.s.refunds.force_refund(
                self.admin, registration.id, "终态强制退票"
            )

        other = self._checkin_ready_activity("活动取消终态")
        second = self.register(self.people[1], other)
        self.s.refunds.cancel_activity(self.admin, other.id, "取消")
        with self.assertRaises(Conflict):
            self.s.refunds.refund_by_participant(self.people[1], second.id)
        with self.assertRaises(Conflict):
            self.s.refunds.force_refund(self.admin, second.id, "终态强制退票")

    def test_req026_no_show_keeps_seat(self) -> None:
        now = self.clock.now()
        activity = self._custom_activity(
            "缺席不释放名额",
            [TicketKind.NORMAL],
            capacity=1,
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=30),
            session_start=now + timedelta(hours=1),
            session_end=now + timedelta(hours=2),
            checkin_open=now - timedelta(hours=1),
        )
        self.register(self.people[0], activity)
        self.clock.set(now + timedelta(hours=3))
        self.s.scheduler.tick()
        registration = self.s.registrations.get_registration(
            self.registration_id(self.people[0], activity)
        )
        self.assertIs(registration.status, RegistrationStatus.NO_SHOW)
        self.assertEqual(self.ticket(activity).occupied, 1)
        with self.assertRaises(Conflict):
            self.s.refunds.force_refund(self.admin, registration.id, "缺席终态")

    def test_req026_refund_then_tick_restores_open_status(self) -> None:
        activity = self._custom_activity(
            "退款后场次回到可报名", [TicketKind.NORMAL], capacity=1
        )
        # 先跑一次时间任务，让场次从 NOT_OPEN 刷新为可报名（CLI 每次进菜单都会 tick）。
        self.s.scheduler.tick()
        registration = self.register(self.people[0], activity)
        session = self.s.activities.get_session(self.session_id(activity))
        self.assertIs(session.status, SessionStatus.FULL)
        self.s.refunds.refund_by_participant(self.people[0], registration.id)
        self.s.scheduler.tick()
        session = self.s.activities.get_session(self.session_id(activity))
        self.assertIs(session.status, SessionStatus.OPEN)


class WaitlistAuditTests(_AuditBase):
    """REQ-019 / REQ-020 / REQ-023 / REQ-049：候补与递补。"""

    def test_req019_allow_waitlist_false_blocks_enqueue(self) -> None:
        activity = self._custom_activity(
            "不允许候补",
            [TicketKind.NORMAL],
            capacity=1,
            allow_waitlist=False,
        )
        self.register(self.people[0], activity)
        with self.assertRaises(Conflict):
            self.enqueue(self.people[1], activity)

    def test_req023_waitlist_terminal_states_are_immutable(self) -> None:
        now = self.clock.now()
        activity = self._custom_activity(
            "候补终态",
            [TicketKind.NORMAL],
            capacity=1,
            sale_end=now + timedelta(hours=2),
            waitlist_deadline=now + timedelta(hours=2),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(days=2),
            session_end=now + timedelta(days=2, hours=3),
            checkin_open=now + timedelta(days=2) - timedelta(hours=1),
        )
        holder = self.register(self.people[0], activity)
        cancelled = self.enqueue(self.people[1], activity)
        self.s.waitlist.cancel(self.people[1], cancelled.id)
        with self.assertRaises(Conflict):
            self.s.waitlist.cancel(self.people[1], cancelled.id)

        promoted = self.enqueue(self.people[2], activity)
        remaining = self.enqueue(self.people[3], activity)
        self.s.refunds.refund_by_participant(self.people[0], holder.id)
        self.s.scheduler.tick()
        self.assertIs(
            self.s.waitlist.get_record(promoted.id).status,
            WaitlistStatus.PROMOTED,
        )
        with self.assertRaises(Conflict):
            self.s.waitlist.cancel(self.people[2], promoted.id)

        self.clock.set(now + timedelta(hours=3))
        self.s.scheduler.tick()
        failed = self.s.waitlist.get_record(remaining.id)
        self.assertIs(failed.status, WaitlistStatus.FAILED)
        self.assertEqual(failed.refund_amount_cents, failed.payment_amount_cents)
        with self.assertRaises(Conflict):
            self.s.waitlist.cancel(self.people[3], remaining.id)

    def test_req049_promotion_generates_registration_with_snapshot(self) -> None:
        activity = self._custom_activity(
            "递补生成报名", [TicketKind.NORMAL], capacity=1
        )
        holder = self.register(self.people[0], activity)
        waiting = self.enqueue(self.people[1], activity)
        before = self.db.query_one(
            "SELECT COUNT(*) AS amount FROM registration "
            "WHERE account_id = ? AND session_id = ?",
            (self.people[1].id, self.session_id(activity)),
        )["amount"]
        self.assertEqual(before, 0)
        self.assertIs(waiting.payment_status, PaymentStatus.PAID)

        self.s.refunds.refund_by_participant(self.people[0], holder.id)
        self.s.scheduler.tick()

        promoted = self.s.waitlist.get_record(waiting.id)
        self.assertIs(promoted.status, WaitlistStatus.PROMOTED)
        registration = self.s.registrations.get_registration(
            self.registration_id(self.people[1], activity)
        )
        self.assertIs(registration.status, RegistrationStatus.PURCHASED)
        self.assertEqual(
            registration.payment_amount_cents,
            promoted.payment_amount_cents,
        )
        self.assertIs(registration.payment_status, PaymentStatus.PAID)


class ActivityAuditTests(_AuditBase):
    """REQ-007 / REQ-021 / REQ-028 / REQ-029 / REQ-038：活动与审核。"""

    def test_req021_cancel_cancels_all_sessions(self) -> None:
        activity = self.make_activity()
        self.register(self.people[0], activity)
        self.s.refunds.cancel_activity(self.admin, activity.id, "场地问题")
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.CANCELLED,
        )
        sessions = self.s.activities.get_sessions(activity.id)
        self.assertTrue(
            all(item.status is SessionStatus.CANCELLED for item in sessions)
        )
        self.assertIs(
            self.s.registrations.get_registration(
                self.registration_id(self.people[0], activity)
            ).status,
            RegistrationStatus.ACTIVITY_CANCELLED,
        )

    def test_req028_session_time_change_notifies_purchasers(self) -> None:
        activity = self.make_activity()
        self.register(self.people[0], activity)
        session_id = self.session_id(activity)
        now = self.clock.now()
        review = self.s.activities.modify_activity(
            self.organizer,
            activity.id,
            session_updates=[
                {
                    "session_id": session_id,
                    "start_time": now + timedelta(days=3),
                    "end_time": now + timedelta(days=3, hours=2),
                    "checkin_open_time": now + timedelta(days=3) - timedelta(hours=1),
                }
            ],
        )
        self.assertIsNotNone(review)
        self.s.admin.review(self.admin, review.id, True, "同意改期")
        notices = self.s.notifications.list_for(self.people[0].id)
        self.assertTrue(
            any(item.type is NotificationType.ACTIVITY_CHANGED for item in notices)
        )

    def test_req029_combined_query_and_role_scope(self) -> None:
        alpha = self._custom_activity(
            "Alpha 音乐会", [TicketKind.NORMAL], publish=True
        )
        beta = self._custom_activity(
            "Beta 展览", [TicketKind.VIP], publish=True
        )
        draft = self._custom_activity(
            "Gamma 草稿", [TicketKind.NORMAL], publish=False
        )
        viewer = self.people[0]

        keyword = self.s.queries.browse_activities(viewer, keyword="Alpha")
        self.assertEqual([view.activity.id for view in keyword], [alpha.id])

        normal = self.s.queries.browse_activities(viewer, kind=TicketKind.NORMAL)
        self.assertEqual([view.activity.id for view in normal], [alpha.id])
        vip = self.s.queries.browse_activities(viewer, kind=TicketKind.VIP)
        self.assertEqual([view.activity.id for view in vip], [beta.id])

        combined = self.s.queries.browse_activities(
            viewer, keyword="Alpha", kind=TicketKind.VIP
        )
        self.assertEqual(combined, [])

        draft_views = self.s.queries.browse_activities(
            self.admin, status=ActivityStatus.DRAFT.value
        )
        self.assertIn(draft.id, [view.activity.id for view in draft_views])
        participant_views = self.s.queries.browse_activities(
            viewer, status=ActivityStatus.DRAFT.value
        )
        self.assertNotIn(draft.id, [view.activity.id for view in participant_views])

        with self.assertRaises(PermissionDenied):
            self.s.queries.browse_activities(self.organizer)
        with self.assertRaises(PermissionDenied):
            self.s.queries.browse_activities(self.inspector)

    def test_req038_activity_is_not_cancelled_when_underfilled(self) -> None:
        now = self.clock.now()
        activity = self._custom_activity(
            "人数不足不自动取消",
            [TicketKind.NORMAL],
            capacity=5,
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=30),
            session_start=now + timedelta(hours=1),
            session_end=now + timedelta(hours=2),
            checkin_open=now - timedelta(hours=1),
        )
        self.s.scheduler.tick()
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.ONGOING,
        )
        self.clock.set(now + timedelta(hours=3))
        self.s.scheduler.tick()
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.ENDED,
        )


class AuditTraceTests(_AuditBase):
    """REQ-039 / REQ-040 / REQ-041：留痕覆盖、字段与可见范围。"""

    def test_req039_audit_covers_key_actions(self) -> None:
        now = self.clock.now()
        activity = self._custom_activity(
            "审计覆盖活动",
            [TicketKind.NORMAL, TicketKind.VIP],
            capacity=1,
            sale_end=now + timedelta(hours=1),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now - timedelta(hours=1),
        )
        first = self.register(self.people[0], activity)
        with self.assertRaises(Conflict):
            self.register(self.people[0], activity)

        waiting = self.enqueue(self.people[1], activity)
        self.s.waitlist.cancel(self.people[1], waiting.id)
        request = self.s.checkin.request_checkin(self.people[0], first.id)
        self.s.checkin.process(self.inspector, request.id, True)

        vip = self.register(self.people[2], activity, kind=TicketKind.VIP)
        promoted = self.enqueue(
            self.people[1], activity, kind=TicketKind.VIP
        )
        self.s.refunds.force_refund(self.admin, vip.id, "审计强制退票")
        self.s.scheduler.tick()
        self.assertIs(
            self.s.waitlist.get_record(promoted.id).status,
            WaitlistStatus.PROMOTED,
        )

        report = self.s.reports.submit_report(
            self.people[3], activity.id, "审计举报"
        )
        self.s.admin.handle_report(
            self.admin, report.id, dismiss=True, result="不属实"
        )
        self.s.admin.ban_account(self.admin, self.people[0].id, "审计封禁")

        cancel = self.s.activities.request_cancel(
            self.organizer, activity.id, "审计取消"
        )
        self.s.admin.review(self.admin, cancel.id, True, "同意取消")

        actions = {
            row["action"]
            for row in self.db.query_all("SELECT DISTINCT action FROM audit_log")
        }
        expected = {
            "ACTIVITY_CREATED",
            "PUBLISH_REVIEW_SUBMITTED",
            "PUBLISH_APPROVED",
            "INSPECTOR_ASSIGNED",
            "REGISTRATION_CREATED",
            "REGISTRATION_FAILED",
            "WAITLIST_JOINED",
            "WAITLIST_CANCELLED",
            "CHECK_REQUEST_CREATED",
            "CHECKIN_PASSED",
            "FORCE_REFUND",
            "WAITLIST_PROMOTED",
            "REPORT_SUBMITTED",
            "REPORT_HANDLED",
            "ACCOUNT_BANNED",
            "CANCEL_REVIEW_SUBMITTED",
            "REVIEW_APPROVED",
            "ACTIVITY_CANCELLED",
            "REFUND",
        }
        self.assertEqual(expected - actions, set())

    def test_req040_audit_fields_are_complete(self) -> None:
        activity = self.make_activity()
        registration = self.register(self.people[0], activity)
        self.s.refunds.refund_by_participant(self.people[0], registration.id)
        rows = self.db.query_all("SELECT * FROM audit_log")
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["operated_at"])
            self.assertTrue(row["object_type"])
            self.assertTrue(row["action"])
            self.assertTrue(row["description"])
            self.assertIsNotNone(row["object_id"])


class KnownDefectTests(_AuditBase):
    """本轮确认的缺陷；修复后删除对应 expectedFailure 装饰器。"""

    def test_bug01_banned_organizer_cannot_create_activity(self) -> None:
        """BUG-01（REQ-018）：封禁组织者仍能创建并发布新活动。"""
        self.s.admin.ban_account(self.admin, self.organizer.id, "封禁测试")
        now = self.clock.now()
        draft = ActivityDraft(
            name="封禁后新活动",
            description="不应创建",
            location="检测地点",
            estimated_participants=10,
            sale_start=now - timedelta(days=1),
            sale_end=now + timedelta(days=1),
            waitlist_deadline=now + timedelta(days=1),
            refund_deadline=now + timedelta(hours=20),
            sessions=[
                SessionDraft(
                    start_time=now + timedelta(days=2),
                    end_time=now + timedelta(days=2, hours=2),
                    checkin_open_time=now + timedelta(days=2) - timedelta(hours=1),
                    allow_waitlist=True,
                    session_no="S1",
                    tickets=[TicketDraft(TicketKind.NORMAL, 5000, 1)],
                )
            ],
        )
        fresh = self.s.auth.get_account(self.organizer.id)
        # 先验“重新读库后”的账号也必须被拒绝；再验 CLI 里可能持有的旧账号对象。
        with self.assertRaises(PermissionDenied):
            self.s.activities.create_activity(fresh, draft)
        with self.assertRaises(PermissionDenied):
            self.s.activities.create_activity(self.organizer, draft)

    def test_bug02_banned_inspector_cannot_process(self) -> None:
        """BUG-02（REQ-018）：封禁检票员仍能通过检票请求。"""
        activity = self._checkin_ready_activity()
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(self.people[0], registration.id)
        self.s.admin.ban_account(self.admin, self.inspector.id, "封禁测试")
        fresh = self.s.auth.get_account(self.inspector.id)
        # 同样要覆盖“重新读库后”的账号与登录时留下的旧对象。
        with self.assertRaises(PermissionDenied):
            self.s.checkin.process(fresh, request.id, True)
        with self.assertRaises(PermissionDenied):
            self.s.checkin.process(self.inspector, request.id, True)

    def test_bug03_waitlist_closes_at_sale_end(self) -> None:
        """BUG-03（REQ-012/019）：售票截止后不能加入候补。"""
        now = self.clock.now()
        activity = self._custom_activity(
            "候补与售票同截止",
            [TicketKind.NORMAL],
            capacity=1,
            sale_end=now + timedelta(hours=1),
            waitlist_deadline=now + timedelta(hours=1),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(hours=5),
            session_end=now + timedelta(hours=8),
            checkin_open=now + timedelta(hours=4),
        )
        self.register(self.people[0], activity)
        self.clock.set(now + timedelta(hours=2))
        with self.assertRaises(DeadlinePassed):
            self.enqueue(self.people[1], activity)

    def test_bug04_waitlist_deadline_cannot_precede_sale_end(self) -> None:
        """BUG-04（REQ-019）：候补截止必须等于售票截止。"""
        now = self.clock.now()
        with self.assertRaises(ValidationError):
            self._custom_activity(
                "候补早于售票截止",
                [TicketKind.NORMAL],
                sale_end=now + timedelta(hours=10),
                waitlist_deadline=now + timedelta(hours=2),
                refund_deadline=now + timedelta(hours=2),
                session_start=now + timedelta(hours=20),
                session_end=now + timedelta(hours=22),
                checkin_open=now + timedelta(hours=19),
                publish=False,
            )

    @unittest.expectedFailure
    def test_bug05_cancelled_activity_review_can_be_closed(self) -> None:
        """BUG-05（REQ-009）：活动取消后发布审核单永久 PENDING。"""
        activity = self.make_activity(publish=False)
        review = self.s.activities.submit_for_review(
            self.organizer, activity.id
        )
        self.s.refunds.cancel_activity(self.admin, activity.id, "紧急取消")
        try:
            self.s.admin.review(self.admin, review.id, False, "活动已取消")
        except AppError:
            pass
        pending = [
            item
            for item in self.s.admin.list_pending_reviews(self.admin)
            if item.id == review.id
        ]
        self.assertEqual(pending, [])

    @unittest.expectedFailure
    def test_bug06_refund_closes_pending_check_request(self) -> None:
        """BUG-06（REQ-013/014）：退票后待处理检票请求仍留在检票员工作台。"""
        activity = self._checkin_ready_activity()
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(self.people[0], registration.id)
        self.s.refunds.refund_by_participant(self.people[0], registration.id)
        pending_ids = {
            item.request_id
            for item in self.s.checkin.list_pending_requests(self.inspector)
        }
        self.assertNotIn(request.id, pending_ids)

    @unittest.expectedFailure
    def test_bug07_cancel_closes_pending_check_request(self) -> None:
        """BUG-07（REQ-011/014）：活动取消后待处理检票请求仍显示。"""
        activity = self._checkin_ready_activity()
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(self.people[0], registration.id)
        self.s.refunds.cancel_activity(self.admin, activity.id, "取消活动")
        pending_ids = {
            item.request_id
            for item in self.s.checkin.list_pending_requests(self.inspector)
        }
        self.assertNotIn(request.id, pending_ids)

    @unittest.expectedFailure
    def test_bug08_failed_registration_audit_visible_to_participant(self) -> None:
        """BUG-08（REQ-041）：参与者看不到自己的“报名失败”留痕。"""
        activity = self._custom_activity(
            "失败留痕", [TicketKind.NORMAL], capacity=1
        )
        self.register(self.people[0], activity)
        with self.assertRaises(CapacityFull):
            self.register(self.people[1], activity)
        logs = self.s.queries.audit_query(self.people[1])
        self.assertTrue(
            any(item.action == "REGISTRATION_FAILED" for item in logs)
        )

    @unittest.expectedFailure
    def test_bug09_session_end_closes_pending_check_request(self) -> None:
        """BUG-09（REQ-014/016）：场次结束后待处理检票请求仍留在工作台。"""
        activity = self._checkin_ready_activity()
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(self.people[0], registration.id)
        now = self.clock.now()
        self.clock.set(now + timedelta(hours=3, minutes=10))
        self.s.scheduler.tick()
        pending_ids = {
            item.request_id
            for item in self.s.checkin.list_pending_requests(self.inspector)
        }
        self.assertNotIn(request.id, pending_ids)


if __name__ == "__main__":
    unittest.main()

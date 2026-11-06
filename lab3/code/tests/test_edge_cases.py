"""第二轮补充的边界与联动测试。

目标是用真实服务跑出容易遗漏的组合场景：边界时刻、封禁后的既有票、
取消/递补联动、修改审核通知范围、举报状态范围、审计分层等。
"""
# pylint: disable=missing-function-docstring

from __future__ import annotations

import threading
import unittest
from datetime import timedelta

from ticketing.container import build_services
from ticketing.domain_共享能力层.activities import ActivityDraft, SessionDraft, TicketDraft
from ticketing.domain_共享能力层.errors import (
    Conflict,
    DeadlinePassed,
    PermissionDenied,
    ValidationError,
)
from ticketing.domain_共享能力层.models import (
    ActivityStatus,
    NotificationType,
    RegistrationStatus,
    TicketKind,
    WaitlistStatus,
)
from ticketing.infrastructure_基础设施.db import Database
from ticketing.infrastructure_基础设施.security import new_request_id, yuan_to_cents

from .helpers import ServiceTestCase


class MoneyUtilityTests(unittest.TestCase):
    """金额工具的异常类型。"""

    def test_non_finite_amount_is_validation_error(self) -> None:
        for text in ("nan", "NaN", "inf", "Infinity"):
            with self.assertRaises(ValidationError):
                yuan_to_cents(text)


class CheckinBoundaryTests(ServiceTestCase):
    """检票时间窗的边界。"""

    def _activity(self):
        now = self.clock.now()
        return self.make_activity(
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=15),
            session_start=now + timedelta(hours=1),
            session_end=now + timedelta(hours=2),
            checkin_open=now - timedelta(hours=1),
        )

    def test_checkin_at_session_end_rejected(self) -> None:
        now = self.clock.now()
        activity = self._activity()
        registration = self.register(self.people[0], activity)
        self.clock.set(now + timedelta(hours=2))
        with self.assertRaises(DeadlinePassed):
            self.s.checkin.request_checkin(self.people[0], registration.id)

    def test_checkin_at_open_time_allowed(self) -> None:
        activity = self._activity()
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(
            self.people[0], registration.id
        )
        self.assertEqual(request.status.value, "PENDING")


class BanEdgeTests(ServiceTestCase):
    """封禁后的既有票仍可使用。"""

    def test_duplicate_ban_rejected_without_extra_audit(self) -> None:
        self.s.admin.ban_account(self.admin, self.people[0].id, "违规", True)
        with self.assertRaises(Conflict):
            self.s.admin.ban_account(
                self.admin, self.people[0].id, "再次封禁", True
            )
        audits = self.db.query_all(
            "SELECT * FROM audit_log WHERE action = 'ACCOUNT_BANNED' "
            "AND object_id = ?",
            (self.people[0].id,),
        )
        self.assertEqual(len(audits), 1)

    def test_banned_participant_can_still_check_in(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_end=now + timedelta(hours=1),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now - timedelta(hours=1),
        )
        registration = self.register(self.people[0], activity)
        self.s.admin.ban_account(self.admin, self.people[0].id, "违规", True)
        request = self.s.checkin.request_checkin(
            self.people[0], registration.id
        )
        self.s.checkin.process(self.inspector, request.id, True)
        self.assertIs(
            self.s.registrations.get_registration(registration.id).status,
            RegistrationStatus.CHECKED_IN,
        )


class CancelRefundEdgeTests(ServiceTestCase):
    """取消活动与已检票、候补的联动。"""

    def test_cancel_refunds_checked_in_and_purchased_and_fails_waitlist(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            normal_capacity=2,
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=15),
            session_start=now + timedelta(hours=1),
            session_end=now + timedelta(hours=2),
            checkin_open=now - timedelta(hours=1),
        )
        first = self.register(self.people[0], activity)
        second = self.register(self.people[1], activity)
        waiting = self.enqueue(self.people[2], activity)
        request = self.s.checkin.request_checkin(self.people[0], first.id)
        self.s.checkin.process(self.inspector, request.id, True)

        self.s.refunds.cancel_activity(self.admin, activity.id, "场地不可用")

        self.assertIs(
            self.s.registrations.get_registration(first.id).status,
            RegistrationStatus.ACTIVITY_CANCELLED,
        )
        self.assertIs(
            self.s.registrations.get_registration(second.id).status,
            RegistrationStatus.ACTIVITY_CANCELLED,
        )
        refreshed = self.s.waitlist.get_record(waiting.id)
        self.assertIs(refreshed.status, WaitlistStatus.FAILED)
        self.assertEqual(refreshed.refund_amount_cents, 5000)
        self.assertEqual(self.ticket(activity).occupied, 0)

    def test_activity_cancel_audit_layers(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        registration = self.register(self.people[0], activity)
        waiting = self.enqueue(self.people[1], activity)
        self.s.refunds.cancel_activity(self.admin, activity.id, "测试取消")
        activity_audits = self.db.query_all(
            "SELECT * FROM audit_log WHERE action = 'ACTIVITY_CANCELLED' "
            "AND object_id = ?",
            (activity.id,),
        )
        refund_audits = self.db.query_all(
            "SELECT * FROM audit_log WHERE action = 'REFUND' AND object_id = ?",
            (registration.id,),
        )
        wait_audits = self.db.query_all(
            "SELECT * FROM audit_log WHERE action = 'WAITLIST_FAILED' "
            "AND object_id = ?",
            (waiting.id,),
        )
        self.assertEqual(len(activity_audits), 1)
        self.assertEqual(len(refund_audits), 1)
        self.assertEqual(len(wait_audits), 1)


class PromotionEdgeTests(ServiceTestCase):
    """退票/强制退票触发的自动递补。"""

    def test_force_refund_promotes_waitlist_head(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        first = self.register(self.people[0], activity)
        waiting = self.enqueue(self.people[1], activity)
        self.s.refunds.force_refund(self.admin, first.id, "测试强制退票")
        self.s.scheduler.tick()
        promoted = self.s.waitlist.get_record(waiting.id)
        self.assertIs(promoted.status, WaitlistStatus.PROMOTED)
        self.assertEqual(self.ticket(activity).occupied, 1)

    def test_two_refunds_promote_two_waiters(self) -> None:
        activity = self.make_activity(normal_capacity=2)
        first = self.register(self.people[0], activity)
        second = self.register(self.people[1], activity)
        third = self.enqueue(self.people[2], activity)
        fourth = self.enqueue(self.people[3], activity)
        self.s.refunds.refund_by_participant(self.people[0], first.id)
        self.s.refunds.refund_by_participant(self.people[1], second.id)
        self.s.scheduler.tick()
        self.assertIs(
            self.s.waitlist.get_record(third.id).status,
            WaitlistStatus.PROMOTED,
        )
        self.assertIs(
            self.s.waitlist.get_record(fourth.id).status,
            WaitlistStatus.PROMOTED,
        )
        self.assertEqual(self.ticket(activity).occupied, 2)


class MultiSessionTests(ServiceTestCase):
    """多场次：同账号可报不同场次，候补队列按场次独立。"""

    def _two_session_activity(self, capacity: int = 1):
        now = self.clock.now()
        draft = ActivityDraft(
            name="双场次活动",
            description="测试多场次",
            location="测试地点",
            estimated_participants=50,
            sale_start=now - timedelta(hours=1),
            sale_end=now + timedelta(hours=1),
            waitlist_deadline=now + timedelta(hours=1),
            refund_deadline=now + timedelta(hours=1),
            sessions=[
                SessionDraft(
                    start_time=now + timedelta(hours=2),
                    end_time=now + timedelta(hours=5),
                    checkin_open_time=now + timedelta(hours=1),
                    allow_waitlist=True,
                    session_no="S1",
                    tickets=[TicketDraft(TicketKind.NORMAL, 5000, capacity)],
                ),
                SessionDraft(
                    start_time=now + timedelta(hours=3),
                    end_time=now + timedelta(hours=6),
                    checkin_open_time=now + timedelta(hours=1),
                    allow_waitlist=True,
                    session_no="S2",
                    tickets=[TicketDraft(TicketKind.NORMAL, 5000, capacity)],
                ),
            ],
        )
        activity = self.s.activities.create_activity(self.organizer, draft)
        review = self.s.activities.submit_for_review(self.organizer, activity.id)
        self.s.admin.review(self.admin, review.id, True, "通过")
        self.s.admin.assign_inspector(self.admin, self.inspector.id, activity.id)
        return self.s.activities.get_activity(activity.id)

    def test_same_account_can_register_two_sessions(self) -> None:
        activity = self._two_session_activity()
        first, second = self.s.activities.get_sessions(activity.id)
        one = self.register(self.people[0], activity, session_id=first.id)
        two = self.register(self.people[0], activity, session_id=second.id)
        self.assertNotEqual(one.id, two.id)
        count = self.db.query_one(
            "SELECT COUNT(*) AS amount FROM registration WHERE account_id = ?",
            (self.people[0].id,),
        )["amount"]
        self.assertEqual(count, 2)

    def test_waitlist_queues_are_per_session(self) -> None:
        activity = self._two_session_activity()
        first, second = self.s.activities.get_sessions(activity.id)
        self.register(self.people[0], activity, session_id=first.id)
        self.register(self.people[1], activity, session_id=second.id)
        first_wait = self.s.waitlist.enqueue(
            self.people[2], first.id, TicketKind.NORMAL,
            new_request_id("EDGE"), self.people[2].name, self.people[2].phone,
        )
        second_wait = self.s.waitlist.enqueue(
            self.people[3], second.id, TicketKind.NORMAL,
            new_request_id("EDGE"), self.people[3].name, self.people[3].phone,
        )
        first_registration = self.db.query_one(
            "SELECT id FROM registration WHERE session_id = ? AND account_id = ?",
            (first.id, self.people[0].id),
        )["id"]
        self.s.refunds.refund_by_participant(
            self.people[0], int(first_registration)
        )
        self.s.scheduler.tick()
        self.assertIs(
            self.s.waitlist.get_record(first_wait.id).status,
            WaitlistStatus.PROMOTED,
        )
        self.assertIs(
            self.s.waitlist.get_record(second_wait.id).status,
            WaitlistStatus.WAITING,
        )

    def test_statistics_by_session_and_activity(self) -> None:
        now = self.clock.now()
        activity = self._two_session_activity(capacity=2)
        first, second = self.s.activities.get_sessions(activity.id)
        self.register(self.people[0], activity, session_id=first.id)
        self.register(self.people[0], activity, session_id=second.id)
        self.register(self.people[1], activity, session_id=first.id)
        self.register(self.people[2], activity, session_id=second.id)

        self.clock.set(now + timedelta(hours=2))
        registration = self.db.query_one(
            "SELECT id FROM registration WHERE session_id = ? AND account_id = ?",
            (first.id, self.people[0].id),
        )["id"]
        request = self.s.checkin.request_checkin(
            self.people[0], int(registration)
        )
        self.s.checkin.process(self.inspector, request.id, True)

        self.clock.set(now + timedelta(hours=7))
        self.s.scheduler.tick()
        stats = self.s.queries.activity_statistics(self.organizer, activity.id)
        self.assertTrue(stats.open)
        self.assertEqual(stats.overall.registered, 4)
        self.assertEqual(stats.overall.attended, 1)
        self.assertEqual(stats.overall.refunded, 0)
        self.assertEqual(len(stats.per_session), 2)
        self.assertEqual(stats.per_session[0].registered, 2)
        self.assertEqual(stats.per_session[0].attended, 1)


class WaitlistDeadlineTests(ServiceTestCase):
    """候补截止边界。"""

    def test_join_after_waitlist_deadline_rejected(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            normal_capacity=1,
            sale_end=now + timedelta(hours=1),
            waitlist_deadline=now + timedelta(hours=1),
            refund_deadline=now + timedelta(minutes=45),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now + timedelta(hours=1),
        )
        self.register(self.people[0], activity)
        self.clock.set(now + timedelta(hours=1, minutes=1))
        with self.assertRaises(DeadlinePassed):
            self.enqueue(self.people[1], activity)

    def test_join_at_waitlist_deadline_rejected(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            normal_capacity=1,
            sale_end=now + timedelta(hours=1),
            waitlist_deadline=now + timedelta(hours=1),
            refund_deadline=now + timedelta(minutes=45),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now + timedelta(hours=1),
        )
        self.register(self.people[0], activity)
        self.clock.set(now + timedelta(hours=1))
        with self.assertRaises(DeadlinePassed):
            self.enqueue(self.people[1], activity)

    def test_cancel_and_rejoin_waitlist_goes_to_tail(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        first = self.enqueue(self.people[1], activity)
        self.s.waitlist.cancel(self.people[1], first.id)
        second = self.enqueue(self.people[1], activity)
        self.assertNotEqual(first.id, second.id)
        head = self.s.waitlist.head(self.ticket(activity).id)
        self.assertEqual(head.id, second.id)


class ModificationEdgeTests(ServiceTestCase):
    """修改审核的时机与通知范围。"""

    def test_session_change_after_sale_requires_review_and_applies(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_start=now - timedelta(hours=1),
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=15),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=5),
            checkin_open=now + timedelta(hours=1),
        )
        session = self.s.activities.get_sessions(activity.id)[0]
        new_start = now + timedelta(days=1)
        review = self.s.activities.modify_activity(
            self.organizer,
            activity.id,
            session_updates=[
                {
                    "session_id": session.id,
                    "start_time": new_start,
                    "end_time": new_start + timedelta(hours=3),
                    "checkin_open_time": new_start - timedelta(hours=1),
                }
            ],
        )
        self.assertIsNotNone(review)
        self.s.admin.review(self.admin, review.id, True, "同意")
        updated = self.s.activities.get_sessions(activity.id)[0]
        self.assertEqual(updated.start_time, new_start.strftime("%Y-%m-%d %H:%M:%S"))

    def test_modification_notifies_only_active_registrants(self) -> None:
        activity = self.make_activity(normal_capacity=2)
        keep = self.register(self.people[0], activity)
        refunded = self.register(self.people[1], activity)
        self.s.refunds.refund_by_participant(self.people[1], refunded.id)
        review = self.s.activities.modify_activity(
            self.organizer, activity.id, location="新地点"
        )
        self.s.admin.review(self.admin, review.id, True, "同意")
        keep_notices = self.db.query_all(
            "SELECT * FROM notification WHERE recipient_id = ? AND type = ?",
            (self.people[0].id, NotificationType.ACTIVITY_CHANGED.value),
        )
        refunded_notices = self.db.query_all(
            "SELECT * FROM notification WHERE recipient_id = ? AND type = ?",
            (self.people[1].id, NotificationType.ACTIVITY_CHANGED.value),
        )
        self.assertEqual(len(keep_notices), 1)
        self.assertEqual(len(refunded_notices), 0)
        self.assertEqual(
            self.s.registrations.get_registration(keep.id).status,
            RegistrationStatus.PURCHASED,
        )


class ReportStateTests(ServiceTestCase):
    """举报允许的活动状态。"""

    def test_ended_activity_can_be_reported(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=15),
            session_start=now + timedelta(hours=1),
            session_end=now + timedelta(hours=2),
            checkin_open=now - timedelta(hours=1),
        )
        self.clock.set(now + timedelta(hours=3))
        self.s.scheduler.tick()
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.ENDED,
        )
        report = self.s.reports.submit_report(
            self.people[0], activity.id, "活动与宣传不符"
        )
        self.assertEqual(report.status.value, "PENDING")

    def test_draft_activity_cannot_be_reported(self) -> None:
        draft = self.make_activity(publish=False)
        with self.assertRaises(ValidationError):
            self.s.reports.submit_report(self.people[0], draft.id, "测试")


class ModificationStateTests(ServiceTestCase):
    """终态活动的修改/取消入口。"""

    def test_modify_and_cancel_after_end_rejected(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=15),
            session_start=now + timedelta(hours=1),
            session_end=now + timedelta(hours=2),
            checkin_open=now - timedelta(hours=1),
        )
        self.clock.set(now + timedelta(hours=3))
        self.s.scheduler.tick()
        with self.assertRaises(Conflict):
            self.s.activities.modify_activity(
                self.organizer, activity.id, location="新地点"
            )
        with self.assertRaises(Conflict):
            self.s.activities.request_cancel(
                self.organizer, activity.id, "测试取消"
            )


class RegistrationEdgeTests(ServiceTestCase):
    """报名幂等的跨账号冲突。"""

    def test_register_at_sale_start_allowed(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_start=now + timedelta(hours=1),
            sale_end=now + timedelta(hours=2),
            waitlist_deadline=now + timedelta(hours=2),
            refund_deadline=now + timedelta(hours=2),
            session_start=now + timedelta(hours=3),
            session_end=now + timedelta(hours=4),
            checkin_open=now + timedelta(hours=2),
        )
        self.clock.set(now + timedelta(hours=1))
        registration = self.register(self.people[0], activity)
        self.assertIs(registration.status, RegistrationStatus.PURCHASED)

    def test_request_id_owned_by_other_account_rejected(self) -> None:
        first_activity = self.make_activity()
        second_activity = self.make_activity()
        request_id = new_request_id("EDGE")
        self.register(
            self.people[0], first_activity, request_id=request_id
        )
        with self.assertRaises(Conflict):
            self.register(
                self.people[1], second_activity, request_id=request_id
            )

    def test_banned_participant_cannot_register_or_waitlist(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        self.s.admin.ban_account(self.admin, self.people[1].id, "违规", True)
        with self.assertRaises(PermissionDenied):
            self.enqueue(self.people[1], activity)

    def test_concurrent_same_account_same_session_one_record(self) -> None:
        """同一账号并发报名同一场次，唯一约束兜底，只留一条记录。"""
        activity = self.make_activity(normal_capacity=2)
        session_id = self.session_id(activity)
        barrier = threading.Barrier(2)
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            conn = Database(self.db_path)
            services = build_services(conn, self.clock)
            barrier.wait()
            try:
                services.registrations.register(
                    self.people[0],
                    session_id,
                    TicketKind.NORMAL,
                    new_request_id("CONC"),
                    self.people[0].name,
                    self.people[0].phone,
                )
                outcome = "ok"
            except Exception as exc:  # pylint: disable=broad-except
                outcome = type(exc).__name__
            with lock:
                results.append(outcome)
            conn.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        count = self.db.query_one(
            "SELECT COUNT(*) AS amount FROM registration "
            "WHERE account_id = ? AND session_id = ?",
            (self.people[0].id, session_id),
        )["amount"]
        self.assertEqual(count, 1)
        self.assertEqual(self.ticket(activity).occupied, 1)
        self.assertNotIn("IntegrityError", results)
        self.assertTrue(all(item in ("ok", "conflict") for item in results))

    def test_concurrent_first_waitlist_queue_creation(self) -> None:
        """两个账号并发首次入队时，候补队列只创建一条。"""
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        session_id = self.session_id(activity)
        barrier = threading.Barrier(2)
        results: list[str] = []
        lock = threading.Lock()

        def worker(person) -> None:
            conn = Database(self.db_path)
            services = build_services(conn, self.clock)
            barrier.wait()
            try:
                services.waitlist.enqueue(
                    person,
                    session_id,
                    TicketKind.NORMAL,
                    new_request_id("CONC"),
                    person.name,
                    person.phone,
                )
                outcome = "ok"
            except Exception as exc:  # pylint: disable=broad-except
                outcome = type(exc).__name__
            with lock:
                results.append(outcome)
            conn.close()

        threads = [
            threading.Thread(target=worker, args=(self.people[1],)),
            threading.Thread(target=worker, args=(self.people[2],)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        normal_ticket = self.ticket(activity)
        queues = self.db.query_one(
            "SELECT COUNT(*) AS amount FROM waitlist WHERE ticket_type_id = ?",
            (normal_ticket.id,),
        )["amount"]
        waiting = self.db.query_one(
            "SELECT COUNT(*) AS amount FROM waitlist_record "
            "WHERE session_id = ? AND status = 'WAITING'",
            (session_id,),
        )["amount"]
        self.assertEqual(queues, 1)
        self.assertEqual(waiting, 2)
        self.assertEqual(results, ["ok", "ok"])

    def test_concurrent_waitlist_enqueue_no_integrity_error(self) -> None:
        """并发入队不应把唯一约束异常漏出到调用方。"""
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        session_id = self.session_id(activity)
        barrier = threading.Barrier(2)
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            conn = Database(self.db_path)
            services = build_services(conn, self.clock)
            barrier.wait()
            try:
                services.waitlist.enqueue(
                    self.people[1],
                    session_id,
                    TicketKind.NORMAL,
                    new_request_id("CONC"),
                    self.people[1].name,
                    self.people[1].phone,
                )
                outcome = "ok"
            except Conflict:
                outcome = "conflict"
            except Exception as exc:  # pylint: disable=broad-except
                outcome = type(exc).__name__
            with lock:
                results.append(outcome)
            conn.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        count = self.db.query_one(
            "SELECT COUNT(*) AS amount FROM waitlist_record "
            "WHERE account_id = ? AND session_id = ? AND status = 'WAITING'",
            (self.people[1].id, session_id),
        )["amount"]
        self.assertEqual(count, 1)
        self.assertNotIn("IntegrityError", results)
        self.assertTrue(all(item in ("ok", "conflict") for item in results))


if __name__ == "__main__":
    unittest.main()

"""候补、退票、检票、时间推进与封禁测试。"""
# pylint: disable=missing-function-docstring,protected-access

from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import patch

from ticketing.application.seed import seed_demo
from ticketing.domain.errors import Conflict, DeadlinePassed, PermissionDenied
from ticketing.domain.models import (
    AccountStatus,
    ActivityStatus,
    CheckRequestStatus,
    RegistrationStatus,
    WaitlistStatus,
)
from ticketing.infrastructure.db import Database
from ticketing.infrastructure.security import new_request_id

from .helpers import ServiceTestCase


class WaitlistTests(ServiceTestCase):
    """候补 FIFO、取消、递补与截止失败。"""

    def test_fifo_and_promotion(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        first = self.register(self.people[0], activity)
        second = self.enqueue(self.people[1], activity)
        third = self.enqueue(self.people[2], activity)
        self.assertEqual(self.s.waitlist.head(self.ticket(activity).id).id, second.id)

        self.s.refunds.refund_by_participant(self.people[0], first.id)
        self.s.scheduler.tick()
        promoted = self.s.waitlist.get_record(second.id)
        self.assertIs(promoted.status, WaitlistStatus.PROMOTED)
        self.assertEqual(
            self.s.waitlist.head(self.ticket(activity).id).id, third.id
        )
        row = self.db.query_one(
            "SELECT * FROM registration WHERE account_id = ?",
            (self.people[1].id,),
        )
        self.assertIsNotNone(row)
        self.assertIs(RegistrationStatus(row["status"]), RegistrationStatus.PURCHASED)

    def test_cancel_refunds_full_amount(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        record = self.enqueue(self.people[1], activity)
        cancelled = self.s.waitlist.cancel(self.people[1], record.id)
        self.assertIs(cancelled.status, WaitlistStatus.SELF_CANCELLED)
        self.assertEqual(cancelled.refund_amount_cents, 5000)

    def test_expire_refunds(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            normal_capacity=1,
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now,
            session_start=now + timedelta(hours=1),
            session_end=now + timedelta(hours=2),
            checkin_open=now,
        )
        self.register(self.people[0], activity)
        record = self.enqueue(self.people[1], activity)
        self.clock.advance(hours=2)
        self.s.scheduler.tick()
        expired = self.s.waitlist.get_record(record.id)
        self.assertIs(expired.status, WaitlistStatus.FAILED)
        self.assertEqual(expired.refund_amount_cents, 5000)

    def test_duplicate_enqueue_returns_existing_on_unique_conflict(self) -> None:
        """并发重复入队撞唯一索引时，返回已有记录而不是抛 IntegrityError。"""
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        record = self.enqueue(self.people[1], activity)
        with patch.object(
            self.s.waitlist,
            "active_for_account_session",
            side_effect=[None, record],
        ):
            again = self.enqueue(self.people[1], activity)
        self.assertEqual(again.id, record.id)

    def test_waitlist_integrity_error_does_not_return_other_account_record(self) -> None:
        """并发同号冲突时，不能把其他账号的候补记录当作幂等结果返回。"""
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        request_id = new_request_id("TEST")
        other = self.enqueue(self.people[1], activity, request_id=request_id)
        with patch.object(
            self.s.waitlist,
            "find_by_request_id",
            side_effect=[None, other],
        ):
            with self.assertRaises(Conflict):
                self.enqueue(self.people[2], activity, request_id=request_id)
        self.assertIsNone(
            self.s.waitlist.active_for_account_session(
                self.people[2].id, self.session_id(activity)
            )
        )

    def test_promotion_retries_next_candidate_after_failure(self) -> None:
        """队首递补失败时，事件留待下一次并继续尝试下一位。"""
        activity = self.make_activity(normal_capacity=1)
        first = self.register(self.people[0], activity)
        second = self.enqueue(self.people[1], activity)
        third = self.enqueue(self.people[2], activity)
        original = self.s.promotion._create_registration
        calls = []

        def fake_create(conn, record, account):
            if not calls:
                calls.append(record.id)
                return False
            return original(conn, record, account)

        self.s.refunds.refund_by_participant(self.people[0], first.id)
        with patch.object(
            self.s.promotion, "_create_registration", side_effect=fake_create
        ):
            self.s.scheduler.tick()
            self.assertIs(
                self.s.waitlist.get_record(second.id).status,
                WaitlistStatus.FAILED,
            )
            self.assertIs(
                self.s.waitlist.get_record(third.id).status,
                WaitlistStatus.WAITING,
            )
            self.s.scheduler.tick()
        self.assertIs(
            self.s.waitlist.get_record(third.id).status,
            WaitlistStatus.PROMOTED,
        )


class RefundTests(ServiceTestCase):
    """退票截止与管理员强制退票。"""

    def test_refund_after_deadline_fails(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(refund_deadline=now + timedelta(hours=1))
        registration = self.register(self.people[0], activity)
        self.clock.advance(hours=2)
        with self.assertRaises(DeadlinePassed):
            self.s.refunds.refund_by_participant(
                self.people[0], registration.id
            )
        self.assertIs(
            self.s.registrations.get_registration(registration.id).status,
            RegistrationStatus.PURCHASED,
        )

    def test_force_refund_refunds_notifies_and_audits(self) -> None:
        activity = self.make_activity()
        registration = self.register(self.people[0], activity)
        result = self.s.refunds.force_refund(
            self.admin, registration.id, "违规操作"
        )
        self.assertIs(result.status, RegistrationStatus.SELF_CANCELLED)
        self.assertEqual(result.refund_amount_cents, 5000)
        notifications = self.db.query_all(
            "SELECT * FROM notification WHERE recipient_id = ?",
            (self.people[0].id,),
        )
        self.assertTrue(any(row["type"] == "FORCE_REFUND" for row in notifications))
        audits = self.db.query_all(
            "SELECT * FROM audit_log WHERE action = 'FORCE_REFUND'"
        )
        self.assertEqual(len(audits), 1)

    def test_force_refund_checked_in_rejected(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_end=now + timedelta(hours=1),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now - timedelta(hours=1),
        )
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(
            self.people[0], registration.id
        )
        self.s.checkin.process(self.inspector, request.id, True)
        with self.assertRaises(Conflict):
            self.s.refunds.force_refund(self.admin, registration.id, "测试")

    def test_stale_cancel_does_not_duplicate_activity_audit(self) -> None:
        """并发取消时，第二个持有旧活动对象的调用不能重复写审计/通知。"""
        activity = self.make_activity()
        self.register(self.people[0], activity)
        stale = self.s.activities.get_activity(activity.id)
        self.s.refunds.cancel_activity(self.admin, activity.id, "第一次")
        with self.assertRaises(Conflict):
            with self.db.transaction() as conn:
                self.s.refunds.cancel_activity_conn(
                    conn, self.admin.id, stale, "重复取消"
                )
        audits = self.db.query_all(
            "SELECT * FROM audit_log WHERE action = 'ACTIVITY_CANCELLED' "
            "AND object_type = 'ACTIVITY' AND object_id = ?",
            (activity.id,),
        )
        self.assertEqual(len(audits), 1)
        notices = self.db.query_all(
            "SELECT * FROM notification WHERE type = 'ACTIVITY_CANCELLED' "
            "AND recipient_id = ?",
            (self.organizer.id,),
        )
        self.assertEqual(len(notices), 1)


class CheckinTests(ServiceTestCase):
    """检票请求、通过、异常与权限。"""

    def _checkin_ready(self):
        # 售票截止必须早于场次开始；把场次放在未来，检票窗口现在已开放。
        now = self.clock.now()
        return self.make_activity(
            sale_end=now + timedelta(hours=1),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now - timedelta(hours=1),
        )

    def test_checkin_pass_and_duplicate(self) -> None:
        activity = self._checkin_ready()
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(
            self.people[0], registration.id
        )
        processed = self.s.checkin.process(self.inspector, request.id, True)
        self.assertIs(processed.status, CheckRequestStatus.PASSED)
        self.assertIs(
            self.s.registrations.get_registration(registration.id).status,
            RegistrationStatus.CHECKED_IN,
        )
        with self.assertRaises(Conflict):
            self.s.checkin.request_checkin(
                self.people[0], registration.id
            )

    def test_pending_requests_mask_phone(self) -> None:
        activity = self._checkin_ready()
        registration = self.register(self.people[0], activity)
        self.s.checkin.request_checkin(self.people[0], registration.id)
        requests = self.s.checkin.list_pending_requests(self.inspector)
        self.assertEqual(len(requests), 1)
        self.assertIn("****", requests[0].buyer_phone)
        self.assertNotEqual(requests[0].buyer_phone, self.people[0].phone)

    def test_abnormal_does_not_change_registration(self) -> None:
        activity = self._checkin_ready()
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(
            self.people[0], registration.id
        )
        processed = self.s.checkin.process(self.inspector, request.id, False)
        self.assertIs(processed.status, CheckRequestStatus.ABNORMAL)
        self.assertIs(
            self.s.registrations.get_registration(registration.id).status,
            RegistrationStatus.PURCHASED,
        )

    def test_checkin_before_window_fails(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=4),
            checkin_open=now + timedelta(hours=1),
        )
        registration = self.register(self.people[0], activity)
        with self.assertRaises(DeadlinePassed):
            self.s.checkin.request_checkin(
                self.people[0], registration.id
            )

    def test_inspector_must_be_assigned(self) -> None:
        other = self.s.auth.create_inspector(
            self.admin, "13900000099", "Inspect@123", "另一检票员"
        )
        activity = self._checkin_ready()
        registration = self.register(self.people[0], activity)
        request = self.s.checkin.request_checkin(
            self.people[0], registration.id
        )
        with self.assertRaises(Conflict):
            self.s.checkin.process(other, request.id, True)


class SchedulerTests(ServiceTestCase):
    """时间推动终态与名额规则。"""

    def test_session_end_marks_no_show_and_normal_end(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            normal_capacity=2,
            sale_end=now + timedelta(minutes=15),
            refund_deadline=now - timedelta(hours=1),
            session_start=now + timedelta(minutes=30),
            session_end=now + timedelta(hours=1),
            checkin_open=now - timedelta(hours=1),
        )
        first = self.register(self.people[0], activity)
        second = self.register(self.people[1], activity)
        request = self.s.checkin.request_checkin(self.people[0], first.id)
        self.s.checkin.process(self.inspector, request.id, True)
        self.clock.advance(hours=2)
        self.s.scheduler.tick()
        self.assertIs(
            self.s.registrations.get_registration(first.id).status,
            RegistrationStatus.NORMAL_END,
        )
        self.assertIs(
            self.s.registrations.get_registration(second.id).status,
            RegistrationStatus.NO_SHOW,
        )
        self.assertEqual(self.ticket(activity).occupied, 2)

    def test_cancelled_activity_not_finalized_by_time(self) -> None:
        """取消后的报名不会被场次结束的时间任务改成缺席/正常结束。"""
        now = self.clock.now()
        activity = self.make_activity(
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=15),
            session_start=now + timedelta(hours=1),
            session_end=now + timedelta(hours=2),
            checkin_open=now,
        )
        registration = self.register(self.people[0], activity)
        self.s.refunds.cancel_activity(self.admin, activity.id, "测试取消")
        self.clock.set(now + timedelta(hours=3))
        self.s.scheduler.tick()
        self.assertIs(
            self.s.registrations.get_registration(registration.id).status,
            RegistrationStatus.ACTIVITY_CANCELLED,
        )

    def test_activity_status_moves_with_time(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(hours=1),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now + timedelta(hours=1),
        )
        self.clock.advance(hours=1, minutes=1)
        self.s.scheduler.tick()
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.ONGOING,
        )
        self.clock.advance(hours=3)
        self.s.scheduler.tick()
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.ENDED,
        )


class BanTests(ServiceTestCase):
    """封禁的连锁处置。"""

    def test_ban_organizer_cancels_activities(self) -> None:
        activity = self.make_activity()
        registration = self.register(self.people[0], activity)
        self.s.admin.ban_account(self.admin, self.organizer.id, "违规", True)
        self.assertIs(
            self.s.auth.get_account(self.organizer.id).status,
            AccountStatus.BANNED,
        )
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.CANCELLED,
        )
        self.assertIs(
            self.s.registrations.get_registration(registration.id).status,
            RegistrationStatus.ACTIVITY_CANCELLED,
        )

    def test_ban_participant_blocks_new_purchase_but_keeps_ticket(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        registration = self.register(self.people[0], activity)
        self.s.admin.ban_account(self.admin, self.people[0].id, "违规", True)
        with self.assertRaises(PermissionDenied):
            self.register(self.people[0], self.make_activity())
        self.assertIs(
            self.s.registrations.get_registration(registration.id).status,
            RegistrationStatus.PURCHASED,
        )

    def test_ban_participant_cancels_waitlist(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        record = self.enqueue(self.people[1], activity)
        self.s.admin.ban_account(self.admin, self.people[1].id, "违规", True)
        refreshed = self.s.waitlist.get_record(record.id)
        self.assertIs(refreshed.status, WaitlistStatus.FAILED)
        self.assertEqual(refreshed.refund_amount_cents, 5000)


class SeedDataTests(unittest.TestCase):
    """演示数据的完整性：场景齐全、状态与运行记录一致。"""

    def test_demo_data_is_complete(self) -> None:
        db = Database(":memory:")
        db.initialize()
        try:
            self.assertTrue(seed_demo(db))
            statuses = [
                row["status"]
                for row in db.query_all("SELECT status FROM activity ORDER BY id")
            ]
            self.assertEqual(
                statuses, ["PUBLISHED", "ONGOING", "ENDED", "DRAFT"]
            )
            # 检票员工作台应有一条 PENDING 请求（p4）
            pending = db.query_one(
                "SELECT COUNT(*) AS amount FROM check_request "
                "WHERE status = 'PENDING'"
            )
            self.assertEqual(pending["amount"], 1)
            waiting = db.query_one(
                "SELECT COUNT(*) AS amount FROM waitlist_record "
                "WHERE status = 'WAITING'"
            )
            self.assertEqual(waiting["amount"], 1)
            rows = db.query_all(
                """
                SELECT r.status, COUNT(*) AS amount
                  FROM registration r
                  JOIN activity a ON a.id = r.activity_id
                 WHERE a.name = '秋季摄影展'
                 GROUP BY r.status
                """
            )
            self.assertEqual(
                {row["status"]: row["amount"] for row in rows},
                {"NORMAL_END": 2, "NO_SHOW": 1, "SELF_CANCELLED": 1},
            )
            report = db.query_one(
                "SELECT COUNT(*) AS amount FROM report WHERE status = 'PENDING'"
            )
            self.assertEqual(report["amount"], 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

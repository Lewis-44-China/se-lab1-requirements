"""认证、活动审核、报名幂等、名额并发测试。"""
# pylint: disable=missing-function-docstring

from __future__ import annotations

import threading
import unittest
from datetime import timedelta

from ticketing.container import build_services
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import (
    CapacityFull,
    Conflict,
    DeadlinePassed,
    PermissionDenied,
    ValidationError,
)
from ticketing.domain.models import ActivityStatus, RegistrationStatus, Role, TicketKind
from ticketing.infrastructure.security import new_request_id

from .helpers import ServiceTestCase


class AuthTests(ServiceTestCase):
    """账号注册与登录。"""

    def test_register_and_login(self) -> None:
        account = self.s.auth.register(
            "13600000099", "Pass@123", "新用户", Role.PARTICIPANT
        )
        logged = self.s.auth.login("13600000099", "Pass@123")
        self.assertEqual(account.id, logged.id)
        self.assertEqual(logged.role, Role.PARTICIPANT)

    def test_duplicate_phone_rejected(self) -> None:
        with self.assertRaises(Conflict):
            self.s.auth.register(
                self.people[0].phone, "Pass@123", "重复", Role.PARTICIPANT
            )

    def test_wrong_password_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.s.auth.login(self.people[0].phone, "wrong")

    def test_password_is_not_plaintext(self) -> None:
        row = self.db.query_one(
            "SELECT * FROM account WHERE id = ?", (self.people[0].id,)
        )
        self.assertNotEqual(row["password_hash"], "Pass@123")
        self.assertTrue(row["password_salt"])
        self.assertGreaterEqual(len(row["password_hash"]), 64)


class ActivityTests(ServiceTestCase):
    """活动发布、修改与取消审核。"""

    def test_publish_review_flow(self) -> None:
        activity = self.make_activity(publish=False)
        self.assertIs(activity.status, ActivityStatus.DRAFT)
        review = self.s.activities.submit_for_review(self.organizer, activity.id)
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.PENDING_REVIEW,
        )
        self.s.admin.review(self.admin, review.id, True, "通过")
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.PUBLISHED,
        )

    def test_publish_reject_returns_draft(self) -> None:
        activity = self.make_activity(publish=False)
        review = self.s.activities.submit_for_review(self.organizer, activity.id)
        self.s.admin.review(self.admin, review.id, False, "资料不完整")
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.DRAFT,
        )

    def test_ticket_change_before_sale_needs_review(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_start=now + timedelta(days=2),
            sale_end=now + timedelta(days=2, hours=12),
            refund_deadline=now + timedelta(days=2),
            session_start=now + timedelta(days=3),
            checkin_open=now + timedelta(days=2, hours=1),
        )
        ticket = self.ticket(activity, TicketKind.NORMAL)
        review = self.s.activities.modify_activity(
            self.organizer,
            activity.id,
            ticket_updates=[
                {
                    "ticket_type_id": ticket.id,
                    "price_cents": 8800,
                    "capacity": 5,
                }
            ],
        )
        self.assertIsNotNone(review)
        self.assertEqual(
            self.s.tickets.get_ticket_type(ticket.id).price_cents, 5000
        )
        self.s.admin.review(self.admin, review.id, True, "同意")
        updated = self.s.tickets.get_ticket_type(ticket.id)
        self.assertEqual(updated.price_cents, 8800)
        self.assertEqual(updated.capacity, 5)

    def test_ticket_change_after_sale_forbidden(self) -> None:
        activity = self.make_activity()
        ticket = self.ticket(activity, TicketKind.NORMAL)
        with self.assertRaises(PermissionDenied):
            self.s.activities.modify_activity(
                self.organizer,
                activity.id,
                ticket_updates=[
                    {
                        "ticket_type_id": ticket.id,
                        "price_cents": 100,
                        "capacity": 9,
                    }
                ],
            )

    def test_ticket_change_approved_after_sale_forbidden(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_start=now + timedelta(days=2),
            sale_end=now + timedelta(days=2, hours=12),
            refund_deadline=now + timedelta(days=2),
            session_start=now + timedelta(days=3),
            checkin_open=now + timedelta(days=2, hours=1),
        )
        ticket = self.ticket(activity, TicketKind.NORMAL)
        review = self.s.activities.modify_activity(
            self.organizer,
            activity.id,
            ticket_updates=[
                {
                    "ticket_type_id": ticket.id,
                    "price_cents": 8800,
                    "capacity": 5,
                }
            ],
        )
        self.assertIsNotNone(review)
        self.clock.set(now + timedelta(days=2, hours=1))
        with self.assertRaises(PermissionDenied):
            self.s.admin.review(self.admin, review.id, True, "同意")
        updated = self.s.tickets.get_ticket_type(ticket.id)
        self.assertEqual(updated.price_cents, 5000)
        self.assertEqual(updated.capacity, 1)

    def test_session_time_change_respects_deadlines(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_start=now - timedelta(days=1),
            sale_end=now + timedelta(days=1),
            refund_deadline=now + timedelta(days=1),
            session_start=now + timedelta(days=2),
            checkin_open=now + timedelta(days=1, hours=23),
        )
        session = self.s.activities.get_sessions(activity.id)[0]
        with self.assertRaises(ValidationError):
            self.s.activities.modify_activity(
                self.organizer,
                activity.id,
                session_updates=[
                    {
                        "session_id": session.id,
                        "start_time": now + timedelta(hours=1),
                        "end_time": now + timedelta(hours=4),
                        "checkin_open_time": now,
                    }
                ],
            )

    def test_location_change_notifies_registrants(self) -> None:
        activity = self.make_activity()
        self.register(self.people[0], activity)
        review = self.s.activities.modify_activity(
            self.organizer, activity.id, location="新地点"
        )
        self.assertIsNotNone(review)
        self.s.admin.review(self.admin, review.id, True, "同意")
        updated = self.s.activities.get_activity(activity.id)
        self.assertEqual(updated.location, "新地点")
        rows = self.db.query_all(
            "SELECT * FROM notification WHERE recipient_id = ?",
            (self.people[0].id,),
        )
        self.assertTrue(any(row["type"] == "ACTIVITY_CHANGED" for row in rows))

    def test_cancel_approval_refunds_and_fails_waitlist(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        registration = self.register(self.people[0], activity)
        waitlist = self.enqueue(self.people[1], activity)
        review = self.s.activities.request_cancel(
            self.organizer, activity.id, "场地不可用"
        )
        self.s.admin.review(self.admin, review.id, True, "同意取消")
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.CANCELLED,
        )
        refreshed = self.s.registrations.get_registration(registration.id)
        self.assertIs(
            refreshed.status, RegistrationStatus.ACTIVITY_CANCELLED
        )
        self.assertEqual(refreshed.refund_amount_cents, 5000)
        record = self.s.waitlist.get_record(waitlist.id)
        self.assertEqual(record.status.value, "FAILED")
        self.assertEqual(record.refund_amount_cents, 5000)


    def test_publish_approval_after_cancel_rejected(self) -> None:
        activity = self.make_activity(publish=False)
        publish_review = self.s.activities.submit_for_review(
            self.organizer, activity.id
        )
        cancel_review = self.s.activities.request_cancel(
            self.organizer, activity.id, "取消"
        )
        self.s.admin.review(self.admin, cancel_review.id, True, "同意取消")
        with self.assertRaises(Conflict):
            self.s.admin.review(self.admin, publish_review.id, True, "同意发布")
        with self.assertRaises(Conflict):
            self.s.admin.review(self.admin, publish_review.id, False, "驳回")
        self.assertIs(
            self.s.activities.get_activity(activity.id).status,
            ActivityStatus.CANCELLED,
        )

    def test_modification_approval_after_cancel_rejected(self) -> None:
        activity = self.make_activity()
        review = self.s.activities.modify_activity(
            self.organizer, activity.id, location="新地点"
        )
        self.assertIsNotNone(review)
        self.s.refunds.cancel_activity(self.admin, activity.id, "活动取消")
        with self.assertRaises(Conflict):
            self.s.admin.review(self.admin, review.id, True, "同意修改")
        updated = self.s.activities.get_activity(activity.id)
        self.assertIs(updated.status, ActivityStatus.CANCELLED)
        self.assertNotEqual(updated.location, "新地点")


class RegistrationTests(ServiceTestCase):
    """报名幂等、重复报名与名额。"""

    def test_register_success(self) -> None:
        activity = self.make_activity()
        registration = self.register(self.people[0], activity)
        self.assertIs(registration.status, RegistrationStatus.PURCHASED)
        self.assertEqual(registration.payment_amount_cents, 5000)
        self.assertEqual(self.ticket(activity).occupied, 1)

    def test_same_request_id_is_idempotent(self) -> None:
        activity = self.make_activity()
        request_id = new_request_id("TEST")
        first = self.register(
            self.people[0], activity, request_id=request_id
        )
        second = self.register(
            self.people[0], activity, request_id=request_id
        )
        self.assertEqual(first.id, second.id)
        count = self.db.query_one(
            "SELECT COUNT(*) AS amount FROM registration WHERE session_id = ?",
            (self.session_id(activity),),
        )["amount"]
        self.assertEqual(count, 1)

    def test_same_session_second_request_rejected(self) -> None:
        activity = self.make_activity()
        self.register(self.people[0], activity)
        with self.assertRaises(Conflict):
            self.register(self.people[0], activity)

    def test_register_at_sale_end_is_allowed(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(sale_end=now + timedelta(hours=1))
        self.clock.set(now + timedelta(hours=1))
        registration = self.register(self.people[0], activity)
        self.assertIs(registration.status, RegistrationStatus.PURCHASED)

    def test_register_after_sale_end_fails(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(sale_end=now + timedelta(hours=1))
        self.clock.set(now + timedelta(hours=1, seconds=1))
        with self.assertRaises(DeadlinePassed):
            self.register(self.people[0], activity)

    def test_capacity_full_and_failure_audit(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        with self.assertRaises(CapacityFull):
            self.register(self.people[1], activity)
        self.assertEqual(self.ticket(activity).occupied, 1)
        failures = self.db.query_all(
            """
            SELECT * FROM audit_log
             WHERE action = 'REGISTRATION_FAILED' AND operator_id = ?
            """,
            (self.people[1].id,),
        )
        self.assertEqual(len(failures), 1)

    def test_concurrent_last_seat_only_one_wins(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        participants = [
            self.s.auth.register(
                f"1350000000{i}", "Pass@123", f"并发{i}", Role.PARTICIPANT
            )
            for i in range(8)
        ]
        session_id = self.session_id(activity)
        barrier = threading.Barrier(len(participants))
        results: list[str] = []
        lock = threading.Lock()

        def worker(person) -> None:
            conn = Database(self.db_path)
            services = build_services(conn, self.clock)
            barrier.wait()
            try:
                services.registrations.register(
                    person,
                    session_id,
                    TicketKind.NORMAL,
                    new_request_id("CONC"),
                    person.name,
                    person.phone,
                )
                outcome = "ok"
            except CapacityFull:
                outcome = "full"
            except Exception as exc:  # pylint: disable=broad-except
                outcome = f"error:{exc}"
            finally:
                conn.close()
            with lock:
                results.append(outcome)

        threads = [
            threading.Thread(target=worker, args=(person,))
            for person in participants
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(results.count("full"), len(participants) - 1, results)
        ticket = self.ticket(activity, TicketKind.NORMAL)
        self.assertEqual(ticket.occupied, 1)
        count = self.db.query_one(
            "SELECT COUNT(*) AS amount FROM registration WHERE session_id = ?",
            (self.session_id(activity),),
        )["amount"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()

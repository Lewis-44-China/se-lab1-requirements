"""查询、名单、统计、审计数据范围测试。"""
# pylint: disable=missing-function-docstring

from __future__ import annotations

import unittest
from datetime import timedelta
from pathlib import Path

from ticketing.domain.models import RegistrationStatus, Role

from .helpers import ServiceTestCase


class QueryTests(ServiceTestCase):
    """Q1 只读查询与数据范围。"""

    def test_participant_cannot_see_draft(self) -> None:
        draft = self.make_activity(name="草稿活动", publish=False)
        views = self.s.queries.browse_activities(self.people[0])
        self.assertNotIn(draft.id, [view.activity.id for view in views])
        admin_views = self.s.queries.browse_activities(self.admin)
        self.assertIn(draft.id, [view.activity.id for view in admin_views])

    def test_organizer_roster_masks_phone(self) -> None:
        activity = self.make_activity()
        self.register(self.people[0], activity)
        roster = self.s.queries.organizer_roster(self.organizer, activity.id)
        self.assertEqual(len(roster), 1)
        self.assertIn("****", roster[0].phone_masked)
        self.assertNotIn(self.people[0].phone, roster[0].phone_masked)

    def test_export_csv_has_no_phone(self) -> None:
        activity = self.make_activity()
        self.register(self.people[0], activity)
        target = Path(self.temp_dir.name) / "roster.csv"
        count = self.s.queries.export_roster_csv(
            self.organizer, activity.id, target
        )
        self.assertEqual(count, 1)
        content = target.read_text(encoding="utf-8-sig")
        self.assertIn("姓名,场次,票种", content)
        self.assertIn("参与者1", content)
        self.assertNotIn(self.people[0].phone, content)

    def test_statistics_open_only_after_all_sessions_end(self) -> None:
        now = self.clock.now()
        self.clock.set(now - timedelta(days=5))
        activity = self.make_activity(
            normal_capacity=4,
            sale_start=now - timedelta(days=5),
            sale_end=now - timedelta(days=4),
            refund_deadline=now - timedelta(days=3, hours=12),
            session_start=now - timedelta(days=2),
            session_end=now - timedelta(days=2) + timedelta(hours=3),
            checkin_open=now - timedelta(days=2, hours=1),
        )
        first = self.register(self.people[0], activity)
        second = self.register(self.people[1], activity)
        third = self.register(self.people[2], activity)
        self.clock.set(now - timedelta(days=4))
        self.s.refunds.refund_by_participant(self.people[2], third.id)
        self.clock.set(now - timedelta(days=2) + timedelta(hours=1))
        request = self.s.checkin.request_checkin(self.people[0], first.id)
        self.s.checkin.process(self.inspector, request.id, True)
        self.clock.set(now)
        self.s.scheduler.tick()

        stats = self.s.queries.activity_statistics(self.organizer, activity.id)
        self.assertTrue(stats.open)
        self.assertEqual(stats.overall.registered, 2)
        self.assertEqual(stats.overall.attended, 1)
        self.assertEqual(stats.overall.refunded, 1)
        self.assertAlmostEqual(stats.overall.attendance_rate, 50.0, places=1)
        self.assertAlmostEqual(stats.overall.refund_rate, 33.3, places=1)
        self.assertIs(
            self.s.registrations.get_registration(second.id).status,
            RegistrationStatus.NO_SHOW,
        )
        self.assertIs(
            self.s.registrations.get_registration(first.id).status,
            RegistrationStatus.NORMAL_END,
        )

    def test_audit_scope_by_role(self) -> None:
        activity = self.make_activity()
        registration = self.register(self.people[0], activity)
        participant_logs = self.s.queries.audit_query(self.people[0])
        self.assertTrue(
            any(item.object_type == "REGISTRATION" for item in participant_logs)
        )
        organizer_logs = self.s.queries.audit_query(self.organizer)
        self.assertFalse(
            any(item.object_type == "REGISTRATION" for item in organizer_logs)
        )
        self.assertTrue(
            any(item.object_type == "ACTIVITY" for item in organizer_logs)
        )
        admin_logs = self.s.queries.audit_query(self.admin)
        self.assertTrue(
            any(item.object_type == "REGISTRATION" for item in admin_logs)
        )
        self.assertTrue(
            any(item.object_type == "ACTIVITY" for item in admin_logs)
        )
        self.assertGreaterEqual(
            len(admin_logs), len(participant_logs) + len(organizer_logs) - 2
        )
        self.assertIsNotNone(
            self.s.registrations.get_registration(registration.id)
        )

    def test_audit_scope_includes_reported_organizer(self) -> None:
        activity = self.make_activity()
        report = self.s.reports.submit_report(
            self.people[0], activity.id, "测试举报"
        )
        self.s.admin.handle_report(
            self.admin, report.id, dismiss=True, result="举报不属实"
        )
        logs = self.s.queries.audit_query(self.organizer, object_type="REPORT")
        self.assertTrue(any(item.object_id == report.id for item in logs))
        other = self.s.auth.register(
            "13700000099", "Org@123", "其他组织者", Role.ORGANIZER
        )
        other_logs = self.s.queries.audit_query(other, object_type="REPORT")
        self.assertFalse(any(item.object_id == report.id for item in other_logs))

    def test_platform_summary(self) -> None:
        self.make_activity()
        summary = self.s.queries.platform_summary(self.admin)
        self.assertGreaterEqual(summary["registrations"], 0)
        self.assertIn("PARTICIPANT", summary["accounts"])
        self.assertIn("PUBLISHED", summary["activities"])


if __name__ == "__main__":
    unittest.main()

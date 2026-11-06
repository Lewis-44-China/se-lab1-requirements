"""表现层入口的回归测试：开售后改价入口、我的票候补分类。"""
# pylint: disable=missing-function-docstring,protected-access

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from ticketing.infrastructure_基础设施.db import Database
from ticketing.presentation_表现层.cli import ConsoleApp, main

from .helpers import ServiceTestCase


class ConsoleEntryTests(ServiceTestCase):
    """直接调用 ConsoleApp 的菜单方法，校验界面行为。"""

    def test_ticket_modification_locked_after_sale(self) -> None:
        now = self.clock.now()
        activity = self.make_activity(
            sale_start=now - timedelta(hours=1),
            sale_end=now + timedelta(minutes=30),
            refund_deadline=now + timedelta(minutes=15),
            session_start=now + timedelta(hours=2),
            session_end=now + timedelta(hours=3),
            checkin_open=now + timedelta(hours=1),
        )
        app = ConsoleApp(self.s)
        output = io.StringIO()
        with patch("builtins.input", side_effect=["4", ""]):
            with redirect_stdout(output):
                app._manage_activity(self.organizer, activity)
        text = output.getvalue()
        self.assertIn("活动已开售，不可修改", text)
        self.assertIn("票价与容量不可修改", text)
        reviews = self.db.query_all(
            "SELECT * FROM review_application WHERE activity_id = ? "
            "AND type = 'MODIFY'",
            (activity.id,),
        )
        self.assertEqual(reviews, [])

    def test_create_wizard_can_disable_waitlist(self) -> None:
        app = ConsoleApp(self.s)
        output = io.StringIO()
        inputs = [
            "测试活动", "测试描述", "测试地点", "10",
            "2026-12-01 10:00", "2026-12-01 12:00", "2026-12-01 11:00",
            "2026-12-01 13:00", "2026-12-01 12:30",
            "n",          # 不允许候补
            "n",          # 不设置 VIP
            "y", "100", "2",  # 普通票
            "n",          # 不提交审核
            "",           # pause
        ]
        with patch("builtins.input", side_effect=inputs):
            with redirect_stdout(output):
                app._create_activity(self.organizer)
        row = self.db.query_one(
            "SELECT allow_waitlist FROM activity_session ORDER BY id DESC LIMIT 1"
        )
        self.assertEqual(row["allow_waitlist"], 0)

    def test_location_only_modification_does_not_require_session_times(self) -> None:
        activity = self.make_activity()
        app = ConsoleApp(self.s)
        output = io.StringIO()
        # 选项 3 → 只填地点 → 不改场次时间 → pause
        with patch("builtins.input", side_effect=["3", "新地点", "n", ""]):
            with redirect_stdout(output):
                app._manage_activity(self.organizer, activity)
        row = self.db.query_one(
            "SELECT payload FROM review_application "
            "WHERE activity_id = ? AND type = 'MODIFY' "
            "ORDER BY id DESC LIMIT 1",
            (activity.id,),
        )
        self.assertIsNotNone(row)
        payload = json.loads(row["payload"])
        self.assertEqual(payload["location"], "新地点")
        self.assertNotIn("sessions", payload)

    def test_audit_filters_by_operator(self) -> None:
        self.make_activity()
        app = ConsoleApp(self.s)
        output = io.StringIO()
        inputs = ["", "", str(self.organizer.id), "", "", ""]
        with patch("builtins.input", side_effect=inputs):
            with redirect_stdout(output):
                app._audit(self.admin)
        text = output.getvalue()
        self.assertIn("ACTIVITY_CREATED", text)
        # 管理员审核留痕的操作人是管理员，不应出现在组织者筛选结果里。
        self.assertNotIn("PUBLISH_APPROVED", text)

    def test_no_seed_empty_db_creates_admin(self) -> None:
        path = Path(self.temp_dir.name) / "empty.db"
        with patch.object(ConsoleApp, "run", return_value=None):
            self.assertEqual(main(["--no-seed", "--db", str(path)]), 0)
        db = Database(path)
        try:
            row = db.query_one(
                "SELECT role FROM account WHERE phone = '13800000000'"
            )
            self.assertIsNotNone(row)
            self.assertEqual(row["role"], "ADMIN")
        finally:
            db.close()

    def test_reset_removes_wal_and_shm(self) -> None:
        path = Path(self.temp_dir.name) / "reset.db"
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").write_text("stale", encoding="utf-8")
        with patch.object(ConsoleApp, "run", return_value=None):
            self.assertEqual(
                main(["--reset", "--no-seed", "--db", str(path)]), 0
            )
        self.assertTrue(path.exists())
        self.assertFalse(Path(f"{path}-wal").exists())
        self.assertFalse(Path(f"{path}-shm").exists())

    def test_my_tickets_has_waitlist_category(self) -> None:
        activity = self.make_activity(normal_capacity=1)
        self.register(self.people[0], activity)
        self.enqueue(self.people[1], activity)
        app = ConsoleApp(self.s)
        output = io.StringIO()
        with patch("builtins.input", side_effect=["6", "0"]):
            with redirect_stdout(output):
                app._my_tickets(self.people[1])
        text = output.getvalue()
        self.assertIn("我的票 · 候补中", text)
        self.assertIn("测试活动", text)


if __name__ == "__main__":
    unittest.main()

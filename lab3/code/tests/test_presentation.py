"""表现层入口的回归测试：开售后改价入口、我的票候补分类。"""
# pylint: disable=missing-function-docstring,protected-access

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from unittest.mock import patch

from ticketing.presentation.cli import ConsoleApp

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

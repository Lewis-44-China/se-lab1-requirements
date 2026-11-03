"""测试公共夹具：临时数据库、固定时钟、常用账号与活动。"""

from __future__ import annotations

# pylint: disable=consider-using-with

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from ticketing.activities import ActivityDraft, SessionDraft, TicketDraft
from ticketing.clock import ManualClock
from ticketing.container import build_services
from ticketing.db import Database
from ticketing.models import Role, TicketKind
from ticketing.security import new_request_id

BASE_TIME = datetime(2026, 11, 1, 12, 0, 0)


class ServiceTestCase(unittest.TestCase):
    """每个测试独立数据库，互不影响。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = Database(self.db_path)
        self.db.initialize()
        self.clock = ManualClock(BASE_TIME)
        self.s = build_services(self.db, self.clock)
        self.admin = self.s.auth.bootstrap_admin(
            "13800000000", "Admin@123", "管理员"
        )
        self.inspector = self.s.auth.create_inspector(
            self.admin, "13900000000", "Inspect@123", "检票员"
        )
        self.organizer = self.s.auth.register(
            "13700000000", "Org@123", "组织者", Role.ORGANIZER
        )
        self.people = [
            self.s.auth.register(
                f"1360000000{i}", "Pass@123", f"参与者{i}", Role.PARTICIPANT
            )
            for i in range(1, 5)
        ]

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def make_activity(
        self,
        name: str = "测试活动",
        *,
        sale_start: datetime | None = None,
        sale_end: datetime | None = None,
        refund_deadline: datetime | None = None,
        session_start: datetime | None = None,
        session_end: datetime | None = None,
        checkin_open: datetime | None = None,
        vip_capacity: int = 2,
        normal_capacity: int = 1,
        publish: bool = True,
        allow_waitlist: bool = True,
    ):
        """创建一个活动，默认走完发布审核。"""
        now = self.clock.now()
        sale_start = sale_start or now - timedelta(days=1)
        sale_end = sale_end or now + timedelta(days=1)
        refund_deadline = refund_deadline or now + timedelta(hours=20)
        session_start = session_start or now + timedelta(days=2)
        session_end = session_end or session_start + timedelta(hours=3)
        checkin_open = checkin_open or session_start - timedelta(hours=1)
        draft = ActivityDraft(
            name=name,
            description="测试活动描述",
            location="测试地点",
            estimated_participants=100,
            sale_start=sale_start,
            sale_end=sale_end,
            refund_deadline=refund_deadline,
            sessions=[
                SessionDraft(
                    start_time=session_start,
                    end_time=session_end,
                    checkin_open_time=checkin_open,
                    allow_waitlist=allow_waitlist,
                    session_no="S1",
                    tickets=[
                        TicketDraft(TicketKind.VIP, 10000, vip_capacity),
                        TicketDraft(TicketKind.NORMAL, 5000, normal_capacity),
                    ],
                )
            ],
        )
        activity = self.s.activities.create_activity(self.organizer, draft)
        if publish:
            review = self.s.activities.submit_for_review(
                self.organizer, activity.id
            )
            self.s.admin.review(self.admin, review.id, True, "通过")
            self.s.admin.assign_inspector(
                self.admin, self.inspector.id, activity.id
            )
            activity = self.s.activities.get_activity(activity.id)
        return activity

    def session_id(self, activity) -> int:
        """活动第一个场次的 id。"""
        return self.s.activities.get_sessions(activity.id)[0].id

    def register(
        self,
        participant,
        activity,
        kind: TicketKind = TicketKind.NORMAL,
        request_id: str | None = None,
        session_id: int | None = None,
    ):
        """帮某参与者报名。"""
        return self.s.registrations.register(
            participant,
            session_id or self.session_id(activity),
            kind,
            request_id or new_request_id("TEST"),
            participant.name,
            participant.phone,
        )

    def enqueue(
        self,
        participant,
        activity,
        kind: TicketKind = TicketKind.NORMAL,
        request_id: str | None = None,
    ):
        """帮某参与者加入候补。"""
        return self.s.waitlist.enqueue(
            participant,
            self.session_id(activity),
            kind,
            request_id or new_request_id("TEST"),
            participant.name,
            participant.phone,
        )

    def registration_id(self, participant, activity) -> int:
        """取某账号在某活动的报名 id。"""
        row = self.db.query_one(
            """
            SELECT id FROM registration
             WHERE account_id = ? AND activity_id = ?
             ORDER BY id DESC LIMIT 1
            """,
            (participant.id, activity.id),
        )
        if row is None:
            raise AssertionError("报名记录不存在")
        return int(row["id"])

    def ticket(self, activity, kind: TicketKind = TicketKind.NORMAL):
        """取活动第一个场次的指定票种。"""
        tickets = self.s.tickets.list_for_session(self.session_id(activity))
        return next(item for item in tickets if item.kind is kind)

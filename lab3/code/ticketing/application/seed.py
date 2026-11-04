"""演示数据。

用 ManualClock 在不同时间点调用真实服务，保证演示数据的状态、名额、
审计和通知都与业务规则一致，而不是直接往表里塞“假数据”。
运行：python3 -m ticketing.application.seed  （或 python3 main.py 首次启动自动生成）
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ticketing.domain.activities import ActivityDraft, SessionDraft, TicketDraft
from ticketing.infrastructure.clock import ManualClock
from ticketing.container import build_services
from ticketing.infrastructure.db import Database
from ticketing.domain.models import Role, TicketKind
from ticketing.infrastructure.security import new_request_id


def seed_demo(db: Database, clock: ManualClock | None = None) -> bool:
    """若数据库为空则生成演示数据；返回是否实际生成。"""
    if db.query_one("SELECT 1 FROM account LIMIT 1") is not None:
        return False
    clock = clock or ManualClock()
    services = build_services(db, clock)
    now = clock.now()

    admin = services.auth.bootstrap_admin(
        "13800000000", "Admin@123", "平台管理员"
    )
    inspector = services.auth.create_inspector(
        admin, "13900000000", "Inspect@123", "检票员小张"
    )
    organizer = services.auth.register(
        "13700000000", "Org@123", "组织者李明", Role.ORGANIZER
    )
    people = [
        services.auth.register(
            f"1360000000{i}", "Pass@123", name, Role.PARTICIPANT
        )
        for i, name in enumerate(
            ["参与者王芳", "参与者赵强", "参与者陈晨", "参与者刘洋"], start=1
        )
    ]
    p1, p2, p3, p4 = people

    # 活动一：已公开、售票中；普通票容量 1，用来演示候补递补
    clock.set(now - timedelta(days=1))
    act1 = _create_and_publish(
        services,
        organizer,
        admin,
        name="春日音乐会",
        description="室内小型音乐会，VIP 含前排座位。",
        location="大学生活动中心 1 号厅",
        estimated_participants=200,
        sale_start=now - timedelta(days=1),
        sale_end=now + timedelta(days=1),
        refund_deadline=now + timedelta(hours=20),
        session_start=now + timedelta(days=2),
        checkin_open=now + timedelta(days=2) - timedelta(hours=1),
        tickets=[
            TicketDraft(TicketKind.VIP, 19900, 2),
            TicketDraft(TicketKind.NORMAL, 9900, 1),
        ],
    )
    services.admin.assign_inspector(admin, inspector.id, act1.id)
    clock.set(now)
    services.registrations.register(
        p1, _session_id(services, act1.id), TicketKind.NORMAL,
        new_request_id("SEED"), p1.name, p1.phone,
    )
    services.waitlist.enqueue(
        p2, _session_id(services, act1.id), TicketKind.NORMAL,
        new_request_id("SEED"), p2.name, p2.phone,
    )
    services.registrations.register(
        p3, _session_id(services, act1.id), TicketKind.VIP,
        new_request_id("SEED"), p3.name, p3.phone,
    )

    # 活动二：进行中，检票开放；p3 已检票，p4 待检票
    clock.set(now - timedelta(days=3))
    act2 = _create_and_publish(
        services,
        organizer,
        admin,
        name="AI 应用讲座",
        description="面向本科生的大模型应用开发讲座。",
        location="图书馆报告厅",
        estimated_participants=120,
        sale_start=now - timedelta(days=3),
        sale_end=now - timedelta(hours=2),
        refund_deadline=now - timedelta(minutes=90),
        session_start=now - timedelta(hours=1),
        checkin_open=now - timedelta(hours=2),
        tickets=[
            TicketDraft(TicketKind.VIP, 15900, 2),
            TicketDraft(TicketKind.NORMAL, 8900, 2),
        ],
    )
    services.admin.assign_inspector(admin, inspector.id, act2.id)
    clock.set(now - timedelta(hours=2, minutes=30))
    services.registrations.register(
        p3, _session_id(services, act2.id), TicketKind.VIP,
        new_request_id("SEED"), p3.name, p3.phone,
    )
    services.registrations.register(
        p4, _session_id(services, act2.id), TicketKind.NORMAL,
        new_request_id("SEED"), p4.name, p4.phone,
    )
    clock.set(now - timedelta(hours=1, minutes=30))
    request = services.checkin.request_checkin(
        p3, _registration_id(services, p3.id, act2.id)
    )
    services.checkin.process(inspector, request.id, passed=True)

    # 活动三：已结束，用来演示统计（出席率/退票率）
    clock.set(now - timedelta(days=10))
    act3 = _create_and_publish(
        services,
        organizer,
        admin,
        name="秋季摄影展",
        description="校园摄影作品展。",
        location="艺术楼展厅",
        estimated_participants=80,
        sale_start=now - timedelta(days=10),
        sale_end=now - timedelta(days=4),
        refund_deadline=now - timedelta(days=3, hours=12),
        session_start=now - timedelta(days=2),
        checkin_open=now - timedelta(days=2, hours=1),
        tickets=[
            TicketDraft(TicketKind.VIP, 12900, 3),
            TicketDraft(TicketKind.NORMAL, 6900, 3),
        ],
    )
    services.admin.assign_inspector(admin, inspector.id, act3.id)
    clock.set(now - timedelta(days=5))
    for person, kind in (
        (p1, TicketKind.VIP),
        (p2, TicketKind.NORMAL),
        (p3, TicketKind.NORMAL),
        (p4, TicketKind.NORMAL),
    ):
        services.registrations.register(
            person, _session_id(services, act3.id), kind,
            new_request_id("SEED"), person.name, person.phone,
        )
    clock.set(now - timedelta(days=4, hours=12))
    services.refunds.refund_by_participant(
        p4, _registration_id(services, p4.id, act3.id)
    )
    clock.set(now - timedelta(days=2) + timedelta(hours=1))
    for person in (p1, p3):
        request = services.checkin.request_checkin(
            person, _registration_id(services, person.id, act3.id)
        )
        services.checkin.process(inspector, request.id, passed=True)

    # 活动四：组织者的草稿，演示创建向导与提交审核
    clock.set(now)
    _create_draft(
        services,
        organizer,
        name="周末戏剧工作坊",
        description="面向零基础的表演体验课（草稿，尚未提交审核）。",
        location="文科楼 B203",
        estimated_participants=30,
        sale_start=now + timedelta(days=1),
        sale_end=now + timedelta(days=3),
        refund_deadline=now + timedelta(days=2, hours=12),
        session_start=now + timedelta(days=4),
        checkin_open=now + timedelta(days=4) - timedelta(hours=1),
        tickets=[
            TicketDraft(TicketKind.VIP, 9900, 1),
            TicketDraft(TicketKind.NORMAL, 4900, 2),
        ],
    )

    # 活动二的一条待处理举报，供管理员演示
    services.reports.submit_report(p2, act2.id, "活动信息与实际不符")

    clock.set(now)
    services.scheduler.tick()
    return True


def _create_and_publish(
    services,
    organizer,
    admin,
    *,
    name: str,
    description: str,
    location: str,
    estimated_participants: int,
    sale_start: datetime,
    sale_end: datetime,
    waitlist_deadline: datetime | None = None,
    refund_deadline: datetime,
    session_start: datetime,
    checkin_open: datetime,
    tickets: list[TicketDraft],
):
    """创建活动并走完发布审核。"""
    activity = _create_draft(
        services,
        organizer,
        name=name,
        description=description,
        location=location,
        estimated_participants=estimated_participants,
        sale_start=sale_start,
        sale_end=sale_end,
        waitlist_deadline=waitlist_deadline,
        refund_deadline=refund_deadline,
        session_start=session_start,
        checkin_open=checkin_open,
        tickets=tickets,
    )
    review = services.activities.submit_for_review(organizer, activity.id)
    services.admin.review(admin, review.id, approve=True, comment="演示数据通过")
    return services.activities.get_activity(activity.id)


def _create_draft(
    services,
    organizer,
    *,
    name: str,
    description: str,
    location: str,
    estimated_participants: int,
    sale_start: datetime,
    sale_end: datetime,
    waitlist_deadline: datetime | None = None,
    refund_deadline: datetime,
    session_start: datetime,
    checkin_open: datetime,
    tickets: list[TicketDraft],
):
    """创建草稿活动（单个场次）。"""
    draft = ActivityDraft(
        name=name,
        description=description,
        location=location,
        estimated_participants=estimated_participants,
        sale_start=sale_start,
        sale_end=sale_end,
        waitlist_deadline=waitlist_deadline or sale_end,
        refund_deadline=refund_deadline,
        sessions=[
            SessionDraft(
                start_time=session_start,
                end_time=session_start + timedelta(hours=3),
                checkin_open_time=checkin_open,
                allow_waitlist=True,
                session_no="S1",
                tickets=tickets,
            )
        ],
    )
    return services.activities.create_activity(organizer, draft)


def _session_id(services, activity_id: int) -> int:
    """取活动的第一个场次 id。"""
    return services.activities.get_sessions(activity_id)[0].id


def _registration_id(services, account_id: int, activity_id: int) -> int:
    """取某账号在某活动的报名记录 id（演示数据里每个活动只有一条）。"""
    row = services.db.query_one(
        """
        SELECT id FROM registration
         WHERE account_id = ? AND activity_id = ?
         ORDER BY id DESC LIMIT 1
        """,
        (account_id, activity_id),
    )
    if row is None:
        raise RuntimeError("演示数据缺少报名记录")
    return int(row["id"])


def main() -> None:
    """独立运行 seed。"""
    db = Database("ticketing.db")
    db.initialize()
    created = seed_demo(db, ManualClock())
    print("演示数据已生成" if created else "数据库已有账号，跳过演示数据")
    db.close()


if __name__ == "__main__":
    main()

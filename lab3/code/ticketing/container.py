"""服务容器：集中装配各模块，避免 CLI 和测试重复写依赖注入。"""

from __future__ import annotations

from dataclasses import dataclass

from .activities import ActivityService
from .admin import AdminService
from .audit import AuditService
from .auth import AuthService
from .checkin import CheckinService
from .clock import Clock
from .db import Database
from .notifications import NotificationService
from .promotion import PromotionService
from .queries import QueryService
from .refunds import RefundService
from .registrations import RegistrationService
from .reports import ReportService
from .scheduler import Scheduler
from .tickets import TicketService
from .waitlist import WaitlistService


@dataclass(slots=True)
class Services:
    """所有服务实例。"""

    db: Database
    clock: Clock
    audit: AuditService
    notifications: NotificationService
    tickets: TicketService
    auth: AuthService
    activities: ActivityService
    registrations: RegistrationService
    waitlist: WaitlistService
    promotion: PromotionService
    refunds: RefundService
    checkin: CheckinService
    queries: QueryService
    reports: ReportService
    admin: AdminService
    scheduler: Scheduler


def build_services(db: Database, clock: Clock) -> Services:
    """按依赖顺序装配服务。"""
    audit = AuditService(db, clock)
    notifications = NotificationService(db, clock)
    tickets = TicketService(db)
    auth = AuthService(db, clock, audit)
    activities = ActivityService(db, clock, audit, tickets, notifications)
    registrations = RegistrationService(db, clock, audit, tickets)
    waitlist = WaitlistService(db, clock, audit, tickets, notifications)
    promotion = PromotionService(db, clock, audit, tickets, waitlist)
    refunds = RefundService(
        db, clock, audit, tickets, notifications, waitlist
    )
    checkin = CheckinService(db, clock, audit)
    queries = QueryService(db, clock)
    reports = ReportService(db, clock, audit)
    admin = AdminService(
        db,
        clock,
        audit,
        auth,
        activities,
        refunds,
        waitlist,
        notifications,
        queries,
    )
    scheduler = Scheduler(
        db, clock, audit, activities, waitlist, promotion
    )
    return Services(
        db=db,
        clock=clock,
        audit=audit,
        notifications=notifications,
        tickets=tickets,
        auth=auth,
        activities=activities,
        registrations=registrations,
        waitlist=waitlist,
        promotion=promotion,
        refunds=refunds,
        checkin=checkin,
        queries=queries,
        reports=reports,
        admin=admin,
        scheduler=scheduler,
    )

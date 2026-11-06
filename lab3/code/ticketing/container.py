"""服务容器：集中装配各模块，避免 CLI 和测试重复写依赖注入。"""

# 审查通过：组合根按依赖顺序手工装配，无循环依赖；新增服务时需要在 build_services 接线。

from __future__ import annotations

from dataclasses import dataclass

from ticketing.domain.activities import ActivityService
from ticketing.application.admin import AdminService
from ticketing.common.audit import AuditService
from ticketing.domain.auth import AuthService
from ticketing.domain.checkin import CheckinService
from ticketing.infrastructure.clock import Clock
from ticketing.infrastructure.db import Database
from ticketing.common.notifications import NotificationService
from ticketing.application.promotion import PromotionService
from ticketing.domain.queries import QueryService
from ticketing.domain.refunds import RefundService
from ticketing.domain.registrations import RegistrationService
from ticketing.domain.reports import ReportService
from ticketing.application.scheduler import Scheduler
from ticketing.domain.tickets import TicketService
from ticketing.domain.waitlist import WaitlistService

# 第二轮审查 Q69：container 只做装配，不绕过服务层权限；每个服务仍在校验
# require_role / require_owner / require_active。装配顺序无循环依赖，所有
# 服务共享同一个 db / clock / audit，事务边界留在各服务内部。

@dataclass(slots=True)
# 所有服务的只读聚合对象，CLI/seed/测试共用。
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


# 装配顺序：基础设施（audit/notifications/tickets）→ 领域服务 → 编排（admin/scheduler）。
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

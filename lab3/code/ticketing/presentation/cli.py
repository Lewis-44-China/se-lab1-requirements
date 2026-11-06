"""四角色终端界面。

界面只负责收集输入、调用服务、展示结果；所有业务规则在服务层，
所以即使命令行绕过了按钮显隐，服务层仍会拒绝越权操作。
"""

# 审查通过：四角色菜单与服务层权限边界一致；CLI 只收集输入/展示，写操作由服务层再校验。
# 覆盖登录注册、活动浏览/报名/候补、我的票/退票、检票请求、举报、通知、审计；
# 组织者活动管理与名单统计；检票员工作台；管理员审核/举报/封禁/分配/查询。

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from ticketing.domain.activities import ActivityDraft, SessionDraft, TicketDraft
from ticketing.infrastructure.clock import ManualClock, SystemClock, format_dt, parse_dt
from ticketing.container import Services, build_services
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import AppError, CapacityFull

# 第二轮审查（2026-11-05）：Q42 开售后隐藏/拒绝票价容量修改；Q70 我的票增加
# “候补中”分类；Q71 核对四角色菜单与服务层权限边界。
from ticketing.domain.models import (
    Account,
    Activity,
    ActivityStatus,
    RegistrationStatus,
    Role,
    TicketKind,
    WaitlistStatus,
)
from ticketing.presentation.render import (
    ask,
    ask_int,
    ask_money,
    ask_optional,
    ask_time,
    ask_yes_no,
    error,
    label,
    money,
    print_table,
    section,
    success,
    warn,
)
from ticketing.infrastructure.security import mask_phone, new_request_id
from ticketing.application.seed import seed_demo

DEMO_HINT = """
演示账号（首次启动自动创建）：
  管理员    13800000000 / Admin@123
  检票员    13900000000 / Inspect@123
  组织者    13700000000 / Org@123
  参与者1   13600000001 / Pass@123
  参与者2   13600000002 / Pass@123
"""


class ConsoleApp:
    """命令行应用。"""

    def __init__(self, services: Services) -> None:
        self.services = services

    def run(self) -> None:
        """主循环：登录/注册/退出。"""
        try:
            while True:
                print("\n" + "=" * 62)
                print("  活动票务与报名系统（实验三实现）")
                print("=" * 62)
                print("  1. 登录")
                print("  2. 注册参与者")
                print("  3. 注册组织者")
                print("  0. 退出")
                choice = input("请选择：").strip()
                if choice == "1":
                    account = self._login()
                    if account is not None:
                        self._role_menu(account)
                elif choice == "2":
                    self._register(Role.PARTICIPANT)
                elif choice == "3":
                    self._register(Role.ORGANIZER)
                elif choice == "0":
                    print("再见。")
                    return
                else:
                    warn("无效选择")
        except (KeyboardInterrupt, EOFError):
            print("\n已退出。")

    # ---------- 登录注册 ----------

    def _login(self) -> Account | None:
        phone = ask("手机号")
        password = getpass.getpass("密码：")
        try:
            account = self.services.auth.login(phone, password)
        except AppError as exc:
            error(exc.message)
            return None
        success(f"欢迎，{account.name}（{label(account.role)}）")
        if account.is_banned:
            warn("该账号已被封禁：仍可查看已有票，但不能新增购票或候补。")
        return account

    def _register(self, role: Role) -> None:
        phone = ask("手机号")
        name = ask("姓名")
        password = getpass.getpass("密码（至少 6 位）：")
        confirm = getpass.getpass("确认密码：")
        if password != confirm:
            error("两次密码不一致")
            return
        try:
            account = self.services.auth.register(phone, password, name, role)
        except AppError as exc:
            error(exc.message)
            return
        success(f"注册成功：{account.name}（{label(account.role)}），请登录。")

    def _role_menu(self, account: Account) -> None:
        """按角色进入不同菜单。"""
        while True:
            try:
                self.services.scheduler.tick()
            except AppError as exc:
                warn(f"时间任务执行失败：{exc.message}")
            if account.role is Role.PARTICIPANT:
                if not self._participant_menu(account):
                    return
            elif account.role is Role.ORGANIZER:
                if not self._organizer_menu(account):
                    return
            elif account.role is Role.INSPECTOR:
                if not self._inspector_menu(account):
                    return
            elif account.role is Role.ADMIN:
                if not self._admin_menu(account):
                    return
            else:
                error("未知角色")
                return

    # ---------- 参与者 ----------
    # 审查通过：我的票已按 UI-04 增加筛选（全部/待检票/已检票/已结束/已取消/已退票）；
    # 参与者审计只显示本人报名/候补/检票/举报及自己账号相关留痕（REQ-041）。

    def _participant_menu(self, account: Account) -> bool:
        section(f"参与者菜单 · {account.name}")
        print("  1. 浏览/查询活动并报名")
        print("  2. 我的票与退票")
        print("  3. 我的候补与取消")
        print("  4. 发起检票请求")
        print("  5. 举报活动")
        print("  6. 我的通知")
        print("  7. 我的审计记录")
        print("  8. 账号信息")
        print("  0. 退出登录")
        choice = input("请选择：").strip()
        try:
            if choice == "1":
                self._browse_and_register(account)
            elif choice == "2":
                self._my_tickets(account)
            elif choice == "3":
                self._my_waitlists(account)
            elif choice == "4":
                self._request_checkin(account)
            elif choice == "5":
                self._submit_report(account)
            elif choice == "6":
                self._notifications(account)
            elif choice == "7":
                self._audit(account)
            elif choice == "8":
                self._account_info(account)
            elif choice == "0":
                return False
            else:
                warn("无效选择")
        except AppError as exc:
            error(exc.message)
        except ValueError as exc:
            error(str(exc))
        return True

    def _browse_and_register(self, account: Account) -> None:
        keyword = ask_optional("关键词（名称/描述/地点）")
        date_from = self._optional_time("最早场次开始时间")
        date_to = self._optional_time("最晚场次开始时间")
        status = ask_optional("活动状态 PUBLISHED/ONGOING/ENDED/CANCELLED")
        kind = self._optional_kind()
        views = self.services.queries.browse_activities(
            account,
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
            status=status or None,
            kind=kind,
        )
        section("活动列表")
        print_table(
            ["ID", "活动", "地点", "首场", "价格", "余票/容量", "状态"],
            [
                [
                    view.activity.id,
                    view.activity.name,
                    view.activity.location,
                    view.first_session,
                    f"{money(view.min_price_cents)}~{money(view.max_price_cents)}",
                    f"{view.remaining}/{view.capacity}",
                    label(view.activity.status),
                ]
                for view in views
            ],
        )
        if not views:
            return
        activity_id = ask_int("输入活动 ID 查看详情（0 返回）", 0)
        if activity_id == 0:
            return
        detail = self.services.queries.activity_detail(account, activity_id)
        self._print_detail(detail)
        action = input("1. 报名  2. 候补  0. 返回：").strip()
        if action not in ("1", "2"):
            return
        session_id = ask_int("场次 ID", 1)
        kind = self._choose_kind()
        ticket = self._find_ticket(detail, session_id, kind)
        if ticket is None:
            error("该场次没有此票种")
            return
        name = ask("购票人姓名", account.name)
        phone = ask("手机号", account.phone)
        if action == "1":
            if ticket.remaining <= 0:
                warn("该票种已售罄")
                if ask_yes_no("是否加入候补？"):
                    self._enqueue(account, session_id, kind, name, phone, ticket.price_cents)
                return
            if not ask_yes_no(f"确认支付 {money(ticket.price_cents)} 并报名？", True):
                return
            try:
                registration = self.services.registrations.register(
                    account,
                    session_id,
                    kind,
                    new_request_id("CLI"),
                    name,
                    phone,
                )
            except CapacityFull as exc:
                warn(exc.message)
                if ask_yes_no("是否加入候补？"):
                    self._enqueue(
                        account, session_id, kind, name, phone, ticket.price_cents
                    )
                return
            success(
                f"报名成功，报名编号 {registration.id}，状态：{label(registration.status)}"
            )
        else:
            self._enqueue(account, session_id, kind, name, phone, ticket.price_cents)
        self._pause()

    def _enqueue(
        self, account, session_id, kind, name, phone, price_cents
    ) -> None:
        """加入候补。"""
        if not ask_yes_no(f"确认支付 {money(price_cents)} 并加入候补？", True):
            return
        record = self.services.waitlist.enqueue(
            account, session_id, kind, new_request_id("CLI"), name, phone
        )
        success(f"已加入候补，候补编号 {record.id}；递补成功会自动生成报名记录。")

    def _my_tickets(self, account: Account) -> None:
        views = self.services.queries.my_registrations(account)
        filters = {
            "1": None,
            "2": {RegistrationStatus.PURCHASED},
            "3": {RegistrationStatus.CHECKED_IN},
            "4": {RegistrationStatus.NORMAL_END, RegistrationStatus.NO_SHOW},
            "5": {
                RegistrationStatus.SELF_CANCELLED,
                RegistrationStatus.ACTIVITY_CANCELLED,
            },
        }
        # 第二轮审查 Q70：候补中作为“我的票”的并列分类；选择后复用
        # _my_waitlists 并只显示 WAITING 记录，可在这里直接取消候补。
        choice = input(
            "筛选：1.全部 2.待检票 3.已检票 4.已结束 5.已取消/已退票 "
            "6.候补中 0.返回："
        ).strip()
        if choice == "0":
            return
        if choice == "6":
            self._my_waitlists(account, only_waiting=True)
            return
        if choice not in filters:
            warn("无效选择")
            return
        allowed = filters[choice]
        if allowed is not None:
            views = [
                view for view in views if view.registration.status in allowed
            ]
        section("我的票")
        print_table(
            ["ID", "活动", "场次", "票种", "状态", "金额", "退款", "退票截止", "可退"],
            [
                [
                    view.registration.id,
                    view.activity_name,
                    view.session_no,
                    label(view.registration.ticket_kind),
                    label(view.registration.status),
                    money(view.price_cents),
                    money(view.registration.refund_amount_cents),
                    view.refund_deadline,
                    "是" if view.can_refund else "否",
                ]
                for view in views
            ],
        )
        if not views:
            return
        registration_id = ask_int("输入要退票的报名 ID（0 返回）", 0)
        if registration_id == 0:
            return
        target = next(
            (v for v in views if v.registration.id == registration_id), None
        )
        if target is None:
            error("报名记录不属于当前账号")
            return
        if not target.can_refund:
            error("该票当前不可退（已检票、已过退票截止或已是终态）")
            return
        if not ask_yes_no("确认退票？退款金额将等于支付金额。", False):
            return
        registration = self.services.refunds.refund_by_participant(
            account, registration_id
        )
        success(
            f"退票成功，退款 {money(registration.refund_amount_cents)}，状态：{label(registration.status)}"
        )
        self._pause()

    def _my_waitlists(self, account: Account, only_waiting: bool = False) -> None:
        views = self.services.queries.my_waitlists(account)
        if only_waiting:
            views = [
                view
                for view in views
                if view.record.status is WaitlistStatus.WAITING
            ]
        section("我的票 · 候补中" if only_waiting else "我的候补")
        print_table(
            ["ID", "活动", "场次", "票种", "金额", "入队时间", "状态"],
            [
                [
                    view.record.id,
                    view.activity_name,
                    view.session_no,
                    label(view.ticket_kind),
                    money(view.price_cents),
                    view.record.join_time,
                    label(view.record.status),
                ]
                for view in views
            ],
        )
        if not views:
            return
        record_id = ask_int("输入要取消的候补记录 ID（0 返回）", 0)
        if record_id == 0:
            return
        target = next((v for v in views if v.record.id == record_id), None)
        if target is None:
            error("候补记录不属于当前账号")
            return
        if target.record.status is not WaitlistStatus.WAITING:
            error("只有“候补中”的记录可以取消")
            return
        if not ask_yes_no("确认取消候补？将全额退款。", False):
            return
        record = self.services.waitlist.cancel(account, record_id)
        success(f"已取消候补，退款 {money(record.refund_amount_cents)}")
        self._pause()

    def _request_checkin(self, account: Account) -> None:
        views = [
            view
            for view in self.services.queries.my_registrations(account)
            if view.registration.status is RegistrationStatus.PURCHASED
        ]
        section("可发起检票的票")
        print_table(
            ["报名 ID", "活动", "场次", "票种", "场次时间", "状态"],
            [
                [
                    view.registration.id,
                    view.activity_name,
                    view.session_no,
                    label(view.registration.ticket_kind),
                    view.start_time,
                    label(view.registration.status),
                ]
                for view in views
            ],
        )
        if not views:
            return
        registration_id = ask_int("输入报名 ID（0 返回）", 0)
        if registration_id == 0:
            return
        request = self.services.checkin.request_checkin(account, registration_id)
        success(f"检票请求已提交，请求编号 {request.request_no}，请等待检票员处理。")
        self._pause()

    def _submit_report(self, account: Account) -> None:
        activity_id = ask_int("要举报的活动 ID", 1)
        reason = ask("举报理由")
        report = self.services.reports.submit_report(account, activity_id, reason)
        success(f"举报已提交，编号 {report.id}，管理员会尽快处理。")
        self._pause()

    # ---------- 组织者 ----------

    def _organizer_menu(self, account: Account) -> bool:
        section(f"组织者菜单 · {account.name}")
        print("  1. 我的活动")
        print("  2. 创建活动")
        print("  3. 名单与统计")
        print("  4. 我的通知")
        print("  5. 我的审计记录")
        print("  6. 账号信息")
        print("  0. 退出登录")
        choice = input("请选择：").strip()
        try:
            if choice == "1":
                self._my_activities(account)
            elif choice == "2":
                self._create_activity(account)
            elif choice == "3":
                self._roster_statistics(account)
            elif choice == "4":
                self._notifications(account)
            elif choice == "5":
                self._audit(account)
            elif choice == "6":
                self._account_info(account)
            elif choice == "0":
                return False
            else:
                warn("无效选择")
        except AppError as exc:
            error(exc.message)
        except ValueError as exc:
            error(str(exc))
        return True

    def _my_activities(self, account: Account) -> None:
        activities = self.services.activities.list_by_organizer(account.id)
        section("我的活动")
        print_table(
            ["ID", "活动", "状态", "售票窗口", "退票截止"],
            [
                [
                    item.id,
                    item.name,
                    label(item.status),
                    f"{item.sale_start} ~ {item.sale_end}",
                    item.refund_deadline,
                ]
                for item in activities
            ],
        )
        if not activities:
            return
        activity_id = ask_int("输入活动 ID 进行管理（0 返回）", 0)
        if activity_id == 0:
            return
        activity = next((a for a in activities if a.id == activity_id), None)
        if activity is None:
            error("活动不属于当前组织者")
            return
        self._manage_activity(account, activity)

    def _create_activity(self, account: Account) -> None:
        section("创建活动向导")
        name = ask("活动名称")
        description = ask("活动描述")
        location = ask("活动地点")
        estimated = ask_int("参与人数估计", 1)
        sale_start = ask_time("售票开始", "+0d")
        sale_end = ask_time("售票截止", "+3d")
        waitlist_deadline = ask_time("候补截止", "+3d")
        refund_deadline = ask_time("退票截止", "+2d")
        session_start = ask_time("场次开始", "+4d")
        checkin_open = ask_time("检票开放", "+3d")
        print("\n场次默认 3 小时；票种可只设置一种。")
        tickets: list[TicketDraft] = []
        # 第二轮审查 Q72：票种价格/容量由组织者在创建时填写（REQ-008）；
        # 创建后开售前可申请修改，开售后禁止改价/容量。
        if ask_yes_no("设置 VIP 票？", True):
            price = ask_money("VIP 票价（元）", "199")
            capacity = ask_int("VIP 容量", 1)
            tickets.append(TicketDraft(TicketKind.VIP, price, capacity))
        if ask_yes_no("设置普通票？", True):
            price = ask_money("普通票价（元）", "99")
            capacity = ask_int("普通票容量", 1)
            tickets.append(TicketDraft(TicketKind.NORMAL, price, capacity))
        if not tickets:
            error("至少设置一种票")
            return
        session = SessionDraft(
            start_time=session_start,
            end_time=session_start + timedelta(hours=3),
            checkin_open_time=checkin_open,
            allow_waitlist=True,
            session_no="S1",
            tickets=tickets,
        )
        draft = ActivityDraft(
            name=name,
            description=description,
            location=location,
            estimated_participants=estimated,
            sale_start=sale_start,
            sale_end=sale_end,
            waitlist_deadline=waitlist_deadline,
            refund_deadline=refund_deadline,
            sessions=[session],
        )
        activity = self.services.activities.create_activity(account, draft)
        success(f"活动已创建为草稿，ID {activity.id}。")
        if ask_yes_no("现在提交发布审核？", True):
            review = self.services.activities.submit_for_review(account, activity.id)
            success(f"已提交审核，申请编号 {review.id}，等待管理员审批。")
        self._pause()

    def _manage_activity(self, account: Account, activity: Activity) -> None:
        # 第二轮审查 Q70/Q42：草稿全部直接生效；发布后表面信息直接生效，
        # 地点/场次时间/票价容量走审核；开售后票价容量入口置灰并拒绝。
        # 这里只是提前阻止，服务层仍会做最终校验（Q53）。
        detail = self.services.queries.activity_detail(account, activity.id)
        self._print_detail(detail)
        tickets_locked = (
            activity.status is not ActivityStatus.DRAFT
            and self.services.clock.now() >= parse_dt(activity.sale_start)
        )
        print("  1. 提交发布审核")
        print("  2. 修改表面信息（名称/描述/封面/标签，直接生效）")
        print("  3. 修改地点/场次时间（草稿直接生效，发布后需审核）")
        if tickets_locked:
            print("  4. 修改票价/容量（活动已开售，不可修改）")
        else:
            print("  4. 修改票价/容量（草稿直接生效，发布后开售前需审核）")
        print("  5. 申请取消活动（需管理员审批）")
        print("  6. 查看审核记录")
        print("  0. 返回")
        choice = input("请选择：").strip()
        if choice == "1":
            review = self.services.activities.submit_for_review(account, activity.id)
            success(f"已提交发布审核，申请编号 {review.id}")
        elif choice == "2":
            name = ask("活动名称", activity.name)
            description = ask("活动描述", activity.description)
            cover = ask("封面", activity.cover or "")
            tags = ask("标签", activity.tags or "")
            self.services.activities.modify_activity(
                account,
                activity.id,
                name=name,
                description=description,
                cover=cover,
                tags=tags,
            )
            success("表面信息已直接生效。")
        elif choice == "3":
            location = ask_optional("新地点（回车保持不变）")
            session_id = ask_int("要修改的场次 ID", 1)
            start = ask_time("新的场次开始时间", format_dt(datetime.now()))
            end = ask_time("新的场次结束时间", format_dt(datetime.now() + timedelta(hours=3)))
            checkin = ask_time("新的检票开放时间", format_dt(datetime.now()))
            review = self.services.activities.modify_activity(
                account,
                activity.id,
                location=location or None,
                session_updates=[
                    {
                        "session_id": session_id,
                        "start_time": start,
                        "end_time": end,
                        "checkin_open_time": checkin,
                    }
                ],
            )
            if review is not None:
                success(f"已提交修改审核，申请编号 {review.id}")
            else:
                success("修改已直接生效（草稿）。")
        elif choice == "4":
            if tickets_locked:
                warn("活动已开售，票价与容量不可修改")
            else:
                self._modify_tickets(account, activity, detail)
        elif choice == "5":
            reason = ask("取消原因")
            review = self.services.activities.request_cancel(
                account, activity.id, reason
            )
            success(f"已提交取消申请，申请编号 {review.id}，等待管理员审批。")
        elif choice == "6":
            self._show_reviews(activity)
        self._pause()

    def _modify_tickets(self, account: Account, activity: Activity, detail) -> None:
        """草稿或开售前修改票价/容量；发布后生成修改审核。"""
        print_table(
            ["票种 ID", "类型", "价格", "容量", "已占用"],
            [
                [
                    ticket.id,
                    label(ticket.kind),
                    money(ticket.price_cents),
                    ticket.capacity,
                    ticket.occupied,
                ]
                for tickets in detail.tickets.values()
                for ticket in tickets
            ],
        )
        ticket_id = ask_int("票种 ID", 1)
        price = ask_money("新票价（元）", "0")
        capacity = ask_int("新容量", 1)
        review = self.services.activities.modify_activity(
            account,
            activity.id,
            ticket_updates=[
                {
                    "ticket_type_id": ticket_id,
                    "price_cents": price,
                    "capacity": capacity,
                }
            ],
        )
        if review is not None:
            success(f"已提交修改审核，申请编号 {review.id}")
        else:
            success("修改已直接生效（草稿）。")

    # 审查通过：组织者可查看本活动的发布/修改/取消申请及审核结果。
    def _show_reviews(self, activity: Activity) -> None:
        reviews = self.services.activities.list_reviews_for_activity(activity.id)
        section("审核记录")
        print_table(
            ["申请 ID", "类型", "状态", "提交时间", "审核意见", "处理时间"],
            [
                [
                    item.id,
                    label(item.type),
                    label(item.status),
                    item.submitted_at,
                    item.comment or "-",
                    item.reviewed_at or "-",
                ]
                for item in reviews
            ],
        )

    # 审查通过：统计在全部场次结束后才开放；服务层返回 open=False 时只显示提示（REQ-030）。
    def _roster_statistics(self, account: Account) -> None:
        activities = self.services.activities.list_by_organizer(account.id)
        section("选择活动查看名单与统计")
        print_table(
            ["ID", "活动", "状态"],
            [[item.id, item.name, label(item.status)] for item in activities],
        )
        if not activities:
            return
        activity_id = ask_int("活动 ID（0 返回）", 0)
        if activity_id == 0:
            return
        stats = self.services.queries.activity_statistics(account, activity_id)
        section("统计")
        if not stats.open:
            warn(stats.message)
        else:
            rows = [stats.overall] + stats.per_session if stats.overall else stats.per_session
            print_table(
                ["口径", "报名人数", "出席人数", "退票人数", "出席率", "退票率"],
                [
                    [
                        row.label,
                        row.registered,
                        row.attended,
                        row.refunded,
                        f"{row.attendance_rate:.1f}%",
                        f"{row.refund_rate:.1f}%",
                    ]
                    for row in rows
                ],
            )
        roster = self.services.queries.organizer_roster(account, activity_id)
        section("报名名单（手机号遮挡）")
        print_table(
            ["报名 ID", "姓名", "手机号", "场次", "票种", "状态"],
            [
                [
                    item.registration_id,
                    item.buyer_name,
                    item.phone_masked,
                    item.session_no,
                    label(item.ticket_kind),
                    label(item.status),
                ]
                for item in roster
            ],
        )
        if roster and ask_yes_no("导出名单为 CSV（姓名/场次/票种，不含手机号）？", False):
            default_path = f"exports/活动{activity_id}_名单.csv"
            path = ask("导出路径", default_path)
            count = self.services.queries.export_roster_csv(
                account, activity_id, path
            )
            success(f"已导出 {count} 条记录到 {Path(path).resolve()}")
        self._pause()

    # ---------- 检票员 ----------

    def _inspector_menu(self, account: Account) -> bool:
        section(f"检票员菜单 · {account.name}")
        print("  1. 我负责的活动")
        print("  2. 待处理检票请求")
        print("  3. 我的通知")
        print("  4. 账号信息")
        print("  0. 退出登录")
        choice = input("请选择：").strip()
        try:
            if choice == "1":
                self._assigned_activities(account)
            elif choice == "2":
                self._process_requests(account)
            elif choice == "3":
                self._notifications(account)
            elif choice == "4":
                self._account_info(account)
            elif choice == "0":
                return False
            else:
                warn("无效选择")
        except AppError as exc:
            error(exc.message)
        except ValueError as exc:
            error(str(exc))
        return True

    def _assigned_activities(self, account: Account) -> None:
        activities = self.services.checkin.list_assigned_activities(account)
        section("我负责的活动")
        print_table(
            ["ID", "活动", "地点", "状态"],
            [
                [item.id, item.name, item.location, label(item.status)]
                for item in activities
            ],
        )
        self._pause()

    def _process_requests(self, account: Account) -> None:
        requests = self.services.checkin.list_pending_requests(account)
        section("待处理检票请求")
        print_table(
            ["请求 ID", "请求编号", "活动", "场次", "姓名", "手机号", "票种"],
            [
                [
                    item.request_id,
                    item.request_no,
                    item.activity_name,
                    item.session_no,
                    item.buyer_name,
                    mask_phone(item.buyer_phone),
                    label(item.ticket_kind),
                ]
                for item in requests
            ],
        )
        if not requests:
            return
        request_id = ask_int("请求 ID（0 返回）", 0)
        if request_id == 0:
            return
        action = input("1. 通过检票  2. 标记异常  0. 返回：").strip()
        if action == "1":
            request = self.services.checkin.process(account, request_id, True)
            success(f"检票通过，请求 {request.request_no} 已处理。")
        elif action == "2":
            request = self.services.checkin.process(account, request_id, False)
            success(f"已标记异常，请求 {request.request_no}；报名状态不变。")
        self._pause()

    # ---------- 管理员 ----------
    # 第二轮审查 Q71：四角色菜单覆盖 UI-01～09；菜单只是入口，真正的权限边界
    # 仍由服务层的 require_role/require_owner/require_active 保证，隐藏按钮不算安全边界。

    def _admin_menu(self, account: Account) -> bool:
        section(f"管理员菜单 · {account.name}")
        print("  1. 待审核申请")
        print("  2. 举报处理")
        print("  3. 账号管理（创建检票员/封禁/解封）")
        print("  4. 活动管理（取消/分配检票员）")
        print("  5. 报名查询与强制退票")
        print("  6. 平台概览")
        print("  7. 审计查询")
        print("  8. 我的通知")
        print("  0. 退出登录")
        choice = input("请选择：").strip()
        try:
            if choice == "1":
                self._review_queue(account)
            elif choice == "2":
                self._reports(account)
            elif choice == "3":
                self._accounts(account)
            elif choice == "4":
                self._admin_activities(account)
            elif choice == "5":
                self._admin_registrations(account)
            elif choice == "6":
                self._platform(account)
            elif choice == "7":
                self._audit(account)
            elif choice == "8":
                self._notifications(account)
            elif choice == "0":
                return False
            else:
                warn("无效选择")
        except AppError as exc:
            error(exc.message)
        except ValueError as exc:
            error(str(exc))
        return True

    def _review_queue(self, account: Account) -> None:
        reviews = self.services.admin.list_pending_reviews(account)
        section("待审核申请")
        print_table(
            ["ID", "类型", "活动 ID", "提交时间"],
            [
                [item.id, label(item.type), item.activity_id, item.submitted_at]
                for item in reviews
            ],
        )
        if not reviews:
            return
        review_id = ask_int("审核申请 ID（0 返回）", 0)
        if review_id == 0:
            return
        target = next((item for item in reviews if item.id == review_id), None)
        if target is None:
            error("审核申请不存在或已处理")
            return
        print(f"\n类型：{label(target.type)}；活动 ID：{target.activity_id}")
        print(f"申请内容：{target.payload}")
        approve = ask_yes_no("是否通过？", True)
        comment = ask("审核意见" if approve else "驳回原因", "" if approve else None)
        self.services.admin.review(account, review_id, approve, comment)
        success("审核已处理。")
        self._pause()

    def _reports(self, account: Account) -> None:
        reports = self.services.admin.list_reports(account, pending_only=True)
        section("待处理举报")
        print_table(
            ["ID", "活动 ID", "举报人", "理由", "提交时间"],
            [
                [item.id, item.activity_id, item.reporter_id, item.reason, item.created_at]
                for item in reports
            ],
        )
        if not reports:
            return
        report_id = ask_int("举报 ID（0 返回）", 0)
        if report_id == 0:
            return
        dismiss = not ask_yes_no("举报属实？", True)
        result = ask("处理结果")
        cancel_activity = False
        ban_organizer = False
        if not dismiss:
            cancel_activity = ask_yes_no("同时取消活动？", True)
            ban_organizer = ask_yes_no("同时封禁组织者？", False)
        self.services.admin.handle_report(
            account,
            report_id,
            dismiss=dismiss,
            result=result,
            cancel_activity=cancel_activity,
            ban_organizer=ban_organizer,
        )
        success("举报已处理。")
        self._pause()

    def _accounts(self, account: Account) -> None:
        section("账号管理")
        print("  1. 创建检票员")
        print("  2. 查看全部账号")
        print("  3. 封禁/解封")
        print("  0. 返回")
        choice = input("请选择：").strip()
        if choice == "1":
            phone = ask("检票员手机号")
            name = ask("检票员姓名")
            password = getpass.getpass("初始密码（至少 6 位）：")
            inspector = self.services.admin.create_inspector(
                account, phone, password, name
            )
            success(f"已创建检票员 {inspector.name}（ID {inspector.id}）")
        elif choice == "2":
            accounts = self.services.admin.list_accounts(account)
            print_table(
                ["ID", "手机号", "姓名", "角色", "状态"],
                [
                    [item.id, item.phone, item.name, label(item.role), label(item.status)]
                    for item in accounts
                ],
            )
        elif choice == "3":
            accounts = self.services.admin.list_accounts(account)
            print_table(
                ["ID", "手机号", "姓名", "角色", "状态"],
                [
                    [item.id, item.phone, item.name, label(item.role), label(item.status)]
                    for item in accounts
                ],
            )
            account_id = ask_int("账号 ID", 1)
            ban = ask_yes_no("封禁？（否=解封）", True)
            reason = ask("原因")
            self.services.admin.ban_account(account, account_id, reason, ban)
            success("账号状态已更新。")
        self._pause()

    def _admin_activities(self, account: Account) -> None:
        activities = self.services.admin.all_activities(account)
        section("全部活动")
        print_table(
            ["ID", "活动", "组织者 ID", "状态", "售票窗口"],
            [
                [
                    item.id,
                    item.name,
                    item.organizer_id,
                    label(item.status),
                    f"{item.sale_start} ~ {item.sale_end}",
                ]
                for item in activities
            ],
        )
        if not activities:
            return
        activity_id = ask_int("活动 ID（0 返回）", 0)
        if activity_id == 0:
            return
        action = input("1. 取消活动  2. 分配检票员  3. 查看详情  0. 返回：").strip()
        if action == "1":
            reason = ask("取消原因")
            count = self.services.refunds.cancel_activity(account, activity_id, reason)
            success(f"活动已取消，处理报名记录 {count} 条，候补记录已退款。")
        elif action == "2":
            inspectors = self.services.admin.list_inspectors(account)
            print_table(
                ["ID", "姓名", "手机号"],
                [[item.id, item.name, item.phone] for item in inspectors],
            )
            inspector_id = ask_int("检票员 ID", 1)
            self.services.admin.assign_inspector(account, inspector_id, activity_id)
            success("已分配检票员。")
        elif action == "3":
            detail = self.services.queries.activity_detail(account, activity_id)
            self._print_detail(detail)
        self._pause()

    def _admin_registrations(self, account: Account) -> None:
        keyword = ask_optional("姓名/手机号/报名 ID")
        views = self.services.queries.admin_search_registrations(account, keyword)
        section("报名查询")
        print_table(
            ["ID", "姓名", "手机号", "活动", "场次", "状态", "金额"],
            [
                [
                    view.registration.id,
                    view.registration.buyer_name,
                    view.registration.buyer_phone,
                    view.activity_name,
                    view.session_no,
                    label(view.registration.status),
                    money(view.price_cents),
                ]
                for view in views
            ],
        )
        if not views:
            return
        registration_id = ask_int("要强制退票的报名 ID（0 返回）", 0)
        if registration_id == 0:
            return
        reason = ask("强制退票原因")
        if not ask_yes_no("确认强制退票并退款？", False):
            return
        registration = self.services.refunds.force_refund(
            account, registration_id, reason
        )
        success(
            f"强制退票成功，退款 {money(registration.refund_amount_cents)}。"
        )
        self._pause()

    def _platform(self, account: Account) -> None:
        summary = self.services.queries.platform_summary(account)
        section("平台概览")
        print_table(
            ["项目", "数值"],
            [
                ["账号", json.dumps(summary["accounts"], ensure_ascii=False)],
                ["活动", json.dumps(summary["activities"], ensure_ascii=False)],
                ["报名记录", summary["registrations"]],
                ["有效报名金额", money(int(summary["revenue_cents"]))],
                ["候补中", summary["waiting"]],
            ],
        )
        self._pause()

    # ---------- 通用 ----------

    def _notifications(self, account: Account) -> None:
        notifications = self.services.notifications.list_for(account.id)
        section("我的通知")
        print_table(
            ["ID", "时间", "类型", "内容", "已读"],
            [
                [
                    item.id,
                    item.created_at,
                    label(item.type),
                    item.content,
                    "是" if item.is_read else "否",
                ]
                for item in notifications
            ],
        )
        if notifications and ask_yes_no("全部标记为已读？", False):
            self.services.notifications.mark_all_read(account.id)
            success("已全部标记为已读。")
        self._pause()

    def _audit(self, account: Account) -> None:
        object_type = ask_optional("对象类型（如 ACTIVITY/REGISTRATION）")
        action = ask_optional("操作类型（如 REFUND/CHECKIN_PASSED）")
        date_from = self._optional_time("开始时间")
        date_to = self._optional_time("结束时间")
        logs = self.services.queries.audit_query(
            account,
            object_type=object_type or None,
            action=action or None,
            date_from=date_from,
            date_to=date_to,
            limit=100,
        )
        section("审计记录")
        print_table(
            ["时间", "操作人", "对象", "操作", "前后状态", "说明"],
            [
                [
                    item.operated_at,
                    self._operator_name(item.operator_id),
                    f"{item.object_type}#{item.object_id}",
                    item.action,
                    f"{item.before_status or '-'}→{item.after_status or '-'}",
                    item.description,
                ]
                for item in logs
            ],
        )
        self._pause()

    def _account_info(self, account: Account) -> None:
        section("账号信息")
        print(f"  ID：{account.id}")
        print(f"  姓名：{account.name}")
        print(f"  手机号：{account.phone}")
        print(f"  角色：{label(account.role)}")
        print(f"  状态：{label(account.status)}")
        print(f"  注册时间：{account.created_at}")
        self._pause()

    def _print_detail(self, detail) -> None:
        """打印活动、场次、票种详情。"""
        activity = detail.activity
        section(f"活动详情 · {activity.name}（ID {activity.id}）")
        print(f"  描述：{activity.description}")
        print(f"  地点：{activity.location}")
        print(f"  状态：{label(activity.status)}")
        print(f"  售票：{activity.sale_start} ~ {activity.sale_end}")
        print(f"  候补截止：{activity.waitlist_deadline}")
        print(f"  退票截止：{activity.refund_deadline}")
        print_table(
            ["场次 ID", "场次号", "开始", "结束", "检票开放", "状态"],
            [
                [
                    session.id,
                    session.session_no,
                    session.start_time,
                    session.end_time,
                    session.checkin_open_time,
                    label(session.status),
                ]
                for session in detail.sessions
            ],
        )
        rows = []
        for session in detail.sessions:
            for ticket in detail.tickets.get(session.id, []):
                rows.append(
                    [
                        ticket.id,
                        session.session_no,
                        label(ticket.kind),
                        money(ticket.price_cents),
                        f"{ticket.remaining}/{ticket.capacity}",
                    ]
                )
        print_table(["票种 ID", "场次", "类型", "价格", "余票/容量"], rows)

    def _find_ticket(self, detail, session_id: int, kind: TicketKind):
        for ticket in detail.tickets.get(session_id, []):
            if ticket.kind is kind:
                return ticket
        return None

    def _choose_kind(self) -> TicketKind:
        choice = input("票种：1. VIP  2. 普通票：").strip()
        return TicketKind.NORMAL if choice == "2" else TicketKind.VIP

    def _optional_kind(self) -> TicketKind | None:
        choice = input("票种筛选：0. 全部  1. VIP  2. 普通票：").strip()
        if choice == "1":
            return TicketKind.VIP
        if choice == "2":
            return TicketKind.NORMAL
        return None

    def _optional_time(self, prompt: str) -> str | None:
        text = ask_optional(prompt)
        if not text:
            return None
        return format_dt(parse_dt(text, datetime.now()))

    def _operator_name(self, operator_id: int | None) -> str:
        if operator_id is None:
            return "系统"
        row = self.services.db.query_one(
            "SELECT name FROM account WHERE id = ?", (operator_id,)
        )
        return row["name"] if row else f"账号#{operator_id}"

    @staticmethod
    def _pause() -> None:
        input("\n按回车继续...")


def main(argv: list[str] | None = None) -> int:
    """程序入口。"""
    parser = argparse.ArgumentParser(description="活动票务与报名系统")
    parser.add_argument("--db", default="ticketing.db", help="SQLite 数据库文件")
    parser.add_argument(
        "--no-seed", action="store_true", help="不自动生成演示数据"
    )
    parser.add_argument(
        "--reset", action="store_true", help="删除现有数据库后重建（仅演示）"
    )
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if args.reset and db_path.exists():
        db_path.unlink()
    database = Database(db_path)
    database.initialize()
    if not args.no_seed:
        created = seed_demo(database, ManualClock())
        if created:
            print(DEMO_HINT)
    services = build_services(database, SystemClock())
    try:
        ConsoleApp(services).run()
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

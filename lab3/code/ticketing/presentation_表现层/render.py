"""终端渲染与输入辅助。

终端表格按“显示宽度”对齐：中文和全角符号算 2 列，避免表格错位。
所有输入都做了基本校验，服务层仍会再校验一次业务规则。
"""

# 审查通过：表格按 CJK 显示宽度对齐；输入辅助只做格式/范围检查；
# 成功/警告/错误提示统一，业务规则仍由服务层兜底。
# 第二轮审查（2026-11-05）：复核 CJK 对齐、整数/金额/时间输入校验；
# nan/inf 金额会被捕获并提示，不进入业务层，复核无误。

from __future__ import annotations

import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

from ticketing.infrastructure_基础设施.clock import format_dt, parse_dt
from ticketing.domain_共享能力层.models import (
    AccountStatus,
    ActivityStatus,
    CheckRequestStatus,
    PaymentStatus,
    RegistrationStatus,
    ReportStatus,
    ReviewStatus,
    ReviewType,
    Role,
    SessionStatus,
    TicketKind,
    WaitlistStatus,
)

STATUS_LABELS = {
    Role.PARTICIPANT.value: "参与者",
    Role.ORGANIZER.value: "组织者",
    Role.INSPECTOR.value: "检票员",
    Role.ADMIN.value: "管理员",
    AccountStatus.NORMAL.value: "正常",
    AccountStatus.BANNED.value: "已封禁",
    ActivityStatus.DRAFT.value: "草稿",
    ActivityStatus.PENDING_REVIEW.value: "待审核",
    ActivityStatus.PUBLISHED.value: "公开",
    ActivityStatus.ONGOING.value: "进行中",
    ActivityStatus.ENDED.value: "已结束",
    ActivityStatus.CANCELLED.value: "已取消",
    SessionStatus.NOT_OPEN.value: "未开放",
    SessionStatus.OPEN.value: "可报名",
    SessionStatus.FULL.value: "已满",
    SessionStatus.CLOSED.value: "已截止",
    SessionStatus.CANCELLED.value: "已取消",
    SessionStatus.ENDED.value: "已结束",
    RegistrationStatus.PURCHASED.value: "已购票",
    RegistrationStatus.CHECKED_IN.value: "已检票",
    RegistrationStatus.NORMAL_END.value: "正常结束",
    RegistrationStatus.SELF_CANCELLED.value: "自行取消",
    RegistrationStatus.NO_SHOW.value: "未检票",
    RegistrationStatus.ACTIVITY_CANCELLED.value: "活动取消",
    WaitlistStatus.WAITING.value: "候补中",
    WaitlistStatus.PROMOTED.value: "已递补",
    WaitlistStatus.SELF_CANCELLED.value: "自行取消",
    WaitlistStatus.FAILED.value: "候补失败",
    CheckRequestStatus.PENDING.value: "待处理",
    CheckRequestStatus.PASSED.value: "已通过",
    CheckRequestStatus.ABNORMAL.value: "异常",
    ReviewStatus.PENDING.value: "待审核",
    ReviewStatus.APPROVED.value: "已通过",
    ReviewStatus.REJECTED.value: "已驳回",
    ReviewType.PUBLISH.value: "发布审核",
    ReviewType.MODIFY.value: "修改审核",
    ReviewType.CANCEL.value: "取消申请",
    ReportStatus.PENDING.value: "待处理",
    ReportStatus.RESOLVED.value: "已处理",
    ReportStatus.DISMISSED.value: "已驳回",
    PaymentStatus.PAID.value: "已支付",
    PaymentStatus.UNPAID.value: "未支付",
    TicketKind.VIP.value: "VIP",
    TicketKind.NORMAL.value: "普通票",
}


def label(value) -> str:
    """把枚举或字符串转成中文标签。"""
    text = value.value if hasattr(value, "value") else str(value)
    return STATUS_LABELS.get(text, text)


def money(cents: int | None) -> str:
    """分转元。"""
    if cents is None:
        return "-"
    return f"￥{Decimal(cents) / Decimal(100):.2f}"


def display_width(text: str) -> int:
    """终端显示宽度：CJK 宽字符算 2。"""
    width = 0
    for char in str(text):
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def pad(text: str, width: int) -> str:
    """按显示宽度右侧补空格。"""
    return str(text) + " " * max(0, width - display_width(str(text)))


# 按 CJK 显示宽度对齐，避免中文表格错位。
def print_table(headers: list[str], rows: Iterable[Iterable[object]]) -> None:
    """打印对齐的终端表格。"""
    data = [[str(cell) for cell in row] for row in rows]
    if not data:
        print("  （无记录）")
        return
    widths = [
        max(display_width(header), *(display_width(row[i]) for row in data))
        for i, header in enumerate(headers)
    ]
    print("  " + "  ".join(pad(header, widths[i]) for i, header in enumerate(headers)))
    print("  " + "  ".join("-" * widths[i] for i in range(len(headers))))
    for row in data:
        print("  " + "  ".join(pad(cell, widths[i]) for i, cell in enumerate(row)))


def section(title: str) -> None:
    """打印小节标题。"""
    print(f"\n=== {title} ===")


def success(message: str) -> None:
    """打印成功提示。"""
    print(f"✓ {message}")


def warn(message: str) -> None:
    """打印警告提示。"""
    print(f"! {message}")


def error(message: str) -> None:
    """打印错误提示。"""
    print(f"✗ {message}")


def ask(prompt: str, default: str | None = None) -> str:
    """读取非空字符串；提供默认值时回车即采用默认值。"""
    suffix = f"（默认 {default}）" if default is not None else ""
    while True:
        value = input(f"{prompt}{suffix}：").strip()
        if value:
            return value
        if default is not None:
            return default
        warn("输入不能为空")


def ask_optional(prompt: str) -> str:
    """允许为空。"""
    return input(f"{prompt}（可空）：").strip()


def ask_int(prompt: str, minimum: int | None = None, maximum: int | None = None) -> int:
    """读取整数并检查范围。"""
    while True:
        text = input(f"{prompt}：").strip()
        try:
            value = int(text)
        except ValueError:
            warn("请输入整数")
            continue
        if minimum is not None and value < minimum:
            warn(f"不能小于 {minimum}")
            continue
        if maximum is not None and value > maximum:
            warn(f"不能大于 {maximum}")
            continue
        return value


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    """读取 y/n。"""
    hint = "Y/n" if default else "y/N"
    value = input(f"{prompt}（{hint}）：").strip().lower()
    if not value:
        return default
    return value in ("y", "yes", "是", "1")


def ask_time(prompt: str, default: str | None = None) -> datetime:
    """读取时间；支持 2026-11-20 19:30 或 +3d/+2h/+30m。"""
    while True:
        text = ask(prompt, default)
        try:
            return parse_dt(text, datetime.now())
        except ValueError as exc:
            warn(str(exc))


def ask_money(prompt: str, default: str = "0") -> int:
    """读取金额（元），返回分。"""
    while True:
        text = ask(prompt, default)
        try:
            value = Decimal(text)
            if value < 0:
                raise InvalidOperation
            return int((value * 100).quantize(Decimal("1")))
        except (InvalidOperation, ValueError):
            warn("请输入非负金额，例如 99.00")


def show_time(value: datetime) -> str:
    """格式化时间。"""
    return format_dt(value)

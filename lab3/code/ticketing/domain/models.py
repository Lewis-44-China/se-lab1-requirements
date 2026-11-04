"""领域枚举与数据对象。

这些类与实验二 UML 类图一一对应；数据库行通过 from_row 转成对象，
服务层只操作对象和枚举，避免在业务代码里散落字符串常量。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

# 四种账号角色，一致
class Role(str, Enum):
    """账号角色。"""

    PARTICIPANT = "PARTICIPANT"
    ORGANIZER = "ORGANIZER"
    INSPECTOR = "INSPECTOR"
    ADMIN = "ADMIN"

# 账号状态，一致
class AccountStatus(str, Enum):
    """账号状态：正常/封禁。"""

    NORMAL = "NORMAL"
    BANNED = "BANNED"

# 活动状态，一致
class ActivityStatus(str, Enum):
    """活动状态（REQ-021）。"""

    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    ONGOING = "ONGOING"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"

# 场次状态，审核通过：allow_waitlist 是场次属性，候补截止 waitlistDeadline 是活动属性；
# FULL 只表示容量已满，不区分能否候补。
class SessionStatus(str, Enum):
    """场次状态（REQ-007）。"""

    NOT_OPEN = "NOT_OPEN"
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    ENDED = "ENDED"


# 票种类型，一致
class TicketKind(str, Enum):
    """票种类型（REQ-008）。"""

    VIP = "VIP"
    NORMAL = "NORMAL"

# 报名记录状态，一致
class RegistrationStatus(str, Enum):
    """报名记录状态（REQ-022）。"""

    PURCHASED = "PURCHASED"
    CHECKED_IN = "CHECKED_IN"
    NORMAL_END = "NORMAL_END"
    SELF_CANCELLED = "SELF_CANCELLED"
    NO_SHOW = "NO_SHOW"
    ACTIVITY_CANCELLED = "ACTIVITY_CANCELLED"


# 支付标记，一致
class PaymentStatus(str, Enum):
    """支付标记（REQ-025）。"""

    PAID = "PAID"
    UNPAID = "UNPAID"


# 候补记录状态，一致
class WaitlistStatus(str, Enum):
    """候补记录状态（REQ-023）。"""

    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    SELF_CANCELLED = "SELF_CANCELLED"
    FAILED = "FAILED"   # 包括活动取消


# 检票请求状态，一致
class CheckRequestStatus(str, Enum):
    """检票请求状态（REQ-014/017）。"""

    PENDING = "PENDING"
    PASSED = "PASSED"
    ABNORMAL = "ABNORMAL"


# 审核申请类型，一致
class ReviewType(str, Enum):
    """审核申请类型（REQ-009/010/011）。"""

    PUBLISH = "PUBLISH"
    MODIFY = "MODIFY"
    CANCEL = "CANCEL"


# 审核结果状态，一致
class ReviewStatus(str, Enum):
    """审核结果状态。"""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# 举报处理状态，一致
class ReportStatus(str, Enum):
    """举报处理状态。"""

    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


# 站内消息类型，一致
class NotificationType(str, Enum):
    """站内消息类型。"""

    REVIEW_RESULT = "REVIEW_RESULT"
    ACTIVITY_CHANGED = "ACTIVITY_CHANGED"
    WAITLIST_PROMOTED = "WAITLIST_PROMOTED"
    FORCE_REFUND = "FORCE_REFUND"
    ACTIVITY_CANCELLED = "ACTIVITY_CANCELLED"
    WAITLIST_FAILED = "WAITLIST_FAILED"

# 以上枚举审查通过；场次状态的疑问已核实（allow_waitlist 属场次，候补截止属活动）。


# 以下数据对象与 schema 表、实验二类图一一对应，审核通过


@dataclass(slots=True)
class Account:
    """账号。"""

    id: int
    phone: str
    password_hash: str
    password_salt: str
    name: str
    role: Role
    status: AccountStatus
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Account":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            phone=row["phone"],
            password_hash=row["password_hash"],
            password_salt=row["password_salt"],
            name=row["name"],
            role=Role(row["role"]),
            status=AccountStatus(row["status"]),
            created_at=row["created_at"],
        )

    @property
    def is_banned(self) -> bool:
        """账号是否被封禁。"""
        return self.status is AccountStatus.BANNED


@dataclass(slots=True)
class Activity:
    """活动聚合根。"""

    id: int
    organizer_id: int
    name: str
    description: str
    location: str
    estimated_participants: int
    sale_start: str
    sale_end: str
    waitlist_deadline: str
    refund_deadline: str
    cover: str
    tags: str
    status: ActivityStatus
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Activity":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            organizer_id=row["organizer_id"],
            name=row["name"],
            description=row["description"],
            location=row["location"],
            estimated_participants=row["estimated_participants"],
            sale_start=row["sale_start"],
            sale_end=row["sale_end"],
            waitlist_deadline=row["waitlist_deadline"],
            refund_deadline=row["refund_deadline"],
            cover=row["cover"],
            tags=row["tags"],
            status=ActivityStatus(row["status"]),
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class Session:
    """场次。"""

    id: int
    activity_id: int
    session_no: str
    start_time: str
    end_time: str
    checkin_open_time: str
    allow_waitlist: bool
    status: SessionStatus

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Session":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            activity_id=row["activity_id"],
            session_no=row["session_no"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            checkin_open_time=row["checkin_open_time"],
            allow_waitlist=bool(row["allow_waitlist"]),
            status=SessionStatus(row["status"]),
        )


@dataclass(slots=True)
class TicketType:
    """票种与容量。"""

    id: int
    session_id: int
    kind: TicketKind
    price_cents: int
    capacity: int
    occupied: int

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "TicketType":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            kind=TicketKind(row["kind"]),
            price_cents=row["price_cents"],
            capacity=row["capacity"],
            occupied=row["occupied"],
        )

    @property
    def remaining(self) -> int:
        """余票 = 容量 - 已占用。"""
        return self.capacity - self.occupied


@dataclass(slots=True)
class Registration:
    """报名记录（报名即购票）。"""

    id: int
    account_id: int
    activity_id: int
    session_id: int
    ticket_type_id: int
    buyer_name: str
    buyer_phone: str
    ticket_kind: TicketKind
    status: RegistrationStatus
    payment_status: PaymentStatus
    payment_amount_cents: int
    refund_amount_cents: int | None
    refund_time: str | None
    request_id: str
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Registration":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            account_id=row["account_id"],
            activity_id=row["activity_id"],
            session_id=row["session_id"],
            ticket_type_id=row["ticket_type_id"],
            buyer_name=row["buyer_name"],
            buyer_phone=row["buyer_phone"],
            ticket_kind=TicketKind(row["ticket_kind"]),
            status=RegistrationStatus(row["status"]),
            payment_status=PaymentStatus(row["payment_status"]),
            payment_amount_cents=row["payment_amount_cents"],
            refund_amount_cents=row["refund_amount_cents"],
            refund_time=row["refund_time"],
            request_id=row["request_id"],
            created_at=row["created_at"],
        )

    @property
    def is_terminal(self) -> bool:
        """终态不可再变更（REQ-022）。"""
        return self.status in {
            RegistrationStatus.NORMAL_END,
            RegistrationStatus.SELF_CANCELLED,
            RegistrationStatus.NO_SHOW,
            RegistrationStatus.ACTIVITY_CANCELLED,
        }

    @property
    def occupies_seat(self) -> bool:
        """已购票、已检票、未检票占用名额（REQ-026）。"""
        return self.status in {
            RegistrationStatus.PURCHASED,
            RegistrationStatus.CHECKED_IN,
            RegistrationStatus.NO_SHOW,
        }


@dataclass(slots=True)
class WaitlistRecord:
    """候补记录。"""

    id: int
    waitlist_id: int
    account_id: int
    activity_id: int
    session_id: int
    join_time: str
    payment_status: PaymentStatus
    payment_amount_cents: int
    status: WaitlistStatus
    refund_amount_cents: int | None
    refund_time: str | None
    request_id: str
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "WaitlistRecord":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            waitlist_id=row["waitlist_id"],
            account_id=row["account_id"],
            activity_id=row["activity_id"],
            session_id=row["session_id"],
            join_time=row["join_time"],
            payment_status=PaymentStatus(row["payment_status"]),
            payment_amount_cents=row["payment_amount_cents"],
            status=WaitlistStatus(row["status"]),
            refund_amount_cents=row["refund_amount_cents"],
            refund_time=row["refund_time"],
            request_id=row["request_id"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class CheckRequest:
    """检票请求。"""

    id: int
    registration_id: int
    request_no: str
    inspector_id: int | None
    status: CheckRequestStatus
    created_at: str
    processed_at: str | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CheckRequest":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            registration_id=row["registration_id"],
            request_no=row["request_no"],
            inspector_id=row["inspector_id"],
            status=CheckRequestStatus(row["status"]),
            created_at=row["created_at"],
            processed_at=row["processed_at"],
        )


@dataclass(slots=True)
class ReviewApplication:
    """审核申请。"""

    id: int
    activity_id: int
    type: ReviewType
    payload: str
    status: ReviewStatus
    submitted_at: str
    reviewer_id: int | None
    comment: str
    reviewed_at: str | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ReviewApplication":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            activity_id=row["activity_id"],
            type=ReviewType(row["type"]),
            payload=row["payload"],
            status=ReviewStatus(row["status"]),
            submitted_at=row["submitted_at"],
            reviewer_id=row["reviewer_id"],
            comment=row["comment"],
            reviewed_at=row["reviewed_at"],
        )


@dataclass(slots=True)
class Report:
    """举报。"""

    id: int
    reporter_id: int
    activity_id: int
    reason: str
    status: ReportStatus
    handler_id: int | None
    result: str
    handled_at: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Report":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            reporter_id=row["reporter_id"],
            activity_id=row["activity_id"],
            reason=row["reason"],
            status=ReportStatus(row["status"]),
            handler_id=row["handler_id"],
            result=row["result"],
            handled_at=row["handled_at"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class Notification:
    """站内消息。"""

    id: int
    recipient_id: int
    type: NotificationType
    content: str
    is_read: bool
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Notification":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            recipient_id=row["recipient_id"],
            type=NotificationType(row["type"]),
            content=row["content"],
            is_read=bool(row["is_read"]),
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class AuditLog:
    """审计留痕，只追加不修改。"""

    id: int
    operator_id: int | None
    operated_at: str
    object_type: str
    object_id: int
    action: str
    before_status: str | None
    after_status: str | None
    description: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "AuditLog":
        """从数据库行构造对象。"""
        return cls(
            id=row["id"],
            operator_id=row["operator_id"],
            operated_at=row["operated_at"],
            object_type=row["object_type"],
            object_id=row["object_id"],
            action=row["action"],
            before_status=row["before_status"],
            after_status=row["after_status"],
            description=row["description"],
        )


# 数据对象审查通过：字段与表、类图一致，from_row 与派生属性正确。
# 第二部分审查完毕：数据库定义结构已用于实现相关类、转换方法与派生属性。
"""角色与数据范围校验（对应设计基线 M7）。

界面隐藏按钮不是安全边界；所有写操作和敏感读操作都在服务层再校验一次。
"""

from __future__ import annotations

from .errors import PermissionDenied
from .models import Account, AccountStatus, Role
from .security import mask_phone


class PermissionService:
    """无状态权限策略。"""

    @staticmethod
    def require_role(account: Account, *roles: Role) -> None:
        """要求账号属于指定角色之一。"""
        if account.role not in roles:
            allowed = "、".join(role.value for role in roles)
            raise PermissionDenied(f"需要 {allowed} 角色")

    @staticmethod
    def require_active(account: Account) -> None:
        """购票、候补等新增交易要求账号未被封禁。"""
        if account.status is AccountStatus.BANNED:
            raise PermissionDenied("账号已被封禁，不能进行购票或候补")

    @staticmethod
    def require_owner(account: Account, owner_id: int, what: str = "数据") -> None:
        """要求当前账号是对象所有者。"""
        if account.id != owner_id:
            raise PermissionDenied(f"无权访问他人的{what}")

    @staticmethod
    def require_activity_owner(account: Account, organizer_id: int) -> None:
        """组织者只能操作自己的活动。"""
        PermissionService.require_role(account, Role.ORGANIZER)
        if account.id != organizer_id:
            raise PermissionDenied("只能管理自己创建的活动")

    @staticmethod
    def visible_phone(viewer: Account, owner_id: int, phone: str) -> str:
        """完整手机号仅管理员与本人可见，其余角色看遮挡版。"""
        if viewer.role is Role.ADMIN or viewer.id == owner_id:
            return phone
        return mask_phone(phone)

    @staticmethod
    def is_assigned_inspector(
        db, inspector_id: int, activity_id: int
    ) -> bool:
        """检票员是否被管理员分配到该活动。"""
        row = db.query_one(
            """
            SELECT 1 FROM activity_inspector
            WHERE inspector_id = ? AND activity_id = ?
            """,
            (inspector_id, activity_id),
        )
        return row is not None

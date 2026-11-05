"""角色与数据范围校验（对应设计基线 M7）。

界面隐藏按钮不是安全边界；所有写操作和敏感读操作都在服务层再校验一次。
"""

from __future__ import annotations

from ticketing.domain.errors import PermissionDenied
from ticketing.domain.models import Account, AccountStatus, Role
from ticketing.infrastructure.security import mask_phone

# 审查通过：公开用例入口都做了权限校验（角色/所有者/账号状态/检票员分配）。
# 低层查询（get_*、list_by_organizer、notifications.list_for 等）依赖调用方传入
# 正确的当前账号，不能绕过应用层直接调用（Q21/Q22）。
# visible_phone 是统一脱敏策略，但当前查询/CLI 直接调用 mask_phone（Q21）。

class PermissionService:
    """无状态权限策略。"""

    @staticmethod
    # 角色边界。
    def require_role(account: Account, *roles: Role) -> None:
        """要求账号属于指定角色之一。"""
        if account.role not in roles:
            allowed = "、".join(role.value for role in roles)
            raise PermissionDenied(f"需要 {allowed} 角色")

    @staticmethod
    # 新增交易边界：封禁账号不能购票/候补；查看已有票不受限。
    # 第二轮审查：对照 REQ-018，封禁后仅禁止新增交易（报名/候补，本方法只在这两处
# 调用）；已有票仍可检票入场、退票、查询和接收通知，不做限制。
    def require_active(account: Account) -> None:
        """购票、候补等新增交易要求账号未被封禁。"""
        if account.status is AccountStatus.BANNED:
            raise PermissionDenied("账号已被封禁，不能进行购票或候补")

    @staticmethod
    # 数据所有者边界。
    # 第二轮审查：仅用于参与者自己的数据（退票/检票/取消候补）；管理员操作走各自的
# require_role(ADMIN) 入口，不调用本方法，因此“管理员除外”由调用边界保证。
    def require_owner(account: Account, owner_id: int, what: str = "数据") -> None:
        """要求当前账号是对象所有者。"""
        if account.id != owner_id:
            raise PermissionDenied(f"无权访问他人的{what}")

    @staticmethod
    # 组织者只能操作自己的活动。
    def require_activity_owner(account: Account, organizer_id: int) -> None:
        """组织者只能操作自己的活动。"""
        PermissionService.require_role(account, Role.ORGANIZER)
        if account.id != organizer_id:
            raise PermissionDenied("只能管理自己创建的活动")

    @staticmethod
    # 统一脱敏策略：管理员/本人完整，其他角色遮挡；当前多处直接调 mask_phone。
    def visible_phone(viewer: Account, owner_id: int, phone: str) -> str:
        """完整手机号仅管理员与本人可见，其余角色看遮挡版。"""
        if viewer.role is Role.ADMIN or viewer.id == owner_id:
            return phone
        return mask_phone(phone)

    @staticmethod
    # 检票员数据边界：只处理被分配的活动。
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

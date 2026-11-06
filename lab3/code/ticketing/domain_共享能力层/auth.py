"""账号与认证服务（对应设计基线 D6 + A0）。

- 参与者、组织者自助注册；管理员预创建；检票员由管理员创建；
- 登录只需手机号 + 密码，一个手机号只对应一个身份；
- 被封禁账号仍可登录查看已有票，但服务层会阻止其新增购票/候补。
"""

# 审查通过：三种创建方式——参与者/组织者自助 register（角色受限）；
# 管理员系统初始化 bootstrap_admin；检票员由管理员 create_inspector。
# 重复手机号由唯一约束 + Conflict 拦截；手机号/密码/姓名在注册前校验。
# 第二轮审查（2026-11-05）：核实手机号跨四种角色唯一、登录不需要角色参数
# （Q58/Q59），代码逻辑未改。

from __future__ import annotations

import sqlite3

from ticketing.common_横切能力.audit import AuditService
from ticketing.infrastructure_基础设施.clock import Clock, format_dt
from ticketing.infrastructure_基础设施.db import Database
from ticketing.domain_共享能力层.errors import Conflict, NotFound, ValidationError
from ticketing.domain_共享能力层.models import Account, AccountStatus, Role
from ticketing.common_横切能力.permissions import PermissionService
from ticketing.infrastructure_基础设施.security import (
    hash_password,
    normalize_phone,
    validate_password,
    verify_password,
)


class AuthService:
    """注册、登录与账号查询。"""

    def __init__(self, db: Database, clock: Clock, audit: AuditService) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit

    # 自助注册：只允许参与者/组织者；校验手机号/密码/姓名；唯一手机号冲突转 Conflict。
    # 第二轮审查 Q58：手机号在 account.phone 上有 UNIQUE 约束，覆盖四种角色；
    # 自助注册、管理员创建检票员、管理员初始化都走 INSERT + IntegrityError→Conflict，
    # 所以同一手机号不可能同时注册成两种角色。
    def register(
        self, phone: str, password: str, name: str, role: Role
    ) -> Account:
        """参与者/组织者自助注册。"""
        if role not in (Role.PARTICIPANT, Role.ORGANIZER):
            raise ValidationError("只能注册参与者或组织者；管理员、检票员账号由平台创建")
        self._validate_profile(phone, password, name)
        normalized = normalize_phone(phone)
        password_hash, salt = hash_password(password)
        try:
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO account (
                        phone, password_hash, password_salt, name, role, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized,
                        password_hash,
                        salt,
                        name.strip(),
                        role.value,
                        AccountStatus.NORMAL.value,
                        format_dt(self.clock.now()),
                    ),
                )
                account_id = int(cursor.lastrowid)
                self.audit.record(
                    conn,
                    account_id,
                    "ACCOUNT",
                    account_id,
                    "ACCOUNT_CREATED",
                    f"账号注册：{name.strip()}（{role.value}）",
                    None,
                    AccountStatus.NORMAL.value,
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict("该手机号已注册") from exc
        return self.get_account(account_id)

    # 登录：手机号 + 密码；失败统一提示“手机号或密码错误”，不泄露账号是否存在。
    # 第二轮审查 Q59：登录不需要传角色。角色是账号属性（account.role），登录后
    # 按该属性进入对应菜单；封禁账号仍可登录，是为了查看已有票/候补（REQ-018）。
    def login(self, phone: str, password: str) -> Account:
        """手机号 + 密码登录；失败时不区分“账号不存在/密码错误”。"""
        normalized = normalize_phone(phone)
        row = self.db.query_one("SELECT * FROM account WHERE phone = ?", (normalized,))
        if row is None:
            raise ValidationError("手机号或密码错误")
        if not verify_password(password, row["password_hash"], row["password_salt"]):
            raise ValidationError("手机号或密码错误")
        return Account.from_row(row)

    def get_account(self, account_id: int) -> Account:
        """按 id 取账号，不存在则抛 NotFound。"""
        row = self.db.query_one("SELECT * FROM account WHERE id = ?", (account_id,))
        if row is None:
            raise NotFound("账号不存在")
        return Account.from_row(row)

    def find_by_phone(self, phone: str) -> Account | None:
        """按手机号查找，供内部流程使用。"""
        row = self.db.query_one(
            "SELECT * FROM account WHERE phone = ?", (normalize_phone(phone),)
        )
        return Account.from_row(row) if row else None

    # 管理员创建检票员账号；检票员不能自助注册。
    def create_inspector(
        self, admin: Account, phone: str, password: str, name: str
    ) -> Account:
        """管理员创建检票员账号（REQ-002/047）。"""
        PermissionService.require_role(admin, Role.ADMIN)
        self._validate_profile(phone, password, name)
        normalized = normalize_phone(phone)
        password_hash, salt = hash_password(password)
        try:
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO account (
                        phone, password_hash, password_salt, name, role, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized,
                        password_hash,
                        salt,
                        name.strip(),
                        Role.INSPECTOR.value,
                        AccountStatus.NORMAL.value,
                        format_dt(self.clock.now()),
                    ),
                )
                inspector_id = int(cursor.lastrowid)
                self.audit.record(
                    conn,
                    admin.id,
                    "ACCOUNT",
                    inspector_id,
                    "INSPECTOR_CREATED",
                    f"管理员创建检票账号：{name.strip()}",
                    None,
                    AccountStatus.NORMAL.value,
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict("该手机号已注册") from exc
        return self.get_account(inspector_id)

    # 系统初始化管理员：手机号已存在时只接受已有管理员，防止普通账号占号。
    def bootstrap_admin(
        self, phone: str, password: str, name: str = "平台管理员"
    ) -> Account:
        """首次初始化时创建管理员；已存在则返回现有账号。"""
        existing = self.find_by_phone(phone)
        if existing is not None:
            # 防止普通账号占用管理员手机号后，初始化直接返回该账号导致系统没有管理员。
            if existing.role is not Role.ADMIN:
                raise Conflict("该手机号已被非管理员账号占用，无法初始化管理员")
            return existing
        password_hash, salt = hash_password(password)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO account (
                    phone, password_hash, password_salt, name, role, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalize_phone(phone),
                    password_hash,
                    salt,
                    name,
                    Role.ADMIN.value,
                    AccountStatus.NORMAL.value,
                    format_dt(self.clock.now()),
                ),
            )
            account_id = int(cursor.lastrowid)
            self.audit.record(
                conn,
                account_id,
                "ACCOUNT",
                account_id,
                "ADMIN_BOOTSTRAPPED",
                "系统初始化管理员账号",
                None,
                AccountStatus.NORMAL.value,
            )
        return self.get_account(account_id)

    # 查询账号：由 AdminService 先做管理员权限校验后调用。
    def list_accounts(self, role: Role | None = None) -> list[Account]:
        """列出账号；仅供管理员查询。"""
        if role is None:
            rows = self.db.query_all("SELECT * FROM account ORDER BY id")
        else:
            rows = self.db.query_all(
                "SELECT * FROM account WHERE role = ? ORDER BY id", (role.value,)
            )
        return [Account.from_row(row) for row in rows]

    @staticmethod
    def _validate_profile(phone: str, password: str, name: str) -> None:
        """注册资料的基本校验。"""
        normalize_phone(phone)
        validate_password(password)
        if not name.strip():
            raise ValidationError("姓名不能为空")
        if len(name.strip()) > 30:
            raise ValidationError("姓名过长")

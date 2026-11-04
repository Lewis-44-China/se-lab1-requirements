"""账号与认证服务（对应设计基线 D6 + A0）。

- 参与者、组织者自助注册；管理员预创建；检票员由管理员创建；
- 登录只需手机号 + 密码，一个手机号只对应一个身份；
- 被封禁账号仍可登录查看已有票，但服务层会阻止其新增购票/候补。
"""

from __future__ import annotations

import sqlite3

from ticketing.common.audit import AuditService
from ticketing.infrastructure.clock import Clock, format_dt
from ticketing.infrastructure.db import Database
from ticketing.domain.errors import Conflict, NotFound, ValidationError
from ticketing.domain.models import Account, AccountStatus, Role
from ticketing.common.permissions import PermissionService
from ticketing.infrastructure.security import (
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

    def bootstrap_admin(
        self, phone: str, password: str, name: str = "平台管理员"
    ) -> Account:
        """首次初始化时创建管理员；已存在则返回现有账号。"""
        existing = self.find_by_phone(phone)
        if existing is not None:
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

"""口令、手机号与金额工具。

口令使用 PBKDF2-HMAC-SHA256 加随机盐存储（REQ-045：不准明文）；
手机号在组织者、检票员视图中统一遮挡（REQ-003/045）；
金额只用“分”这个整数单位，避免浮点误差。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from decimal import Decimal, InvalidOperation

from .errors import ValidationError

PHONE_PATTERN = re.compile(r"^1\d{10}$")
PBKDF2_ITERATIONS = 200_000


def normalize_phone(text: str) -> str:
    """去掉空白并校验中国大陆手机号格式。"""
    phone = text.strip().replace(" ", "")
    if not PHONE_PATTERN.match(phone):
        raise ValidationError("手机号必须是 11 位数字且以 1 开头")
    return phone


def validate_password(password: str) -> None:
    """口令最少 6 位；课程项目不做复杂度强校验。"""
    if len(password) < 6:
        raise ValidationError("密码至少 6 位")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """返回 (哈希, 盐)，盐使用十六进制字符串存储。"""
    salt_hex = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS,
    )
    return digest.hex(), salt_hex


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """常量时间比较，避免时序侧信道。"""
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


def mask_phone(phone: str) -> str:
    """13851629609 -> 138****9609。"""
    if len(phone) < 7:
        return "****"
    return f"{phone[:3]}****{phone[-4:]}"


def new_request_id(prefix: str = "REQ") -> str:
    """生成请求幂等号；同一请求重试时应复用同一个编号。"""
    return f"{prefix}-{uuid.uuid4().hex}"


def yuan_to_cents(text: str) -> int:
    """把用户输入的“元”转成“分”，只保留两位小数。"""
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValidationError(f"金额格式不正确：{text}") from exc
    if value < 0:
        raise ValidationError("金额不能为负数")
    cents = int((value * 100).quantize(Decimal("1")))
    return cents


def cents_to_yuan(cents: int | None) -> str:
    """把“分”格式化成两位小数的“元”。"""
    if cents is None:
        return "-"
    return f"{Decimal(cents) / Decimal(100):.2f}"

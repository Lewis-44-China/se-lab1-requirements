"""口令、手机号与金额工具。

口令使用 PBKDF2-HMAC-SHA256 加随机盐存储（REQ-045：不准明文）；
手机号在组织者、检票员视图中统一遮挡（REQ-003/045）；
金额只用“分”这个整数单位，避免浮点误差。
"""

# 第二轮审查（2026-11-05）：复核 PBKDF2 参数、随机盐、常量时间比较、手机号脱敏
# 与 Decimal 金额换算；手工验证正确/错误口令、盐唯一性与金额舍入，复核无误。

# 审查通过：PBKDF2-HMAC-SHA256 + 16 字节随机盐 + 200000 次迭代；校验用
# hmac.compare_digest 做常量时间比较，避免时序侧信道。

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from decimal import Decimal, InvalidOperation

from ticketing.domain_共享能力层.errors import ValidationError

PHONE_PATTERN = re.compile(r"^1\d{10}$")
PBKDF2_ITERATIONS = 200_000


# 审查通过：只接受中国大陆 11 位手机号（1 开头），去除普通空格；
# 不支持 +86 前缀，与实验一需求中的手机号格式一致。
def normalize_phone(text: str) -> str:
    """去掉空白并校验中国大陆手机号格式。"""
    phone = text.strip().replace(" ", "")
    if not PHONE_PATTERN.match(phone):
        raise ValidationError("手机号必须是 11 位数字且以 1 开头")
    return phone


# 审查通过：课程项目只要求至少 6 位，不做复杂度强校验；真实系统应加强。
def validate_password(password: str) -> None:
    """口令最少 6 位；课程项目不做复杂度强校验。"""
    if len(password) < 6:
        raise ValidationError("密码至少 6 位")


# 审查通过：盐为 16 字节（token_hex(16)），与哈希一起存库，不存明文口令。
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


# 审查通过：用存储的盐重新计算，再常量时间比较。
def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """常量时间比较，避免时序侧信道。"""
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


# 审查通过：保留前 3 位与后 4 位，中间遮挡；组织者/检票员视图使用。
def mask_phone(phone: str) -> str:
    """13851629609 -> 138****9609。"""
    if len(phone) < 7:
        return "****"
    return f"{phone[:3]}****{phone[-4:]}"


# 审查通过：uuid4 生成幂等号；同一请求重试应复用同一编号，重复请求返回首次结果。
def new_request_id(prefix: str = "REQ") -> str:
    """生成请求幂等号；同一请求重试时应复用同一个编号。"""
    return f"{prefix}-{uuid.uuid4().hex}"


# 审查通过：用 Decimal 换算，避免二进制浮点误差；金额统一存“分”。
# 注意：按 Decimal 默认舍入处理第三位小数，界面输入建议最多两位。
def yuan_to_cents(text: str) -> int:
    """把用户输入的“元”转成“分”，只保留两位小数。"""
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValidationError(f"金额格式不正确：{text}") from exc
    # 第三轮补充：nan / inf 也是合法 Decimal，但不是合法金额；
    # 统一转成业务异常，保持“业务层只抛 AppError”的约定。
    if not value.is_finite():
        raise ValidationError(f"金额格式不正确：{text}")
    if value < 0:
        raise ValidationError("金额不能为负数")
    cents = int((value * 100).quantize(Decimal("1")))
    return cents


# 审查通过：仅用于展示，内部计算和存储始终用“分”的整数。
def cents_to_yuan(cents: int | None) -> str:
    """把“分”格式化成两位小数的“元”。"""
    if cents is None:
        return "-"
    return f"{Decimal(cents) / Decimal(100):.2f}"

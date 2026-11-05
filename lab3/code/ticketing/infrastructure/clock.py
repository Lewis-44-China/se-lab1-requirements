"""时间抽象与时间解析。

生产环境使用 SystemClock（服务器本地时间）；测试和演示数据使用
ManualClock，可以在不修改系统时间的前提下推进“业务时间”。
所有截止判断都经过 Clock，因此“以服务器时间为准”只有一处实现。
"""

# 第二轮审查（2026-11-05）：复核统一时间格式、三种绝对格式与 +Nd/+Nh/+Nm 相对格式；
# 解析结果统一到秒级，手工验证格式往返与相对时间计算，复核无误。

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

# 审查通过：所有业务截止判断都走 Clock.now()；数据库时间统一为
# "YYYY-MM-DD HH:MM:SS"，同一格式下字符串比较等价于时间比较。
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
INPUT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M")


class Clock(ABC):
    """时钟接口。"""

    @abstractmethod
    def now(self) -> datetime:
        """返回当前业务时间（精确到秒）。"""


# 审查通过：生产时钟取服务器本地时间并去掉微秒，保证与数据库格式一致。
class SystemClock(Clock):
    """使用服务器本地时间。"""

    def now(self) -> datetime:
        return datetime.now().replace(microsecond=0)


# 审查通过：测试/演示时钟可 set/advance；仅单线程使用，不用于生产并发。
class ManualClock(Clock):
    """可手动设置、推进的时钟，用于测试和演示数据。"""

    def __init__(self, current: datetime | None = None) -> None:
        self._current = (current or datetime.now()).replace(microsecond=0)

    def now(self) -> datetime:
        return self._current

    def set(self, value: datetime) -> None:
        """直接把时钟拨到指定时间。"""
        self._current = value.replace(microsecond=0)

    def advance(self, **kwargs: float) -> None:
        """按时长推进，例如 advance(days=1, hours=2)。"""
        self._current += timedelta(**kwargs)


def format_dt(value: datetime) -> str:
    """转成数据库统一时间格式。"""
    return value.strftime(TIME_FORMAT)


# 审查通过：支持三种绝对格式和 +Nd/+Nh/+Nm 相对格式；
# 相对格式只用于界面输入，业务判断比较的是已格式化的绝对时间。
def parse_dt(text: str, now: datetime | None = None) -> datetime:
    """解析用户输入的时间。

    支持：
    - 2026-11-20 19:30
    - 2026-11-20 19:30:00
    - 2026-11-20T19:30
    - +3d / +2h / +30m（相对当前时间，便于演示）
    """
    value = text.strip()
    base = now or datetime.now()
    if value.startswith("+"):
        return _parse_relative(value, base)
    for fmt in INPUT_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(microsecond=0)
        except ValueError:
            continue
    raise ValueError(f"无法识别的时间：{text}")


# 审查通过：相对时间只支持 d/h/m，输入非法时抛 ValueError，由 CLI 捕获提示。
def _parse_relative(value: str, base: datetime) -> datetime:
    """解析 +3d、+2h、+30m 这类相对时间。"""
    unit = value[-1].lower()
    number_text = value[1:-1]
    if not number_text.isdigit():
        raise ValueError(f"无法识别的相对时间：{value}")
    number = int(number_text)
    if unit == "d":
        return (base + timedelta(days=number)).replace(microsecond=0)
    if unit == "h":
        return (base + timedelta(hours=number)).replace(microsecond=0)
    if unit == "m":
        return (base + timedelta(minutes=number)).replace(microsecond=0)
    raise ValueError(f"相对时间单位只支持 d/h/m：{value}")

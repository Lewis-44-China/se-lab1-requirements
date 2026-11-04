"""业务异常定义。

服务层只抛出这里定义的异常；命令行界面统一捕获并打印中文提示。
这样做的好处是：业务规则不依赖 UI，测试也可以直接断言异常类型。
"""


# 审查通过：业务层只抛 AppError 子类，CLI 统一捕获并显示中文提示；
# CapacityFull 额外带 ticket_type_id，便于询问是否候补。
class AppError(Exception):
    """所有业务异常的基类。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(AppError):
    """输入不合法（必填项缺失、时间顺序错误、手机号格式错误等）。"""


class PermissionDenied(AppError):
    """角色不符、越权访问他人数据。"""


class NotFound(AppError):
    """对象不存在。"""


class Conflict(AppError):
    """对象状态冲突（重复报名、重复审核、已在候补等）。"""


class DeadlinePassed(AppError):
    """操作已超过截止时间。"""


class CapacityFull(AppError):
    """票种名额已满；调用方可据此询问是否候补。"""

    def __init__(self, message: str, ticket_type_id: int) -> None:
        super().__init__(message)
        self.ticket_type_id = ticket_type_id


# 注意：当前封禁由 PermissionService.require_active 抛 PermissionDenied 表达，
# 本异常暂未使用；保留作为更细的语义预留，后续可统一替换或删除。
class AccountBanned(AppError):
    """账号被封禁，不能进行购票、候补等新增交易。"""

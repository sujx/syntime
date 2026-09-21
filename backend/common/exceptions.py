"""统一业务异常（api.md 错误码体系）。

服务层抛 ``BizError`` 子类携带错误码；DRF 统一异常 handler（API 基座任务）按
``code`` 映射为统一返回结构，服务层不自行拼接响应体。
"""

from __future__ import annotations


class BizError(Exception):
    """业务异常基类：code 对应 api.md 统一错误码，message 为用户可见提示。"""

    code: int = 50000
    default_message: str = "系统异常"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message


class SyncWindowConflictError(BizError):
    """同步窗口已被占用（uk_sync_window）：运行中重复触发，后到者拒绝（E010）。"""

    code = 40900
    default_message = "任务进行中，请勿重复提交"

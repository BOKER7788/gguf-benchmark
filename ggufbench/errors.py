"""统一错误码、异常类型与错误响应构造。

约定（架构 §12.3 / §12.4）：
- 成功：``{"ok": true, ...payload}``
- 失败：``{"ok": false, "error": {"code": "E_XXX", "message": "中文可读信息"}}``
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """全局错误码枚举（值即对外暴露的字符串）。"""

    E_PY_VERSION = "E_PY_VERSION"            # Python < 3.11
    E_LLAMA_NOT_FOUND = "E_LLAMA_NOT_FOUND"  # llama-server 路径无效/不存在
    E_PORT_IN_USE = "E_PORT_IN_USE"          # 端口被占用
    E_DIR_NOT_FOUND = "E_DIR_NOT_FOUND"      # 扫描目录不存在
    E_NO_GGUF = "E_NO_GGUF"                  # 目录内无可用 gguf
    E_TASK_EXISTS = "E_TASK_EXISTS"          # 已有任务在跑（全局单任务）
    E_TASK_NOT_FOUND = "E_TASK_NOT_FOUND"    # 任务 id 不存在
    E_TASK_BUSY = "E_TASK_BUSY"              # 目标状态不允许该操作
    E_BAD_REQUEST = "E_BAD_REQUEST"          # 参数校验失败
    E_INTERNAL = "E_INTERNAL"                # 未捕获异常


# 错误码 → HTTP 状态码（默认映射，可在抛出时覆盖）
_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.E_PY_VERSION: 500,
    ErrorCode.E_LLAMA_NOT_FOUND: 400,
    ErrorCode.E_PORT_IN_USE: 409,
    ErrorCode.E_DIR_NOT_FOUND: 400,
    ErrorCode.E_NO_GGUF: 404,
    ErrorCode.E_TASK_EXISTS: 409,
    ErrorCode.E_TASK_NOT_FOUND: 404,
    ErrorCode.E_TASK_BUSY: 409,
    ErrorCode.E_BAD_REQUEST: 400,
    ErrorCode.E_INTERNAL: 500,
}


def default_status(code: ErrorCode) -> int:
    """返回错误码默认的 HTTP 状态码。"""
    return _HTTP_STATUS.get(code, 500)


class ApiError(Exception):
    """业务异常：携带错误码、可读信息与 HTTP 状态码。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message: str = message
        self.status_code: int = status_code if status_code is not None else default_status(code)

    def to_body(self) -> dict:
        """转换为统一错误响应体。"""
        return error_body(self.code, self.message)


def error_body(code: ErrorCode, message: str) -> dict:
    """构造统一错误响应体。"""
    return {"ok": False, "error": {"code": code.value, "message": message}}


def ok_body(**payload) -> dict:
    """构造统一成功响应体。"""
    return {"ok": True, **payload}


__all__ = [
    "ErrorCode",
    "ApiError",
    "error_body",
    "ok_body",
    "default_status",
]

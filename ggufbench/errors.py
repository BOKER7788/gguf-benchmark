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
    E_NETWORK = "E_NETWORK"                  # 网络请求失败（下载 llama.cpp 等）
    E_DIALOG = "E_DIALOG"                    # 无法弹出系统对话框
    E_UNSUPPORTED = "E_UNSUPPORTED"          # 当前平台/环境不支持该操作


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
    ErrorCode.E_NETWORK: 502,
    ErrorCode.E_DIALOG: 501,
    ErrorCode.E_UNSUPPORTED: 501,
}


# ---------------------------------------------------------------------------
# 人话化提示（P1-2）
#
# 面向零基础用户：每个错误码/失败原因都配「这是什么意思」+「你该怎么做」两行。
# UI 把它展示在错误信息下方，用户不必去翻文档。
# ---------------------------------------------------------------------------
HINTS: dict[str, dict[str, str]] = {
    "E_PY_VERSION": {
        "what": "你的 Python 版本太旧，本工具需要 3.11 或更高。",
        "how": "到 python.org 下载新版 Python（安装时勾选 Add python.exe to PATH），或直接用 start.bat 启动，它会引导你安装。",
    },
    "E_LLAMA_NOT_FOUND": {
        "what": "没找到 llama-server，它是真正执行推理的程序。",
        "how": "在「参数配置」里点「选择文件」指定 llama-server.exe；若还没有，点「一键获取 llama.cpp」自动下载。",
    },
    "E_PORT_IN_USE": {
        "what": "要用的端口已被别的程序占用。",
        "how": "在「参数配置」里把端口改成 8081 / 8090 等其它值，再重新开始。",
    },
    "E_DIR_NOT_FOUND": {
        "what": "你填的模型文件夹不存在。",
        "how": "点「选择文件夹」重新选一次，注意路径里不要有打错的字。",
    },
    "E_NO_GGUF": {
        "what": "这个文件夹里没有找到模型文件（.gguf）。",
        "how": "把下载好的 .gguf 模型放进该文件夹，或换一个含模型的文件夹。页面下方有模型下载指引。",
    },
    "E_TASK_EXISTS": {
        "what": "已经有一个测试任务在跑了，本工具同一时刻只允许一个。",
        "how": "等它跑完，或点「中断」结束当前任务后再开新的。",
    },
    "E_TASK_NOT_FOUND": {
        "what": "找不到这个测试任务（可能后端刚重启过，任务记录已清空）。",
        "how": "回到「④ 配置」重新点一次「开始测试」即可。",
    },
    "E_TASK_BUSY": {
        "what": "当前任务状态不允许这个操作。",
        "how": "等任务结束后再试。",
    },
    "E_BAD_REQUEST": {
        "what": "有参数填得不对，程序无法继续。",
        "how": "检查提示里指出的那一项，改成合理值后重试。",
    },
    "E_NETWORK": {
        "what": "网络请求失败，可能是网络不通或 GitHub 访问受限。",
        "how": "检查网络后重试；若一直失败，可手动到 github.com/ggml-org/llama.cpp 的 Releases 下载 Windows 版，解压后把 llama-server.exe 路径填进「参数配置」。",
    },
    "E_DIALOG": {
        "what": "没能弹出系统选择窗口（少数精简系统或远程桌面环境会这样）。",
        "how": "不用急，直接在输入框里手动粘贴完整路径也可以。",
    },
    "E_UNSUPPORTED": {
        "what": "当前系统不支持这个操作。",
        "how": "改用其它方式完成，或参考文档手动操作。",
    },
    "E_INTERNAL": {
        "what": "程序内部出错了。",
        "how": "看一下 reports/task.log 里的详细日志；重启一次工具通常能解决。",
    },
    # ---- 数据点失败原因（报告「状态」列的红色项）----
    "OOM_GPU": {
        "what": "显存不够，模型在这个上下文档位放不下。",
        "how": "换更小的上下文档位、换更小的量化版本（Q4 比 Q8 省一半显存），或在 BIOS 里给核显划分更多显存后重测。",
    },
    "MODEL_FAIL": {
        "what": "模型没能加载起来。",
        "how": "常见原因是文件不完整或不是有效的 .gguf。建议重新下载该模型文件，并确认分片文件（-00001-of-00002 之类）都在同一个文件夹里。",
    },
    "TIMEOUT": {
        "what": "这一个点跑得太久，超过了设定的超时时间。",
        "how": "调低上下文档位；或在「高级设置」里把单点超时调大。",
    },
    "OTHER": {
        "what": "这次运行失败了，原因不明确。",
        "how": "查看 reports/task.log 里对应时间的日志，通常能看到具体报错。",
    },
}


def hint_for(key: str) -> dict[str, str]:
    """返回错误码/失败原因对应的「什么意思 + 该怎么做」。

    未登记的值返回空字典，调用方应做好兜底。
    """
    return HINTS.get((key or "").strip().upper(), {})


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
    "HINTS",
    "hint_for",
]

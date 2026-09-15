"""日志初始化与日志目录工具。

日志格式（架构 §12.5）::

    [%(asctime)s] [%(levelname)s] [%(name)s] %(message)s

日志产物（架构 §12.5）：
- 任务级：``<output_dir>/task.log``
- 每模型：``<output_dir>/<model>/llama_stdout.log``、``llama_stderr.log``、``points.json``
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_SAFE_RE = re.compile(r"[^0-9A-Za-z._\u4e00-\u9fff-]+")


def safe_name(name: str) -> str:
    """将任意模型名转换为安全的文件/目录名片段。"""
    cleaned = _SAFE_RE.sub("_", name.strip())
    return cleaned.strip("_") or "model"


def setup_logging(level: int = logging.INFO, log_file: Path | None = None) -> None:
    """初始化根 logger（幂等：重复调用不会叠加 handler）。"""
    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)

    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        target = str(log_file.resolve())
        already = any(
            isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == target
            for h in root.handlers
        )
        if not already:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(formatter)
            root.addHandler(fh)

    # 降低第三方库噪声（httpx / httpcore 每次请求都会打 INFO）
    for noisy in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str = "ggufbench") -> logging.Logger:
    """获取具名 logger。"""
    return logging.getLogger(name)


def get_model_log_dir(output_dir: str | Path, model_name: str) -> Path:
    """返回并创建某模型的日志目录 ``<output_dir>/<safe_model>/``。"""
    path = Path(output_dir) / safe_name(model_name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_task_log_path(output_dir: str | Path) -> Path:
    """返回任务级日志文件路径（不创建）。"""
    return Path(output_dir) / "task.log"


def append_task_log(output_dir: str | Path, message: str, level: str = "INFO") -> None:
    """向任务级 ``task.log`` 追加一行（带时间戳，不依赖 logging 配置）。"""
    import time

    path = get_task_log_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime(DATE_FORMAT)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] [{level}] {message}\n")


__all__ = [
    "LOG_FORMAT",
    "DATE_FORMAT",
    "setup_logging",
    "get_logger",
    "safe_name",
    "get_model_log_dir",
    "get_task_log_path",
    "append_task_log",
]

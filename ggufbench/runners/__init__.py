"""运行器工厂 ``make_runner`` 与包导出（架构 Q10）。"""

from __future__ import annotations

from pathlib import Path

from ..logging_utils import get_logger
from ..models import BenchConfig, ModelMeta
from .base import LlamaServerRunner, is_port_in_use
from .mock_runner import MockRunner
from .real_runner import RealRunner

logger = get_logger("runners")


def _looks_like_real_server(config: BenchConfig) -> bool:
    """判断配置中的 llama-server 路径是否可用。"""
    path = config.llama_server_path.strip()
    if not path:
        return False
    candidate = Path(path).expanduser()
    return candidate.exists()


def make_runner(
    config: BenchConfig,
    model: ModelMeta,
    ctx_size: int,
    log_dir: Path,
) -> LlamaServerRunner:
    """按 ``runner_mode`` 选择运行器。

    - ``real``：强制真实运行器；
    - ``mock``：强制 MockRunner；
    - ``auto``：``llama_server_path`` 存在 → RealRunner，否则降级 MockRunner。
    """
    mode = config.runner_mode
    if mode == "mock":
        return MockRunner(config, model, ctx_size, log_dir)
    if mode == "real":
        return RealRunner(config, model, ctx_size, log_dir)
    # auto
    if _looks_like_real_server(config):
        return RealRunner(config, model, ctx_size, log_dir)
    logger.info("runner_mode=auto 且未找到 llama-server，降级 MockRunner")
    return MockRunner(config, model, ctx_size, log_dir)


__all__ = [
    "LlamaServerRunner",
    "MockRunner",
    "RealRunner",
    "make_runner",
    "is_port_in_use",
]

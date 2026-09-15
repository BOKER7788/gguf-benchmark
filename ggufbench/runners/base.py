"""``LlamaServerRunner`` 抽象基类 + 端口检测工具。

模板方法 ``restart_once`` 基于 ``start`` + ``wait_ready`` 实现"崩溃后重启一次"。
"""

from __future__ import annotations

import socket
from abc import ABC, abstractmethod
from pathlib import Path

from ..logging_utils import get_logger
from ..models import BenchConfig, ModelMeta, RunResult

logger = get_logger("runner")

DEFAULT_READY_TIMEOUT_S = 120.0


def is_port_in_use(host: str, port: int) -> bool:
    """检测端口是否被占用（架构 §7 ⑤）。

    能 ``bind`` 成功则未占用；``OSError``/``OverflowError``/``ValueError``
    （含非法端口）一律视为不可用（返回 True），避免上层崩溃。
    """
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return True
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind((host, port))
        return False
    except (OSError, OverflowError, ValueError):
        return True
    finally:
        sock.close()


class LlamaServerRunner(ABC):
    """llama-server 运行器抽象。"""

    def __init__(
        self,
        config: BenchConfig,
        model: ModelMeta,
        ctx_size: int,
        log_dir: Path,
    ) -> None:
        self.config: BenchConfig = config
        self.model: ModelMeta = model
        self.ctx_size: int = ctx_size
        self.log_dir: Path = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._restarted: bool = False

    # ---- 子类必须实现 ----
    @abstractmethod
    def start(self) -> None:
        """启动子进程（mock 仅记录参数）。"""
        raise NotImplementedError

    @abstractmethod
    def wait_ready(self, timeout_s: float = DEFAULT_READY_TIMEOUT_S) -> bool:
        """轮询 ``/health`` 直到就绪或超时。"""
        raise NotImplementedError

    @abstractmethod
    def tokenize(self, text: str) -> int:
        """调用 ``/tokenize`` 返回真实 token 数。"""
        raise NotImplementedError

    @abstractmethod
    def complete(self, prompt: str, n_predict: int) -> RunResult:
        """调用 ``/completion`` 执行一次推理。"""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """终止进程并释放端口。"""
        raise NotImplementedError

    @abstractmethod
    def is_alive(self) -> bool:
        """进程是否仍在运行。"""
        raise NotImplementedError

    # ---- 可选/模板方法 ----
    def build_cmd(self) -> list[str]:
        """返回完整启动命令（用于报告留档，架构决策 10 + §8.5）。

        注意：GPU 后端口由所选 llama.cpp 编译版本决定，**不是**命令行开关，
        因此此处不生成 ``--backend`` 之类并不存在的参数；后端口信息在报告
        硬件区块单独记录。
        """
        exe = self.config.llama_server_path or "llama-server"
        cmd = [
            exe,
            "-m",
            self.model.gguf_path,
            "-c",
            str(self.ctx_size),
            "-ngl",
            str(self.config.n_gpu_layers),
            "--threads",
            str(self.config.threads),
            "--port",
            str(self.config.port),
        ]
        cmd.extend(self.config.extra_args)
        return cmd

    def restart_once(self) -> bool:
        """崩溃后重启一次（每档仅允许一次）。返回重启后是否就绪。"""
        if self._restarted:
            return False
        self._restarted = True
        try:
            self.stop()
        except Exception:  # pragma: no cover - 清理失败不致命
            pass
        try:
            self.start()
        except Exception as exc:  # pragma: no cover - 环境相关
            logger.warning("restart start 失败: %s", exc)
            return False
        return self.wait_ready()


__all__ = ["LlamaServerRunner", "is_port_in_use", "DEFAULT_READY_TIMEOUT_S"]

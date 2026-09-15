"""``MockRunner``：确定性合成 timings，供开发机全链路（无 llama.cpp）。"""

from __future__ import annotations

import time
from pathlib import Path

from ..logging_utils import get_logger
from ..models import BenchConfig, ModelMeta, RunResult
from .base import LlamaServerRunner

logger = get_logger("mock_runner")


def _parse_size_b(model_size: str) -> float:
    """从 ``0.8B`` / ``35B`` 解析出参数规模（单位 B）；失败返回 1.0。"""
    value = model_size.strip().rstrip("Bb")
    try:
        return max(0.1, float(value))
    except ValueError:
        return 1.0


class MockRunner(LlamaServerRunner):
    """合成运行器：依据模型规模与输入长度给出确定性的吞吐数据。

    - prefill 吞吐随输入长度增长而衰减；
    - decode 吞吐随 ctx 增长而轻微衰减；
    - 通过 ``config.extra_args`` 中的 ``mock-fail-ctx=<n>`` 可注入失败，供手工自测。
    """

    def __init__(
        self,
        config: BenchConfig,
        model: ModelMeta,
        ctx_size: int,
        log_dir: Path,
    ) -> None:
        super().__init__(config, model, ctx_size, log_dir)
        self._started: bool = False
        self._fail_ctxs: set[int] = self._parse_fail_ctxs(config.extra_args)

    @staticmethod
    def _parse_fail_ctxs(extra_args: list[str]) -> set[int]:
        """解析 ``mock-fail-ctx=8000`` 之类的手工失败注入。"""
        result: set[int] = set()
        for arg in extra_args:
            if arg.startswith("mock-fail-ctx="):
                try:
                    result.add(int(arg.split("=", 1)[1]))
                except ValueError:
                    continue
        return result

    # ---- 生命周期 ----
    def start(self) -> None:
        """模拟启动：写一行日志，标记已启动。"""
        self._started = True
        logger.info("[mock] start model=%s ctx=%d", self.model.model_name, self.ctx_size)

    def stop(self) -> None:
        """模拟停止。"""
        self._started = False

    def is_alive(self) -> bool:
        """mock 始终存活（除非未启动）。"""
        return self._started

    def wait_ready(self, timeout_s: float = 120.0) -> bool:
        """mock 立即就绪。"""
        time.sleep(0.005)
        return True

    # ---- 推理接口 ----
    def tokenize(self, text: str) -> int:
        """近似 token 计数：约 4 字符 = 1 token。"""
        return max(1, round(len(text) / 4))

    def complete(self, prompt: str, n_predict: int) -> RunResult:
        """合成一次推理结果（确定性）。"""
        if self.ctx_size in self._fail_ctxs:
            return RunResult(
                ok=False,
                exit_code=1,
                stderr_tail="mock injected failure (out of memory) for ctx=%d" % self.ctx_size,
            )

        input_tokens = self.tokenize(prompt)
        size_b = _parse_size_b(self.model.model_size)

        prefill_base = 9000.0 / (size_b ** 0.5)                # 小模型更快
        prefill = prefill_base * (1.0 / (1.0 + input_tokens / 30000.0))
        decode_base = 200.0 / (size_b ** 0.5)
        decode = decode_base * (1.0 / (1.0 + self.ctx_size / 200000.0))

        # 确定性抖动（模拟多次测量差异，不是随机数）
        jitter = 1.0 + 0.01 * ((input_tokens + self.ctx_size // 1000) % 5 - 2)
        prefill *= jitter
        decode *= jitter

        prompt_ms = input_tokens / max(1.0, prefill) * 1000.0
        predicted_ms = n_predict / max(0.1, decode) * 1000.0
        return RunResult(
            prompt_tokens=input_tokens,
            prompt_ms=round(prompt_ms, 2),
            predicted_tokens=n_predict,
            predicted_ms=round(predicted_ms, 2),
            exit_code=0,
            timed_out=False,
            stderr_tail="",
            ok=True,
        )


__all__ = ["MockRunner"]

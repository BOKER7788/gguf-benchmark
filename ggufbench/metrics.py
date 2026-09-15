"""``MetricsParser``：中位数、tps/耗时换算、fail_reason 判定。"""

from __future__ import annotations

from statistics import median as _stat_median

from .models import BenchmarkPoint, BenchConfig, ModelMeta, RunResult

# ---- fail_reason 关键词表（架构 §7 ⑥）----
_OOM_KEYWORDS = (
    "out of memory",
    "oom",
    "failed to allocate",
    "cuda error: out of memory",
    "vk_error_out_of_device_memory",
    "hip out of memory",
    "unable to allocate",
    "ggml_vulkan",
    "insufficient memory",
    "vk_error",
)
_MODEL_KEYWORDS = (
    "failed to load model",
    "unknown model architecture",
    "invalid model",
    "gguf",
    "failed to open",
    "magic",
    "tensor",
    "corrupt",
    "not supported",
)


class MetricsParser:
    """指标聚合与失败归因。"""

    @staticmethod
    def median(values: list[float]) -> float:
        """中位数（空列表返回 0）。"""
        clean = [float(v) for v in values]
        if not clean:
            return 0.0
        return float(_stat_median(clean))

    @classmethod
    def classify_failure(cls, exit_code: int, stderr: str, timed_out: bool) -> str:
        """按退出码/超时/stderr 归类失败原因。"""
        if timed_out:
            return "TIMEOUT"
        lowered = (stderr or "").lower()
        if any(k in lowered for k in _OOM_KEYWORDS):
            return "OOM_GPU"
        if any(k in lowered for k in _MODEL_KEYWORDS):
            return "MODEL_FAIL"
        if exit_code not in (0, None):
            return "OTHER"
        return "OTHER"

    @classmethod
    def build_point(
        cls,
        runs: list[RunResult],
        meta: ModelMeta,
        ctx_size: int,
        input_tokens: int,
        config: BenchConfig,
    ) -> BenchmarkPoint:
        """由多次正式运行取中位数，构造成功数据点。"""
        prefill_list = [r.prompt_tokens / (r.prompt_ms / 1000.0) for r in runs if r.prompt_ms > 0]
        decode_list = [r.predicted_tokens / (r.predicted_ms / 1000.0) for r in runs if r.predicted_ms > 0]
        prompt_tokens_list = [float(r.prompt_tokens) for r in runs]

        return BenchmarkPoint(
            model_name=meta.model_name,
            model_size=meta.model_size,
            precision=meta.precision,
            n_chip=meta.n_chip,
            ctx_size=ctx_size,
            input_tokens=int(round(cls.median(prompt_tokens_list))) or input_tokens,
            output_tokens=config.output_tokens,
            prefill_tps=round(cls.median(prefill_list), 2),
            decode_tps=round(cls.median(decode_list), 2),
            vision_fps=0.0,  # 本轮纯文本，决策 7
            prefill_time_ms=round(cls.median([r.prompt_ms for r in runs]), 2),
            decode_time_ms=round(cls.median([r.predicted_ms for r in runs]), 2),
            success=True,
            error_msg="",
            fail_reason="",
            skipped=False,
        )

    @classmethod
    def failed_point(
        cls,
        meta: ModelMeta,
        ctx_size: int,
        input_tokens: int,
        result: RunResult,
        config: BenchConfig,
        *,
        skipped: bool = False,
        reason: str | None = None,
    ) -> BenchmarkPoint:
        """构造失败（或跳过）数据点。"""
        fail_reason = reason or cls.classify_failure(result.exit_code, result.stderr_tail, result.timed_out)
        if not fail_reason:
            fail_reason = "OTHER"
        error_msg = result.stderr_tail.strip()[:300] or f"运行失败（exit={result.exit_code}）"
        return BenchmarkPoint(
            model_name=meta.model_name,
            model_size=meta.model_size,
            precision=meta.precision,
            n_chip=meta.n_chip,
            ctx_size=ctx_size,
            input_tokens=input_tokens,
            output_tokens=config.output_tokens,
            prefill_tps=0.0,
            decode_tps=0.0,
            vision_fps=0.0,
            prefill_time_ms=0.0,
            decode_time_ms=0.0,
            success=False,
            error_msg=error_msg,
            fail_reason=fail_reason,  # type: ignore[arg-type]
            skipped=skipped,
        )


__all__ = ["MetricsParser"]

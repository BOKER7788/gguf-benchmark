"""``MetricsParser``：中位数、tps/耗时换算、fail_reason 判定。"""

from __future__ import annotations

from statistics import median as _stat_median

from .models import BenchmarkPoint, BenchConfig, ModelMeta, RunResult

# ---- 输入长度防呆阈值 ----
# 提示词构造用 /tokenize 校准到误差 < 2%，因此实测 prompt_n 低于目标 80% 即视为异常
# （正常情况实测≈目标；命中 KV cache 时实测会塌到个位数）。
_PREFILL_TOLERANCE = 0.8

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
        """由多次正式运行取中位数，构造成功数据点。

        防呆（P0 回归守卫）：``input_tokens`` 是本次请求的**目标** token 数，构造
        提示词时已用 ``/tokenize`` 校准到误差 < 2%。若实测回来的 ``prompt_n`` 明显
        低于目标，说明服务端并没有真正 prefill 整段输入（典型原因是命中 KV cache：
        ``cache_prompt`` 未关闭时，预热留下的缓存会让 ``prompt_n`` 只剩几个新增
        token）。这种数据一旦落进报告就是"看起来成功、数值偏低 50 倍"的静默错误，
        因此这里显式判为失败，而不是照单全收。
        """
        measured = int(round(cls.median([float(r.prompt_tokens) for r in runs])))
        if input_tokens > 0 and measured < input_tokens * _PREFILL_TOLERANCE:
            return BenchmarkPoint(
                model_name=meta.model_name,
                model_size=meta.model_size,
                precision=meta.precision,
                n_chip=meta.n_chip,
                ctx_size=ctx_size,
                input_tokens=input_tokens,
                output_tokens=config.output_tokens,
                success=False,
                error_msg=(
                    f"输入 token 数异常：目标 {input_tokens}，实测仅 {measured}。"
                    "通常是推理引擎复用了上一次请求的 KV cache（prompt 缓存未关闭），"
                    "导致 prefill 吞吐被严重低估；请确认 llama-server 请求带 "
                    "cache_prompt=false 后重测。"
                ),
                fail_reason="OTHER",
                skipped=False,
            )

        prefill_list = [r.prompt_tokens / (r.prompt_ms / 1000.0) for r in runs if r.prompt_ms > 0]
        decode_list = [r.predicted_tokens / (r.predicted_ms / 1000.0) for r in runs if r.predicted_ms > 0]

        return BenchmarkPoint(
            model_name=meta.model_name,
            model_size=meta.model_size,
            precision=meta.precision,
            n_chip=meta.n_chip,
            ctx_size=ctx_size,
            input_tokens=measured or input_tokens,
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

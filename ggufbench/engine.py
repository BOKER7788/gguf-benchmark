"""``BenchEngine``：双维度矩阵裁剪、串行编排、每档重启、失败状态机、事件回调。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from . import PROJECT_ROOT, __version__
from .hardware import HardwareCollector, get_collector
from .logging_utils import append_task_log, get_logger, get_model_log_dir
from .metrics import MetricsParser
from .models import (
    BenchmarkPoint,
    BenchConfig,
    HardwareInfo,
    ModelMeta,
    RunResult,
    TaskStatus,
)
from .prompt_builder import PromptBuilder
from .runners import make_runner
from .runners.base import LlamaServerRunner

logger = get_logger("engine")

EventCallback = Callable[[dict], None]
RunnerFactory = Callable[[BenchConfig, ModelMeta, int, Path], LlamaServerRunner]


class BenchEngine:
    """同步执行引擎（跑在后台线程，全局串行）。"""

    def __init__(
        self,
        config: BenchConfig,
        *,
        runner_factory: RunnerFactory = make_runner,
        hardware: HardwareCollector | None = None,
        prompt_builder: PromptBuilder | None = None,
        on_event: Optional[EventCallback] = None,
        report_builder: object | None = None,
        generate_reports: bool = True,
    ) -> None:
        self.config: BenchConfig = config
        self._runner_factory: RunnerFactory = runner_factory
        self._hardware: HardwareCollector = hardware or get_collector(runner_mode=config.runner_mode)
        self._prompt_builder: PromptBuilder = prompt_builder or PromptBuilder(config.prompt_text)
        self._on_event: Optional[EventCallback] = on_event
        self._report_builder = report_builder
        self.generate_reports: bool = generate_reports

        self.status: TaskStatus = TaskStatus()
        self.points: list[BenchmarkPoint] = []
        self.points_by_model: dict[str, list[BenchmarkPoint]] = {}
        self.launch_cmds: dict[str, dict[int, list[str]]] = {}
        self.hardware: HardwareInfo = HardwareInfo()
        self.reports: list[Path] = []

        self._abort = threading.Event()
        self._current_runner: Optional[LlamaServerRunner] = None
        self._restart_lock = threading.Lock()

        out = Path(config.output_dir)
        if not out.is_absolute():
            out = (PROJECT_ROOT / out).resolve()
        self.output_dir: Path = out
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ---- 矩阵裁剪 ----
    @staticmethod
    def build_matrix(ctx_levels: list[int], input_levels: list[int]) -> dict:
        """构造双维度矩阵，仅保留 ``input < ctx``（架构 §7 ①）。

        Returns:
            ``{"pairs": [(ctx, input), ...], "per_ctx": {ctx: [input, ...]}, "total": int}``
        """
        pairs: list[tuple[int, int]] = []
        per_ctx: dict[int, list[int]] = {}
        for ctx in sorted(set(ctx_levels)):
            valid_inputs = [i for i in sorted(set(input_levels)) if i < ctx]
            if not valid_inputs:
                continue
            per_ctx[ctx] = valid_inputs
            for inp in valid_inputs:
                pairs.append((ctx, inp))
        return {"pairs": pairs, "per_ctx": per_ctx, "total": len(pairs)}

    # ---- 运行 ----
    def run(self, models: list[ModelMeta]) -> None:
        """串行执行所有模型的全部档位，并在结束后生成报告。"""
        matrix = self.build_matrix(self.config.ctx_levels, self.config.input_levels)
        self.status.state = "running"
        self.status.model_total = len(models)
        self.status.points_total = matrix["total"] * len(models)
        self.status.message = "运行中"
        self._emit({"type": "state", "status": self.status.model_dump()})

        try:
            self.hardware = self._hardware.collect()
            for index, meta in enumerate(models, start=1):
                if self._abort.is_set():
                    break
                self.status.model_index = index
                self.status.current_model = meta.model_name
                meta.status = "running"
                append_task_log(self.output_dir, f"开始模型 {meta.model_name} ({index}/{len(models)})")
                self._emit({"type": "state", "status": self.status.model_dump()})

                model_points, launch = self._run_model(meta, matrix)
                self.points_by_model[meta.model_name] = model_points
                self.launch_cmds[meta.model_name] = launch

                if self._abort.is_set():
                    meta.status = "aborted"
                    break

            if self.generate_reports:
                self._generate_reports(models)

            self.status.state = "done"
            self.status.message = "已中断" if self._abort.is_set() else "全部完成"
            self.status.percent = 100.0 if not self._abort.is_set() else self.status.percent
            append_task_log(self.output_dir, f"任务结束: {self.status.message}")
        except Exception as exc:  # noqa: BLE001 - 顶层兜底，避免线程静默死亡
            logger.exception("引擎执行异常: %s", exc)
            self.status.state = "error"
            self.status.message = str(exc)
            append_task_log(self.output_dir, f"任务异常: {exc}", level="ERROR")
        finally:
            self.status.model_index = self.status.model_index
            self._emit({"type": "done", "status": self.status.model_dump()})

    def abort(self) -> None:
        """请求中断：置位 abort 事件并终止当前运行器。"""
        self._abort.set()
        runner = self._current_runner
        if runner is not None:
            try:
                runner.stop()
            except Exception:  # pragma: no cover - 清理失败不致命
                pass

    # ---- 单模型执行 ----
    def _run_model(
        self,
        meta: ModelMeta,
        matrix: dict,
        ) -> tuple[list[BenchmarkPoint], dict[int, list[str]]]:
        """执行单个模型的全部档位，返回 (数据点列表, 启动参数)。"""
        model_points: list[BenchmarkPoint] = []
        launch_cmds: dict[int, list[str]] = {}
        pairs: list[tuple[int, int]] = matrix["pairs"]
        consec_fail = 0
        skipped = False
        idx = 0

        for ctx in sorted(matrix["per_ctx"].keys()):
            if self._abort.is_set():
                break
            inputs: list[int] = matrix["per_ctx"][ctx]
            log_dir = get_model_log_dir(self.output_dir, meta.model_name)
            runner = self._runner_factory(self.config, meta, ctx, log_dir)
            self._current_runner = runner
            launch_cmds[ctx] = runner.build_cmd()
            append_task_log(self.output_dir, f"启动参数 ctx={ctx}: " + " ".join(runner.build_cmd()))

            started = self._safe_start(runner)
            ready = started and runner.wait_ready()
            if not ready and started:
                ready = runner.restart_once()  # 崩溃后重启一次（架构 §7 ④）

            if not ready:
                first_input = inputs[0]
                fail = MetricsParser.failed_point(
                    meta,
                    ctx,
                    first_input,
                    RunResult(ok=False, exit_code=1, stderr_tail="llama-server 启动失败：健康检查未通过"),
                    self.config,
                    reason="MODEL_FAIL",
                )
                model_points.append(fail)
                self._record_point(fail, idx)
                idx += 1
                consec_fail += 1
                self.status.consec_fail = consec_fail
                self._emit_point(fail)
                runner.stop()
                self._current_runner = None
                if consec_fail >= self.config.skip_after_fails:
                    skipped = True
                    self._mark_skipped(meta, pairs, idx, fail.fail_reason, model_points)
                    meta.status = "skipped"
                    break
                continue

            for inp in inputs:
                if self._abort.is_set():
                    break
                self.status.current_ctx = ctx
                self.status.current_input = inp
                point = self._measure_point(runner, meta, ctx, inp)
                model_points.append(point)
                self._record_point(point, idx)
                idx += 1

                if point.success:
                    consec_fail = 0
                else:
                    consec_fail += 1
                self.status.consec_fail = consec_fail
                self._emit_point(point)

                if consec_fail >= self.config.skip_after_fails:
                    skipped = True
                    self._mark_skipped(meta, pairs, idx, point.fail_reason, model_points)
                    meta.status = "skipped"
                    append_task_log(
                        self.output_dir,
                        f"模型 {meta.model_name} 连续失败 {consec_fail} 次，跳过剩余档位",
                    )
                    break

            runner.stop()
            self._current_runner = None
            if skipped or self._abort.is_set():
                break

        if not skipped and not self._abort.is_set():
            meta.status = "done"
        return model_points, launch_cmds

    def _safe_start(self, runner: LlamaServerRunner) -> bool:
        """安全启动运行器。"""
        try:
            runner.start()
            return True
        except Exception as exc:  # pragma: no cover - 环境相关
            logger.warning("运行器启动失败: %s", exc)
            return False

    def _mark_skipped(
        self,
        meta: ModelMeta,
        pairs: list[tuple[int, int]],
        start_idx: int,
        reason: str,
        model_points: list[BenchmarkPoint],
    ) -> None:
        """把该模型剩余全部档位标记为 skipped。"""
        for ctx, inp in pairs[start_idx:]:
            point = MetricsParser.failed_point(
                meta,
                ctx,
                inp,
                RunResult(ok=False, exit_code=0),
                self.config,
                skipped=True,
                reason=reason or "OTHER",
            )
            point.error_msg = "已跳过（连续失败）"
            model_points.append(point)
            self.status.points_done += 1
            self.points.append(point)
        self._update_percent()
        self._emit({"type": "state", "status": self.status.model_dump()})

    def _record_point(self, point: BenchmarkPoint, _idx: int) -> None:
        """登记数据点并更新状态。"""
        self.points.append(point)
        self.status.points_done += 1
        self.status.last_point = point
        self._update_percent()

    def _update_percent(self) -> None:
        """更新完成百分比。"""
        total = self.status.points_total or 1
        self.status.percent = round(min(100.0, self.status.points_done / total * 100.0), 1)

    # ---- 单点测量 ----
    def _measure_point(
        self,
        runner: LlamaServerRunner,
        meta: ModelMeta,
        ctx: int,
        input_tokens: int,
    ) -> BenchmarkPoint:
        """测量单个 (ctx, input) 点：预热 + 重复取中位数（架构 §7 ②）。"""
        prompt = self._prompt_builder.build(input_tokens, runner)
        out_tokens = self.config.output_tokens

        # 预热（丢弃结果）
        for _ in range(max(0, self.config.warmup_runs)):
            result = runner.complete(prompt, out_tokens)
            if not result.ok:
                if not result.timed_out and self._restart(runner):
                    result = runner.complete(prompt, out_tokens)
                if not result.ok:
                    return MetricsParser.failed_point(meta, ctx, input_tokens, result, self.config)

        runs: list[RunResult] = []
        attempts = 0
        max_attempts = self.config.repeat_runs + 2
        while len(runs) < self.config.repeat_runs and attempts < max_attempts:
            attempts += 1
            result = runner.complete(prompt, out_tokens)
            if not result.ok:
                if not result.timed_out and self._restart(runner):
                    result = runner.complete(prompt, out_tokens)
                if not result.ok:
                    return MetricsParser.failed_point(meta, ctx, input_tokens, result, self.config)
            runs.append(result)

        if not runs:
            return MetricsParser.failed_point(
                meta, ctx, input_tokens, RunResult(ok=False, exit_code=-1), self.config
            )
        point = MetricsParser.build_point(runs, meta, ctx, input_tokens, self.config)
        logger.info(
            "model=%s ctx=%d input=%d prefill=%.1f decode=%.1f",
            meta.model_name,
            ctx,
            point.input_tokens,
            point.prefill_tps,
            point.decode_tps,
        )
        return point

    def _restart(self, runner: LlamaServerRunner) -> bool:
        """串行化重启，避免并发。"""
        with self._restart_lock:
            return runner.restart_once()

    # ---- 事件 ----
    def _emit_point(self, point: BenchmarkPoint) -> None:
        """广播数据点事件。"""
        self._emit({"type": "point", "point": point.model_dump(), "status": self.status.model_dump()})

    def _emit(self, payload: dict) -> None:
        """调用外部事件回调（线程安全由调用方 TaskManager 负责）。"""
        if self._on_event is not None:
            try:
                self._on_event(payload)
            except Exception as exc:  # pragma: no cover - 回调异常不应影响执行
                logger.warning("事件回调异常: %s", exc)

    # ---- 报告生成 ----
    def _generate_reports(self, models: list[ModelMeta]) -> None:
        """生成单模型报告 + 总览报告 + points.json。"""
        from .report.builder import ReportBuilder

        builder = self._report_builder
        if builder is None:
            builder = ReportBuilder(tool_version=__version__, llama_version=self.config.llama_version)

        written: list[Path] = []
        for meta in models:
            points = self.points_by_model.get(meta.model_name, [])
            launch = self.launch_cmds.get(meta.model_name, {})
            html = builder.build_model(meta, points, self.hardware, self.config, launch)
            path = builder.resolve_report_path(self.output_dir, meta.model_name, meta.precision)
            builder.write(path, html)
            builder.write_points_json(self.output_dir, meta, points, self.hardware, self.config, launch)
            written.append(path)

        overview_html = builder.build_overview(models, self.points, self.hardware, self.config)
        overview_path = self.output_dir / "overview.html"
        builder.write(overview_path, overview_html)
        builder.write_all_points_json(self.output_dir, models, self.points, self.hardware, self.config)

        self.reports = written + [overview_path]
        append_task_log(self.output_dir, "报告已生成: " + ", ".join(str(p) for p in self.reports))


__all__ = ["BenchEngine"]

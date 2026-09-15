"""C. 失败跳过状态机（P0，最容易写错）。

用可控的 ``CtlRunner`` 精确编排每次 ``complete()`` 的返回，验证：
- 连续 2 次失败 → 剩余档位全部 skipped 且停止该模型；
- 失败→成功→失败 不被误判（成功清零计数）；
- 崩溃重启一次成功不额外计失败；重启仍失败则计失败。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from _harness import Suite

from ggufbench.engine import BenchEngine
from ggufbench.hardware import GenericHardwareCollector
from ggufbench.models import BenchConfig, ModelMeta, RunResult
from ggufbench.runners.base import LlamaServerRunner


class CtlRunner(LlamaServerRunner):
    """脚本化运行器：按队列返回 wait_ready / complete 结果。"""

    def __init__(self, config, model, ctx, log_dir, ready_seq, complete_seq):
        super().__init__(config, model, ctx, log_dir)
        self.ready_seq = list(ready_seq)
        self.complete_seq = list(complete_seq)
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        pass

    def is_alive(self) -> bool:
        return True

    def wait_ready(self, timeout_s: float = 120.0) -> bool:
        return self.ready_seq.pop(0) if self.ready_seq else True

    def tokenize(self, text: str) -> int:
        return max(1, round(len(text) / 4))

    def complete(self, prompt: str, n_predict: int) -> RunResult:
        mode = self.complete_seq.pop(0) if self.complete_seq else "ok"
        if mode == "ok":
            n = self.tokenize(prompt)
            return RunResult(
                prompt_tokens=n, prompt_ms=1000.0,
                predicted_tokens=n_predict, predicted_ms=1000.0,
                exit_code=0, ok=True,
            )
        if mode == "timeout":
            return RunResult(ok=False, timed_out=True, exit_code=-1, stderr_tail="timeout")
        return RunResult(ok=False, exit_code=1, stderr_tail="boom")


class TrackedFactory:
    """记录每次被创建的 (ctx) 与运行器实例。"""

    def __init__(self, ready_map, complete_map):
        self.ready_map = ready_map
        self.complete_map = complete_map
        self.created_ctx: list[int] = []
        self.runners: list[CtlRunner] = []

    def __call__(self, config, model, ctx, log_dir):
        self.created_ctx.append(ctx)
        r = CtlRunner(config, model, ctx, log_dir,
                      self.ready_map.get(ctx, [True]), self.complete_map.get(ctx, []))
        self.runners.append(r)
        return r


def _model(name="TestModel-2B", size="2B"):
    return ModelMeta(model_name=name, model_size=size, gguf_path="/tmp/x.gguf", precision="w8a8")


def _engine(ctx_levels, input_levels, factory, skip_after_fails=2, tmp=None):
    cfg = BenchConfig(
        ctx_levels=ctx_levels,
        input_levels=input_levels,
        warmup_runs=0,
        repeat_runs=1,
        skip_after_fails=skip_after_fails,
        runner_mode="mock",
        output_dir=tmp,
    )
    return BenchEngine(
        cfg,
        runner_factory=factory,
        hardware=GenericHardwareCollector(),
        generate_reports=False,
    )


def run() -> Suite:
    s = Suite("C. 失败跳过状态机")
    tmp = tempfile.mkdtemp(prefix="ggufbench_qa_")

    # ---- C1 连续 2 次失败 → 剩余全部 skipped 且停止该模型 ----
    fac = TrackedFactory({}, {8000: ["fail", "fail", "fail", "fail"]})
    eng = _engine([8000, 16000], [250, 500, 1000, 2000, 4000, 8000], fac, tmp=tmp)
    m = _model()
    eng.run([m])
    skipped = [p for p in eng.points if p.skipped]
    s.eq("C1", "总点数 == 11", len(eng.points), 11)
    s.eq("C1b", "连续 2 失败后剩余 9 个点全部 skipped", len(skipped), 9)
    s.check("C1c", "所有 skipped 点 skipped==True 且 success==False",
            all(p.skipped and not p.success for p in skipped))
    s.check("C1d", "停止测试该模型（未再创建 ctx=16000 运行器）",
            16000 not in fac.created_ctx, f"created_ctx={fac.created_ctx}")
    s.eq("C1e", "模型状态标记为 skipped", m.status, "skipped")
    s.eq("C1f", "失败点数 == 2", sum(1 for p in eng.points if not p.success and not p.skipped), 2)

    # ---- C2 反向用例：失败→成功→失败 不应被误判为连续 2 次失败 ----
    # 用 timeout 失败（不触发 restart，恰好消耗 1 次 complete），精确编排点级结果：
    #   fail, ok, fail, ok, ok  → consec 从未达到 2
    fac2 = TrackedFactory({}, {8000: ["timeout", "ok", "timeout", "ok", "ok"]})
    eng2 = _engine([8000, 16000], [250, 500, 1000, 2000, 4000, 8000], fac2, tmp=tmp)
    m2 = _model("ReverseCase")
    eng2.run([m2])
    s.eq("C2", "失败→成功→失败 后无 skipped 点", len([p for p in eng2.points if p.skipped]), 0)
    s.eq("C2b", "模型正常跑完（status=done）", m2.status, "done")
    s.eq("C2c", "全部 11 个点均被记录", len(eng2.points), 11)
    s.eq("C2d", "成功清零：末尾 consec_fail == 0", eng2.status.consec_fail, 0)
    s.check("C2e", "两个 ctx 都被执行", 8000 in fac2.created_ctx and 16000 in fac2.created_ctx)
    s.eq("C2f", "失败点数 == 2（250 与 1000）",
          sum(1 for p in eng2.points if not p.success), 2)

    # ---- C2g 文档化：restart_once 每档仅一次（同 ctx 第二次失败不再重启）----
    fac2g = TrackedFactory({}, {8000: ["fail", "fail", "fail"]})
    eng2g = _engine([8000], [250, 500], fac2g, tmp=tmp)
    eng2g.run([_model("RestartOncePerCtx")])
    restart_calls = [r._restarted for r in fac2g.runners]
    s.check("C2g", "restart_once 每档仅触发一次（_restarted=True）",
            all(restart_calls) and len(fac2g.runners) == 1,
            f"runners={len(fac2g.runners)} _restarted={restart_calls}")

    # ---- C3 崩溃重启一次成功 → 该点成功且不额外计失败 ----
    fac3 = TrackedFactory({}, {8000: ["fail", "ok"]})
    eng3 = _engine([8000], [250], fac3, tmp=tmp)
    eng3.run([_model("RestartOK")])
    s.eq("C3", "重启后成功：点 success==True", eng3.points[0].success, True)
    s.eq("C3b", "重启后成功：不额外计失败（consec_fail==0）", eng3.status.consec_fail, 0)

    # ---- C4 崩溃两次（重启仍失败）→ 判失败并计入 consec_fail ----
    fac4 = TrackedFactory({}, {8000: ["fail", "fail"]})
    eng4 = _engine([8000], [250], fac4, tmp=tmp)
    eng4.run([_model("RestartFail")])
    s.eq("C4", "重启仍失败：点 success==False", eng4.points[0].success, False)
    s.eq("C4b", "重启仍失败：计入 consec_fail==1", eng4.status.consec_fail, 1)
    s.check("C4c", "失败原因属枚举值", eng4.points[0].fail_reason in
            ("OOM_GPU", "MODEL_FAIL", "TIMEOUT", "OTHER", ""),
            f"fail_reason={eng4.points[0].fail_reason!r}")

    # ---- C5 启动时崩溃一次、重启成功 → 正常测量 ----
    fac5 = TrackedFactory({8000: [False, True]}, {})
    eng5 = _engine([8000], [250, 500], fac5, tmp=tmp)
    eng5.run([_model("StartCrashRecover")])
    s.eq("C5", "启动崩溃一次后恢复：2 点全成功",
          [p.success for p in eng5.points], [True, True])

    # ---- C6 启动连续崩溃两次 → 该点判失败(ModelLoadFail) ----
    fac6 = TrackedFactory({8000: [False, False]}, {})
    eng6 = _engine([8000], [250, 500], fac6, tmp=tmp)
    eng6.run([_model("StartCrashTwice")])
    s.check("C6", "启动崩溃两次：至少 1 个失败点", any(not p.success for p in eng6.points),
            f"points={[(p.success, p.fail_reason) for p in eng6.points]}")
    fails = [p for p in eng6.points if not p.success]
    s.check("C6b", "启动失败归因为 MODEL_FAIL", fails and fails[0].fail_reason == "MODEL_FAIL",
            f"fail_reason={[p.fail_reason for p in fails]}")
    s.eq("C6c", "计入 consec_fail==1", eng6.status.consec_fail, 1)

    # ---- C7 consec_fail 跨 ctx 边界持续累计 ----
    fac7 = TrackedFactory({}, {8000: ["ok", "fail", "fail"], 16000: ["fail", "fail"]})
    eng7 = _engine([8000, 16000], [250, 4000, 8000], fac7, tmp=tmp)
    m7 = _model("CrossCtx")
    eng7.run([m7])
    s.eq("C7", "跨 ctx 累计：最后 2 点被 skipped",
          len([p for p in eng7.points if p.skipped]), 2)
    s.eq("C7b", "跨 ctx 累计：模型标记 skipped", m7.status, "skipped")

    return s

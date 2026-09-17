"""J. 体量可行性与 mock 免责声明（v1.1.2 新增）。

把 v1.1.1 暴露的三个问题固化成正向/反向断言：

1. **体量可行性**：224 GB 的模型在 64 GB 机器上不可能加载，必须被算出来、
   写进报告、并在 real 模式下直接拦截（旧版照跑不误且报告不显示体积）。
2. **mock 免责声明**：mock 报告不得再声称「数据由本机 llama.cpp 后端实测」
   （旧版页脚与同一文档里的 mock 警示条直接矛盾）。
3. **硬件采集与 runner_mode 解耦**：旧版在 mock 下强制通用采集器，Windows 上
   导致「内存大小：未知」——恰好抹掉了判断体量的必需输入。
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from _harness import PROJECT_ROOT, Suite

from ggufbench.feasibility import (
    LEVEL_IMPOSSIBLE,
    LEVEL_OK,
    LEVEL_TIGHT,
    LEVEL_UNKNOWN,
    judge,
    memory_capacity_gb,
    weights_gib,
)
from ggufbench.hardware import (
    GenericHardwareCollector,
    HardwareCollector,
    WindowsHardwareCollector,
    get_collector,
)
from ggufbench.models import BenchConfig, BenchmarkPoint, HardwareInfo, ModelMeta
from ggufbench.report.builder import ReportBuilder

# 本机形态的硬件快照：64 GB 物理内存 + UMA 核显（显存与内存共享同一块）
HW_UMA = HardwareInfo(
    cpu_model="TestCPU", host_model="TestHost", ram_gb=61.6,
    os_version="Windows 11", gpu="Test GPU", gpu_backend="vulkan", uma_vram_gb=30.0,
)

_BIG_MB = 229445.15          # 397B Q4_K_M 的 7 个分片合计（约 224 GiB）
_SMALL_MB = 774.23           # 0.8B Q8_0


def _point(name: str, size: str, ok: bool = True) -> BenchmarkPoint:
    return BenchmarkPoint(
        model_name=name, model_size=size, precision="w4a8",
        ctx_size=4000, input_tokens=250, prefill_tps=100.0, decode_tps=10.0,
        success=ok, fail_reason="" if ok else "OOM_GPU",
        error_msg="" if ok else "out of memory",
    )


class _StaticCollector(HardwareCollector):
    """固定返回给定硬件快照（避免测试真的去起 PowerShell）。"""

    def __init__(self, hw: HardwareInfo) -> None:
        self._hw = hw

    def collect(self) -> HardwareInfo:
        return self._hw


def run() -> Suite:
    s = Suite("J. 体量可行性与 mock 免责声明")

    meta_big = ModelMeta(model_name="Qwen3.5-397B-A17B-Q4_K_M", model_size="397B",
                         gguf_path="/big.gguf", file_size_mb=_BIG_MB)
    meta_small = ModelMeta(model_name="Qwen3.5-0.8B-Q8_0", model_size="0.8B",
                           gguf_path="/small.gguf", file_size_mb=_SMALL_MB)
    meta_tight = ModelMeta(model_name="Model-55B-Q4_K_M", model_size="55B",
                           gguf_path="/t.gguf", file_size_mb=54000.0)

    # =====================================================================
    #  1. 可行性判断
    # =====================================================================
    v_big = judge(meta_big, HW_UMA)
    s.eq("J1", "397B(224 GiB) 在 64GB 机器上判为「物理上装不下」",
         v_big.level, LEVEL_IMPOSSIBLE)
    s.check("J2", "结论里给出权重体积与内存倍数",
            f"{v_big.weights_gib:.1f} GiB" in v_big.detail and "倍" in v_big.detail,
            v_big.detail[:120])
    s.check("J3", "给出可操作的替代方案（降量化/换模型/加内存）",
            len(v_big.reasons) >= 2 and all(isinstance(r, str) and r for r in v_big.reasons),
            str(v_big.reasons))

    s.eq("J4", "0.8B(0.76 GiB) 判为可加载", judge(meta_small, HW_UMA).level, LEVEL_OK)
    s.eq("J5", "55B(52.7 GiB, 86%) 判为内存紧张", judge(meta_tight, HW_UMA).level, LEVEL_TIGHT)

    # UMA 核显与系统共享物理内存 → 容量不能把显存再加一遍
    s.check("J6", "UMA 核显下容量取物理内存而非「内存+显存」",
            abs(memory_capacity_gb(HW_UMA) - 61.6) < 0.01,
            f"capacity={memory_capacity_gb(HW_UMA)}")
    s.check("J7", "独显（显存 > 物理内存）时按两者之和估算",
            abs(memory_capacity_gb(HardwareInfo(ram_gb=16.0, uma_vram_gb=24.0)) - 40.0) < 0.01)

    v_unknown = judge(meta_big, HardwareInfo())
    s.eq("J8", "内存未知时判为「无法判断」（不臆测）", v_unknown.level, LEVEL_UNKNOWN)
    s.check("J9", "无法判断时说明缺了哪项输入",
            "内存" in v_unknown.detail or "体积" in v_unknown.detail, v_unknown.detail)

    s.check("J10", "weights_gib 换算正确（MiB → GiB）",
            abs(weights_gib(_BIG_MB) - 224.07) < 0.05, f"{weights_gib(_BIG_MB):.2f}")

    # =====================================================================
    #  2. 报告：体量区块 + mock 免责声明（正向）
    # =====================================================================
    cfg_mock = BenchConfig(runner_mode="mock")
    cfg_real = BenchConfig(runner_mode="real")
    launch = {4000: ["llama-server", "-m", "/big.gguf", "-c", "4000", "-ngl", "99"]}
    builder = ReportBuilder("1.1.2")

    html_mock = builder.build_model(meta_big, [_point(meta_big.model_name, "397B")],
                                    HW_UMA, cfg_mock, launch)
    html_real = builder.build_model(meta_big, [_point(meta_big.model_name, "397B")],
                                    HW_UMA, cfg_real, launch)

    s.check("J11", "报告含「模型体量与内存」区块", 'class="footprint"' in html_mock)
    s.check("J12", "报告结论列标注「物理上装不下」", "物理上装不下" in html_mock)
    s.check("J13", "报告写明本机可用内存数值", "61.6 GB" in html_mock)
    s.check("J14", "报告显示权重体积（GiB）", f"{weights_gib(_BIG_MB):.1f} GiB" in html_mock)
    s.check("J15", "装不下的模型给出可尝试的替代方案",
            "换更小的量化版本" in html_mock)

    # =====================================================================
    #  3. mock 免责声明（反向：旧版的矛盾表述必须消失）
    # =====================================================================
    s.check("J16", "mock 报告页脚不再声称「数据由本机 llama.cpp 后端实测」",
            "数据由本机 llama.cpp 后端实测" not in html_mock)
    s.check("J17", "mock 报告页脚显式声明未调用推理",
            "并未调用 llama.cpp 推理" in html_mock)
    s.check("J18", "real 报告页脚仍保留「后端实测」表述",
            "数据由本机 llama.cpp 后端实测" in html_real)
    s.check("J19", "real 报告不出现 mock 警示条", 'class="mock-banner' not in html_real)

    s.check("J20", "显式 mock 时文案为「你选择了 mock」而非甩锅 llama-server",
            "你选择了 mock" in html_mock and "未检测到可用的 llama-server" not in html_mock)
    s.check("J21", "警示条说明数字来自模型名公式，且再大的模型也会显示成功",
            "按模型名里的参数规模算出来的合成值" in html_mock and "装不下" in html_mock)
    s.check("J22", "mock 报告标注启动参数「实际并未执行」",
            "实际并未执行" in html_mock)

    # auto 降级（路径无效）时仍应归因于「未检测到 llama-server」
    cfg_degrade = BenchConfig(runner_mode="auto", llama_server_path="/definitely/not/here")
    html_degrade = builder.build_model(meta_small, [_point("Qwen3.5-0.8B-Q8_0", "0.8B")],
                                       HW_UMA, cfg_degrade, {})
    s.check("J23", "auto 降级时归因为「未检测到可用的 llama-server」",
            "未检测到可用的 llama-server" in html_degrade
            and "你选择了 mock" not in html_degrade)

    # =====================================================================
    #  4. 报告结构契约未被破坏
    # =====================================================================
    data = json.loads(re.search(r"const DATA=(.*?); const MODELS=", html_mock, re.S).group(1))
    s.eq("J24", "DATA 字段数仍为 16（14 业务 + fail_reason/skipped）", len(data[0]), 16)
    s.eq("J25", "汇总表仍为 10 列",
         len(re.findall(r"thCell\('([a-z]+)', '([^']+)'\)", html_mock)), 10)
    for item in ["CPU 型号", "主机型号", "内存大小", "系统版本"]:
        s.check("J26", f"硬件区块保留「{item}」", item in html_mock)
    s.check("J27", "报告仍为零外部引用（无 CDN）",
            not re.findall(r'(?:src|href)="https?://', html_mock))

    # =====================================================================
    #  5. 硬件采集与 runner_mode 解耦
    # =====================================================================
    coll_mock = get_collector(runner_mode="mock")
    if sys.platform.startswith("win"):
        s.check("J28", "Windows 上 mock 模式不再降级为通用采集器",
                isinstance(coll_mock, WindowsHardwareCollector),
                type(coll_mock).__name__)
    else:
        s.check("J28", "非 Windows 上仍用通用采集器",
                isinstance(coll_mock, GenericHardwareCollector),
                type(coll_mock).__name__)

    generic_ram = GenericHardwareCollector._ram_gb()
    s.check("J29", "通用采集器能采到物理内存（Windows 走 ctypes）",
            generic_ram > 1.0, f"ram_gb={generic_ram}")

    # =====================================================================
    #  6. 引擎在 real 模式下拦截「装不下」的模型
    # =====================================================================
    from ggufbench.engine import BenchEngine
    from ggufbench.models import RunResult

    calls: list[str] = []

    def _never_called(config, model, ctx, log_dir):  # noqa: ANN001
        calls.append(model.model_name)
        raise AssertionError("体积超限的模型不应创建运行器")

    with tempfile.TemporaryDirectory(prefix="ggufbench_j_") as d:
        cfg = BenchConfig(runner_mode="real", output_dir=d, ctx_levels=[4000],
                          input_levels=[250, 500], warmup_runs=0, repeat_runs=1)
        engine = BenchEngine(cfg, runner_factory=_never_called,
                             hardware=_StaticCollector(HW_UMA), generate_reports=False)
        engine.run([meta_big])

        s.check("J30", "real 模式下体积超限的模型不创建运行器（不尝试加载）",
                calls == [], f"calls={calls}")
        s.eq("J31", "为其生成完整数量的失败点", len(engine.points), 2)
        s.check("J32", "失败原因归为 OOM_GPU",
                all(p.fail_reason == "OOM_GPU" for p in engine.points),
                str([p.fail_reason for p in engine.points]))
        s.check("J33", "失败信息说明体积超限且未尝试加载",
                all("体积超限" in p.error_msg for p in engine.points),
                engine.points[0].error_msg[:120] if engine.points else "")
        s.check("J34", "任务状态标记为已跳过",
                meta_big.model_name in engine.skipped_models
                and "跳过" in engine.status.message,
                engine.status.message)
        # 回归：引擎会给模型写状态，而 pydantic 默认不校验赋值。
        # 若写入的值不在 ModelStatus 枚举内，模型对象再经由 API 回传时会被
        # 服务端拒绝（HTTP 422）—— J37 曾因此失败。
        try:
            ModelMeta(**meta_big.model_dump())
            s.check("J34b", "引擎写完状态后模型仍通过 ModelMeta 校验（枚举未越界）", True)
        except Exception as exc:  # noqa: BLE001
            s.check("J34b", "引擎写完状态后模型仍通过 ModelMeta 校验（枚举未越界）",
                    False, f"status={meta_big.status!r} err={exc}")

    # 反向：体积正常的模型不应被拦截
    with tempfile.TemporaryDirectory(prefix="ggufbench_j2_") as d2:
        cfg2 = BenchConfig(runner_mode="real", output_dir=d2, ctx_levels=[4000],
                           input_levels=[250], warmup_runs=0, repeat_runs=1)
        seen: list[str] = []

        def _fake_runner(config, model, ctx, log_dir):  # noqa: ANN001
            seen.append(model.model_name)

            class _R:
                def build_cmd(self):
                    return ["llama-server", "-m", model.gguf_path]

                def start(self):
                    return True

                def wait_ready(self, timeout_s: float = 120.0):
                    return True

                def tokenize(self, text: str):
                    # 必须与文本长度成比例：常量会让 prompt 校准无限增长（MemoryError）
                    return max(1, round(len(text) / 4))

                def complete(self, prompt: str, n_predict: int):
                    return RunResult(prompt_tokens=max(1, round(len(prompt) / 4)),
                                     prompt_ms=10.0,
                                     predicted_tokens=8, predicted_ms=10.0, ok=True)

                def stop(self):
                    return None

                def is_alive(self):
                    return True

                def restart_once(self):
                    return False

            return _R()

        engine2 = BenchEngine(cfg2, runner_factory=_fake_runner,
                              hardware=_StaticCollector(HW_UMA), generate_reports=False)
        engine2.run([meta_small])
        s.eq("J35", "体积正常的模型正常进入测量", seen, ["Qwen3.5-0.8B-Q8_0"])
        s.check("J36", "正常模型不被标记为跳过", engine2.skipped_models == [])

    # =====================================================================
    #  7. A7 预览接口返回体量预判（界面据此提前告警）
    # =====================================================================
    try:
        from fastapi.testclient import TestClient

        from ggufbench.app import create_app

        client = TestClient(create_app())
        r = client.post("/api/tasks/preview",
                        json={"models": [meta_big.model_dump(), meta_small.model_dump()],
                              "config": {"ctx_levels": [4000], "input_levels": [250]}})
        body = r.json()
        s.eq("J37", "A7 预览 200", r.status_code, 200)
        feas = {f["model"]: f for f in body.get("feasibility", [])}
        s.eq("J38", "A7 返回每个模型的可行性结论", len(feas), 2)
        s.check("J39", "A7 把 397B 标为 impossible",
                feas.get(meta_big.model_name, {}).get("level") == LEVEL_IMPOSSIBLE,
                str(feas.get(meta_big.model_name, {}).get("level")))
        s.check("J40", "A7 给出本机内存数值", isinstance(body.get("memory_gb"), (int, float)),
                str(body.get("memory_gb")))
        s.check("J41", "A7 汇总最严重档位",
                body.get("feasibility_worst") == LEVEL_IMPOSSIBLE,
                str(body.get("feasibility_worst")))
    except Exception as exc:  # pragma: no cover
        s.check("J37", "A7 预览接口可用", False, str(exc))

    return s

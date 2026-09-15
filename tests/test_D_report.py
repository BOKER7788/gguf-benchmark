"""D. 报告正确性（P0）——与黄金样本逐字段比对。

解析 ``reports/overview.html`` 与 ``reports/*.html``：
零外部引用、DATA 14 字段、10 列表头、内联 CSS/JS/SVG、硬件区块、
fail_reason 枚举、OOM 横幅、启动参数留档、文件名冲突后缀。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from _harness import PROJECT_ROOT, Suite

from ggufbench.models import BenchConfig, BenchmarkPoint, HardwareInfo, ModelMeta
from ggufbench.report.builder import ReportBuilder

# 上游参考报告（黄金样本）。非必需，未提供时相关比对退回内置字段基准。
GOLDEN = Path(os.environ.get(
    "GGUF_BENCH_GOLDEN",
    PROJECT_ROOT / "docs" / "golden-sample" / "395-result.html",
))
REPORTS = PROJECT_ROOT / "reports"
EXPECTED_FIELDS = [
    "model_name", "model_size", "precision", "n_chip", "ctx_size", "input_tokens",
    "output_tokens", "prefill_tps", "decode_tps", "vision_fps", "prefill_time_ms",
    "decode_time_ms", "success", "error_msg",
]
EXPECTED_HEADERS = [
    "Ctx(k)", "Input(k)", "Prefill(tps)", "Decode(tps)", "P-Time(ms)",
    "D-Time(ms)", "Vision(fps)", "精度", "芯片数", "状态",
]


def _extract_data(txt: str):
    m = re.search(r"const DATA=(.*?); const MODELS=", txt, re.S)
    if not m:
        m = re.search(r"const DATA ?= ?(.*?);", txt, re.S)
    return json.loads(m.group(1))


def _extract_headers(txt: str):
    # 报告内嵌 CLIENT_JS：thCell('key', 'label') 的顺序即列序
    return re.findall(r"thCell\('([a-z]+)', '([^']+)'\)", txt)


def _external_refs(txt: str) -> list[str]:
    """真正会导致外部网络加载的引用（排除 SVG xmlns 命名空间）。"""
    refs: list[str] = []
    refs += re.findall(r'<link[^>]+href="https?://[^"]+"', txt)
    refs += re.findall(r'<script[^>]+src="https?://[^"]+"', txt)
    refs += re.findall(r'<img[^>]+src="https?://[^"]+"', txt)
    refs += re.findall(r"@import\s+(?:url\()?['\"]?https?://", txt)
    refs += re.findall(r'url\(\s*["\']?https?://[^)]+\)', txt)
    return refs


def run() -> Suite:
    s = Suite("D. 报告正确性")
    overview = (REPORTS / "overview.html").read_text(encoding="utf-8")
    model_files = sorted(p for p in REPORTS.glob("*.html") if p.name != "overview.html")
    s.check("D0", "存在 overview.html 与至少 1 个模型报告", bool(model_files), f"model_files={model_files}")

    # 黄金样本（上游参考报告）为可选输入：
    # 可用环境变量 GGUF_BENCH_GOLDEN 指定；缺省找 docs/golden-sample/395-result.html。
    # 未提供时退回内置 EXPECTED_FIELDS 基准，而不是让整套测试失败。
    if GOLDEN.exists():
        golden_txt = GOLDEN.read_text(encoding="utf-8")
        golden_data = _extract_data(golden_txt)
        golden_fields = list(golden_data[0].keys())
    else:
        s.note(f"未找到黄金样本 {GOLDEN}；改用内置 EXPECTED_FIELDS 作为字段基准。"
               f"如需完整逐字段比对，请设置环境变量 GGUF_BENCH_GOLDEN 指向该报告。")
        golden_fields = list(EXPECTED_FIELDS)

    # ---- D1 零外部引用 ----
    all_refs = []
    for name, txt in [("overview", overview)] + [(p.name, p.read_text(encoding="utf-8")) for p in model_files]:
        refs = _external_refs(txt)
        all_refs += [(name, r) for r in refs]
    s.check("D1", "零外部资源引用（link/script/img/@import/url）", not all_refs, f"发现: {all_refs[:5]}")

    raw_http = re.findall(r"https?://[^\s\"'<>]*", overview)
    non_ns = [u for u in raw_http if "www.w3.org" not in u]
    s.check("D1b", "原始 http(s):// 仅为 SVG xmlns 命名空间",
            not non_ns, f"非命名空间的 URL: {non_ns[:5]}; 全部={raw_http}")

    # ---- D2 DATA 14 字段与黄金样本一致 ----
    ov_data = _extract_data(overview)
    s.eq("D2", "DATA 前 14 字段 == 黄金样本字段（同序）", list(ov_data[0].keys())[:14], golden_fields)
    s.check("D2b", "黄金样本字段集 ⊆ 报告字段集",
            set(golden_fields) <= set(ov_data[0].keys()),
            f"缺失={set(golden_fields) - set(ov_data[0].keys())}")
    extra = [k for k in ov_data[0].keys() if k not in golden_fields]
    s.eq("D2c", "额外字段仅为 x-extension", set(extra), {"fail_reason", "skipped"})

    # ---- D3 表头 10 列且顺序正确 ----
    hs = _extract_headers(overview)
    labels = [h[1] for h in hs]
    s.eq("D3", "表头 10 列且列序正确", labels, EXPECTED_HEADERS)

    # ---- D4 内联 style/script/svg ----
    s.check("D4", "内联 <style>", "<style>" in overview)
    s.check("D4b", "内联 <script>", "<script>" in overview)
    s.check("D4c", "内联 2 个 <svg>（Prefill/Decode 曲线）", overview.count("<svg") == 2,
            f"count={overview.count('<svg')}")

    # ---- D5 可折叠参数说明 / 曲线 / 硬件四项 ----
    s.check("D5", "存在可折叠参数说明块 <details class=intro>", '<details class="intro"' in overview)
    s.check("D5b", "Prefill 曲线 svg", "Prefill 吞吐率" in overview)
    s.check("D5c", "Decode 曲线 svg", "Decode 吞吐率" in overview)
    for item in ["CPU 型号", "主机型号", "内存大小", "系统版本"]:
        s.check("D5d", f"硬件区块含「{item}」", item in overview)

    # ---- D6 vision_fps 全 0 且渲染为 0.00 / - ----
    s.check("D6", "所有点 vision_fps == 0", all(d.get("vision_fps") == 0 for d in ov_data),
            f"非 0 值: {[d['vision_fps'] for d in ov_data if d.get('vision_fps') != 0][:5]}")
    s.check("D6b", "表格 vision 列渲染表达式为 toFixed(2) 或 '-'",
            "(p.vision_fps||0).toFixed(2)" in overview or "'-'" in overview)

    # ---- D7 fail_reason 仅枚举值 ----
    enum = {"OOM_GPU", "MODEL_FAIL", "TIMEOUT", "OTHER", ""}
    bad = {d.get("fail_reason") for d in ov_data if d.get("fail_reason") not in enum}
    s.check("D7", "fail_reason 仅出现枚举值", not bad, f"非法值: {bad}")

    # ---- D8 OOM 横幅（构造含 OOM_GPU 的数据）----
    oom_pt = BenchmarkPoint(
        model_name="M-OOM", model_size="2B", precision="w8a8", ctx_size=16000,
        input_tokens=8000, success=False, error_msg="out of memory", fail_reason="OOM_GPU",
    )
    hw = HardwareInfo(cpu_model="TestCPU", host_model="TestHost", ram_gb=64.0, os_version="TestOS")
    meta = ModelMeta(model_name="M-OOM", model_size="2B", gguf_path="/tmp/m.gguf", precision="w8a8")
    html_oom = ReportBuilder().build_model(meta, [oom_pt], hw, BenchConfig(), {})
    s.check("D8", "含 OOM_GPU → 出现 oom-banner", 'class="oom-banner"' in html_oom)
    s.check("D8b", "OOM 提示含「BIOS」与「UMA 显存」",
            "BIOS" in html_oom and "UMA 显存" in html_oom)
    ok_pt = BenchmarkPoint(
        model_name="M-OK", model_size="2B", precision="w8a8", ctx_size=4000,
        input_tokens=250, success=True,
    )
    html_ok = ReportBuilder().build_model(meta, [ok_pt], hw, BenchConfig(), {})
    s.check("D8c", "无 OOM → 不出现 oom-banner", 'class="oom-banner"' not in html_ok)

    # ---- D9 启动参数留档 + 工具/llama.cpp 版本 ----
    model_txt = model_files[0].read_text(encoding="utf-8")
    s.check("D9", "模型报告含「启动参数（可复现）」", "启动参数（可复现）" in model_txt)
    s.check("D9b", "模型报告留档完整 llama-server 命令", "llama-server" in model_txt and "-c" in model_txt)
    s.check("D9c", "页头含工具版本", "测试工具: GGUF Benchmark v" in overview)
    s.check("D9d", "页头含 llama.cpp 版本", "llama.cpp:" in overview)

    # ---- D10 文件名冲突后缀 _2 且不覆盖 ----
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p1 = ReportBuilder.resolve_report_path(out, "ModelX", "w8a8")
        p1.write_text("first", encoding="utf-8")
        p2 = ReportBuilder.resolve_report_path(out, "ModelX", "w8a8")
        p2.write_text("second", encoding="utf-8")
        s.eq("D10", "冲突时生成 _2 后缀", p2.name, "ModelX_w8a8_2.html")
        s.check("D10b", "旧文件不被覆盖", p1.read_text(encoding="utf-8") == "first")

    # ---- D11 报告点数与模型分组一致 ----
    s.eq("D11", "总览点数 == 模型数 × 49", len(ov_data), 98)
    for p in model_files:
        md = _extract_data(p.read_text(encoding="utf-8"))
        s.eq("D11b", f"{p.name} 点数 == 49", len(md), 49)

    # ---- D12 points.json / all_points.json 结构 ----
    allp = json.loads((REPORTS / "all_points.json").read_text(encoding="utf-8"))
    s.eq("D12", "all_points.json 点数 == 98", len(allp["points"]), 98)
    s.check("D12b", "all_points.json 含 models/hardware/config/llama_version",
            all(k in allp for k in ("models", "hardware", "config", "llama_version")))
    model_dirs = [d for d in REPORTS.iterdir() if d.is_dir()]
    s.check("D12c", "每个模型目录含 points.json",
            model_dirs and all((d / "points.json").exists() for d in model_dirs),
            f"dirs={[d.name for d in model_dirs]}")

    return s

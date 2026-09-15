"""E. 前端逻辑（P0）。

- 报告客户端 JS：10 列表头点击排序、失败点置尾、按模型筛选、摘要卡、曲线显隐；
- 工具 UI ``web/app.js``：档位常量、组合数计算、SSE→轮询回退、中断。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from _harness import PROJECT_ROOT, Suite

EXPECTED_KEYS = ["ctx", "input", "prefill", "decode", "ptime", "dtime", "vision", "precision", "chip", "status"]
EXPECTED_LABELS = ["Ctx(k)", "Input(k)", "Prefill(tps)", "Decode(tps)", "P-Time(ms)", "D-Time(ms)", "Vision(fps)", "精度", "芯片数", "状态"]
HARNESS = Path(__file__).resolve().parent / "frontend_harness.js"
OVERVIEW = PROJECT_ROOT / "reports" / "overview.html"


def _strip_mark(label: str) -> str:
    return re.sub(r"\s*[\u25b2\u25bc]\s*$", "", label).strip()


def run() -> Suite:
    s = Suite("E. 前端逻辑")

    # ---- 运行 Node harness ----
    try:
        proc = subprocess.run(
            ["node", str(HARNESS), str(OVERVIEW)],
            capture_output=True, text=True, timeout=60,
        )
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        s.check("E0", "Node harness 可运行", False, f"{exc}; stderr={getattr(proc,'stderr','')[:300]}")
        return s

    # E1 SORT_MAP 覆盖 10 列
    s.eq("E1", "SORT_MAP 覆盖全部 10 列", out["sortMapKeys"], EXPECTED_KEYS)

    # E2 表头 10 列且列序正确
    s.eq("E2", "渲染表头 10 列", out["renderHasTenHeaders"], 10)
    s.eq("E2b", "表头列序正确", [_strip_mark(x) for x in out["renderHeaderLabels"]], EXPECTED_LABELS)

    # E3 每列可排序（升序）
    sb = out["sortedBy"]
    num_expect = {
        "ctx": [4000, 8000, 8000], "input": [250, 1000, 4000], "prefill": [100, 200, 300],
        "decode": [20, 50, 80], "ptime": [1, 5, 9], "dtime": [2, 6, 8],
        "vision": [0, 0, 0], "chip": [1, 2, 4],
    }
    for k, exp in num_expect.items():
        s.eq("E3", f"按 {k} 升序排序正确", sb[k], exp)
    s.eq("E3b", "按 precision 字典序排序", sb["precision"], ["w4a8", "w8a8", "w8a8"])
    s.eq("E3c", "按 status 排序（false 在前）", out["statusSortAsc"], [False, False, True])

    # E4 失败/跳过点恒排末尾
    s.check("E4", "失败点恒排在末尾（即使排序值为最小值）", out["failedLast"])

    # E5 失败点状态徽章显示中文原因
    s.check("E5", "失败点状态显示「显存不足(OOM)」", out["renderStatusHasOOM"])

    # E6 摘要卡（总数据点/成功率/最高 Prefill/最高 Decode）
    sh = out["summaryHtml"]
    s.check("E6", "摘要卡：总数据点 = 2", "总数据点" in sh and ">2<" in sh, sh[:200])
    s.check("E6b", "摘要卡：成功率 = 50%", "成功率" in sh and "50%" in sh)
    s.check("E6c", "摘要卡：最高 Prefill = 9,999 tps", "最高 Prefill" in sh and "9,999 tps" in sh)
    s.check("E6d", "摘要卡：最高 Decode = 100 tps", "最高 Decode" in sh and "100 tps" in sh)
    s.check("E6e", "数据点计数同步 = 2", str(out["pointCount"]) == "2")

    # E7 按模型/精度筛选
    s.eq("E7", "按模型筛选（M1 → 4 点）", out["filteredForM1"], 4)
    s.eq("E7b", "不筛选返回全部（12 点）", out["filteredAll"], 12)
    s.eq("E7c", "按精度筛选（w4a8 → 0 点）", out["filteredW4a8"], 0)

    # E8 曲线可见性随筛选同步
    s.eq("E8", "全部筛选时 14 条曲线可见", out["seriesVisibleAll"], out["seriesTotal"])
    s.eq("E8b", "单模型筛选时仅 7 条曲线可见", out["seriesVisibleOneModel"], 7)

    # ---- E9/E10 工具 UI web/app.js 静态验证 ----
    app_js = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
    m_ctx = re.search(r"const CTX_LEVELS = \[([^\]]*)\]", app_js)
    m_inp = re.search(r"const INPUT_LEVELS = \[([^\]]*)\]", app_js)
    ctx = [int(x) for x in m_ctx.group(1).split(",")] if m_ctx else []
    inp = [int(x) for x in m_inp.group(1).split(",")] if m_inp else []
    s.eq("E9", "app.js CTX_LEVELS 与后端一致",
          ctx, [4000, 8000, 16000, 32000, 64000, 128000, 256000])
    s.eq("E9b", "app.js INPUT_LEVELS 与后端一致",
          inp, [250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000, 128000])
    combos = sum(1 for c in ctx for i in inp if i < c)
    s.eq("E9c", "app.js 本地组合数计算 == 49", combos, 49)

    s.check("E10", "app.js 使用 EventSource(SSE)", "EventSource" in app_js)
    s.check("E10b", "SSE 失败回退轮询 setInterval", "setInterval" in app_js and "startPolling" in app_js)
    s.check("E10c", "app.js 调用 abort 中断接口", "/abort" in (PROJECT_ROOT / "web" / "api.js").read_text(encoding="utf-8"))
    s.check("E10d", "app.js 含超时/进度应用逻辑", "applyStatus" in app_js and "percent" in app_js)

    return s

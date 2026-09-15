"""H. 曲线悬停数值标签（P0 新增能力）。

两层验证：
1. **静态结构**：报告 HTML 必须包含提示浮层 CSS、十字准线、透明捕获层、
   每个数据点的 ``data-x/data-y/data-val/data-in/data-ctx/data-model/data-color``，
   以及客户端 ``initChartTooltips`` 函数——且全程零外部资源。
2. **真实行为**：由 ``chart_tooltip_harness.js``（Node）**实际派发 mousemove /
   mouseleave 事件**，用生成 HTML 里解析出的真实坐标寻点，断言浮层内容、
   十字准线对齐、行数上限、边界翻转与隐藏 series 不参与提示。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from _harness import PROJECT_ROOT, Suite


def run() -> Suite:
    s = Suite("H. 曲线悬停数值标签")

    overview = PROJECT_ROOT / "reports" / "overview.html"
    if not overview.exists():  # pragma: no cover - 依赖前序模块产物
        s.check("H0", "存在 reports/overview.html", False, f"缺失: {overview}")
        return s

    txt = overview.read_text(encoding="utf-8")

    # ---- H1 静态结构：交互层与数据属性 ----
    s.check("H1a", "存在提示浮层样式 .chart-tip", ".chart-tip" in txt)
    s.check("H1b", "存在十字准线 .chart-crosshair", 'class="chart-crosshair"' in txt)
    s.check("H1c", "存在透明捕获层 .chart-hit", 'class="chart-hit"' in txt)
    s.check("H1d", "图表容器为定位上下文（position: relative）",
            bool(re.search(r"\.chart-container\s*\{[^}]*position:\s*relative", txt)))
    s.check("H1e", "存在客户端 initChartTooltips", "function initChartTooltips" in txt)
    s.check("H1f", "初始化时调用了 initChartTooltips()", "initChartTooltips();" in txt)

    dots = re.findall(r'<circle class="series-dot"([^>]*)>', txt)
    s.check("H2a", "曲线点带有坐标/数值属性", len(dots) > 0 and all(
        'data-x=' in d and 'data-y=' in d and 'data-val=' in d and 'data-in=' in d
        and 'data-ctx=' in d and 'data-model=' in d and 'data-color=' in d
        for d in dots), f"点数={len(dots)}")
    s.check("H2b", "每个曲线点保留原生 <title> 兜底提示",
            len(re.findall(r'class="series-dot"[^>]*>\s*<title>', txt)) == len(dots),
            f"dots={len(dots)}")

    # 两个图表各自都应具备一条十字准线与一个捕获层
    s.eq("H2c", "两个图表各有 1 条十字准线", len(re.findall(r'class="chart-crosshair"', txt)), 2)
    s.eq("H2d", "两个图表各有 1 个捕获层", len(re.findall(r'class="chart-hit"', txt)), 2)

    # ---- H3 零外部资源（新增能力不得破坏离线约束）----
    ext = re.findall(r'(?:src|href)\s*=\s*["\']https?://', txt)
    s.eq("H3", "悬停能力未引入任何外部资源", len(ext), 0)

    # ---- H4 真实行为验证（Node 驱动真实事件）----
    node = shutil.which("node")
    if not node:  # pragma: no cover - 环境相关
        s.note("未找到 node，跳过 H4 行为验证")
        return s

    harness = Path(__file__).resolve().parent / "chart_tooltip_harness.js"
    try:
        proc = subprocess.run(
            [node, str(harness), str(overview)],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            s.check("H4a", "tooltip harness 正常退出", False, (proc.stderr or "")[-600:])
            return s
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:  # pragma: no cover
        s.check("H4a", "tooltip harness 可执行", False, repr(exc))
        return s

    s.eq("H4a", "识别出 2 张曲线图", out.get("chartCount"), 2)
    s.eq("H4b", "每张图为每个图表创建且仅创建 1 个浮层", out.get("tipCreatedPerChart"), 2)
    s.eq("H4c", "两张图都绑定了 mousemove", out.get("hitHasMoveListener"), [True, True])

    s.eq("H5a", "悬停后浮层可见", out.get("tipDisplayAfterMove"), "block")
    s.check("H5b", "浮层包含被悬停模型的名称", bool(out.get("tipHasModel")))
    s.check("H5c", "浮层表头含 Ctx 与 Input 档位", bool(out.get("tipHasHead")))
    s.eq("H5d", "十字准线可见", out.get("crosshairVisible"), True)
    s.eq("H5e", "十字准线对齐到最近档位 x", out.get("crosshairAligned"), True)
    s.eq("H5f", "浮层跟随光标定位", out.get("tipFollowsCursor"), True)

    # 行数上限：同一 x 档位 series 很多时不得无限增长
    rows = out.get("rowCount") or 0
    same_x = out.get("seriesAtSameX") or 0
    s.check("H6a", "同一档位多条 series 时行数受上限约束（≤12 行 + 溢出提示）",
            rows <= 12 or rows <= same_x, f"同档位 series={same_x} 行数={rows}")
    if same_x > 12:
        s.eq("H6b", "超出上限时给出溢出提示", out.get("hasOverflowNote"), True)

    s.eq("H7a", "鼠标移出绘图区即隐藏", out.get("hiddenOutsidePlot"), True)
    s.eq("H7b", "贴近右边缘时浮层向左翻转", out.get("flippedAtRightEdge"), True)
    s.eq("H7c", "mouseleave 后隐藏", out.get("hiddenAfterLeave"), True)

    # 被筛选隐藏的 series 不得出现在提示里（按 series 计数，避免模型名跨 ctx 重复的误判）
    s.eq("H8", "被筛选隐藏的 series 不参与提示",
         out.get("hiddenSeriesExcluded"), True,
         f"仅 1 条 series 可见时应为 {out.get('expectedRowsWithOneSeries')} 行，"
         f"实际 {out.get('rowsWithOneSeriesVisible')} 行")

    return s

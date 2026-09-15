"""``render_chart_svg(points, metric)``：对数横轴 + 线性纵轴的 SVG 曲线生成。

坐标映射严格复刻黄金样本（架构 §8.4）：
- ``viewBox="0 0 1180 380"``，绘图区 ``x∈[70,1150]``，``y∈[40,320]``
- 横轴对数，定义域固定 ``[250, 256000]``
- 纵轴线性，5 条水平网格线；``data-series`` 与客户端筛选 key 一致
"""

from __future__ import annotations

import math
from html import escape

# 12 色调色板（架构 §12.7，报告与 UI 共用）
PALETTE = [
    "#00d4aa", "#7c83ff", "#ff6b6b", "#ffd93d", "#6bcb77", "#4d96ff",
    "#ff922b", "#e599f7", "#20c997", "#f06595", "#748ffc", "#ffa94d",
]

X0, X1, Y0, Y1 = 70.0, 1150.0, 40.0, 320.0
X_MIN, X_MAX = 250, 256000
# 横轴刻度位置与标签（6 条纵向网格线）
X_TICKS: list[tuple[int, str]] = [
    (250, "0.25k"), (1000, "1k"), (4000, "4k"),
    (16000, "16k"), (64000, "64k"), (256000, "256k"),
]
METRIC_LABEL = {"prefill": "Prefill", "decode": "Decode"}


def nice_ceil(value: float) -> float:
    """向上取整到 ``{1,2,5}×10^k``（架构 §8.4 定义的 nice 数）。"""
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10 ** exponent
    for mult in (1, 2, 5, 10):
        candidate = mult * base
        if candidate >= value:
            return float(candidate)
    return float(10 * base)


def _compute_ymax(values: list[float]) -> float:
    """计算纵轴上限。

    说明：架构 §8.4 文字描述为 ``nice_ceil(max)``，但同节的"校验 golden"给出
    黄金样本实际纵轴上限 ``≈9376``（对应 ``max×1.1``，而非 nice 数 10000）。
    为与黄金样本**数值对齐**，此处采用 ``max × 1.1`` 并四舍五入；
    ``nice_ceil`` 仍作为工具函数导出备用。
    """
    positive = [v for v in values if v > 0]
    if not positive:
        return 1.0
    return float(round(max(positive) * 1.1, 2))


def _xmap(value: float) -> float:
    """横轴：对数映射到像素坐标。"""
    clamped = min(max(value, X_MIN), X_MAX)
    ratio = (math.log10(clamped) - math.log10(X_MIN)) / (math.log10(X_MAX) - math.log10(X_MIN))
    return X0 + ratio * (X1 - X0)


def _ymap(value: float, ymax: float) -> float:
    """纵轴：线性映射到像素坐标。"""
    return Y1 - (value / ymax) * (Y1 - Y0)


def _series_key(point) -> str:
    """构造 data-series key：``model_name|model_size|precision|n_chip|ctx_size``。"""
    return f"{point.model_name}|{point.model_size}|{point.precision}|{point.n_chip}|{point.ctx_size}"


def render_chart_svg(points: list, metric: str) -> str:
    """生成单张曲线图的 SVG 字符串。

    Args:
        points: ``BenchmarkPoint`` 列表（可跨模型）。
        metric: ``"prefill"`` 或 ``"decode"``。

    Returns:
        完整 ``<svg>...</svg>`` 字符串（仅渲染 success=true 的点）。
    """
    field = f"{metric}_tps"
    label = METRIC_LABEL.get(metric, metric)
    success_points = [p for p in points if getattr(p, "success", False)]
    ymax = _compute_ymax([float(getattr(p, field, 0.0) or 0.0) for p in success_points])

    out: list[str] = []
    out.append(
        f'<svg viewBox="0 0 1180 380" xmlns="http://www.w3.org/2000/svg" class="chart-svg" '
        f'role="img" aria-label="{escape(label)} 吞吐率 (tps)">'
    )
    out.append('<rect x="0" y="0" width="1180" height="380" fill="#16213e"/>')
    out.append('<rect x="70" y="40" width="1080" height="280" fill="#0f1729"/>')

    # ---- 水平网格线（6 条，含 0 与 ymax）----
    for k in range(6):
        value = ymax * k / 5.0
        y = _ymap(value, ymax)
        out.append(f'<line x1="70" y1="{y:.1f}" x2="1150" y2="{y:.1f}" stroke="#2a2a4a" stroke-width="1"/>')
        out.append(
            f'<text x="62" y="{y + 4:.1f}" fill="#a0a0b0" font-size="11" text-anchor="end">'
            f'{value:,.0f}</text>'
        )

    # ---- 纵向网格线（6 条）----
    for value, tick_label in X_TICKS:
        x = _xmap(value)
        out.append(f'<line x1="{x:.1f}" y1="40" x2="{x:.1f}" y2="320" stroke="#2a2a4a" stroke-width="1"/>')
        out.append(
            f'<text x="{x:.1f}" y="338" fill="#a0a0b0" font-size="11" text-anchor="middle">'
            f'{tick_label}</text>'
        )

    # ---- 坐标轴 ----
    out.append('<line x1="70" y1="40" x2="70" y2="320" stroke="#4a4a6a" stroke-width="1.5"/>')
    out.append('<line x1="70" y1="320" x2="1150" y2="320" stroke="#4a4a6a" stroke-width="1.5"/>')

    # ---- 标题 ----
    out.append(f'<text x="70" y="22" fill="#00d4aa" font-size="15" font-weight="600">{escape(label)} 吞吐率 (tps)</text>')
    out.append('<text x="610" y="372" fill="#a0a0b0" font-size="11" text-anchor="middle">输入 Token 数 (k, 对数轴)</text>')

    # ---- 按 series 分组（保持首次出现顺序）----
    grouped: dict[str, list] = {}
    for point in sorted(success_points, key=lambda p: (p.model_name, p.ctx_size, p.input_tokens)):
        grouped.setdefault(_series_key(point), []).append(point)

    legend_items: list[str] = []
    for idx, (series_key, series_points) in enumerate(grouped.items()):
        color = PALETTE[idx % len(PALETTE)]
        series_points = sorted(series_points, key=lambda p: p.input_tokens)
        coords = " ".join(
            f"{_xmap(p.input_tokens):.1f},{_ymap(float(getattr(p, field, 0.0) or 0.0), ymax):.1f}"
            for p in series_points
        )
        out.append(
            f'<polyline class="series-line" data-series="{escape(series_key)}" points="{coords}" '
            f'fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for p in series_points:
            cx = _xmap(p.input_tokens)
            value = float(getattr(p, field, 0.0) or 0.0)
            cy = _ymap(value, ymax)
            title = f"{p.model_name}: {value:,.1f} tps @ {p.input_tokens / 1000:.2f}k"
            # data-* 供客户端悬停提示读取（零依赖，纯原生 SVG + JS）
            out.append(
                f'<circle class="series-dot" data-series="{escape(series_key)}" '
                f'data-x="{cx:.1f}" data-y="{cy:.1f}" data-val="{value:.2f}" '
                f'data-in="{p.input_tokens}" data-ctx="{p.ctx_size}" '
                f'data-model="{escape(str(p.model_name))}" data-color="{color}" '
                f'cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{color}">'
                f"<title>{escape(title)}</title></circle>"
            )
        first = series_points[0]
        legend_items.append(
            f'<tspan fill="{color}">&#9679;</tspan>'
            f'<tspan fill="#888"> {escape(first.model_name)} ({first.ctx_size // 1000}K) </tspan>'
        )

    # ---- 图例 ----
    if legend_items:
        out.append('<text x="70" y="300" font-size="10">' + "".join(legend_items) + "</text>")

    # ---- 悬停交互层（必须位于所有曲线之上才能捕获指针）----
    # 十字准线 + 全绘图区透明捕获矩形；实际寻点与提示浮层由客户端 JS 完成。
    out.append(
        '<line class="chart-crosshair" x1="70" y1="40" x2="70" y2="320" '
        'stroke="#7c83ff" stroke-width="1" stroke-dasharray="4 4" style="display:none"/>'
    )
    out.append(
        '<rect class="chart-hit" x="70" y="40" width="1080" height="280" '
        'fill="transparent" style="cursor:crosshair"/>'
    )

    out.append("</svg>")
    return "".join(out)


__all__ = ["render_chart_svg", "nice_ceil", "PALETTE", "METRIC_LABEL"]

"""报告包导出。"""

from __future__ import annotations

from .builder import ReportBuilder
from .chart import PALETTE, nice_ceil, render_chart_svg
from .template import render_report_html

__all__ = ["ReportBuilder", "render_chart_svg", "render_report_html", "nice_ceil", "PALETTE"]

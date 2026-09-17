"""``ReportBuilder``：组装单模型 / 总览报告并落盘；``build_from_points_json`` 离线入口。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .. import TOOL_NAME
from ..logging_utils import get_logger, safe_name
from ..models import BenchConfig, BenchmarkPoint, HardwareInfo, ModelMeta
from .template import render_report_html

logger = get_logger("report")

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


class ReportBuilder:
    """报告组装器（纯函数 + 落盘）。"""

    def __init__(self, tool_version: str = "1.0", llama_version: str = "unknown") -> None:
        self.tool_version: str = tool_version
        self.llama_version: str = llama_version

    # ---- 组装 ----
    def build_model(
        self,
        meta: ModelMeta,
        points: list[BenchmarkPoint],
        hw: HardwareInfo,
        cfg: BenchConfig,
        launch_cmds: dict[int, list[str]],
    ) -> str:
        """生成单模型报告 HTML。"""
        host = hw.host_model or "本地主机"
        title = f"{meta.model_name} Benchmark @ {host}"
        return render_report_html(
            kind="model",
            title=title,
            generated_at=time.strftime(_TIME_FMT),
            models=[meta],
            points=points,
            hw=hw,
            cfg=cfg,
            launch_cmds=launch_cmds or {},
            tool_name=TOOL_NAME,
            tool_version=self.tool_version,
            llama_version=self.llama_version,
        )

    def build_overview(
        self,
        models: list[ModelMeta],
        points: list[BenchmarkPoint],
        hw: HardwareInfo,
        cfg: BenchConfig,
    ) -> str:
        """生成总览报告 HTML（含全部模型曲线，复用同一渲染逻辑）。"""
        host = hw.host_model or "本地主机"
        title = f"{TOOL_NAME} 总览 @ {host}"
        return render_report_html(
            kind="overview",
            title=title,
            generated_at=time.strftime(_TIME_FMT),
            models=models,
            points=points,
            hw=hw,
            cfg=cfg,
            launch_cmds={},
            tool_name=TOOL_NAME,
            tool_version=self.tool_version,
            llama_version=self.llama_version,
        )

    # ---- 落盘 ----
    @staticmethod
    def write(path: Path, html: str) -> Path:
        """写出 HTML 文件。

        ``newline="\\n"`` 是刻意加的：文本模式下 Windows 会把 ``\\n`` 翻译成
        ``\\r\\n``，导致同一份报告在不同 OS 上字节不一致，且会打断按 ``;\\n``
        切片的自带前端 harness（tests/frontend_harness.js 等）。
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8", newline="\n")
        logger.info("报告已写入: %s", path)
        return path

    @staticmethod
    def resolve_report_path(output_dir: Path, model_name: str, precision: str) -> Path:
        """按 ``<模型名>_<精度>.html`` 生成路径，冲突时追加序号（PRD Q6）。"""
        output_dir = Path(output_dir)
        base = f"{safe_name(model_name)}_{precision}.html"
        candidate = output_dir / base
        index = 2
        while candidate.exists():
            candidate = output_dir / f"{safe_name(model_name)}_{precision}_{index}.html"
            index += 1
        return candidate

    @staticmethod
    def write_points_json(
        output_dir: Path,
        meta: ModelMeta,
        points: list[BenchmarkPoint],
        hw: HardwareInfo,
        cfg: BenchConfig,
        launch_cmds: dict[int, list[str]],
    ) -> Path:
        """写出单模型 ``reports/<model>/points.json``。"""
        model_dir = Path(output_dir) / safe_name(meta.model_name)
        model_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": meta.model_dump(),
            "points": [p.model_dump() for p in points],
            "hardware": hw.model_dump(),
            "config": cfg.model_dump(),
            "launch_cmds": {str(k): v for k, v in (launch_cmds or {}).items()},
            "llama_version": cfg.llama_version,
        }
        path = model_dir / "points.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
                        newline="\n")
        return path

    @staticmethod
    def write_all_points_json(
        output_dir: Path,
        models: list[ModelMeta],
        points: list[BenchmarkPoint],
        hw: HardwareInfo,
        cfg: BenchConfig,
    ) -> Path:
        """写出全量 ``reports/all_points.json``（总览重建入口）。"""
        payload = {
            "models": [m.model_dump() for m in models],
            "points": [p.model_dump() for p in points],
            "hardware": hw.model_dump(),
            "config": cfg.model_dump(),
            "llama_version": cfg.llama_version,
        }
        path = Path(output_dir) / "all_points.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
                        newline="\n")
        return path

    # ---- 离线重建 ----
    @staticmethod
    def build_from_points_json(points_json: Path, out_html: Path, *, overview: bool = False) -> None:
        """给定 ``points.json`` 离线重建 HTML（架构 T04 自测入口）。

        支持两种输入形状：
        - 单模型：``{"model": {...}, "points": [...], ...}``
        - 全量：``{"models": [...], "points": [...], ...}``（总览）
        """
        data = json.loads(Path(points_json).read_text(encoding="utf-8"))
        points = [BenchmarkPoint(**d) for d in data.get("points", [])]
        hw = HardwareInfo(**data.get("hardware", {}))
        cfg = _config_from_dict(data.get("config", {}))
        llama_version = str(data.get("llama_version", cfg.llama_version))
        builder = ReportBuilder(tool_version=data.get("config", {}).get("tool_version", "1.0"),
                                llama_version=llama_version)

        is_overview = overview or "models" in data
        if is_overview:
            models = [ModelMeta(**m) for m in data.get("models", [])]
            html = builder.build_overview(models, points, hw, cfg)
        else:
            meta = ModelMeta(**data["model"])
            launch = {int(k): v for k, v in data.get("launch_cmds", {}).items()}
            html = builder.build_model(meta, points, hw, cfg, launch)

        ReportBuilder.write(Path(out_html), html)


def _config_from_dict(raw: dict) -> BenchConfig:
    """从字典安全构造 ``BenchConfig``（忽略未知键）。"""
    if not raw:
        return BenchConfig()
    filtered = {k: v for k, v in raw.items() if k in BenchConfig.model_fields}
    return BenchConfig(**filtered)


__all__ = ["ReportBuilder"]

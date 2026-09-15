"""A1~A15 全部路由实现（薄层，委派给各服务）。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import __version__
from .config_store import ConfigStore
from .engine import BenchEngine
from .errors import ApiError, ErrorCode, error_body, ok_body
from .logging_utils import get_logger
from .models import BenchConfig, BenchmarkPoint, ModelMeta
from .report.builder import ReportBuilder
from .runners.base import is_port_in_use
from .scanner import ModelScanner
from .task_manager import TaskManager

logger = get_logger("api")


# ----------------------------- 请求模型 -----------------------------
class ScanRequest(BaseModel):
    dir: str = ""
    recursive: bool = True


class PortCheckRequest(BaseModel):
    port: int
    host: str = "127.0.0.1"


class TokenizeRequest(BaseModel):
    text: str = ""
    model: str | None = None


class PreviewRequest(BaseModel):
    models: list[ModelMeta] = Field(default_factory=list)
    config: dict[str, Any] | None = None


class CreateTaskRequest(BaseModel):
    models: list[ModelMeta] = Field(default_factory=list)
    config: dict[str, Any] | None = None


class OverviewBuildRequest(BaseModel):
    task_id: str = ""


# ----------------------------- 辅助 -----------------------------
def _merge_config(store: ConfigStore, patch: dict[str, Any] | None) -> BenchConfig:
    """把请求里的部分配置合并进当前配置（不落盘），非法参数返回 400。"""
    current = store.load().model_dump()
    if patch:
        current.update({k: v for k, v in patch.items() if k in BenchConfig.model_fields})
    try:
        return BenchConfig(**current)
    except Exception as exc:
        raise ApiError(ErrorCode.E_BAD_REQUEST, f"参数校验失败: {exc}") from exc


def _estimate_tokens(text: str) -> int:
    """无可用 tokenizer 时的近似 token 估算（约 4 字符 = 1 token）。"""
    return max(1, round(len(text) / 4)) if text else 0


def _llama_found(cfg: BenchConfig) -> bool:
    """llama-server 路径是否存在。"""
    path = (cfg.llama_server_path or "").strip()
    return bool(path) and Path(path).expanduser().exists()


# ----------------------------- 路由注册 -----------------------------
def register_routes(app: FastAPI, store: ConfigStore, task_manager: TaskManager) -> None:
    """注册 A1~A15 路由。"""

    # ---- 异常处理 ----
    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())

    @app.exception_handler(Exception)
    async def _unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        logger.exception("未捕获异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content=error_body(ErrorCode.E_INTERNAL, f"服务器内部错误: {exc}"),
        )

    # ---- A1 健康检查 ----
    @app.get("/api/health")
    async def health() -> dict:
        cfg = store.load()
        return ok_body(
            python_version=sys.version.split()[0],
            llama_server_found=_llama_found(cfg),
            version=__version__,
        )

    # ---- A2 读取配置（直接返回 BenchConfig）----
    @app.get("/api/config")
    async def get_config() -> dict:
        return store.load().model_dump()

    # ---- A3 保存配置 ----
    @app.put("/api/config")
    async def put_config(patch: dict[str, Any]) -> dict:
        try:
            cfg = store.save(patch)
        except Exception as exc:  # pydantic 校验
            raise ApiError(ErrorCode.E_BAD_REQUEST, f"配置校验失败: {exc}") from exc
        return ok_body(config=cfg.model_dump())

    # ---- A4 目录扫描 ----
    @app.post("/api/scan")
    async def scan(req: ScanRequest) -> dict:
        scanner = ModelScanner()
        models = scanner.scan(req.dir, req.recursive)
        ignored = scanner.list_ignored(req.dir, req.recursive)
        store.set_runtime(scan_result=models)
        return ok_body(models=[m.model_dump() for m in models], ignored=ignored)

    # ---- A5 端口占用检测 ----
    @app.post("/api/port-check")
    async def port_check(req: PortCheckRequest) -> dict:
        if not 1 <= req.port <= 65535:
            raise ApiError(ErrorCode.E_BAD_REQUEST, f"端口范围 1..65535，收到 {req.port}")
        in_use = is_port_in_use(req.host, req.port)
        return ok_body(in_use=in_use)

    # ---- A6 tokenize（真实校验；无运行器时近似估算）----
    @app.post("/api/tokenize")
    async def tokenize(req: TokenizeRequest) -> dict:
        runner = task_manager.current_runner()
        if runner is not None:
            try:
                count = runner.tokenize(req.text)
                return ok_body(token_count=int(count))
            except Exception as exc:  # pragma: no cover - 运行器相关
                logger.warning("tokenize 代理失败，回退估算: %s", exc)
        return ok_body(token_count=_estimate_tokens(req.text))

    # ---- A7 任务预览（矩阵裁剪）----
    @app.post("/api/tasks/preview")
    async def preview(req: PreviewRequest) -> dict:
        cfg = _merge_config(store, req.config)
        matrix = BenchEngine.build_matrix(cfg.ctx_levels, cfg.input_levels)
        total = matrix["total"]
        per_model = [{"model": m.model_name, "points": total} for m in req.models]
        return ok_body(
            total_points=total * max(1, len(req.models)) if req.models else 0,
            per_model=per_model,
            matrix={"per_ctx": {str(k): v for k, v in matrix["per_ctx"].items()}, "total": total},
        )

    # ---- A8 创建并启动任务 ----
    @app.post("/api/tasks")
    async def create_task(req: CreateTaskRequest) -> dict:
        if not req.models:
            raise ApiError(ErrorCode.E_BAD_REQUEST, "未选择任何模型")
        cfg = _merge_config(store, req.config)
        store.save(cfg.model_dump())  # 持久化本次运行配置 (P1-02)
        try:
            task_id = task_manager.create("", req.models, cfg)
        except ApiError:
            raise
        except Exception as exc:  # pragma: no cover
            raise ApiError(ErrorCode.E_INTERNAL, f"创建任务失败: {exc}") from exc
        return ok_body(task_id=task_id)

    # ---- A9 任务状态（直接返回 TaskStatus）----
    @app.get("/api/tasks/{task_id}")
    async def task_status(task_id: str) -> dict:
        return task_manager.get(task_id).model_dump()

    # ---- A10 SSE 事件流 ----
    @app.get("/api/tasks/{task_id}/events")
    async def task_events(task_id: str) -> StreamingResponse:
        task_manager.get(task_id)  # 校验存在（不存在则抛 404）
        task_manager.bind_loop(asyncio.get_running_loop())
        return StreamingResponse(
            task_manager.subscribe(task_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- A11 中断任务 ----
    @app.post("/api/tasks/{task_id}/abort")
    async def abort_task(task_id: str) -> dict:
        ok = task_manager.abort(task_id)
        if not ok:
            raise ApiError(ErrorCode.E_TASK_BUSY, "任务当前无法中断")
        return ok_body()

    # ---- A12 拉取数据点 ----
    @app.get("/api/tasks/{task_id}/points")
    async def task_points(task_id: str, model: str | None = None) -> dict:
        points: list[BenchmarkPoint] = task_manager.points(task_id, model)
        return ok_body(points=[p.model_dump() for p in points])

    # ---- A13 报告列表 ----
    @app.get("/api/reports")
    async def list_reports() -> dict:
        out_dir = _output_dir(store)
        reports = []
        for path in sorted(out_dir.glob("*.html")):
            model_name = path.stem
            reports.append(
                {
                    "model": model_name,
                    "path": f"/reports/{path.name}",
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)),
                }
            )
        return ok_body(reports=reports)

    # ---- A14 手动重建总览 ----
    @app.post("/api/reports/overview/build")
    async def build_overview(req: OverviewBuildRequest) -> dict:
        engine = task_manager.engine_of(req.task_id)
        builder = ReportBuilder(tool_version=__version__, llama_version=getattr(engine.config, "llama_version", "unknown"))
        models = task_manager.models_of(req.task_id) or _models_from_points(engine.points)
        html = builder.build_overview(models, engine.points, engine.hardware, engine.config)
        out_dir = _output_dir(store)
        path = out_dir / "overview.html"
        builder.write(path, html)
        return ok_body(path=f"/reports/{path.name}")


def _output_dir(store: ConfigStore) -> Path:
    """解析配置中的输出目录为绝对路径。"""
    from . import PROJECT_ROOT

    out = Path(store.load().output_dir)
    if not out.is_absolute():
        out = (PROJECT_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def _models_from_points(points: list[BenchmarkPoint]) -> list[ModelMeta]:
    """由数据点反推模型元信息（A14 兜底）。"""
    seen: dict[str, ModelMeta] = {}
    for p in points:
        if p.model_name not in seen:
            seen[p.model_name] = ModelMeta(
                model_name=p.model_name,
                model_size=p.model_size,
                gguf_path="",
                precision=p.precision,
                n_chip=p.n_chip,
            )
    return list(seen.values())


__all__ = ["register_routes"]

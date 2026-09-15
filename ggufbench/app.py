"""FastAPI 应用装配：CORS(本地)、路由注册、``/web`` 与 ``/reports`` 静态挂载。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import PROJECT_ROOT, TOOL_NAME, WEB_DIR, __version__
from .api import register_routes
from .config_store import ConfigStore
from .logging_utils import get_logger, setup_logging, get_task_log_path
from .task_manager import TaskManager

logger = get_logger("app")


def _resolve_output_dir(config_dir: str) -> Path:
    """解析输出目录为绝对路径并创建。"""
    out = Path(config_dir)
    if not out.is_absolute():
        out = (PROJECT_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def create_app() -> FastAPI:
    """构建并返回 FastAPI 应用。"""
    store = ConfigStore()
    config = store.load()  # 首次运行写出 config.json
    output_dir = _resolve_output_dir(config.output_dir)

    # 任务级日志落盘
    setup_logging(log_file=get_task_log_path(output_dir))

    task_manager = TaskManager()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """启动时绑定事件循环（供 SSE 广播）；退出时清理运行器。"""
        try:
            task_manager.bind_loop(asyncio.get_running_loop())
        except RuntimeError:  # pragma: no cover - 非事件循环环境
            pass
        yield

    app = FastAPI(title=TOOL_NAME, version=__version__, lifespan=lifespan)

    # 本地 CORS（仅 127.0.0.1 使用）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态资源：web/
    app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    # 报告静态访问：/reports/<model>.html
    app.mount("/reports", StaticFiles(directory=str(output_dir), html=True), name="reports")

    # 路由注册
    register_routes(app, store, task_manager)

    @app.get("/")
    async def index() -> FileResponse:
        """返回零构建单页 UI。"""
        return FileResponse(str(WEB_DIR / "index.html"))

    @app.get("/favicon.ico")
    async def favicon() -> FileResponse:  # pragma: no cover - 浏览器请求
        return FileResponse(str(WEB_DIR / "index.html"))

    logger.info("应用已装配: output_dir=%s", output_dir)
    return app


__all__ = ["create_app"]

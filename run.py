"""程序入口。

职责（架构 §2 #2）：
- 解析命令行参数
- 校验 Python 版本（< 3.11 直接报错退出）
- 启动 Uvicorn（默认后台服务 http://127.0.0.1:8765）
- 可选自动打开浏览器
- 支持 ``--report-only`` 离线重建报告（不启动服务）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _check_python_version() -> None:
    """检查 Python 版本是否满足 >= 3.11。"""
    if sys.version_info < (3, 11):  # noqa: UP036 - 运行期仍显式检查
        from ggufbench.errors import ErrorCode

        print(
            f"[{ErrorCode.E_PY_VERSION.value}] 需要 Python 3.11 或更高版本，"
            f"当前为 {sys.version.split()[0]}。",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="GGUF Benchmark — 本地大模型批量测试工具",
    )
    parser.add_argument("--host", default=None, help="后端监听地址（默认取配置 host）")
    parser.add_argument("--port", type=int, default=None, help="后端监听端口（默认取配置 backend_port）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--log-level", default="info", help="uvicorn 日志级别（默认 info）")
    parser.add_argument(
        "--report-only",
        metavar="POINTS_JSON",
        default=None,
        help="离线重建报告：给定 points.json，生成 HTML（不启动服务）",
    )
    parser.add_argument("--out", default=None, help="配合 --report-only 的输出 HTML 路径")
    parser.add_argument(
        "--overview",
        action="store_true",
        help="配合 --report-only：按总览报告生成",
    )
    return parser.parse_args(argv)


def _resolve_output_dir() -> Path:
    """读取配置中的 output_dir，返回绝对路径。"""
    from ggufbench.config_store import ConfigStore

    store = ConfigStore()
    cfg = store.load()
    out = Path(cfg.output_dir)
    if not out.is_absolute():
        from ggufbench import PROJECT_ROOT

        out = (PROJECT_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def _run_report_only(args: argparse.Namespace) -> int:
    """离线重建报告入口。"""
    import json

    from ggufbench.report.builder import ReportBuilder

    points_json = Path(args.report_only)
    if not points_json.exists():
        print(f"[E_BAD_REQUEST] points.json 不存在: {points_json}", file=sys.stderr)
        return 1
    out_html = Path(args.out) if args.out else points_json.with_suffix(".html")
    try:
        ReportBuilder.build_from_points_json(points_json, out_html, overview=bool(args.overview))
    except json.JSONDecodeError as exc:
        print(f"[E_BAD_REQUEST] points.json 解析失败（非法 JSON）: {exc}", file=sys.stderr)
        return 1
    except (KeyError, ValueError, TypeError) as exc:
        print(f"[E_BAD_REQUEST] points.json 结构不正确: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[E_INTERNAL] 写入报告失败: {exc}", file=sys.stderr)
        return 1
    print(f"[OK] 报告已生成: {out_html}")
    return 0


def _route_url(host: str, port: int) -> str:
    """构造浏览器访问 URL（0.0.0.0 归一化为 127.0.0.1）。"""
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return f"http://{display_host}:{port}/"


def _open_browser_later(host: str, port: int, delay: float = 1.5) -> None:
    """延迟打开浏览器（不阻塞主线程）。"""
    import threading
    import webbrowser

    def _worker() -> None:
        import time

        time.sleep(delay)
        try:
            webbrowser.open(_route_url(host, port))
        except Exception:  # pragma: no cover - 环境相关
            pass

    threading.Thread(target=_worker, daemon=True).start()


def _serve(args: argparse.Namespace) -> int:
    """启动后端服务。"""
    import uvicorn

    from ggufbench.app import create_app
    from ggufbench.config_store import ConfigStore

    cfg = ConfigStore().load()
    host = args.host or cfg.host
    port = args.port or cfg.backend_port

    app = create_app()

    if not args.no_browser:
        _open_browser_later(host, port)

    print(f"[{TOOL_BANNER}] 后端启动中: {_route_url(host, port)}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)
    return 0


TOOL_BANNER = "GGUF Benchmark"


def main(argv: list[str] | None = None) -> int:
    """主入口。"""
    _check_python_version()
    args = _parse_args(argv)

    if args.report_only:
        return _run_report_only(args)

    # 确保 output_dir 存在，并按任务日志路径初始化日志
    out_dir = _resolve_output_dir()
    from ggufbench.logging_utils import get_task_log_path, setup_logging

    setup_logging(log_file=get_task_log_path(out_dir))
    return _serve(args)


if __name__ == "__main__":
    raise SystemExit(main())

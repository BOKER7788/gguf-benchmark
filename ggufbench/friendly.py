"""面向零基础用户的辅助能力。

集中实现「不该让用户手动做的事」：

- :func:`pick_directory` / :func:`pick_file` —— 调系统原生选择窗口（P0-6）
- :func:`open_in_file_manager` —— 在文件管理器里定位报告（P0-11）
- :func:`recommended_config` —— 按本机硬件推荐后端/线程数（P0-7）
- :class:`LlamaDownloader` —— 一键获取 llama.cpp 的 Windows Vulkan 构建（P0-3）

所有系统调用都带超时与异常兜底：即使失败，也只返回 ``None`` / ``ok=False``，
由调用方降级为「请手动填写路径」，绝不把栈信息抛给用户。
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

from . import PROJECT_ROOT
from .logging_utils import get_logger

logger = get_logger("friendly")

# 用户挑选文件/文件夹需要时间，给足超时；超时后按「取消」处理
_DIALOG_TIMEOUT_S = 300.0

# 同一时刻只允许一个原生对话框，避免多个弹窗打架
_dialog_lock = threading.Lock()

DEFAULT_LLAMA_DIR = PROJECT_ROOT / "llama.cpp"


# ===========================================================================
# 原生选择窗口
# ===========================================================================
def _run(cmd: list[str], timeout: float = _DIALOG_TIMEOUT_S) -> subprocess.CompletedProcess | None:
    """执行外部命令，任何失败都返回 ``None``。"""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("外部命令失败 %s: %s", cmd[0] if cmd else "?", exc)
        return None


def pick_directory(title: str = "请选择文件夹") -> str | None:
    """弹出系统原生文件夹选择窗口。

    Returns:
        选中的绝对路径；用户取消或环境不支持时返回 ``None``。
    """
    if not _dialog_lock.acquire(blocking=False):
        logger.info("已有对话框在等待，忽略本次请求")
        return None
    try:
        return _pick_directory_impl(title)
    finally:
        _dialog_lock.release()


def _pick_directory_impl(title: str) -> str | None:
    if sys.platform.startswith("win"):
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null;"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
            f"$d.Description = '{title}';"
            "$d.ShowNewFolderButton = $true;"
            "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
            " { Write-Output $d.SelectedPath }"
        )
        proc = _run(["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script])
        return _clean(proc.stdout if proc else "")

    if sys.platform == "darwin":
        safe = title.replace('"', "")
        proc = _run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{safe}")'])
        return _clean(proc.stdout if proc else "")

    # Linux：优先 zenity，退回 tkinter
    if shutil.which("zenity"):
        proc = _run(["zenity", "--file-selection", "--directory", f"--title={title}"])
        return _clean(proc.stdout if proc else "")
    return _tk_dialog("directory", title)


def pick_file(title: str = "请选择文件", patterns: str = "可执行文件|*.exe|所有文件|*.*") -> str | None:
    """弹出系统原生文件选择窗口。"""
    if not _dialog_lock.acquire(blocking=False):
        logger.info("已有对话框在等待，忽略本次请求")
        return None
    try:
        return _pick_file_impl(title, patterns)
    finally:
        _dialog_lock.release()


def _pick_file_impl(title: str, patterns: str) -> str | None:
    if sys.platform.startswith("win"):
        # patterns 形如 "可执行文件|*.exe|所有文件|*.*"
        ps_filter = patterns.replace("'", "")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms | Out-Null;"
            "$d = New-Object System.Windows.Forms.OpenFileDialog;"
            f"$d.Title = '{title}';"
            f"$d.Filter = '{ps_filter}';"
            "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
            " { Write-Output $d.FileName }"
        )
        proc = _run(["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script])
        return _clean(proc.stdout if proc else "")

    if sys.platform == "darwin":
        safe = title.replace('"', "")
        proc = _run(
            [
                "osascript",
                "-e",
                f'POSIX path of (choose file with prompt "{safe}")',
            ]
        )
        return _clean(proc.stdout if proc else "")

    if shutil.which("zenity"):
        proc = _run(["zenity", "--file-selection", f"--title={title}"])
        return _clean(proc.stdout if proc else "")
    return _tk_dialog("file", title)


def _tk_dialog(kind: str, title: str) -> str | None:
    """最后兜底：用独立 Python 子进程跑 tkinter，避免与服务器的线程模型冲突。"""
    code = (
        "import tkinter as tk, sys\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
        f"p = filedialog.ask{'directory' if kind == 'directory' else 'openfilename'}"
        f"(title={title!r})\n"
        "sys.stdout.write(p or '')\n"
    )
    proc = _run([sys.executable, "-c", code])
    return _clean(proc.stdout if proc else "")


def _clean(text: str | None) -> str | None:
    """清理命令输出：去空白、去末尾斜杠、空串转 None。"""
    if not text:
        return None
    value = text.strip().strip('"')
    if not value:
        return None
    if len(value) > 1:
        value = value.rstrip("/\\")
    return value or None


# ===========================================================================
# 在文件管理器里打开
# ===========================================================================
def open_in_file_manager(target: str | Path) -> bool:
    """在系统文件管理器中打开目录（或定位到文件）。"""
    path = Path(target).expanduser()
    if not path.exists():
        logger.warning("打开路径失败，目标不存在: %s", path)
        return False
    if path.is_file():
        path = path.parent
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
        return True
    except OSError as exc:
        logger.warning("打开路径失败: %s", exc)
        return False


# ===========================================================================
# 按本机硬件推荐配置
# ===========================================================================
def recommended_config() -> dict:
    """给出适合本机的默认后端 / 线程数 / GPU 卸载层数（P0-7）。

    目的：让用户「什么都不用改」就能跑。检测失败时回落到最保守的 Vulkan。
    """
    from .hardware import get_collector

    threads = max(2, (os.cpu_count() or 8) - 1)
    backend = "vulkan"
    try:
        hw = get_collector().collect()
        gpu = (hw.gpu or "").lower()
        cpu = (hw.cpu_model or "").lower()
        if "nvidia" in gpu or "geforce" in gpu or "rtx" in gpu:
            backend = "cuda"
        elif "radeon" in gpu or "amd" in gpu or "gfx" in gpu:
            backend = "vulkan"
        elif sys.platform == "darwin" or "apple" in cpu:
            backend = "metal"
        elif not gpu or gpu.startswith("unknown"):
            backend = "cpu" if sys.platform not in ("darwin",) else "metal"
    except Exception as exc:  # noqa: BLE001 - 推荐失败不应影响主流程
        logger.warning("硬件探测失败，使用保守默认: %s", exc)

    return {
        "gpu_backend": backend,
        "threads": threads,
        "n_gpu_layers": 99,
        "platform": platform.system(),
    }


# ===========================================================================
# 一键获取 llama.cpp（P0-3）
# ===========================================================================
class LlamaDownloader:
    """下载并解压 llama.cpp 官方 Windows Vulkan 构建。

    单例式用法：``start()`` 启动后台线程，``status()`` 轮询进度。
    只跟踪一个任务；重复 ``start()`` 会被忽略。
    """

    _RELEASE_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    # 形如 llama-b1234-bin-win-vulkan-x64.zip
    _ASSET_RE = re.compile(r"bin-win-vulkan.*\.zip$", re.IGNORECASE)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {
            "state": "idle",  # idle|running|done|error
            "percent": 0.0,
            "message": "",
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "llama_server_path": "",
            "error": "",
        }

    # ---- 对外 ----
    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, dest_dir: str | None = None) -> dict:
        """启动下载（非阻塞）。已在运行则直接返回当前状态。"""
        with self._lock:
            if self._state["state"] == "running":
                return dict(self._state)
            self._state = {
                "state": "running",
                "percent": 0.0,
                "message": "正在查询 llama.cpp 最新版本…",
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "llama_server_path": "",
                "error": "",
            }
        target = Path(dest_dir).expanduser() if dest_dir else DEFAULT_LLAMA_DIR
        threading.Thread(target=self._work, args=(target,), daemon=True).start()
        return self.status()

    # ---- 内部 ----
    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    def _fail(self, message: str) -> None:
        self._set(state="error", error=message, message=message)

    def _work(self, dest_dir: Path) -> None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            self._fail(f"缺少 httpx 依赖: {exc}")
            return

        tmp_zip = dest_dir.parent / "llama.cpp-download.zip"
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as client:
                # 1) 查最新 release 并挑选 Vulkan 资产
                self._set(message="正在查询 llama.cpp 最新版本…")
                resp = client.get(self._RELEASE_API)
                if resp.status_code == 403:
                    self._fail("GitHub 接口访问受限（可能是频率限制或网络不通），请稍后重试或手动下载。")
                    return
                resp.raise_for_status()
                assets = resp.json().get("assets", []) or []
                url = ""
                for asset in assets:
                    name = str(asset.get("name", ""))
                    if self._ASSET_RE.search(name):
                        url = str(asset.get("browser_download_url", ""))
                        break
                if not url:
                    self._fail("在最新 release 里没找到 Windows Vulkan 构建包，请手动下载。")
                    return

                # 2) 流式下载并回报进度
                self._set(message="正在下载 llama.cpp（约 200MB）…")
                dest_dir.parent.mkdir(parents=True, exist_ok=True)
                with client.stream("GET", url) as stream:
                    stream.raise_for_status()
                    total = int(stream.headers.get("content-length") or 0)
                    done = 0
                    with tmp_zip.open("wb") as fh:
                        for chunk in stream.iter_bytes(chunk_size=1 << 20):
                            fh.write(chunk)
                            done += len(chunk)
                            if total:
                                self._set(
                                    percent=round(done / total * 100, 1),
                                    downloaded_mb=round(done / 1048576, 1),
                                    total_mb=round(total / 1048576, 1),
                                )

            # 3) 解压
            self._set(message="正在解压…", percent=100.0)
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            dest_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp_zip) as zf:
                zf.extractall(dest_dir)  # noqa: S202 - 来源为官方 release

            # 4) 定位 llama-server.exe
            exe = _find_llama_server(dest_dir)
            if exe is None:
                self._fail("解压完成但没找到 llama-server.exe，请手动指定。")
                return
            self._set(
                state="done",
                message=f"完成：{exe}",
                llama_server_path=str(exe),
                percent=100.0,
            )
            logger.info("llama.cpp 已就绪: %s", exe)
        except Exception as exc:  # noqa: BLE001 - 任何异常都要转成可读信息
            logger.exception("下载 llama.cpp 失败: %s", exc)
            self._fail(f"下载失败：{exc}")
        finally:
            try:
                tmp_zip.unlink(missing_ok=True)
            except OSError:
                pass


def _find_llama_server(root: Path) -> Path | None:
    """在解压目录里递归查找 llama-server(.exe)。"""
    names = {"llama-server.exe", "llama-server"}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name.lower() in names:
            return path
    return None


__all__ = [
    "pick_directory",
    "pick_file",
    "open_in_file_manager",
    "recommended_config",
    "LlamaDownloader",
    "DEFAULT_LLAMA_DIR",
]

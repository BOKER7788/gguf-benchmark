"""随包内置资源的自动定位（v1.1.1「开箱即用」）。

发布包内直接携带推理引擎与默认模型，用户解压后无需任何手工配置：

    <项目根>/llama.cpp/llama-server.exe      随包分发的推理引擎（Windows Vulkan 版）
    <项目根>/models/*.gguf                   随包分发的默认模型（Qwen3.5-0.8B Q8_0）

同时兼容用户自己的既有布局（``llama-b1234-bin-win-vulkan-x64/``、
``Qwen3.5-0.8B-GGUF/`` 以及把 llama.cpp 放在任意子目录），因此升级/迁移后
旧配置依然可用。解析顺序：显式配置（且真实存在）> 随包内置 > 常见布局。

设计约束：本模块只做只读探测，不下载、不修改任何文件；遍历时跳过 ``.venv`` /
``reports`` 等无关大目录，保证首次启动的配置加载足够快。
"""

from __future__ import annotations

import os
from pathlib import Path

from . import PROJECT_ROOT

# ---- 随包内置位置（约定的固定名，便于打包与文档描述）----
BUNDLED_LLAMA_DIR: Path = PROJECT_ROOT / "llama.cpp"
BUNDLED_MODELS_DIR: Path = PROJECT_ROOT / "models"

_SERVER_NAMES = ("llama-server.exe", "llama-server")
_GGUF_SUFFIX = ".gguf"

# traversal 时需要跳过的目录（无关且可能很大）
_SKIP_DIR_NAMES = {
    ".venv", "venv", "env", ".git", ".workbuddy", "reports", "dist",
    "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache",
}


def _walk_dirs(root: Path, max_depth: int = 3):
    """广度优先产出 ``(dir, depth)``，跳过无关目录；失败静默忽略。"""
    if not root.is_dir():
        return
    queue: list[tuple[Path, int]] = [(root, 0)]
    while queue:
        current, depth = queue.pop(0)
        yield current, depth
        if depth >= max_depth:
            continue
        try:
            entries = list(os.scandir(current))
        except OSError:  # pragma: no cover - 权限/占用
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False) and entry.name not in _SKIP_DIR_NAMES:
                    queue.append((Path(entry.path), depth + 1))
            except OSError:  # pragma: no cover
                continue


def find_llama_server(root: Path | None = None) -> Path | None:
    """定位可用的 ``llama-server`` 可执行文件（内置优先）。

    Returns:
        找到则返回绝对路径，否则 ``None``。
    """
    base = Path(root or PROJECT_ROOT)

    # 1) 随包内置的固定位置
    for name in _SERVER_NAMES:
        candidate = BUNDLED_LLAMA_DIR / name
        if candidate.is_file():
            return candidate.resolve()

    # 2) 内置目录下的任意层级
    for directory, _depth in _walk_dirs(BUNDLED_LLAMA_DIR):
        for name in _SERVER_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate.resolve()

    # 3) 项目内的常见布局（含用户自己解压的 llama-* 目录）
    for directory, _depth in _walk_dirs(base):
        if directory == base:
            continue
        for name in _SERVER_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate.resolve()
    return None


def find_models_dir(root: Path | None = None) -> Path | None:
    """定位含 ``*.gguf`` 的模型目录（内置优先）。

    Returns:
        找到则返回目录绝对路径，否则 ``None``。
    """
    base = Path(root or PROJECT_ROOT)

    def has_gguf(directory: Path) -> bool:
        try:
            return any(
                entry.is_file() and entry.name.lower().endswith(_GGUF_SUFFIX)
                for entry in os.scandir(directory)
            )
        except OSError:  # pragma: no cover
            return False

    # 1) 随包内置的固定位置
    if has_gguf(BUNDLED_MODELS_DIR):
        return BUNDLED_MODELS_DIR.resolve()

    # 2) 项目根下的任意子目录（如 Qwen3.5-0.8B-GGUF/），先浅后深
    for directory, depth in _walk_dirs(base):
        if directory in (base, BUNDLED_MODELS_DIR):
            continue
        if has_gguf(directory):
            return directory.resolve()
        if depth > 2:
            continue

    # 3) 项目根本身
    if has_gguf(base):
        return base.resolve()
    return None


def bundled_resources() -> dict:
    """报告随包内置资源的实际存在情况。

    用途：前端据此**如实**描述「本包是否带了引擎/模型」。发布包分两种——
    含内置资源（约 811 MB 模型 + 86 MB 引擎）与不含（源码包，约 3 MB）——
    如果文案写死「本包已内置」，在不含资源的包里就会误导用户。

    Returns:
        ``{"engine": bool, "engine_path": str, "models": int, "models_dir": str}``
    """
    engine = None
    for name in _SERVER_NAMES:
        candidate = BUNDLED_LLAMA_DIR / name
        if candidate.is_file():
            engine = candidate
            break

    models = 0
    if BUNDLED_MODELS_DIR.is_dir():
        try:
            models = sum(
                1
                for entry in os.scandir(BUNDLED_MODELS_DIR)
                if entry.is_file() and entry.name.lower().endswith(_GGUF_SUFFIX)
            )
        except OSError:  # pragma: no cover
            models = 0

    return {
        "engine": engine is not None,
        "engine_path": str(engine) if engine else "",
        "models": models,
        "models_dir": str(BUNDLED_MODELS_DIR) if models else "",
    }


def resolve_defaults(data: dict) -> dict:
    """就地补齐 ``llama_server_path`` / ``scan_dir``，返回同一个 dict。

    只有在「未填写」或「填写了但路径已不存在」（例如整包被移动到别的盘符）
    时才回填，绝不覆盖用户明确指定且真实存在的路径。
    """
    server = str(data.get("llama_server_path") or "").strip()
    if not server or not Path(server).expanduser().exists():
        found = find_llama_server()
        if found is not None:
            data["llama_server_path"] = str(found)

    scan = str(data.get("scan_dir") or "").strip()
    if not scan or not Path(scan).expanduser().exists():
        found_dir = find_models_dir()
        if found_dir is not None:
            data["scan_dir"] = str(found_dir)

    if not str(data.get("gpu_backend") or "").strip():
        data["gpu_backend"] = "vulkan"

    return data


__all__ = [
    "BUNDLED_LLAMA_DIR",
    "BUNDLED_MODELS_DIR",
    "bundled_resources",
    "find_llama_server",
    "find_models_dir",
    "resolve_defaults",
]

"""GGUF Benchmark — Minisforum Strix Halo 本地大模型批量测试工具。

包元信息与共享路径常量。所有其它模块通过本模块获取项目根路径，
避免在多个文件里重复 ``Path(__file__).resolve().parent.parent``。
"""

from __future__ import annotations

from pathlib import Path

__version__ = "1.0"
TOOL_NAME = "GGUF Benchmark"

# ---- 共享路径常量 ---------------------------------------------------------
PACKAGE_DIR: Path = Path(__file__).resolve().parent
PROJECT_ROOT: Path = PACKAGE_DIR.parent
WEB_DIR: Path = PROJECT_ROOT / "web"
CONFIG_DIR: Path = PROJECT_ROOT / "config"
CONFIG_FILE: Path = PROJECT_ROOT / "config.json"
DEFAULT_CONFIG_FILE: Path = CONFIG_DIR / "default_config.json"

__all__ = [
    "__version__",
    "TOOL_NAME",
    "PACKAGE_DIR",
    "PROJECT_ROOT",
    "WEB_DIR",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "DEFAULT_CONFIG_FILE",
]

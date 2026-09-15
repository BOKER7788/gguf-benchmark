"""硬件信息采集。

- ``HardwareCollector`` 抽象基类
- ``WindowsHardwareCollector``：PowerShell ``Get-CimInstance`` 采集真实硬件
- ``GenericHardwareCollector``：跨平台降级（platform 标准库），保证硬件区块非空
- ``get_collector()``：工厂，按平台选择
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from abc import ABC, abstractmethod

from .logging_utils import get_logger
from .models import HardwareInfo

logger = get_logger("hardware")

_PS_TIMEOUT = 20.0


class HardwareCollector(ABC):
    """硬件采集抽象。"""

    @abstractmethod
    def collect(self) -> HardwareInfo:
        """采集硬件信息。"""
        raise NotImplementedError


class WindowsHardwareCollector(HardwareCollector):
    """Windows 平台：通过 PowerShell CIM 查询采集。"""

    def collect(self) -> HardwareInfo:
        """采集 CPU / 主机 / 内存 / 系统 / GPU / UMA 显存。"""
        info = HardwareInfo()
        script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "$cs=Get-CimInstance Win32_ComputerSystem;"
            "$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1;"
            "$os=Get-CimInstance Win32_OperatingSystem;"
            "$bb=Get-CimInstance Win32_BaseBoard | Select-Object -First 1;"
            "$gpu=Get-CimInstance Win32_VideoController | Select-Object -First 1;"
            "[pscustomobject]@{"
            "cpu=$cpu.Name;"
            "host=$cs.Model;"
            "board=($bb.Manufacturer+' '+$bb.Product);"
            "ram=$cs.TotalPhysicalMemory;"
            "os=($os.Caption+' '+$os.Version+' ('+$os.BuildNumber+')');"
            "gpu=$gpu.Name;"
            "vram=$gpu.AdapterRAM}"
            " | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=_PS_TIMEOUT,
                check=False,
            )
            data = json.loads(completed.stdout.strip() or "{}")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:  # pragma: no cover - 环境相关
            logger.warning("PowerShell 采集失败，回退通用采集: %s", exc)
            return GenericHardwareCollector().collect()

        info.cpu_model = str(data.get("cpu") or "Unknown CPU").strip()
        host = str(data.get("host") or "").strip()
        board = str(data.get("board") or "").strip()
        info.host_model = host or board or "Unknown Host"
        try:
            info.ram_gb = round(int(data.get("ram") or 0) / (1024 ** 3), 1)
        except (TypeError, ValueError):
            info.ram_gb = 0.0
        info.os_version = str(data.get("os") or "").strip()
        info.gpu = str(data.get("gpu") or "").strip()
        try:
            vram = int(data.get("vram") or 0)
            info.uma_vram_gb = round(vram / (1024 ** 3), 1) if vram > 0 else 0.0
        except (TypeError, ValueError):
            info.uma_vram_gb = 0.0
        return info


class GenericHardwareCollector(HardwareCollector):
    """跨平台降级采集（macOS / Linux / Windows 兜底），保证字段可读非空。"""

    def collect(self) -> HardwareInfo:
        """基于 ``platform`` 标准库采集可读信息。"""
        cpu = platform.processor() or platform.machine() or "Unknown CPU"
        cpu = cpu.strip() or "Unknown CPU"
        if platform.system() == "Darwin":
            cpu = self._mac_cpu_name() or cpu
        machine = platform.machine()
        os_version = f"{platform.system()} {platform.release()} ({platform.version()})".strip()
        ram_gb = self._ram_gb()

        host_model = platform.node() or "Unknown Host"
        return HardwareInfo(
            cpu_model=cpu,
            host_model=f"{host_model} / {machine}",
            ram_gb=ram_gb,
            os_version=os_version,
            gpu="Unknown GPU（非 Windows 目标机，仅开发自测）",
            gpu_backend="",
            uma_vram_gb=0.0,
        )

    @staticmethod
    def _mac_cpu_name() -> str:
        """在 macOS 上读取更友好的 CPU 名称。"""
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return completed.stdout.strip()
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - 环境相关
            return ""

    @staticmethod
    def _ram_gb() -> float:
        """尽力获取物理内存大小（GB）。"""
        # 优先 sysconf（Linux/macOS）
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            total = pages * page_size
            if total > 0:
                return round(total / (1024 ** 3), 1)
        except (ValueError, OSError, AttributeError):
            pass
        return 0.0


def get_collector(platform_name: str | None = None, *, runner_mode: str = "auto") -> HardwareCollector:
    """工厂：按平台选择采集器。

    Args:
        platform_name: 覆盖平台名（默认取 ``sys.platform``）。
        runner_mode: ``mock`` 时强制通用采集器（开发自测）。
    """
    system = (platform_name or sys.platform).lower()
    if runner_mode == "mock":
        return GenericHardwareCollector()
    if system.startswith("win"):
        return WindowsHardwareCollector()
    return GenericHardwareCollector()


__all__ = [
    "HardwareCollector",
    "WindowsHardwareCollector",
    "GenericHardwareCollector",
    "get_collector",
]

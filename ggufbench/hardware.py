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

        # 采集不完整时不要静默变成「未知」：显式告警，并尽量补上内存这一项
        # （内存是可行性判断的必需输入，缺了它报告就没法提示「装不下」）。
        if info.ram_gb <= 0:
            info.ram_gb = GenericHardwareCollector._ram_gb()
            if info.ram_gb > 0:
                logger.warning("PowerShell 未返回内存大小，已用系统 API 补采: %s GB", info.ram_gb)
            else:
                logger.warning("内存大小采集失败（PowerShell 与系统 API 均未返回）")
        if not info.cpu_model or info.cpu_model == "Unknown CPU":
            logger.warning("CPU 型号采集失败")
        if not info.gpu:
            info.gpu = "未采集到（系统未返回显卡信息）"
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
            gpu="未采集到（当前平台不支持自动采集）",
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
        """尽力获取物理内存大小（GB）。

        Windows 上 ``os.sysconf`` 不存在，必须走 ``GlobalMemoryStatusEx``。
        v1.1.1 及更早版本没有这条分支，直接 ``return 0.0``，报告里就显示成
        「内存大小：未知」—— 恰好抹掉了判断「模型放不放得下」最需要的那一项。
        """
        if sys.platform.startswith("win"):
            try:
                import ctypes

                class _MemoryStatusEx(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                status = _MemoryStatusEx()
                status.dwLength = ctypes.sizeof(_MemoryStatusEx)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                    total = int(status.ullTotalPhys)
                    if total > 0:
                        return round(total / (1024 ** 3), 1)
            except (OSError, AttributeError, ValueError):  # pragma: no cover - 极端环境
                pass

        # 类 Unix：sysconf
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
        runner_mode: **自 v1.1.2 起不再影响采集器选择，仅为兼容旧调用保留**。

    v1.1.1 及更早版本在 ``runner_mode="mock"`` 时强制改用通用采集器，理由是
    「开发自测」。后果是 Windows 上报告显示「内存大小：未知 / GPU：Unknown GPU
    （非 Windows 目标机，仅开发自测）」—— 而 mock 只是不调用推理，这台机器
    本身并没有变。判断「这个模型装不装得下」恰恰最需要在 mock 时也能看到内存。
    """
    if runner_mode == "mock":
        logger.debug("硬件采集不再受 runner_mode 影响（v1.1.2 起）")
    system = (platform_name or sys.platform).lower()
    if system.startswith("win"):
        return WindowsHardwareCollector()
    return GenericHardwareCollector()


_hw_cache: HardwareInfo | None = None


def collect_cached(refresh: bool = False) -> HardwareInfo:
    """采集硬件信息并在进程内缓存（v1.1.2）。

    ``/api/tasks/preview`` 会在用户每次改档位时被调用，而硬件采集要起
    PowerShell（约 1 秒），实时采集会把界面拖慢。硬件在进程生命周期内不会变，
    因此缓存一次即可；采集失败时回退空 ``HardwareInfo``，由调用方判为「无法判断」。
    """
    global _hw_cache
    if _hw_cache is None or refresh:
        try:
            _hw_cache = get_collector().collect()
        except Exception:  # noqa: BLE001 - 采集失败不应影响业务
            logger.exception("硬件采集失败")
            _hw_cache = HardwareInfo()
    return _hw_cache


__all__ = [
    "HardwareCollector",
    "WindowsHardwareCollector",
    "GenericHardwareCollector",
    "collect_cached",
    "get_collector",
]

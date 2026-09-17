"""全部 Pydantic v2 数据模型（与 PRD §6 / 架构 §4 逐字段一致）。

包含：
- ``BenchmarkPoint``（14 主字段 + x-extension）
- ``ModelMeta`` / ``HardwareInfo`` / ``TaskStatus`` / ``BenchConfig``
- 内部数据类 ``RunResult``（单次推理结果，非 API 契约）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# 档位合法性上限（防止误填超大值导致矩阵爆炸）
MAX_LEVEL_VALUE = 10_000_000

# 精度固定字面量（架构 §12.1）
Precision = Literal["w8a8", "w4a8"]
# 失败原因枚举（全大写，空串表示无失败）
FailReason = Literal["OOM_GPU", "MODEL_FAIL", "TIMEOUT", "OTHER", ""]
ModelStatus = Literal["pending", "running", "done", "skipped", "failed", "aborted"]
"""模型在本次任务中的状态。

``failed`` 为 v1.1.2 新增：引擎会把「体积超出内存、直接跳过」的模型标为
``failed``。此前枚举里没有这个值，而引擎写状态时不做赋值校验（pydantic
默认 ``validate_assignment=False``），于是模型对象会带着一个非法值继续流转，
再经由 ``/api/tasks/preview`` 之类的接口回传时被服务端拒绝（HTTP 422）。
"""
TaskState = Literal["idle", "running", "aborting", "done", "error"]

# 失败原因 → 中文可读名（渲染用，US-07）
FAIL_REASON_TEXT: dict[str, str] = {
    "OOM_GPU": "显存不足(OOM)",
    "MODEL_FAIL": "模型加载失败",
    "TIMEOUT": "超时",
    "OTHER": "运行失败",
    "": "",
}


class BenchmarkPoint(BaseModel):
    """单个数据点。14 个主字段与黄金样本逐字段对齐，另加 x-extension。"""

    # ---- 14 主字段（黄金样本兼容）----
    model_name: str
    model_size: str
    precision: Precision
    n_chip: int = 1
    ctx_size: int
    input_tokens: int
    output_tokens: int = 256
    prefill_tps: float = 0.0
    decode_tps: float = 0.0
    vision_fps: float = 0.0
    prefill_time_ms: float = 0.0
    decode_time_ms: float = 0.0
    success: bool = True
    error_msg: str = ""

    # ---- x-extension（不破坏黄金样本兼容）----
    fail_reason: FailReason = ""
    skipped: bool = False


class ModelMeta(BaseModel):
    """模型元信息。"""

    model_name: str
    model_size: str
    gguf_path: str
    precision: Precision = "w8a8"
    precision_source: Literal["filename", "manual"] = "filename"
    n_chip: int = 1
    file_size_mb: float = 0.0
    selected: bool = False
    status: ModelStatus = "pending"


class HardwareInfo(BaseModel):
    """硬件信息（报告硬件区块）。"""

    cpu_model: str = "Unknown CPU"
    host_model: str = "Unknown Host"
    ram_gb: float = 0.0
    os_version: str = ""
    gpu: str = ""
    gpu_backend: str = ""
    uma_vram_gb: float = 0.0


class TaskStatus(BaseModel):
    """任务状态快照（A9 / SSE 推送）。"""

    task_id: str = ""
    state: TaskState = "idle"
    current_model: str = ""
    model_index: int = 0
    model_total: int = 0
    current_ctx: int = 0
    current_input: int = 0
    points_done: int = 0
    points_total: int = 0
    percent: float = 0.0
    last_point: Optional[BenchmarkPoint] = None
    consec_fail: int = 0
    message: str = ""

    # ---- 面向普通用户的进度信息（P0-9 耗时预估 / P0-8 mock 提示）----
    runner_mode_effective: Literal["real", "mock"] = "real"
    """实际生效的运行器类型。``auto`` 降级到 mock 时这里会是 ``mock``，
    UI 与报告据此显示「本次为模拟数据」警示。"""
    elapsed_s: float = 0.0
    """已用时（秒）。"""
    eta_s: float = 0.0
    """预计剩余时间（秒）；0 表示尚不足以估算。"""
    work_total: float = 0.0
    """总工作量（按输入 token 数加权，比单纯点数更贴近真实耗时）。"""
    work_done: float = 0.0
    """已完成工作量。"""
    report_paths: list[str] = Field(default_factory=list)
    """生成的报告绝对路径（UI 提供「打开文件夹」）。"""
    output_dir: str = ""
    """报告的绝对输出目录。"""


class BenchConfig(BaseModel):
    """测试与运行配置。

    键名与 PRD §6.5 逐字段一致；额外新增以下运行期键（架构 §12.2 + UI §5.5 需要）：
    ``runner_mode``、``prefill_timeout_s``、``scan_result``、``n_gpu_layers``、
    ``llama_version``、``host``、``backend_port``。
    """

    scan_dir: str = ""
    recursive: bool = True
    llama_server_path: str = ""
    port: int = 8080
    gpu_backend: str = "vulkan"
    extra_args: list[str] = Field(default_factory=list)
    threads: int = 16
    n_chip: int = 1
    ctx_levels: list[int] = Field(default_factory=lambda: [4000, 8000, 16000, 32000, 64000, 128000, 256000])
    input_levels: list[int] = Field(
        default_factory=lambda: [250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000, 128000]
    )
    warmup_runs: int = 1
    repeat_runs: int = 3
    output_tokens: int = 256
    precision_source: Literal["filename", "manual"] = "filename"
    prompt_text: str = ""
    output_dir: str = "./reports"
    auto_open_overview: bool = True
    skip_after_fails: int = 2

    # ---- 面向普通用户（P0-10 试跑 / P1-1 BIOS 显存提醒）----
    quick_test: bool = False
    """``True`` 时只跑「最小 ctx 档位 × 最小 input 档位」一个点，
    约 1 分钟，用于在正式压测前确认 llama-server 路径、模型加载与报告链路都正常。"""
    warn_large_ctx: bool = True
    """勾选大 ctx 档位时是否在前端提示「需先在 BIOS 划分核显显存」。"""

    # ---- 运行期扩展键 ----
    runner_mode: Literal["auto", "real", "mock"] = "auto"
    prefill_timeout_s: int = 1800
    scan_result: list[ModelMeta] = Field(default_factory=list)
    n_gpu_layers: int = 99
    llama_version: str = "unknown"
    host: str = "127.0.0.1"
    backend_port: int = 8765

    # ---- 校验（P2 修复：档位/端口合法性）----
    @field_validator("ctx_levels", "input_levels")
    @classmethod
    def _validate_levels(cls, value: object) -> list[int]:
        """校验档位：必须为正整数、去重升序、且不超过上限。"""
        if not isinstance(value, (list, tuple)):
            raise ValueError("档位必须为列表")
        normalized: list[int] = []
        for item in value:
            try:
                number = int(item)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"档位必须为整数: {item!r}") from exc
            if number <= 0:
                raise ValueError(f"档位必须为正整数: {number}")
            if number > MAX_LEVEL_VALUE:
                raise ValueError(f"档位超出上限 {MAX_LEVEL_VALUE}: {number}")
            normalized.append(number)
        return sorted(set(normalized))

    @field_validator("port", "backend_port")
    @classmethod
    def _validate_port(cls, value: int) -> int:
        """校验端口范围 1..65535。"""
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("端口必须为整数") from exc
        if not 1 <= number <= 65535:
            raise ValueError(f"端口范围 1..65535，收到 {number}")
        return number


@dataclass
class RunResult:
    """单次推理结果（内部，非 API 契约）。"""

    prompt_tokens: int = 0
    prompt_ms: float = 0.0
    predicted_tokens: int = 0
    predicted_ms: float = 0.0
    exit_code: int = 0
    timed_out: bool = False
    stderr_tail: str = ""
    ok: bool = True


__all__ = [
    "Precision",
    "FailReason",
    "ModelStatus",
    "TaskState",
    "FAIL_REASON_TEXT",
    "BenchmarkPoint",
    "ModelMeta",
    "HardwareInfo",
    "TaskStatus",
    "BenchConfig",
    "RunResult",
]

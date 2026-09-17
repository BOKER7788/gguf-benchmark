"""确定性测试夹具：用 mock 引擎现场生成「2 模型 × 49 点」的完整报告产物。

回归套件的 D / E / H / I 四个模块需要一个**形状确定**的报告集合：2 个模型、
每个模型 49 个数据点，并且包含 ``overview.html``、``all_points.json`` 与每个
模型的 ``points.json``。

这些产物属于运行结果，不在发布包内（``.gitignore`` 排除了 ``reports/``），
所以 v1.1.0 的测试在干净解压后必然崩在 ``FileNotFoundError``。这里改为在临时
目录里**走生产代码路径**（``BenchEngine`` + ``MockRunner`` + ``ReportBuilder``）
现场生成，测试因此自洽、可重复，也不再依赖开发机上的历史残留文件。

用 mock 而非真实推理：这些模块校验的是**报告结构与前端逻辑**，不是性能数字，
因此不需要 llama-server，也不应受机器差异影响。
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

import _harness  # noqa: F401 - 导入即把 PROJECT_ROOT 放进 sys.path

from ggufbench.engine import BenchEngine
from ggufbench.models import BenchConfig, ModelMeta

# 固定 2 个模型：D11/D12 断言「模型数 × 49 = 98 点」
FIXTURE_MODELS: list[tuple[str, str, str]] = [
    ("ModelA-2B-Q8_0", "2B", "w8a8"),
    ("ModelB-4B-Q4_K_M", "4B", "w4a8"),
]

# 每个模型的数据点数（默认 ctx × input 矩阵裁剪结果）
EXPECTED_POINTS_PER_MODEL = 49

_cache: Path | None = None


def build_fixture(out_dir: Path) -> Path:
    """在 ``out_dir`` 下生成夹具报告产物，返回该目录。"""
    cfg = BenchConfig(
        runner_mode="mock",
        output_dir=str(out_dir),
        warmup_runs=0,
        repeat_runs=1,
        auto_open_overview=False,
    )
    engine = BenchEngine(cfg, generate_reports=True)
    models = [
        ModelMeta(
            model_name=name,
            model_size=size,
            gguf_path=f"/fixture/{name}.gguf",
            precision=precision,  # type: ignore[arg-type]
            selected=True,
        )
        for name, size, precision in FIXTURE_MODELS
    ]
    engine.run(models)

    # 引擎内部对异常做了兜底（state=error），这里显式校验产物是否齐全，
    # 避免夹具不完整时测试给出误导性的失败信息。
    overview = out_dir / "overview.html"
    all_points = out_dir / "all_points.json"
    model_htmls = sorted(p for p in out_dir.glob("*.html") if p.name != "overview.html")
    missing = [str(p) for p in (overview, all_points) if not p.exists()]
    if missing or len(model_htmls) != len(FIXTURE_MODELS):
        raise RuntimeError(
            f"测试夹具生成不完整：missing={missing} model_htmls={[p.name for p in model_htmls]} "
            f"engine_state={engine.status.state} message={engine.status.message}"
        )
    return out_dir


def fixture_dir() -> Path:
    """返回（并在首次调用时生成）夹具目录；同一进程内复用。"""
    global _cache
    if _cache is None or not _cache.exists():
        out = Path(tempfile.mkdtemp(prefix="ggufbench_fixture_"))
        _cache = build_fixture(out)
        atexit.register(shutil.rmtree, str(out), ignore_errors=True)
    return _cache


def fixture_overview() -> Path:
    """夹具里的 ``overview.html`` 路径。"""
    return fixture_dir() / "overview.html"


__all__ = [
    "FIXTURE_MODELS",
    "EXPECTED_POINTS_PER_MODEL",
    "build_fixture",
    "fixture_dir",
    "fixture_overview",
]

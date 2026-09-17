"""I. 零基础用户友好度（P0/P1 改造的契约）。

覆盖两类：
1. **后端能力**：人话错误解释、硬件推荐、mock 预判、llama-server 校验、
   试跑矩阵、进度里的 ETA 字段；
2. **交付约束**：品牌词已清除、署名到位、批处理内置 winget 与国内镜像、
   前端已接入新交互。
"""

from __future__ import annotations

import re
from pathlib import Path

from _fixture import fixture_overview
from _harness import PROJECT_ROOT, Suite

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from ggufbench import AUTHOR
from ggufbench.engine import BenchEngine
from ggufbench.errors import HINTS, ErrorCode
from ggufbench.models import BenchConfig

APP_JS = PROJECT_ROOT / "web" / "app.js"
INDEX = PROJECT_ROOT / "web" / "index.html"
START_BAT = PROJECT_ROOT / "start.bat"

# 用户明确要求：整个程序与结果中不得出现这些品牌词
FORBIDDEN = re.compile(r"minisforum|strix|ryzen\s+ai|radeon\s+8060", re.I)

SCAN_EXTS = {".py", ".js", ".html", ".css", ".md", ".bat", ".json", ".mermaid", ".txt"}
# llama.cpp / models 是随包分发的第三方二进制与权重，dist 是打包输出，均不参与品牌词扫描
SKIP_DIRS = {".venv", ".git", ".workbuddy", "__pycache__", "reports", "node_modules",
             "llama.cpp", "models", "dist"}
# 守卫脚本自身与被测产物要排除：前者含用于检测的禁用词字面量，后者是运行产物
SKIP_FILES = {"test_I_friendly.py", "_results.json", "ONBOARDING-AUDIT.md"}


def _iter_project_files():
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(PROJECT_ROOT).parts):
            continue
        if path.suffix.lower() in SCAN_EXTS:
            yield path


def run() -> Suite:
    s = Suite("I. 零基础用户友好度")
    report_path = fixture_overview()
    report = report_path.read_text(encoding="utf-8")

    # =====================================================================
    #  1. 品牌词清除 + 署名（用户的硬性要求）
    # =====================================================================
    hits: list[str] = []
    for path in _iter_project_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{path.relative_to(PROJECT_ROOT)}:{i}")
    s.check("I1", "全项目无 Minisforum / Strix Halo / Ryzen AI / Radeon 8060 等品牌词",
            not hits, f"命中: {hits[:8]}")

    s.eq("I1b", "包元信息里的作者署名", AUTHOR, "Boker")

    if report_path.exists():
        s.check("I1c", "报告页脚含作者署名",
                ("by " + AUTHOR) in report)
        s.check("I1d", "报告内除 SVG 命名空间外不含任何外部 URL",
                all("w3.org/2000/svg" in u for u in re.findall(r"https?://[^\s\"'<>]+", report)),
                f"URL 样例={re.findall(r'https?://[^\\s\"\'<>]+', report)[:5]}")
    else:  # pragma: no cover - 夹具构造失败
        s.check("I1c", "存在夹具报告 overview.html", False, "缺报告")

    # =====================================================================
    #  2. 人话化错误解释（P1-2）
    # =====================================================================
    missing_code = [c.value for c in ErrorCode if c.value not in HINTS]
    s.check("I2", "所有错误码都有人话解释", not missing_code, f"缺: {missing_code}")
    reasons = ["OOM_GPU", "MODEL_FAIL", "TIMEOUT", "OTHER"]
    s.check("I2b", "所有失败原因都有人话解释",
            all(r in HINTS for r in reasons), f"缺: {[r for r in reasons if r not in HINTS]}")
    bad = [
        k for k, v in HINTS.items()
        if not v.get("what", "").strip() or not v.get("how", "").strip()
    ]
    s.check("I2c", "每条解释都同时含「什么意思」与「该怎么做」", not bad, f"不完整: {bad}")

    # =====================================================================
    #  3. 试跑矩阵（P0-10）
    # =====================================================================
    cfg = BenchConfig()
    eng = BenchEngine(cfg, generate_reports=False)
    full = eng.effective_matrix(quick=False)
    quick = eng.effective_matrix(quick=True)
    s.eq("I3a", "完整矩阵为 49 组", full["total"], 49)
    s.eq("I3b", "试跑矩阵只有 1 组", quick["total"], 1)
    s.eq("I3c", "试跑取最小 ctx × 最小 input",
          quick["pairs"], [(min(cfg.ctx_levels), min(cfg.input_levels))])

    s.eq("I3d", "config.quick_test=True 时 effective_matrix 自动生效",
          BenchEngine(BenchConfig(quick_test=True), generate_reports=False)
          .effective_matrix()["total"], 1)

    # =====================================================================
    #  4. 进度新增字段：ETA / 已用时 / 工作量（P0-9）
    # =====================================================================
    eng.status.work_total = 1000.0
    eng.status.work_done = 100.0
    eng._started_at = 0.0
    s.check("I4a", "TaskStatus 含 elapsed_s / eta_s / work_done",
            hasattr(eng.status, "elapsed_s") and hasattr(eng.status, "eta_s")
            and hasattr(eng.status, "work_done"))
    s.eq("I4b", "未开始时 elapsed_s 为 0", eng.status.elapsed_s, 0.0)
    s.check("I4c", "工作量按输入 token 加权（work_total > 点数）",
            eng.status.work_total > full["total"])

    # =====================================================================
    #  5. mock 预判（P0-8）—— 绝不能静默降级
    # =====================================================================
    from ggufbench.runners import resolve_runner_mode

    s.eq("I5a", "auto + 无 llama-server → 预判为 mock",
          resolve_runner_mode(BenchConfig(runner_mode="auto", llama_server_path="/nope/x")), "mock")
    s.eq("I5b", "auto + 有 llama-server → 预判为 real",
          resolve_runner_mode(BenchConfig(runner_mode="auto", llama_server_path=__file__)), "real")
    s.eq("I5c", "显式 mock → mock",
          resolve_runner_mode(BenchConfig(runner_mode="mock")), "mock")

    s.check("I5d", "mock 配置的报告含醒目 mock 警示条", "mock-banner" in report)
    s.check("I5e", "报告含「这份报告怎么看」结论层", "这份报告怎么看" in report)

    # =====================================================================
    #  6. 交付约束：批处理与前端（P0-2 / P0-5 / P0-6 / P0-7）
    # =====================================================================
    start = START_BAT.read_text(encoding="utf-8", errors="ignore")
    s.check("I6a", "start.bat 内置 winget 一键安装 Python",
            "winget install" in start and "Python.Python.3.12" in start)
    s.check("I6b", "start.bat 未找到 Python 时先解释「应用执行别名」原因",
            "应用执行别名" in start)
    s.check("I6c", "start.bat 依赖使用国内镜像（可用环境变量覆盖）",
            "GGUF_BENCH_PIP_INDEX" in start and "tuna.tsinghua.edu.cn" in start)
    s.check("I6d", "start.bat 依赖已装则跳过（不再每次静默等待）",
            "跳过安装" in start)
    s.check("I6e", "start.bat 不再用 --quiet 静默安装",
            "--quiet" not in start)

    app = APP_JS.read_text(encoding="utf-8", errors="ignore")
    for cid, name, needle in [
        ("I7a", "前端接入原生文件夹选择", "pickDir"),
        ("I7b", "前端接入原生文件选择", "pickFile"),
        ("I7c", "前端接入一键获取 llama.cpp", "llamaDownload"),
        ("I7d", "前端接入 llama-server 可用性校验", "llamaCheck"),
        ("I7e", "前端接入报告文件夹打开", "openFolder"),
        ("I7f", "前端展示预计耗时", "timeEstimate"),
        ("I7g", "前端在大 ctx 档位提示显存划分", "biosWarn"),
        ("I7h", "前端支持试跑 1 个档位", "quick_test"),
        ("I7i", "前端展示预计剩余时间", "etaText"),
        ("I7j", "前端未设置 llama-server 时会二次确认", "confirm("),
    ]:
        s.check(cid, name, needle in app)

    index = INDEX.read_text(encoding="utf-8", errors="ignore")
    for cid, name, needle in [
        ("I8a", "上手页含三步向导", "三步上手"),
        ("I8b", "扫描页含模型获取指引", "还没有模型文件"),
        ("I8c", "扫描页给出国内模型站入口", "modelscope.cn"),
        ("I8d", "配置页把高级项收进折叠区", "高级设置"),
        ("I8e", "提供「先试跑」按钮", "quickTestBtn"),
        ("I8f", "提供「打开报告所在文件夹」按钮", "openFolderBtn"),
        ("I8g", "品牌区显示署名", "by Boker"),
    ]:
        s.check(cid, name, needle in index)
    # I8h/I8i：界面文案不得把「本包已内置资源」写死在 HTML 里。
    # 发布包有「含内置资源」与「轻量版（不含）」两种，写死会在轻量版里说谎；
    # 正确做法是由 /api/health 的 bundled_engine / bundled_models 驱动（见 I9f/I9g）。
    s.check("I8h", "上手向导的②③说明改为动态占位（step2Hint/step3Hint）",
            'id="step2Hint"' in index and 'id="step3Hint"' in index)
    s.check("I8i", "页面不再写死「本包已内置」字样",
            "本包<b>已内置</b>" not in index) 

    # =====================================================================
    #  7. 新增接口可用（P0-3 / P0-6 / P0-7）
    # =====================================================================
    if TestClient is None:  # pragma: no cover
        s.note("TestClient 不可用，跳过 I9")
        return s

    from ggufbench.app import create_app

    client = TestClient(create_app())
    s.eq("I9a", "GET /api/hints 返回全部解释",
          len(client.get("/api/hints").json().get("hints", {})), len(HINTS))
    s.check("I9b", "GET /api/hints/OOM_GPU 返回两条人话",
            bool(client.get("/api/hints/OOM_GPU").json()["hint"]["how"]))
    rec = client.get("/api/hardware/recommend").json()
    s.check("I9c", "GET /api/hardware/recommend 给出合法后端",
            rec.get("gpu_backend") in {"vulkan", "cuda", "rocm", "metal", "cpu"},
            f"got={rec.get('gpu_backend')}")
    s.check("I9d", "GET /api/hardware/recommend 给出线程数",
            isinstance(rec.get("threads"), int) and rec["threads"] >= 2)
    rm = client.get("/api/runner-mode").json()
    s.check("I9e", "GET /api/runner-mode 明确告知是否会用 mock",
            "will_use_mock" in rm and isinstance(rm["will_use_mock"], bool))

    # I9f/I9g：健康检查必须自报「本包带了什么」，界面才能如实描述。
    # 否则轻量版（无 llama.cpp/ 与 models/）会显示「本包已内置」并让用户去找不存在的文件。
    from ggufbench.bundle import bundled_resources

    health = client.get("/api/health").json()
    s.check("I9f", "GET /api/health 自报 bundled_engine / bundled_models",
            "bundled_engine" in health and "bundled_models" in health,
            f"keys={sorted(health)[:12]}")
    res = bundled_resources()
    s.eq("I9g", "/api/health 的 bundled_engine 与磁盘实际一致",
          bool(health.get("bundled_engine")), bool(res["engine"]))
    s.eq("I9h", "/api/health 的 bundled_models 与磁盘实际一致",
          int(health.get("bundled_models") or 0), int(res["models"]))
    s.check("I9i", "前端依据 bundled_* 渲染内置说明（不写死）",
            "bundled_engine" in app and "bundled_models" in app)
    chk = client.post("/api/llama/check", json={"path": "/definitely/not/here"}).json()
    s.eq("I9f", "POST /api/llama/check 对不存在路径返回 exists=False", chk["exists"], False)
    dl = client.get("/api/llama/download/status").json()
    s.eq("I9g", "GET /api/llama/download/status 初始为 idle", dl["state"], "idle")

    return s

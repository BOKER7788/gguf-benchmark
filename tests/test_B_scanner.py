"""B. 模型识别（P0，黄金路径外最易出错）。

对抗性测试：分片 gguf、mmproj、非 gguf 文件、精度推断、空目录、递归行为。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from _harness import Suite

from ggufbench.errors import ApiError, ErrorCode
from ggufbench.scanner import ModelScanner


def _touch(p: Path, data: bytes = b"gguf") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def run() -> Suite:
    s = Suite("B. 模型识别")
    sc = ModelScanner()

    # ---- B1 分片 gguf：应合并为单模型，而非多个独立模型 ----
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _touch(root / "Big-3B-00001-of-00003.gguf", b"x" * (1024 * 1024))
        _touch(root / "Big-3B-00002-of-00003.gguf", b"x" * (2 * 1024 * 1024))
        _touch(root / "Big-3B-00003-of-00003.gguf", b"x" * (3 * 1024 * 1024))
        models = sc.scan(d)
        s.eq("B1", "分片 gguf(3 分片) 合并为单模型", len(models), 1)
        if models:
            m = models[0]
            s.eq("B1b", "分片模型名去掉 -0000x-of-0000y 后缀", m.model_name, "Big-3B")
            s.eq("B1c", "分片尺寸求和 = 6.0MB (1+2+3)", m.file_size_mb, 6.0)
            s.check("B1d", "gguf_path 指向首个分片",
                    m.gguf_path.endswith("Big-3B-00001-of-00003.gguf"), f"path={m.gguf_path}")

    # B1e 分片与独立文件混合：分片合并 + 独立保留
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _touch(root / "S-2B-00001-of-00002.gguf", b"x" * 1024)
        _touch(root / "S-2B-00002-of-00002.gguf", b"x" * 1024)
        _touch(root / "Solo-Q8_0.gguf")
        models = sc.scan(d)
        names = sorted(m.model_name for m in models)
        s.eq("B1e", "分片与独立文件混合 → 合并 + 保留",
              names, ["S-2B", "Solo-Q8_0"])

    # ---- B2 mmproj 必须被过滤 ----
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _touch(root / "Qwen-2B-Q4_K_M.gguf")
        _touch(root / "mmproj-model-f16.gguf")
        _touch(root / "mm_projector.gguf")
        models = sc.scan(d)
        names = [m.model_name for m in models]
        s.check(
            "B2",
            "mmproj / mm_projector 被过滤",
            all("mmproj" not in n.lower() and "mm_projector" not in n.lower() for n in names),
            f"候选: {names}",
        )
        ignored = sc.list_ignored(d)
        s.check(
            "B2b",
            "list_ignored 报告被忽略的 mmproj",
            set(ignored) == {"mmproj-model-f16.gguf", "mm_projector.gguf"},
            f"ignored={ignored}",
        )

    # ---- B3 非 gguf 文件被忽略 ----
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _touch(root / "model-A-Q8_0.gguf")
        for extra in ("tokenizer.json", "config.json", "README.md", "model.safetensors"):
            _touch(root / extra, b"{}")
        models = sc.scan(d)
        s.eq("B3", "仅返回 .gguf 候选", [m.model_name for m in models], ["model-A-Q8_0"])

    # ---- B4 精度推断 ----
    cases = {
        "Qwen3.5-0.8B-Q8_0.gguf": "w8a8",
        "Qwen3.5-2B-Q4_K_M.gguf": "w4a8",
        "model-w8a8.gguf": "w8a8",
        "model-w4a8.gguf": "w4a8",
        "model-int8.gguf": "w8a8",
        "model-int4.gguf": "w4a8",
        "model-mxfp4.gguf": "w4a8",
        "no-quant-tag.gguf": "w8a8",  # 兜底
        "weird.gguf": "w8a8",  # 兜底
    }
    for fn, exp in cases.items():
        s.eq("B4", f"精度推断 {fn} → {exp}", ModelScanner.infer_precision(fn), exp)

    # 精度 Q4_K_M 不应被 q8 误判（顺序敏感）
    s.eq("B4b", "Q4_K_M 优先判 w4a8", ModelScanner.infer_precision("x-Q4_K_M-q8_0.gguf"), "w4a8")

    # ---- B5 尺寸解析 ----
    size_cases = {
        "Qwen3.5-0.8B-Q8_0.gguf": "0.8B",
        "Qwen-2B-Q4.gguf": "2B",
        "Llama-35b.gguf": "35B",
        "no-size.gguf": "Unknown",
    }
    for fn, exp in size_cases.items():
        s.eq("B5", f"尺寸解析 {fn} → {exp}", ModelScanner.parse_size(fn), exp)

    # ---- B6 空目录 / 无 gguf ----
    with tempfile.TemporaryDirectory() as d:
        try:
            empty = sc.scan(d)
            s.check("B6", "空目录不崩溃（返回空列表）", empty == [], f"got={empty}")
        except Exception as exc:  # noqa: BLE001
            s.check("B6", "空目录不崩溃（返回空列表）", False, repr(exc))

        _touch(Path(d) / "note.txt", b"x")
        try:
            nogguf = sc.scan(d)
            # PRD US-01③ 要求的是"无 gguf 时给出明确空态提示"，非错误码。
            s.check("B6b", "无 gguf 目录：不崩溃并返回空列表（PRD US-01③ 空态语义）",
                    nogguf == [], f"实际返回 {nogguf}")
            # 前端需有中文空态提示
            app_js = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text(encoding="utf-8")
            s.check("B6c", "前端含中文空态提示文案",
                    "尚未扫描或目录内无 .gguf 文件" in app_js, "app.js 未见空态提示")
            s.note("E_NO_GGUF 错误码在 errors.py:20 定义但全项目从未抛出（死代码）；"
                   "PRD US-01③ 明确要求的是 UI 空态提示而非错误码，故非功能缺陷（低优先级清理项）。")
        except Exception as exc:  # noqa: BLE001
            s.check("B6b", "无 gguf 目录不崩溃", False, repr(exc))

    # ---- B7 不存在目录 → E_DIR_NOT_FOUND 且中文 ----
    with tempfile.TemporaryDirectory() as d:
        missing = str(Path(d) / "does-not-exist")
        try:
            sc.scan(missing)
            s.check("B7", "不存在目录抛 E_DIR_NOT_FOUND", False, "未抛异常")
        except ApiError as exc:
            chinese = any("\u4e00" <= ch <= "\u9fff" for ch in exc.message)
            s.check(
                "B7",
                "不存在目录抛 E_DIR_NOT_FOUND（中文）",
                exc.code == ErrorCode.E_DIR_NOT_FOUND and chinese and exc.status_code == 400,
                f"code={exc.code} status={exc.status_code} msg={exc.message}",
            )
        except Exception as exc:  # noqa: BLE001
            s.check("B7", "不存在目录抛 E_DIR_NOT_FOUND", False, repr(exc))

    # ---- B8 递归 vs 非递归 ----
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _touch(root / "top-Q8_0.gguf")
        _touch(root / "sub" / "nested-Q4_K_M.gguf")
        rec = sorted(m.model_name for m in sc.scan(d, recursive=True))
        non = sorted(m.model_name for m in sc.scan(d, recursive=False))
        s.eq("B8", "递归扫描含子目录模型", rec, ["nested-Q4_K_M", "top-Q8_0"])
        s.eq("B8b", "非递归仅扫顶层", non, ["top-Q8_0"])

    # ---- B9 隐藏文件 / 大文件不影响识别 ----
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _touch(root / ".hidden-Q8_0.gguf")
        models = sc.scan(d)
        s.check("B9", "隐藏 .gguf 仍被识别（行为记录）", len(models) == 1, f"names={[m.model_name for m in models]}")

    # ---- B10 跨子目录同名分片必须各自独立（回归：曾按 base 归并导致漏测一个模型）----
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for sub in ("A", "B"):
            _touch(root / sub / "model-00001-of-00002.gguf")
            _touch(root / sub / "model-00002-of-00002.gguf")
        models = sc.scan(d, recursive=True)
        s.eq("B10", "跨子目录同名分片不被误合并（期望 2 个模型）", len(models), 2)
        s.eq("B10b", "两个模型文件大小各自独立求和（各 2 字节组）",
             sorted(round(m.file_size_mb, 4) for m in models), [0.0, 0.0])

    # ---- B11 只存在末片时仍归并为单模型 ----
    with tempfile.TemporaryDirectory() as d:
        _touch(Path(d) / "Solo-7B-00003-of-00003.gguf")
        models = sc.scan(d)
        s.eq("B11", "仅末片存在时仍识别为 1 个模型", len(models), 1)
        s.eq("B11b", "模型名去分片后缀", models[0].model_name if models else None, "Solo-7B")

    # ---- B12 非零填充分片号（-1-of-2）：记录当前行为，llama.cpp 实际不产出此命名 ----
    with tempfile.TemporaryDirectory() as d:
        _touch(Path(d) / "np-1-of-2.gguf")
        _touch(Path(d) / "np-2-of-2.gguf")
        models = sc.scan(d)
        s.check("B12", "非零填充分片号不归并（已知限制，llama.cpp 均为 5 位零填充）",
                len(models) == 2, f"models={[m.model_name for m in models]}")

    return s

"""打包「开箱即用」发布 ZIP（v1.1.1）。

v1.1.0 的打包脚本依赖 ``git ls-files``，在**没有 .git 的目录**（例如从 ZIP 解压
出来的源码）里会直接 ``CalledProcessError``；而且发布包不含推理引擎与模型，
用户解压后还得自己下载。

这里改为**显式清单 + 递归排除**：扫描项目根，按白名单收文件、按黑名单排除
运行产物，并把随包内置的资源一并收进包内：

    llama.cpp/        推理引擎（Windows Vulkan 版，约 86 MB）
    models/           默认模型 Qwen3.5-0.8B-Q8_0.gguf（约 811 MB）

于是用户解压后**无需任何下载与配置**，双击 ``start.bat`` 即可试用完整流程。

用法::

    .venv/bin/python scripts/make_release_zip.py                # 输出到 dist/（含内置资源）
    .venv/bin/python scripts/make_release_zip.py --out D:/rel   # 指定输出目录
    .venv/bin/python scripts/make_release_zip.py --no-bundle    # 轻量版（不含引擎/模型）

两种包的对比：

    gguf-benchmark-v1.1.2-win.zip         约 805 MB  开箱即用（含 llama.cpp/ 与 models/）
    gguf-benchmark-v1.1.2-win-lite.zip    约   3 MB  仅源码；用户自备引擎与模型

轻量版**必须**改用 ``README_FIRST_LITE`` 作为包内说明：仓库里的 ``请先读我.txt``
是给「含内置资源」的包写的（写着"本包已经内置引擎与模型"），
直接复用会在轻量包里说谎。界面文案同理——``/api/health`` 会返回
``bundled_engine`` / ``bundled_models``，前端据此如实渲染。
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ggufbench import __version__  # noqa: E402

# 包内最外层目录名（与 v1.1.0 保持一致，避免既有文档/链接失效）
INNER_ROOT = "gguf-benchmark"

# ---- 递归排除：目录名 -------------------------------------------------------
EXCLUDE_DIR_NAMES = {
    ".venv", "venv", "env", ".git", ".github", ".workbuddy", ".idea", ".vscode",
    "reports", "dist", "__pycache__", "node_modules",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".eggs",
}

# ---- 递归排除：文件名 -------------------------------------------------------
EXCLUDE_FILE_NAMES = {
    "config.json",          # 用户运行期配置，首次启动自动生成
    "_results.json",        # 测试运行产物
    "startup-error.log",    # 崩溃日志（若有）
    "请先读我.txt",          # 由本脚本按当前版本号重新生成（见 README_FIRST）
    ".DS_Store", "Thumbs.db", "desktop.ini",
}

# ---- 递归排除：文件名模式（fnmatch）----------------------------------------
EXCLUDE_FILE_PATTERNS = ("*.pyc", "*.pyo", "*.log", "*.tmp", "*.bak", "*.orig")

# ---- 体积大且不该重复打包的兼容目录 ----------------------------------------
# 开发机上可能同时存在「原始解压目录」与「正式内置目录」，二者内容相同。
# 打包时只保留 llama.cpp/ 与 models/，避免发布包平白翻倍。
EXCLUDE_COMPAT_DIRS = {"llama-b10989-bin-win-vulkan-x64", "Qwen3.5-0.8B-GGUF"}

# ---- 内置资源（--no-bundle 时跳过）-----------------------------------------
BUNDLE_DIRS = ("llama.cpp", "models")

# 压缩策略：.gguf 已高度熵编码，再 deflate 收益极小却很慢 → 直接存储
STORE_SUFFIXES = {".gguf", ".zip", ".7z", ".gz", ".xz", ".zst"}

README_FIRST = """GGUF Benchmark v{version}  —— by Boker
================================================

这是一个在 Windows 上运行的本地大模型性能测试工具。
报告是单文件 HTML，可以直接分享、离线打开。

【本包已经内置引擎与模型，无需额外下载】
    llama.cpp\\llama-server.exe      推理引擎（Windows Vulkan 版）
    models\\Qwen3.5-0.8B-Q8_0.gguf   默认模型

【怎么用】只需要两步

  第 1 步：双击  start.bat
      · 如果电脑上没有 Python，脚本会问你一句，按 Y 会自动帮你装好。
      · 第一次运行需要装几个依赖（约 1-3 分钟），窗口里会显示进度。

  第 2 步：浏览器会自动打开，直接点「先试跑 1 个档位」
      · 跑的默认就是本包内置的 Qwen3.5-0.8B，无需任何配置。
      · 试跑通过后，再点「开始完整测试」跑全部 49 个档位。

  想停止服务：双击  stop.bat

【想换自己的模型】
  把 .gguf 文件放进 models\\ 目录（或任意目录），回到页面点「扫描」即可。
  想换新版本 llama.cpp：整个目录替换掉 llama.cpp\\ 即可。

【先看效果】
  docs/demo/overview.html 是演示报告，直接用浏览器打开，
  把鼠标放在曲线上滑动就能看到每个档位的数值。
  注意：演示报告里的数字是模拟数据，不是你机器的真实性能。

【常见问题】
  见 README.md 的「常见问题（Windows）」一节。

【测试】
  想验证程序本身没坏，可以运行：
      .venv\\Scripts\\python tests\\run_all.py
"""


README_FIRST_LITE = """GGUF Benchmark v{version}  —— by Boker  （轻量版 · 不含引擎与模型）
================================================

这是一个在 Windows 上运行的本地大模型性能测试工具。
报告是单文件 HTML，可以直接分享、离线打开。

【本包不含推理引擎与模型，需自备（两样都准备好即可开始）】
    ① 推理引擎：llama.cpp 的 llama-server.exe
    ② 模型文件：任意 .gguf 文件

  ▸ 你手上有现成的？直接指定就行，不用重新下载：
      · 引擎：页面上点「手动选择已有的 llama-server.exe」
      · 模型：把 .gguf 放进 models\\ 目录，或到「② 选模型」指定它所在的文件夹
  ▸ 你手上没有？页面会帮你：
      · 引擎：点「获取 / 更新 llama.cpp」自动下载 Windows Vulkan 版（约 200MB）
      · 模型：到模型网站搜索「模型名 GGUF」，下载一个 .gguf 放进 models\\

  若想要「开箱即用、什么都不用配」的版本，请下载
      gguf-benchmark-v{version}-win.zip（约 805 MB，已内置引擎与 0.8B 模型）。

【怎么用】只需要两步

  第 1 步：双击  start.bat
      · 如果电脑上没有 Python，脚本会问你一句，按 Y 会自动帮你装好。
      · 第一次运行需要装几个依赖（约 1-3 分钟），窗口里会显示进度。

  第 2 步：浏览器会自动打开，把上面①②两样准备好后点「先试跑 1 个档位」
      · 试跑通过后，再点「开始完整测试」跑全部 49 个档位。

  想停止服务：双击  stop.bat

【体积说明】
  本包故意不含引擎与模型，所以只有几 MB，下载很快；引擎与模型可以复用
  你已有的文件，不必为了试用再下载一遍。

【先看效果】
  docs/demo/overview.html 是演示报告，直接用浏览器打开，
  把鼠标放在曲线上滑动就能看到每个档位的数值。
  注意：演示报告里的数字是模拟数据，不是你机器的真实性能。

【常见问题】
  见 README.md 的「常见问题（Windows）」一节。

【测试】
  想验证程序本身没坏，可以运行：
      .venv\\Scripts\\python tests\\run_all.py
"""


def _is_excluded_dir(name: str) -> bool:
    return name in EXCLUDE_DIR_NAMES or name in EXCLUDE_COMPAT_DIRS


def collect_files(include_bundle: bool = True) -> list[Path]:
    """扫描项目根，返回要打进包的文件（相对 PROJECT_ROOT 的路径）。

    规则：递归遍历，按黑名单排除目录/文件，其余全部收录。
    这样新增源码文件无需修改本脚本（旧的 git ls-files 方案反而更脆）。
    """
    import fnmatch

    result: list[Path] = []
    skip_bundle = {PROJECT_ROOT / d for d in BUNDLE_DIRS} if not include_bundle else set()

    stack = [PROJECT_ROOT]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if _is_excluded_dir(entry.name) or entry in skip_bundle:
                    continue
                # 符号链接/联接点不跟随，避免打包时意外拉入整盘
                if entry.is_symlink():
                    continue
                stack.append(entry)
            elif entry.is_file():
                if entry.name in EXCLUDE_FILE_NAMES:
                    continue
                if any(fnmatch.fnmatch(entry.name, pat) for pat in EXCLUDE_FILE_PATTERNS):
                    continue
                result.append(entry.relative_to(PROJECT_ROOT))

    return sorted(result, key=lambda p: str(p).lower())


def build(out_dir: Path, include_bundle: bool = True) -> Path:
    files = collect_files(include_bundle=include_bundle)
    if not files:
        raise SystemExit(f"在 {PROJECT_ROOT} 下没有找到可打包的文件")

    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if include_bundle else "-lite"
    zip_path = out_dir / f"gguf-benchmark-v{__version__}-win{suffix}.zip"

    total_raw = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in files:
            src = PROJECT_ROOT / rel
            if not src.is_file():
                continue
            total_raw += src.stat().st_size
            compress = (
                zipfile.ZIP_STORED
                if src.suffix.lower() in STORE_SUFFIXES
                else zipfile.ZIP_DEFLATED
            )
            zf.write(src, f"{INNER_ROOT}/{rel.as_posix()}", compress_type=compress)

        # 包内说明文件：含内置资源时优先用仓库里的 请先读我.txt（与 GitHub 上保持一致），
        # 缺失时回退到内置模板；轻量版必须换用 README_FIRST_LITE（否则会说谎）。
        # 同一路径只写一次，避免 zip 里出现重复条目。
        if include_bundle:
            readme_src = PROJECT_ROOT / "请先读我.txt"
            readme_text = (
                readme_src.read_text(encoding="utf-8")
                if readme_src.is_file()
                else README_FIRST.format(version=__version__)
            )
        else:
            readme_text = README_FIRST_LITE.format(version=__version__)
        zf.writestr(f"{INNER_ROOT}/请先读我.txt", readme_text)
    size_mb = zip_path.stat().st_size / 1048576
    print(f"已生成: {zip_path}")
    print(f"  收录文件: {len(files) + 1} 个（含 请先读我.txt）")
    print(f"  原始体积: {total_raw / 1048576:.1f} MB")
    print(f"  压缩体积: {size_mb:.1f} MB")
    _verify(zip_path, include_bundle)
    return zip_path


def _verify(zip_path: Path, include_bundle: bool = True) -> None:
    """自检：确认关键入口都在包里，且「有没有内置资源」与包型一致。"""
    common = [
        f"{INNER_ROOT}/run.py",
        f"{INNER_ROOT}/start.bat",
        f"{INNER_ROOT}/stop.bat",
        f"{INNER_ROOT}/requirements.txt",
        f"{INNER_ROOT}/ggufbench/__init__.py",
        f"{INNER_ROOT}/ggufbench/bundle.py",
        f"{INNER_ROOT}/web/index.html",
        f"{INNER_ROOT}/config/default_config.json",
        f"{INNER_ROOT}/tests/run_all.py",
        f"{INNER_ROOT}/tests/_fixture.py",
        f"{INNER_ROOT}/请先读我.txt",
    ]
    if include_bundle:
        must_have = common + [
            f"{INNER_ROOT}/llama.cpp/llama-server.exe",
            f"{INNER_ROOT}/models/Qwen3.5-0.8B-Q8_0.gguf",
        ]
        must_not_have: list[str] = []
        wrong_claim = "本包<b>已内置</b>"          # 静态文案里的写死承诺
    else:
        must_have = common
        must_not_have = [f"{INNER_ROOT}/llama.cpp/", f"{INNER_ROOT}/models/"]
        wrong_claim = "本包已经内置引擎与模型"      # 轻量版绝不能出现这句

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        readme = zf.read(f"{INNER_ROOT}/请先读我.txt").decode("utf-8")

    missing = [m for m in must_have if m not in names]
    if missing:
        raise SystemExit("发布包自检失败，缺少关键文件:\n  - " + "\n  - ".join(missing))

    extra = [n for n in must_not_have if any(x.startswith(n) for x in names)]
    if extra:
        raise SystemExit("发布包自检失败，轻量版里不该出现:\n  - " + "\n  - ".join(extra))

    if wrong_claim in readme:
        raise SystemExit(f"发布包自检失败：包内说明含有与包型不符的表述「{wrong_claim}」")

    kind = "含内置资源" if include_bundle else "轻量版（不含引擎与模型）"
    print(f"  自检通过: {len(must_have)} 个关键文件均在包内；包型={kind}；说明文件表述与包型一致")


def main() -> int:
    parser = argparse.ArgumentParser(description="打包开箱即用的发布 ZIP")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "dist"), help="输出目录")
    parser.add_argument("--no-bundle", action="store_true",
                        help="打轻量版：不含内置的 llama.cpp/ 与 models/（包名带 -lite，约 3 MB）")
    args = parser.parse_args()
    build(Path(args.out).expanduser().resolve(), include_bundle=not args.no_bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

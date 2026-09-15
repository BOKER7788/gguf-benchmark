"""打包「开箱即用」发布 ZIP（P0-1）。

只收录 git 跟踪的文件（天然排除 .venv / reports / config.json / 内部笔记），
并在包内最外层放一个 `双击这里开始.bat` 的副本，让零基础用户解压后：
    ① 双击 start.bat  →  ② 浏览器自动打开  →  ③ 按向导点两下
    
用法::

    .venv/bin/python scripts/make_release_zip.py            # 输出到 dist/
    .venv/bin/python scripts/make_release_zip.py --out /tmp
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ggufbench import __version__  # noqa: E402

# 打进包内的说明文件（zip 根目录）
README_FIRST = """GGUF Benchmark v{version}  —— by Boker
================================================

这是一个在 Windows 上运行的本地大模型性能测试工具。
报告是单文件 HTML，可以直接分享、离线打开。

【怎么用】只需要两步

  第 1 步：双击  start.bat
      · 如果电脑上没有 Python，脚本会问你一句，按 Y 会自动帮你装好。
      · 第一次运行需要装几个依赖（约 1-3 分钟），窗口里会显示进度。

  第 2 步：浏览器会自动打开，照着页面上的「三步上手」操作
      · 第 2 步可以点「一键获取 llama.cpp」自动下载推理引擎（约 200MB）。
      · 第 3 步还没有模型？页面上有下载指引（推荐先下一个小模型试通流程）。

  想停止服务：双击  stop.bat

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


def tracked_files() -> list[str]:
    """取 git 跟踪的文件列表（保证不打包临时产物）。"""
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def build(out_dir: Path) -> Path:
    files = tracked_files()
    if not files:
        raise SystemExit("没有从 git 取到任何文件；请确认这是 git 仓库且已有提交")

    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"gguf-benchmark-v{__version__}-win.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            src = PROJECT_ROOT / rel
            if not src.is_file():
                continue
            zf.write(src, f"gguf-benchmark/{rel}")
        zf.writestr("gguf-benchmark/请先读我.txt", README_FIRST.format(version=__version__))

    size_mb = zip_path.stat().st_size / 1048576
    print(f"已生成: {zip_path}")
    print(f"  收录文件: {len(files) + 1} 个")
    print(f"  体积: {size_mb:.2f} MB")
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="打包开箱即用的发布 ZIP")
    parser.add_argument("--out", default=str(PROJECT_ROOT / "dist"), help="输出目录")
    args = parser.parse_args()
    build(Path(args.out).expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

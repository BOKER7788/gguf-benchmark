"""G. 工程卫生。

- requirements.txt 依赖最小化（仅 fastapi/uvicorn/httpx）；
- 无循环导入、无未使用 import、无明显重复代码；
- 根目录 config.json 的性质判定。
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import re
from pathlib import Path

from _harness import PROJECT_ROOT, Suite

PKG = PROJECT_ROOT / "ggufbench"
BANNED = {"psutil", "jinja2", "numpy", "pandas", "requests", "aiohttp", "pydantic"}


def _iter_py():
    return sorted(PKG.rglob("*.py"))


def _module_name(path: Path) -> str:
    rel = path.relative_to(PROJECT_ROOT).with_suffix("")
    return ".".join(rel.parts)


def _imports(tree: ast.AST):
    """返回 [(module_or_none, [names], lineno)]。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.append((None, [a.name for a in node.names], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            out.append((node.module, [a.name for a in node.names], node.lineno))
    return out


def _unused_imports(path: Path, src: str):
    tree = ast.parse(src)
    lines = src.splitlines()
    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            pass
    # 汇总所有 import 引入的顶层名字
    unused = []
    for module, names, lineno in _imports(tree):
        if module == "__future__":  # 编译期未来导入，非运行期名字
            continue
        for n in names:
            top = n.split(".")[0]
            # 该名字在 import 行之外是否出现
            occurrences = 0
            for i, ln in enumerate(lines, start=1):
                if i == lineno:
                    continue
                if re.search(rf"\b{re.escape(top)}\b", ln):
                    occurrences += 1
            if occurrences == 0 and top not in used_names:
                unused.append((top, lineno))
    return unused


def _func_hashes():
    """跨文件函数体指纹（>4 行），用于重复代码检测。"""
    seen = {}
    for path in _iter_py():
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(node.body) >= 4:
                body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                h = hashlib.md5(body.encode()).hexdigest()
                seen.setdefault(h, []).append(f"{path.name}:{node.name}")
    return {h: v for h, v in seen.items() if len(v) > 1}


def run() -> Suite:
    s = Suite("G. 工程卫生")

    # ---- G1 requirements.txt ----
    req = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    pkgs = []
    for ln in req.splitlines():
        ln = ln.split("#")[0].strip()
        if not ln:
            continue
        name = re.split(r"[=<>!\[\s]", ln)[0].strip().lower()
        if name:
            pkgs.append(name)
    s.eq("G1", "requirements.txt 仅 3 个第三方依赖", len(pkgs), 3)
    s.eq("G1b", "依赖集合 == fastapi/uvicorn/httpx", set(pkgs), {"fastapi", "uvicorn", "httpx"})
    banned_hit = BANNED & set(pkgs)
    s.check("G1c", "无 psutil/Jinja2/numpy/pandas 等重型依赖", not banned_hit, f"命中={banned_hit}")

    # ---- G2 模块可导入 + 循环导入 ----
    import_errors = []
    for path in _iter_py():
        mod = _module_name(path)
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001
            import_errors.append((mod, repr(exc)))
    s.check("G2", "全部模块可正常导入", not import_errors, f"错误={import_errors}")

    # 静态循环检测
    graph: dict[str, set[str]] = {}
    for path in _iter_py():
        mod = _module_name(path)
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        deps = set()
        pkg_prefix = "ggufbench"
        for module, names, _ in _imports(tree):
            if module is None:
                for n in names:
                    # import ggufbench.x
                    if n.startswith(pkg_prefix + "."):
                        deps.add(n)
            else:
                if module.startswith(pkg_prefix):
                    deps.add(module)
                elif module == "" or module is None:
                    pass
        # 相对导入 from . import x / from .x import y —— ast 里 module 为 'x' 或 None(点为0)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    base = "ggufbench." + ("." * (node.level - 1))
                    if node.module:
                        deps.add("ggufbench." + node.module)
                    else:
                        for a in node.names:
                            deps.add("ggufbench." + a.name)
        graph[mod] = deps

    def _cycles(g):
        found = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in g}

        def dfs(n, stack):
            color[n] = GRAY
            stack.append(n)
            for m in g.get(n, ()):  # noqa: B905
                if m not in color:
                    continue
                if color[m] == GRAY:
                    found.append(stack[stack.index(m):] + [m])
                elif color[m] == WHITE:
                    dfs(m, stack)
            stack.pop()
            color[n] = BLACK

        for n in list(g):
            if color[n] == WHITE:
                dfs(n, [])
        return found

    cyc = _cycles(graph)
    s.check("G2b", "无循环导入（静态图检测）", not cyc, f"环={cyc}")

    # ---- G3 未使用 import ----
    all_unused = {}
    for path in _iter_py():
        u = _unused_imports(path, path.read_text(encoding="utf-8"))
        if u:
            all_unused[path.name] = u
    s.check("G3", "无未使用 import", not all_unused, f"未使用={all_unused}")

    # ---- G4 重复代码 ----
    dups = _func_hashes()
    s.check("G4", "无明显跨文件重复函数体", not dups, f"重复组={list(dups.values())}")

    # ---- G5 根目录 config.json 性质判定 ----
    cfg = PROJECT_ROOT / "config.json"
    if cfg.exists():
        data = __import__("json").loads(cfg.read_text(encoding="utf-8"))
        runtime_keys = {"scan_result", "runner_mode", "llama_version"}
        is_runtime = any(k in data for k in runtime_keys)
        s.check("G5", "根 config.json 为 ConfigStore 运行期产物（含 scan_result/runner_mode）",
                is_runtime,
                f"keys={list(data.keys())[:6]}")
        # 断言 ConfigStore 确实写该文件
        from ggufbench import CONFIG_FILE
        s.eq("G5b", "CONFIG_FILE 指向项目根 config.json", CONFIG_FILE, PROJECT_ROOT / "config.json")
    else:
        s.check("G5", "根 config.json 存在性（由 ConfigStore 首次 load 生成）", False, "文件不存在")

    # ---- G6 Windows 批处理脚本兼容性 ----
    # .bat 在 cmd.exe 下对行尾与代码页敏感：LF 行尾会让 if/for 多行块解析失败，
    # 无 chcp 65001 会让脚本里的中文变成乱码；start /B 会让后端随控制台一起被杀。
    for name in ("start.bat", "stop.bat"):
        path = PROJECT_ROOT / name
        if not path.exists():
            s.check(f"G6-{name}", f"{name} 存在", False, "文件缺失")
            continue
        raw = path.read_bytes()
        crlf = raw.count(b"\r\n")
        bare_lf = raw.count(b"\n") - crlf
        s.eq(f"G6a-{name}", f"{name} 使用 CRLF 行尾（无裸 LF）", bare_lf, 0)
        s.check(f"G6b-{name}", f"{name} 设置 chcp 65001（中文不乱码）",
                "chcp 65001" in raw.decode("utf-8", "replace"))

    start = (PROJECT_ROOT / "start.bat").read_text(encoding="utf-8")
    s.check("G6c", "start.bat 用 pythonw.exe 无窗口后台启动",
            "pythonw.exe" in start)
    # 只匹配 start 命令本身，注释里提到 /B 不算
    cmd_lines = [ln.strip() for ln in start.splitlines()
                 if ln.strip().lower().startswith("start ") and '"' in ln]
    s.check("G6d", "start.bat 的启动命令未使用 /B（否则关窗口会杀掉后端）",
            all(" /B " not in f" {ln} " for ln in cmd_lines),
            f"命令={cmd_lines}")
    s.check("G6e", "start.bat 含后端就绪探测（轮询 /api/health）",
            "api/health" in start)

    # ---- G7 Python 发现必须「实际执行 + 校验」，不能只看 where ----
    # 起因：Windows 自带 Microsoft Store 的 python.exe「应用执行别名」（0 字节占位程序），
    # WindowsApps 默认在 PATH 中，`where python` 会命中它并返回成功，
    # 但执行时只打印一行英文提示到 stderr、stdout 为空，导致版本探测取不到值。
    s.check("G7a", "start.bat 注释说明 where 命中不等于可用解释器",
            "where python` 命中并不代表存在可用的解释器" in start)
    s.check("G7b", "start.bat 显式识别并跳过 WindowsApps（商店别名）路径",
            "WindowsApps" in start and "findstr /i /c:\"WindowsApps\"" in start)
    s.check("G7c", "start.bat 探测时重定向 stderr（2^>nul），不让占位程序的英文提示漏到屏幕",
            '2^>nul' in start)
    s.check("G7d", "start.bat 用正则校验探测输出必须是版本号格式",
            'findstr /r /c:"^[0-9][0-9]*\\.[0-9][0-9]*$"' in start)
    s.check("G7e", "start.bat 有 :probe 子过程做「执行 + 校验」",
            ":probe" in start and "PROBE_VER" in start)

    # py 启动器优先级必须高于 python：py 在 C:\Windows\，不会被商店别名遮蔽
    i_py = start.find('call :try_cmd "py -3"')
    i_py2 = start.find('call :try_cmd "py"')
    i_python = start.find("for /f \"delims=\" %%p in ('where python 2^>nul')")
    s.check("G7f", "优先尝试 py 启动器，再尝试 PATH 中的 python",
            i_py != -1 and i_py2 != -1 and i_python != -1 and i_py < i_py2 < i_python,
            f"py-3@{i_py} py@{i_py2} python@{i_python}")

    s.check("G7g", "兜底扫描常见安装目录（%LOCALAPPDATA%\\Programs\\Python 等）",
            r"\Programs\Python\Python3*" in start and r"%ProgramFiles%\Python3*" in start)

    # 报错文案必须可操作：给出下载地址与关闭别名的路径
    s.check("G7h", "报错给出安装地址（python.org/downloads）",
            "python.org/downloads/windows" in start)
    s.check("G7i", "报错说明如何关闭「应用执行别名」",
            "应用执行别名" in start)
    s.check("G7j", "报错给出自检命令 py -3 --version",
            "py -3 --version" in start)

    return s

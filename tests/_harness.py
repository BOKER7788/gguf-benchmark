"""极简测试框架（零第三方依赖，纯标准库）。

设计目标：
- 与项目"仅 3 个第三方依赖"的约束一致，不引入 pytest；
- 每个测试模块暴露 ``run() -> Suite``，可独立执行也可由 ``run_all.py`` 聚合；
- 结果可序列化，供 QA_REPORT.md 生成。

约定：``Suite.check(name, cond, detail)`` / ``Suite.eq(name, got, exp)``。
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class Result:
    """单条断言结果。"""

    id: str
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Suite:
    """一组断言。"""

    name: str
    results: list[Result] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ---- 断言 ----
    def check(self, cid: str, name: str, cond: bool, detail: str = "") -> bool:
        """条件断言。"""
        ok = bool(cond)
        self.results.append(Result(cid, name, ok, "" if ok else (detail or "条件为假")))
        return ok

    def eq(self, cid: str, name: str, got, exp, detail: str = "") -> bool:
        """相等断言。"""
        ok = got == exp
        d = "" if ok else (detail or f"期望={exp!r} 实际={got!r}")
        self.results.append(Result(cid, name, ok, d))
        return ok

    def note(self, text: str) -> None:
        """附加说明（不计入 PASS/FAIL）。"""
        self.notes.append(text)

    # ---- 统计 ----
    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    def failures(self) -> list[Result]:
        return [r for r in self.results if not r.passed]


def run_guarded(name: str, fn) -> Suite:
    """安全执行一个测试模块的 ``run()``；异常记为一条 FAIL 而非中断整体。"""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        s = Suite(name)
        s.check("EXC", f"{name} 执行异常", False, traceback.format_exc())
        return s

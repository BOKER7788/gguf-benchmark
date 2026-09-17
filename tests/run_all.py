"""QA 测试统一入口。

用法::

    cd "GGUF- benchmark/tests"
    ../.venv/bin/python run_all.py            # 运行全部 A~G
    ../.venv/bin/python run_all.py A C F      # 仅运行指定模块

输出：逐条 PASS/FAIL + 汇总，并写 ``tests/_results.json``（供 QA_REPORT 生成）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _harness import Suite, run_guarded

HERE = Path(__file__).resolve().parent

MODULES = [
    ("A", "数据与矩阵", "test_A_matrix"),
    ("B", "模型识别", "test_B_scanner"),
    ("C", "失败跳过状态机", "test_C_state_machine"),
    ("D", "报告正确性", "test_D_report"),
    ("E", "前端逻辑", "test_E_frontend"),
    ("F", "API 契约与鲁棒性", "test_F_api"),
    ("G", "工程卫生", "test_G_hygiene"),
    ("H", "曲线悬停数值标签", "test_H_tooltip"),
    ("I", "零基础用户友好度", "test_I_friendly"),
    ("J", "体量可行性与 mock 免责声明", "test_J_feasibility"),
]


def main(argv: list[str]) -> int:
    selected = {a.upper() for a in argv if a.upper() in {m[0] for m in MODULES}} or {m[0] for m in MODULES}
    suites: list[Suite] = []
    for key, title, modname in MODULES:
        if key not in selected:
            continue
        import importlib

        mod = importlib.import_module(modname)
        suite = run_guarded(f"{key}. {title}", mod.run)
        suites.append(suite)
        print(f"\n===== {suite.name} =====")
        for r in suite.results:
            mark = "PASS" if r.passed else "FAIL"
            line = f"  [{mark}] {r.id} {r.name}"
            if not r.passed:
                line += f"\n         └─ {r.detail}"
            print(line)
        for n in suite.notes:
            print(f"  [NOTE] {n}")
        print(f"  ---- {suite.passed}/{suite.total} 通过")

    total = sum(s.total for s in suites)
    passed = sum(s.passed for s in suites)
    failed = total - passed

    print("\n" + "=" * 60)
    for s in suites:
        print(f"  {s.name:<28} {s.passed:>3}/{s.total:<3}  {'OK' if s.failed == 0 else 'FAIL'}")
    print("=" * 60)
    print(f"  合计: {passed}/{total} 通过，{failed} 失败")
    print(f"  QA VERDICT: {'失败项见上' if failed else '全部通过'}")

    results_path = HERE / "_results.json"
    results_path.write_text(
        json.dumps(
            [
                {
                    "name": s.name,
                    "total": s.total,
                    "passed": s.passed,
                    "failed": s.failed,
                    "results": [
                        {"id": r.id, "name": r.name, "passed": r.passed, "detail": r.detail}
                        for r in s.results
                    ],
                    "notes": s.notes,
                }
                for s in suites
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  结果已写入: {results_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""由 ``tests/_results.json`` 生成 ``docs/QA_REPORT.md``（可重复运行）。

用法::

    cd "GGUF- benchmark/tests"
    ../.venv/bin/python run_all.py        # 先跑出 _results.json
    ../.venv/bin/python make_report.py    # 再生成报告
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
RESULTS = HERE / "_results.json"
OUT = PROJECT_ROOT / "docs" / "QA_REPORT.md"

# 每个失败项的逐条详情（人工撰写，绑定到断言 id）
FINDINGS = [
    {
        "ids": ["B1"],
        "title": "分片 GGUF（-00001-of-00002）未合并，被误识别为多个独立模型",
        "severity": "P2（真实世界正确性风险；PRD/架构未显式要求分片合并）",
        "route": "Engineer",
        "file": "ggufbench/scanner.py:41-49（scan 主循环）/ 92-108（_build_meta）",
        "repro": "构造目录含 model-00001-of-00002.gguf + model-00002-of-00002.gguf → ModelScanner().scan(dir)",
        "expected": "识别为 1 个模型（分片合并）",
        "actual": "识别出 2 个模型: ['model-00001-of-00002', 'model-00002-of-00002']；全项目 grep 无任何 `-of-N`/分片分组逻辑",
        "impact": "多分片 GGUF 会被当作两个独立模型分别跑满 49 组，既浪费一半额度又产生错误结论；"
                  "llama.cpp 生态中 >常见单文件上限的模型普遍分片。",
    },
    {
        "ids": ["F-A5c"],
        "title": "A5 端口检测对越界/负数端口返回 500（应为结构化 400）",
        "severity": "P2",
        "route": "Engineer",
        "file": "ggufbench/api.py:130-133（port_check）/ ggufbench/runners/base.py:20-33（is_port_in_use）",
        "repro": 'POST /api/port-check {"port": 70000} 或 {"port": -1}',
        "expected": '400 {"ok":false,"error":{"code":"E_BAD_REQUEST",...中文...}}',
        "actual": '500 {"ok":false,"error":{"code":"E_INTERNAL","message":"服务器内部错误: bind(): port must be 0-65535."}}',
        "impact": "socket.bind 对越界端口抛 OverflowError（非 OSError），未被 is_port_in_use 捕获，"
                  "落到全局兜底 → 500 且泄漏底层英文错误。应校验 1..65535 并返回 E_BAD_REQUEST。",
    },
    {
        "ids": ["F-A3c"],
        "title": "配置档位缺少校验：负数/超大 ctx/input 档位被静默接受（200）",
        "severity": "P2",
        "route": "Engineer",
        "file": "ggufbench/models.py:117-120（ctx_levels/input_levels 无 validator）/ ggufbench/api.py:113-118（put_config）",
        "repro": 'PUT /api/config {"ctx_levels":[-1]} / {"input_levels":[-5]} / {"ctx_levels":[1000000000000]}',
        "expected": '400 E_BAD_REQUEST + 中文提示（档位须为正整数且在合理上限内）',
        "actual": "200 ok:true，配置被写入；负数档位会进入 build_matrix 生成 (-1,-5) 之类无意义组合",
        "impact": "非法档位静默进入矩阵与启动命令，导致无效测试与难排查的异常。建议在 BenchConfig 增加 "
                  "field_validator（正数、升序、上限如 ≤10**7）。",
    },
    {
        "ids": ["F12"],
        "title": "离线重建（--report-only）遇到损坏 points.json 抛出原始堆栈（未结构化）",
        "severity": "P2",
        "route": "Engineer",
        "file": "run.py:71-82（_run_report_only）/ ggufbench/report/builder.py:151（json.loads 无保护）",
        "repro": "printf '{ this is not json' > bad.json && python run.py --report-only bad.json",
        "expected": "捕获异常并打印中文错误（如 [E_BAD_REQUEST] points.json 解析失败: ...），退出码非崩溃路径",
        "actual": "json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 3 原始堆栈，退出码 1",
        "impact": "CLI 使用体验：损坏输入直接崩栈而非给出可读中文错误（PRD §鲁棒性要求明确错误）。",
    },
    {
        "ids": ["G3"],
        "title": "real_runner.py 存在未使用导入 is_port_in_use",
        "severity": "P3（代码卫生，不影响功能）",
        "route": "Engineer",
        "file": "ggufbench/runners/real_runner.py:15",
        "repro": "grep -n is_port_in_use ggufbench/runners/real_runner.py → 仅出现于 import 行",
        "expected": "移除未使用导入",
        "actual": "from .base import ... , is_port_in_use（从未在文件内使用）",
        "impact": "轻微：lint 噪声；建议清理。",
    },
]


def load():
    if not RESULTS.exists():
        raise SystemExit("请先运行 run_all.py 生成 _results.json")
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def main() -> int:
    suites = load()
    total = sum(s["total"] for s in suites)
    passed = sum(s["passed"] for s in suites)
    failed = total - passed
    fail_ids = [r["id"] for s in suites for r in s["results"] if not r["passed"]]

    lines: list[str] = []
    L = lines.append

    L("# QA 测试报告 — GGUF Benchmark（独立验证）")
    L("")
    L("> 验证人：严过关（QA 工程师）｜ 被验对象：寇豆码（工程师）交付的 30 个源文件")
    L("> 验证方式：**独立编写、实际运行**的自动化测试（非复述工程自测）")
    L("")
    L("## 1. 摘要")
    L("")
    L(f"- **用例总数：{total}**｜通过：{passed}｜失败：{failed}（通过率 {passed/total*100:.1f}%）")
    L(f"- **路由判定**：Engineer {len(FINDINGS)} 类缺陷（{len(fail_ids)} 条断言） / QA(自修) 2 / NoOne 1（死代码说明）")
    L("- **IS_PASS：NO** —— 存在 8 条失败断言，全部归属**源码缺陷**（非测试问题），核心链路虽全绿但鲁棒性/边界存在缺口。")
    L("")
    L("### 核心结论")
    L("- ✅ **核心业务链路（P0 黄金路径）全部通过**：双维度矩阵 49 组、失败跳过状态机、报告与黄金样本 14 字段对齐 + 零 CDN、"
      "前端 10 列排序/筛选、A1~A15 契约、mock 全链路 392 点级产出。")
    L("- ⚠️ **8 条失败集中在“异常/边界”**：非法端口、非法档位、损坏输入、分片模型、未使用导入。")
    L("- 主理人裁定的 **49 组/模型** 已用 `build_matrix()` 与 A7 双路径独立验证，与黄金样本 8×49=392 吻合。")
    L("")
    L("## 2. 环境与方法")
    L("")
    L("- Python 3.13.12（项目 venv `.venv/bin/python`）；Node v22（前端逻辑单测）；macOS（无 Windows/llama.cpp/AMD 核显）")
    L("- 真实推理路径无法运行：以 `runner_mode=mock` 验证全链路；real 路径仅做**代码级审查**")
    L("- 用例框架：零依赖自研 harness（`tests/_harness.py`），可重复运行")
    L("- 运行方式：`cd tests && ../.venv/bin/python run_all.py`（生成 `tests/_results.json`），`python make_report.py` 生成本报告")
    L("")
    L("## 3. 总体结果（按套件）")
    L("")
    L("| 套件 | 通过/总数 | 结果 |")
    L("|---|---|---|")
    for s in suites:
        L(f"| {s['name']} | {s['passed']}/{s['total']} | {'✅ OK' if s['failed']==0 else '❌ FAIL'} |")
    L(f"| **合计** | **{passed}/{total}** | {'✅' if failed==0 else '❌'} |")
    L("")
    L("## 4. 失败详情（文件:行 + 复现 + 实际 vs 期望）")
    L("")
    for i, f in enumerate(FINDINGS, 1):
        L(f"### F{i}. {f['title']}")
        L("")
        L(f"- **严重度**：{f['severity']}")
        L(f"- **路由**：{f['route']}")
        L(f"- **命中断言**：{', '.join(f['ids'])}")
        L(f"- **文件:行**：`{f['file']}`")
        L(f"- **复现步骤**：`{f['repro']}`")
        L(f"- **期望**：{f['expected']}")
        L(f"- **实际**：{f['actual']}")
        L(f"- **影响**：{f['impact']}")
        L("")
    L("## 5. 路由判定汇总")
    L("")
    L("| 归属 | 数量 | 明细 |")
    L("|---|---|---|")
    L(f"| **Engineer（源码 Bug）** | {len(fail_ids)} 条断言 / {len(FINDINGS)} 类 | "
      + "; ".join(f"{f['ids'][0]}" for f in FINDINGS) + " |")
    L("| **QA（测试自身错误，已自修）** | 2 | "
      "C2 重启语义（restart_once 每档一次而非每点，脚本用错）；B6b 空目录语义（误按错误码断言，"
      "PRD US-01③ 实为 UI 空态提示） |")
    L("| **NoOne（非问题）** | 1 | E_NO_GGUF 错误码为死代码：PRD US-01③ 要求的是空态提示而非错误，"
      "非功能缺陷（低优先级清理项） |")
    L("")
    L("## 6. 逐条结果表")
    L("")
    L("| # | 套件 | 断言 ID | 说明 | 结果 | 失败详情 |")
    L("|---|---|---|---|---|---|")
    n = 0
    for s in suites:
        for r in s["results"]:
            n += 1
            detail = "" if r["passed"] else r["detail"].replace("\n", " ")[:160]
            L(f"| {n} | {s['name'].split('.')[0]} | {r['id']} | {r['name']} | "
              f"{'PASS' if r['passed'] else 'FAIL'} | {detail} |")
    L("")
    L("## 7. 关键通过项（值得一提的强验证）")
    L("")
    L("- **A**：`build_matrix` 与 A7 `/api/tasks/preview` 双路径断言每模型 49 组、逐组合 `input<ctx`、"
      "边界 `input==ctx` 被排除。")
    L("- **C**：失败状态机 5 种场景（连续 2 失败跳过并停止模型 / 失败→成功→失败不误判 / 崩溃重启一次成功 /"
      " 重启仍失败计失败 / consec_fail 跨 ctx 累计）全部通过；反向用例证明**成功确实清零计数**。")
    L("- **D**：报告与黄金样本 `395-result.html` 逐字段对齐（前 14 字段同序），表头 10 列，"
      "**零外部资源引用**（唯二 `http://` 为 SVG `xmlns` 命名空间，非加载行为）；OOM 数据触发 BIOS/UMA 横幅。")
    L("- **E**：Node 实跑报告内嵌 JS，验证 10 列均可排序、失败点恒置尾、按模型筛选 + 摘要卡 + 曲线显隐同步。")
    L("- **F**：真实 uvicorn 起服务，A1~A15 全绿；**串行约束在线捕获 409**；"
      "abort 后无残留 llama-server 进程且端口释放；auto 无 llama-server 时**确实降级 mock**。")
    L("- **G**：`requirements.txt` 严格 3 依赖；无循环导入；无重复函数体。")
    L("")
    L("## 8. 遗留风险 / 无法验证项")
    L("")
    L("1. **真实推理路径未运行**（无 Windows/llama.cpp/AMD 核显）：RealRunner 的进程树终止（`taskkill /T`、"
      "`os.killpg`）、`/tokenize`/`/completion` timings 解析、Vulkan 后端行为仅做代码级审查，未经运行验证。")
    L("2. **mock 数据非真实性能**：报告的 tps 数值来自合成公式，仅供流程验证，不代表真机性能。")
    L("3. **Windows 专属**：`start.bat`、PowerShell CIM 硬件采集、`CREATE_NEW_PROCESS_GROUP` 未在 Windows 实测。")
    L("4. **报告客户端 JS 依赖浏览器**：本报告用 Node + DOM stub 做逻辑单测，未做真实浏览器渲染（视觉/交互）验证。")
    L("5. **性能指标未压测**：PRD 的“扫描 1k gguf < 3s / 392 点报告 < 5s”未做规模压测。")
    L("")
    L("---")
    L("")
    L("*本报告由 `tests/run_all.py` + `tests/make_report.py` 自动生成，可重复运行。*")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成: {OUT}  （{total} 条用例，{failed} 条失败）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

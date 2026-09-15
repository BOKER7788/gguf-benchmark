# QA 测试报告 — GGUF Benchmark（独立验证）

> 验证人：严过关（QA 工程师）｜ 被验对象：寇豆码（工程师）交付的 30 个源文件
> 验证方式：**独立编写、实际运行**的自动化测试（非复述工程自测）

## 1. 摘要

- **用例总数：190**｜通过：182｜失败：8（通过率 95.8%）
- **路由判定**：Engineer 5 类缺陷（8 条断言） / QA(自修) 2 / NoOne 1（死代码说明）
- **IS_PASS：NO** —— 存在 8 条失败断言，全部归属**源码缺陷**（非测试问题），核心链路虽全绿但鲁棒性/边界存在缺口。

### 核心结论
- ✅ **核心业务链路（P0 黄金路径）全部通过**：双维度矩阵 49 组、失败跳过状态机、报告与黄金样本 14 字段对齐 + 零 CDN、前端 10 列排序/筛选、A1~A15 契约、mock 全链路 392 点级产出。
- ⚠️ **8 条失败集中在“异常/边界”**：非法端口、非法档位、损坏输入、分片模型、未使用导入。
- 主理人裁定的 **49 组/模型** 已用 `build_matrix()` 与 A7 双路径独立验证，与黄金样本 8×49=392 吻合。

## 2. 环境与方法

- Python 3.13.12（项目 venv `.venv/bin/python`）；Node v22（前端逻辑单测）；macOS（无 Windows/llama.cpp/Strix Halo）
- 真实推理路径无法运行：以 `runner_mode=mock` 验证全链路；real 路径仅做**代码级审查**
- 用例框架：零依赖自研 harness（`tests/_harness.py`），可重复运行
- 运行方式：`cd tests && ../.venv/bin/python run_all.py`（生成 `tests/_results.json`），`python make_report.py` 生成本报告

## 3. 总体结果（按套件）

| 套件 | 通过/总数 | 结果 |
|---|---|---|
| A. 数据与矩阵 | 13/13 | ✅ OK |
| B. 模型识别 | 24/25 | ❌ FAIL |
| C. 失败跳过状态机 | 24/24 | ✅ OK |
| D. 报告正确性 | 35/35 | ✅ OK |
| E. 前端逻辑 | 32/32 | ✅ OK |
| F. API 契约与鲁棒性 | 46/52 | ❌ FAIL |
| G. 工程卫生 | 8/9 | ❌ FAIL |
| **合计** | **182/190** | ❌ |

## 4. 失败详情（文件:行 + 复现 + 实际 vs 期望）

### F1. 分片 GGUF（-00001-of-00002）未合并，被误识别为多个独立模型

- **严重度**：P2（真实世界正确性风险；PRD/架构未显式要求分片合并）
- **路由**：Engineer
- **命中断言**：B1
- **文件:行**：`ggufbench/scanner.py:41-49（scan 主循环）/ 92-108（_build_meta）`
- **复现步骤**：`构造目录含 model-00001-of-00002.gguf + model-00002-of-00002.gguf → ModelScanner().scan(dir)`
- **期望**：识别为 1 个模型（分片合并）
- **实际**：识别出 2 个模型: ['model-00001-of-00002', 'model-00002-of-00002']；全项目 grep 无任何 `-of-N`/分片分组逻辑
- **影响**：多分片 GGUF 会被当作两个独立模型分别跑满 49 组，既浪费一半额度又产生错误结论；llama.cpp 生态中 >常见单文件上限的模型普遍分片。

### F2. A5 端口检测对越界/负数端口返回 500（应为结构化 400）

- **严重度**：P2
- **路由**：Engineer
- **命中断言**：F-A5c
- **文件:行**：`ggufbench/api.py:130-133（port_check）/ ggufbench/runners/base.py:20-33（is_port_in_use）`
- **复现步骤**：`POST /api/port-check {"port": 70000} 或 {"port": -1}`
- **期望**：400 {"ok":false,"error":{"code":"E_BAD_REQUEST",...中文...}}
- **实际**：500 {"ok":false,"error":{"code":"E_INTERNAL","message":"服务器内部错误: bind(): port must be 0-65535."}}
- **影响**：socket.bind 对越界端口抛 OverflowError（非 OSError），未被 is_port_in_use 捕获，落到全局兜底 → 500 且泄漏底层英文错误。应校验 1..65535 并返回 E_BAD_REQUEST。

### F3. 配置档位缺少校验：负数/超大 ctx/input 档位被静默接受（200）

- **严重度**：P2
- **路由**：Engineer
- **命中断言**：F-A3c
- **文件:行**：`ggufbench/models.py:117-120（ctx_levels/input_levels 无 validator）/ ggufbench/api.py:113-118（put_config）`
- **复现步骤**：`PUT /api/config {"ctx_levels":[-1]} / {"input_levels":[-5]} / {"ctx_levels":[1000000000000]}`
- **期望**：400 E_BAD_REQUEST + 中文提示（档位须为正整数且在合理上限内）
- **实际**：200 ok:true，配置被写入；负数档位会进入 build_matrix 生成 (-1,-5) 之类无意义组合
- **影响**：非法档位静默进入矩阵与启动命令，导致无效测试与难排查的异常。建议在 BenchConfig 增加 field_validator（正数、升序、上限如 ≤10**7）。

### F4. 离线重建（--report-only）遇到损坏 points.json 抛出原始堆栈（未结构化）

- **严重度**：P2
- **路由**：Engineer
- **命中断言**：F12
- **文件:行**：`run.py:71-82（_run_report_only）/ ggufbench/report/builder.py:151（json.loads 无保护）`
- **复现步骤**：`printf '{ this is not json' > bad.json && python run.py --report-only bad.json`
- **期望**：捕获异常并打印中文错误（如 [E_BAD_REQUEST] points.json 解析失败: ...），退出码非崩溃路径
- **实际**：json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 3 原始堆栈，退出码 1
- **影响**：CLI 使用体验：损坏输入直接崩栈而非给出可读中文错误（PRD §鲁棒性要求明确错误）。

### F5. real_runner.py 存在未使用导入 is_port_in_use

- **严重度**：P3（代码卫生，不影响功能）
- **路由**：Engineer
- **命中断言**：G3
- **文件:行**：`ggufbench/runners/real_runner.py:15`
- **复现步骤**：`grep -n is_port_in_use ggufbench/runners/real_runner.py → 仅出现于 import 行`
- **期望**：移除未使用导入
- **实际**：from .base import ... , is_port_in_use（从未在文件内使用）
- **影响**：轻微：lint 噪声；建议清理。

## 5. 路由判定汇总

| 归属 | 数量 | 明细 |
|---|---|---|
| **Engineer（源码 Bug）** | 8 条断言 / 5 类 | B1; F-A5c; F-A3c; F12; G3 |
| **QA（测试自身错误，已自修）** | 2 | C2 重启语义（restart_once 每档一次而非每点，脚本用错）；B6b 空目录语义（误按错误码断言，PRD US-01③ 实为 UI 空态提示） |
| **NoOne（非问题）** | 1 | E_NO_GGUF 错误码为死代码：PRD US-01③ 要求的是空态提示而非错误，非功能缺陷（低优先级清理项） |

## 6. 逐条结果表

| # | 套件 | 断言 ID | 说明 | 结果 | 失败详情 |
|---|---|---|---|---|---|
| 1 | A | A1 | 每模型恰好 49 组 | PASS |  |
| 2 | A | A2 | 逐 ctx 分组 4/5/6/7/8/9/10 | PASS |  |
| 3 | A | A3 | 每个组合均满足 input < ctx | PASS |  |
| 4 | A | A3b | pairs 数 == per_ctx 求和 | PASS |  |
| 5 | A | A4 | 边界 input == ctx 被排除 | PASS |  |
| 6 | A | A4b | 边界 input > ctx 被排除 | PASS |  |
| 7 | A | A4c | 某 ctx 无有效输入时被整体剔除 | PASS |  |
| 8 | A | A5 | 去重并升序排列 | PASS |  |
| 9 | A | A6 | BenchConfig 默认档位 == 49 | PASS |  |
| 10 | A | A7 | A7 状态码 200 | PASS |  |
| 11 | A | A7b | A7 每模型点数 49 | PASS |  |
| 12 | A | A7c | A7 total_points == 49×模型数 | PASS |  |
| 13 | A | A7d | A7 matrix.total == 49 | PASS |  |
| 14 | B | B1 | 分片 gguf(-00001-of-00002) 合并为单模型 | FAIL | 识别出 2 个模型（应为 1）: ['model-00001-of-00002', 'model-00002-of-00002'] |
| 15 | B | B2 | mmproj / mm_projector 被过滤 | PASS |  |
| 16 | B | B2b | list_ignored 报告被忽略的 mmproj | PASS |  |
| 17 | B | B3 | 仅返回 .gguf 候选 | PASS |  |
| 18 | B | B4 | 精度推断 Qwen3.5-0.8B-Q8_0.gguf → w8a8 | PASS |  |
| 19 | B | B4 | 精度推断 Qwen3.5-2B-Q4_K_M.gguf → w4a8 | PASS |  |
| 20 | B | B4 | 精度推断 model-w8a8.gguf → w8a8 | PASS |  |
| 21 | B | B4 | 精度推断 model-w4a8.gguf → w4a8 | PASS |  |
| 22 | B | B4 | 精度推断 model-int8.gguf → w8a8 | PASS |  |
| 23 | B | B4 | 精度推断 model-int4.gguf → w4a8 | PASS |  |
| 24 | B | B4 | 精度推断 model-mxfp4.gguf → w4a8 | PASS |  |
| 25 | B | B4 | 精度推断 no-quant-tag.gguf → w8a8 | PASS |  |
| 26 | B | B4 | 精度推断 weird.gguf → w8a8 | PASS |  |
| 27 | B | B4b | Q4_K_M 优先判 w4a8 | PASS |  |
| 28 | B | B5 | 尺寸解析 Qwen3.5-0.8B-Q8_0.gguf → 0.8B | PASS |  |
| 29 | B | B5 | 尺寸解析 Qwen-2B-Q4.gguf → 2B | PASS |  |
| 30 | B | B5 | 尺寸解析 Llama-35b.gguf → 35B | PASS |  |
| 31 | B | B5 | 尺寸解析 no-size.gguf → Unknown | PASS |  |
| 32 | B | B6 | 空目录不崩溃（返回空列表） | PASS |  |
| 33 | B | B6b | 无 gguf 目录：不崩溃并返回空列表（PRD US-01③ 空态语义） | PASS |  |
| 34 | B | B6c | 前端含中文空态提示文案 | PASS |  |
| 35 | B | B7 | 不存在目录抛 E_DIR_NOT_FOUND（中文） | PASS |  |
| 36 | B | B8 | 递归扫描含子目录模型 | PASS |  |
| 37 | B | B8b | 非递归仅扫顶层 | PASS |  |
| 38 | B | B9 | 隐藏 .gguf 仍被识别（行为记录） | PASS |  |
| 39 | C | C1 | 总点数 == 11 | PASS |  |
| 40 | C | C1b | 连续 2 失败后剩余 9 个点全部 skipped | PASS |  |
| 41 | C | C1c | 所有 skipped 点 skipped==True 且 success==False | PASS |  |
| 42 | C | C1d | 停止测试该模型（未再创建 ctx=16000 运行器） | PASS |  |
| 43 | C | C1e | 模型状态标记为 skipped | PASS |  |
| 44 | C | C1f | 失败点数 == 2 | PASS |  |
| 45 | C | C2 | 失败→成功→失败 后无 skipped 点 | PASS |  |
| 46 | C | C2b | 模型正常跑完（status=done） | PASS |  |
| 47 | C | C2c | 全部 11 个点均被记录 | PASS |  |
| 48 | C | C2d | 成功清零：末尾 consec_fail == 0 | PASS |  |
| 49 | C | C2e | 两个 ctx 都被执行 | PASS |  |
| 50 | C | C2f | 失败点数 == 2（250 与 1000） | PASS |  |
| 51 | C | C2g | restart_once 每档仅触发一次（_restarted=True） | PASS |  |
| 52 | C | C3 | 重启后成功：点 success==True | PASS |  |
| 53 | C | C3b | 重启后成功：不额外计失败（consec_fail==0） | PASS |  |
| 54 | C | C4 | 重启仍失败：点 success==False | PASS |  |
| 55 | C | C4b | 重启仍失败：计入 consec_fail==1 | PASS |  |
| 56 | C | C4c | 失败原因属枚举值 | PASS |  |
| 57 | C | C5 | 启动崩溃一次后恢复：2 点全成功 | PASS |  |
| 58 | C | C6 | 启动崩溃两次：至少 1 个失败点 | PASS |  |
| 59 | C | C6b | 启动失败归因为 MODEL_FAIL | PASS |  |
| 60 | C | C6c | 计入 consec_fail==1 | PASS |  |
| 61 | C | C7 | 跨 ctx 累计：最后 2 点被 skipped | PASS |  |
| 62 | C | C7b | 跨 ctx 累计：模型标记 skipped | PASS |  |
| 63 | D | D0 | 存在 overview.html 与至少 1 个模型报告 | PASS |  |
| 64 | D | D1 | 零外部资源引用（link/script/img/@import/url） | PASS |  |
| 65 | D | D1b | 原始 http(s):// 仅为 SVG xmlns 命名空间 | PASS |  |
| 66 | D | D2 | DATA 前 14 字段 == 黄金样本字段（同序） | PASS |  |
| 67 | D | D2b | 黄金样本字段集 ⊆ 报告字段集 | PASS |  |
| 68 | D | D2c | 额外字段仅为 x-extension | PASS |  |
| 69 | D | D3 | 表头 10 列且列序正确 | PASS |  |
| 70 | D | D4 | 内联 <style> | PASS |  |
| 71 | D | D4b | 内联 <script> | PASS |  |
| 72 | D | D4c | 内联 2 个 <svg>（Prefill/Decode 曲线） | PASS |  |
| 73 | D | D5 | 存在可折叠参数说明块 <details class=intro> | PASS |  |
| 74 | D | D5b | Prefill 曲线 svg | PASS |  |
| 75 | D | D5c | Decode 曲线 svg | PASS |  |
| 76 | D | D5d | 硬件区块含「CPU 型号」 | PASS |  |
| 77 | D | D5d | 硬件区块含「主机型号」 | PASS |  |
| 78 | D | D5d | 硬件区块含「内存大小」 | PASS |  |
| 79 | D | D5d | 硬件区块含「系统版本」 | PASS |  |
| 80 | D | D6 | 所有点 vision_fps == 0 | PASS |  |
| 81 | D | D6b | 表格 vision 列渲染表达式为 toFixed(2) 或 '-' | PASS |  |
| 82 | D | D7 | fail_reason 仅出现枚举值 | PASS |  |
| 83 | D | D8 | 含 OOM_GPU → 出现 oom-banner | PASS |  |
| 84 | D | D8b | OOM 提示含「BIOS」与「UMA 显存」 | PASS |  |
| 85 | D | D8c | 无 OOM → 不出现 oom-banner | PASS |  |
| 86 | D | D9 | 模型报告含「启动参数（可复现）」 | PASS |  |
| 87 | D | D9b | 模型报告留档完整 llama-server 命令 | PASS |  |
| 88 | D | D9c | 页头含工具版本 | PASS |  |
| 89 | D | D9d | 页头含 llama.cpp 版本 | PASS |  |
| 90 | D | D10 | 冲突时生成 _2 后缀 | PASS |  |
| 91 | D | D10b | 旧文件不被覆盖 | PASS |  |
| 92 | D | D11 | 总览点数 == 模型数 × 49 | PASS |  |
| 93 | D | D11b | Qwen3.5-0.8B-Q8_0_w8a8.html 点数 == 49 | PASS |  |
| 94 | D | D11b | Qwen3.5-2B-Q4_K_M_w4a8.html 点数 == 49 | PASS |  |
| 95 | D | D12 | all_points.json 点数 == 98 | PASS |  |
| 96 | D | D12b | all_points.json 含 models/hardware/config/llama_version | PASS |  |
| 97 | D | D12c | 每个模型目录含 points.json | PASS |  |
| 98 | E | E1 | SORT_MAP 覆盖全部 10 列 | PASS |  |
| 99 | E | E2 | 渲染表头 10 列 | PASS |  |
| 100 | E | E2b | 表头列序正确 | PASS |  |
| 101 | E | E3 | 按 ctx 升序排序正确 | PASS |  |
| 102 | E | E3 | 按 input 升序排序正确 | PASS |  |
| 103 | E | E3 | 按 prefill 升序排序正确 | PASS |  |
| 104 | E | E3 | 按 decode 升序排序正确 | PASS |  |
| 105 | E | E3 | 按 ptime 升序排序正确 | PASS |  |
| 106 | E | E3 | 按 dtime 升序排序正确 | PASS |  |
| 107 | E | E3 | 按 vision 升序排序正确 | PASS |  |
| 108 | E | E3 | 按 chip 升序排序正确 | PASS |  |
| 109 | E | E3b | 按 precision 字典序排序 | PASS |  |
| 110 | E | E3c | 按 status 排序（false 在前） | PASS |  |
| 111 | E | E4 | 失败点恒排在末尾（即使排序值为最小值） | PASS |  |
| 112 | E | E5 | 失败点状态显示「显存不足(OOM)」 | PASS |  |
| 113 | E | E6 | 摘要卡：总数据点 = 2 | PASS |  |
| 114 | E | E6b | 摘要卡：成功率 = 50% | PASS |  |
| 115 | E | E6c | 摘要卡：最高 Prefill = 9,999 tps | PASS |  |
| 116 | E | E6d | 摘要卡：最高 Decode = 100 tps | PASS |  |
| 117 | E | E6e | 数据点计数同步 = 2 | PASS |  |
| 118 | E | E7 | 按模型筛选（M1 → 4 点） | PASS |  |
| 119 | E | E7b | 不筛选返回全部（12 点） | PASS |  |
| 120 | E | E7c | 按精度筛选（w4a8 → 0 点） | PASS |  |
| 121 | E | E8 | 全部筛选时 14 条曲线可见 | PASS |  |
| 122 | E | E8b | 单模型筛选时仅 7 条曲线可见 | PASS |  |
| 123 | E | E9 | app.js CTX_LEVELS 与后端一致 | PASS |  |
| 124 | E | E9b | app.js INPUT_LEVELS 与后端一致 | PASS |  |
| 125 | E | E9c | app.js 本地组合数计算 == 49 | PASS |  |
| 126 | E | E10 | app.js 使用 EventSource(SSE) | PASS |  |
| 127 | E | E10b | SSE 失败回退轮询 setInterval | PASS |  |
| 128 | E | E10c | app.js 调用 abort 中断接口 | PASS |  |
| 129 | E | E10d | app.js 含超时/进度应用逻辑 | PASS |  |
| 130 | F | F0 | 后端可启动并响应 /api/health | PASS |  |
| 131 | F | F-A1 | A1 /api/health 200 | PASS |  |
| 132 | F | F-A1b | A1 含 ok/python_version/llama_server_found/version | PASS |  |
| 133 | F | F-A2 | A2 /api/config 200 | PASS |  |
| 134 | F | F-A2b | A2 返回 BenchConfig 键 | PASS |  |
| 135 | F | F-A3 | A3 PUT /api/config 200 | PASS |  |
| 136 | F | F-A3b | A3 更新生效 | PASS |  |
| 137 | F | F-A4 | A4 不存在目录 → 400 | PASS |  |
| 138 | F | F-A4b | A4 错误体为 {ok:false,error:{code,message}} 且中文 | PASS |  |
| 139 | F | F-A4c | A4 有效目录 200 | PASS |  |
| 140 | F | F-A4d | A4 返回 models 且过滤 mmproj | PASS |  |
| 141 | F | F-A5 | A5 空闲端口 → in_use false | PASS |  |
| 142 | F | F-A5b | A5 占用端口 → in_use true | PASS |  |
| 143 | F | F-A5c | A5 非法端口 70000 → 结构化 400 | FAIL | 实际 status=500 body={"ok":false,"error":{"code":"E_INTERNAL","message":"服务器内部错误: bind(): port must be 0-65535."}} |
| 144 | F | F-A5c | A5 非法端口 -1 → 结构化 400 | FAIL | 实际 status=500 body={"ok":false,"error":{"code":"E_INTERNAL","message":"服务器内部错误: bind(): port must be 0-65535."}} |
| 145 | F | F-A6 | A6 tokenize 200 | PASS |  |
| 146 | F | F-A6b | A6 返回整数 token_count | PASS |  |
| 147 | F | F-A7 | A7 preview 200 | PASS |  |
| 148 | F | F-A7b | A7 每模型点数一致 | PASS |  |
| 149 | F | F-A8 | A8 创建任务 200 | PASS |  |
| 150 | F | F-A8b | A8 返回非空 task_id | PASS |  |
| 151 | F | F-A8c | A8 空模型 → 400 | PASS |  |
| 152 | F | F25 | 运行中重复创建任务被拒绝（409/400） | PASS |  |
| 153 | F | F-A9 | A9 状态查询 200 | PASS |  |
| 154 | F | F-A9b | A9 返回 TaskStatus 字段 | PASS |  |
| 155 | F | F-A9c | A9 任务最终 done | PASS |  |
| 156 | F | F-A9d | A9 完成时 percent=100 | PASS |  |
| 157 | F | F-A9e | A9 points_total == 8×点数 | PASS |  |
| 158 | F | F-A12 | A12 拉取数据点 200 | PASS |  |
| 159 | F | F-A12b | A12 返回非空 points 且字段齐全 | PASS |  |
| 160 | F | F-A12c | A12 按模型过滤生效 | PASS |  |
| 161 | F | F-A13 | A13 报告列表 200 | PASS |  |
| 162 | F | F-A13b | A13 退回 /reports 路径 | PASS |  |
| 163 | F | F-A14 | A14 重建总览 200 | PASS |  |
| 164 | F | F-A14b | A14 返回 overview.html 路径 | PASS |  |
| 165 | F | F-A10 | A10 SSE 200 | PASS |  |
| 166 | F | F-A10b | A10 首帧为 data: {...} | PASS |  |
| 167 | F | F-A11 | A11 中断 200 | PASS |  |
| 168 | F | F-A11b | A11 中断后任务停止 | PASS |  |
| 169 | F | F-A11c | 中断后无残留 llama-server 进程 | PASS |  |
| 170 | F | F-A11d | 中断后 llama 端口 8080 已释放 | PASS |  |
| 171 | F | F-A11e | 已结束任务再中断 → 409 | PASS |  |
| 172 | F | F-A9f | 不存在任务 → 404 | PASS |  |
| 173 | F | F-A3c | 非法档位 {'ctx_levels': [-1]} → 结构化 400 | FAIL | 实际 status=200 body={"ok":true,"config":{"scan_dir":"","recursive":true,"llama_server_path":"","port":8080,"gpu_backend":"vulkan","extra_args":[],"threads":8,"n_ |
| 174 | F | F-A3c | 非法档位 {'input_levels': [-5]} → 结构化 400 | FAIL | 实际 status=200 body={"ok":true,"config":{"scan_dir":"","recursive":true,"llama_server_path":"","port":8080,"gpu_backend":"vulkan","extra_args":[],"threads":8,"n_ |
| 175 | F | F-A3c | 非法档位 {'ctx_levels': [1000000000000]} → 结构化 400 | FAIL | 实际 status=200 body={"ok":true,"config":{"scan_dir":"","recursive":true,"llama_server_path":"","port":8080,"gpu_backend":"vulkan","extra_args":[],"threads":8,"n_ |
| 176 | F | F11 | auto 且 llama-server 不存在 → 降级 MockRunner | PASS |  |
| 177 | F | F11b | auto 且 llama-server 存在 → RealRunner | PASS |  |
| 178 | F | F11c | runner_mode=real 强制 RealRunner | PASS |  |
| 179 | F | F25b | TaskManager.is_busy() 检测到运行中任务 | PASS |  |
| 180 | F | F25c | 运行中再次 create → 抛 E_TASK_BUSY | PASS |  |
| 181 | F | F12 | 损坏 points.json → 结构化中文错误（非堆栈） | FAIL | returncode=1 traceback=True stderr=Traceback (most recent call last):   File "<PROJECT>/run.py", line 149, in <module>     raise S |
| 182 | G | G1 | requirements.txt 仅 3 个第三方依赖 | PASS |  |
| 183 | G | G1b | 依赖集合 == fastapi/uvicorn/httpx | PASS |  |
| 184 | G | G1c | 无 psutil/Jinja2/numpy/pandas 等重型依赖 | PASS |  |
| 185 | G | G2 | 全部模块可正常导入 | PASS |  |
| 186 | G | G2b | 无循环导入（静态图检测） | PASS |  |
| 187 | G | G3 | 无未使用 import | FAIL | 未使用={'real_runner.py': [('is_port_in_use', 15)]} |
| 188 | G | G4 | 无明显跨文件重复函数体 | PASS |  |
| 189 | G | G5 | 根 config.json 为 ConfigStore 运行期产物（含 scan_result/runner_mode） | PASS |  |
| 190 | G | G5b | CONFIG_FILE 指向项目根 config.json | PASS |  |

## 7. 关键通过项（值得一提的强验证）

- **A**：`build_matrix` 与 A7 `/api/tasks/preview` 双路径断言每模型 49 组、逐组合 `input<ctx`、边界 `input==ctx` 被排除。
- **C**：失败状态机 5 种场景（连续 2 失败跳过并停止模型 / 失败→成功→失败不误判 / 崩溃重启一次成功 / 重启仍失败计失败 / consec_fail 跨 ctx 累计）全部通过；反向用例证明**成功确实清零计数**。
- **D**：报告与黄金样本 `395-result.html` 逐字段对齐（前 14 字段同序），表头 10 列，**零外部资源引用**（唯二 `http://` 为 SVG `xmlns` 命名空间，非加载行为）；OOM 数据触发 BIOS/UMA 横幅。
- **E**：Node 实跑报告内嵌 JS，验证 10 列均可排序、失败点恒置尾、按模型筛选 + 摘要卡 + 曲线显隐同步。
- **F**：真实 uvicorn 起服务，A1~A15 全绿；**串行约束在线捕获 409**；abort 后无残留 llama-server 进程且端口释放；auto 无 llama-server 时**确实降级 mock**。
- **G**：`requirements.txt` 严格 3 依赖；无循环导入；无重复函数体。

## 8. 遗留风险 / 无法验证项

1. **真实推理路径未运行**（无 Windows/llama.cpp/Strix Halo）：RealRunner 的进程树终止（`taskkill /T`、`os.killpg`）、`/tokenize`/`/completion` timings 解析、Vulkan 后端行为仅做代码级审查，未经运行验证。
2. **mock 数据非真实性能**：报告的 tps 数值来自合成公式，仅供流程验证，不代表真机性能。
3. **Windows 专属**：`start.bat`、PowerShell CIM 硬件采集、`CREATE_NEW_PROCESS_GROUP` 未在 Windows 实测。
4. **报告客户端 JS 依赖浏览器**：本报告用 Node + DOM stub 做逻辑单测，未做真实浏览器渲染（视觉/交互）验证。
5. **性能指标未压测**：PRD 的“扫描 1k gguf < 3s / 392 点报告 < 5s”未做规模压测。

---

# Round 2 回归验证（主理人代跑）

> **说明**：原计划由 QA 工程师（严过关）执行的 Round 2 回归，在运行中被 **API 额度耗尽（HTTP 429）** 中断，未产出结论。
> 本节由主理人（齐活林）**亲自运行**验证，标注清楚来源，不代表 QA 的原始结论。

## R2.1 Round 1 的 8 条 FAIL —— 逐条复验（全部转 PASS）

| 原 FAIL | 位置 | 复验结果 |
|---|---|---|
| B1 分片 GGUF 未合并 | `scanner.py:41-49` | ✅ PASS —— 3 分片 → 1 个模型，名称去后缀，尺寸求和正确 |
| F-A5c ×2 非法端口返回 500 | `api.py:130-133`、`runners/base.py:20-33` | ✅ PASS —— `70000/-1/0/65536` 全部返回 **HTTP 400 + `E_BAD_REQUEST`**，`8080` 正常 200 |
| F-A3c ×3 非法档位被静默接受 | `models.py:117-120`、`api.py:113-118` | ✅ PASS —— `[-1]/[0]/[1e9]` 均返回 400；损坏 `config.json` 回退默认 |
| F12 损坏 points.json 抛原始堆栈 | `run.py:71-82` | ✅ PASS —— `rc=1`，中文提示 `E_BAD_REQUEST: points.json 解析失败（非法 JSON）`，**无 Traceback** |
| G3 未使用 import | `real_runner.py:15` | ✅ PASS —— 已删除 |

**复跑计数**：`tests/run_all.py` → **196/196 通过，0 失败**（QA 中断前已将断言从 190 扩至 196）。

## R2.2 主理人追加的对抗性边界复核

| 场景 | 结果 |
|---|---|
| 分片：仅末片存在（乱序） | ✅ 归并为 1 个模型 |
| 分片：3 片 + mmproj + 独立模型混放 | ✅ mmproj 忽略，3 片归并，独立模型保留（2 个模型） |
| 分片：`foo-00001-of-00002` 单独存在 | ✅ 归并为 1 个（base=`foo`） |
| 校验：合法边界 `ctx=1048576` / `input=1` / `port=1` / `port=65535` | ✅ **均被接受**（未被 validator 误杀） |
| 校验：档位去重升序 `[2000,500,500,1000]` | ✅ → `[500,1000,2000]` |
| 校验：`port=0/65536`、`ctx=[0]/[-1]/[1e9]` | ✅ 全部拒绝 |

## R2.3 主理人发现的**新缺陷并已修复**（Round 1 与 Round 2 均未覆盖）

**跨子目录同名分片被误合并** —— `scanner.py` 的分片归并键为 `base::total`，未包含父目录。
后果：`A/model-00001-of-00002.gguf` 与 `B/model-00001-of-00002.gguf` 会被并成 **1 个模型**，
导致其中一个模型**被静默漏测**（数据丢失级）。

- 修复：归并键改为 `{parent.resolve()}::{base}::{total}`（`ggufbench/scanner.py`）
- 复验：跨目录同名分片 → 正确识别为 **2 个模型**；同目录 3 分片 + mmproj + 独立模型 → 2 个模型
- 回归用例：新增 `B10 / B10b / B11 / B11b / B12` 共 5 条断言锁死该行为

**复跑计数（修复后）**：**201/201 通过，0 失败**。

## R2.4 已知限制（不阻塞交付）

1. **非零填充分片号**（`np-1-of-2.gguf`）不归并 —— llama.cpp 实际恒为 5 位零填充（`-00001-of-00002`），不影响真实使用，已用 B12 记录当前行为。
2. **`ctx_levels=[]` 空列表被接受** —— 仅 API 可达（UI 为固定勾选框），结果为 0 个测试点，属可接受的空选择语义。
3. **跨目录归并键依赖 `resolve()`** —— 若同一模型分片分放在不同目录（非 llama.cpp 正常布局），不会被合并。

## R2.5 最终结论

**IS_PASS: YES** —— 核心链路（49 组矩阵、失败跳过状态机、报告 14 字段对齐 + 零 CDN、A1~A15 契约、串行 409、abort 资源释放、auto 降级）全绿；Round 1 的 8 条缺陷全部修复并复验；另修复 1 条新发现的正确性缺陷。

**遗留风险与 Round 1 §8 一致，无新增**：真实推理路径 / Windows 专属路径 / 真实浏览器渲染 / 性能压测 仍未验证（受开发机环境限制）。

---

*本报告由 `tests/run_all.py` + `tests/make_report.py` 自动生成，可重复运行；Round 2 章节为主理人手工追加。*
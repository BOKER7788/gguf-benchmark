# GGUF Benchmark

**本地大模型批量性能测试工具** —— 一键扫描模型 → 双维度压测 → 生成可分享的离线可视化报告。

> **by Boker** · MIT License · 基于 [llama.cpp](https://github.com/ggml-org/llama.cpp)

> **先看效果**：打开 [`docs/demo/overview.html`](docs/demo/overview.html)（单文件、零依赖，浏览器直接打开）。
> **把鼠标放在曲线上滑动**，会出现十字准线与数值浮层；表头可点击排序。
> ⚠️ 演示报告由 `mock` 生成，数字是**合成数据**，不代表任何真机性能。

---

## 下载哪个包？

| 包 | 体积 | 适合谁 |
|---|---|---|
| `gguf-benchmark-v1.1.2-win.zip` | **约 805 MB** | **第一次用 / 只想尽快跑通**。已内置推理引擎与 0.8B 模型，解压即用，无需任何下载与配置。 |
| `gguf-benchmark-v1.1.2-win-lite.zip` | **约 0.25 MB** | 手上**已有** `llama-server.exe` 和 `.gguf` 模型（比如之前用过本工具）。只下源码，引擎与模型复用你自己那份，省 800 MB。 |

两个包的**功能完全相同**，区别只在带不带内置资源；轻量版解压后的界面会如实显示
「本包未内置推理引擎 / 模型」并告诉你怎么补上（可以自动下载，也可以直接指定已有的）。

> 下面这段说明按**完整版**（805 MB）写。若你下的是轻量版，把 ②③ 两步当成必做项即可。

---

## 怎么用（只需要两步）

> **完整版发布包已内置推理引擎与默认模型** —— 解压后目录里就有：
> - `llama.cpp/llama-server.exe`：推理引擎（Windows Vulkan 版）
> - `models/Qwen3.5-0.8B-Q8_0.gguf`：默认模型
>
> 所以**无需任何下载与配置**，双击 `start.bat` 后在页面上点「**先试跑 1 个档位**」
> 就能跑通完整流程。下面表格里的 ②③ 只在你**想换自己的引擎/模型**时才需要。

### 第 1 步：双击 `start.bat`

- 如果电脑上没有 Python，脚本会**问你一句**，按 `Y` 它会用 `winget` 自动装好并配置 PATH。
- 第一次运行会装几个依赖（约 1-3 分钟），窗口里**会显示进度**，不会黑屏卡住。
- 装好后脚本会在后台启动服务，并**自动打开浏览器**。

### 第 2 步：照着页面上的「三步上手」做

浏览器打开后，第一页就是**三步上手向导**，每一步都带完成状态：

| 步骤 | 页面会帮你做什么 |
|---|---|
| ① 运行环境 | 自动检测 Python 版本与依赖是否就绪 |
| ② 推理引擎 | 完整版**已内置**（自动填好 `llama.cpp/llama-server.exe`）；想换版本可点「获取 / 更新 llama.cpp」自动下载（约 200MB），或手动选择已有的文件 |
| ③ 模型文件 | 完整版**已内置**（启动时自动扫描 `models/` 并勾选）；想换模型可点「**选择文件夹…**」用系统窗口挑目录 |

> 也就是说，用完整版时你**只需要**：双击 `start.bat` → 浏览器自动打开 → 点「**先试跑 1 个档位**」。

然后：

1. **④ 配置** 页只有几个要看的项 —— GPU 后端、线程数等已按你的机器预填好，收在「高级设置」里，一般不用动；
2. 页面会显示**预计耗时**（完整测试可能要几十分钟到几小时）；
3. 建议先点「**先试跑 1 个档位（约 1 分钟）**」确认路径和模型都没问题；
4. 再点「开始完整测试」。跑完自动打开报告，也能点「打开报告所在文件夹」。

**想停止服务**：双击 `stop.bat`。

---

## 特性

- **零基础可用**：原生文件夹选择、一键获取 llama.cpp、按机器预填参数、耗时预估、先试跑再全量。
- **不会拿假数据骗你**：找不到 llama-server 时，界面与报告顶部都会出现**醒目警示**，明确告诉你这是模拟数据；
  主动选了 mock 模式时文案会直接说「你选择了 mock 模式」，而不是甩锅给「未检测到 llama-server」。
- **不会让不可能的结论溜过去**：报告新增「模型体量与内存」区块，逐模型列出权重体积与占内存比例；
  真实模式下**仅权重就超过内存的模型会被直接跳过**（标记为显存不足），而不是花几十分钟把机器拖死。
  配置页勾选模型后立刻提示装不下的模型。
- **双维度矩阵**：ctx 档 `4/8/16/32/64/128/256K` × input 档 `0.25/0.5/1/2/4/…/128K`，仅保留 `input < ctx`（默认 **49 组/模型**）。
- **失败跳过状态机**：同一模型连续 2 次失败 → 剩余档位标记「已跳过」；成功一次即清零。
- **失败归因 + 人话解释**：`OOM_GPU / MODEL_FAIL / TIMEOUT / OTHER`，每条都配「这是什么意思 / 你该怎么做」。
- **完全离线报告**：单文件自包含 HTML（内联 CSS/JS/SVG，**零 CDN**），含 Prefill/Decode 曲线、可折叠参数说明、10 列可排序汇总表、硬件信息与启动参数留档。
- **曲线悬停数值标签**：十字准线 + 跟随浮层；被筛选隐藏的曲线不参与提示。
- **零构建前端**：原生 HTML + 原生 JS，目标机**只需 Python，无需 Node**。
- **可复现**：报告记录每档 ctx 的完整 llama.cpp 启动参数（mock 模式下会标注「实际并未执行」）。

---

## 常见问题（Windows）

### 报错 `Python was not found; run without arguments to install from the Microsoft Store...`

**原因**：Windows 10/11 自带 Microsoft Store 的「**应用执行别名**」——
`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`（以及 `python3.exe`）。
它是 **0 字节占位程序**，被调用时只打印那行英文就退出；而 `WindowsApps`
**默认在 PATH 中**，所以 `where python` 会命中它。也就是说：**`where python` 成功 ≠ 有可用的解释器**。

新版 `start.bat` 已改为对每个候选**实际执行并校验输出是否为 `3.11` 这样的版本号**，
并主动跳过 `WindowsApps` 路径（避免误触发 Microsoft Store）。若仍报错，说明确实没有可用 Python：

| 方式 | 适用场景 | 操作 |
|---|---|---|
| **A. 让脚本自动装**（推荐） | 从未装过 Python | 重新运行 `start.bat`，在提示处按 `Y`，脚本会用 `winget` 装好 |
| **B. 关闭应用执行别名** | 已装但被别名抢占 | 设置 → 应用 → 高级应用设置 → **应用执行别名** → 关掉 `python.exe`、`python3.exe` |
| **C. 用 `py` 启动器** | 多版本共存 / PATH 混乱 | `py` 位于 `C:\Windows\`，**不会被别名遮蔽**；脚本已优先尝试它。自检：`py -3 --version` |

**验证**：

```bat
python --version      :: 能打印 Python 3.11.x+ 即可
py -3 --version       :: 上一条失败但这条正常 → 属于方式 B
```

### 大 ctx 档位直接 OOM

在工具里勾选 **64K 及以上**的上下文档位时，页面会就地提示：核显若没在 **BIOS 里划分足够显存**，
这些档位会因显存不足失败。报告会把这类失败归因为 `OOM_GPU` 并给出处理建议。

### 关掉黑窗口后服务停了

请用 `start.bat` 启动（内部用 `pythonw.exe` 且**不加 `/B`**，与当前控制台解耦）。
停止请用 `stop.bat`。

### 报告里的数字看起来是假的

如果界面或报告顶部出现了「**模拟数据（mock）**」的橙色警示，说明当时没有可用的
llama-server，本次没有真正调用推理。请按第 2 步配置好 `llama-server.exe` 后重跑。

mock 模式下**不会加载任何模型**，tps 与耗时是按模型名里的参数规模算出来的合成值，
所以再大的模型也会「测试成功」——包括本机内存根本装不下的。判断方法看下一节。

### 报告里的模型「测试成功」了，但它真的跑得动吗

报告的「**模型体量与内存**」区块会逐模型列出权重体积、占内存比例与结论：

| 结论 | 含义 |
|---|---|
| 可以加载 | 权重占用不到本机内存的 80% |
| 内存紧张 | 占 80%~90%，能加载但大上下文档位很可能 OOM |
| 物理上装不下 | 仅权重就超过内存上限 —— 这份数据不可能是本机真实推理的结果 |
| 无法判断 | 没采集到模型体积或本机内存 |

> 经验值：模型体积直接看 `.gguf` 文件大小（分片模型要把所有分片相加）。
> 权重必须全部驻留在内存或显存里，**再加上 KV cache**，所以可用内存至少要
> 比权重体积大一截。真实模式下，本工具会直接跳过装不下的模型并标记为「显存不足」。

---

## 开发 / 手动运行

适用于 Linux / macOS，或想手动控制的 Windows 用户。

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/python run.py                        # http://127.0.0.1:8765
.venv/bin/python run.py --no-browser           # 不自动开浏览器
```

**离线重建报告**（已有 `points.json` 时无需重跑推理）：

```bash
.venv/bin/python run.py --report-only reports/all_points.json --overview --out overview.html
```

**打包「开箱即用」发布 ZIP**（含内置的 `llama.cpp/` 与 `models/`）：

```bash
.venv/bin/python scripts/make_release_zip.py             # 完整版，约 805MB（含内置资源）
.venv/bin/python scripts/make_release_zip.py --no-bundle # 轻量版，约 0.25MB（仅源码）
```

> 脚本不再依赖 `git ls-files`（在没有 `.git` 的目录也能跑），改为**显式清单 + 递归排除**，
> 自动剔除 `.venv/` `reports/` `config.json` `__pycache__/` 等运行产物，并在打包后自检：
> 关键文件是否齐全 + 轻量版里确实不含 `llama.cpp/`、`models/` + 包内说明的表述与包型一致
> （避免轻量版的说明文件沿用「本包已经内置引擎与模型」而说谎）。

### 测试

```bash
.venv/bin/python tests/run_all.py               # Linux/macOS
.venv\Scripts\python tests\run_all.py           # Windows
```

10 个模块 / **337 条断言**，零第三方依赖（不依赖 pytest）。
测试**自带确定性夹具**（`tests/_fixture.py` 用 mock 引擎现场生成 2 模型 × 49 点的报告产物到临时目录），
因此不依赖开发机上的历史 `reports/` 残留，干净解压即可全绿。

| 模块 | 覆盖 |
|---|---|
| A 数据与矩阵 | 49 组矩阵、`input < ctx` 裁剪、边界排除 |
| B 模型识别 | 分片 GGUF 归并、mmproj 过滤、精度推断、跨目录隔离 |
| C 失败跳过状态机 | 连续失败、成功清零（反向用例）、崩溃重启一次 |
| D 报告正确性 | 14 字段对齐、10 列表头、零 CDN、OOM 横幅 |
| E 前端逻辑 | 10 列排序、筛选、摘要卡、曲线显隐 |
| F API 契约与鲁棒性 | A1~A15、串行 409、abort 资源释放、非法输入 400 |
| G 工程卫生 | 依赖最小化、无循环导入、Windows 批处理兼容性 |
| H 曲线悬停交互 | Node 真实派发 mousemove/mouseleave，断言寻点、行数上限、边界翻转 |
| I 零基础友好度 | 人话错误、试跑矩阵、mock 预判、品牌词清除、前端交互接入 |
| J 体量可行性与 mock 免责声明 | 装不下的模型被拦截、报告体量区块、mock 页脚/警示文案、硬件采集与 runner_mode 解耦 |

### 目录结构

```
start.bat / stop.bat    Windows 一键启动 / 停止
run.py                  程序入口（含 --report-only）
requirements.txt        3 个依赖（fastapi / uvicorn / httpx）
llama.cpp/              随包内置的推理引擎（Windows Vulkan 版，开箱即用）
models/                 随包内置的默认模型（Qwen3.5-0.8B Q8_0，开箱即用）
ggufbench/              后端包
  ├ bundle.py           内置资源自动定位（llama.cpp/ 与 models/，零配置启动）
  ├ feasibility.py      模型体量 vs 本机内存的可行性判断（装不下就拦下来）
  ├ friendly.py         原生对话框、一键获取 llama.cpp、硬件推荐
  ├ engine.py           矩阵裁剪、串行编排、每档重启、失败状态机、ETA
  ├ api.py              A1~A15 + 小白友好接口
  └ report/             曲线、模板、报告组装
web/                    零构建前端（index.html + app.js + api.js + styles.css）
scripts/                发布打包
docs/                   PRD / 架构 / QA 报告 / 上手体验审计 / 演示报告
tests/                  回归套件（run_all.py）
  └ _fixture.py         确定性测试夹具（不依赖历史 reports/ 残留）
```

### 跨平台说明

| 能力 | macOS / Linux | Windows 11 |
|---|---|---|
| 后端 / 报告 / 前端 | ✅ | ✅ |
| 随包内置引擎与模型 | 自行放置 `llama.cpp/` 与 `models/` | ✅ 发布包已内置，零配置 |
| 原生文件夹选择 | `osascript` / `zenity` / tkinter | PowerShell `FolderBrowserDialog` |
| 硬件信息采集 | `platform` / `sysctl` | PowerShell CIM（CPU/主机/内存/系统/GPU） |
| llama-server 进程管理 | `setsid` + `killpg` | `CREATE_NEW_PROCESS_GROUP` + `taskkill /F /T` |
| 一键获取 llama.cpp | 需手动下载（官方只提供 Windows 构建） | ✅ 自动下载解压 |

---

## 许可

[MIT License](LICENSE) © 2026 Boker

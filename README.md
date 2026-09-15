# GGUF Benchmark — Minisforum Strix Halo 本地大模型批量测试工具

一键「扫描 → 勾选 → 配置 → 双维度压测 → 生成离线可视化报告」。专为
Minisforum Strix Halo（Ryzen AI MAX+ 395 / Radeon 8060S）调优与对外评测设计。

> **先看效果**：打开 [`docs/demo/overview.html`](docs/demo/overview.html)（单文件、零依赖，
> 可直接在浏览器打开）。把鼠标放在曲线上滑动，会出现十字准线与数值浮层。
> ⚠️ 该报告由 `runner_mode=mock` 生成，tps 均为**合成数据**，非真机性能。

## 特性

- **零构建前端**：原生 HTML + 原生 JS，由 FastAPI 静态挂载，目标机只需 Python，无需 Node。
- **双维度矩阵**：ctx 档 `[4000,8000,16000,32000,64000,128000,256000]` × input 档
  `[250,500,1000,2000,4000,8000,16000,32000,64000,128000]`，**仅保留 `input < ctx`**（默认 **49 组/模型**）。
- **失败跳过状态机**：同一模型连续 2 次失败 → 剩余档位标记「已跳过」；成功一次即清零。
- **失败归因**：`OOM_GPU / MODEL_FAIL / TIMEOUT / OTHER`，OOM 触发报告顶部中文提示。
- **完全离线报告**：单文件自包含 HTML（内联 CSS/JS/SVG，零 CDN），含曲线图、可折叠参数说明、
  汇总表（精度/芯片数可排序）、硬件信息与启动参数留档。
- **曲线悬停数值标签**：鼠标在曲线图上滑动即出现十字准线与浮层，显示该档位的 Ctx / Input
  与各条曲线的实测 tps；贴近右/下边缘自动翻转，被筛选隐藏的曲线不参与提示。
- **mock 注入**：`runner_mode = auto|real|mock`。开发机（macOS，无 llama.cpp）零配置即可全链路跑通。

## 安装

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
```

## 运行

- Windows 11：双击 `start.bat`（后台拉起后端并打开浏览器），停止用 `stop.bat`。
- 跨平台（开发自测）：

```
python run.py                 # 默认 http://127.0.0.1:8765
python run.py --no-browser    # 不自动开浏览器
```

离线重建报告：

```
python run.py --report-only reports/<model>/points.json --out out.html
python run.py --report-only reports/all_points.json --out overview.html --overview
```

## 目录结构

```
start.bat             Windows 一键启动（后台服务 + 就绪探测 + 开浏览器）
stop.bat              Windows 一键停止（按端口 8765 结束后端进程树）
run.py                程序入口（含 --report-only）
requirements.txt      3 个依赖
config/               默认配置
ggufbench/            后端包（api/engine/runners/report/...）
web/                  零构建前端（index.html + app.js + api.js + styles.css）
reports/              运行产物（报告 / 日志 / points.json）
tests/                回归套件（run_all.py，零第三方依赖）
```

## 测试

```
.venv/bin/python tests/run_all.py          # Linux/macOS
.venv\Scripts\python tests\run_all.py      # Windows
```

A~H 共 8 个模块，覆盖数据矩阵、模型识别、失败状态机、报告正确性、前端逻辑、
API 契约与鲁棒性、工程卫生、曲线悬停交互。

## 跨平台说明（macOS 开发 → Windows 部署）

| 能力 | macOS（开发机） | Windows 11（目标机） |
|---|---|---|
| 后端服务 / 报告生成 / 前端 UI | ✅ 完全可用 | ✅ 完全可用 |
| 硬件信息采集 | 通用采集（`sysctl`/`platform`） | PowerShell CIM（CPU/主机/内存/系统/GPU） |
| llama-server 进程管理 | `start_new_session` + `os.killpg` | `CREATE_NEW_PROCESS_GROUP` + `taskkill /F /T` |
| 真实推理吞吐 | ❌ 无 llama.cpp，走 mock | ✅ 需自备 `llama-server.exe` |

批处理脚本已按 Windows 要求处理：**CRLF 行尾** + **`chcp 65001`（保证中文不乱码）** +
**`pythonw.exe` + 非 `/B` 启动（关窗口不中断后台服务）**。

## 常见问题（Windows）

### 报错 `Python was not found; run without arguments to install from the Microsoft Store...`

然后在 `start.bat` 里看到 `[ERROR] 未能找到可用的 Python 解释器`。

**原因**：Windows 10/11 自带 Microsoft Store 的「**应用执行别名**」——
`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`（以及 `python3.exe`）。
它是 **0 字节占位程序**，被调用时只打印上面那行英文提示就退出；而 `WindowsApps`
**默认在 PATH 中**，因此 `where python` 会命中它。也就是说：**`where python` 成功 ≠ 有可用的解释器**。

`start.bat` 已改为对每个候选**实际执行并校验输出是否为 `3.11` 这样的版本号**，
并主动跳过 `WindowsApps` 路径（避免误触发 Microsoft Store）。若即使用了新版脚本仍报错，
说明机器上确实没有可用的 Python，或仅剩商店别名，请按下表处理。

**三种修复方式**

| 方式 | 适用场景 | 操作 |
|---|---|---|
| **A. 安装 Python 3.11+**（推荐） | 从未装过 Python | 到 <https://www.python.org/downloads/windows/> 下载 **Windows installer (64-bit)**，安装第一屏**务必勾选 `Add python.exe to PATH`** |
| **B. 关闭应用执行别名** | Python 已装，但被商店别名抢占了 `python` 这个名字 | 设置 → 应用 → 高级应用设置 → **应用执行别名** → 把 `python.exe`、`python3.exe` 两个开关都**关掉** |
| **C. 用 `py` 启动器** | 多版本共存 / PATH 混乱 | `py` 位于 `C:\Windows\`，**不会被商店别名遮蔽**。脚本已优先尝试 `py -3`；手动验证：`py -3 --version` |

**验证修复是否生效**

```bat
where python
python --version
py -3 --version
```

- `python --version` 能打印 `Python 3.11.x`（或更高）→ 已修好
- 若 `python --version` 仍输出那行英文、但 `py -3 --version` 正常 → 属于方式 B，去关掉别名
- 然后双击 `start.bat`，正常应看到 `[INFO] Python 解释器:` 与 `[INFO] Python 版本 :` 两行

### 其他

- **大 ctx 档位直接 OOM**：先在 BIOS 划分 UMA 显存（报告会把这类失败归因为 `OOM_GPU` 并提示）。
- **关掉黑窗口后服务停了**：请用 `start.bat` 启动（内部用 `pythonw.exe` 且不加 `/B`，与当前控制台解耦）；
  停止请用 `stop.bat`。

## 目标机冒烟（Strix Halo / Windows 11）

1. 安装 Python 3.11+，双击 `start.bat`。
2. ② 扫描目录选择 GGUF 所在目录；③ 勾选模型；④ 配置 `llama-server.exe` 路径与端口。
3. 点「开始测试」→ 观察进度 → 完成后自动打开 `reports/overview.html`。
4. 在报告曲线上滑动鼠标查看各档位数值标签。

> 注意：真实吞吐/OOM 判定需在目标机验证；开发机 mock 仅用于流程与报告结构验证。
> 大 ctx 档位需先在 BIOS 划分 UMA 显存，否则会 OOM（报告会归因为 `OOM_GPU` 并给出提示）。

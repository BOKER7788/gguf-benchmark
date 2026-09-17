# 更新日志

## v1.1.2（两种发布包：完整版 / 轻量版）

同一个版本号提供两个包，**功能完全相同**，只差在带不带内置资源：

| 包 | 大小 | 说明 |
|---|---|---|
| `gguf-benchmark-v1.1.2-win.zip` | 约 805 MB | 完整版：内置 `llama.cpp/` 与 `models/`，解压即用 |
| `gguf-benchmark-v1.1.2-win-lite.zip` | 约 0.25 MB | 轻量版：仅源码，自备引擎与模型（复用已有文件，省 800 MB 下载） |

- **轻量版**：`scripts/make_release_zip.py --no-bundle` 产出。包内说明改用独立模板
  （不再沿用完整版那句「本包已经内置引擎与模型」），打包自检会同时断言
  「轻量版里不含 `llama.cpp/`、`models/`」与「说明文件的表述和包型一致」。
- **界面文案改为按实情渲染**：`/api/health` 新增 `bundled_engine` / `bundled_models`，
  上手向导的②③两步据此显示「本包**已**内置」还是「本包**未**内置、需要怎么补上」，
  不再把「已内置」写死在 HTML 里 —— 否则轻量版会误导用户去找一个不存在的文件。

---

## v1.1.2

**本版重点：堵住「不可能的结果被当成真机性能」这条路。**

起因是一次真实误判：在 64 GB 内存的机器上，224 GB（7 个分片）的 397B 模型
「测试成功」并给出了完整的 28 组数据；同时多个模型「启动极快」。
排查结论是那次运行处于 `mock` 模式 —— 模型从未加载、llama-server 从未启动，
tps 是按**模型文件名里的参数规模**算出来的公式值。但报告里没有任何一处
能让读者发现这一点，反而有两处自相矛盾的表述在互相抵消。本版把这些漏洞补上。

### 新增

- **模型体量与内存的可行性判断**（`ggufbench/feasibility.py`）：把「权重体积 vs
  本机可用内存」算成显式结论 —— `可以加载` / `内存紧张`（>80%）/ `物理上装不下`
  （>90%）。UMA 核显按「显存与系统共享同一块物理内存」处理，不会把显存重复相加；
  独显（显存 > 物理内存）按两者之和估算；内存未知时判为「无法判断」而不是臆测。
- **报告新增「模型体量与内存」区块**：逐模型列出权重体积、占内存比例与结论。
  此前报告里**完全没有模型体积字段**，读者没有任何依据判断某个结果是否可能为真。
- **真实模式下的跑前拦截**：权重超过内存上限的模型**不会**再被尝试加载
  （读 200+ GB 只会把机器拖死几千秒），而是直接标记为「显存不足（OOM）」并写明
  体积超限的算式与替代方案。
- **界面提前告警**：`/api/tasks/preview` 返回逐模型可行性结论，配置页在勾选模型后
  立即提示装不下的模型；real 模式启动前会二次确认。选择 mock 模式时会明确确认
  「这份结果不能用于选型」。
- **通用硬件采集补齐 Windows 内存**：走 `GlobalMemoryStatusEx`（ctypes）。
  此前 Windows 上通用采集器的 `_ram_gb()` 直接返回 0.0，报告显示「内存大小：未知」。

### 修复

- **mock 报告页脚不再声称「数据由本机 llama.cpp 后端实测」**
  （`report/template.py`）。该表述与同一份文档里的 mock 警示条直接矛盾，
  读者只能在「警示是误报」和「页脚是套话」之间二选一 —— 两者都不该发生。
- **mock 警示条按触发原因分文案**：主动选了 mock 时说「你选择了 mock 模式」，
  只有 `auto` 因找不到 llama-server 而降级时才说「未检测到可用的 llama-server」。
  旧版一律甩锅给「未检测到 llama-server」，在路径明明有效时这句话是错的，
  于是整条警示被当成误报忽略。
- **mock 警示条写清数据来源**：明说「按模型名里的参数规模算出来的合成值」、
  「没有加载任何模型」、「再大的模型也会显示成功」。
- **mock 模式下标注启动参数「实际并未执行」**：报告里「启动参数（可复现）」原本会
  列出**从未运行过**的命令行，读者会合理地认为这些命令跑过。
- **硬件采集不再受 `runner_mode` 影响**：旧版在 mock 下强制改用通用采集器，
  Windows 上直接导致「内存大小：未知 / GPU：Unknown GPU（非 Windows 目标机）」——
  恰好抹掉了判断体量可行性最需要的输入。mock 只是不调用推理，这台机器本身没变。
- **`ModelStatus` 补上 `failed`**：引擎会给模型写这个状态，而枚举里没有它；
  pydantic 默认不校验赋值，于是模型对象会带着非法值继续流转，再经
  `/api/tasks/preview` 回传时被服务端拒绝（HTTP 422）。

### 测试

- 回归套件新增 **J 模块（体量可行性与 mock 免责声明，45 条断言）**，
  把上述每一条都固化成正向/反向断言，含「real 模式下体积超限的模型不得创建运行器」
  这类行为级验证。
- 合计 **10 个模块 / 337 条断言**，干净解压全绿。

---

## v1.1.1

**本版重点：修掉阻塞运行的缺陷 + 让发布包真正「开箱即用」。**

### 新增

- **发布包内置推理引擎与默认模型**：包内直接携带 `llama.cpp/llama-server.exe`（Windows Vulkan 版）
  与 `models/Qwen3.5-0.8B-Q8_0.gguf`。解压后**无需下载、无需配置**，双击 `start.bat` 即可用
  默认引擎和模型跑通完整流程（扫描 → 矩阵 → 真实推理 → 报告）。
- `ggufbench/bundle.py`：内置资源自动定位。`llama_server_path` / `scan_dir` 为空
  （或指向已不存在的旧路径）时自动回填，同时兼容用户原有的 `llama-b*/`、`*GGUF/` 布局。
- `scripts/make_release_zip.py` 支持 `--no-bundle`（只打源码包）。

### 修复

- **真实基准的 prefill 吞吐被 KV 缓存污染（严重）**
  `warmup_runs > 0` 时，预热请求已把整段 prompt 写入 llama-server 的 KV 缓存，紧接着的正式测量
  请求按最长公共前缀命中缓存，`timings.prompt_n` 只剩几个新增 token，而 prefill 正是用它计算 ——
  导致吞吐被低估约 **50 倍**，且 `input_tokens` 被写成个位数，报告仍显示成功、无任何告警。
  修复：`RealRunner.complete()` 的 payload 显式带上 `cache_prompt: false`。
  加固：`MetricsParser.build_point()` 检测到「实测 prompt token 数远小于目标档位且缓存命中」时
  记 warning，不再静默放行脏数据。
- **`start.bat` 无法启动后端（严重）**
  脚本用 `pythonw.exe run.py` 启动（GUI 子系统、无控制台），此时 `sys.stdout`/`sys.stderr` 为
  `None`，`uvicorn` 初始化日志格式器时执行 `sys.stdout.isatty()` 抛 `AttributeError` →
  `ValueError: Unable to configure formatter 'default'`，进程 exit 1，后端从未监听。
  修复：`run.py` 在 `uvicorn.run()` 之前把为 `None` 的标准流补成 `os.devnull`；同时把顶层异常
  写入 `reports/startup-error.log`，便于无窗口场景排障。
- **报告在 Windows 被写成 CRLF，导致 E/H 测试模块崩**
  `ReportBuilder.write()` 以文本模式写 `\n`，Windows 下被翻译成 `\r\n`，而 Node harness 的正则
  要求 `;\n` → 匹配失败。修复：三处 `write_text(..., newline="\n")`，两个 harness 正则改为
  `/;\r?\n/`。
- **回归套件在干净解压后必然失败**
  D/E/H/I 硬依赖开发机上的 `reports/` 残留产物（而 `reports/` 被 `.gitignore` 排除、发布包内不存在），
  D 还硬编码「2 模型 × 49 点」，F 用从未读取的 `subprocess.PIPE` 把后端写死、并用 POSIX 专属
  `pgrep` / `/bin/echo`。修复：新增 `tests/_fixture.py` 用 mock 引擎现场生成确定性夹具；F 的子进程
  输出重定向到文件、进程查询按平台分支；`_harness.run_guarded` 异常时保留已通过的断言。
  结果：干净解压 **292/292 全绿**（修前 141/146）。
- **回环请求可能被送去代理**：`RealRunner` 的 httpx 客户端未关 `trust_env`，本机设有
  `HTTP_PROXY` 时连 `127.0.0.1` 也走代理。修复：显式 `trust_env=False`。
- `stop.bat` 缺 `enabledelayedexpansion`，导致「未发现进程」提示分支恒不执行（死代码）。
- `start.bat` 的就绪等待用 `timeout /t 1`，在 stdin 非控制台（被脚本/自动化调用）时立即失败并让
  15 次探测空转。修复：改用 `ping -n 2`。

### 文档

- README 与 `请先读我.txt` 改为反映「内置引擎与模型、零配置上手」。
- 修正文档间互相矛盾的测试数字（统一为 9 模块 / 292 条断言，已在干净解压环境复现全绿）。

---

## v1.1.0

首个公开发布版：双维度矩阵压测、失败跳过状态机、单文件离线报告、零构建前端。
（此前未做过端到端验证，上述 v1.1.1 修复即来自实测结论。）

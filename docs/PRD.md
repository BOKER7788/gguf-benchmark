# PRD — 本地大模型批量性能测试工具（GGUF Benchmark）

> 版本：v1.0 ｜ 作者：许清楚（产品经理）｜ 状态：定稿（8 项设计决策 + 10 项默认值已由用户确认）
> 语言：中文 ｜ 技术栈：Python 后端 + 浏览器 UI ｜ 报告：完全离线单文件 HTML（零 CDN）
> 参考黄金样本：`395-result.html`（8 模型 / 392 数据点，深色主题、内联 SVG 曲线）

---

## 1. 产品目标与一句话定位

**一句话定位**：一个跑在 Windows 11 上的「一键扫描 → 勾选模型 → 双维度压测 → 自动生成离线可视化报告」的 llama.cpp 本地推理基准测试工具，专为本地大模型场景 机器调优与对外评测而设计。

**产品目标（3 个正交目标）**

| # | 目标 | 可衡量标准 |
|---|---|---|
| G1 | **零门槛跑通**：用户自备 `llama-server.exe`，只需选目录、勾模型、点开始，不触碰命令行 | 首次使用者 ≤ 3 步完成一次测试启动（选目录 → 勾选 → 开始） |
| G2 | **数据可信**：双维度（ctx × input）实测吞吐，用真实 token 数校验而非估算，冷启动抖动可控 | 每点预热 1 次 + 正式 3 次取中位数；token 数经 llama.cpp `/tokenize` 校验，误差 = 0 |
| G3 | **报告即交付物**：产出可直接对外分享的离线 HTML，视觉与信息密度对齐黄金样本，并额外满足「精度 / 芯片数 可排序」 | 单文件零外部依赖，双击可开；字段数 ≥ 黄金样本，且精度/芯片数列可按值排序 |

---

## 2. 目标用户与使用场景

| 用户角色 | 场景 | 关注点 |
|---|---|---|
| **硬件评测工程师** | 新机型/新固件发布前，批量验证各尺寸模型（0.8B~35B）在 目标机 上的可用性 | 哪些模型 / 上下文档位能跑、能跑多快、有无 OOM |
| **硬件评测工程师** | 出评测内容，需要可复现的吞吐曲线与对比表 | 曲线图、可离线分享的报告、启动参数留档（可复现） |
| **本机开发者/调参者**（次要） | 验证某个量化精度（Q8 vs Q4）或 UMA 显存划分对性能的影响 | 精度区分、芯片数、显存不足 vs 真跑不动的失败归因 |

**核心使用场景（Happy Path）**：用户把 `start.bat` 双击 → 后台起后端 → 浏览器打开 UI → 选模型目录 → 扫描出候选 → 勾选要测的模型 → 配置 llama-server 路径/端口/后端参数 → 点「开始测试」→ 实时看进度 → 跑完自动打开总览报告 → 用下拉筛选 + 表头排序分析。

---

## 3. 用户故事（含验收标准 AC）

| ID | 用户故事 | 验收标准（AC） |
|---|---|---|
| **US-01** | 作为产品经理，我想让工具自动扫描模型目录并列出候选 GGUF，以便我不必手敲路径逐个指定 | ① 输入一个目录路径后点「扫描」，列出所有 `*.gguf`，显示文件名/大小/推断精度（w8a8/w4a8）；② mmproj 文件被自动忽略（不进候选列表）；③ 无 gguf 时给出明确空态提示 |
| **US-02** | 作为工程师，我想在 UI 里勾选要跑的模型，以便只测我关心的几个 | ① 候选列表支持多选勾选；② 至少勾 1 个才能点「开始」，否则按钮禁用并提示；③ 支持全选/全不选 |
| **US-03** | 作为用户，我想配置 llama-server 路径、端口、GPU 后端参数，以便工具用我自己的二进制 | ① 可填 `.exe` 路径 / 端口 / 后端口（Vulkan 等）/ 额外参数；② 启动前检测端口占用，被占用则报错并阻止启动；③ 配置可持久化（重启 UI 后仍在） |
| **US-04** | 作为评测工程师，我想看到预置的双维度扫描任务（ctx × input），以便一键覆盖完整矩阵 | ① 默认 ctx 档 = 4/8/16/32/64/128/256K，input 档 = 0.25/0.5/1/2/4/8/16/32/64/128K；② **仅生成 input < ctx 的组合**；③ 档位可在 UI 调整 |
| **US-05** | 作为用户，我想在测试时看到实时进度并能中断，以便发现配错时及时止损 | ① 进度显示：当前模型 / 当前 ctx / 当前 input / 已完成点数 / 总点数 / 百分比；② 有「中断」按钮，点击后当前 llama-server 被终止、任务标记为已中断；③ 进度实时刷新（≤2s 延迟） |
| **US-06** | 作为用户，我想让工具在模型连续加载失败时自动跳过，以便不浪费时间 | ① 同一模型**连续 2 次失败（不分档位）** → 跳过该模型**剩余全部** ctx/input 档位；② 该模型状态标记为「已跳过」，并记录触发档位；③ 后续模型继续正常执行 |
| **US-07** | 作为工程师，我想区分「显存不足(OOM)」与「模型真跑不动」两类失败，以便定位是 BIOS UMA 划分问题还是模型问题 | ① 解析 llama.cpp stderr/退出码，将失败归类为 `OOM_GPU` / `MODEL_FAIL` / `TIMEOUT` / `OTHER`；② 报告状态列展示可读中文失败原因（而非笼统「所有运行失败」）；③ OOM 类失败在报告顶部给出「检查 BIOS UMA 显存划分」的提示 |
| **US-08** | 作为产品经理，我想拿到一份美观的离线 HTML 报告，以便直接分享 | ① 每个模型一份独立 HTML + 一份总览 overview.html；② 报告零 CDN、单文件可双击打开；③ 含 Prefill/Decode 曲线图、可折叠参数说明、汇总表、硬件信息 |
| **US-09** | 作为读者，我想在报告里按模型筛选并排序，以便从不同角度看数据 | ① 下拉筛选：模型/精度/芯片数/ctx；② 表头点击排序：Input(k)/Ctx(k)/Prefill/Decode/P-Time/D-Time/Vision/精度/芯片数/状态；③ 单模型页组内排序 + 总览页全局排序 |
| **US-10** | 作为评测工程师，我想报告记录 llama.cpp 启动参数，以便别人复现 | ① 报告顶部/参数区记录每档 ctx 的启动命令（含线程数、后端口、额外参数）；② 留存原始日志（stdout/stderr + 每点 JSON）到输出目录 |

---

## 4. 需求池（P0 / P1 / P2）

> 优先级定义：**P0 = Must have（没有它工具不可用/报告不达标）**；**P1 = Should have（体验与完整性，首版尽量做）**；**P2 = Nice to have（可延后/降级）**。

### P0（必须做，共 11 条）

| ID | 需求 | 说明 | 关联 |
|---|---|---|---|
| P0-01 | 后台启动后端服务 | `start.bat` 只负责后台拉起 Python 服务，不占用前台窗口；自动打开浏览器到 UI | 决策1 |
| P0-02 | 目录扫描 + 模型候选列表 | 扫描 gguf、忽略 mmproj、推断精度、显示候选 | US-01 |
| P0-03 | 模型勾选 | UI 多选，至少 1 个才可启动 | US-02 |
| P0-04 | llama-server 配置 | 路径/端口/GPU 后端/额外参数；端口占用检测 | US-03 |
| P0-05 | 双维度扫描引擎 | 按 ctx 档位重启 llama-server；仅生成 input<ctx 组合；串行执行（同一时刻 1 模型 1 实例） | 决策2、默认8 |
| P0-06 | 指标采集 + 中位数 | 每点预热 1 + 正式 3 取中位数；采 Prefill/Decode tps 与耗时；token 数经 `/tokenize` 校验 | 默认3/4/5 |
| P0-07 | 失败跳过规则 | 连续 2 次失败跳过该模型剩余档位，状态「已跳过」 | US-06、决策8 |
| P0-08 | 失败归因分类 | OOM_GPU / MODEL_FAIL / TIMEOUT / OTHER 可区分 | US-07 |
| P0-09 | 单模型 HTML 报告 | 曲线图 + 可折叠参数说明 + 汇总表 + 硬件信息 + 启动参数留档 | US-08、G3 |
| P0-10 | 总览 overview HTML | 汇总全部模型，与单模型页同套渲染逻辑 | 决策3 |
| P0-11 | 报告离线 + 筛选排序 | 零 CDN；模型/精度/芯片/ctx 筛选；表头按值排序 | US-09 |

### P1（应做，共 6 条）

| ID | 需求 | 说明 |
|---|---|---|
| P1-01 | 实时进度 + 中断按钮 | 轮询或 SSE 推送进度；可中断当前任务 |
| P1-02 | 配置持久化 | llama-server 路径/端口/扫描目录等写入本地配置文件 |
| P1-03 | 原始日志留存 | 每模型目录下保存 stdout/stderr 与每点 JSON |
| P1-04 | 自定义 prompt | UI 可粘贴自定义长文本 prompt，覆盖内置中性文本 |
| P1-05 | 跑完自动打开总览 | 任务结束后自动在浏览器打开 overview.html |
| P1-06 | 精度手动覆盖 | 文件名推断失败时 UI 可手动指定每个模型的 w8a8/w4a8 |

### P2（可延后，共 4 条）

| ID | 需求 | 说明 / 降级 |
|---|---|---|
| P2-01 | 每点重复次数可调 UI | 默认固定 3 次，先只读展示 |
| P2-02 | Decode 输出长度可调 UI | 默认固定 256 token |
| P2-03 | 多芯片数支持 | 默认固定 n_chip=1，UI 可改但不保证测试 |
| P2-04 | Vision 指标采集 | 本轮纯文本不实现，列保留恒为 0/-（决策7） |

---

## 5. UI 设计稿（文字线框 + 结构草图）

### 5.1 页面流

```
[start.bat] → 后台起后端 → 自动开浏览器
   │
   ▼
① 启动/状态页 ──健康检查OK──▶ ② 目录选择与扫描 ──▶ ③ 模型勾选
                                                          │
                                                          ▼
⑥ 报告页 ◀──跑完自动打开── ⑤ 测试进度 ◀──点开始── ④ 参数配置
   │
   ├─ 单模型报告（每个模型一份）
   └─ 总览报告（overview，默认打开）
```

### 5.2 页面 ① 启动/状态页（极简）

```
┌───────────────────────────────────────────────┐
│  GGUF Benchmark                     │
│  ● 后端已连接 (http://127.0.0.1:8765)          │
│  Python 3.11+ ✓   llama-server: 未配置 ✗       │
│                                                │
│  [ 进入配置 → ]                                │
└───────────────────────────────────────────────┘
```
- 若后端未就绪：显示「正在启动后端…」+ 重试；若 Python 版本 < 3.11 给出明确报错。

### 5.3 页面 ② 目录选择与扫描

```
┌───────────────────────────────────────────────┐
│  ① 模型目录                                     │
│  路径: [ D:/models                    ] [扫描] │
│  ○ 递归扫描子目录                               │
├───────────────────────────────────────────────┤
│  扫描结果 (共 8 个候选):                        │
│  ☑ Qwen3.5-0.8B-Q8_0.gguf    0.8B  w8a8  820MB │
│  ☑ Qwen3.5-2B-Q4_K_M.gguf    2B    w4a8  1.3GB │
│  ☐ mmproj-vision.gguf        (已忽略)          │
│  ...                                           │
│  已选 2 个                       [ 下一步 → ]   │
└───────────────────────────────────────────────┘
```
- mmproj 行显示为灰色并标注「已忽略」（决策7）。

### 5.4 页面 ③ 模型勾选（可与②合并为一屏）

- 表格列：勾选框 / 文件名 / 尺寸 / 推断精度（可下拉覆盖）/ 文件大小。
- 精度来源默认「解析文件名」：`Q8/w8a8 → w8a8`，`Q4/w4a8 → w4a8`（默认1）；无法判断时该行标黄，需手动选。

### 5.5 页面 ④ 参数配置

```
┌───────────────────────────────────────────────┐
│  llama-server                                  │
│  可执行文件: [ C:/llama/llama-server.exe ][浏览]│
│  端口: [8080]  后端: [vulkan ▼]  -ngl: [99]    │
│  额外参数: [ --flash-attn ...             ]     │
│  线程数: [16]   芯片数: [1]                     │
├───────────────────────────────────────────────┤
│  测试维度                                       │
│  ctx 档位:  ☑4K ☑8K ☑16K ☑32K ☑64K ☑128K ☑256K │
│  input档位: ☑0.25K ☑0.5K ☑1K ☑2K ☑4K ☑8K ☑16K  │
│             ☑32K ☑64K ☑128K                    │
│  预计组合数: 2 模型 × 45 组/模型 = 90 点        │
│  重复: 预热1 + 正式[3]   Decode长度: [256]      │
│  Prompt: (●) 内置中性长文本  ( ) 自定义 [____]  │
├───────────────────────────────────────────────┤
│  输出目录: [ ./reports ]   ☑跑完自动打开总览    │
│                     [ 开始测试 ]                │
└───────────────────────────────────────────────┘
```
- 前端实时按「仅保留 input < ctx」计算预计组合数（决策2）。
- 端口占用检测在点「开始」时执行并可提前「检测」。

### 5.6 页面 ⑤ 测试进度

```
┌───────────────────────────────────────────────┐
│  运行中…  模型 1/2: Qwen3.5-0.8B                │
│  ██████████████░░░░░░░░  58%  (26/45 点)       │
│  当前: ctx=32000  input=16000  w8a8            │
│  最近点: Prefill 6,923 tps | Decode 42.1 tps   │
│  ● 加载 llama-server(ctx=32000)…               │
│                            [ 中断 ]            │
└───────────────────────────────────────────────┘
```
- 每模型结束显示小结（成功 x/总 y，失败原因分布）。

### 5.7 页面 ⑥ 报告页（对齐黄金样本结构）

```
┌────────────────────────────────────────────────────────────┐
│  Benchmark Report                              │
│  生成时间: ... | 工具: GGUF Benchmark v1.0 | llama.cpp 后端   │
│  [ ▾ 参数说明（点击展开/收起） ]  ← <details class="intro">   │
├────────────────────────────────────────────────────────────┤
│  模型:[全部▾] 精度:[全部▾] 芯片:[全部▾] ctx:[全部▾]  数据点:392│
├────────────────────────────────────────────────────────────┤
│  [总数据点 392] [成功率 98%] [最高Prefill 12,345tps] [最高Decode 172tps] │
├────────────────────────────────────────────────────────────┤
│  <SVG> Prefill 吞吐率 (tps) — 对数横轴，多条 data-series 曲线  │
│  <SVG> Decode  吞吐率 (tps) — 同上                            │
├────────────────────────────────────────────────────────────┤
│  ▸ Qwen3.5-0.8B (0.8B) — 精度: w8a8 | 芯片: 1 | Context: 4,000 │
│    [Ctx(k)|Input(k)|Prefill|Decode|P-Time|D-Time|Vision|精度|  │
│     芯片数|状态]  ← 表头可点击排序                             │
│    ...（按 model,ctx 各一张表）                                │
├────────────────────────────────────────────────────────────┤
│  硬件: AMD <CPU 型号> / <GPU 型号> / 内存 64GB /Win11 │
│  启动参数: llama-server -m ... -c 32000 -ngl 99 --threads 16   │
└────────────────────────────────────────────────────────────┘
```

### 5.8 关键取舍：精度 / 芯片数如何呈现（**并存方案**）

参考报告把「精度 / 芯片数」放在分组标题里；用户要求的表格字段包含这两列。**决策：两者并存，且新增列为「一等列」。**

| 呈现位置 | 是否保留 | 理由 |
|---|---|---|
| 分组标题（`精度: w8a8 \| 芯片: 1 \| Context: 4000`） | ✅ 保留 | 与黄金样本视觉一致，读者扫一眼即知该表上下文；总览页多模型时便于分组定位 |
| 表格内新增「精度」「芯片数」两列 | ✅ 新增（P0） | 满足用户字段要求；**总览页全局排序必须有列值**（否则按精度排序时跨模型不可比）；单模型页内也可排序 |

- 两列默认**常显**，避免排序依赖隐藏列造成困惑；列顺序：`… | Vision(fps) | 精度 | 芯片数 | 状态`。
- 冗余信息不影响可读性：分组标题用中文全称，表格列用短值（`w8a8` / `1`）。

---

## 6. 数据模型（JSON Schema）

### 6.1 BenchmarkPoint（单个数据点，14 字段，与黄金样本对齐）

```json
{
  "$id": "BenchmarkPoint",
  "type": "object",
  "required": ["model_name","model_size","precision","n_chip","ctx_size",
               "input_tokens","output_tokens","prefill_tps","decode_tps",
               "vision_fps","prefill_time_ms","decode_time_ms","success","error_msg"],
  "properties": {
    "model_name":      { "type": "string", "example": "Qwen3.5-0.8B" },
    "model_size":      { "type": "string", "example": "0.8B" },
    "precision":       { "type": "string", "enum": ["w8a8","w4a8"] },
    "n_chip":          { "type": "integer", "default": 1 },
    "ctx_size":        { "type": "integer", "example": 32000 },
    "input_tokens":    { "type": "integer", "example": 16000 },
    "output_tokens":   { "type": "integer", "default": 256 },
    "prefill_tps":     { "type": "number" },
    "decode_tps":      { "type": "number" },
    "vision_fps":      { "type": "number", "default": 0 },
    "prefill_time_ms": { "type": "number" },
    "decode_time_ms":  { "type": "number" },
    "success":         { "type": "boolean" },
    "error_msg":       { "type": "string", "default": "" }
  },
  "x-extension": {
    "fail_reason": { "type": "string", "enum": ["OOM_GPU","MODEL_FAIL","TIMEOUT","OTHER",""] },
    "skipped":     { "type": "boolean", "description": "true=因连续失败被跳过，非真实测量点" }
  }
}
```

> 说明：`error_msg` 保持与黄金样本一致的字符串字段；新增的失败归因与跳过标记放在 `x-extension`（可选扩展），渲染时通过 `fail_reason` 生成可读中文（US-07）。

### 6.2 ModelMeta（模型元信息）

```json
{
  "$id": "ModelMeta",
  "type": "object",
  "properties": {
    "model_name":   { "type": "string" },
    "model_size":   { "type": "string" },
    "gguf_path":    { "type": "string" },
    "precision":    { "type": "string", "enum": ["w8a8","w4a8"] },
    "precision_source": { "type": "string", "enum": ["filename","manual"] },
    "n_chip":       { "type": "integer", "default": 1 },
    "file_size_mb": { "type": "number" },
    "selected":     { "type": "boolean", "default": false },
    "status":       { "type": "string", "enum": ["pending","running","done","skipped","aborted"] }
  }
}
```

### 6.3 HardwareInfo（硬件信息）

```json
{
  "$id": "HardwareInfo",
  "type": "object",
  "properties": {
    "cpu_model":      { "type": "string", "example": "AMD <CPU 型号>" },
    "host_model":     { "type": "string", "example": "主机型号" },
    "ram_gb":         { "type": "number",  "example": 64 },
    "os_version":     { "type": "string", "example": "Windows 11 Pro 24H2 (26100)" },
    "gpu":            { "type": "string", "example": "<GPU 型号>" },
    "gpu_backend":    { "type": "string", "example": "Vulkan RADV" },
    "uma_vram_gb":    { "type": "number", "description": "BIOS 划分的 UMA 显存，用于 OOM 归因提示" }
  }
}
```

### 6.4 TaskStatus（任务状态）

```json
{
  "$id": "TaskStatus",
  "type": "object",
  "properties": {
    "task_id":        { "type": "string" },
    "state":          { "type": "string", "enum": ["idle","running","aborting","done","error"] },
    "current_model":  { "type": "string" },
    "model_index":    { "type": "integer" },
    "model_total":    { "type": "integer" },
    "current_ctx":    { "type": "integer" },
    "current_input":  { "type": "integer" },
    "points_done":    { "type": "integer" },
    "points_total":   { "type": "integer" },
    "percent":        { "type": "number" },
    "last_point":     { "$ref": "BenchmarkPoint" },
    "consec_fail":    { "type": "integer", "description": "当前模型连续失败计数" },
    "message":        { "type": "string" }
  }
}
```

### 6.5 BenchConfig（测试与运行配置，含 8 决策 + 10 默认值）

```json
{
  "$id": "BenchConfig",
  "type": "object",
  "properties": {
    "scan_dir":          { "type": "string" },
    "recursive":         { "type": "boolean", "default": true },
    "llama_server_path": { "type": "string" },
    "port":              { "type": "integer", "default": 8080 },
    "gpu_backend":       { "type": "string", "default": "vulkan" },
    "extra_args":        { "type": "array", "items": {"type":"string"}, "default": [] },
    "threads":           { "type": "integer", "default": 16 },
    "n_chip":            { "type": "integer", "default": 1 },
    "ctx_levels":        { "type": "array", "items": {"type":"integer"},
                           "default": [4000,8000,16000,32000,64000,128000,256000] },
    "input_levels":      { "type": "array", "items": {"type":"integer"},
                           "default": [250,500,1000,2000,4000,8000,16000,32000,64000,128000] },
    "warmup_runs":       { "type": "integer", "default": 1 },
    "repeat_runs":       { "type": "integer", "default": 3 },
    "output_tokens":     { "type": "integer", "default": 256 },
    "precision_source":  { "type": "string", "enum": ["filename","manual"], "default": "filename" },
    "prompt_text":       { "type": "string", "description": "空=使用内置中性长文本" },
    "output_dir":        { "type": "string", "default": "./reports" },
    "auto_open_overview":{ "type": "boolean", "default": true },
    "skip_after_fails":  { "type": "integer", "default": 2 }
  }
}
```

---

## 7. 后端 API 契约（给架构师的硬输入）

> 基础：`http://127.0.0.1:<port>`，JSON；错误统一 `{ "ok": false, "error": {"code": "...", "message": "..."} }`。
> 建议实现：**FastAPI**（自带 OpenAPI + 简洁路由），Uvicorn 后台运行。

| # | 方法 | 路径 | 请求体 / 参数 | 响应体 | 说明 |
|---|---|---|---|---|---|
| A1 | GET | `/api/health` | — | `{ok, python_version, llama_server_found, version}` | UI 启动健康检查 |
| A2 | GET | `/api/config` | — | `BenchConfig` | 读取当前配置 |
| A3 | PUT | `/api/config` | `BenchConfig`(部分) | `{ok, config}` | 保存/更新配置（持久化） |
| A4 | POST | `/api/scan` | `{dir, recursive}` | `{ok, models: ModelMeta[]}` | 扫描目录，忽略 mmproj，推断精度 |
| A5 | POST | `/api/port-check` | `{port}` | `{ok, in_use: bool}` | 端口占用检测 |
| A6 | POST | `/api/tokenize` | `{text, model?}` | `{ok, token_count}` | 代理 llama.cpp `/tokenize`，用于真实 token 校验 |
| A7 | POST | `/api/tasks/preview` | `{models[], config}` | `{ok, total_points, per_model:[{model,points}], matrix}` | 计算实际执行矩阵（仅 input<ctx）与预计点数 |
| A8 | POST | `/api/tasks` | `{models: ModelMeta[], config}` | `{ok, task_id}` | 创建并**启动**测试任务（后台串行执行） |
| A9 | GET | `/api/tasks/{task_id}` | — | `TaskStatus` | 轮询任务状态（进度/中断按钮用） |
| A10 | GET | `/api/tasks/{task_id}/events` | — | `text/event-stream` | SSE 实时推送进度（P1；不可用时前端回退 A9 轮询） |
| A11 | POST | `/api/tasks/{task_id}/abort` | — | `{ok}` | 中断任务，终止当前 llama-server |
| A12 | GET | `/api/tasks/{task_id}/points` | `?model=` | `{ok, points: BenchmarkPoint[]}` | 拉取已采集数据点（失败点一并返回） |
| A13 | GET | `/api/reports` | — | `{ok, reports:[{model, path, generated_at}]}` | 列出已生成报告 |
| A14 | POST | `/api/reports/overview/build` | `{task_id}` | `{ok, path}` | 手动重新生成总览报告 |
| A15 | GET | `/reports/{model}.html` `/reports/overview.html` | — | `text/html` | 静态报告访问（file mount） |

**内部执行引擎（非 API，供架构师设计参考）**

```
for model in selected_models:            # 串行（决策8）
    for ctx in ctx_levels:               # 每档重启 llama-server
        start llama-server(--ctx ctx)    # 记录启动参数(决策10)
        wait_ready()
        for input in input_levels:
            if input >= ctx: continue    # 双维度裁剪(决策2)
            n = tokenize_len(prompt, input)   # /tokenize 校准(默认5)
            run(warmup=1) -> run(repeat=3) -> median
            record point(success, fail_reason)
            if model.consec_fail >= 2: mark skipped; break all  # (决策8/US-06)
        stop llama-server()
    generate model report html
generate overview.html; auto open
```

---

## 8. 非功能需求

| 类别 | 要求 |
|---|---|
| **性能** | UI 操作响应 < 200ms；扫描 1k 个 gguf < 3s；SSE 进度延迟 ≤ 2s；报告生成（392 点）< 5s |
| **可用性** | 首次使用 ≤ 3 步启动；所有失败均有中文可读提示；中断后资源（llama-server 进程/端口）必须释放 |
| **离线** | 报告 100% 零 CDN，单文件自包含（内联 CSS/JS/SVG）；UI 本身也需本地资源，不依赖外网 |
| **日志** | 每模型：`reports/<model>/llama_stdout.log`、`llama_stderr.log`、`points.json`；任务级 `task.log` |
| **可复现** | 报告记录每档 ctx 的完整启动参数（含 -c/-ngl/--threads/后端口/额外参数）+ 工具版本 + llama.cpp 版本 |
| **鲁棒性** | 端口占用/llama-server 不存在/目录无 gguf/Python<3.11 均给明确错误；llama-server 崩溃自动重启一次后计入失败 |
| **串行约束** | 全局同时仅允许 1 个任务、1 个 llama-server 实例；重复启动请求被拒绝 |
| **资源** | 任务结束后无残留进程；单项测量加超时（建议 prefill 超时 = ctx/最低速率估算 × 3，可配置） |

---

## 9. 验收标准的环境约束（重要）

> **开发机是 macOS，无 Windows / 无 llama.cpp / 无 AMD 核显。** 真实推理性能数据无法在开发机验证。

因此验收分两层：

| 层级 | 可验证内容 | 方法 |
|---|---|---|
| **可验证（开发机）** | ① 全链路闭环（扫描→勾选→配置→mock 执行→报告生成）可跑通；② 报告 HTML **逐字段**与黄金样本对齐（14 字段渲染、SVG 结构、筛选/排序、折叠区块、零 CDN）；③ 失败跳过、失败归因、双维度裁剪、token 校准等**逻辑**用 mock 数据断言 | 用 mock `llama-server`（返回固定 tps）跑端到端；与 `395-result.html` 逐字段 diff |
| **不可验证（需目标机）** | ④ 真实吞吐数值；⑤ 真实 OOM 触发与 UMA 归因；⑥ 真实模型加载失败判定 | 交付时在 目标机（Windows 11）上由用户执行冒烟测试；PRD 中这些项标注为「目标机验收」 |

**结论**：P0「报告与逻辑」以开发机 mock 为准；P0「真实性能/失败判定」以目标机冒烟为准，开发阶段不得声称已验证真实性能。

---

## 10. 待确认问题

> 已按默认值自行拍板，列出仅供团队知悉，**不阻塞开发**。

| # | 问题 | 已拍板默认 |
|---|---|---|
| Q1 | 失败跳过的「连续 2 次」是否跨 ctx 档位计数？ | **是**，不分档位（用户已明确）。跨到新 ctx 不重置计数，但**成功一次即清零** |
| Q2 | ctx 档位重启 llama-server 时 KV cache 复用还是重载？ | 每档**重启**（决策8 串行 + 保证 ctx 生效） |
| Q3 | 内置 prompt 的具体长度与内容？ | 选一段中性中文长文本（如技术文档片段），运行时用 `/tokenize` 截断/复制到目标长度 |
| Q4 | 超时阈值如何定？ | 按「ctx ÷ 模型最低可接受速率 × 3」估算，配置项可覆盖；默认单点上限 30min |
| Q5 | 总览页是否也需要曲线图？ | **是**（复用单模型页渲染逻辑，按模型着色），与黄金样本一致 |
| Q6 | 报告文件名冲突（同名模型不同精度）？ | 文件名 = `<模型名>_<精度>.html`，冲突时追加序号 |

---

*本文档为简单 PRD，已含用户确认的 8 项设计决策与 10 项默认值；未做竞品分析（按主理人要求）。*

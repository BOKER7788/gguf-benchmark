// 哈希路由 + 6 视图交互 + SSE/轮询进度 + 中断（零框架、零构建）
(function () {
  'use strict';

  // ---- 常量子源 ----
  const CTX_LEVELS = [4000, 8000, 16000, 32000, 64000, 128000, 256000];
  const INPUT_LEVELS = [250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000, 128000];

  const state = {
    candidates: [],       // [{model_name, model_size, gguf_path, precision, file_size_mb, selected}]
    selected: {},         // key=gguf_path -> bool
    taskId: null,
    eventSource: null,
    pollTimer: null,
    autoOpen: true,
    busy: false
  };

  const $ = (id) => document.getElementById(id);

  // ---- 路由 ----
  function currentView() {
    const hash = (location.hash || '#start').replace('#', '');
    const known = ['start', 'scan', 'select', 'config', 'progress', 'report'];
    return known.indexOf(hash) >= 0 ? hash : 'start';
  }

  function showView() {
    const view = currentView();
    document.querySelectorAll('.view').forEach((el) => el.classList.remove('active'));
    const target = $('v-' + view);
    if (target) target.classList.add('active');
    document.querySelectorAll('.nav a').forEach((a) => {
      a.classList.toggle('active', a.getAttribute('data-view') === view);
    });
    if (view === 'report') loadReports();
  }

  // ---- ① 开始页：健康检查 + 上手向导（P1-3 / P0-8）----
  function setStep(id, ok, text) {
    const dot = $(id + 'Dot');
    if (dot) dot.className = 'step-dot ' + (ok === true ? 'dot-ok' : ok === false ? 'dot-bad' : 'dot-wait');
    const t = $(id + 'Text');
    if (t && text != null) t.textContent = text;
  }

  function updateMockWarn(willMock) {
    ['mockWarn', 'mockWarn2'].forEach((id) => {
      const el = $(id);
      if (el) el.style.display = willMock ? '' : 'none';
    });
    const w3 = $('mockWarn3');
    if (w3 && !willMock) w3.style.display = 'none';
  }

  async function checkHealth() {
    try {
      const data = await API.health();
      $('healthDot').className = 'dot dot-ok';
      $('healthText').textContent = '后端已连接 (' + location.origin + ')';
      const pyOk = String(data.python_version || '') >= '3.11';
      $('pyVersion').textContent = data.python_version + (pyOk ? ' ✓' : ' ✗（需要 3.11 或更高）');
      $('llamaFound').textContent = data.llama_server_found ? '已配置 ✓' : '未配置';
      $('outDir').textContent = data.output_dir || '—';
      $('toolVersion').textContent = 'v' + data.version + (data.author ? '  ·  by ' + data.author : '');
      const bv = $('brandVer');
      if (bv) bv.textContent = 'v' + data.version;

      // 上手向导第 1 步：Python 环境
      setStep('step1', pyOk, pyOk
        ? 'Python ' + data.python_version + '，依赖已就绪 ✓'
        : 'Python 版本偏低（' + data.python_version + '），请安装 3.11 或更高版本');

      // 第 2 步：llama-server
      setStep('step2', !!data.llama_server_found, data.llama_server_found
        ? '已配置，可以测真实性能 ✓'
        : '尚未获取。点下面的按钮自动下载，或手动指定已有的 llama-server.exe');

      // 第 3 步：模型
      const hasModels = state.candidates.length > 0;
      setStep('step3', hasModels ? true : null, hasModels
        ? '已发现 ' + state.candidates.length + ' 个模型 ✓'
        : '正在查找模型…若目录为空，请把 .gguf 放进 models/ 目录，或到「② 选模型」指定文件夹');

      updateMockWarn(!data.llama_server_found);
      return true;
    } catch (e) {
      $('healthDot').className = 'dot dot-wait';
      $('healthText').textContent = '正在启动后端…';
      return false;
    }
  }

  async function refreshRunnerMode() {
    try {
      const d = await API.runnerMode();
      updateMockWarn(!!d.will_use_mock);
    } catch (e) { /* 忽略 */ }
  }

  async function waitForBackend() {
    for (let i = 0; i < 60; i++) {
      if (await checkHealth()) { await loadConfig(); return; }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  // ---- ② 扫描 ----
  function renderScanResult() {
    const ignored = state.ignored || [];
    if (!state.candidates.length && !ignored.length) {
      $('scanResult').innerHTML = '<p class="muted" style="padding:1rem 0;">尚未扫描或目录内无 .gguf 文件。</p>';
      $('scanSummary').textContent = '';
      return;
    }
    $('scanSummary').textContent = `共 ${state.candidates.length} 个候选` + (ignored.length ? `，忽略 ${ignored.length} 个 mmproj` : '');
    let html = '<table><thead><tr><th>文件名</th><th>尺寸</th><th>精度</th><th>大小(MB)</th></tr></thead><tbody>';
    state.candidates.forEach((m) => {
      html += `<tr><td>${escapeHtml(m.model_name)}</td><td>${m.model_size}</td><td>${m.precision}</td><td>${m.file_size_mb}</td></tr>`;
    });
    ignored.forEach((name) => {
      html += `<tr class="ignored"><td>${escapeHtml(name)}</td><td>—</td><td>—</td><td>（已忽略）</td></tr>`;
    });
    html += '</tbody></table>';
    $('scanResult').innerHTML = html;
  }

  async function doScan() {
    const dir = $('scanDir').value.trim();
    const recursive = $('scanRecursive').checked;
    if (!dir) { alert('请输入模型目录路径'); return; }
    $('scanBtn').disabled = true;
    try {
      const data = await API.scan(dir, recursive);
      state.candidates = data.models || [];
      state.ignored = data.ignored || [];
      state.selected = {};
      state.candidates.forEach((m) => { state.selected[m.gguf_path] = true; m.selected = true; });
      renderScanResult();
      renderSelectResult();
      updateSelectedCount();
      location.hash = '#select';
    } catch (e) {
      alert('扫描失败: ' + e.message);
    } finally {
      $('scanBtn').disabled = false;
    }
  }

  // ---- ③ 勾选 ----
  function renderSelectResult() {
    if (!state.candidates.length) {
      $('selectResult').innerHTML = '<p class="muted" style="padding:1rem 0;">请先在②扫描目录。</p>';
      return;
    }
    let html = '<table><thead><tr><th>选</th><th>文件名</th><th>尺寸</th><th>精度</th><th>大小(MB)</th></tr></thead><tbody>';
    state.candidates.forEach((m, i) => {
      const checked = state.selected[m.gguf_path] ? 'checked' : '';
      html += `<tr>
        <td><input type="checkbox" data-idx="${i}" class="modelCheck" ${checked}></td>
        <td>${escapeHtml(m.model_name)}</td>
        <td>${m.model_size}</td>
        <td>
          <select class="input precSelect" data-idx="${i}" style="width:auto;">
            <option value="w8a8" ${m.precision === 'w8a8' ? 'selected' : ''}>w8a8</option>
            <option value="w4a8" ${m.precision === 'w4a8' ? 'selected' : ''}>w4a8</option>
          </select>
        </td>
        <td>${m.file_size_mb}</td>
      </tr>`;
    });
    html += '</tbody></table>';
    $('selectResult').innerHTML = html;

    document.querySelectorAll('.modelCheck').forEach((el) => {
      el.addEventListener('change', () => {
        const idx = parseInt(el.getAttribute('data-idx'), 10);
        const path = state.candidates[idx].gguf_path;
        state.selected[path] = el.checked;
        state.candidates[idx].selected = el.checked;
        updateSelectedCount();
      });
    });
    document.querySelectorAll('.precSelect').forEach((el) => {
      el.addEventListener('change', () => {
        const idx = parseInt(el.getAttribute('data-idx'), 10);
        state.candidates[idx].precision = el.value;
        state.candidates[idx].precision_source = 'manual';
      });
    });
  }

  function selectedModels() {
    return state.candidates.filter((m) => state.selected[m.gguf_path]);
  }

  function updateSelectedCount() {
    const n = selectedModels().length;
    $('selectedCount').textContent = n;
    $('toConfig').disabled = n === 0;
    updateCombo();
  }

  // ---- ④ 配置 ----
  function buildChips() {
    $('ctxLevels').innerHTML = CTX_LEVELS.map((c) =>
      `<label><input type="checkbox" class="ctxChip" value="${c}" checked> ${c / 1000}K</label>`).join('');
    $('inputLevels').innerHTML = INPUT_LEVELS.map((c) =>
      `<label><input type="checkbox" class="inputChip" value="${c}" checked> ${c / 1000}K</label>`).join('');
    document.querySelectorAll('.ctxChip, .inputChip').forEach((el) => el.addEventListener('change', updateCombo));
  }

  function checkedValues(selector) {
    return Array.prototype.slice.call(document.querySelectorAll(selector))
      .filter((el) => el.checked).map((el) => parseInt(el.value, 10)).sort((a, b) => a - b);
  }

  function computeCombos(ctx, input) {
    let total = 0;
    ctx.forEach((c) => { input.forEach((i) => { if (i < c) total++; }); });
    return total;
  }

  function updateCombo() {
    const perModel = computeCombos(checkedValues('.ctxChip'), checkedValues('.inputChip'));
    const models = selectedModels().length;
    $('comboCount').textContent = perModel;
    $('comboModels').textContent = models;
    $('comboTotal').textContent = perModel * models;
    updateBiosWarn();
    updateTimeEstimate();
    refreshFeasibility();
  }

  // 体量/内存可行性提示（v1.1.2）：在开跑之前就把「装不下」的模型标出来。
  // 旧版没有任何这类校验，224 GB 的模型也能一路跑到底并显示成功。
  async function refreshFeasibility() {
    const box = $('footprintWarn');
    if (!box) return;
    const models = selectedModels();
    if (!models.length) { box.style.display = 'none'; return; }
    let data = null;
    try {
      data = await API.preview(models, collectConfig());
    } catch (e) { box.style.display = 'none'; return; }

    const list = (data && data.feasibility) || [];
    const bad = list.filter((f) => f.level === 'impossible');
    const tight = list.filter((f) => f.level === 'tight');
    if (!bad.length && !tight.length) { box.style.display = 'none'; return; }

    const mem = data && data.memory_gb ? `本机可用内存约 ${data.memory_gb} GB。` : '';
    let html = '';
    if (bad.length) {
      html += '<b>⚠️ 以下模型本机装不下（仅权重就超过内存）：</b>'
        + '<div class="banner-sub">'
        + bad.map((f) => `${escapeHtml(f.model)}：${f.weights_gib} GiB / ${f.capacity_gb} GB`)
            .join('；')
        + `。${mem}real 模式下它们会直接失败（本工具会跳过并标记为「显存不足」）；`
        + '在 mock 模式下它们会显示成功，但那不是真实数据。</div>';
    }
    if (tight.length) {
      html += `<b>提示：${tight.length} 个模型的内存占用偏高。</b>`
        + '<div class="banner-sub">'
        + tight.map((f) => `${escapeHtml(f.model)}：${f.weights_gib} GiB / ${f.capacity_gb} GB`)
            .join('；')
        + '。建议先点「先试跑 1 个档位」，并把上下文档位调小。</div>';
    }
    box.innerHTML = html;
    box.style.display = '';
  }

  async function loadConfig() {
    try {
      const cfg = await API.getConfig();
      $('scanDir').value = cfg.scan_dir || '';
      $('scanRecursive').checked = !!cfg.recursive;
      $('cfgLlamaPath').value = cfg.llama_server_path || '';
      $('cfgPort').value = cfg.port;
      $('cfgBackend').value = cfg.gpu_backend || 'vulkan';
      $('cfgNgl').value = cfg.n_gpu_layers != null ? cfg.n_gpu_layers : 99;
      $('cfgThreads').value = cfg.threads;
      $('cfgNChip').value = cfg.n_chip;
      $('cfgExtra').value = (cfg.extra_args || []).join(' ');
      $('cfgRunnerMode').value = cfg.runner_mode || 'auto';
      $('cfgWarmup').value = cfg.warmup_runs;
      $('cfgRepeat').value = cfg.repeat_runs;
      $('cfgOutputTokens').value = cfg.output_tokens;
      $('cfgSkipFails').value = cfg.skip_after_fails;
      $('cfgTimeout').value = cfg.prefill_timeout_s;
      $('cfgPrompt').value = cfg.prompt_text || '';
      $('cfgOutputDir').value = cfg.output_dir || './reports';
      $('cfgAutoOpen').checked = !!cfg.auto_open_overview;
      state.autoOpen = !!cfg.auto_open_overview;
      updateCombo();
      // 开箱即用：随包分发的 models/ 已在配置里，启动时自动扫描一次，
      // 让零基础用户不必再手点「扫描」就能直接试跑。
      await autoScanIfConfigured();
    } catch (e) { /* 后端未就绪时忽略 */ }
  }

  // 启动时自动扫描：仅在「已配置模型目录」且「尚无候选」时执行，不打断用户已有选择。
  async function autoScanIfConfigured() {
    const dir = $('scanDir').value.trim();
    if (!dir || state.candidates.length) return false;
    try {
      const data = await API.scan(dir, $('scanRecursive').checked);
      state.candidates = data.models || [];
      state.ignored = data.ignored || [];
      state.selected = {};
      state.candidates.forEach((m) => { state.selected[m.gguf_path] = true; m.selected = true; });
      renderScanResult();
      renderSelectResult();
      updateSelectedCount();
      if (state.candidates.length) {
        setStep('step3', true, '已发现 ' + state.candidates.length + ' 个模型 ✓');
      }
      return state.candidates.length > 0;
    } catch (e) {
      return false;   // 目录不存在等 → 交给用户手动扫描
    }
  }

  function collectConfig() {
    return {
      scan_dir: $('scanDir').value.trim(),
      recursive: $('scanRecursive').checked,
      llama_server_path: $('cfgLlamaPath').value.trim(),
      port: parseInt($('cfgPort').value, 10) || 8080,
      gpu_backend: $('cfgBackend').value,
      n_gpu_layers: parseInt($('cfgNgl').value, 10) || 99,
      threads: parseInt($('cfgThreads').value, 10) || 16,
      n_chip: parseInt($('cfgNChip').value, 10) || 1,
      extra_args: $('cfgExtra').value.trim() ? $('cfgExtra').value.trim().split(/\s+/) : [],
      runner_mode: $('cfgRunnerMode').value,
      ctx_levels: checkedValues('.ctxChip'),
      input_levels: checkedValues('.inputChip'),
      warmup_runs: parseInt($('cfgWarmup').value, 10) || 1,
      repeat_runs: parseInt($('cfgRepeat').value, 10) || 3,
      output_tokens: parseInt($('cfgOutputTokens').value, 10) || 256,
      skip_after_fails: parseInt($('cfgSkipFails').value, 10) || 2,
      prefill_timeout_s: parseInt($('cfgTimeout').value, 10) || 1800,
      prompt_text: $('cfgPrompt').value,
      output_dir: $('cfgOutputDir').value.trim() || './reports',
      auto_open_overview: $('cfgAutoOpen').checked
    };
  }

  async function doPortCheck() {
    const port = parseInt($('cfgPort').value, 10) || 8080;
    try {
      const data = await API.portCheck(port);
      $('portCheckMsg').textContent = data.in_use
        ? `端口 ${port} 已被占用 ✗` : `端口 ${port} 可用 ✓`;
      $('portCheckMsg').style.color = data.in_use ? 'var(--red)' : 'var(--green)';
    } catch (e) {
      $('portCheckMsg').textContent = '检测失败: ' + e.message;
      $('portCheckMsg').style.color = 'var(--red)';
    }
  }

  // ---- ⑤ 进度 ----
  async function startTask(quick) {
    const models = selectedModels();
    if (!models.length) { alert('请至少勾选 1 个模型'); return; }
    if (state.busy) { alert('已有任务在运行'); return; }
    const cfg = collectConfig();
    cfg.quick_test = !!quick;
    if (!cfg.ctx_levels.length || !cfg.input_levels.length) { alert('请至少各勾选 1 个档位'); return; }

    // 没设置 llama-server 又强制 real 会直接失败；auto 会降级成 mock，这里给出明确提示
    if (!cfg.llama_server_path && cfg.runner_mode === 'auto') {
      const ok = confirm('还没有设置 llama-server 路径。\n\n' +
        '继续的话只会得到「模拟数据」，不代表你机器的真实性能。\n\n' +
        '仍要继续吗？（建议先取消，去「① 开始」点「一键获取 llama.cpp」）');
      if (!ok) return;
    }

    // 显式选了 mock：把代价讲清楚再放行（v1.1.2）。
    // 旧版只靠一个可以视而不见的提示条，结果用户拿 mock 数据当成了真机性能。
    if (cfg.runner_mode === 'mock') {
      const ok = confirm('当前运行模式是 mock（合成数据）。\n\n' +
        '· 不会加载任何模型，也不会启动 llama-server；\n' +
        '· tps 与耗时是按模型名里的参数规模算出来的合成值；\n' +
        '· 因此再大的模型（包括本机内存装不下的）也会显示「成功」。\n\n' +
        '这份结果不能用来做选型或性能结论。仍要继续吗？');
      if (!ok) return;
    }

    // 体积超限的模型：real 模式下会被直接跳过，提前说清楚（v1.1.2）
    try {
      const pre = await API.preview(models, cfg);
      const bad = ((pre && pre.feasibility) || []).filter((f) => f.level === 'impossible');
      if (bad.length && cfg.runner_mode !== 'mock') {
        const ok = confirm('以下模型仅权重就超过本机内存，本次会被直接跳过（标记为「显存不足」）：\n\n' +
          bad.map((f) => '· ' + f.model + '（' + f.weights_gib + ' GiB / 可用 ' + f.capacity_gb + ' GB）').join('\n') +
          '\n\n仍要开始吗？');
        if (!ok) return;
      }
    } catch (e) { /* 预检失败不阻塞启动 */ }

    try {
      await API.putConfig(cfg);
      const preview = await API.preview(models, cfg);
      if (preview.matrix && preview.matrix.total) $('comboCount').textContent = preview.matrix.total;
      if (preview.total_points) $('comboTotal').textContent = preview.total_points;

      const data = await API.createTask(models, cfg);
      state.taskId = data.task_id;
      state.busy = true;
      state.autoOpen = cfg.auto_open_overview;
      resetProgress();
      location.hash = '#progress';
      subscribeProgress(state.taskId);
    } catch (e) {
      alert('启动失败: ' + e.message);
    }
  }

  function resetProgress() {
    $('progBar').style.width = '0%';
    $('progPercent').textContent = '0%';
    $('progPoints').textContent = '0/0';
    $('progModelIdx').textContent = '0/0';
    $('progModelName').textContent = '—';
    $('progCtx').textContent = '—';
    $('progInput').textContent = '—';
    $('progLast').textContent = '—';
    $('progMessage').textContent = '—';
    $('elapsedText').textContent = '—';
    $('etaText').textContent = '估算中…';
    $('doneCard').style.display = 'none';
  }

  function applyStatus(status) {
    if (!status) return;
    if (status.model_total) $('progModelIdx').textContent = `${status.model_index}/${status.model_total}`;
    if (status.current_model) $('progModelName').textContent = status.current_model;
    if (status.current_ctx) $('progCtx').textContent = status.current_ctx;
    if (status.current_input) $('progInput').textContent = status.current_input;
    $('progBar').style.width = (status.percent || 0) + '%';
    $('progPercent').textContent = (status.percent || 0).toFixed(0) + '%';
    $('progPoints').textContent = `${status.points_done}/${status.points_total}`;
    if (status.message) $('progMessage').textContent = status.message;

    // 已用时 / 预计剩余（P0-9）
    $('elapsedText').textContent = fmtDuration(status.elapsed_s);
    $('etaText').textContent = status.eta_s > 0 ? fmtDuration(status.eta_s) : '估算中…';

    // mock 警示（P0-8）：进度页也要醒目提示
    const w3 = $('mockWarn3');
    if (w3) w3.style.display = status.runner_mode_effective === 'mock' ? '' : 'none';

    const p = status.last_point;
    if (p) {
      $('progLast').textContent = p.success
        ? `Prefill ${p.prefill_tps.toLocaleString()} tps | Decode ${p.decode_tps.toLocaleString()} tps @ ctx=${p.ctx_size}`
        : `失败：${failText(p.fail_reason) || p.error_msg || '运行失败'}`;
    }
  }

  function failText(reason) {
    const map = { OOM_GPU: '显存不足(OOM)', MODEL_FAIL: '模型加载失败', TIMEOUT: '超时', OTHER: '运行失败' };
    return map[reason] || '';
  }

  function subscribeProgress(taskId) {
    cleanupProgressListeners();
    if ('EventSource' in window) {
      try {
        const es = new EventSource(`/api/tasks/${taskId}/events`);
        state.eventSource = es;
        es.onmessage = (ev) => {
          let payload = null;
          try { payload = JSON.parse(ev.data); } catch (e) { return; }
          applyStatus(payload.status);
          if (payload.type === 'done' || payload.type === 'error') onTaskDone(taskId);
        };
        es.onerror = () => { es.close(); state.eventSource = null; startPolling(taskId); };
        return;
      } catch (e) { /* 回退轮询 */ }
    }
    startPolling(taskId);
  }

  function startPolling(taskId) {
    if (state.pollTimer) return;
    state.pollTimer = setInterval(async () => {
      try {
        const status = await API.getTask(taskId);
        applyStatus(status);
        if (status.state === 'done' || status.state === 'error') onTaskDone(taskId);
      } catch (e) { /* 忽略瞬时错误 */ }
    }, 1000);
  }

  function cleanupProgressListeners() {
    if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  async function onTaskDone(taskId) {
    cleanupProgressListeners();
    state.busy = false;
    $('progMessage').textContent = '任务已完成';
    $('etaText').textContent = '—';
    await loadReports();
    await showDoneCard(taskId);
    if (state.autoOpen) {
      location.hash = '#report';
      setReportFrame('/reports/overview.html');
    }
  }

  async function showDoneCard(taskId) {
    try {
      const data = await API.taskPoints(taskId);
      const pts = data.points || [];
      if (!pts.length) return;
      const ok = pts.filter((p) => p.success).length;
      const skipped = pts.filter((p) => p.skipped).length;
      const rate = Math.round((ok / pts.length) * 100);
      $('donePassRate').textContent = rate + '%（' + ok + '/' + pts.length + '）';
      $('doneFail').textContent = String(pts.length - ok);
      let hint = '';
      if (skipped) hint += `${skipped} 个点因连续失败被跳过。`;
      if (rate === 0) {
        hint += ' 全部失败：请检查 llama-server 路径是否正确、模型文件是否完整。';
      } else if (rate < 100) {
        hint += ' 失败点多为显存不足或超时 —— 报告顶部的说明会告诉你具体原因与处理办法。';
      } else {
        hint += ' 全部成功。可以在下面的报告里把鼠标放到曲线上查看每个档位的数值。';
      }
      $('doneHint').textContent = hint.trim();
      $('doneCard').style.display = '';
    } catch (e) { /* 拿不到就只是不显示统计卡 */ }
  }

  async function doAbort() {
    if (!state.taskId) return;
    try {
      await API.abortTask(state.taskId);
      $('progMessage').textContent = '已请求中断…';
    } catch (e) { alert('中断失败: ' + e.message); }
  }

  // ---- ⑥ 报告 ----
  async function loadReports() {
    try {
      const data = await API.listReports();
      const reports = data.reports || [];
      const select = $('reportSelect');
      select.innerHTML = '';
      const overviewOpt = document.createElement('option');
      overviewOpt.value = '/reports/overview.html';
      overviewOpt.textContent = '总览 overview.html';
      select.appendChild(overviewOpt);
      reports.forEach((r) => {
        if (r.path.endsWith('overview.html')) return;
        const opt = document.createElement('option');
        opt.value = r.path;
        opt.textContent = r.model + '  (' + r.generated_at + ')';
        select.appendChild(opt);
      });
      select.onchange = () => setReportFrame(select.value);
    } catch (e) { /* 忽略 */ }
  }

  function setReportFrame(src) {
    $('reportFrame').src = src;
    $('reportSelect').value = src;
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
  }

  // ---- 面向零基础用户的辅助交互（P0-3 / P0-6 / P0-9 / P0-11）----

  async function chooseDir() {
    try {
      const d = await API.pickDir('请选择放有 .gguf 模型的文件夹');
      if (d && d.path) { $('scanDir').value = d.path; await doScan(); }
    } catch (e) {
      alert('无法打开文件夹选择窗口：' + e.message + '\n\n直接把路径粘贴到输入框里也可以。');
    }
  }

  async function chooseLlamaFile() {
    try {
      const d = await API.pickFile('请选择 llama-server 可执行文件',
        '可执行文件|*.exe|所有文件|*.*');
      if (d && d.path) { $('cfgLlamaPath').value = d.path; await checkLlamaPath(); }
    } catch (e) {
      alert('无法打开文件选择窗口：' + e.message + '\n\n直接把路径粘贴到输入框里也可以。');
    }
  }

  async function checkLlamaPath() {
    const p = $('cfgLlamaPath').value.trim();
    const msg = $('llamaCheckMsg');
    if (!p) { msg.textContent = '尚未设置 —— 不设置只能得到模拟数据'; msg.style.color = 'var(--text-secondary)'; return; }
    try {
      const r = await API.llamaCheck(p);
      if (r.exists && r.runnable) {
        msg.textContent = '✓ 可用：' + (r.version || p);
        msg.style.color = 'var(--green)';
      } else if (r.exists) {
        msg.textContent = '⚠️ 文件存在但无法执行：' + (r.version || '（没有输出）');
        msg.style.color = 'var(--red)';
      } else {
        msg.textContent = '✗ 找不到这个文件，请重新选择';
        msg.style.color = 'var(--red)';
      }
      await refreshRunnerMode();
    } catch (e) {
      msg.textContent = '校验失败：' + e.message;
      msg.style.color = 'var(--red)';
    }
  }

  let dlTimer = null;

  async function downloadLlama() {
    try {
      $('dlProgress').style.display = '';
      $('dlLlamaBtn').disabled = true;
      await API.llamaDownload('');
      if (dlTimer) clearInterval(dlTimer);
      dlTimer = setInterval(downloadTick, 1000);
      downloadTick();
    } catch (e) {
      $('dlLlamaBtn').disabled = false;
      alert('启动下载失败：' + e.message);
    }
  }

  async function downloadTick() {
    try {
      const s = await API.llamaDownloadStatus();
      const pct = Number(s.percent || 0);
      $('dlBar').style.width = pct + '%';
      $('dlText').textContent = s.total_mb
        ? `${pct}%  ${s.downloaded_mb} / ${s.total_mb} MB`
        : (s.message || '准备中…');
      if (s.state === 'done') {
        clearInterval(dlTimer); dlTimer = null;
        $('dlLlamaBtn').disabled = false;
        $('cfgLlamaPath').value = s.llama_server_path || '';
        await checkLlamaPath();
        alert('llama.cpp 已就绪，可以开始真实测试了。');
      } else if (s.state === 'error') {
        clearInterval(dlTimer); dlTimer = null;
        $('dlLlamaBtn').disabled = false;
        alert('下载失败：' + (s.error || '未知错误') +
          '\n\n可以手动到 github.com/ggml-org/llama.cpp 的 Releases 下载 Windows 版，' +
          '解压后用「选择文件」指定 llama-server.exe。');
      }
    } catch (e) { /* 忽略瞬时错误 */ }
  }

  function updateBiosWarn() {
    const big = checkedValues('.ctxChip').some((c) => c >= 64000);
    const el = $('biosWarn');
    if (el) el.style.display = big ? '' : 'none';
  }

  function fmtDuration(sec) {
    if (!sec || sec <= 0) return '—';
    if (sec < 60) return Math.round(sec) + ' 秒';
    if (sec < 3600) return Math.round(sec / 60) + ' 分钟';
    const h = Math.floor(sec / 3600);
    const m = Math.round((sec % 3600) / 60);
    return h + ' 小时' + (m ? ' ' + m + ' 分' : '');
  }

  // 粗估：每点耗时 ≈ (预热+重复) × (输入千token × 0.35 + 0.6) 秒，另加每档重启服务的固定开销
  function estimateSeconds() {
    const ctx = checkedValues('.ctxChip');
    const input = checkedValues('.inputChip');
    const models = selectedModels().length || 1;
    const runs = (parseInt($('cfgWarmup').value, 10) || 1) + (parseInt($('cfgRepeat').value, 10) || 3);
    const perModel = ctx.reduce((acc, c) => acc + input.filter((i) => i < c)
      .reduce((a, i) => a + runs * (i / 1000 * 0.35 + 0.6), 0), 0);
    return (perModel + ctx.length * 20) * models;
  }

  function updateTimeEstimate() {
    const el = $('timeEstimate');
    if (!el) return;
    if (!selectedModels().length) { el.textContent = '先在上面勾选模型'; return; }
    el.textContent = '约 ' + fmtDuration(estimateSeconds()) + '（粗估，实际取决于模型大小与机器性能）';
  }

  async function openReportFolder() {
    try { await API.openFolder(''); }
    catch (e) { alert('无法打开文件夹：' + e.message); }
  }

  // ---- 初始化 ----
  function bind() {
    document.querySelectorAll('[data-goto]').forEach((el) => {
      el.addEventListener('click', () => { location.hash = el.getAttribute('data-goto'); });
    });
    $('scanBtn').addEventListener('click', doScan);
    $('pickDirBtn').addEventListener('click', chooseDir);
    $('pickLlamaBtn').addEventListener('click', chooseLlamaFile);
    const p2 = $('pickLlamaBtn2');
    if (p2) p2.addEventListener('click', chooseLlamaFile);
    $('dlLlamaBtn').addEventListener('click', downloadLlama);
    const lp = $('cfgLlamaPath');
    if (lp) lp.addEventListener('change', checkLlamaPath);
    $('selectAll').addEventListener('click', () => {
      state.candidates.forEach((m) => { state.selected[m.gguf_path] = true; m.selected = true; });
      renderSelectResult(); updateSelectedCount();
    });
    $('selectNone').addEventListener('click', () => {
      state.candidates.forEach((m) => { state.selected[m.gguf_path] = false; m.selected = false; });
      renderSelectResult(); updateSelectedCount();
    });
    $('toConfig').addEventListener('click', () => { location.hash = '#config'; });
    $('portCheckBtn').addEventListener('click', doPortCheck);
    $('startBtn').addEventListener('click', () => startTask(false));
    const qb = $('quickTestBtn');
    if (qb) qb.addEventListener('click', () => startTask(true));
    $('abortBtn').addEventListener('click', doAbort);
    $('reloadReports').addEventListener('click', loadReports);
    const of = $('openFolderBtn');
    if (of) of.addEventListener('click', openReportFolder);
    window.addEventListener('hashchange', showView);
  }

  document.addEventListener('DOMContentLoaded', () => {
    buildChips();
    bind();
    showView();
    renderScanResult();
    renderSelectResult();
    waitForBackend();
    refreshRunnerMode();
  });
})();

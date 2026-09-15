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
    const hash = (location.hash || '#status').replace('#', '');
    const known = ['status', 'scan', 'select', 'config', 'progress', 'report'];
    return known.indexOf(hash) >= 0 ? hash : 'status';
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

  // ---- ① 状态页 ----
  async function checkHealth() {
    try {
      const data = await API.health();
      $('healthDot').className = 'dot dot-ok';
      $('healthText').textContent = '后端已连接 (' + location.origin + ')';
      $('pyVersion').textContent = data.python_version + (data.python_version >= '3.11' ? ' ✓' : ' ✗（需 3.11+）');
      $('llamaFound').textContent = data.llama_server_found ? '已配置' : '未配置（将使用 mock）';
      $('toolVersion').textContent = 'v' + data.version;
      return true;
    } catch (e) {
      $('healthDot').className = 'dot dot-wait';
      $('healthText').textContent = '正在启动后端…';
      return false;
    }
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
    } catch (e) { /* 后端未就绪时忽略 */ }
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
  async function startTask() {
    const models = selectedModels();
    if (!models.length) { alert('请至少勾选 1 个模型'); return; }
    if (state.busy) { alert('已有任务在运行'); return; }
    const cfg = collectConfig();
    if (!cfg.ctx_levels.length || !cfg.input_levels.length) { alert('请至少各勾选 1 个档位'); return; }

    try {
      await API.putConfig(cfg);
      const preview = await API.preview(models, cfg);
      updateCombo();
      $('comboCount').textContent = preview.matrix.total;
      $('comboTotal').textContent = preview.total_points;

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
    await loadReports();
    if (state.autoOpen) {
      location.hash = '#report';
      setReportFrame('/reports/overview.html');
    }
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

  // ---- 初始化 ----
  function bind() {
    document.querySelectorAll('[data-goto]').forEach((el) => {
      el.addEventListener('click', () => { location.hash = el.getAttribute('data-goto'); });
    });
    $('scanBtn').addEventListener('click', doScan);
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
    $('startBtn').addEventListener('click', startTask);
    $('abortBtn').addEventListener('click', doAbort);
    $('reloadReports').addEventListener('click', loadReports);
    window.addEventListener('hashchange', showView);
  }

  document.addEventListener('DOMContentLoaded', () => {
    buildChips();
    bind();
    showView();
    renderScanResult();
    renderSelectResult();
    waitForBackend();
  });
})();

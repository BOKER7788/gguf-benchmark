"""报告模板：黄金样本 ``<style>`` 常量、客户端 JS 常量（含新增排序）、页面骨架。

所有产物均为零 CDN、单文件自包含（内联 CSS/JS/SVG）。
"""

from __future__ import annotations

import json
from html import escape

from .. import AUTHOR
from ..models import BenchConfig, BenchmarkPoint, HardwareInfo, ModelMeta
from ..runners import resolve_runner_mode
from .chart import render_chart_svg

# ---------------------------------------------------------------------------
# CSS：复用黄金样本 :root 变量与全部类（原样拷贝 + 少量新增）
# ---------------------------------------------------------------------------
CSS = """
:root {
  --bg: #1a1a2e;
  --card-bg: #16213e;
  --border: #2a2a4a;
  --text: #e0e0e0;
  --text-secondary: #a0a0b0;
  --accent: #00d4aa;
  --accent2: #7c83ff;
  --red: #ff6b6b;
  --green: #51cf66;
  --header-bg: #0f3460;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6;
  min-height: 100vh;
}
.header {
  background: linear-gradient(135deg, #0f3460 0%, #16213e 100%);
  padding: 2rem; text-align: center; border-bottom: 1px solid var(--border);
}
.header h1 { font-size: 1.8rem; color: var(--accent); }
.header .subtitle { color: var(--text-secondary); margin-top: 0.5rem; font-size: 0.9rem; }
.container { max-width: 1400px; margin: 0 auto; padding: 1.5rem; }
.controls {
  display: flex; flex-wrap: wrap; gap: 1rem; align-items: center;
  padding: 1rem; background: var(--card-bg); border-radius: 8px;
  margin-bottom: 1.5rem; border: 1px solid var(--border);
}
.controls label { color: var(--text-secondary); font-size: 0.85rem; margin-right: 0.3rem; }
.controls select {
  background: var(--bg); color: var(--text); border: 1px solid var(--border);
  padding: 0.4rem 0.8rem; border-radius: 4px; font-size: 0.9rem; cursor: pointer;
}
.summary { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
.summary-card {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 1rem 1.5rem; flex: 1; min-width: 180px;
}
.summary-card .label { color: var(--text-secondary); font-size: 0.8rem; }
.summary-card .value { font-size: 1.5rem; font-weight: bold; color: var(--accent); }
.table-wrapper { overflow-x: auto; }
table {
  width: 100%; border-collapse: collapse; font-size: 0.9rem;
  background: var(--card-bg); border-radius: 8px; overflow: hidden;
}
thead { background: var(--header-bg); }
th {
  padding: 0.75rem 1rem; text-align: right; color: var(--accent2);
  font-weight: 600; white-space: nowrap; border-bottom: 2px solid var(--border);
}
th:first-child { text-align: left; }
td {
  padding: 0.6rem 1rem; text-align: right; border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
td:first-child { text-align: left; font-weight: 500; }
tr:hover { background: rgba(124, 131, 255, 0.05); }
tr.failed { opacity: 0.5; }
tr.failed td { color: var(--red); }
.badge {
  display: inline-block; padding: 0.15rem 0.5rem; border-radius: 10px;
  font-size: 0.75rem; font-weight: 600;
}
.badge-pass { background: rgba(81, 207, 102, 0.15); color: var(--green); }
.badge-fail { background: rgba(255, 107, 107, 0.15); color: var(--red); }
.badge-skip { background: rgba(255, 217, 61, 0.15); color: #ffd93d; }
.section-title {
  font-size: 1.2rem; color: var(--accent); margin: 1.5rem 0 0.8rem;
  padding-bottom: 0.5rem; border-bottom: 1px solid var(--border);
}
.chart-container {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem;
  position: relative;
}
.chart-svg { width: 100%; height: auto; display: block; }
.chart-tip {
  position: absolute; pointer-events: none; display: none; z-index: 5;
  background: rgba(15, 23, 41, 0.96); border: 1px solid var(--accent2);
  border-radius: 6px; padding: 0.5rem 0.7rem; font-size: 0.78rem;
  color: var(--text); line-height: 1.5; white-space: nowrap;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45);
}
.chart-tip .tip-head { color: var(--accent); font-weight: 600; margin-bottom: 0.25rem; }
.chart-tip .tip-row { display: flex; align-items: center; gap: 0.4rem; }
.chart-tip .tip-dot {
  width: 8px; height: 8px; border-radius: 50%; flex: none; display: inline-block;
}
.chart-tip .tip-val { color: var(--accent2); font-weight: 600; margin-left: 0.6rem; }
.footer {
  text-align: center; padding: 2rem; color: var(--text-secondary);
  font-size: 0.8rem; border-top: 1px solid var(--border); margin-top: 2rem;
}
.model-section { margin-bottom: 2rem; }
.intro {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 1rem 1.5rem; margin-bottom: 1.5rem;
}
.intro summary {
  cursor: pointer; color: var(--accent); font-weight: 600; font-size: 1.05rem;
  list-style: none; padding: 0.2rem 0;
}
.intro summary::-webkit-details-marker { display: none; }
.intro summary::before { content: '\u25b8 '; }
.intro[open] summary::before { content: '\u25be '; }
.intro .intro-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 0.8rem 1.5rem; margin-top: 1rem;
}
.intro .intro-item { font-size: 0.88rem; }
.intro .intro-item b { color: var(--accent2); }
.intro .intro-item span { color: var(--text-secondary); }
.intro-caption { color: var(--text-secondary); font-size: 0.82rem; margin-top: 0.9rem; }
.oom-banner {
  background: rgba(255, 107, 107, 0.12); border: 1px solid var(--red);
  color: var(--red); padding: 0.75rem 1rem; border-radius: 8px;
  margin-bottom: 1.5rem; font-size: 0.9rem;
}
.mock-banner {
  background: rgba(124, 131, 255, 0.14); border: 1px solid var(--accent2);
  color: #c9cdff; padding: 0.75rem 1rem; border-radius: 8px;
  margin-bottom: 1.5rem; font-size: 0.92rem; line-height: 1.7;
}
.mock-banner code {
  background: rgba(0, 0, 0, 0.3); padding: 0.1rem 0.35rem; border-radius: 4px;
}
.hardware {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; padding: 1rem 1.5rem; margin-bottom: 1.5rem;
}
.hardware h2 { font-size: 1.05rem; color: var(--accent); margin-bottom: 0.6rem; }
.hardware .hw-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0.4rem 1.2rem; font-size: 0.88rem;
}
.hardware .hw-item b { color: var(--accent2); }
.launch-params { margin-top: 0.9rem; }
.launch-params .lp-title { color: var(--accent2); font-weight: 600; font-size: 0.9rem; }
.launch-params code {
  display: block; background: #0f1729; color: var(--text-secondary);
  padding: 0.35rem 0.6rem; border-radius: 4px; margin: 0.25rem 0;
  font-size: 0.8rem; white-space: pre-wrap; word-break: break-all;
}
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--accent); }
@media (max-width: 768px) {
  .controls { flex-direction: column; align-items: flex-start; }
  .summary { flex-direction: column; }
}
"""

# ---------------------------------------------------------------------------
# 客户端 JS（逐字复用黄金样本 + 3 处增强：精度/芯片列、表头排序、失败原因徽章）
# ---------------------------------------------------------------------------
CLIENT_JS = """
// ---- 排序状态 ----
let sortKey = null, sortDir = 1;
const SORT_MAP = {
  ctx:       { field: 'ctx_size',        type: 'num' },
  input:     { field: 'input_tokens',    type: 'num' },
  prefill:   { field: 'prefill_tps',     type: 'num' },
  decode:    { field: 'decode_tps',      type: 'num' },
  ptime:     { field: 'prefill_time_ms', type: 'num' },
  dtime:     { field: 'decode_time_ms',  type: 'num' },
  vision:    { field: 'vision_fps',      type: 'num' },
  precision: { field: 'precision',       type: 'str' },
  chip:      { field: 'n_chip',          type: 'num' },
  status:    { field: 'success',         type: 'num' }
};
const FAIL_TEXT = { OOM_GPU: '显存不足(OOM)', MODEL_FAIL: '模型加载失败', TIMEOUT: '超时', OTHER: '运行失败', '': '' };

// ---- 初始化筛选器 ----
function initFilters() {
  const modelSelect = document.getElementById('modelFilter');
  const precSelect = document.getElementById('precisionFilter');
  const chipSelect = document.getElementById('chipFilter');
  const ctxSelect = document.getElementById('ctxFilter');

  MODELS.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m; opt.textContent = m;
    modelSelect.appendChild(opt);
  });

  const precs = [...new Set(DATA.map(d => d.precision))].sort();
  precs.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p; opt.textContent = p;
    precSelect.appendChild(opt);
  });

  const chips = [...new Set(DATA.map(d => d.n_chip))].sort((a,b) => a-b);
  chips.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = c + ' 芯片';
    chipSelect.appendChild(opt);
  });

  const ctxs = [...new Set(DATA.map(d => d.ctx_size))].sort((a,b) => a-b);
  ctxs.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = (c/1000) + 'K';
    ctxSelect.appendChild(opt);
  });

  modelSelect.addEventListener('change', renderAll);
  precSelect.addEventListener('change', renderAll);
  chipSelect.addEventListener('change', renderAll);
  ctxSelect.addEventListener('change', renderAll);
}

// ---- 过滤数据 ----
function getFilteredData() {
  const model = document.getElementById('modelFilter').value;
  const prec = document.getElementById('precisionFilter').value;
  const chip = document.getElementById('chipFilter').value;
  const ctx = document.getElementById('ctxFilter').value;

  return DATA.filter(d => {
    if (model !== 'all' && d.model_name !== model) return false;
    if (prec !== 'all' && d.precision !== prec) return false;
    if (chip !== 'all' && d.n_chip !== parseInt(chip)) return false;
    if (ctx !== 'all' && d.ctx_size !== parseInt(ctx)) return false;
    return true;
  });
}

// ---- 摘要卡片 ----
function renderSummary(filtered) {
  const success = filtered.filter(d => d.success);
  let maxPrefill = 0, maxDecode = 0;
  success.forEach(d => {
    if (d.prefill_tps > maxPrefill) maxPrefill = d.prefill_tps;
    if (d.decode_tps > maxDecode) maxDecode = d.decode_tps;
  });
  const passRate = filtered.length > 0 ? (success.length / filtered.length * 100).toFixed(0) : 0;

  document.getElementById('summaryCards').innerHTML = `
    <div class="summary-card"><div class="label">总数据点</div><div class="value">${filtered.length}</div></div>
    <div class="summary-card"><div class="label">成功率</div><div class="value">${passRate}%</div></div>
    <div class="summary-card"><div class="label">最高 Prefill</div><div class="value">${maxPrefill.toLocaleString()} tps</div></div>
    <div class="summary-card"><div class="label">最高 Decode</div><div class="value">${maxDecode.toLocaleString()} tps</div></div>
  `;
  document.getElementById('pointCount').textContent = filtered.length;
}

// ---- 图表 (离线 SVG, 根据筛选切换可见性) ----
function updateChartVisibility(filtered) {
  const keys = new Set(
    filtered.filter(d => d.success)
            .map(d => `${d.model_name}|${d.model_size}|${d.precision}|${d.n_chip}|${d.ctx_size}`)
  );
  document.querySelectorAll('.series-line, .series-dot').forEach(el => {
    const key = el.getAttribute('data-series');
    el.style.display = keys.has(key) ? '' : 'none';
  });
}

// ---- 状态徽章（US-07）----
function statusBadge(p) {
  if (p.skipped) return '<span class="badge badge-skip">已跳过</span>';
  if (p.success) return '<span class="badge badge-pass">OK</span>';
  const txt = FAIL_TEXT[p.fail_reason] || p.error_msg || '运行失败';
  return '<span class="badge badge-fail">' + txt + '</span>';
}

// ---- 排序 ----
function sortPoints(points) {
  if (!sortKey || !SORT_MAP[sortKey]) return points;
  const m = SORT_MAP[sortKey];
  const copy = points.slice();
  copy.sort((a, b) => {
    let av, bv;
    if (m.type === 'str') { av = String(a[m.field]); bv = String(b[m.field]); }
    else { av = Number(a[m.field] || 0); bv = Number(b[m.field] || 0); }
    if (av < bv) return -1 * sortDir;
    if (av > bv) return 1 * sortDir;
    return 0;
  });
  return copy;
}

function thCell(key, label) {
  let mark = '';
  if (sortKey === key) mark = sortDir === 1 ? ' \\u25b2' : ' \\u25bc';
  return '<th class="sortable" data-key="' + key + '">' + label + mark + '</th>';
}

// ---- 表格 ----
function renderTables(filtered) {
  const grouped = {};
  filtered.forEach(d => {
    const key = `${d.model_name}|${d.ctx_size}`;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(d);
  });

  let html = '';
  for (const [key, points] of Object.entries(grouped)) {
    const first = points[0];
    const successCount = points.filter(p => p.success).length;

    html += `<div class="model-section">`;
    html += `<div class="section-title">${first.model_name} (${first.model_size}) &mdash;
              精度: ${first.precision} | 芯片: ${first.n_chip} | Context: ${first.ctx_size.toLocaleString()} (${successCount}/${points.length} 成功)</div>`;
    html += `<div class="table-wrapper"><table><thead><tr>`;
    html += thCell('ctx', 'Ctx(k)') + thCell('input', 'Input(k)') + thCell('prefill', 'Prefill(tps)') +
            thCell('decode', 'Decode(tps)') + thCell('ptime', 'P-Time(ms)') + thCell('dtime', 'D-Time(ms)') +
            thCell('vision', 'Vision(fps)') + thCell('precision', '精度') + thCell('chip', '芯片数') +
            thCell('status', '状态');
    html += `</tr></thead><tbody>`;

    const base = points.slice().sort((a, b) => a.input_tokens - b.input_tokens);
    const ordered = sortPoints(base).filter(p => p.success)
                      .concat(sortPoints(base).filter(p => !p.success));
    for (const p of ordered) {
      const cls = p.success ? '' : ' class="failed"';
      html += `<tr${cls}>
        <td>${(p.ctx_size/1000).toFixed(0)}</td>
        <td>${(p.input_tokens/1000).toFixed(2)}</td>
        <td>${p.success ? p.prefill_tps.toLocaleString() : '-'}</td>
        <td>${p.success ? p.decode_tps.toLocaleString() : '-'}</td>
        <td>${p.success ? Math.round(p.prefill_time_ms).toLocaleString() : '-'}</td>
        <td>${p.success ? Math.round(p.decode_time_ms).toLocaleString() : '-'}</td>
        <td>${(p.vision_fps||0).toFixed(2)}</td>
        <td>${p.precision}</td>
        <td>${p.n_chip}</td>
        <td>${statusBadge(p)}</td>
      </tr>`;
    }
    html += `</tbody></table></div></div>`;
  }

  document.getElementById('tables').innerHTML = html || '<p style="color:var(--text-secondary);text-align:center;padding:2rem;">无匹配数据</p>';
  bindSort();
}

function bindSort() {
  document.querySelectorAll('#tables th.sortable').forEach(el => {
    el.addEventListener('click', () => {
      const key = el.getAttribute('data-key');
      if (sortKey === key) { sortDir = -sortDir; } else { sortKey = key; sortDir = 1; }
      renderTables(getFilteredData());
    });
  });
}

function renderAll() {
  const filtered = getFilteredData();
  renderSummary(filtered);
  renderTables(filtered);
  updateChartVisibility(filtered);
}

// ---- 曲线悬停提示：鼠标在图上滑动即显示该档位的数值标签 ----
var VIEW_W = 1180, VIEW_H = 380, PLOT_X0 = 70, PLOT_X1 = 1150, PLOT_Y0 = 40, PLOT_Y1 = 320;

function _collectVisibleDots(svg) {
  const out = [];
  if (!svg.querySelectorAll) return out;
  const all = svg.querySelectorAll('.series-dot');
  Array.prototype.forEach.call(all, function (d) {
    if (d.style && d.style.display === 'none') return;
    const x = parseFloat(d.getAttribute('data-x'));
    const y = parseFloat(d.getAttribute('data-y'));
    if (isNaN(x) || isNaN(y)) return;
    out.push({
      x: x, y: y,
      val: parseFloat(d.getAttribute('data-val')) || 0,
      input: parseFloat(d.getAttribute('data-in')) || 0,
      ctx: parseFloat(d.getAttribute('data-ctx')) || 0,
      model: d.getAttribute('data-model') || '',
      color: d.getAttribute('data-color') || '#00d4aa'
    });
  });
  return out;
}

function initChartTooltips() {
  if (typeof document.querySelectorAll !== 'function' || typeof document.createElement !== 'function') return;
  const svgs = document.querySelectorAll('.chart-svg');
  if (!svgs || !svgs.length) return;
  Array.prototype.forEach.call(svgs, function (svg) {
    const container = svg.parentNode;
    if (!container || typeof container.appendChild !== 'function' || !svg.querySelector) return;
    const hit = svg.querySelector('.chart-hit');
    const cross = svg.querySelector('.chart-crosshair');
    if (!hit || typeof hit.addEventListener !== 'function') return;

    const tip = document.createElement('div');
    tip.className = 'chart-tip';
    container.appendChild(tip);

    function hide() {
      tip.style.display = 'none';
      if (cross) cross.style.display = 'none';
    }

    function onMove(ev) {
      if (!svg.getBoundingClientRect) return;
      const rect = svg.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const svgX = (ev.clientX - rect.left) / rect.width * VIEW_W;
      const svgY = (ev.clientY - rect.top) / rect.height * VIEW_H;
      if (svgX < PLOT_X0 || svgX > PLOT_X1 || svgY < PLOT_Y0 || svgY > PLOT_Y1) { hide(); return; }

      const dots = _collectVisibleDots(svg);
      if (!dots.length) { hide(); return; }

      let targetX = null, bestDx = Infinity;
      dots.forEach(function (d) {
        const dx = Math.abs(d.x - svgX);
        if (dx < bestDx) { bestDx = dx; targetX = d.x; }
      });
      const near = dots.filter(function (d) { return Math.abs(d.x - targetX) < 6; });
      if (!near.length) { hide(); return; }

      if (cross) {
        cross.setAttribute('x1', targetX);
        cross.setAttribute('x2', targetX);
        cross.style.display = '';
      }

      near.sort(function (a, b) { return b.val - a.val; });
      const MAX_ROWS = 12;
      const shown = near.slice(0, MAX_ROWS);
      let html = '<div class="tip-head">Ctx ' + Math.round(near[0].ctx / 1000)
               + 'K · Input ' + (near[0].input / 1000) + 'k'
               + (near.length > 1 ? ' · ' + near.length + ' 条曲线' : '') + '</div>';
      shown.forEach(function (d) {
        html += '<div class="tip-row">'
             + '<span class="tip-dot" style="background:' + d.color + '"></span>'
             + '<span>' + d.model + '</span>'
             + '<span class="tip-val">' + d.val.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' tps</span>'
             + '</div>';
      });
      if (near.length > MAX_ROWS) {
        html += '<div class="tip-row" style="color:var(--text-secondary)">…以及另外 '
             + (near.length - MAX_ROWS) + ' 条（用上方筛选缩小范围）</div>';
      }
      tip.innerHTML = html;
      tip.style.display = 'block';

      // 定位：浮层挂在容器上，故必须用容器坐标（而非 SVG 坐标，两者相差容器内边距）
      const crect = (typeof container.getBoundingClientRect === 'function')
        ? container.getBoundingClientRect() : rect;
      const cx = ev.clientX - crect.left;
      const cy = ev.clientY - crect.top;
      const tw = tip.offsetWidth || 190;
      const th = tip.offsetHeight || 80;
      let left = cx + 14;
      let top = cy + 14;
      if (left + tw > crect.width) left = Math.max(4, cx - tw - 14);
      if (top + th > crect.height) top = Math.max(4, cy - th - 14);
      tip.style.left = left + 'px';
      tip.style.top = top + 'px';
    }

    hit.addEventListener('mousemove', onMove);
    hit.addEventListener('mouseleave', hide);
    if (typeof svg.addEventListener === 'function') svg.addEventListener('mouseleave', hide);
  });
}

// 离线初始化（无外部 CDN 依赖）
initFilters();
renderAll();
initChartTooltips();
"""

# intro 的 10 条参数说明（复用黄金样本）
_INTRO_ITEMS: list[tuple[str, str]] = [
    ("Input(k)", "输入 prompt 长度，单位千 token（如 4 = 4000 tokens）。本工具的核心可变测试维度之一。"),
    ("Context / ctx(k)", "模型上下文窗口（KV cache 上限），单位千 token。本次作为可变维度扫描：4/8/16/32/64/128/256K。输入超出 ctx 的点会自动跳过。"),
    ("Prefill(tps)", "首阶段把输入喂给模型的速度（tokens/秒）。越高，长 prompt 处理越快。"),
    ("Decode(tps)", "生成输出阶段的速度（tokens/秒）。决定对话/写作流畅度，是体感关键指标。"),
    ("P-Time(ms) / D-Time(ms)", "Prefill / Decode 阶段实际耗时（毫秒）。"),
    ("Vision(fps)", "VLM 视觉帧率（图像理解速度）。纯文本 LLM 无此项，显示为 0 / -。"),
    ("精度 (w8a8 / w4a8)", "权重量化配置。w8a8\u2248Q8，w4a8\u2248Q4，仅影响报告展示。"),
    ("芯片数", "参与推理的 AI 芯片 / GPU 数量。"),
    ("状态", "OK = 测试成功；加载连续失败 2 次的组合标记为「已跳过」；失败原因细分为显存不足/模型加载失败/超时/运行失败。"),
    ("中位数", "每个点预热 1 次 + 正式跑 N 次，取中位数，避免冷启动抖动。"),
]


def header_html(title: str, generated_at: str, tool_name: str, tool_version: str, llama_version: str) -> str:
    """页头。"""
    return (
        '<div class="header">'
        f"<h1>{escape(title)}</h1>"
        '<div class="subtitle">'
        f"生成时间: {escape(generated_at)} | 测试工具: {escape(tool_name)} v{escape(tool_version)} | "
        f"llama.cpp: {escape(llama_version)}"
        "</div></div>"
    )


def oom_banner_html(points: list[BenchmarkPoint]) -> str:
    """OOM 提示横幅（US-07）。存在 OOM_GPU 失败点时展示。"""
    if not any(getattr(p, "fail_reason", "") == "OOM_GPU" for p in points):
        return ""
    return (
        '<div class="oom-banner">检测到 <b>显存不足(OOM)</b> 失败：请检查 BIOS 中 '
        "UMA 显存划分（Graphics / iGPU Memory）是否充足，或降低模型的上下文档位后重试。</div>"
    )


def intro_html(cfg: BenchConfig) -> str:
    """可展开/收起的参数说明区块。"""
    items = "".join(
        f'<div class="intro-item"><b>{escape(name)}</b><br><span>{escape(desc)}</span></div>'
        for name, desc in _INTRO_ITEMS
    )
    caption = (
        f'<div class="intro-caption">测试规模：ctx 档位 {cfg.ctx_levels}，input 档位 {cfg.input_levels}；'
        f"仅保留 input &lt; ctx 的组合。每点预热 {cfg.warmup_runs} 次 + 正式 {cfg.repeat_runs} 次取中位数；"
        f"Decode 输出长度 {cfg.output_tokens} token；跳过硬阈值 {cfg.skip_after_fails} 次连续失败。</div>"
    )
    return (
        '<details class="intro" open>'
        "<summary>参数说明（点击展开 / 收起）</summary>"
        f'<div class="intro-grid">{items}</div>{caption}</details>'
    )


def controls_html() -> str:
    """4 个下拉筛选控件 + 数据点计数。"""
    return (
        '<div class="controls">'
        '<div><label>模型:</label><select id="modelFilter"><option value="all">全部模型</option></select></div>'
        '<div><label>精度:</label><select id="precisionFilter"><option value="all">全部</option></select></div>'
        '<div><label>芯片数:</label><select id="chipFilter"><option value="all">全部</option></select></div>'
        '<div><label>上下文(ctx):</label><select id="ctxFilter"><option value="all">全部</option></select></div>'
        '<div style="margin-left: auto; color: var(--text-secondary); font-size: 0.85rem;">'
        '数据点: <span id="pointCount">0</span></div>'
        "</div>"
    )


def chart_container(svg: str) -> str:
    """曲线图容器。"""
    return f'<div class="chart-container">{svg}</div>'


def hardware_html(
    hw: HardwareInfo,
    launch_cmds: dict[int, list[str]],
    tool_name: str,
    tool_version: str,
    llama_version: str,
) -> str:
    """硬件信息区块 + 每档启动参数留档（决策 10）。"""
    items = [
        ("CPU 型号", hw.cpu_model or "Unknown"),
        ("主机型号", hw.host_model or "Unknown"),
        ("内存大小", f"{hw.ram_gb} GB" if hw.ram_gb else "未知"),
        ("系统版本", hw.os_version or "未知"),
        ("GPU", hw.gpu or "未知"),
        ("后端口", hw.gpu_backend or "未知"),
    ]
    if hw.uma_vram_gb:
        items.append(("UMA 显存", f"{hw.uma_vram_gb} GB"))
    grid = "".join(
        f'<div class="hw-item"><b>{escape(k)}</b>: {escape(str(v))}</div>' for k, v in items
    )

    param_lines = ""
    for ctx in sorted(launch_cmds.keys()):
        cmd = " ".join(launch_cmds[ctx])
        param_lines += f'<code>ctx={ctx}: {escape(cmd)}</code>'
    if not param_lines:
        param_lines = '<code>（无启动参数记录）</code>'

    return (
        '<div class="hardware">'
        "<h2>硬件信息与启动参数</h2>"
        f'<div class="hw-grid">{grid}</div>'
        '<div class="launch-params">'
        '<div class="lp-title">启动参数（可复现）</div>'
        f"{param_lines}"
        f'<div class="hw-item" style="margin-top:0.6rem;"><b>工具</b>: {escape(tool_name)} v{escape(tool_version)} '
        f'&nbsp;|&nbsp; <b>llama.cpp</b>: {escape(llama_version)}</div>'
        "</div></div>"
    )


def footer_html() -> str:
    """页脚（含作者署名）。

    刻意不写入项目 URL：报告要保持「除 SVG 命名空间外不含任何外部 URL」
    这一**可 grep 验证**的强保证，便于离线分发与审计。
    """
    return (
        '<div class="footer">'
        f"GGUF Benchmark &mdash; by {escape(AUTHOR)}<br>"
        "完全离线、零 CDN 单文件报告。数据由本机 llama.cpp 后端实测。"
        "</div>"
    )


def mock_banner_html(cfg: BenchConfig) -> str:
    """mock 模式警示条（P0-8）。

    ``auto`` 在找不到 llama-server 时会静默降级到 mock。若不显式警示，
    用户会把合成数据当成自己机器的真实性能 —— 这是代价最大的误解。
    """
    if resolve_runner_mode(cfg) != "mock":
        return ""
    return (
        '<div class="mock-banner">'
        "<b>⚠️ 本次报告是模拟数据（mock），不代表真机性能。</b><br>"
        "未检测到可用的 llama-server，本次没有调用真实推理，"
        "表中的 tps 与耗时均为合成值，仅用于验证流程与报告样式。<br>"
        "要获得真实数据：在工具「参数配置」里填入 <code>llama-server.exe</code> 路径后重新运行。"
        "</div>"
    )


def how_to_read_html(points: list[BenchmarkPoint]) -> str:
    """报告顶部「这份报告怎么看」结论层（P1-4）。"""
    ok = [p for p in points if getattr(p, "success", False)]
    if not ok:
        return (
            '<div class="intro" style="border-color:var(--red)">'
            '<div style="color:var(--red);font-weight:600;margin-bottom:.5rem">'
            "本次没有任何成功的数据点</div>"
            '<div class="intro-item"><span>常见原因：模型文件不完整、llama-server 路径不对、'
            "或显存不足。请查看下方汇总表中的失败原因列。</span></div></div>"
        )

    best_prefill = max(ok, key=lambda p: p.prefill_tps or 0)
    # 最大 ctx 且成功的点，用于给出「可用上限」结论
    max_ctx_ok = max(ok, key=lambda p: p.ctx_size)
    oom = [p for p in points if (getattr(p, "fail_reason", "") or "") == "OOM_GPU"]
    vision = any((p.vision_fps or 0) > 0 for p in ok)

    lines = [
        ("Prefill 越高越好", "它是把输入喂进模型的速度，决定长提示词的等待时间。"),
        ("Decode 曲线越平越好", "曲线越平说明长上下文下生成速度衰减越小。"),
        ("绿色 OK 失败为红色", "红色行代表该组合未跑通；点开「状态」列可看具体原因。"),
    ]
    facts = [
        f"最高 Prefill：{best_prefill.prefill_tps:,.0f} tps"
        f"（ctx={best_prefill.ctx_size // 1000}K, input={best_prefill.input_tokens / 1000:g}k）",
        f"成功跑通的最大上下文档位：{max_ctx_ok.ctx_size // 1000}K",
    ]
    if not vision:
        facts.append("本报告未包含视觉（VLM）数据，Vision 列显示 0 / -")

    items = "".join(
        f'<div class="intro-item"><b>{escape(t)}</b><br><span>{escape(d)}</span></div>'
        for t, d in lines
    )
    fact_items = "".join(
        f'<div class="intro-item"><span style="color:var(--accent)">{escape(f)}</span></div>'
        for f in facts
    )
    oom_html = ""
    if oom:
        oom_html = (
            '<div class="intro-item" style="grid-column:1/-1">'
            f'<b style="color:var(--red)">检测到 {len(oom)} 个显存不足（OOM）数据点</b><br>'
            "<span>建议：调低上下文档位、换更小的量化版本，或在 BIOS 中为核显划分更多显存后重测。</span></div>"
        )
    return (
        '<details class="intro" open><summary>这份报告怎么看（点击展开 / 收起）</summary>'
        f'<div class="intro-grid">{items}{fact_items}{oom_html}</div></details>'
    )


def _serialize_points(points: list[BenchmarkPoint]) -> str:
    """把数据点序列化为可安全内联进 ``<script>`` 的 JSON。"""
    data = [p.model_dump() for p in points]
    text = json.dumps(data, ensure_ascii=False)
    return text.replace("<", "\\u003c")


def render_report_html(
    *,
    kind: str,
    title: str,
    generated_at: str,
    models: list[ModelMeta],
    points: list[BenchmarkPoint],
    hw: HardwareInfo,
    cfg: BenchConfig,
    launch_cmds: dict[int, list[str]],
    tool_name: str,
    tool_version: str,
    llama_version: str,
) -> str:
    """组装单文件自包含 HTML 报告。

    Args:
        kind: ``"model"`` 或 ``"overview"``。
        title: 报告标题。
        generated_at: 生成时间字符串。
        models: 参与模型元信息。
        points: 数据点（单模型页=该模型点；总览页=全部点）。
        hw: 硬件信息。
        cfg: 配置。
        launch_cmds: 每档 ctx 启动参数（单模型页使用）。
        tool_name / tool_version / llama_version: 版本信息。
    """
    model_names = sorted({m.model_name for m in models})
    if not model_names:
        model_names = sorted({p.model_name for p in points})

    parts: list[str] = []
    parts.append(
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
    )
    parts.append(header_html(title, generated_at, tool_name, tool_version, llama_version))
    parts.append('<div class="container">')
    parts.append(mock_banner_html(cfg))
    parts.append(oom_banner_html(points))
    parts.append(how_to_read_html(points))
    parts.append(intro_html(cfg))
    parts.append(controls_html())
    parts.append('<div class="summary" id="summaryCards"></div>')
    parts.append(chart_container(render_chart_svg(points, "prefill")))
    parts.append(chart_container(render_chart_svg(points, "decode")))
    parts.append('<div id="tables"></div>')
    parts.append(
        hardware_html(hw, launch_cmds, tool_name, tool_version, llama_version)
    )
    parts.append("</div>")  # container
    parts.append(footer_html())
    parts.append(
        "<script>const DATA=" + _serialize_points(points)
        + "; const MODELS=" + json.dumps(model_names, ensure_ascii=False)
        + ";\n" + CLIENT_JS + "\n</script></body></html>"
    )
    return "".join(parts)


__all__ = [
    "CSS",
    "CLIENT_JS",
    "render_report_html",
    "header_html",
    "intro_html",
    "controls_html",
    "chart_container",
    "hardware_html",
    "footer_html",
    "oom_banner_html",
]

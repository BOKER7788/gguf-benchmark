// 前端(报告客户端 JS)逻辑单元验证 harness（Node，无第三方依赖）。
// 用法: node frontend_harness.js <overview.html>
// 输出: 单行 JSON，供 test_E_frontend.py 断言。
'use strict';
const fs = require('fs');

const file = process.argv[2];
const html = fs.readFileSync(file, 'utf8');

// 提取 const DATA=[...]; const MODELS=[...];
const dataMatch = html.match(/const DATA=(.*?); const MODELS=/s);
const modelsMatch = html.match(/const MODELS=(.*?);\n/s);
const DATA = JSON.parse(dataMatch[1]);
let MODELS = [];
try { MODELS = JSON.parse(modelsMatch[1]); } catch (e) { MODELS = [...new Set(DATA.map(d => d.model_name))]; }

// 提取内嵌 CLIENT_JS（DATA/MODELS 之后的 <script> 主体）
const scriptBody = html.slice(html.indexOf('const MODELS=') + ('const MODELS=' + modelsMatch[1] + ';\n').length,
                              html.lastIndexOf('</script>'));

// ---- DOM stub ----
function mkEl(id) {
  return {
    id, value: 'all', innerHTML: '', textContent: '', className: '', checked: true, disabled: false,
    style: {}, children: [], _listeners: {},
    appendChild(c) { this.children.push(c); },
    addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); },
    getAttribute() { return null; }, setAttribute() {},
  };
}
const els = {};
function getEl(id) { if (!els[id]) els[id] = mkEl(id); return els[id]; }
const headerEls = [];
const seriesEls = [...new Set(DATA.map(d => `${d.model_name}|${d.model_size}|${d.precision}|${d.n_chip}|${d.ctx_size}`))]
  .map(k => { const e = mkEl(null); e.getAttribute = () => k; e._key = k; return e; });

global.document = {
  getElementById: getEl,
  createElement: () => mkEl(null),
  querySelectorAll: (sel) => {
    if (sel.indexOf('series') >= 0) return seriesEls;
    if (sel.indexOf('sortable') >= 0) return headerEls;
    return [];
  },
  addEventListener() {},
};
global.window = global;
global.location = { hash: '', origin: 'http://127.0.0.1:8765' };

// ---- 执行 CLIENT_JS ----
const fn = new Function('DATA', 'MODELS', 'document', 'window', 'location', scriptBody + `
  return { SORT_MAP, sortPoints, getFilteredData, renderSummary, renderTables, updateChartVisibility,
           setSort: (k,d)=>{ sortKey=k; sortDir=d; } };
`);
const api = fn(DATA, MODELS, global.document, global.window, global.location);

const out = {};

// E1: SORT_MAP keys
out.sortMapKeys = Object.keys(api.SORT_MAP);
out.sortFieldMap = {};
Object.keys(api.SORT_MAP).forEach(k => { out.sortFieldMap[k] = api.SORT_MAP[k].field; });

// E-chart visibility —— 在原始（未改动）DATA 上验证曲线随“按模型筛选”显隐
const realModel = (MODELS && MODELS.length) ? MODELS[0] : null;
out.seriesTotal = seriesEls.length;
getEl('modelFilter').value = 'all';
api.updateChartVisibility(api.getFilteredData());
out.seriesVisibleAll = seriesEls.filter(e => (e.style.display || '') !== 'none').length;
if (realModel) {
  getEl('modelFilter').value = realModel;
  api.updateChartVisibility(api.getFilteredData());
  out.seriesVisibleOneModel = seriesEls.filter(e => (e.style.display || '') !== 'none').length;
  out.oneModel = realModel;
}
getEl('modelFilter').value = 'all';

// E2/E3: 受控数据集上验证每列排序结果
const testPts = [
  { model_name: 'A', model_size: '2B', precision: 'w8a8', n_chip: 1, ctx_size: 8000, input_tokens: 4000,
    prefill_tps: 100, decode_tps: 50, prefill_time_ms: 5, decode_time_ms: 6, vision_fps: 0.0, success: true, fail_reason: '' },
  { model_name: 'A', model_size: '2B', precision: 'w4a8', n_chip: 4, ctx_size: 8000, input_tokens: 250,
    prefill_tps: 300, decode_tps: 20, prefill_time_ms: 9, decode_time_ms: 2, vision_fps: 0.0, success: true, fail_reason: '' },
  { model_name: 'A', model_size: '2B', precision: 'w8a8', n_chip: 2, ctx_size: 4000, input_tokens: 1000,
    prefill_tps: 200, decode_tps: 80, prefill_time_ms: 1, decode_time_ms: 8, vision_fps: 0.0, success: true, fail_reason: '' },
];
out.sortedBy = {};
Object.keys(api.SORT_MAP).forEach(k => {
  api.setSort(k, 1);
  out.sortedBy[k] = api.sortPoints(testPts).map(p => p[api.SORT_MAP[k].field]);
});
// status 列：混合成功/失败时的排序
api.setSort('status', 1);
out.statusSortAsc = api.sortPoints([{ success: false }, { success: true }, { success: false }]).map(p => p.success);

// E: 失败点恒排末尾 —— 受控渲染
DATA.length = 0;
const good = { model_name: 'Z', model_size: '2B', precision: 'w8a8', n_chip: 1, ctx_size: 8000, input_tokens: 250,
  prefill_tps: 9999, decode_tps: 100, prefill_time_ms: 1, decode_time_ms: 1, vision_fps: 0.0, success: true, fail_reason: '' };
const bad = { model_name: 'Z', model_size: '2B', precision: 'w8a8', n_chip: 1, ctx_size: 8000, input_tokens: 4000,
  prefill_tps: 0, decode_tps: 0, prefill_time_ms: 0, decode_time_ms: 0, vision_fps: 0.0, success: false, fail_reason: 'OOM_GPU' };
DATA.push(bad, good); // 故意让失败点先入队
api.setSort('prefill', 1); // 升序（失败值=0 会排最前，但应被强制置尾）
getEl('tables').innerHTML = '';
api.renderTables(api.getFilteredData());
const tblHtml = getEl('tables').innerHTML;
out.failedLast = /<tr class="failed">[\s\S]*<\/tr>\s*<\/tbody>/.test(tblHtml);
out.renderHasTenHeaders = (tblHtml.match(/<th class="sortable"/g) || []).length;
out.renderHeaderLabels = [...tblHtml.matchAll(/<th class="sortable"[^>]*>([^<\n]+)</g)].map(m => m[1].trim());
out.renderStatusHasOOM = tblHtml.indexOf('显存不足(OOM)') >= 0;

// E-summary: 摘要卡（2 点，1 成功 → 成功率 50%，最高 prefill 9999）
getEl('summaryCards').innerHTML = '';
api.renderSummary(api.getFilteredData());
out.summaryHtml = getEl('summaryCards').innerHTML;
out.pointCount = getEl('pointCount').textContent;

// E-filter: 多模型数据 + 按模型筛选
DATA.length = 0;
for (let m = 0; m < 3; m++) {
  for (let c = 0; c < 4; c++) {
    DATA.push({ model_name: 'M' + m, model_size: '2B', precision: 'w8a8', n_chip: 1, ctx_size: 4000,
      input_tokens: 250 + c * 250, prefill_tps: 100 + m * 10 + c, decode_tps: 50, prefill_time_ms: 1,
      decode_time_ms: 1, vision_fps: 0.0, success: true, fail_reason: '' });
  }
}
getEl('modelFilter').value = 'M1';
out.filteredForM1 = api.getFilteredData().length;
getEl('modelFilter').value = 'all';
out.filteredAll = api.getFilteredData().length;

// E precision filter
getEl('precisionFilter').value = 'w4a8';
out.filteredW4a8 = api.getFilteredData().length; // 数据全为 w8a8 → 0

console.log(JSON.stringify(out));

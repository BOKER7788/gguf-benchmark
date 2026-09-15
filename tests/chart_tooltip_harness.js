// 曲线悬停提示（tooltip）真实行为验证 harness（Node，零第三方依赖）。
//
// 与 frontend_harness.js 不同：本 harness 会**真实驱动** mousemove 事件，
// 用从生成的 HTML 里解析出的真实 <circle class="series-dot"> 坐标做寻点，
// 再断言浮层内容 / 十字准线位置 / 边界翻转 / 隐藏 series 不参与。
//
// 两张曲线图（Prefill / Decode）**分别隔离**，避免点位串图。
//
// 用法: node chart_tooltip_harness.js <report.html>
// 输出: 单行 JSON，供 test_H_tooltip.py 断言。
'use strict';
const fs = require('fs');

const html = fs.readFileSync(process.argv[2], 'utf8');
const dataMatch = html.match(/const DATA=(.*?); const MODELS=/s);
const modelsMatch = html.match(/const MODELS=(.*?);\n/s);
const DATA = JSON.parse(dataMatch[1]);
const MODELS = JSON.parse(modelsMatch[1]);
const scriptBody = html.slice(
  html.indexOf('const MODELS=') + ('const MODELS=' + modelsMatch[1] + ';\n').length,
  html.lastIndexOf('</script>')
);

// ---- 把 HTML 按 <svg>...</svg> 切成独立图表块 ----
function svgBlocks(source) {
  const blocks = [];
  let i = 0;
  while ((i = source.indexOf('<svg', i)) !== -1) {
    const end = source.indexOf('</svg>', i);
    if (end === -1) break;
    blocks.push(source.slice(i, end + 6));
    i = end + 6;
  }
  return blocks;
}

function parseDots(svgChunk) {
  const re = /<circle class="series-dot"([^>]*)>/g;
  const list = [];
  let m;
  while ((m = re.exec(svgChunk)) !== null) {
    const attrs = {};
    const aRe = /([\w-]+)="([^"]*)"/g;
    let a;
    while ((a = aRe.exec(m[1])) !== null) attrs[a[1]] = a[2];
    list.push(attrs);
  }
  return list;
}

const blocks = svgBlocks(html);
const perChartDots = blocks.map(parseDots);

// ---- DOM stub ----
const VIEW = { left: 0, top: 0, width: 1180, height: 380 };

function mkDot(attrs) {
  return {
    _attrs: attrs, style: {},
    getAttribute(k) { return this._attrs[k] === undefined ? null : this._attrs[k]; },
    setAttribute(k, v) { this._attrs[k] = v; },
    addEventListener() {},
    querySelectorAll() { return []; },
  };
}
function mkTip() {
  return {
    style: { display: 'none' }, className: '', innerHTML: '',
    offsetWidth: 190, offsetHeight: 90,
    appendChild() {}, addEventListener() {}, getAttribute() { return null; }, setAttribute() {},
  };
}
function mkCrosshair() {
  return {
    _attrs: { x1: '70', x2: '70' }, style: { display: 'none' }, _listeners: {},
    getAttribute(k) { return this._attrs[k] === undefined ? null : this._attrs[k]; },
    setAttribute(k, v) { this._attrs[k] = v; },
    addEventListener() {}, appendChild() {}, querySelectorAll() { return []; },
  };
}

const charts = perChartDots.map((raw, idx) => {
  const dots = raw.map(mkDot);
  const hit = {
    style: {}, _listeners: {},
    addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); },
    fire(ev, arg) { (this._listeners[ev] || []).forEach((f) => f(arg)); },
    getAttribute() { return null; }, setAttribute() {}, appendChild() {}, querySelectorAll() { return []; },
  };
  const cross = mkCrosshair();
  const tip = mkTip();
  const container = { _appended: null, appendChild(el) { this._appended = el; } };
  const svg = {
    style: {}, _listeners: {}, parentNode: container,
    querySelector(sel) {
      if (sel === '.chart-hit') return hit;
      if (sel === '.chart-crosshair') return cross;
      return null;
    },
    querySelectorAll(sel) { return sel === '.series-dot' ? dots : []; },
    getBoundingClientRect() { return VIEW; },
    addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); },
    getAttribute() { return null; }, setAttribute() {}, appendChild() {},
  };
  return { idx, raw, dots, hit, cross, tip, container, svg, _tipCreated: null };
});

const els = {};
function mkEl(id) {
  return {
    id, value: 'all', innerHTML: '', textContent: '', className: '', style: {}, children: [],
    appendChild() {}, addEventListener() {}, getAttribute() { return null; }, setAttribute() {},
  };
}
function getEl(id) { if (!els[id]) els[id] = mkEl(id); return els[id]; }

let createdTips = [];
global.document = {
  getElementById: getEl,
  createElement() { const t = mkTip(); createdTips.push(t); return t; },
  querySelectorAll(sel) { return sel === '.chart-svg' ? charts.map((c) => c.svg) : []; },
  addEventListener() {},
};
global.window = global;
global.location = { hash: '', origin: 'http://127.0.0.1:8765' };

const fn = new Function('DATA', 'MODELS', 'document', 'window', 'location', scriptBody + `
  return { initChartTooltips, updateChartVisibility, getFilteredData };
`);
const api = fn(DATA, MODELS, global.document, global.window, global.location);

// initFilters() 也会调用 createElement('option')，因此重跑一次初始化并清空捕获，
// 这样 createdTips 里就只剩各图表的提示浮层。
createdTips = [];
api.initChartTooltips();
charts.forEach((c, i) => { c.tip = createdTips[i] || c.tip; c.container._appended = c.tip; });

const out = {};
out.chartCount = charts.length;
out.dotsPerChart = charts.map((c) => c.raw.length);
out.tipCreatedPerChart = createdTips.length;
out.hitHasMoveListener = charts.map((c) => (c.hit._listeners.mousemove || []).length > 0);

// ================= 在图表 0（Prefill）上做行为验证 =================
const C = charts[0];
const t = C.raw[Math.min(4, C.raw.length - 1)];
out.targetModel = t['data-model'];
out.targetVal = parseFloat(t['data-val']);
out.targetInputK = parseFloat(t['data-in']) / 1000;

function move(clientX, clientY) { C.hit.fire('mousemove', { clientX, clientY }); }
function rows(htmlStr) { return (htmlStr.match(/class="tip-row"/g) || []).length; }
function valTokens() {
  return (C.tip.innerHTML.match(/tip-val">([^<]*)</g) || []).map((s) => s.replace(/^tip-val">/, '').replace(/<$/, ''));
}

// ---- H1 悬停命中：浮层显示 + 含目标模型与数值 + 十字准线对齐 ----
move(parseFloat(t['data-x']), parseFloat(t['data-y']));
out.tipDisplayAfterMove = C.tip.style.display;
out.tipHasModel = C.tip.innerHTML.indexOf(out.targetModel) >= 0;
out.tipHasHead = /Ctx \d+K · Input [\d.]+k/.test(C.tip.innerHTML);
out.crosshairVisible = C.cross.style.display !== 'none';
out.crosshairAligned = Math.abs(parseFloat(C.cross._attrs.x1) - parseFloat(t['data-x'])) < 0.5;
out.tipFollowsCursor = parseFloat(C.tip.style.left) > parseFloat(t['data-x']) * 0.02;

// ---- H2 行数上限（同 x 档位 series 很多时不得无限增长）----
const sameX = C.raw.filter((d) => Math.abs(parseFloat(d['data-x']) - parseFloat(t['data-x'])) < 6);
out.seriesAtSameX = sameX.length;
out.rowCount = rows(C.tip.innerHTML);
out.rowCountRespectsCap = out.rowCount <= 12 || out.rowCount <= sameX.length;
out.hasOverflowNote = C.tip.innerHTML.indexOf('以及另外') >= 0;

// ---- H3 绘图区外 → 隐藏 ----
move(5, 5);
out.hiddenOutsidePlot = C.tip.style.display === 'none';

// ---- H4 右边缘翻转 ----
move(1148, 60);
out.flippedAtRightEdge = parseFloat(C.tip.style.left) < 1148 - 100;

// ---- H5 mouseleave → 隐藏 ----
C.hit.fire('mouseleave', {});
out.hiddenAfterLeave = C.tip.style.display === 'none';

// ---- H6 被筛选隐藏的 series 必须从提示中消失（按 series 计数，不按模型名）----
const keepSeries = C.raw[0]['data-series'];
C.dots.forEach((d) => { if (d._attrs['data-series'] !== keepSeries) d.style.display = 'none'; });
const visibleAtX = C.raw.filter((d) => d['data-series'] === keepSeries
  && Math.abs(parseFloat(d['data-x']) - parseFloat(C.raw[0]['data-x'])) < 6).length;
move(parseFloat(C.raw[0]['data-x']), parseFloat(C.raw[0]['data-y']));
out.rowsWithOneSeriesVisible = rows(C.tip.innerHTML);
out.expectedRowsWithOneSeries = visibleAtX;
out.hiddenSeriesExcluded = out.rowsWithOneSeriesVisible === visibleAtX;

console.log(JSON.stringify(out));

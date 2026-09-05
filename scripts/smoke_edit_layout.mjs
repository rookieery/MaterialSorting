// 编辑排料端到端冒烟（prd-edit-nesting-layout US-005，2026-09-04）—— 上传→求解→
// 编辑（拖动+旋转+两形态）→保存→导出→重置 全链路回归锁死（Playwright + chrome channel；
// 范本 scripts/smoke_plt_table_preview.mjs 上传/commit/求解工具函数 +
// out/us003_browser_verify（拖动/旋转/指标）与 out/us004_browser_verify（保存/重置/导出
// 抓包）的 DOM 取证套路，全部断言走 DOM / 路由抓包，不依赖 vite store import）。
//
// 前置：ms-web 在 :8000 运行 + 新 static 构建（prod 模式）。
//
//   node scripts/smoke_edit_layout.mjs
//
// 相位：
//   S1 上传 5336 母版 → commit → 超排 3 码（32/33/34，30 片）20s 求解 → final；
//      记录基线：solver 终帧 placed_items / final.density + 主视图快照（NestLabel +
//      全部毛版 points + viewBox/fab）。
//   S2 编辑弹窗打开：完整版 5 层（毛版/净版/内部线/刺口/布纹线五类节点全可见）↔
//      毛板纯轮廓（4 工艺层全 display:none、毛版恒显）两形态断言 + 可逆切回 +
//      顶部状态条初值 = 主视图利用率（ceil 口径 ±0.02pt）+ Δ +0.00pt。
//   S3 拖动一片右移超界（+300mm → 料长增/利用率降）+ 旋转另一片（拖柄自由转角）
//      → 指标面板出现（面积/深度/角度三值 + 旋转偏离 >10°）。
//   S4 保存 → 主视图恰两片 points 重绘（被拖片 maxX 增 + 旋转片）+ NestLabel
//      利用率降/长度增 + viewBox/fab = 保存料长。
//   S5 导出 PLT 抓包：ExportInfoModal 预览行 → 确认 → POST /export 200（.plt）；
//      payload placed 与 solver 基线 diff 非空 + density 与 final.density diff 非空。
//   S6 ✕ 重开弹窗（已保存非 dirty → ✕ 直关无确认层）→ 拖片左移腾空（右缘逐片）
//      → 状态条料长缩/利用率升 → 保存 → 主视图画布随 viewBoxMaxW 收缩。
//   S7 弹窗外重置（confirm 原文案）→ 主视图全片 points/NestLabel/viewBox 回算法
//      基线 → 再导出抓包：placed 与 density 与基线 diff 回零（逐片 ε 对拍）。
//
// 报告落 out/smoke_edit_layout/report.json；退出码 0 = 全 PASS。
import { writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
const { chromium } = createRequire(
  new URL('../materialSorting-web/package.json', import.meta.url),
)('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9.dxf';
const OUT = 'D:/code/MaterialSorting/out/smoke_edit_layout';
const SIZES = [32, 33, 34]; // 5336 码集 30..40；3 码 × 10 片 = 30 片（短求解）
const SOLVE_TIME = '20';

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
const results = [];
function check(name, ok, extra = '') {
  results.push({ name, ok, extra: String(extra) });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 200) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function dismissTour(p, rounds = 6) {
  for (let i = 0; i < rounds; i++) {
    const gone = await p.evaluate(() => document.querySelector('[data-testid=tour-overlay]') === null);
    if (gone) return;
    await p.evaluate(() => {
      const btn = document.querySelector('[data-testid=tour-skip]');
      if (btn) btn.click();
    });
    await p.waitForTimeout(600);
  }
}
async function rawFetch(p, url, init = null) {
  return p.evaluate(async ({ u, i }) => {
    const r = await fetch(u, i);
    let body = null;
    try { body = await r.json(); } catch { body = null; }
    return { status: r.status, body };
  }, { u: url, i: init });
}
function frameText(f) {
  if (typeof f === 'string') return f;
  if (f && typeof f.payload === 'string') return f.payload;
  if (f && f.payload != null && typeof f.payload === 'object') return String.fromCharCode(...f.payload);
  return '';
}
const cap = { msgs: [] };
page.on('websocket', (ws) => {
  ws.on('framereceived', (f) => {
    try { cap.msgs.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
  });
});
async function waitMsg(type, timeout = 120000) {
  const t0 = Date.now();
  for (;;) {
    const m = cap.msgs.find((x) => x && x.type === type);
    if (m) return m;
    if (Date.now() - t0 > timeout) return null;
    await sleep(500);
  }
}

// ---- 通用 DOM 读取（同 out/us004_browser_verify/verify.mjs 套路） ----
/** 主视图（.nest-card svg）快照：viewBox / fab 宽 / 全部毛版 points（DOM 序 = placed 序）+ NestLabel。 */
const mainSnap = () => page.evaluate(() => {
  const svg = document.querySelector('.nest-card svg');
  const g = svg.querySelector('g');
  const fab = svg.children[1];
  return {
    viewBox: svg.getAttribute('viewBox'),
    fabW: Number(fab.getAttribute('width')),
    points: Array.from(g.querySelectorAll('polygon'))
      .filter((p) => p.getAttribute('fill-opacity') === '0.55')
      .map((p) => p.getAttribute('points')),
    label: document.querySelector('.nest-label')?.textContent || '',
  };
});
/** 弹窗状态条文本。 */
const modalStats = () => page.evaluate(() => ({
  width: document.querySelector('[data-testid=edit-layout-width]')?.textContent || '',
  density: document.querySelector('[data-testid=edit-layout-density]')?.textContent || '',
  delta: document.querySelector('[data-testid=edit-layout-delta]')?.textContent || '',
}));
const widthOf = (s) => Number((s.width.match(/([\d.]+)/) || [0, 0])[1]);
const pctOf = (s) => Number((s.density.match(/([\d.]+)%/) || [0, 0])[1]);
const labelPct = (l) => Number((l.match(/([\d.]+)%/) || [0, 0])[1]);
const labelCm = (l) => Number((l.match(/长度 ([\d.]+) cm/) || [0, 0])[1]);
/** 弹窗 svg 比尺 px/mm（meet = min(宽比, 高比)；xMinYMid 横向无 letterbox，dx 差分直除）。 */
async function editScale() {
  return page.evaluate(() => {
    const svg = document.querySelector('svg.edit-layout-svg');
    const r = svg.getBoundingClientRect();
    const vb = svg.getAttribute('viewBox').split(' ').map(Number);
    return Math.min(r.width / vb[2], r.height / vb[3]);
  });
}
/** 弹窗 5 层形态快照：五类工艺节点计数 + 各自可见（display != 'none'）计数。 */
const layerCensus = () => page.evaluate(() => {
  const g = document.querySelector('svg.edit-layout-svg g');
  const visible = (els) => Array.from(els).filter((e) => e.style.display !== 'none').length;
  const rough = g.querySelectorAll('polygon[fill-opacity="0.55"]');
  const net = g.querySelectorAll('polygon[stroke="#33cc33"]');
  const internal = g.querySelectorAll('polyline[stroke="#ff8c1a"]');
  const notch = g.querySelectorAll('line[stroke="#ffd700"]');
  const grain = g.querySelectorAll('line[stroke="#e53e3e"]');
  return {
    rough: rough.length, roughVis: visible(rough),
    net: net.length, netVis: visible(net),
    internal: internal.length, internalVis: visible(internal),
    notch: notch.length, notchVis: visible(notch),
    grain: grain.length, grainVis: visible(grain),
  };
});
/** 弹窗内全部毛版 polygon（US-003 教训：提层后 DOM 序 ≠ working 序 —— 按 points 寻址）。 */
const roughPolysEval = () => page.evaluate(() => {
  const g = document.querySelector('svg.edit-layout-svg g');
  return Array.from(g.querySelectorAll('polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55')
    .map((p) => ({ points: p.getAttribute('points') }));
});
function parsePts(str) { return (str || '').split(' ').map((t) => t.split(',').map(Number)); }
function maxXOf(pts) { return Math.max(...pts.map((p) => p[0])); }
async function hitPoint(el) {
  return el.evaluate((node) => {
    const r = node.getBoundingClientRect();
    for (const [fx, fy] of [[0.5, 0.5], [0.35, 0.5], [0.65, 0.5], [0.5, 0.35], [0.5, 0.65],
      [0.3, 0.3], [0.7, 0.7], [0.3, 0.7], [0.7, 0.3], [0.25, 0.5], [0.75, 0.5], [0.4, 0.4], [0.6, 0.6]]) {
      const x = r.x + r.width * fx;
      const y = r.y + r.height * fy;
      if (document.elementFromPoint(x, y) === node) return { x, y };
    }
    return null;
  });
}
async function dragMouse(from, dx, dy, steps = 10) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + dx, from.y + dy, { steps });
  await page.mouse.up();
}
/** 弹窗内拖「当前包络 maxX 的片」水平 dxMm（负 = 左移）；返回被拖片拖前 points 字符串。 */
async function dragMaxXPiece(dxMm) {
  const s = await editScale();
  for (let attempt = 0; attempt < 3; attempt++) {
    const polys = await roughPolysEval();
    let bestIdx = -1, bestMaxX = -Infinity;
    polys.forEach((p, i) => {
      const mx = maxXOf(parsePts(p.points));
      if (mx > bestMaxX) { bestMaxX = mx; bestIdx = i; }
    });
    const beforePoints = polys[bestIdx].points;
    const el = await page.evaluateHandle((idx) => {
      const g = document.querySelector('svg.edit-layout-svg g');
      return Array.from(g.querySelectorAll('polygon'))
        .filter((p) => p.getAttribute('fill-opacity') === '0.55')[idx];
    }, bestIdx);
    const pt = await hitPoint(el);
    if (pt) {
      await dragMouse(pt, dxMm * s, 0);
      await sleep(150);
      return beforePoints;
    }
  }
  throw new Error('dragMaxXPiece: 找不到可命中片');
}
async function openEditViaUI() {
  await page.click('[data-testid=edit-controls-edit]');
  await page.waitForSelector('[data-testid=edit-layout-overlay]', { timeout: 5000 });
}
async function waitMainLabel(expectFn, timeout = 8000) {
  const t0 = Date.now();
  let last = null;
  for (;;) {
    last = (await mainSnap()).label;
    if (expectFn(last)) return last;
    if (Date.now() - t0 > timeout) return last;
    await sleep(200);
  }
}
/** 抓一次 POST /export（真实打到后端）：返回 {status, cd, body}。 */
async function exportOnce(tag) {
  let captured = null;
  const onResp = (r) => {
    if (r.url().endsWith('/export')) captured = r;
  };
  page.on('response', onResp);
  await page.click('button.export');
  await page.waitForSelector('.export-ro-row', { timeout: 15000 });
  await page.click('[data-testid=export-info-confirm]');
  for (let i = 0; i < 60 && !captured; i++) await sleep(500);
  page.off('response', onResp);
  const cd = captured ? (captured.headers()['content-disposition'] || '') : '';
  const body = captured ? captured.request().postDataJSON() : null;
  check(tag + 'a POST /export 发出且 200（.plt 附件）',
    !!captured && captured.status() === 200 && decodeURIComponent(cd).includes('.plt'),
    captured ? captured.status() + ' ' + decodeURIComponent(cd).slice(0, 60) : 'no response');
  return body;
}
/** placed 与 solver 基线逐片对拍（id/rotation/translation ε=1mm）→ 差异片数。 */
function placedDiffCount(placed, base) {
  if (!placed || !base || placed.length !== base.length) return -1;
  let n = 0;
  placed.forEach((it, i) => {
    if (it.id !== base[i].id
      || Math.abs(it.rotation - base[i].rotation) > 1e-6
      || Math.abs(it.translation[0] - base[i].translation[0]) > 1
      || Math.abs(it.translation[1] - base[i].translation[1]) > 1) n += 1;
  });
  return n;
}

// ---------- S1 上传 5336 + commit + 短求解 ----------
await page.goto(BASE, { waitUntil: 'networkidle' });
const sid = await page.evaluate(() => localStorage.getItem('ms_sid'));
check('S0 页面加载落会话 sid', /^[0-9a-f]{32}$/.test(sid || ''), (sid || '').slice(0, 8));

await dismissTour(page);
await page.locator('input[type=file]').first().setInputFiles(DXF);
await page.waitForSelector('button.tab:not([disabled]):has-text("超排")', { timeout: 240000 });
let committed = false;
let ptypesBody = null;
for (let i = 0; i < 80; i++) {
  const r = await rawFetch(page, '/api/ptypes', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
  if (r.status === 200 && Object.keys(r.body?.representatives || {}).length > 0) {
    committed = true; ptypesBody = r.body; break;
  }
  await sleep(3000);
}
check('S1a 上传 5336 + commit 完成（ptypes 非空）', committed,
  ptypesBody ? 'labels=' + Object.keys(ptypesBody.representatives).join(',') : 'no ptypes');

await page.click('button.tab:has-text("超排")');
await sleep(800);
await dismissTour(page);
for (const sz of SIZES) await page.check('#sz_' + sz);
await page.fill('#time', SOLVE_TIME);
await page.click('#start');
const manifest = await waitMsg('manifest', 60000);
const final = await waitMsg('final', 150000);
const solverPlaced = cap.msgs.filter((x) => x && x.type === 'frame').slice(-1)[0]?.placed_items || [];
check('S1b 短求解 20s 出 final（3 码 30 片）',
  !!manifest && !!final && final.density > 0 && solverPlaced.length === 30,
  final ? 'density=' + final.density.toFixed(4) + ' width=' + Math.round(final.width_mm)
    + ' placed=' + solverPlaced.length : 'no final');

const BASE_SNAP = await mainSnap();
const BASE_PCT = labelPct(BASE_SNAP.label);
const BASE_CM = labelCm(BASE_SNAP.label);
check('S1c 主视图基线快照（NestLabel/points/viewBox）',
  BASE_SNAP.points.length === 30 && BASE_PCT > 0,
  'label="' + BASE_SNAP.label + '" viewBox=' + BASE_SNAP.viewBox);

// ---------- S2 编辑弹窗：两形态 + 状态条初值 ----------
await openEditViaUI();
const s2full = await layerCensus();
check('S2a 完整版 5 层：毛版/净版/内部线/刺口/布纹线五类节点全可见',
  s2full.rough === 30 && s2full.roughVis === 30
  && s2full.net === 30 && s2full.netVis === 30
  && s2full.internal >= 1 && s2full.internalVis === s2full.internal
  && s2full.notch >= 1 && s2full.notchVis === s2full.notch
  && s2full.grain === 30 && s2full.grainVis === 30,
  JSON.stringify(s2full));

// 视图工具优化（2026-09-05）：± 缩放按钮删除（滚轮唯一入口）、「重置视图」→「全览」、
// 形态 select 自 footer 移入左上工具区、右下新增 操作指南 卡片。
const uiShape = await page.evaluate(() => ({
  zoomIn: document.querySelector('[data-testid=edit-zoom-in]') !== null,
  zoomOut: document.querySelector('[data-testid=edit-zoom-out]') !== null,
  reset: document.querySelector('[data-testid=edit-zoom-reset]')?.textContent || '',
  modeInTools: document.querySelector(
    '.edit-layout-canvas-tools [data-testid=edit-layout-mode]') !== null,
  guide: document.querySelector('[data-testid=edit-guide]')?.textContent || '',
}));
check('S2a2 视图工具：± 已删、全览按钮 + 工具区形态 select + 操作指南卡',
  !uiShape.zoomIn && !uiShape.zoomOut && uiShape.reset.includes('全览')
  && uiShape.modeInTools && uiShape.guide.includes('滚轮'),
  'reset="' + uiShape.reset.trim() + '" guide=' + uiShape.guide.length + 'chars');

await page.selectOption('[data-testid=edit-layout-mode]', 'rough');
await sleep(300);
const s2rough = await layerCensus();
check('S2b 毛板纯轮廓：4 工艺层全 display:none、毛版恒显',
  s2rough.netVis === 0 && s2rough.internalVis === 0 && s2rough.notchVis === 0
  && s2rough.grainVis === 0 && s2rough.rough === 30 && s2rough.roughVis === 30,
  JSON.stringify(s2rough));
await page.screenshot({ path: OUT + '/s2_rough_mode.png' });

await page.selectOption('[data-testid=edit-layout-mode]', 'full');
await sleep(300);
const s2back = await layerCensus();
check('S2c 形态切换可逆（切回完整版 5 层复现）',
  s2back.netVis === 30 && s2back.grainVis === 30 && s2back.internalVis === s2back.internal,
  'net=' + s2back.netVis + ' grain=' + s2back.grainVis
    + ' internal=' + s2back.internalVis + '/' + s2back.internal);

const s2stats = await modalStats();
const S2_W = widthOf(s2stats);
// ceil 取整伪影上界 = density×(≤1mm/料长)（solver 小数料长 → ceil 后利用率微降，
// EditLayoutModal 头注释口径；标签 2dp 再留 +0.01）。
const ceilTol = (BASE_PCT * 1.0) / (BASE_CM * 10) + 0.01;
check('S2d 顶部状态条初值 = 主视图利用率（ceil 取整伪影上界内）+ Δ +0.00pt',
  Math.abs(pctOf(s2stats) - BASE_PCT) <= ceilTol
  && Math.abs(S2_W - Math.ceil(final.width_mm)) <= 1
  && s2stats.delta.includes('+0.00pt'),
  'modal=' + pctOf(s2stats) + '%/' + S2_W + 'mm vs main=' + BASE_PCT
    + '%/ceil(' + final.width_mm.toFixed(1) + ') tol=' + ceilTol.toFixed(3)
    + ' Δ=' + s2stats.delta);

// ---------- S3 拖片右移超界 + 旋转另一片 → 指标面板 ----------
await dragMaxXPiece(300); // 右移 300mm 超界 → 料长扩（右界永不钳 = 双向伸缩设计）
const s3drag = await modalStats();
const S3_W = widthOf(s3drag);
check('S3a 拖片右移超界 → 状态条料长增/利用率降',
  S3_W >= S2_W + 250 && pctOf(s3drag) < pctOf(s2stats),
  S2_W + '->' + S3_W + 'mm, ' + pctOf(s2stats).toFixed(2) + '%->' + pctOf(s3drag).toFixed(2) + '%');

// 点选另一片（DOM 首位 ≠ 被拖片 —— 被拖片提层后在末位；5336 全片带布纹线）→ 旋转
const rotEl = await page.evaluateHandle(() => {
  const g = document.querySelector('svg.edit-layout-svg g');
  return Array.from(g.querySelectorAll('polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55')[0];
});
const rotBefore = await rotEl.evaluate((n) => n.getAttribute('points'));
const rpt = await hitPoint(rotEl);
await page.mouse.move(rpt.x, rpt.y);
await page.mouse.down();
await page.mouse.up();
await sleep(150);
const hasHandle = await page.evaluate(() =>
  document.querySelector('[data-testid=edit-rotate-handle]') !== null
  && document.querySelector('[data-testid=edit-metrics]') !== null);
check('S3b 点选片 → 旋转手柄 + 指标面板出现', hasHandle);
const hb = await page.locator('[data-testid=edit-rotate-handle]').boundingBox();
const hpt = { x: hb.x + hb.width / 2, y: hb.y + hb.height / 2 };
const grainBefore = await page.evaluate(() =>
  Array.from(document.querySelectorAll('svg.edit-layout-svg g line[stroke="#e53e3e"]'))
    .map((l) => [l.getAttribute('x1'), l.getAttribute('y1'),
      l.getAttribute('x2'), l.getAttribute('y2')]).join('|'));
await page.mouse.move(hpt.x, hpt.y);
await page.mouse.down();
await page.mouse.move(hpt.x - 170, hpt.y + 90, { steps: 10 });
await page.mouse.up();
await sleep(200);
const rotAfter = await rotEl.evaluate((n) => n.getAttribute('points'));
const grainAfter = await page.evaluate(() =>
  Array.from(document.querySelectorAll('svg.edit-layout-svg g line[stroke="#e53e3e"]'))
    .map((l) => [l.getAttribute('x1'), l.getAttribute('y1'),
      l.getAttribute('x2'), l.getAttribute('y2')]).join('|'));
const metrics = await page.evaluate(() => ({
  area: document.querySelector('[data-testid=edit-metrics-area]')?.textContent || '',
  depth: document.querySelector('[data-testid=edit-metrics-depth]')?.textContent || '',
  rot: document.querySelector('[data-testid=edit-metrics-rot]')?.textContent || '',
  foot: document.querySelector('[data-testid=edit-metrics] .edit-metrics-foot')
    ?.textContent || '',
}));
const rotVal = Number((metrics.rot.match(/([\d.]+)°/) || [0, 0])[1]);
const areaVal = Number((metrics.area.match(/([\d.]+) mm/) || [0, 0])[1]);
const depthVal = Number((metrics.depth.match(/([\d.]+)/) || [0, 0])[1]);
check('S3c 拖柄旋转生效（片 points 变化 + 布纹线端点随片）',
  rotAfter !== rotBefore && grainBefore !== grainAfter);
check('S3d 指标面板三值（面积/深度/角度）+ 旋转偏离 >10° + 脚注算法碰撞口径',
  metrics.area.includes('mm²') && metrics.depth.includes('mm') && metrics.rot.includes('°')
  && rotVal > 10 && metrics.foot.includes('按算法碰撞口径'),
  'area=' + areaVal.toFixed(1) + 'mm² depth=' + depthVal.toFixed(1)
    + 'mm rot=' + rotVal.toFixed(1) + '°');
await page.screenshot({ path: OUT + '/s3_drag_rotate_metrics.png' });

// ---------- S4 保存 → 主视图同步 ----------
await page.click('[data-testid=edit-layout-save]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { state: 'detached', timeout: 5000 });
const S4_SNAP = await mainSnap();
const S4_PCT = labelPct(S4_SNAP.label);
const S4_CM = labelCm(S4_SNAP.label);
const S4_VBW = Number(S4_SNAP.viewBox.split(' ')[2]);
const changed = [];
S4_SNAP.points.forEach((p, i) => { if (p !== BASE_SNAP.points[i]) changed.push(i); });
const draggedNew = changed.filter((i) =>
  maxXOf(parsePts(S4_SNAP.points[i])) - maxXOf(parsePts(BASE_SNAP.points[i])) >= 250);
check('S4a 保存后主视图恰两片重绘（被拖片 maxX 增 + 旋转片）',
  changed.length === 2 && draggedNew.length === 1,
  'changed=[' + changed.join(',') + '] draggedNew=[' + draggedNew.join(',') + ']');
check('S4b NestLabel 利用率降 / 长度增（扩长）',
  S4_PCT < BASE_PCT && S4_CM > BASE_CM,
  BASE_PCT + '%->' + S4_PCT + '%, ' + BASE_CM + 'cm->' + S4_CM + 'cm');
check('S4c 画布随保存料长扩张（viewBox/fab = 状态条料长）',
  S4_VBW === S3_W && S4_SNAP.fabW === S3_W,
  'viewBox.w=' + S4_VBW + ' fabW=' + S4_SNAP.fabW + ' saved=' + S3_W);
await page.screenshot({ path: OUT + '/s4_after_save_main.png' });

// ---------- S5 导出 PLT 抓包（与基线 diff 非空） ----------
const exportBody1 = await exportOnce('S5');
const diffCount1 = exportBody1 ? placedDiffCount(exportBody1.placed, solverPlaced) : -1;
check('S5b payload placed 与 solver 基线 diff 非空（fmt=plt/plt-clean 毛版默认）',
  !!exportBody1 && (exportBody1.fmt === 'plt' || exportBody1.fmt === 'plt-clean')
  && diffCount1 >= 2,
  'fmt=' + (exportBody1?.fmt) + ' diff=' + diffCount1 + '/' + (exportBody1?.placed?.length ?? '?'));
check('S5c payload density 与基线 diff 非空（扩长 → 降）',
  !!exportBody1 && exportBody1.density < final.density - 1e-6
  && exportBody1.width_mm === S3_W,
  'density=' + ((exportBody1?.density || 0) * 100).toFixed(2)
    + '% vs solver=' + (final.density * 100).toFixed(2)
    + '% width=' + (exportBody1?.width_mm ?? '?'));

// ---------- S6 ✕ 重开 → 拖片左移腾空 → 保存（缩短） ----------
await openEditViaUI();
await sleep(200);
await page.click('[data-testid=edit-layout-close]');
await sleep(300);
const closeClean = await page.evaluate(() =>
  document.querySelector('[data-testid=edit-layout-overlay]') === null
  && document.querySelector('[data-testid=edit-confirm-overlay]') === null);
check('S6a 已保存非 dirty → ✕ 直关（无确认层）', closeClean);
await openEditViaUI();
const s6open = await modalStats();
// 右缘逐片左移（US-003 教训：多片同 ceil 桶须逐片拖，包络才真正回缩）
const TARGET6 = widthOf(s6open) - 40;
let lastMax6 = Infinity;
let dragged6 = 0;
for (let iter = 0; iter < 12; iter++) {
  const polys = await roughPolysEval();
  const mxs = polys.map((p) => maxXOf(parsePts(p.points)));
  const top = Math.max(...mxs);
  if (top <= TARGET6) break;
  if (Math.abs(top - lastMax6) < 0.05) break;
  lastMax6 = top;
  const ptsKey = polys[mxs.indexOf(top)].points; // points 字符串 = 文档序无关的片身份
  const el = await page.evaluateHandle((key) => {
    const g = document.querySelector('svg.edit-layout-svg g');
    return Array.from(g.querySelectorAll('polygon'))
      .filter((p) => p.getAttribute('fill-opacity') === '0.55')
      .find((p) => p.getAttribute('points') === key);
  }, ptsKey);
  const hp = await hitPoint(el);
  if (!hp) break;
  const s6 = await editScale();
  await dragMouse(hp, -(top - (TARGET6 - 15)) * s6, 0, 10);
  dragged6 += 1;
  await sleep(120);
}
const s6after = await modalStats();
const S6_W = widthOf(s6after);
check('S6b 尾片左移腾空 → 状态条料长缩 ≥40mm / 利用率升',
  S6_W <= widthOf(s6open) - 40 && pctOf(s6after) > pctOf(s6open),
  widthOf(s6open) + '->' + S6_W + 'mm（拖 ' + dragged6 + ' 片）, '
    + pctOf(s6open).toFixed(2) + '%->' + pctOf(s6after).toFixed(2) + '%');
await page.click('[data-testid=edit-layout-save]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { state: 'detached', timeout: 5000 });
const S6_SNAP = await mainSnap();
const S6_PCT = labelPct(S6_SNAP.label);
const S6_CM = labelCm(S6_SNAP.label);
const S6_VBW = Number(S6_SNAP.viewBox.split(' ')[2]);
check('S6c 保存后主视图利用率升/料长缩 + 画布随 viewBoxMaxW 收缩',
  S6_PCT > S4_PCT && S6_CM < S4_CM && S6_VBW === S6_W && S6_SNAP.fabW === S6_W && S6_VBW < S4_VBW,
  S4_PCT + '%->' + S6_PCT + '%, ' + S4_CM + '->' + S6_CM
    + 'cm, vb ' + S4_VBW + '->' + S6_VBW);
await page.screenshot({ path: OUT + '/s6_after_shorten_save.png' });

// ---------- S7 弹窗外重置 → 恢复算法基线（diff 回零） ----------
await page.click('[data-testid=edit-controls-reset]');
await page.waitForSelector('[data-testid=edit-confirm-overlay]', { timeout: 4000 });
const resetMsg = await page.evaluate(() =>
  document.querySelector('[data-testid=edit-confirm-message]')?.textContent || '');
check('S7a 重置 confirm 原文案', resetMsg === '确认将当前更新后的排料布局重置回初始布局', resetMsg);
await page.click('[data-testid=edit-confirm-ok]');
const RST_SNAP = await waitMainLabel((l) => Math.abs(labelPct(l) - BASE_PCT) < 0.005, 8000)
  .then(() => mainSnap());
const RST_PCT = labelPct(RST_SNAP.label);
const RST_VBW = Number(RST_SNAP.viewBox.split(' ')[2]);
const pointsRestored = RST_SNAP.points.length === BASE_SNAP.points.length
  && RST_SNAP.points.every((p, i) => p === BASE_SNAP.points[i]);
check('S7b 重置后 NestLabel 回基线利用率/料长 + 全片 points 逐一回算法基线',
  Math.abs(RST_PCT - BASE_PCT) < 0.005 && pointsRestored,
  '"' + RST_SNAP.label + '" vs "' + BASE_SNAP.label + '" restored=' + pointsRestored);
check('S7c viewBox/fab 回基线锚',
  RST_VBW === Number(BASE_SNAP.viewBox.split(' ')[2]) && RST_SNAP.fabW === BASE_SNAP.fabW,
  'viewBox=' + RST_SNAP.viewBox + ' vs ' + BASE_SNAP.viewBox);
await page.screenshot({ path: OUT + '/s7_after_reset_main.png' });

// ---------- S7d 重置后再导出：placed/density 与基线 diff 回零 ----------
const exportBody2 = await exportOnce('S7d');
const diffCount2 = exportBody2 ? placedDiffCount(exportBody2.placed, solverPlaced) : -1;
check('S7e payload placed 与基线 diff 回零（逐片 ε 对拍）',
  !!exportBody2 && diffCount2 === 0,
  'diff=' + diffCount2 + '/' + (exportBody2?.placed?.length ?? '?'));
check('S7f payload density 与基线 diff 回零（= final.density）',
  !!exportBody2 && Math.abs(exportBody2.density - final.density) < 1e-9,
  ((exportBody2?.density || 0) * 100).toFixed(2) + '% vs ' + (final.density * 100).toFixed(2) + '%');

// ---------- 汇总 ----------
writeFileSync(OUT + '/report.json', JSON.stringify({
  at: new Date().toISOString(),
  base: { label: BASE_SNAP.label, viewBox: BASE_SNAP.viewBox, polys: BASE_SNAP.points.length,
    solver_density: final.density, solver_width_mm: final.width_mm },
  s4: { label: S4_SNAP.label, width: S3_W, changed: changed.length },
  s6: { label: S6_SNAP.label, width: S6_W, dragged: dragged6 },
  s7: { label: RST_SNAP.label, placed_diff: diffCount2, density: exportBody2?.density },
  results,
}, null, 2));
const failed = results.filter((r) => !r.ok);
console.log('\n==== 编辑排料端到端冒烟: ' + (results.length - failed.length) + '/' + results.length + ' PASS ====');
await browser.close();
process.exit(failed.length ? 1 : 0);

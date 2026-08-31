// 导出 PLT 弹窗 v3（全 14 字段预览，2026-08-31）端到端冒烟 harness（Playwright +
// 本地 Chrome channel；范本 scripts/us007_e2e_verify.mjs —— 上传/commit/求解/取证
// 工具函数沿用）。
//
// 前置：ms-web 在 :8000 运行且已加载 /api/plt-table-preview 路由 + 新 static 构建。
//
//   node scripts/smoke_plt_table_preview.mjs
//
// 相位：
//   S1 上传 882 母版 → commit（ptypes 非空）→ 超排页 3 码求解 20s → final；
//   S2 点导出（默认 PLT）→ ExportInfoModal：
//      a 预览请求 POST /api/plt-table-preview 载荷 = bestRun 几何子集
//        （gate_mm/width_mm/density/placed）+ X-Session-Id；
//      b 响应 14 行，弹窗按最终表格列序交错渲染 14 槽（8 只读 + 6 手输）；
//      c 自动字段成品串口径（方案名称 =N套 / 利用率 xx.xx% / 幅宽料长 x.xxxm /
//        绘图时间 YYYY-MM-DD HH:MM / 片数 = placed 条数）；
//      d 手输可编辑（床次填 153）；
//   S3 确认导出 → POST /export 200（fmt=plt，table.bed_no=153）；
//   S4 降级相位：page.route 拦断预览请求 → 重开弹窗 → v2 形态（6 手输 + 提示行、
//      无只读行）→ 确认导出仍 200。
import { createRequire } from 'node:module';
const { chromium } = createRequire(
  new URL('../materialSorting-web/package.json', import.meta.url),
)('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF = 'D:/code/MaterialSorting/data/882#弹力商务13%9%大货贴袋机-埋夹脚口20cm.dxf';
const SHOT = 'D:/code/MaterialSorting/out/smoke_plt_table_preview_modal_v3.png';

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await (await browser.newContext()).newPage();
const results = [];
function check(name, ok, extra = '') {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  [' + extra + ']' : ''}`);
}
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
function captureWs(p) {
  const cap = { msgs: [] };
  p.on('websocket', (ws) => {
    ws.on('framereceived', (f) => {
      try { cap.msgs.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
    });
  });
  return cap;
}
async function waitMsg(cap, type, timeout = 90000) {
  const t0 = Date.now();
  for (;;) {
    const m = cap.msgs.find((x) => x && x.type === type);
    if (m) return m;
    if (Date.now() - t0 > timeout) return null;
    await new Promise((r) => setTimeout(r, 500));
  }
}

// ---------- S1 上传 + commit + 求解 ----------
await page.goto(BASE, { waitUntil: 'networkidle' });
const sid = await page.evaluate(() => localStorage.getItem('ms_sid'));
check('S0 页面加载落会话 sid', /^[0-9a-f]{32}$/.test(sid || ''), (sid || '').slice(0, 8));

await dismissTour(page);
await page.locator('input[type=file]').first().setInputFiles(DXF);
await page.waitForSelector('button.tab:not([disabled]):has-text("超排")', { timeout: 240000 });
let committed = false;
for (let i = 0; i < 80; i++) {
  const r = await rawFetch(page, '/api/ptypes', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
  if (r.status === 200 && Object.keys(r.body?.representatives || {}).length > 0) { committed = true; break; }
  await page.waitForTimeout(3000);
}
check('S1a 上传 882 + commit 完成（ptypes 非空）', committed);

await page.click('button.tab:has-text("超排")');
await page.waitForTimeout(800);
await dismissTour(page);
const boxes = page.locator('input[type=checkbox]');
const nBoxes = await boxes.count();
for (let i = 0; i < Math.min(3, nBoxes); i++) await boxes.nth(i).check();
await page.fill('#time', '20');
const ws = captureWs(page);
await page.click('#start');
const final = await waitMsg(ws, 'final', 90000);
check('S1b 求解 20s 出 final', !!final && final.density > 0,
  final ? 'density=' + final.density.toFixed(4) : 'no final');

// ---------- S2 打开导出弹窗（默认 PLT）→ 14 字段预览 ----------
let previewReq = null;
let previewResp = null;
page.on('request', (r) => {
  if (r.url().includes('/api/plt-table-preview')) {
    previewReq = { url: r.url(), method: r.method(), body: r.postDataJSON(), sid: r.headers()['x-session-id'] || null };
  }
});
page.on('response', async (r) => {
  if (r.url().includes('/api/plt-table-preview')) {
    try { previewResp = await r.json(); } catch { previewResp = null; }
  }
});
await page.click('button.export');
await page.waitForSelector('.export-ro-row', { timeout: 15000 });
check('S2a 弹窗打开且预览行渲染（.export-ro-row 在场）', true);

const frames = ws.msgs.filter((m) => m && m.type === 'frame');
const lastFrame = frames.at(-1);
const nPlaced = lastFrame?.placed_items?.length || 0;
check('S2b 预览请求 = POST + bestRun 几何子集 + 本会话 sid',
  !!previewReq && previewReq.method === 'POST'
  && previewReq.body.gate_mm === 1980
  && Math.abs(previewReq.body.width_mm - (lastFrame?.width_mm ?? -1)) < 0.001
  && previewReq.body.placed?.length === nPlaced && nPlaced > 0
  && previewReq.sid === sid,
  previewReq ? `gate=${previewReq.body.gate_mm} w=${previewReq.body.width_mm} n=${previewReq.body.placed?.length}` : 'no req');
check('S2c 预览响应 14 行（manual 恰 6）', !!previewResp && previewResp.rows?.length === 14
  && previewResp.rows.filter((x) => x.manual).length === 6);

const order = await page.evaluate(() => {
  const els = document.querySelectorAll(
    '.strategy-modal input[id^="export-info-"], .strategy-modal textarea[id^="export-info-"], .strategy-modal .export-ro-row',
  );
  return Array.from(els).map((el) =>
    el.classList.contains('export-ro-row') ? 'auto:' + el.dataset.testid : el.id);
});
const EXPECT_ORDER = [
  'auto:export-info-auto-plan_name',
  'export-info-bed-no',
  'export-info-warp-shrink',
  'export-info-weft-shrink',
  'auto:export-info-auto-utilization',
  'auto:export-info-auto-gate',
  'auto:export-info-auto-fabric_len',
  'auto:export-info-auto-sets',
  'auto:export-info-auto-per_set',
  'auto:export-info-auto-pieces',
  'export-info-planner',
  'auto:export-info-auto-draw_time',
  'export-info-style-no',
  'export-info-remark',
];
check('S2d 14 槽按最终表格列序交错（方案名称..备注）',
  JSON.stringify(order) === JSON.stringify(EXPECT_ORDER), order.join(','));

const vals = await page.evaluate(() =>
  Object.fromEntries(Array.from(document.querySelectorAll('.export-ro-row')).map((el) => [
    el.dataset.testid, el.querySelector('.export-ro-value')?.textContent || '',
  ])));
const plan = vals['export-info-auto-plan_name'] || '';
check('S2e 方案名称成品串（=N套）', /.+=.+套$/.test(plan), plan);
check('S2f 利用率 xx.xx%', /^\d+\.\d{2}%$/.test(vals['export-info-auto-utilization'] || ''), vals['export-info-auto-utilization']);
check('S2g 幅宽/料长/每套用料 x.xxxm',
  /^\d+\.\d{3}m$/.test(vals['export-info-auto-gate'] || '')
  && /^\d+\.\d{3}m$/.test(vals['export-info-auto-fabric_len'] || '')
  && /^\d+\.\d{3}m$/.test(vals['export-info-auto-per_set'] || ''),
  `${vals['export-info-auto-gate']} / ${vals['export-info-auto-fabric_len']} / ${vals['export-info-auto-per_set']}`);
check('S2h 片数 = placed 条数', vals['export-info-auto-pieces'] === String(nPlaced),
  `${vals['export-info-auto-pieces']} vs ${nPlaced}`);
check('S2i 绘图时间 YYYY-MM-DD HH:MM', /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(vals['export-info-auto-draw_time'] || ''), vals['export-info-auto-draw_time']);

// 手输编辑（受控输入原生事件）+ 截图存档
await page.evaluate(() => {
  const input = document.querySelector('#export-info-bed-no');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(input, '153');
  input.dispatchEvent(new Event('input', { bubbles: true }));
});
const bedNoVal = await page.evaluate(() => document.querySelector('#export-info-bed-no')?.value);
check('S2j 手输可编辑（床次填 153）', bedNoVal === '153', String(bedNoVal));
await page.locator('.strategy-modal').screenshot({ path: SHOT });
console.log('      screenshot -> ' + SHOT);

// ---------- S3 确认导出 ----------
let exportResp = null;
page.on('response', (r) => {
  if (r.url().endsWith('/export')) exportResp = r;
});
await page.click('[data-testid=export-info-confirm]');
for (let i = 0; i < 40 && !exportResp; i++) await page.waitForTimeout(500);
const cd = exportResp ? (exportResp.headers()['content-disposition'] || '') : '';
const exportBody = exportResp ? exportResp.request().postDataJSON() : null;
check('S3a 确认 → POST /export 200（PLT 附件）',
  !!exportResp && exportResp.status() === 200 && decodeURIComponent(cd).includes('.plt'),
  exportResp ? exportResp.status() + ' ' + cd.slice(0, 70) : 'no response');
check('S3b 导出载荷 table.bed_no=153 且 fmt=plt',
  !!exportBody && exportBody.fmt === 'plt' && exportBody.table?.bed_no === '153');

// ---------- S4 降级相位：拦断预览请求 → v2 形态仍可导出 ----------
await page.route('**/api/plt-table-preview*', (route) => route.abort());
await page.click('button.export');
await page.waitForSelector('[data-testid=export-info-auto-hint]', { timeout: 10000 });
await page.waitForTimeout(1500); // 等 catch 落定换文案
const degraded = await page.evaluate(() => ({
  hasRo: document.querySelector('.export-ro-row') !== null,
  nInputs: document.querySelectorAll('.strategy-modal input[id^="export-info-"], .strategy-modal textarea[id^="export-info-"]').length,
  hint: document.querySelector('[data-testid=export-info-auto-hint]')?.textContent || '',
}));
check('S4a 预览被拦 → 降级 v2 形态（无只读行 + 6 手输 + 提示行说明自动计算）',
  !degraded.hasRo && degraded.nInputs === 6 && degraded.hint.includes('自动计算') && degraded.hint.includes('不可用'),
  `inputs=${degraded.nInputs} hint=${degraded.hint.slice(0, 30)}…`);
let exportResp2 = null;
page.on('response', (r) => {
  if (r.url().endsWith('/export')) exportResp2 = r;
});
await page.click('[data-testid=export-info-confirm]');
for (let i = 0; i < 40 && !exportResp2; i++) await page.waitForTimeout(500);
check('S4b 降级形态确认导出仍 200', !!exportResp2 && exportResp2.status() === 200,
  exportResp2 ? String(exportResp2.status()) : 'no response');

const failed = results.filter((r) => !r.ok);
console.log('\n==== PLT 表格预览弹窗冒烟: ' + (results.length - failed.length) + '/' + results.length + ' passed ====');
await browser.close();
process.exit(failed.length ? 1 : 0);

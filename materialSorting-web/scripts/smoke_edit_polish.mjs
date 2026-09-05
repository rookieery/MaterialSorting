// edit-polish US-004 端到端冒烟（prd-edit-polish，2026-09-05）—— 智能微调整条链路
// 回归锁死：上传 → per_type 放开 d/tol（制造重合与旋转）→ 短求解 → 编辑弹窗微调
// （报告四段 + 守恒不等式）→ 撤销恢复 → 再微调（确定性双跑全等）→ 保存 → 导出
// DXF/PLT placed 守恒（=Σdemand）→ band on 场景 exclude 生效（带形态区域不动）。
//
// 模板对齐 scripts/smoke_edit_layout.mjs（repo 根，Playwright 流程骨架/抓包套路）
// + smoke_prefix_extra.mjs（per_type 写值/导出格式切换）；浏览器 = Edge 通道
//（本机无 playwright 二进制，借系统通道 msedge，Chrome 兜底 —— 同目录其余冒烟同款）。
//
// 前置：ms-web 在 :8000 运行 + 新 static 构建（prod 模式）。
//
//   node materialSorting-web/scripts/smoke_edit_polish.mjs
//
// 相位：
//   S1 上传 5336 母版 → commit → per_type 全 g 码 d=3/tol=30（工艺余量制造重合与
//      旋转，polish 有实事可做）→ 超排 3 码（32/33/34，30 片）20s 求解 → final。
//   S2 编辑弹窗 → 智能微调：请求 200 + 载荷形态（placed 30/gate_mm/无 exclude 键）
//      + 报告四段 + 四守恒（overlap_pairs 严格下降、rotΣ 下降、width ≤ before、
//      density ≥ before−1e-6）+ 对比卡渲染。
//   S3 撤销微调：画布 points 逐片回微调前 + 卡清空。
//   S4 再微调：确定性双跑 —— placed 与 report（elapsed_sec 除外）与首次全等。
//   S5 保存 → 导出 PLT（默认 plt-clean）+ DXF：payload placed 条数 = Σdemand = 30
//      且与微调响应 placed 深相等（守恒）；DXF 正文 R12 POLYLINE 无 LWPOLYLINE。
//   S6 band on 场景抽验：per_type 开腰头成带 g05 → 重解 → 编辑弹窗微调 →
//      请求带 exclude.labels=['g05'] + 带形态区域（g05 全部毛版）points 前后不变
//      + report.excluded 恰覆盖 g05 实例。
//   S7 compact 压缩回收档（US-005）：对比卡内勾选「回收空隙缩短料长」→ 再微调
//      → 请求带 compact:true + width ≤ 非 compact 档（S6 结果）+ 密度不降 +
//      重合对不增 + placed 守恒。
//
// 报告落 out/smoke_edit_polish/report.json；退出码 0 = 全 PASS。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

// 路径锚定脚本位置（任意 CWD 可跑）：materialSorting-web/ -> repo 根
const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');

const { chromium } = await import('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF = ROOT + '/data/5336#老六订单14%7%围加9.dxf';
const OUT = ROOT + '/out/smoke_edit_polish';
const SIZES = [32, 33, 34]; // 5336 码集；3 码 × 10 片 = 30 片（Σdemand 默认 1/格）
const SOLVE_TIME = '20';
const BAND_LABEL = 'g05';
const EXPECT_TOTAL = 30;

mkdirSync(OUT, { recursive: true });
// Edge 通道（Win11 必有），Chrome 兜底 —— 同目录其余冒烟同款
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true });
} catch {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
}
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
/** 弹窗内全部毛版 polygon（US-003 教训：提层后 DOM 序 ≠ working 序 —— points 寻址）。 */
const roughPoints = () => page.evaluate(() => {
  const g = document.querySelector('svg.edit-layout-svg g');
  return Array.from(g.querySelectorAll('polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55')
    .map((p) => p.getAttribute('points'));
});
/** 弹窗内按 data-label 过滤的毛版 polygon points（band 带形态区域快照用）。 */
const labelPoints = (label) => page.evaluate((lb) => {
  const g = document.querySelector('svg.edit-layout-svg g');
  return Array.from(g.querySelectorAll('polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55' && p.dataset.label === lb)
    .map((p) => p.getAttribute('points'));
}, label);
/** 抓一次微调：点击按钮 → 等待 /api/edit-polish 响应（请求载荷 + body 双捕获）。 */
async function polishOnce() {
  let reqBody = null;
  let respBody = null;
  const handler = async (r) => {
    if (!r.url().endsWith('/api/edit-polish')) return;
    try { reqBody = JSON.parse(r.request().postData()); } catch { reqBody = null; }
    try { respBody = await r.json(); } catch { respBody = null; }
  };
  page.on('response', handler);
  await page.click('[data-testid=edit-polish-btn]');
  for (let i = 0; i < 120 && !respBody; i++) await sleep(500);
  page.off('response', handler);
  return { reqBody, respBody };
}
/** 点选格式 → 导出 → 抓 POST /export 请求载荷与响应正文。PLT 族走 ExportInfoModal
 *  确认（ControlPanel.handleExport 分流：plt/plt-clean 才开弹窗）；DXF 直发无弹窗。
 *  响应正文 = 页内 fetch 包装捕获（apiFetch 走 window.fetch 单点；Playwright 网络层
 *  对 fetch→blob 消费后的附件响应 body 常拿不到 —— smoke_prefix_extra __fetchCaps 同套路）。 */
async function exportOnce(fmt, tag) {
  let captured = null;
  const onResp = (r) => { if (r.url().endsWith('/export')) captured = r; };
  await page.evaluate(() => {
    window.__exportCaps = [];
    if (!window.__exportOrigFetch) window.__exportOrigFetch = window.fetch;
    const orig = window.__exportOrigFetch;
    window.fetch = async function (...args) {
      const res = await orig.apply(this, args);
      if (String(args[0]).includes('/export')) {
        try {
          const buf = await res.clone().arrayBuffer();
          window.__exportCaps.push({ bytes: buf.byteLength, text: new TextDecoder().decode(buf) });
        } catch (e) {
          window.__exportCaps.push({ bytes: 0, text: '', err: String(e) });
        }
      }
      return res;
    };
  });
  await page.selectOption('select.export-fmt', fmt);
  await sleep(200);
  page.on('response', onResp);
  await page.click('button.export');
  if (fmt === 'plt' || fmt === 'plt-clean') {
    await page.waitForSelector('[data-testid=export-info-overlay]', { timeout: 15000 });
    await page.waitForSelector('.export-ro-row', { timeout: 15000 });
    await page.click('[data-testid=export-info-confirm]');
  }
  // 等网络层 captured + 页内包装正文落定（body 走 res.clone()，晚于响应事件）
  for (let i = 0; i < 60; i++) {
    const n = await page.evaluate(() => (window.__exportCaps || []).length);
    if (captured && n > 0) break;
    await sleep(500);
  }
  const caps = await page.evaluate(() => window.__exportCaps || []);
  // 还原 fetch（避免包装层影响后续路径断言）
  await page.evaluate(() => {
    if (window.__exportOrigFetch) window.fetch = window.__exportOrigFetch;
  });
  page.off('response', onResp);
  const cap = caps[caps.length - 1] || { bytes: 0, text: '' };
  const respBody = cap.text || '';
  const cd = captured ? (captured.headers()['content-disposition'] || '') : '';
  let reqBody = null;
  try { reqBody = captured ? captured.request().postDataJSON() : null; } catch { reqBody = null; }
  check(tag + ' POST /export 200（.' + fmt.replace('plt-clean', 'plt') + ' 附件）',
    !!captured && captured.status() === 200
      && decodeURIComponent(cd).includes('.' + fmt.replace('plt-clean', 'plt')),
    captured ? captured.status() + ' ' + decodeURIComponent(cd).slice(0, 60) : 'no response');
  return { reqBody, respBody };
}

// ---------- S1 上传 5336 + per_type 放开 d/tol + 短求解 ----------
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
// 高级配置：全部 g 码 d=3mm / tol=30°（制造工艺余量重合与旋转，polish 有实事可做）
await page.click('[data-testid=per-type-btn]');
await page.waitForSelector('[data-testid=per-type-overlay]', { timeout: 5000 });
const labels = await page.evaluate(() => {
  const els = document.querySelectorAll('[data-testid^="d-"]');
  return Array.from(els).map((e) => e.getAttribute('data-testid').slice(2));
});
for (const lb of labels) {
  await page.fill(`[data-testid="d-${lb}"]`, '3');
  await page.fill(`[data-testid="tol-${lb}"]`, '30');
}
await page.click('[data-testid=per-type-confirm]');
await sleep(400);
for (const sz of SIZES) await page.check('#sz_' + sz);
await page.fill('#time', SOLVE_TIME);
await page.click('#start');
const final1 = await waitMsg('final', 150000);
const solverPlaced = cap.msgs.filter((x) => x && x.type === 'frame').slice(-1)[0]?.placed_items || [];
check('S1b 短求解 20s 出 final（3 码 30 片 = Σdemand）',
  !!final1 && solverPlaced.length === EXPECT_TOTAL,
  final1 ? 'density=' + final1.density.toFixed(4) + ' placed=' + solverPlaced.length : 'no final');

// ---------- S2 编辑弹窗 + 智能微调（报告四段 + 守恒不等式） ----------
await page.click('[data-testid=edit-controls-edit]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { timeout: 5000 });
check('S2a 编辑弹窗打开 + 工具区智能微调按钮在案',
  await page.evaluate(() => {
    const tools = document.querySelector('.edit-layout-canvas-tools');
    const btn = document.querySelector('[data-testid=edit-polish-btn]');
    return !!tools && !!btn && tools.contains(btn) && !btn.disabled;
  }));
await page.screenshot({ path: OUT + '/s2_before_polish.png' });
const pointsBefore = await roughPoints();

const p1 = await polishOnce();
const rep1 = p1.respBody?.report || {};
const ok1 = p1.respBody?.ok === true;
check('S2b 微调请求 200 + 载荷形态（placed 30 / gate_mm / 无 exclude 键）+ 报告四段',
  ok1 && p1.reqBody?.placed?.length === EXPECT_TOTAL && p1.reqBody?.gate_mm > 0
    && !('exclude' in p1.reqBody) && !!rep1.before && !!rep1.after
    && Array.isArray(rep1.moves) && Array.isArray(rep1.residual),
  'placed=' + p1.reqBody?.placed?.length + ' gate=' + p1.reqBody?.gate_mm
    + ' overlap ' + rep1.before?.overlap_pairs + '->' + rep1.after?.overlap_pairs
    + ' rotΣ ' + rep1.before?.rotation_dev_sum_deg + '->' + rep1.after?.rotation_dev_sum_deg
    + ' width ' + rep1.before?.width_mm + '->' + rep1.after?.width_mm
    + ' density ' + rep1.before?.density + '->' + rep1.after?.density
    + ' moves=' + rep1.moves?.length + ' residual=' + rep1.residual?.length);
check('S2c 重合对下降（after < before，或可解时 =0）',
  rep1.after?.overlap_pairs < rep1.before?.overlap_pairs
    || rep1.after?.overlap_pairs === 0,
  rep1.before?.overlap_pairs + ' -> ' + rep1.after?.overlap_pairs);
check('S2d 旋转偏差 Σ 下降（after < before）',
  rep1.after?.rotation_dev_sum_deg < rep1.before?.rotation_dev_sum_deg,
  rep1.before?.rotation_dev_sum_deg + ' -> ' + rep1.after?.rotation_dev_sum_deg + '°');
check('S2e 料长不增（after.width ≤ before.width）',
  rep1.after?.width_mm <= rep1.before?.width_mm + 1e-9,
  rep1.before?.width_mm + ' -> ' + rep1.after?.width_mm + 'mm');
check('S2f 密度不降（after ≥ before − 1e-6）',
  rep1.after?.density >= rep1.before?.density - 1e-6,
  rep1.before?.density + ' -> ' + rep1.after?.density + '%');
check('S2g 对比卡渲染（六指标前→后 + 撤销按钮 + 按钮title口径注记）',
  await page.evaluate(() => {
    const card = document.querySelector('[data-testid=edit-polish-card]');
    if (!card) return false;
    const ids = ['edit-polish-overlap', 'edit-polish-depth', 'edit-polish-rot',
      'edit-polish-rotsum', 'edit-polish-width', 'edit-polish-density'];
    // 口径注记 2026-09-05 三轮迭代起在按钮 title 悬浮（卡内可见脚注已移除不占空间）
    const btnTitle = document.querySelector('[data-testid=edit-polish-btn]')
      ?.getAttribute('title') || '';
    return ids.every((id) => {
        const el = card.querySelector('[data-testid=' + id + ']');
        return el && el.textContent.includes('→');
      })
      && !card.textContent.includes('物理毛版轮廓口径')
      && btnTitle.includes('物理毛版轮廓口径')
      && !!card.querySelector('[data-testid=edit-polish-undo]');
  }));
await page.screenshot({ path: OUT + '/s2_polish_report.png' });

// ---------- S3 撤销微调（画布 points 回微调前 + 卡清空） ----------
await page.click('[data-testid=edit-polish-undo]');
await sleep(400);
const pointsUndone = await roughPoints();
const undoneEqual = pointsBefore.length === pointsUndone.length
  && pointsBefore.every((p, i) => p === pointsUndone[i]);
check('S3a 撤销恢复快照（points 逐片回微调前）+ 卡清空/撤销按钮消失',
  undoneEqual && await page.evaluate(() =>
    document.querySelector('[data-testid=edit-polish-card]') === null),
  'pointsEqual=' + undoneEqual);
await page.screenshot({ path: OUT + '/s3_after_undo.png' });

// ---------- S4 再微调：确定性双跑全等（placed + report 除 elapsed_sec） ----------
const p2 = await polishOnce();
const rep2 = p2.respBody?.report || {};
const strip = (r) => {
  const c = { ...r };
  delete c.elapsed_sec;
  return c;
};
const placedEqual = JSON.stringify(p1.respBody?.placed) === JSON.stringify(p2.respBody?.placed);
const reportEqual = JSON.stringify(strip(rep1)) === JSON.stringify(strip(rep2));
check('S4a 确定性双跑全等（placed 深相等 + report 除 elapsed_sec 全等）',
  p2.respBody?.ok === true && placedEqual && reportEqual,
  'placed=' + placedEqual + ' report=' + reportEqual
    + ' moves1=' + rep1.moves?.length + ' moves2=' + rep2.moves?.length);

// ---------- S5 保存 → 导出 PLT + DXF（placed 守恒 = Σdemand） ----------
await page.click('[data-testid=edit-layout-save]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { state: 'detached', timeout: 5000 });
check('S5a 微调结果保存（弹窗关闭）', true);
const expPlt = await exportOnce('plt-clean', 'S5b');
const placedConserved = expPlt.reqBody?.placed?.length === EXPECT_TOTAL
  && JSON.stringify(expPlt.reqBody?.placed) === JSON.stringify(p2.respBody?.placed);
check('S5c PLT 导出 placed 守恒（条数 = Σdemand = 30 且与微调响应 placed 深相等）',
  placedConserved,
  'len=' + expPlt.reqBody?.placed?.length
    + ' deepEqual=' + (JSON.stringify(expPlt.reqBody?.placed) === JSON.stringify(p2.respBody?.placed)));
check('S5d PLT 正文在案（PU 笔 ≥100）',
  ((expPlt.respBody || '').match(/^PU/gm) || []).length >= 100,
  'bytes=' + (expPlt.respBody || '').length);
const expDxf = await exportOnce('dxf', 'S5e');
const placedConservedDxf = expDxf.reqBody?.placed?.length === EXPECT_TOTAL
  && JSON.stringify(expDxf.reqBody?.placed) === JSON.stringify(p2.respBody?.placed);
check('S5f DXF 导出 placed 守恒（条数 = 30 且与微调响应 placed 深相等）',
  placedConservedDxf, 'len=' + expDxf.reqBody?.placed?.length);
check('S5g DXF 正文 R12 POLYLINE（无 LWPOLYLINE —— ET2008 兼容口径）',
  (expDxf.respBody || '').includes('POLYLINE') && !(expDxf.respBody || '').includes('LWPOLYLINE'),
  'bytes=' + (expDxf.respBody || '').length);

// ---------- S6 band on 场景抽验：exclude 生效 + 带形态区域 bbox 前后不变 ----------
await page.click('[data-testid=per-type-btn]');
await page.waitForSelector('[data-testid=per-type-overlay]', { timeout: 5000 });
await page.check('[data-testid=band-enabled]', { force: true });
await page.selectOption('[data-testid=band-label-select]', BAND_LABEL);
await sleep(600); // 等成带预演缩略三态落定（预演不阻塞确定）
await page.click('[data-testid=per-type-confirm]');
await sleep(400);
for (const sz of SIZES) {
  const checked = await page.isChecked('#sz_' + sz);
  if (!checked) await page.check('#sz_' + sz);
}
await page.fill('#time', SOLVE_TIME);
cap.msgs.length = 0;
// 求解后 phase=done → 按钮是 #restart（SolveControls 五态钩子；idle 期才是 #start）
await page.click('#restart, #start');
const final2 = await waitMsg('final', 150000);
const solverPlaced2 = cap.msgs.filter((x) => x && x.type === 'frame').slice(-1)[0]?.placed_items || [];
const bandCount = solverPlaced2.filter((p) => p.id.startsWith(BAND_LABEL + '_')).length;
check('S6a band on 重解出 final（30 片，其中 ' + BAND_LABEL + ' ' + bandCount + ' 片）',
  !!final2 && solverPlaced2.length === EXPECT_TOTAL && bandCount === SIZES.length,
  final2 ? 'density=' + final2.density.toFixed(4) + ' placed=' + solverPlaced2.length : 'no final');

await page.click('[data-testid=edit-controls-edit]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { timeout: 5000 });
const bandBefore = await labelPoints(BAND_LABEL);
check('S6b 编辑弹窗内带形态区域快照（g05 毛版 ' + bandBefore.length + ' 片在案）',
  bandBefore.length === bandCount, 'n=' + bandBefore.length);
const p3 = await polishOnce();
const rep3 = p3.respBody?.report || {};
check('S6c 微调请求带 exclude.labels=[' + BAND_LABEL + ']（band 记录 → labels 键）',
  p3.respBody?.ok === true && Array.isArray(p3.reqBody?.exclude?.labels)
    && p3.reqBody.exclude.labels.length === 1 && p3.reqBody.exclude.labels[0] === BAND_LABEL,
  'exclude=' + JSON.stringify(p3.reqBody?.exclude));
const bandAfter = await labelPoints(BAND_LABEL);
const bandUnchanged = bandBefore.length === bandAfter.length
  && bandBefore.every((p, i) => p === bandAfter[i]);
check('S6d 带形态区域前后不变（g05 全部毛版 points 逐一相同 —— exclude 生效）',
  bandUnchanged, 'n=' + bandAfter.length + ' unchanged=' + bandUnchanged);
const excludedIdx = rep3.excluded || [];
const expectedExcluded = solverPlaced2
  .map((p, i) => (p.id.startsWith(BAND_LABEL + '_') ? i : -1)).filter((i) => i >= 0);
check('S6e report.excluded 恰覆盖 g05 实例（引擎排除语义对拍）',
  JSON.stringify(excludedIdx) === JSON.stringify(expectedExcluded),
  'excluded=' + JSON.stringify(excludedIdx) + ' expected=' + JSON.stringify(expectedExcluded));
await page.screenshot({ path: OUT + '/s6_band_exclude.png' });

// ---------- S7 compact 压缩回收档（US-005）：勾选 checkbox → 再微调 ----------
// S6 微调后对比卡在案（checkbox 随卡渲染，默认不勾）；勾选 → compact:true 随
// 下次微调请求发出。断言（AC 口径）：width ≤ 非 compact 档（rep3.after，同一
// working 上的非 compact 微调结果）+ 本轮守恒不等式（width 不增/密度不降/
// 重合对不增）+ placed 条数守恒。
const cbBefore = await page.isChecked('[data-testid="edit-polish-compact"]');
check('S7a compact checkbox 随对比卡渲染且默认不勾', cbBefore === false);
await page.check('[data-testid="edit-polish-compact"]');
check('S7b 勾选态受控在案', await page.isChecked('[data-testid="edit-polish-compact"]') === true);
const p4 = await polishOnce();
const rep4 = p4.respBody?.report || {};
check('S7c compact 微调请求 200 + 载荷 compact:true + placed 守恒',
  p4.respBody?.ok === true && p4.reqBody?.compact === true
    && p4.respBody?.placed?.length === EXPECT_TOTAL,
  'compact=' + p4.reqBody?.compact + ' placed=' + p4.respBody?.placed?.length
    + ' width ' + rep4.before?.width_mm + '->' + rep4.after?.width_mm
    + ' density ' + rep4.before?.density + '->' + rep4.after?.density
    + ' overlap ' + rep4.before?.overlap_pairs + '->' + rep4.after?.overlap_pairs);
check('S7d compact 后料长 ≤ 非 compact 档（width ≤ S6 微调结果）',
  rep4.after?.width_mm <= rep3.after?.width_mm + 1e-6,
  'compact=' + rep4.after?.width_mm + ' vs 非 compact=' + rep3.after?.width_mm + 'mm');
check('S7e compact 守恒不等式（本轮 width 不增 / 密度不降 / 重合对不增）',
  rep4.after?.width_mm <= rep4.before?.width_mm + 1e-9
    && rep4.after?.density >= rep4.before?.density - 1e-6
    && rep4.after?.overlap_pairs <= rep4.before?.overlap_pairs,
  'width ' + rep4.before?.width_mm + '->' + rep4.after?.width_mm
    + ' density ' + rep4.before?.density + '->' + rep4.after?.density);
await page.screenshot({ path: OUT + '/s7_compact.png' });

// ---------- 汇总 ----------
writeFileSync(OUT + '/report.json', JSON.stringify({
  at: new Date().toISOString(),
  solve1: { density: final1?.density, width_mm: final1?.width_mm, placed: EXPECT_TOTAL },
  polish1: { before: rep1.before, after: rep1.after, moves: rep1.moves?.length,
    residual: rep1.residual?.length },
  determinism: { placedEqual, reportEqual },
  export: {
    plt: { placed: expPlt.reqBody?.placed?.length, bytes: (expPlt.respBody || '').length },
    dxf: { placed: expDxf.reqBody?.placed?.length, bytes: (expDxf.respBody || '').length },
  },
  band: { label: BAND_LABEL, pieces: bandCount, excluded: excludedIdx,
    unchanged: bandUnchanged, report: { before: rep3.before, after: rep3.after } },
  compact: { requested: p4.reqBody?.compact === true,
    widthVsNonCompact: { compact: rep4.after?.width_mm, plain: rep3.after?.width_mm },
    report: { before: rep4.before, after: rep4.after }, moves: rep4.moves?.length },
  results,
}, null, 2));
const failed = results.filter((r) => !r.ok);
console.log('\n==== edit-polish 端到端冒烟: ' + (results.length - failed.length) + '/' + results.length + ' PASS ====');
await browser.close();
process.exit(failed.length ? 1 : 0);

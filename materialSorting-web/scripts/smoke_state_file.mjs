// 状态文件 US-004 端到端冒烟（playwright，手动脚本不入 vitest；2026-09-11）——
// 保存 → 手改 → 恢复 → 双 Tab 一致性 → 导出守恒 → 重解零回归 的全链回归锁。
//
// 模板对齐 scripts/smoke_drag_snap.mjs（流程骨架 / WS 帧捕获 / fetch 包装导出
// 抓包 / addInitScript 预置 ms.tour.*）；浏览器 = Edge 通道（系统通道借跑，
// Chrome 兜底，同目录其余冒烟同款）。前置：ms-web 在 :8000 运行（prod static）。
//
//   node materialSorting-web/scripts/smoke_state_file.mjs
//
// 相位：
//   S1 上传 5336 母版 → commit → 数量矩阵 g01@30 改 2 + 幅宽 180.00 + 高级配置
//      （g01 重合 d=1 + 腰头成带 g05）→ 3 码 5s 求解（Σdemand 31 → placed 条数
//      按 band 置换口径，守恒断言不硬编码）。
//   S2 编辑弹窗左键拖片 +40mm → 保存（.msn 的 run 将携带编辑后布局）。
//   S3 导出「状态文件」下载 .msn → Node gunzip + JSON 断言：schema 顶层键齐 /
//      run 无 provenance 键（WS 普通求解口径）/ placed 与 WS 末帧条数守恒且
//      恰 1 条被移动 ≈+40mm / form（sizes/gate/time/per_type/band）与
//      quantities 实值入档。
//   S4 全新 context（新 sid）上传 .msn → 恢复编排全链：
//      toast「状态文件已恢复…（含排料结果）」+ 自动切超排 + 来源小字
//      「来源：普通求解 · seed 0」+ nest-label 密度/料长与 .msn final 全等 +
//      布局 DOM polygon 数 = placed 条数；预览 Tab：数量矩阵实值（g01@30=2 /
//      总片数 111）+ 表单字段（gate/time/sizes/band/per_type）逐项回填；
//      编辑弹窗开即已编辑布局（料长 = .msn final.width_mm）；PLT 导出 POST
//      placed 与 .msn placed 深全等（后端守恒）；重解一次出新 final +
//      来源小字退场（WS 求解 origin 清场）。
//
// 报告落 out/smoke_state_file/report.json；退出码 0 = 全 PASS。
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';

// 路径锚定脚本位置（任意 CWD 可跑）：materialSorting-web/scripts/ -> repo 根
const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/smoke_state_file';
mkdirSync(OUT, { recursive: true });

const { chromium } = await import('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF = ROOT + '/data/5336#老六订单14%7%围加9_coded.dxf';
const SIZES = [32, 33, 34]; // 5336 码集；3 码 × 10 片 = 30 片（默认每格 1）
const SOLVE_TIME = '5';
const GATE = '180.00';
const QTY_LABEL = 'g01'; // 数量矩阵改值片型（colhead 顺序 = 最小码 pieces 顺序，g01 恒首列）
const QTY_SIZE = '30'; // 首行码号（coded 5336 码集 30-40 共 11 码，首行 = 最小码 30）
const BAND_LABEL = 'g05'; // 5336 腰头片型（smoke-band-preview 同款；g02 成带必败）
const EXPECT_TOTAL = 111; // 数量矩阵 Σdemand：110 默认（10 片型 × 11 码 × 1）+ g01@30 → 2（+1）
// 求解只勾 32/33/34 三码 → placed = 30（band WB_ 组合片已 expand 回成员 placement，
// 跨进程产物永无 WB_ pid，Σdemand 守恒）—— placed 断言用守恒对拍 + 30 常量双锚。
const DRAG_MM = 40; // S2 编辑位移（左键自由拖动，原样落点）

const results = [];
function check(name, ok, extra) {
  results.push({ name, ok });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 200) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (s) => console.log('---', s);
const normItems = (arr) =>
  arr
    .map((it) =>
      JSON.stringify({ id: it.id, rotation: it.rotation, translation: it.translation, mirror: it.mirror === true ? 1 : 0 }))
    .join('|');
async function dismissTour(p, rounds = 4) {
  for (let i = 0; i < rounds; i++) {
    const gone = await p.evaluate(() => document.querySelector('[data-testid=tour-overlay]') === null);
    if (gone) return;
    await p.evaluate(() => {
      const btn = document.querySelector('[data-testid=tour-skip]');
      if (btn) btn.click();
    });
    await sleep(600);
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
/** WS 帧捕获（page.on('websocket') 挂接器；framereceived JSON 解析）。 */
function wsCapture(page) {
  const cap = { msgs: [] };
  const frameText = (f) => {
    if (typeof f === 'string') return f;
    if (f && typeof f.payload === 'string') return f.payload;
    if (f && f.payload != null && typeof f.payload === 'object') return String.fromCharCode(...f.payload);
    return '';
  };
  page.on('websocket', (ws) => {
    ws.on('framereceived', (f) => {
      try { cap.msgs.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
    });
  });
  cap.waitMsg = async (type, timeout = 120000) => {
    const t0 = Date.now();
    for (;;) {
      const m = cap.msgs.find((x) => x && x.type === type);
      if (m) return m;
      if (Date.now() - t0 > timeout) return null;
      await sleep(500);
    }
  };
  return cap;
}
/** 点选格式 → 导出 → 抓 POST /export 请求载荷与响应正文（页内 fetch 包装，
 *  apiFetch 单点；Playwright 网络层对 fetch→blob 消费后的附件 body 常拿不到）。 */
async function exportOnce(page, fmt, tag) {
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
          const buf = new Uint8Array(await res.clone().arrayBuffer());
          window.__exportCaps.push({ bytes: buf.byteLength, text: new TextDecoder().decode(buf) });
        } catch (e) {
          window.__exportCaps.push({ bytes: 0, text: '', err: String(e) });
        }
      }
      return res;
    };
  });
  await page.selectOption('select.export-fmt', fmt);
  page.on('response', onResp);
  await page.click('button.export');
  if (fmt === 'plt' || fmt === 'plt-clean') {
    await page.waitForSelector('[data-testid=export-info-overlay]', { timeout: 15000 });
    await page.waitForSelector('.export-ro-row', { timeout: 15000 });
    await page.click('[data-testid=export-info-confirm]');
  }
  let n = 0;
  for (; n < 40; n++) {
    const c = await page.evaluate(() => (window.__exportCaps || []).length);
    if (c > 0) break;
    await sleep(500);
  }
  const caps = await page.evaluate(() => window.__exportCaps || []);
  page.off('response', onResp);
  const cap = caps[caps.length - 1] || { bytes: 0, text: '' };
  const cd = captured ? (captured.headers()['content-disposition'] || '') : '';
  let reqBody = null;
  try { reqBody = captured ? captured.request().postDataJSON() : null; } catch { reqBody = null; }
  check(tag + ' POST /export 200（.' + fmt.replace('plt-clean', 'plt') + ' 附件）',
    !!captured && captured.status() === 200
      && decodeURIComponent(cd).includes('.' + fmt.replace('plt-clean', 'plt')),
    captured ? captured.status() + ' ' + decodeURIComponent(cd).slice(0, 60) : 'no response');
  return { reqBody, respBody: cap.text || '' };
}
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}

// ---------- S1 上传 5336 + 数量/表单定制 + 5s 求解 ----------
const ctx1 = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await ctx1.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '7');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page = await ctx1.newPage();
const cap1 = wsCapture(page);

await page.goto(BASE, { waitUntil: 'networkidle' });
const sid = await page.evaluate(() => localStorage.getItem('ms_sid'));
check('S0 保存端页面加载落会话 sid', /^[0-9a-f]{32}$/.test(sid || ''), (sid || '').slice(0, 8));

await page.locator('input[type=file]').first().setInputFiles(DXF);
await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 240000 });
log('S1a 上传 + commit done');

// 数量矩阵（预览 Tab）：g01@30 → 2（data-cell="列-行"，g01 恒首列、30 首行）
const cell00 = page.locator('.qty-cell-input[data-cell="0-0"]');
await cell00.waitFor({ timeout: 15000 });
await cell00.fill('2');
await cell00.press('Enter');
await sleep(300);
const qtyTotal = await page.locator('[data-testid="qty-total"]').innerText();
check('S1b 数量矩阵 g01@30=2 → 总片数 111', qtyTotal.trim() === String(EXPECT_TOTAL), qtyTotal.trim());

// 切超排：勾 3 码 + 幅宽 180.00 + 时长 5
await page.locator('button.tab:not([disabled]):has-text("超排")').click();
await sleep(800);
await dismissTour(page);
for (const sz of SIZES) await page.check('#sz_' + sz);
await page.fill('#gate', GATE);
await page.fill('#time', SOLVE_TIME);

// 高级配置：g01 重合 d=1 + 腰头成带选 g05（表单快照覆盖 per_type/band）
await page.click('[data-testid="per-type-btn"]');
await page.waitForSelector('[data-testid="per-type-overlay"]', { timeout: 15000 });
const dInput = page.locator('[data-testid="d-' + QTY_LABEL + '"]');
await dInput.waitFor({ timeout: 15000 });
await dInput.fill('1');
await dInput.press('Tab');
await page.check('[data-testid="band-enabled"]');
const bandLabel = BAND_LABEL;
// 成带预览缩略（g05 可成带；失败态出现即中止本段）
await page.selectOption('[data-testid="band-label-select"]', bandLabel);
const thumbOk = await page
  .locator('[data-testid="band-thumb-' + bandLabel + '"], [data-testid="band-thumb-error"]')
  .first().waitFor({ timeout: 30000 })
  .then(() => true)
  .catch(() => false);
const thumbErr = await page.locator('[data-testid="band-thumb-error"]').count();
check('S1c 高级配置：g05 成带预览缩略在场（非错误态）', thumbOk && thumbErr === 0);
await page.click('[data-testid="per-type-confirm"]');
await sleep(300);
log('S1c form 定制完成（gate/per_type/band）');

// 5s 求解 → final（placed = Σdemand 调整 band 置换后的条数，守恒断言见 S3/S4）
await page.click('#start');
const final1 = await cap1.waitMsg('final', 120000);
const manifest1 = cap1.msgs.find((x) => x && x.type === 'manifest') || null;
const solverPlaced = cap1.msgs.filter((x) => x && x.type === 'frame').slice(-1)[0]?.placed_items || [];
const solveCount = solverPlaced.length;
check('S1d 短求解 5s 出 final（勾 32/33/34 三码 30 片，含 d=1 erode / band 成带）',
  !!final1 && !!manifest1 && solveCount === 30,
  final1 ? 'density=' + final1.density.toFixed(4) + ' placed=' + solveCount : 'no final');
await page.locator('#restart').waitFor({ timeout: 30000 });
await page.screenshot({ path: OUT + '/s1_solved.png' });

// ---------- S2 编辑弹窗：左键拖片 +40mm → 保存 ----------
await page.click('[data-testid="edit-controls-edit"]');
await page.waitForSelector('[data-testid="edit-layout-overlay"]', { timeout: 5000 });
await sleep(1200); // 画布首帧 imperative 绘制
const pieceHandle = await page.evaluateHandle(() => {
  const svg = document.querySelector('svg.edit-layout-svg');
  return Array.from(svg.querySelectorAll('g > polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55')[0] || null;
});
check('S2a 编辑弹窗打开 + 裁片 polygon 在案', pieceHandle.asElement() !== null);
const S = await page.evaluate(() => {
  const svg = document.querySelector('svg.edit-layout-svg');
  const r = svg.getBoundingClientRect();
  const vb = svg.getAttribute('viewBox').split(' ').map(Number);
  return Math.min(r.width / vb[2], r.height / vb[3]);
});
// 左键（button 0）自由拖动：pointerdown@片中心 → move +DRAG_MM → up（原样落点）
const dragRes = await page.evaluate(({ el, dxPx }) => {
  const svg = document.querySelector('svg.edit-layout-svg');
  const r = el.getBoundingClientRect();
  const x0 = r.x + r.width / 2;
  const y0 = r.y + r.height / 2;
  const x1 = x0 + dxPx;
  el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 51, clientX: x0, clientY: y0, button: 0 }));
  svg.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 51, clientX: (x0 + x1) / 2, clientY: y0 }));
  svg.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 51, clientX: x1, clientY: y0 }));
  svg.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 51, clientX: x1, clientY: y0, button: 0 }));
  return { points: el.getAttribute('points') };
}, { el: pieceHandle.asElement(), dxPx: DRAG_MM * S });
check('S2b 左键拖片 +40mm 落点生效（DOM points 更新）', !!dragRes.points);
const editedWidthText = await page.locator('[data-testid="edit-layout-width"]').innerText();
const editedWidthMm = parseInt(editedWidthText.replace(/[^0-9]/g, ''), 10);
check('S2c 编辑态料长读数在场', Number.isFinite(editedWidthMm) && editedWidthMm > 0, editedWidthText.trim());
await page.click('[data-testid="edit-layout-save"]');
await page.waitForSelector('[data-testid="edit-layout-overlay"]', { state: 'detached', timeout: 5000 });
log('S2 编辑保存完成（料长 ' + editedWidthMm + 'mm）');
await page.screenshot({ path: OUT + '/s2_edited.png' });

// ---------- S3 导出 .msn + Node gunzip 断言 ----------
await page.selectOption('select.export-fmt', 'state');
let dl = null;
{
  const dlP = page.waitForEvent('download', { timeout: 30000 }).then((d) => d).catch(() => null);
  await page.click('button.export');
  dl = await dlP;
  if (!dl) {
    // 诊断：toast / 状态行 / 按钮态（保存失败走 toast 不产附件）
    const dg = await page.evaluate(() => ({
      toasts: Array.from(document.querySelectorAll('.toast-msg')).map((t) => t.textContent),
      status: document.querySelector('#status')?.textContent || '',
      exportDisabled: Array.from(document.querySelectorAll('.export-btns button.export')).map((b) => b.disabled),
    }));
    console.log('DIAG state export:', JSON.stringify(dg));
  }
}
check('S3a 下载 .msn 附件（文件名含「状态」）', !!dl && dl.suggestedFilename().endsWith('.msn') && dl.suggestedFilename().includes('状态'),
  dl ? dl.suggestedFilename() : 'no download');
const msnPath = OUT + '/saved.msn';
if (dl) await dl.saveAs(msnPath);

const doc = dl ? JSON.parse(gunzipSync(readFileSync(msnPath)).toString('utf-8')) : {};
check('S3b 顶层键齐（schema_version=1/app/saved_at/doc/form/quantities/run）',
  doc.schema_version === 1 && doc.app === 'materialsorting'
    && ['saved_at', 'doc', 'form', 'quantities', 'run'].every((k) => k in doc));
const run = doc.run || null;
check('S3c run 块在场（done 态 bestRun 入档）', !!run && Array.isArray(run.placed));
check('S3d WS 普通求解 → run 无 provenance 键（老文件零惩罚口径）',
  !!run && !('provenance' in run));
check('S3e run.placed 与 WS 求解末帧条数守恒（' + solveCount + ' 条）',
  !!run && run.placed.length === solveCount, 'len=' + (run?.placed || []).length);
// 恰 1 条被移动 ≈ +40mm（左键自由拖动原样落点；其余 30 条与求解末帧逐位全等）
let moved = 0; let dx = null;
if (run) {
  const solverById = new Map();
  for (const it of solverPlaced) {
    const key = it.id + '@' + it.rotation + '@' + JSON.stringify(it.translation);
    solverById.set(key, (solverById.get(key) || 0) + 1);
  }
  for (const it of run.placed) {
    const key = it.id + '@' + it.rotation + '@' + JSON.stringify(it.translation);
    if ((solverById.get(key) || 0) > 0) { solverById.set(key, solverById.get(key) - 1); continue; }
    moved += 1;
  }
  const diffItem = run.placed.find(
    (it) => !solverPlaced.some((s) => s.id === it.id && s.rotation === it.rotation
      && JSON.stringify(s.translation) === JSON.stringify(it.translation)));
  dx = diffItem ? diffItem.translation[0] - (solverPlaced.find(
    (s) => s.id === diffItem.id && s.rotation === diffItem.rotation
    && Math.abs(s.translation[1] - diffItem.translation[1]) < 1e-6)?.translation[0] ?? NaN) : null;
}
check('S3f 编辑落档：恰 1 条被移动且 x 位移 ≈ +40mm（其余与求解末帧逐位全等）',
  moved === 1 && dx !== null && Math.abs(dx - DRAG_MM) < 0.5, 'moved=' + moved + ' dx=' + (dx == null ? 'n/a' : dx.toFixed(3)));
check('S3g form 入档：sizes=[32,33,34] / gate=180.00 / time=5 / band_enabled+label / per_type g01 d=1',
  doc.form?.sizes?.join(',') === SIZES.join(',')
    && doc.form?.gate === GATE && doc.form?.time === SOLVE_TIME
    && doc.form?.band_enabled === true && doc.form?.band_label === bandLabel
    && doc.form?.per_type?.[QTY_LABEL]?.d === '1',
  JSON.stringify({ sizes: doc.form?.sizes, gate: doc.form?.gate, band: doc.form?.band_label, d: doc.form?.per_type?.[QTY_LABEL]?.d }));
check('S3h quantities 入档：g01@30=2 / g01@31=1（全量扁平，未勾码也随文件走）',
  doc.quantities?.[QTY_LABEL]?.['30'] === 2 && doc.quantities?.[QTY_LABEL]?.['31'] === 1);
const msnDensity = run?.final?.density ?? null;
const msnWidthMm = run?.final?.width_mm ?? null;
check('S3i final 摘要入档：density>0 / width_mm = 编辑态料长（applyToRun 同口径）',
  typeof msnDensity === 'number' && msnDensity > 0 && msnWidthMm === editedWidthMm,
  'density=' + (msnDensity ?? 'n/a') + ' width=' + (msnWidthMm ?? 'n/a') + '/' + editedWidthMm);
const msnPlaced = run?.placed || [];
await ctx1.close();
log('S3 .msn 落盘 + 断言完成（' + msnPlaced.length + ' 条 placed）');

// ---------- S4 全新 context（新 sid）上传 .msn → 恢复编排全链 ----------
const ctx2 = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await ctx2.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '7');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page2 = await ctx2.newPage();
const cap2 = wsCapture(page2);
await page2.goto(BASE, { waitUntil: 'networkidle' });
const sid2 = await page2.evaluate(() => localStorage.getItem('ms_sid'));
check('S4a 恢复端全新会话（sid ≠ 保存端）', !!sid2 && sid2 !== sid, (sid2 || 'null').slice(0, 8));

await page2.locator('input[type=file]').first().setInputFiles(msnPath);
await page2.waitForSelector('.toast-msg', { timeout: 30000 });
const toasts = await page2.locator('.toast-msg').allInnerTexts();
check('S4b toast「状态文件已恢复…（含排料结果）」',
  toasts.some((t) => t.includes('状态文件已恢复') && t.includes('含排料结果')),
  toasts.join(' | ').slice(0, 60));
// toast 不自动消失（2026-08-31 修订），右上栈会拦截编辑弹窗关闭按钮 —— 逐条 ✕ 关掉
for (let i = 0; i < 5; i++) {
  if ((await page2.locator('.toast-close').count()) === 0) break;
  await page2.locator('.toast-close').first().click();
  await sleep(150);
}
await page2.locator('[data-testid="run-provenance"]').waitFor({ timeout: 10000 });
const prov = await page2.locator('[data-testid="run-provenance"]').innerText();
check('S4c 来源小字「来源：普通求解 · seed 0」（.msn 无 provenance 键 → 缺省 solve 口径）',
  prov.trim() === '来源：普通求解 · seed 0', prov.trim());
await page2.waitForSelector('.nest-label', { timeout: 10000 });
const labelText = await page2.locator('.nest-label').first().innerText();
check('S4d nest-label 密度/料长与 .msn final 全等',
  labelText.includes((msnDensity * 100).toFixed(2) + '%')
    && labelText.includes((msnWidthMm / 10).toFixed(2) + ' cm'),
  labelText.trim());
await sleep(1500);
// layer1 毛版 polygon 带 data-label（net/collide 层无）—— 只数毛版层 = placed 条数
const polyCount = await page2.locator('.nest-card svg polygon[data-label]').count();
check('S4e 布局 DOM 毛版 polygon 数 = placed 条数（' + msnPlaced.length + '）',
  polyCount === msnPlaced.length, 'poly=' + polyCount);
await page2.locator('#restart').waitFor({ timeout: 10000 });
await page2.locator('.export-btns button.export:not([disabled])').waitFor({ timeout: 10000 });
await page2.screenshot({ path: OUT + '/s4_restored_nesting.png' });

// 预览 Tab：数量矩阵实值 + 5 层渲染抽查
await page2.locator('button.tab:has-text("预览")').first().click();
await page2.locator('[data-testid="qty-matrix"]').waitFor({ timeout: 10000 });
const qt = (await page2.locator('[data-testid="qty-total"]').innerText()).trim();
check('S4f 预览 Tab 总片数 111（数量矩阵实值恢复）', qt === String(EXPECT_TOTAL), qt);
const cellV = await page2.locator('.qty-cell-input[data-cell="0-0"]').inputValue();
check('S4g 预览 Tab g01@30=2（hydrateFlat 实值覆盖）', cellV === '2', cellV);
const colheads = await page2.locator('.qty-colhead .qty-label-badge').count();
check('S4h 列头 10 片型（label 并集 = g01..g10）', colheads === 10, 'cols=' + colheads);
const netCount = await page2.locator('.qty-thumb svg polygon[data-role="net"]').count();
check('S4i 缩略图 5 层渲染抽查（净版虚线层 ≥1）', netCount >= 1, 'net=' + netCount);

// 表单（超排 Tab 左侧）：gate/time/sizes + 高级配置 band/per_type 回填
await page2.locator('button.tab:has-text("超排")').first().click();
await sleep(600);
const gateV = await page2.locator('#gate').inputValue();
const timeV = await page2.locator('#time').inputValue();
const sizesChecked = [];
for (const sz of SIZES) {
  if (await page2.locator('#sz_' + sz).isChecked()) sizesChecked.push(sz);
}
check('S4j 表单回填：gate=180.00 / time=5 / sizes=[32,33,34]',
  gateV === GATE && timeV === SOLVE_TIME && sizesChecked.join(',') === SIZES.join(','),
  JSON.stringify({ gateV, timeV, sizesChecked }));
await page2.click('[data-testid="per-type-btn"]');
await page2.waitForSelector('[data-testid="per-type-overlay"]', { timeout: 15000 });
await page2.locator('[data-testid="d-' + QTY_LABEL + '"]').waitFor({ timeout: 15000 });
const bandOn = await page2.locator('[data-testid="band-enabled"]').isChecked();
const bandV = await page2.locator('[data-testid="band-label-select"]').inputValue();
const dV = await page2.locator('[data-testid="d-' + QTY_LABEL + '"]').inputValue();
check('S4k 高级配置回填：band_enabled + band_label=' + bandLabel + ' / per_type g01 d=1',
  bandOn === true && bandV === bandLabel && dV === '1',
  JSON.stringify({ bandOn, bandV, dV }));
await page2.click('[data-testid="per-type-close"]');
await sleep(300);

// 编辑弹窗开即已编辑布局（基线 = 恢复布局，料长 = .msn final.width_mm）
await page2.click('[data-testid="edit-controls-edit"]');
await page2.waitForSelector('[data-testid="edit-layout-overlay"]', { timeout: 5000 });
await sleep(1200);
const rWidthText = await page2.locator('[data-testid="edit-layout-width"]').innerText();
const rWidthMm = parseInt(rWidthText.replace(/[^0-9]/g, ''), 10);
check('S4l 编辑弹窗基线 = 恢复布局（料长 ' + msnWidthMm + 'mm 全等）', rWidthMm === msnWidthMm,
  rWidthText.trim() + ' vs ' + msnWidthMm);
const rPolys = await page2.evaluate(() =>
  document.querySelectorAll('svg.edit-layout-svg g > polygon[fill-opacity="0.55"]').length);
check('S4m 编辑画布裁片条数 = placed（' + msnPlaced.length + '）', rPolys === msnPlaced.length, 'polys=' + rPolys);
await page2.click('[data-testid="edit-layout-close"]');
await page2.waitForSelector('[data-testid="edit-layout-overlay"]', { state: 'detached', timeout: 5000 });
await page2.screenshot({ path: OUT + '/s4n_edit_baseline.png' });

// PLT 导出：后端 placed 守恒（POST 载荷 placed 与 .msn placed 深全等）
const expR = await exportOnce(page2, 'plt-clean', 'S4n');
const expPlaced = expR.reqBody?.placed || [];
check('S4o 恢复后 PLT 导出 placed 守恒（' + msnPlaced.length + ' 条与 .msn placed 深全等）',
  expPlaced.length === msnPlaced.length && normItems(expPlaced) === normItems(msnPlaced),
  'len=' + expPlaced.length);
check('S4p 导出 gate/width/density 与 .msn final 一致',
  expR.reqBody?.gate_mm === 1800 && expR.reqBody?.width_mm === msnWidthMm
    && Math.abs((expR.reqBody?.density ?? -1) - msnDensity) < 1e-9,
  JSON.stringify({ gate: expR.reqBody?.gate_mm, width: expR.reqBody?.width_mm, density: expR.reqBody?.density }));

// 重解一次（WS 链路零回归）：新 final + 来源小字退场
await page2.click('#restart');
const final2 = await cap2.waitMsg('final', 120000);
check('S4q 恢复后重解出新 final（WS 求解零回归）',
  !!final2 && typeof final2.density === 'number' && final2.density > 0,
  final2 ? 'density=' + final2.density.toFixed(4) : 'no final');
await page2.locator('#restart').waitFor({ timeout: 60000 });
await sleep(1000);
check('S4r 重解后来源小字退场（WS 普通求解 origin 清场）',
  (await page2.locator('[data-testid="run-provenance"]').count()) === 0);
const label2 = await page2.locator('.nest-label').first().innerText();
check('S4s 重解后 nest-label 更新（新密度上屏）',
  label2.includes((final2.density * 100).toFixed(2) + '%'), label2.trim());
await page2.screenshot({ path: OUT + '/s4t_resolved.png' });
await ctx2.close();

writeFileSync(OUT + '/report.json', JSON.stringify({ at: new Date().toISOString(), results }, null, 2));
await browser.close();
const fails = results.filter((r) => !r.ok);
console.log(fails.length === 0 ? 'SMOKE PASS' : 'SMOKE FAIL (' + fails.length + ')');
process.exit(fails.length === 0 ? 0 : 1);

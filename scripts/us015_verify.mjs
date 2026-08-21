// US-015 浏览器验证（v1.1 填料混带多选交互；Playwright + 系统 Chrome headless）。
// 前置：ms-web 在 :8000（最新后端 + 最新前端 build）+ A/B 报告 us015_ab_report.json
//（终值对拍数据源：on 臂 seed0 / 带 fill）。
// 链路：上传 5336 -> QtyMatrix P0 需求表（7 双份 g 码整列 2 + 31->1/36->3；g06~g08
// 默认 1/码 = A/B accept_quantities 同表）-> 超排 P0 七码 + 120s -> 高级配置勾成带
// g05 + ack -> 纯腰预演回显 -> 【填料多选 g07（fill 上升 + 预演 body 带 fillers）+
// 上限 3 置灰/取消恢复】-> 多选 UI 截图 -> 确认 -> 真实 WS 求解 -> stage/final 截图
// + 终值对拍 + 守恒（末帧 g05=14 / g07=7）+ 无 WB_ 泄漏。
// 截图产物：.docs/business/us015_filler_multiselect.png / us015_mixed_band_stage.png
// / us015_mixed_band_final_seed0.png（多选交互 + 混带形态目测证据）。
import { chromium } from 'file:///D:/code/MaterialSorting/materialSorting-web/node_modules/playwright/index.mjs';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9_coded.dxf';
const OUT = 'D:/code/MaterialSorting/out/us015_verify';
const DOCS = 'D:/code/MaterialSorting/.docs/business';
const REPORT = 'D:/code/MaterialSorting/materialSorting-server/out/config_runs/_probes/us015_ab_report.json';
mkdirSync(OUT, { recursive: true });
// A/B 报告 on 臂 seed0 密度 + 带 fill（浏览器同配置同 seed -> 确定性对拍基准）
const ab = JSON.parse(readFileSync(REPORT, 'utf-8'));
const row0 = ab.rows.find((r) => r.seed === 0);
const abOnPct = row0 && row0.on_pct;
const abFill = row0 && row0.fill_pct;
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name + (detail ? '  -- ' + String(detail).slice(0, 220) : ''));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1560, height: 980 }, acceptDownloads: true });
const page = await context.newPage();
// 跳过首次进入 Tab 的操作指引浮层（z-2000 全屏遮挡 clicks；与 tourStore.hydrateSeen 同键口径）
// + hook WebSocket 记录全部 server->client 消息（WB_ 泄漏哨兵：manifest/frame/final 全 grep）
// + hook fetch 记录 /api/band/preview 请求体（fillers 序列化断言）
await page.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '7');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
  const Orig = window.WebSocket;
  window.__wsLog = [];
  function Wrapped(...args) {
    const ws = new Orig(...args);
    ws.addEventListener('message', (ev) => {
      try { window.__wsLog.push(String(ev.data)); } catch (e) { /* 忽略 */ }
    });
    return ws;
  }
  Wrapped.prototype = Orig.prototype;
  window.WebSocket = Wrapped;
  const OrigFetch = window.fetch;
  window.__previewBodies = [];
  window.fetch = (...args) => {
    try {
      if (String(args[0]).includes('/api/band/preview')) {
        window.__previewBodies.push(String(args[1] && args[1].body));
      }
    } catch (e) { /* 忽略 */ }
    return OrigFetch(...args);
  };
});
const P0_SIZES = [31, 32, 33, 34, 35, 36, 38];
const DOUBLE_LABELS = ['g01', 'g02', 'g03', 'g04', 'g05', 'g09', 'g10'];
/** 等预演回显稳定（带内预演：填充 N%）并返回 fill 数值。 */
async function waitPreviewOk() {
  await page.waitForFunction(
    () => /带内预演：填充 ([\d.]+)%/.test(
      document.querySelector('[data-testid="band-preview"]')?.textContent ?? ''),
    undefined, { timeout: 30000 });
  const t = await page.locator('[data-testid="band-preview"]').textContent();
  return parseFloat(/填充 ([\d.]+)%/.exec(t)[1]);
}
try {
  // ---- 1) 上传 5336 DXF（multipart）-> 自动 commit（终验 uploads 源口径）----
  await page.goto(APP, { waitUntil: 'networkidle' });
  await page.locator('input[type=file].upload-input-hidden').setInputFiles(DXF);
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 60000 });
  check('上传 5336 + commit（uploads 源）', true);

  // ---- 2) QtyMatrix：P0 需求表（双份 g 码整列 2，再改 31->1 / 36->3）----
  for (const label of DOUBLE_LABELS) {
    await page.locator(`[data-testid="qty-rowfill-${label}"]`).click();
    await page.locator('[data-testid="qty-fill-input"]').fill('2');
    await page.locator('.qty-fill-apply').click();
    await sleep(120);
  }
  const cell = (label, size) =>
    page.locator(`input.qty-cell-input[aria-label="裁片 ${label} 码 ${size} 数量"]`).first();
  for (const label of DOUBLE_LABELS) {
    await cell(label, 31).fill('1');
    await page.keyboard.press('Enter');
    await cell(label, 36).fill('3');
    await page.keyboard.press('Enter');
  }
  await sleep(300);
  check('QtyMatrix P0 需求表（7 g 码整列 2 + 31/36 特例；g06~g08 默认 1）', true);

  // ---- 3) 超排 Tab：P0 七码 + 时长 120s（与 A/B 同配置）----
  await page.getByRole('button', { name: '超排', exact: true }).click();
  await page.waitForSelector('.per-type-btn', { timeout: 15000 });
  for (const s of P0_SIZES) {
    const chip = page.locator(`#sz_${s}`);
    if (!(await chip.isChecked())) await chip.check();
  }
  await page.locator('#time').fill('120');
  check('P0 七码勾选 + 120s', true);

  // ---- 4) 高级配置：勾成带 g05 + ack 二次确认（5336 g05 长宽比 6.9 硬警告）----
  await page.locator('.per-type-btn').click();
  await page.waitForSelector('[data-testid="per-type-band"]', { timeout: 15000 });
  await page.locator('[data-testid="band-enabled"]').check();
  await page.locator('[data-testid="band-label-select"]').selectOption('g05');
  await page.waitForSelector('[data-testid="band-ack-wrap"]', { timeout: 30000 });
  await page.locator('[data-testid="band-ack"]').check();
  const pureFill = await waitPreviewOk();
  check('纯腰预演回显（ack 硬警告流；混带前基线）', pureFill > 45 && pureFill < 100,
    `fill=${pureFill}%`);

  // ---- 5) US-015 填料多选 g07：fill 上升 + 预演 body 带 fillers + 选中态 ----
  await page.locator('[data-testid="band-filler-g07"]').click();
  await sleep(200);
  await page.waitForFunction(
    () => (window.__previewBodies ?? []).some((b) => b.includes('"fillers"')),
    undefined, { timeout: 30000 });
  const mixedFill = await waitPreviewOk();
  const chip07 = page.locator('[data-testid="band-filler-g07"]');
  check('填料 g07 选中态（.on + aria-pressed=true）',
    ((await chip07.getAttribute('class')) ?? '').includes('on')
      && (await chip07.getAttribute('aria-pressed')) === 'true');
  check('混带预演 fill 高于纯腰（填料塞隙效果）', mixedFill > pureFill,
    `mixed=${mixedFill}% > pure=${pureFill}%`);
  if (typeof abFill === 'number') {
    check('混带 fill == A/B on 臂带 fill（同配置确定性）',
      Math.abs(mixedFill - abFill) <= 0.05, `UI=${mixedFill}% vs A/B=${abFill}%`);
  }
  const bodies = await page.evaluate(() => window.__previewBodies ?? []);
  const withFillers = bodies.map((b) => JSON.parse(b)).filter((b) => b.band && b.band.fillers);
  const lastBand = withFillers.length
    ? JSON.stringify(withFillers[withFillers.length - 1].band) : 'none';
  check('预演请求 body 带 band.fillers=["g07"]',
    withFillers.length > 0 && lastBand.includes('"fillers":["g07"]'), lastBand);

  // ---- 6) 上限 3：补选 g06/g08 凑满 -> 未选中 chip 置灰；取消后恢复 ----
  await page.locator('[data-testid="band-filler-g06"]').click();
  await page.locator('[data-testid="band-filler-g08"]').click();
  await sleep(200);
  check('满 3 后未选中 chip 置灰（g01 disabled）',
    await page.locator('[data-testid="band-filler-g01"]').isDisabled());
  check('已选中 chip 仍可操作（g06 enabled）',
    !(await page.locator('[data-testid="band-filler-g06"]').isDisabled()));
  await page.locator('[data-testid="band-filler-g06"]').click();   // 取消 g06
  await sleep(150);
  await page.locator('[data-testid="band-filler-g08"]').click();   // 取消 g08（留 g07）
  await sleep(150);
  check('取消后恢复可选（g01 enabled）',
    !(await page.locator('[data-testid="band-filler-g01"]').isDisabled()));
  await waitPreviewOk();
  await page.screenshot({ path: DOCS + '/us015_filler_multiselect.png' });
  check('多选交互截图落 .docs', true);

  // ---- 7) 确认 -> 真实 WS 求解（g05 腰 + 填料 g07 混带）----
  await page.locator('.per-type-btn-confirm').click();
  await page.waitForSelector('[data-testid="per-type-band"]', { state: 'detached' });
  await sleep(300);
  await page.locator('#start').click();
  await page.waitForFunction(
    () => /腰头成带中/.test(document.querySelector('#status')?.textContent ?? ''),
    undefined, { timeout: 60000 });
  await page.screenshot({ path: DOCS + '/us015_mixed_band_stage.png' });
  check('stage「腰头成带中」+ 截图落 .docs', true);
  await page.waitForFunction(
    () => /完成/.test(document.querySelector('#status')?.textContent ?? ''),
    undefined, { timeout: 300000 });
  await sleep(800);   // 末帧渲染稳定（renderTick 节流）
  await page.screenshot({ path: DOCS + '/us015_mixed_band_final_seed0.png' });
  const statusText = await page.locator('#status').textContent();
  const m = /([\d.]+)%/.exec(statusText ?? '');
  const uiPct = m ? parseFloat(m[1]) : null;
  check('求解完成 + final 截图落 .docs', uiPct !== null, String(statusText).slice(0, 120));
  if (typeof abOnPct === 'number' && uiPct !== null) {
    check('终值对拍：UI 密度 == A/B on 臂 seed0（同配置同 seed 确定性）',
      Math.abs(uiPct - abOnPct) <= 0.05, `UI=${uiPct}% vs A/B=${abOnPct}%`);
  }

  // ---- 8) 末帧守恒（g05=14 腰 + g07=7 填料）+ 全消息无 WB_ 泄漏 ----
  const wsStat = await page.evaluate(() => {
    const logs = window.__wsLog ?? [];
    const frames = logs.map((s) => { try { return JSON.parse(s); } catch (e) { return null; } })
      .filter((mm) => mm && mm.type === 'frame' && Array.isArray(mm.placed_items));
    const last = frames.length ? frames[frames.length - 1].placed_items : [];
    const counts = {};
    for (const pi of last) counts[pi.id] = (counts[pi.id] || 0) + 1;
    let bandWaist = 0;
    let bandFiller = 0;
    for (const id of Object.keys(counts)) {
      if (/^g05_/.test(id)) bandWaist += counts[id];
      if (/^g07_/.test(id)) bandFiller += counts[id];
    }
    return { n_msgs: logs.length, wb_hits: logs.filter((s) => s.includes('WB_')).length,
             n_frames: frames.length, bandWaist, bandFiller };
  });
  check('末帧守恒：g05=14（7 码 P0 表）+ g07=7（填料 1/码）',
    wsStat.bandWaist === 14 && wsStat.bandFiller === 7,
    `g05=${wsStat.bandWaist} g07=${wsStat.bandFiller}`);
  check('前端 WS 全消息无 WB_ 泄漏', wsStat.n_msgs > 0 && wsStat.wb_hits === 0,
    `messages=${wsStat.n_msgs} frames=${wsStat.n_frames} wb_hits=${wsStat.wb_hits}`);
} catch (err) {
  check('脚本异常', false, String(err));
  await page.screenshot({ path: OUT + '/error.png' }).catch(() => {});
} finally {
  await browser.close();
}
writeFileSync(OUT + '/results.json', JSON.stringify({ results, abOnPct, abFill }, null, 2));
const failed = results.filter((r) => !r.ok);
console.log(failed.length === 0 ? '== US-015 浏览器验证 ALL PASS ==' : `== ${failed.length} FAIL ==`);
process.exit(failed.length === 0 ? 0 : 1);

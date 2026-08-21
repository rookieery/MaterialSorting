// US-014 浏览器验证 + 形态截图（Playwright + 系统 Chrome headless）。
// 前置：ms-web 在 :8000（已加载 5336 母版 intermediate）+ materialSorting-web 最新 build
// + A/B 报告 out/config_runs/_probes/band_accept_report.json（终值对拍数据源）。
// 链路：上传 5336 -> QtyMatrix 按 P0 表设量（7 双份 g 码整列 2 + 31->1/36->3）->
// 超排 Tab 勾 P0 七码 + 时长 120s -> 高级配置勾成带 g05 + ack -> 真实 WS 求解 ->
// stage 截图 -> final 截图（与 A/B on 臂 seed0 同配置同 seed，确定性 => 密度应相等）->
// UI 导出三格式（PNG/DXF/PLT 经 HTTP /export 真路径，下载落 out/us014_verify/）。
// 截图产物：.docs/business/us014_band_stage.png / us014_band_final_seed0.png（形态判据目测证据）。
import { chromium } from 'file:///D:/code/MaterialSorting/materialSorting-web/node_modules/playwright/index.mjs';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9_coded.dxf';
const OUT = 'D:/code/MaterialSorting/out/us014_verify';
const DOCS = 'D:/code/MaterialSorting/.docs/business';
const REPORT = 'D:/code/MaterialSorting/materialSorting-server/out/config_runs/_probes/band_accept_report.json';
mkdirSync(OUT, { recursive: true });
// A/B 报告 on 臂 seed0 密度（浏览器同配置同 seed -> 确定性对拍基准）
const ab = JSON.parse(readFileSync(REPORT, 'utf-8'));
const abOnSeed0 = ab.density_ab.per_seed.find((r) => r.seed === 0);
const abOnPct = abOnSeed0 && abOnSeed0.on && abOnSeed0.on.density_pct;
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
});
const P0_SIZES = [31, 32, 33, 34, 35, 36, 38];
const DOUBLE_LABELS = ['g01', 'g02', 'g03', 'g04', 'g05', 'g09', 'g10'];
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
  check('QtyMatrix P0 需求表（7 g 码整列 2 + 31/36 特例）', true);

  // ---- 3) 超排 Tab：P0 七码 + 时长 120s（与 A/B 同配置）----
  await page.getByRole('button', { name: '超排', exact: true }).click();
  await page.waitForSelector('.per-type-btn', { timeout: 15000 });
  for (const s of P0_SIZES) {
    const chip = page.locator(`#sz_${s}`);
    if (!(await chip.isChecked())) await chip.check();
  }
  for (const s of [28, 29, 30, 37]) {
    const chip = page.locator(`#sz_${s}`);
    if ((await chip.count()) > 0 && (await chip.isChecked())) await chip.uncheck();
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
  await page.waitForFunction(
    () => /带内预演：填充/.test(document.querySelector('[data-testid="band-preview"]')?.textContent ?? ''),
    undefined, { timeout: 30000 });
  await page.locator('.per-type-btn-confirm').click();
  await page.waitForSelector('[data-testid="per-type-band"]', { state: 'detached' });
  await sleep(300);
  check('成带 g05 配置确认（ack 硬警告流）', true);

  // ---- 5) 真实 WS 求解：stage 截图 -> final 截图（形态目测证据）----
  await page.locator('#start').click();
  await page.waitForFunction(
    () => /腰头成带中/.test(document.querySelector('#status')?.textContent ?? ''),
    undefined, { timeout: 60000 });
  await page.screenshot({ path: DOCS + '/us014_band_stage.png' });
  check('stage「腰头成带中」+ 截图落 .docs', true);
  await page.waitForFunction(
    () => /完成/.test(document.querySelector('#status')?.textContent ?? ''),
    undefined, { timeout: 300000 });
  await sleep(800);   // 末帧渲染稳定（renderTick 节流）
  await page.screenshot({ path: DOCS + '/us014_band_final_seed0.png' });
  const statusText = await page.locator('#status').textContent();
  const m = /([\d.]+)%/.exec(statusText ?? '');
  const uiPct = m ? parseFloat(m[1]) : null;
  check('求解完成 + final 截图落 .docs', uiPct !== null, String(statusText).slice(0, 120));
  if (typeof abOnPct === 'number' && uiPct !== null) {
    check('终值对拍：UI 密度 == A/B on 臂 seed0（同配置同 seed 确定性）',
      Math.abs(uiPct - abOnPct) <= 0.05, `UI=${uiPct}% vs A/B=${abOnPct}%`);
  }

  // ---- 6) UI 导出三格式（HTTP /export 真路径，band on 末帧 placements）----
  for (const fmt of ['png', 'dxf', 'plt']) {
    await page.locator('select.export-fmt').selectOption(fmt);
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 60000 }),
      page.locator('button.export').click(),
    ]);
    const dest = OUT + `/ui_export_seed0.${fmt}`;
    await download.saveAs(dest);
    const name = download.suggestedFilename();
    check(`UI 导出 ${fmt.toUpperCase()} 成功`, /\.png$|\.dxf$|\.plt$/.test(name), name);
  }
  // 末帧链路无 WB_ 泄漏：hook WebSocket 收到的全部消息（manifest/frame/final）grep
  const leak = await page.evaluate(() => {
    const logs = window.__wsLog ?? [];
    return { n_msgs: logs.length, wb_hits: logs.filter((s) => s.includes('WB_')).length };
  });
  check('前端 WS 全消息无 WB_ 泄漏', leak.n_msgs > 0 && leak.wb_hits === 0,
    `messages=${leak.n_msgs} wb_hits=${leak.wb_hits}`);
} catch (err) {
  check('脚本异常', false, String(err));
  await page.screenshot({ path: OUT + '/error.png' }).catch(() => {});
} finally {
  await browser.close();
}
writeFileSync(OUT + '/results.json', JSON.stringify({ results, abOnPct }, null, 2));
const failed = results.filter((r) => !r.ok);
console.log(failed.length === 0 ? '== US-014 浏览器验证 ALL PASS ==' : `== ${failed.length} FAIL ==`);
process.exit(failed.length === 0 ? 0 : 1);

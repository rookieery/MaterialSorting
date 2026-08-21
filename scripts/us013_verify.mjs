// US-013 浏览器验证（Playwright + 系统 Chrome headless）。
// 前置：ms-web 在 :8000（已加载 5336 母版 intermediate）+ materialSorting-web 最新 build。
// 链路：上传 5336 DXF -> QtyMatrix 设 g05@30=3（奇）g05@31=2（偶）-> 超排 Tab ->
// 选码号 -> 高级配置「布局设置」：勾选成带 + 选 g05 -> 预演 422 hard_warning ->
// ack 二次确认勾选 -> 带 ack 重试成功（fill 回显）-> 确定 -> 启动闸门/互斥断言 ->
// 真实 WS 求解（stage「腰头成带中」状态行）-> 收尾 -> 回上传预览页不成对徽章截图。
import { chromium } from 'file:///D:/code/MaterialSorting/materialSorting-web/node_modules/playwright/index.mjs';
import { mkdirSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9_coded.dxf';
const OUT = 'D:/code/MaterialSorting/out/us013_verify';
mkdirSync(OUT, { recursive: true });
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name + (detail ? '  -- ' + String(detail).slice(0, 200) : ''));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1560, height: 980 } });
// 跳过首次进入 Tab 的操作指引浮层（z-2000 全屏遮挡 clicks）：
// 预置 localStorage seen 标记（与 tourStore.hydrateSeen 同键口径，version=7）。
await page.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '7');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
try {
  // ---- 1) 上传 5336 DXF（multipart）-> 自动 commit ----
  await page.goto(APP, { waitUntil: 'networkidle' });
  await page.locator('input[type=file].upload-input-hidden').setInputFiles(DXF);
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 60000 });
  check('上传 + 自动 commit', true);

  // ---- 2) QtyMatrix：g05@30=3（奇）/ g05@31=2（偶）。band 未开 -> 无徽章 ----
  const cell = (label, size) =>
    page.locator('input.qty-cell-input[aria-label="裁片 ' + label + ' 码 ' + size + ' 数量"]');
  await cell('g05', '30').first().fill('3');
  await cell('g05', '31').first().fill('2');
  await page.keyboard.press('Enter');
  await sleep(300);
  check('band 未开 -> 无不成对徽章',
    (await page.locator('[data-testid="qty-odd-badge-g05"]').count()) === 0);

  // ---- 3) 超排 Tab -> 全选码号 -> 时长 8s ----
  await page.getByRole('button', { name: '超排', exact: true }).click();
  await page.waitForSelector('.per-type-btn', { timeout: 15000 });
  const chips = page.locator('.sizes input[type=checkbox]');
  const nChips = await chips.count();
  for (let i = 0; i < nChips; i++) if (!(await chips.nth(i).isChecked())) await chips.nth(i).check();
  await page.locator('#time').fill('8');
  check('超排 Tab + 码号全选', nChips > 0, 'chips=' + nChips);

  // ---- 4) 高级配置弹窗：布局设置分区（暗色主题）----
  await page.locator('.per-type-btn').click();
  await page.waitForSelector('[data-testid="per-type-band"]', { timeout: 15000 });
  await page.screenshot({ path: OUT + '/01_modal_band_idle.png' });
  const sectionTitle = await page.locator('.per-type-band-title').textContent();
  check('分区标题「布局设置」', sectionTitle === '布局设置', sectionTitle);
  check('未勾选 -> 下拉 disabled', await page.locator('[data-testid="band-label-select"]').isDisabled());
  const bg = await page.locator('.per-type-modal').evaluate((el) => getComputedStyle(el).backgroundColor);
  check('弹窗暗色主题 #26282e', bg === 'rgb(38, 40, 46)', bg);

  // ---- 5) 勾选成带 + 选 g05 -> 预演 422 hard_warning -> ack 勾选框 ----
  await page.locator('[data-testid="band-enabled"]').check();
  await page.locator('[data-testid="band-label-select"]').selectOption('g05');
  await sleep(1500);
  await page.waitForSelector('[data-testid="band-ack-wrap"]', { timeout: 30000 });
  const failText = await page.locator('[data-testid="band-preview"]').textContent();
  check('预演 422 hard_warning 降级提示', /长宽比 6\.9/.test(failText), String(failText).slice(0, 120));
  await page.screenshot({ path: OUT + '/02_modal_hard_warning.png' });
  check('g05 80x80 缩略图 + 徽章', (await page.locator('[data-testid="band-thumb-g05"]').count()) === 1);

  // ---- 6) 勾选 ack -> 带 ack 重试（5s 预算）-> fill 回显 ----
  await page.locator('[data-testid="band-ack"]').check();
  await page.waitForFunction(
    () => /带内预演：填充/.test(document.querySelector('[data-testid="band-preview"]')?.textContent ?? ''),
    { timeout: 30000 });
  const okText = await page.locator('[data-testid="band-preview"]').textContent();
  check('ack 重试 -> fill 回显', /带内预演：填充 [\d.]+%/.test(okText), String(okText).slice(0, 140));
  check('盈亏参考线对照', /盈亏参考线 62\.4~63\.6%/.test(okText));
  await page.screenshot({ path: OUT + '/03_modal_ack_preview_ok.png' });

  // ---- 7) 确定 -> 启动闸门 + 互斥 ----
  await page.locator('.per-type-btn-confirm').click();
  await page.waitForSelector('[data-testid="per-type-band"]', { state: 'detached' });
  await sleep(300);
  const startBtn = page.locator('#start');
  check('已选编号 + 数量非 0 -> 启动可用', !(await startBtn.isDisabled()));
  const strategy = page.locator('[data-testid="strategy-btn"]');
  check('band 开 -> 高级运行置灰 + title 互斥',
    (await strategy.isDisabled()) && /互斥/.test((await strategy.getAttribute('title')) ?? ''),
    await strategy.getAttribute('title'));

  // ---- 8) 真实 WS 求解 -> stage「腰头成带中」状态行 ----
  await startBtn.click();
  await page.waitForFunction(
    () => /腰头成带中/.test(document.querySelector('#status')?.textContent ?? ''),
    { timeout: 60000 });
  const stageStatus = await page.locator('#status').textContent();
  check('stage「腰头成带中」状态行', /腰头成带中：带内聚排/.test(stageStatus), String(stageStatus).slice(0, 120));
  await page.screenshot({ path: OUT + '/04_solve_stage_band.png' });
  await page.waitForFunction(
    () => /求解完成|已停止|停止/.test(document.querySelector('#status')?.textContent ?? '')
      || document.querySelector('#restart') !== null,
    { timeout: 120000 });
  await sleep(500);
  const finalStatus = await page.locator('#status').textContent();
  check('求解收尾', /密度|完成|停止/.test(finalStatus), String(finalStatus).slice(0, 140));
  await page.screenshot({ path: OUT + '/05_solve_final.png' });

  // ---- 9) 回上传预览 -> 不成对徽章（band 开 + g05@30=3 奇）----
  await page.getByRole('button', { name: '上传预览', exact: true }).click();
  await page.waitForSelector('[data-testid="qty-matrix"]', { timeout: 15000 });
  await sleep(400);
  const badge = page.locator('[data-testid="qty-odd-badge-g05"]');
  check('g05 列头「不成对」徽章', (await badge.count()) === 1);
  const oddCell = page.locator('td.qty-cell.odd input').first();
  const oddTitle = await oddCell.getAttribute('title');
  check('奇数格 title 该码不成对', /该码不成对/.test(oddTitle ?? ''), oddTitle);
  await page.screenshot({ path: OUT + '/06_qty_matrix_odd_badge.png' });

  // ---- 10) 互斥恢复：关 band -> 高级运行可用 ----
  await page.getByRole('button', { name: '超排', exact: true }).click();
  await page.waitForSelector('.per-type-btn', { timeout: 15000 });
  await page.locator('.per-type-btn').click();
  await page.waitForSelector('[data-testid="band-enabled"]', { timeout: 15000 });
  await page.locator('[data-testid="band-enabled"]').uncheck();
  await page.locator('.per-type-btn-confirm').click();
  await sleep(300);
  check('关 band -> 高级运行恢复可用', !(await page.locator('[data-testid="strategy-btn"]').isDisabled()));
  await page.screenshot({ path: OUT + '/07_mutex_restored.png' });
} catch (e) {
  check('执行异常', false, String(e).slice(0, 400));
  try { await page.screenshot({ path: OUT + '/99_error.png' }); } catch {}
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.ok);
console.log('\n==== US-013 浏览器验证: ' + (results.length - failed.length) + '/' + results.length + ' PASS ====');
failed.forEach((f) => console.log('FAILED: ' + f.name + ' -- ' + f.detail));
process.exit(failed.length ? 1 : 0);

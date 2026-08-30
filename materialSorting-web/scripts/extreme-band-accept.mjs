// 极限运行 band/prefix 透传端到端验收（2026-08-30；模板 smoke-extreme-run.mjs）：
//   1. 上传 5336 母版 → commit → 超排 Tab → 全选码号（默认数量 1/片/码）
//   2. 高级配置开启腰头成带 g05（真腰）→ 确定（关闭即保存）
//   3. 极限弹窗断言【新行为】：执行按钮可点（旧版置灰）+ extreme-layout-hint
//      状态行「将随排料参数生效：腰头成带 g05」
//   4. 自定义 16 分钟（960s ≥ 905 下限，预计 2 轮）→ 执行 → 202 → 进度态
//   5. 打印 sid + run_name（后续 curl 轮询 status 用；轮询即活性，会话不逐出）
// 环境前置：ms-web 已在 :8000（新代码），static/ 已 build。
import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE_URL ?? 'http://127.0.0.1:8000/';

let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '7');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page = await context.newPage();
const log = (s) => console.log(s);

try {
  await page.goto(BASE, { waitUntil: 'networkidle' });

  // 1. 上传 → parse → 自动 commit（等 commit-status.done 而非 parse done）。
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 60000 });
  const commitText = await page.locator('[data-testid="commit-status"].done').innerText();
  const nestingTab = page.locator('button.tab:not(.disabled)', { hasText: '超排' });
  await nestingTab.waitFor({ timeout: 60000 });
  log(`1 commit ok: ${commitText.replace(/\s+/g, ' ')}`);
  await nestingTab.click();
  await page.getByTestId('extreme-btn').waitFor({ timeout: 5000 });

  // 全选码号（默认数量 → 每片每码 1 份；band 单副本链可正常聚合）。
  const sizeIds = await page.locator('.sizes .chip input').evaluateAll((els) =>
    els.map((e) => e.id),
  );
  for (const id of sizeIds) {
    await page.locator(`#${id}`).check({ force: true });
  }
  log(`1b sizes checked: ${await page.locator('.sizes .chip input:checked').count()} of ${sizeIds.length}`);

  // 2. 高级配置 → 开腰头成带 g05 → 确定。
  await page.getByTestId('per-type-btn').click();
  await page.waitForSelector('.per-type-modal', { timeout: 5000 });
  await page.getByTestId('band-enabled').check();
  await page.getByTestId('band-label-select').selectOption('g05');
  await page.getByTestId('per-type-confirm').click();
  await page.waitForSelector('.per-type-modal', { state: 'detached', timeout: 5000 });
  log('2 band g05 enabled via advanced config');

  // 3. 极限弹窗新行为断言：可执行 + 状态行（旧版此处置灰 + extreme-layout-warning）。
  await page.getByTestId('extreme-btn').click();
  await page.waitForSelector('.strategy-modal', { timeout: 5000 });
  const hint = await page.getByTestId('extreme-layout-hint').innerText();
  if (!hint.includes('腰头成带 g05')) throw new Error(`状态行缺腰头成带 g05: ${hint}`);
  const execDisabled = await page.getByTestId('extreme-exec-btn').isDisabled();
  if (execDisabled) throw new Error('执行按钮仍置灰（拦截未解除）');
  log(`3 hint ok: ${hint}`);

  // 4. 自定义 16 分钟 → 预计 2 轮 → 执行 → 202。
  await page.getByTestId('extreme-preset-custom').click();
  const input = page.getByTestId('extreme-custom-input');
  await input.fill('16');
  const rounds = await page.getByTestId('extreme-rounds').innerText();
  if (!rounds.includes('预计 2 轮')) throw new Error(`轮数对拍失败: ${rounds}`);
  log(`4 rounds ok: ${rounds}`);
  await page.screenshot({ path: 'scripts/shot-extreme-band-config.png' });

  const startResp = page.waitForResponse(
    (r) => r.url().includes('/api/extreme/start'),
    { timeout: 15000 },
  );
  await page.getByTestId('extreme-exec-btn').click();
  const resp = await startResp;
  if (resp.status() !== 202) {
    throw new Error(`start 非 202: ${resp.status()} ${await resp.text()}`);
  }
  const body = await resp.json();
  log(`5 start 202: run_name=${body.run_name} pid=${body.pid}`);
  await page.waitForSelector('[data-testid="strategy-progress-title"]', { timeout: 30000 });
  const title = await page.getByTestId('strategy-progress-title').innerText();
  if (!title.includes('极限运行')) throw new Error(`进度标题异常: ${title}`);
  log(`6 progress ok: ${title}`);

  const sid = await page.evaluate(() => localStorage.getItem('ms_sid'));
  console.log(`SID=${sid}`);
  console.log(`RUN_NAME=${body.run_name}`);
  await page.screenshot({ path: 'scripts/shot-extreme-band-running.png' });
} catch (e) {
  await page.screenshot({ path: 'scripts/shot-extreme-band-fail.png' }).catch(() => {});
  console.error(`FAIL: ${e.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}

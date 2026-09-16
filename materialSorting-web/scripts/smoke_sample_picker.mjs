// 样例功能 UI 冒烟（playwright，手动脚本不入 vitest；模板 = smoke-band-preview.mjs）：
//   1. 上传预览页左侧出现「样例」区块（h2 与「DXF 上传预览」同级）+ select 6 选项
//   2. 默认选中第一个（data/ 排序 = 3069 母版）
//   3. 点「应用」→ 走 /api/samples/file + /api/parse-dxf + /api/commit-to-nesting
//      → 面板状态行「已解析 N 码」「已应用至超排」+ 数量矩阵出现 + 超排 Tab 解锁
import { chromium } from 'playwright';

let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
// 预置引导层已读（TOUR_VERSION='8'），避免 tour-overlay 拦截点击
await context.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '8');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page = await context.newPage();
const log = (s) => console.log(s);
const fail = (msg) => {
  console.error(`FAIL: ${msg}`);
  process.exitCode = 1;
};

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });

// 1. 样例区块存在 + 标题同级
const section = page.locator('[data-testid="sample-section"]');
await section.waitFor({ timeout: 8000 });
const h2s = await page.locator('.upload-panel h2').allInnerTexts();
log(`1 sample section ok; panel h2s = ${JSON.stringify(h2s)}`);
if (!h2s.includes('样例') || !h2s.some((t) => t.includes('DXF'))) fail('h2 同级断言不过');

// 2. select 选项 = data/ 全部 dxf，默认第一个
const select = page.locator('[data-testid="sample-select"]');
await page.waitForFunction(() => {
  const el = document.querySelector('[data-testid="sample-select"]');
  return el && el.options.length > 1;
}, { timeout: 8000 });
const options = await select.locator('option').allInnerTexts();
const selected = await select.inputValue();
log(`2 options(${options.length}): ${JSON.stringify(options.map((o) => o.slice(0, 18)))}`);
log(`  default selected = ${selected.slice(0, 30)}`);
if (options.length !== 6) fail(`期望 6 个样例，实际 ${options.length}`);
if (selected !== options[0]) fail('默认未选中第一个');

// 3. 应用 → parse + commit 全链路（等待数量矩阵出现 = parse done）
const applyBtn = page.locator('[data-testid="sample-apply"]');
await applyBtn.click();
await page.waitForSelector('.qty-matrix', { timeout: 60000 });
log('3 qty-matrix appeared after apply');
const uploadDone = await page.locator('[data-testid="upload-status"]').allInnerTexts();
log(`  upload-status: ${JSON.stringify(uploadDone)}`);
await page.waitForSelector('[data-testid="commit-status"]', { timeout: 60000 });
await page.waitForFunction(() => {
  const els = document.querySelectorAll('[data-testid="commit-status"]');
  return Array.from(els).some((e) => e.textContent && e.textContent.includes('已应用至超排'));
}, { timeout: 60000 });
const commitText = await page.locator('[data-testid="commit-status"]').last().innerText();
log(`  commit-status: ${commitText}`);
const sampleError = await page.locator('[data-testid="sample-error"]').count();
if (sampleError > 0) fail(`样例区块报错: ${await page.locator('[data-testid="sample-error"]').innerText()}`);
// 解析出的文件名 = 选中样例名
const filenameShown = await page.locator('.upload-filename').innerText();
if (filenameShown !== selected) fail(`解析文件名 ${filenameShown} ≠ 选中样例 ${selected}`);

// 4. 超排 Tab 解锁（commit done 联动）
const nestingTab = page.locator('button.tab', { hasText: '超排' });
const tabEnabled = await nestingTab.isEnabled();
log(`4 超排 tab enabled = ${tabEnabled}`);
if (!tabEnabled) fail('超排 Tab 未解锁');

await page.screenshot({ path: 'scripts/shot-sample-picker.png', fullPage: false });
log(`PASS 判定: ${process.exitCode ? 'FAIL' : 'ALL OK'}`);
await browser.close();

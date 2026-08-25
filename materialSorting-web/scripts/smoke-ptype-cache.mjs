// 高级配置弹窗代表裁片会话缓存冒烟（playwright，手动脚本不入 vitest；2026-08-25）：
//   1. 上传母版 commit → 切超排 Tab
//   2. 开高级配置弹窗 → /api/ptypes 请求 1 次 + 缩略图渲染
//   3. 关闭重开 → 零新请求 + 缩略图立即渲染（无「…」闪烁）
//   4. 表头缩略图点开放大预览 → 零新请求（共享同一份缓存）
//   5. （后端换 commit 才失效，此处不覆盖 —— 单测已锁 invalidate 语义）
import { chromium } from 'playwright';

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

let ptypesCalls = 0;
page.on('request', (req) => {
  if (req.url().includes('/api/ptypes')) ptypesCalls += 1;
});

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });

const fileInput = page.locator('input[type="file"]');
await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
await page.waitForTimeout(3000);
for (const text of ['提交排料', '确认提交', 'commit']) {
  const btn = page.locator('button', { hasText: text });
  if (await btn.count()) {
    await btn.first().click();
    break;
  }
}
await page.waitForTimeout(3000);

await page.locator('button.tab', { hasText: '超排' }).click();

// ① 首开：1 次 /api/ptypes + 缩略图渲染
await page.getByTestId('per-type-btn').click();
await page.waitForSelector('.per-type-modal', { timeout: 5000 });
await page.waitForSelector('.ptype-thumb svg.piece-preview-svg', { timeout: 10000 });
const callsAfterFirst = ptypesCalls;
const thumbs = await page.locator('.ptype-thumb svg.piece-preview-svg').count();
log(`1 first-open: ptypesCalls=${callsAfterFirst} thumbs=${thumbs}`);
await page.screenshot({ path: 'scripts/shot-ptype-cache-first.png' });

// ② 关闭（ESC 即保存关闭）→ 重开：零新请求 + 缩略图立即在场（不等 networkidle，
//    立刻数 SVG —— 缓存命中应同步渲染，无「…」占位过程）
await page.keyboard.press('Escape');
await page.waitForSelector('.per-type-modal', { state: 'detached', timeout: 3000 });
await page.getByTestId('per-type-btn').click();
await page.waitForSelector('.per-type-modal', { timeout: 5000 });
const thumbsImmediate = await page.locator('.ptype-thumb svg.piece-preview-svg').count();
await page.waitForTimeout(800);
const callsAfterReopen = ptypesCalls;
log(`2 reopen: thumbsImmediate=${thumbsImmediate} ptypesCalls=${callsAfterReopen} (delta=${callsAfterReopen - callsAfterFirst})`);
await page.screenshot({ path: 'scripts/shot-ptype-cache-reopen.png' });

// ③ 放大预览（表头缩略图点击）→ 共享缓存，零新请求
const firstThumb = page.locator('.ptype-thumb:not([disabled])').first();
await firstThumb.click();
await page.waitForSelector('.ptype-preview-modal', { timeout: 5000 });
await page.waitForTimeout(800);
const callsAfterZoom = ptypesCalls;
const zoomSvg = await page.locator('.ptype-preview-modal svg.piece-preview-svg').count();
log(`3 zoom: svg=${zoomSvg} ptypesCalls=${callsAfterZoom} (delta=${callsAfterZoom - callsAfterReopen})`);

await browser.close();
const pass = callsAfterFirst === 1 && callsAfterReopen === callsAfterFirst &&
  callsAfterZoom === callsAfterFirst && thumbsImmediate === thumbs && thumbs > 0;
log(pass ? 'SMOKE PASS' : 'SMOKE FAIL');
process.exit(pass ? 0 : 1);

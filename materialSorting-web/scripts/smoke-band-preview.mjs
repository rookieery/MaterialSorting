// 成带预览 UI 冒烟（playwright，手动脚本不入 vitest）：
//   1. 打开高级配置 → 布局设置勾选腰头成带、选 g05 → 缩略图渲染（band-thumb-g05 + 成员/轮廓 SVG）
//   2. 点击缩略图 → 放大弹窗（.band-zoom-modal + 统计行 + 尺码标注）
//   3. ESC 只关放大层，底层 modal 仍在
//   4. 切换 g 码到 g02（成带失败）→ 错误态展示
import { chromium } from 'playwright';

// 本机没下 playwright 浏览器二进制，借系统通道（Edge Win11 必有，Chrome 兜底）
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
// 预置引导层已读（TOUR_VERSION='7'），避免 tour-overlay 拦截点击
await context.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '7');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page = await context.newPage();
const log = (s) => console.log(s);

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });

// doc 是内存态（新 profile 为空 → 超排 Tab 禁用）→ 走真实上传流程：
// 上传页选 5336 母版 → parse → commit（网关 /api/parse-dxf + /api/commit-to-nesting）
const fileInput = page.locator('input[type="file"]');
await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
// 等 parse 响应渲染（数量矩阵出现）再 commit（按钮文案以实际为准，兜底两种）
await page.waitForTimeout(3000);
for (const text of ['提交排料', '确认提交', 'commit']) {
  const btn = page.locator('button', { hasText: text });
  if (await btn.count()) {
    await btn.first().click();
    break;
  }
}
await page.waitForTimeout(3000);

// 切「超排」Tab（ControlPanel 在排料页）
await page.locator('button.tab', { hasText: '超排' }).click();
await page.getByTestId('per-type-btn').click();
await page.waitForSelector('.per-type-modal', { timeout: 5000 });
log('1 modal open');

// 布局设置：勾选 + 选 g05（原生 checkbox/select，forced click 绕开覆盖层）
const bandCheck = page.locator('.per-type-modal input[type="checkbox"]');
await bandCheck.check({ force: true });
await page.locator('.per-type-modal select').selectOption('g05');
const thumb = page.locator('[data-testid="band-thumb-g05"]');
await thumb.waitFor({ timeout: 10000 });
const nMembers = await thumb.locator('[data-role="band-member"]').count();
const hasOutline = await thumb.locator('[data-role="band-outline"]').count();
const stats = await thumb.locator('.per-type-band-thumb-meta, .band-thumb-stats').count();
log(`2 thumb ok: members=${nMembers} outline=${hasOutline} statsNodes=${stats}`);
await page.screenshot({ path: 'scripts/shot-band-thumb.png' });

// 点击放大
await thumb.click();
await page.waitForSelector('.band-zoom-modal', { timeout: 5000 });
const zoomMembers = await page.locator('.band-zoom-modal [data-role="band-member"]').count();
const zoomLabels = await page.locator('.band-zoom-modal [data-role="band-size-label"]').count();
const zoomText = (await page.locator('.band-zoom-modal').innerText()).replace(/\s+/g, ' ').slice(0, 160);
log(`3 zoom ok: members=${zoomMembers} labels=${zoomLabels} | ${zoomText}`);
await page.screenshot({ path: 'scripts/shot-band-zoom.png' });

// ESC 只关放大层
await page.keyboard.press('Escape');
await page.waitForSelector('.band-zoom-modal', { state: 'detached', timeout: 3000 });
const modalStill = await page.locator('.per-type-modal').count();
log(`4 esc: zoom closed, modal still=${modalStill === 1}`);

// 切 g02 → 成功换 band-thumb-g02 或失败 data-testid="band-thumb-error"
await page.locator('.per-type-modal select').selectOption('g02');
await page.waitForTimeout(2500);
const errNode = await page.locator('[data-testid="band-thumb-error"]').count();
const g02Thumb = await page.locator('[data-testid="band-thumb-g02"]').count();
const errText = errNode ? (await page.locator('[data-testid="band-thumb-error"]').innerText()).replace(/\s+/g, ' ').slice(0, 100) : '';
log(`5 g02: error-state=${errNode} thumb=${g02Thumb} ${errText}`);
await page.screenshot({ path: 'scripts/shot-band-state.png' });

await browser.close();
log('SMOKE DONE');

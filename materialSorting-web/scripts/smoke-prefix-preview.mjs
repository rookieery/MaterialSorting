// 前缀组合形态预览 UI 冒烟（playwright，手动脚本不入 vitest；smoke-band-preview 同套路）：
//   1. 上传 5336 母版 → 数量矩阵整列设值 g02=2 / g03=2（造 2+2 资格码）
//   2. 高级配置 → 布局设置勾选「起始端成套前后幅」→ 默认预选 g02/g03 → 组合预览缩略
//      （prefix-thumb-g02+g03 + 4 成员/轮廓 SVG；不再有单片 prefix-thumb-g02/g03）
//   3. 点击缩略 → 放大弹窗（.band-zoom-modal 复用 + 统计行 + 成员 g 码标注 tag）
//   4. ESC 只关放大层，底层 modal 仍在
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

// doc 是内存态（新 profile 为空 → 超排 Tab 禁用）→ 走真实上传流程
const fileInput = page.locator('input[type="file"]');
await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
await page.waitForSelector('[data-testid="qty-matrix"]', { timeout: 20000 });
log('1 uploaded + parsed (qty matrix visible)');

// 仅首个码（5336 首行 = 30）设 g02=2 / g03=2（格子 input，aria-label 定位）——
// 造出恰一个 2+2 资格码（整列设值会让所有码 eligible，seeded 选码可能挑中大码 →
// 4 片竖排超高误报错误态）
const firstSize = await page
  .locator('.qty-matrix tbody .qty-size-btn')
  .first()
  .innerText();
for (const label of ['g02', 'g03']) {
  const cell = page.locator(`input[aria-label="裁片 ${label} 码 ${firstSize.trim()} 数量"]`);
  await cell.fill('2');
  await cell.press('Enter');
  await page.waitForTimeout(200);
}
log(`2 qty matrix: size${firstSize.trim()} g02=2 g03=2 (one eligible size)`);

// 切「超排」Tab → 先勾选码号（SizePicker 空选 → serializeQuantities 发 null，
// 预览会误报「无 2+2 资格码」—— 与求解闸门同语义，冒烟需真实选码）
await page.locator('button.tab', { hasText: '超排' }).click();
await page.locator(`.panel input#sz_${firstSize.trim()}`).check({ force: true });
await page.getByTestId('per-type-btn').click();
await page.waitForSelector('.per-type-modal', { timeout: 5000 });

// 勾选「起始端成套前后幅」→ 默认预选面积最大两片（5336 = g02/g03）
await page.locator('[data-testid="prefix-enabled"]').check({ force: true });
const front = await page.locator('[data-testid="prefix-front-select"]').inputValue();
const back = await page.locator('[data-testid="prefix-back-select"]').inputValue();
log(`3 prefix enabled: front=${front} back=${back}`);
if (front === '' || back === '') {
  // 默认预选缺席兜底：手选 g02/g03
  await page.locator('[data-testid="prefix-front-select"]').selectOption('g02');
  await page.locator('[data-testid="prefix-back-select"]').selectOption('g03');
}

// 组合形态预览缩略（三态之 ok）；单片缩略已删（prefix-thumb-g02/g03 不存在）
const thumb = page.locator('[data-testid="prefix-thumb-g02+g03"]');
const errNode = page.locator('[data-testid="prefix-thumb-error"]');
await Promise.race([
  thumb.waitFor({ timeout: 15000 }),
  errNode.waitFor({ timeout: 15000 }),
]).catch(() => {});
if ((await errNode.count()) && !(await thumb.count())) {
  // 瞬态（effect 清空 ↔ 新 fetch 落定之间）兜底：等 1.2s 再读终态
  await page.waitForTimeout(1200);
}
if ((await errNode.count()) && !(await thumb.count())) {
  log(`4 ERROR state: ${(await errNode.innerText()).replace(/\s+/g, ' ').slice(0, 200)}`);
  await page.screenshot({ path: 'scripts/shot-prefix-error.png' });
  await browser.close();
  process.exit(1);
}
await thumb.waitFor({ timeout: 5000 });
const nMembers = await thumb.locator('[data-role="band-member"]').count();
const hasOutline = await thumb.locator('[data-role="band-outline"]').count();
const badge = await thumb.locator('.qty-label-badge').innerText();
log(`4 thumb ok: members=${nMembers} outline=${hasOutline} badge=${badge}`);
await page.screenshot({ path: 'scripts/shot-prefix-thumb.png' });

// 点击放大 → prefix-zoom（.band-zoom-modal 复用；标注 = 成员 g 码 tag）
await thumb.click();
await page.waitForSelector('[data-testid="prefix-zoom-overlay"]', { timeout: 5000 });
const zoomMembers = await page.locator('[data-testid="prefix-zoom-overlay"] [data-role="band-member"]').count();
const labels = await page
  .locator('[data-testid="prefix-zoom-overlay"] [data-role="band-size-label"]')
  .allInnerTexts();
const zoomText = (await page.locator('[data-testid="prefix-zoom-overlay"]').innerText())
  .replace(/\s+/g, ' ')
  .slice(0, 200);
log(`5 zoom ok: members=${zoomMembers} labels=${JSON.stringify(labels)} | ${zoomText}`);
await page.screenshot({ path: 'scripts/shot-prefix-zoom.png' });

// ESC 只关放大层
await page.keyboard.press('Escape');
await page.waitForSelector('[data-testid="prefix-zoom-overlay"]', { state: 'detached', timeout: 3000 });
const modalStill = await page.locator('.per-type-modal').count();
log(`6 esc: zoom closed, modal still=${modalStill === 1}`);
await page.screenshot({ path: 'scripts/shot-prefix-final.png' });

await browser.close();
log('SMOKE DONE');

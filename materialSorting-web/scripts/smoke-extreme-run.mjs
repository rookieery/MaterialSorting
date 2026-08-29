// 极限运行入口 UI 冒烟（playwright，手动脚本不入 vitest；模板 smoke-band-preview.mjs）：
//   1. 上传 5336 母版 → commit → 切「超排」Tab → 「极限运行」按钮在场（与高级运行并排）
//   2. 打开弹窗：默认 120 分钟选中；预设/预计轮数对拍（公式 N = 1 + floor((T-602.5)/347.5)：
//      60min→9 / 120min→19 / 240min→40，与 ExtremeRunModal.estimateExtremeRounds 同式实现）
//   3. 发起（60 分钟档）→ 轮询出现 starting/running（标题「极限运行」+ 入口徽标）
//   4. 等首帧密度出现 → 终止 → stopped 终态（结果态/占位均可，产物树已由后端清理标记）
// 环境前置：ms-web 已在 :8000（prod 模式需先 npm run build —— static/ 为构建产物）；
//   BASE_URL 可覆写（dev 模式 npm run dev :5173 经 Vite proxy 亦可）。
import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE_URL ?? 'http://127.0.0.1:8000/';
const FIRST_ROUND_S = 602.5;
const PER_ROUND_S = 347.5;
const expectRounds = (sec) => Math.max(1, 1 + Math.floor((sec - FIRST_ROUND_S) / PER_ROUND_S));

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
let stopped = false;

try {
  await page.goto(BASE, { waitUntil: 'networkidle' });

  // 1. 上传母版 → parse → 自动 commit（US-021：解析成功即自动 commit，无手动按钮）。
  //    注意：超排 Tab 解锁联动的是 **parse done**（PreviewPage subscribe），commit
  //    POST 仍可能在途 —— start 时会话 pieces 快照未注册 → 后端 422「排料数据为空」。
  //    故先等 commit 完成指示（UploadPanel「已应用至超排：N 裁片，M 码」暗绿底，
  //    US-001 页面 display:none 不卸载、DOM 常驻可等）再点 Tab。
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
  //（注意 `.upload-status.done` 同时命中 parse-done 与 commit-done 两个元素，
  //  须按 commit-status testid 精确等「已应用至超排」）
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 60000 });
  const commitText = await page.locator('[data-testid="commit-status"].done').innerText();
  const nestingTab = page.locator('button.tab:not(.disabled)', { hasText: '超排' });
  await nestingTab.waitFor({ timeout: 60000 });
  log(`1 commit ok: ${commitText.replace(/\s+/g, ' ')}`);
  await nestingTab.click();
  await page.getByTestId('strategy-btn').waitFor({ timeout: 5000 });
  await page.getByTestId('extreme-btn').waitFor({ timeout: 5000 });
  log('1 entries ok: strategy-btn + extreme-btn both present');

  // 勾选码号（US-017 起 DEFAULT_FORM.sizes 为空 —— 执行按钮按 sizes 空禁用）：
  // 勾母版前两个码（数量矩阵未配置 → 每片每码 1 份默认）。chip input id = `sz_<key>`。
  const sizeIds = await page.locator('.sizes .chip input').evaluateAll((els) =>
    els.map((e) => e.id),
  );
  for (const id of sizeIds.slice(0, 2)) {
    await page.locator(`#${id}`).check({ force: true });
  }
  const nChecked = await page.locator('.sizes .chip input:checked').count();
  log(`1b sizes checked: ${nChecked} of ${sizeIds.length}`);

  // 2. 打开弹窗：默认 120 分钟 + 轮数对拍（60/240 与公式对拍）
  await page.getByTestId('extreme-btn').click();
  await page.waitForSelector('.strategy-modal', { timeout: 5000 });
  const active = await page.locator('.extreme-preset-btn.active').innerText();
  const roundsText = () => page.getByTestId('extreme-rounds').innerText();
  let t = await roundsText();
  if (!t.includes(`预计 ${expectRounds(120 * 60)} 轮`)) throw new Error(`默认档轮数对拍失败: ${t}`);
  if (!active.includes('2 小时')) throw new Error(`默认预设不是 120 分钟: ${active}`);
  for (const m of [60, 240]) {
    await page.getByTestId(`extreme-preset-${m}`).click();
    t = await roundsText();
    if (!t.includes(`预计 ${expectRounds(m * 60)} 轮`)) throw new Error(`${m}min 轮数对拍失败: ${t}`);
  }
  log(`2 presets ok: 120min default=${expectRounds(7200)}轮 60min=${expectRounds(3600)}轮 240min=${expectRounds(14400)}轮`);
  await page.screenshot({ path: 'scripts/shot-extreme-config.png' });

  // 3. 发起（60 分钟档 = 最短预设；随后早停）→ starting/running
  await page.getByTestId('extreme-preset-60').click();
  await page.getByTestId('extreme-exec-btn').click();
  await page.waitForSelector('[data-testid="strategy-progress-title"]', { timeout: 20000 });
  const title = await page.getByTestId('strategy-progress-title').innerText();
  if (!title.includes('极限运行')) throw new Error(`进度标题缺「极限运行」: ${title}`);
  await page.getByTestId('extreme-badge').waitFor({ timeout: 10000 });
  const stage = await page.getByTestId('strategy-stage').innerText().catch(() => '—');
  log(`3 started: title="${title.replace(/\s+/g, ' ')}" stage="${stage.replace(/\s+/g, ' ')}" badge=运行中`);

  // 4. 等首帧密度（incumbent/current 任一）→ 终止 → 结果态（stopped 回落 best_frame）
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[data-testid="strategy-big-density"]');
      return el && el.textContent && el.textContent !== '—' && el.textContent !== '';
    },
    { timeout: 240000, polling: 2000 },
  );
  const best = await page.getByTestId('strategy-big-density').innerText();
  await page.screenshot({ path: 'scripts/shot-extreme-running.png' });
  await page.getByTestId('strategy-stop-btn').click();
  stopped = true;
  // 结果态（stopped 回落 best_frame 最优；「正在读取运行结果…」是 result 拉取中的
  // 瞬态 —— 等真正的结果头落地）。
  await page.waitForSelector('[data-testid="strategy-result-head"]', { timeout: 30000 });
  const finalState = await page.getByTestId('strategy-result-head').innerText();
  const extraHint = await page.getByTestId('strategy-result-extra-hint').innerText().catch(() => '');
  log(`4 stopped ok: first-frame best=${best} final="${finalState.replace(/\s+/g, ' ')}" hint="${extraHint}"`);
  await page.screenshot({ path: 'scripts/shot-extreme-result.png' });
  log('SMOKE DONE');
} finally {
  // 兜底清理：异常退出也绝不留跑着的极限 run（同会话单飞槽会被占住）
  if (!stopped) {
    await page.getByTestId('strategy-stop-btn').click().catch(() => {});
  }
  await browser.close();
}

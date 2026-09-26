// 用时显示 UI 冒烟（playwright，手动脚本不入 vitest）：
//   1. 上传 5336 母版 → commit → 切「超排」Tab → 普通运行（默认 120s 单 seed）
//   2. 运行中多次采样 .nest-label：用时段存在且随时间增长（manifest 片数阶段也要有）
//   3. 完成后采样：用时段定格（与运行中最后采样解耦，不再增长）且 ≈ final.elapsed
import { chromium } from 'playwright';

let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '8');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page = await context.newPage();
const log = (s) => console.log(s);
let fail = 0;
const check = (name, ok, detail = '') => {
  log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' | ' + detail : ''}`);
  if (!ok) fail += 1;
};

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
await page.locator('input[type="file"]').setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
await page.waitForTimeout(3000);
for (const text of ['提交排料', '确认提交', 'commit']) {
  const btn = page.locator('button', { hasText: text });
  if (await btn.count()) {
    await btn.first().click();
    break;
  }
}
await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 240000 });
await page.locator('button.tab:not([disabled]):has-text("超排")').click();
await page.waitForTimeout(800);
// 勾 3 码（启动按钮置灰 = 码号未选）+ 时长 20s（快速冒烟）
for (const sz of [32, 33, 34]) await page.check('#sz_' + sz);
await page.fill('#time', '20');
log('1 uploaded + committed + nesting tab');

// 启动普通运行
await page.click('#start');
await page.locator('.nest-label').first().waitFor({ timeout: 20000 });
log('2 solve started, nest-label present');

// 运行中采样：用时段存在且单调增长
const readLabel = async () =>
  (await page.locator('.nest-label').first().innerText()).trim();
const elapsedOf = (text) => {
  const m = text.match(/用时 (\d+) 秒/);
  return m ? +m[1] : null;
};
const s1 = await readLabel();
await page.waitForTimeout(4000);
const s2 = await readLabel();
await page.waitForTimeout(5000);
const s3 = await readLabel();
log(`  samples: [${s1}] -> [${s2}] -> [${s3}]`);
check('3a 运行中每条 label 都带用时段', [s1, s2, s3].every((t) => t.includes('用时')), s1);
const e1 = elapsedOf(s1), e2 = elapsedOf(s2), e3 = elapsedOf(s3);
check(
  '3b 用时随时间增长（+4s / +5s 采样）',
  e1 !== null && e2 !== null && e3 !== null && e2 > e1 && e3 > e2,
  `${e1} -> ${e2} -> ${e3}`,
);

// 等完成（20s 预算 + spawn 余量；状态行「完成：seed 0」）
await page.locator('text=/完成：seed 0/').waitFor({ timeout: 120000 });
await page.waitForTimeout(2500); // 让 final 落笔 + 若干次 renderTick bump
const done1 = await readLabel();
await page.waitForTimeout(4000); // done 后再等 4s，确认定格
const done2 = await readLabel();
log(`  done: [${done1}] vs +4s [${done2}]`);
const d1 = elapsedOf(done1), d2 = elapsedOf(done2);
check('4a 完成态用时段在场（用时 N 秒）', d1 !== null, done1);
check('4b 完成后定格不再增长', d1 !== null && d2 !== null && d1 === d2, `${d1} vs ${d2}`);
check('4c 定格值量级合理（≥20s 求解预算，<60s）', d1 !== null && d1 >= 20 && d1 < 60, `elapsed=${d1}s`);
await page.screenshot({ path: 'scripts/shot-elapsed-label.png' });

await browser.close();
log(fail === 0 ? 'SMOKE DONE (all pass)' : `SMOKE DONE (${fail} FAIL)`);
process.exit(fail === 0 ? 0 : 1);

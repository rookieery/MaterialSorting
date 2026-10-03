// prd-initial-layout US-006（2026-10-03）InitialLayoutModal 弹窗浏览器验证（playwright，
// 手动脚本不入 vitest；模板 = us004_il_entry_verify.mjs + us005_gesture_verify.mjs 拖片）。
//
// 前置：ms-web 在 $MS_WEB_URL（缺省 http://127.0.0.1:8010，prod 模式需先
// npm run build）；样例母版在 data/（sample-apply 走真实 parse+commit 管线）。
//
// 相位（PRD 验收：生成→编辑→保存闸→刷新确认→伪卡片出现在 NestsGrid 且不进 bestRun）：
//   A 打开自动生成：无 saved → busy 浮层（生成中）+ ✕/刷新/保存全禁 → 生成请求
//     seed=0 → 画布片落场 + 状态条料长/利用率回显（无 Δ 行）；
//   B 编辑 dirty：拖片右移 → ✕ 弹「放弃未保存的修改？」→ 取消保持；
//   C 刷新确认：布局刷新 → 「将丢弃当前编辑」→ 重新生成（seed=1）→ busy → 画布
//     重落（编辑被丢弃、delta 基线重置）；
//   D 保存闸：拖片 B 压到片 A 上（红色非法重叠）→ 保存 disabled + 数量提示；
//     再刷新（seed=2）恢复合法 → 保存 enabled；
//   E 保存：伪卡片「初始布局（未求解）」挂进 NestsGrid + 导出按钮保持 disabled
//     （仅伪卡片 = 未求解不可导出，bestRun 不受污染）；
//   F 续编：重开弹窗 → 零生成请求（saved 新鲜）+ 画布即刻回显。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/us006_il_modal';
mkdirSync(OUT, { recursive: true });

const MS_WEB_URL = process.env.MS_WEB_URL ?? 'http://127.0.0.1:8010';

const results = [];
function check(name, ok, extra) {
  results.push({ name, ok });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 160) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const { chromium } = await import('playwright');
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

/** 生成请求观测（URL + body seed）。 */
const genReqs = [];
page.on('request', (req) => {
  if (req.url().includes('/api/initial-layout/generate')) {
    let seed = null;
    try {
      seed = JSON.parse(req.postData() ?? '{}').seed ?? null;
    } catch { /* ignore */ }
    genReqs.push({ url: req.url(), seed });
  }
});

const OVERLAY = '[data-testid="initial-layout-overlay"]';

/** 样例载入解锁超排 Tab（us004 gotoNesting 同款）。 */
async function gotoNesting() {
  await page.locator('[data-testid="sample-apply"]').click();
  await page.waitForFunction(() => {
    const els = document.querySelectorAll('[data-testid="commit-status"]');
    return Array.from(els).some((e) => e.textContent && e.textContent.includes('已应用至超排'));
  }, { timeout: 90000 });
  await page.locator('button.tab', { hasText: '超排' }).click();
  await page.locator('[data-testid="initial-layout-btn"]').waitFor({ state: 'visible', timeout: 8000 });
  await sleep(300);
}

/** 画布片落场等待（生成 ~10s + 余量）。 */
async function waitCanvas(timeoutMs = 45000) {
  await page.waitForFunction(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    return svg != null && svg.querySelectorAll(':scope g > polygon').length > 0;
  }, { timeout: timeoutMs });
}

/**
 * 重生成等待：busy 浮层**先起后落**完整周期 + 画布片在场。旧画布在生成在飞期间
 * 保持渲染（run 不置空），waitCanvas 单用会瞬时返回旧帧 —— 拖片会被随后落场的
 * 新 working 清掉（首版脚本实测竞态），故重生成后必须走本帮助函数。
 */
async function waitRegen(timeoutMs = 45000) {
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'visible', timeout: 8000 });
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'hidden', timeout: timeoutMs });
  await waitCanvas(5000);
  await sleep(300); // EditCanvas 首帧计数/标记回填
}

/** 片 k 的屏幕中心 + 视图比尺（px/mm）。 */
async function pieceInfo(idx) {
  return page.evaluate((i) => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    const polys = svg.querySelectorAll(':scope g > polygon');
    const pr = polys[i].getBoundingClientRect();
    const sr = svg.getBoundingClientRect();
    const vb = svg.getAttribute('viewBox').split(' ').map(Number);
    const s = Math.min(sr.width / vb[2], sr.height / vb[3]);
    return { cx: pr.x + pr.width / 2, cy: pr.y + pr.height / 2, s, n: polys.length };
  }, idx);
}

/** 屏幕像素直拖（把片 idx 拖到 (tx,ty) 屏幕坐标）。 */
async function dragTo(idx, tx, ty) {
  const info = await pieceInfo(idx);
  await page.mouse.move(info.cx, info.cy);
  await page.mouse.down();
  await page.mouse.move(tx, ty, { steps: 8 });
  await sleep(40);
  await page.mouse.up();
  await sleep(120);
}

/** 保存闸提示文字（无 → null）。 */
async function saveHint() {
  const el = page.locator('[data-testid="initial-layout-save-hint"]');
  return (await el.count()) > 0 ? ((await el.textContent()) ?? '').trim() : null;
}

try {
  // ---- A 打开自动生成
  await page.goto(MS_WEB_URL + '/', { waitUntil: 'networkidle' });
  await gotoNesting();
  await page.locator('[data-testid="initial-layout-btn"]').click();
  await page.locator(OVERLAY).waitFor({ state: 'visible', timeout: 5000 });
  check('A 弹窗打开（initial-layout-overlay）', true);
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'visible', timeout: 5000 });
  check('A busy 浮层（生成中）', true);
  check(
    'A busy 期三按钮全禁',
    (await page.locator('[data-testid="initial-layout-close"]').isDisabled()) &&
      (await page.locator('[data-testid="initial-layout-refresh"]').isDisabled()) &&
      (await page.locator('[data-testid="initial-layout-save"]').isDisabled()),
  );
  await page.screenshot({ path: OUT + '/01_busy.png' });

  await waitCanvas();
  check('A 画布片落场（生成 ~10s）', true);
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'hidden', timeout: 5000 });
  check('A busy 退场', true);
  check('A 生成请求恰好 1 次 + seed=0', genReqs.length === 1 && genReqs[0].seed === 0, JSON.stringify(genReqs));
  const widthText = ((await page.locator('[data-testid="initial-layout-width"]').textContent()) ?? '').trim();
  check('A 状态条料长回显', /料长 \d+ mm/.test(widthText), widthText);
  const densityText = ((await page.locator('[data-testid="initial-layout-density"]').textContent()) ?? '').trim();
  check('A 状态条利用率回显', /利用率 \d+\.\d+%/.test(densityText), densityText);
  check(
    'A 无 Δ 行（初始布局无相对基线语义）',
    (await page.locator(OVERLAY + ' [data-testid="edit-layout-delta"]').count()) === 0,
  );
  check('A busy 后保存可用', !(await page.locator('[data-testid="initial-layout-save"]').isDisabled()));
  await page.screenshot({ path: OUT + '/02_canvas.png' });

  // ---- B 编辑 dirty → ✕ 确认（取消保持）
  const a0 = await pieceInfo(0);
  await dragTo(0, a0.cx + 80, a0.cy); // 右移 80px（世界 ~160mm 量级，任意编辑即可）
  await page.locator('[data-testid="initial-layout-close"]').click();
  const closeMsg = ((await page.locator('[data-testid="edit-confirm-message"]').textContent()) ?? '').trim();
  check('B ✕ dirty 确认层（放弃未保存的修改？）', closeMsg.includes('放弃未保存的修改'), closeMsg);
  await page.locator('[data-testid="edit-confirm-cancel"]').click();
  await sleep(150);
  check('B 取消 → 弹窗保持', (await page.locator(OVERLAY).count()) === 1);

  // ---- C 布局刷新确认（丢弃编辑重生成 seed=1）—— waitRegen 防「旧画布在飞」竞态
  await page.locator('[data-testid="initial-layout-refresh"]').click();
  const refreshMsg = ((await page.locator('[data-testid="edit-confirm-message"]').textContent()) ?? '').trim();
  check('C 刷新确认层（将丢弃当前编辑）', refreshMsg.includes('将丢弃当前编辑'), refreshMsg);
  await page.screenshot({ path: OUT + '/03_refresh_confirm.png' });
  await page.locator('[data-testid="edit-confirm-ok"]').click();
  await waitRegen();
  check('C 重生成完整周期（busy 起落 + 画布重落）', true);
  check('C 生成请求 2 次 + seed=1', genReqs.length === 2 && genReqs[1].seed === 1, JSON.stringify(genReqs.map((g) => g.seed)));

  // ---- D 保存闸：拖片 1 压到片 0（红色非法重叠）
  const a1 = await pieceInfo(0);
  await dragTo(1, a1.cx + 6, a1.cy + 6); // 片 1 中心拖到片 0 中心附近 → 深度交叠
  let hint = null;
  for (let i = 0; i < 20 && hint === null; i++) {
    hint = await saveHint();
    if (hint === null) await sleep(150);
  }
  check('D 保存闸提示（存在 N 片非法（红色）重叠）', hint !== null && /存在 \d+ 片非法/.test(hint), String(hint));
  check('D 保存 disabled', await page.locator('[data-testid="initial-layout-save"]').isDisabled());
  await page.screenshot({ path: OUT + '/04_save_gate.png' });

  // 刷新（确认丢弃）恢复合法（seed=2）→ 保存闸解除
  await page.locator('[data-testid="initial-layout-refresh"]').click();
  await page.locator('[data-testid="edit-confirm-message"]').waitFor({ state: 'visible', timeout: 5000 });
  await page.locator('[data-testid="edit-confirm-ok"]').click();
  await waitRegen();
  check('D 生成请求 3 次 + seed=2', genReqs.length === 3 && genReqs[2].seed === 2, JSON.stringify(genReqs.map((g) => g.seed)));
  check('D 刷新后保存闸解除', !(await page.locator('[data-testid="initial-layout-save"]').isDisabled()));
  check('D 刷新后无非法提示', (await page.locator('[data-testid="initial-layout-save-hint"]').count()) === 0);

  // ---- E 保存 → 伪卡片 + 导出不启
  await page.locator('[data-testid="initial-layout-save"]').click();
  await page.locator(OVERLAY).waitFor({ state: 'hidden', timeout: 5000 });
  check('E 保存后弹窗关闭', true);
  await page.waitForFunction(() => {
    const el = document.querySelector('.nest-label');
    return el != null && el.textContent != null && el.textContent.includes('初始布局（未求解）');
  }, { timeout: 8000 });
  const labelText = await page.evaluate(() => document.querySelector('.nest-label').textContent);
  check('E 伪卡片出现在 NestsGrid（初始布局（未求解）· pct% · 长度 cm）', true, String(labelText));
  check(
    'E 导出按钮保持 disabled（仅伪卡片 = 未求解不可导出，bestRun 不受污染）',
    await page.locator('.export-btns button.export').isDisabled(),
  );
  await page.screenshot({ path: OUT + '/05_pseudo_card.png' });

  // ---- F 续编：重开 → 零生成 + 画布即刻回显
  await page.locator('[data-testid="initial-layout-btn"]').click();
  await page.locator(OVERLAY).waitFor({ state: 'visible', timeout: 5000 });
  check('F 重开弹窗（saved 在场）', true);
  check('F 续编零生成请求', genReqs.length === 3, JSON.stringify(genReqs.map((g) => g.seed)));
  await waitCanvas(4000); // 无 busy 生成，画布应即刻落场
  check('F 画布即刻回显（续编不生成）', true);
  await page.screenshot({ path: OUT + '/06_resume.png' });
  // 无编辑 → ✕ 直接关（无确认层）
  await page.locator('[data-testid="initial-layout-close"]').click();
  await sleep(150);
  check('F 续编未编辑 ✕ 直接关', (await page.locator(OVERLAY).count()) === 0);
} catch (e) {
  console.error('FULL ERROR:', e);
  check('脚本异常中断', false, String(e));
  try { await page.screenshot({ path: OUT + '/error.png' }); } catch { /* ignore */ }
} finally {
  await context.close();
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
writeFileSync(OUT + '/report.json', JSON.stringify({ results, failed: failed.length }, null, 2));
console.log(failed.length === 0 ? 'ALL PASS' : `FAILED ${failed.length}`);
process.exit(failed.length === 0 ? 0 : 1);

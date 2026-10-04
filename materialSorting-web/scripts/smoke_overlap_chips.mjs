// 重叠序号定位（2026-10-04 初始布局弹窗优化）端到端 UI 冒烟 —— footer 提示上方
// 序号 chips + 点击定位高亮 + 编号 mousedown 冻结语义。模板 = smoke_initial_layout.mjs
// （样例载入/弹窗生成/拖片套路）。
//
// 前置：ms-web 在 $SMOKE_BASE_URL（缺省 http://127.0.0.1:8010，prod 模式需先
// npm run build）；data/ 样例母版在案（sample 标记免 key）。产物
// out/smoke_overlap_chips/{report.json, *.png}；退出码 0 = 全部检查 PASS。
//
// 相位：
//   P1 样例载入 → 弹窗自动生成（合法布局：无提示无 chips）；
//   P2 拖片 A 到片 B 上制造非法重叠 → 提示出现、**chips 不出现**（编号 mousedown
//      冻结 —— 制造重叠的那次拖动其 pointerdown 早于重叠存在）；
//   P3 空白处 mousedown → chips 出现（数量 == 提示片数、在提示上方、编号 1..N）；
//   P4 点击序号 1 → 画布橙色脉冲定位高亮（edit-focus-piece）+ chip 激活态；
//      再点同号 → 高亮取消；
//   P5 拖开重叠片 → 计数归零：提示、chips、高亮同帧消失，保存闸放行。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/smoke_overlap_chips';
mkdirSync(OUT, { recursive: true });

const BASE = (process.env.SMOKE_BASE_URL || 'http://127.0.0.1:8010').replace(/\/+$/, '');
const SAMPLE = '5336#老六订单14%7%围加9.dxf';
const SIZES = [32, 33, 34];

const results = [];
function check(name, ok, extra = '') {
  results.push({ name, ok, extra: String(extra ?? '') });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 200) + ']' : '');
  return ok;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const { chromium } = await import('playwright');
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true });
} catch {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
}
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '8');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page = await context.newPage();

const OVERLAY = '[data-testid="initial-layout-overlay"]';

async function hintCount() {
  const t = ((await page.locator('[data-testid="initial-layout-save-hint"]').textContent().catch(() => '')) ?? '').trim();
  const m = t.match(/存在 (\d+) 片/);
  return { text: t, n: m ? parseInt(m[1], 10) : 0 };
}

async function chipsInfo() {
  return page.evaluate(() => {
    const cs = Array.from(document.querySelectorAll('[data-testid="initial-layout-overlap-chip"]'));
    const hint = document.querySelector('[data-testid="initial-layout-save-hint"]');
    const chipsAboveHint = cs.length > 0 && hint != null
      && (cs[0].compareDocumentPosition(hint) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    return {
      n: cs.length,
      labels: cs.map((c) => c.textContent),
      pieceIndexes: cs.map((c) => c.dataset.pieceIndex),
      chipsAboveHint,
      anyActive: cs.some((c) => c.classList.contains('is-active')),
    };
  });
}

/** 翻转组直属毛版 polygon（层1）屏幕矩形（DOM 序 = working 下标序）。 */
function pieceRects() {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    const polys = Array.from(svg.querySelectorAll(':scope > g > polygon'));
    return polys.map((p) => {
      const r = p.getBoundingClientRect();
      return { cx: r.x + r.width / 2, cy: r.y + r.height / 2, right: r.right, top: r.y, bottom: r.bottom };
    });
  });
}

/** 空白画布点（elementFromPoint 扫描，优先 fab 命中 = 布内无片空白；fallback
 *  bg/svg 命中 —— P5 解除重叠的拖放落点须真实无片，拖到「最右片右侧」会压到
 *  尾部片堆（首版 6 片红误报即此因））。 */
function blankPoint() {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    const r = svg.getBoundingClientRect();
    let fallback = null;
    for (let i = 0; i < 60; i++) {
      for (let j = 0; j < 24; j++) {
        const x = r.x + 4 + ((r.width - 8) * i) / 60;
        const y = r.y + 4 + ((r.height - 8) * j) / 24;
        const el = document.elementFromPoint(x, y);
        if (el == null) continue;
        if (el.tagName === 'rect' && el !== svg.querySelector('rect')) return { x, y }; // fab
        if (fallback == null && (el === svg || el.tagName === 'rect')) fallback = { x, y };
      }
    }
    return fallback ?? { x: r.x + 2, y: r.y + 2 };
  });
}

async function dragTo(cx, cy, tx, ty) {
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(tx, ty, { steps: 10 });
  await sleep(80);
  await page.mouse.up();
  await sleep(250);
}

try {
  // ---- P1 样例载入 + 弹窗自动生成（合法布局）
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.locator('[data-testid="sample-select"]').selectOption(SAMPLE);
  await page.locator('[data-testid="sample-apply"]').click();
  await page.waitForFunction(() => {
    const els = document.querySelectorAll('[data-testid="commit-status"]');
    return Array.from(els).some((e) => e.textContent && e.textContent.includes('已应用至超排'));
  }, null, { timeout: 90000 });
  await page.locator('button.tab', { hasText: '超排' }).click();
  for (const sz of SIZES) await page.check('#sz_' + sz);
  await page.locator('[data-testid="initial-layout-btn"]').click();
  await page.locator(OVERLAY).waitFor({ state: 'visible', timeout: 5000 });
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'hidden', timeout: 45000 });
  await page.waitForFunction(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    return svg != null && svg.querySelectorAll(':scope > g > polygon').length > 0;
  }, null, { timeout: 10000 });
  await sleep(500);
  const h0 = await hintCount();
  check('P1 生成合法布局：无提示无 chips、保存可点',
    h0.n === 0 && (await chipsInfo()).n === 0
      && !(await page.locator('[data-testid="initial-layout-save"]').isDisabled()),
    'hint=' + JSON.stringify(h0.text));

  // ---- P2 拖片 0 到片 1 中心 → 非法重叠：提示出现、chips 冻结缺席
  const rects = await pieceRects();
  check('P2a 画布片 ≥2（可制造重叠）', rects.length >= 2, 'n=' + rects.length);
  await dragTo(rects[0].cx, rects[0].cy, rects[1].cx, rects[1].cy);
  const h1 = await hintCount();
  check('P2b 重叠制造：提示出现（≥2 片红）+ 保存禁用',
    h1.n >= 2 && (await page.locator('[data-testid="initial-layout-save"]').isDisabled()),
    h1.text);
  const c1 = await chipsInfo();
  check('P2c 编号 mousedown 冻结：chips 不出现（制造重叠的拖动其 down 早于重叠）',
    c1.n === 0, JSON.stringify(c1));
  await page.screenshot({ path: OUT + '/01_overlap_hint_only.png' });

  // ---- P3 空白 mousedown → chips 出现（数量 == 提示片数、提示上方、1..N）
  const bp = await blankPoint();
  await page.mouse.move(bp.x, bp.y);
  await page.mouse.down();
  await sleep(60);
  await page.mouse.up();
  await sleep(250);
  const c2 = await chipsInfo();
  check('P3a mousedown 后 chips 出现且数量 == 提示片数', c2.n === h1.n && c2.n >= 2,
    'chips=' + c2.n + ' hint=' + h1.n);
  check('P3b chips 在提示上方（DOM 序在前）', c2.chipsAboveHint);
  check('P3c 编号 1..N 连续', c2.labels.join(',') === Array.from({ length: c2.n }, (_, i) => String(i + 1)).join(','),
    c2.labels.join(','));
  await page.screenshot({ path: OUT + '/02_chips_row.png' });

  // ---- P4 点击序号 1 → 红圈定位标记；再点取消
  await page.locator('[data-testid="initial-layout-overlap-chip"]').first().click();
  await sleep(300);
  const focus1 = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="edit-focus-piece"]');
    const inters = document.querySelectorAll('[data-testid="edit-focus-intersection"]').length;
    return el != null
      ? {
          tag: el.tagName,
          stroke: el.getAttribute('stroke'),
          ve: el.getAttribute('vector-effect'),
          r: Number(el.getAttribute('r')),
          intersections: inters,
        }
      : null;
  });
  const c3 = await chipsInfo();
  check('P4a 点击序号 1 → 红圈定位标记在场（屏幕定宽描边 + 交集区）',
    focus1 != null && focus1.tag.toLowerCase() === 'circle' && focus1.stroke === '#e03131'
      && focus1.ve === 'non-scaling-stroke' && focus1.r > 0 && focus1.intersections >= 1,
    JSON.stringify(focus1));
  check('P4b 被点 chip 激活态', c3.anyActive);
  await page.screenshot({ path: OUT + '/03_focus_highlight.png' });
  await page.locator('[data-testid="initial-layout-overlap-chip"]').first().click();
  await sleep(250);
  check('P4c 再点同号 → 高亮取消',
    (await page.evaluate(() => document.querySelector('[data-testid="edit-focus-piece"]'))) === null);

  // ---- P5 片级重置（R）解除重叠 → 计数归零：提示/chips 同帧消失 + 保存放行
  //  （拖放到空白点的中心仍可能半宽回压邻片（首两版 6/13 片红误报即此因）——
  //   R 键重置回生成基线 = 必然合法布局，同为学生真实解除路径。）
  // 选中被拖片：P2 拖动提层（re-append 置顶）后 DOM 序已乱（pieceRects[0] 不再
  // 是它 —— 既有冒烟「稳定键」教训同款），改在重叠发生点（片 1 中心）取顶层
  // 命中，顶层必是 P2 拖上去的片 0。
  await page.mouse.move(rects[1].cx, rects[1].cy);
  await page.mouse.down();
  await sleep(60);
  await page.mouse.up();
  await sleep(150);
  // 焦点让位（P4 点过 chip 按钮后 activeElement 仍是它 —— 画布键盘守卫②
  // 「表单控件聚焦时键盘归控件」会吞 R 键；真实用户点画布后焦点自然离按钮，
  // 此处显式 blur 对齐）。
  await page.evaluate(() => {
    const ae = document.activeElement;
    if (ae != null && ae !== document.body) ae.blur();
  });
  check('P5a 选中态在案（旋转手柄可见）',
    await page.evaluate(() => {
      const h = document.querySelector('[data-testid="edit-rotate-handle"]');
      return h != null && (h.closest('g')?.style.display ?? '') !== 'none';
    }));
  await page.keyboard.press('r');
  await sleep(300);
  const h2 = await hintCount();
  check('P5 重叠解除：提示与 chips 消失 + 保存放行',
    h2.n === 0 && (await chipsInfo()).n === 0
      && !(await page.locator('[data-testid="initial-layout-save"]').isDisabled()),
    'hint=' + JSON.stringify(h2.text));
  await page.screenshot({ path: OUT + '/04_resolved.png' });
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
console.log(failed.length === 0 ? 'ALL PASS' : 'FAILED ' + failed.length);
process.exit(failed.length === 0 ? 0 : 1);

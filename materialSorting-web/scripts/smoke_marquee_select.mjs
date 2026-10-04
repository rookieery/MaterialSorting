// 批量框选移动（2026-10-04 初始布局弹窗优化）端到端 UI 冒烟 —— 工具区「区域选择」
// 按钮 + 橡皮筋完全覆盖选中 + 框选块整体拖动 + 取消语义（单击清选中位置保留 / Esc
// 退出）+ 组包络钳制（minX≥0）。模板 = smoke_overlap_chips.mjs（样例载入/弹窗生成/
// 空白点扫描套路）。
//
// 前置：ms-web 在 $SMOKE_BASE_URL（缺省 http://127.0.0.1:8010，prod 模式需先
// npm run build）；data/ 样例母版在案（sample 标记免 key）。产物
// out/smoke_marquee_select/{report.json, *.png}；退出码 0 = 全部检查 PASS。
//
// 框选起点约束：排料自 x=0 铺满、最左片贴 svg 左缘，「最左片外扩」会把 pointerdown
// 落在 svg 外（监听不触发 = 什么都不选，首版 P3 全红即此因）—— 改取**中部片**
// bbox 外扩（四边 ≥12px 余量留在 svg 内）。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/smoke_marquee_select';
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

/** 翻转组直属毛版 polygon（layer1）屏幕盒 + 选中类快照（DOM 序 = working 下标序）。
 *  选择器带 [data-label]：只取 layer1 毛版（净版 netEl/collideEl 也是 g 直属
 *  polygon，混入会把一片算两片 —— 首版 P3 复算 expect=2 即此因）。 */
function pieceRects() {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    const sr = svg.getBoundingClientRect();
    const polys = Array.from(svg.querySelectorAll(':scope > g > polygon[data-label]'));
    return polys.map((p) => {
      const r = p.getBoundingClientRect();
      return {
        left: r.left,
        top: r.top,
        right: r.right,
        bottom: r.bottom,
        cx: r.x + r.width / 2,
        cy: r.y + r.height / 2,
        marginL: r.left - sr.left,
        marginT: r.top - sr.top,
        marginR: sr.right - r.right,
        marginB: sr.bottom - r.bottom,
        selected: p.classList.contains('edit-marquee-selected'),
      };
    });
  });
}

/** 框选矩形屏幕盒（无 → null）。 */
function marqueeRectScreen() {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="edit-marquee-rect"]');
    if (el == null) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
}

/** 空白画布点（elementFromPoint 全网格扫描，优先 fab 命中 = 布内无片空白）。 */
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

async function toggleText() {
  return ((await page.locator('[data-testid="edit-marquee-toggle"]').textContent()) ?? '').trim();
}

async function svgCursor() {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    return svg != null ? svg.style.cursor : '';
  });
}

async function dragTo(cx, cy, tx, ty) {
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(tx, ty, { steps: 12 });
  await sleep(80);
  await page.mouse.up();
  await sleep(300);
}

try {
  // ---- P1 样例载入 + 弹窗自动生成 → 按钮/指南行在场
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
  await page.locator('[data-testid="initial-layout-overlay"]').waitFor({ state: 'visible', timeout: 5000 });
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'hidden', timeout: 45000 });
  await page.waitForFunction(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    return svg != null && svg.querySelectorAll(':scope > g > polygon').length > 0;
  }, null, { timeout: 10000 });
  await sleep(500);
  check('P1a 工具区「区域选择」按钮在场（形态 select 同排）',
    await page.evaluate(() => {
      const b = document.querySelector('[data-testid="edit-marquee-toggle"]');
      return b != null && b.closest('.edit-layout-canvas-tools') != null;
    }));
  check('P1b 初始文案「区域选择」+ 指南批量行在场', (await toggleText()) === '区域选择'
    && (await page.locator('[data-testid="edit-guide-marquee-row"]').count()) === 1);

  // ---- P2 切入框选模式：文案翻转 + crosshair 光标
  await page.locator('[data-testid="edit-marquee-toggle"]').click();
  await sleep(200);
  check('P2 切入模式：文案「取消框选」+ crosshair 光标',
    (await toggleText()) === '取消框选' && (await svgCursor()) === 'crosshair');
  await page.screenshot({ path: OUT + '/01_mode_on.png' });

  // ---- P3 框选：中部片 bbox 外扩 10px → 完全覆盖者入选 + 矩形=选中块包络
  let rects = await pieceRects();
  check('P3a 画布片 ≥4（可分选未选）', rects.length >= 4, 'n=' + rects.length);
  // 自中部向外找首片四边余量 ≥12px（外扩 10px 后仍在 svg 内，事件必达 svg 监听）
  const order = rects.map((_, i) => i).sort((a, b) => Math.abs(a - rects.length / 2) - Math.abs(b - rects.length / 2));
  const cand = order.find((i) => rects[i].marginL >= 12 && rects[i].marginT >= 12 && rects[i].marginR >= 12 && rects[i].marginB >= 12);
  check('P3b 找到中部候选片（svg 内有余量）', cand != null, 'cand=' + cand);
  const x0 = rects[cand].left - 10;
  const y0 = rects[cand].top - 10;
  const x1 = rects[cand].right + 10;
  const y1 = rects[cand].bottom + 10;
  await dragTo(x0, y0, x1, y1);
  await sleep(300);
  // 期望集 = 同一屏幕框（内缩 2px 防亚像素抖动）完全覆盖的片 —— 独立复算
  // （选择器同 pieceRects 只取 layer1 毛版）
  const expectSel = await page.evaluate(
    ([rx0, ry0, rx1, ry1]) => {
      const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
      return Array.from(svg.querySelectorAll(':scope > g > polygon[data-label]')).filter((p) => {
        const r = p.getBoundingClientRect();
        return r.left >= rx0 + 2 && r.right <= rx1 - 2 && r.top >= ry0 + 2 && r.bottom <= ry1 - 2;
      }).length;
    },
    [x0, y0, x1, y1],
  );
  rects = await pieceRects();
  const gotSel = rects.filter((r) => r.selected).length;
  check('P3c 完全覆盖语义：选中数 == 独立复算期望（半覆盖不选）',
    gotSel === expectSel && gotSel >= 1, `got=${gotSel} expect=${expectSel}`);
  const mr = await marqueeRectScreen();
  const selRects = rects.filter((r) => r.selected);
  const selUnion = selRects.reduce(
    (a, r) => ({
      x0: Math.min(a.x0, r.left),
      y0: Math.min(a.y0, r.top),
      x1: Math.max(a.x1, r.right),
      y1: Math.max(a.y1, r.bottom),
    }),
    { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity },
  );
  check('P3d 框选矩形 = 选中块包络（±3px）',
    mr != null && Math.abs(mr.x - selUnion.x0) <= 3 && Math.abs(mr.y - selUnion.y0) <= 3,
    JSON.stringify({ mr, selUnion }));
  await page.screenshot({ path: OUT + '/02_selected.png' });

  // ---- P4 拖动选中块：全选中片同位移 + 未选中不动 + 矩形随动
  const before = await pieceRects();
  const grabber = before.find((r) => r.selected);
  check('P4a 有可抓取选中片', grabber != null);
  const DX = 120;
  await dragTo(grabber.cx, grabber.cy, grabber.cx + DX, grabber.cy);
  const after = await pieceRects();
  // 单遍配对（filter+map 的 i 是过滤后下标，与 before 串位 = 首版 645px 假读数即此因）
  const movedDeltas = [];
  const stillDeltas = [];
  after.forEach((r, i) => {
    const d = r.left - before[i].left;
    (before[i].selected ? movedDeltas : stillDeltas).push(d);
  });
  check('P4b 选中片全部平移 ~120px（±2px，等位移）',
    movedDeltas.length >= 1 && movedDeltas.every((d) => Math.abs(d - DX) <= 2),
    JSON.stringify(movedDeltas));
  check('P4c 未选中片纹丝不动（±1px）',
    stillDeltas.every((d) => Math.abs(d) <= 1), JSON.stringify(stillDeltas.slice(0, 5)));
  const mr2 = await marqueeRectScreen();
  check('P4d 框选矩形随块平移（x 增 ~120px）',
    mr2 != null && mr != null && Math.abs(mr2.x - (mr.x + DX)) <= 3,
    JSON.stringify({ before: mr, after: mr2 }));
  check('P4e 拖后选中态保持（可继续拖）', (await pieceRects()).some((r) => r.selected));
  await page.screenshot({ path: OUT + '/03_dragged.png' });

  // ---- P5 组包络钳制：把块拖出布头（向左 2000px）→ 块左缘不越 fab 左缘（minX≥0）
  const grab2 = (await pieceRects()).find((r) => r.selected);
  await dragTo(grab2.cx, grab2.cy, grab2.cx - 2000, grab2.cy);
  const clamp = await page.evaluate(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    const fab = svg.querySelectorAll(':scope > rect')[1];
    const fr = fab.getBoundingClientRect();
    const sel = Array.from(svg.querySelectorAll(':scope > g > polygon.edit-marquee-selected'));
    const minX = Math.min(...sel.map((p) => p.getBoundingClientRect().left));
    return { fabLeft: fr.left, minX };
  });
  check('P5 组包络钳制：块左缘不越布头（minX≥0，±2px）',
    clamp.minX >= clamp.fabLeft - 2, JSON.stringify(clamp));
  await page.screenshot({ path: OUT + '/04_clamped.png' });

  // ---- P6 单击空白 = 清选中、位置保留（不回滚）
  const posBefore = await pieceRects();
  const bp = await blankPoint();
  await page.mouse.move(bp.x, bp.y);
  await page.mouse.down();
  await sleep(60);
  await page.mouse.up();
  await sleep(250);
  const posAfter = await pieceRects();
  check('P6a 单击空白 = 清除选中（模式保持）',
    !posAfter.some((r) => r.selected) && (await marqueeRectScreen()) === null
    && (await toggleText()) === '取消框选');
  check('P6b 位置保留不回滚（钳制后位置仍在，±1px）',
    posAfter.every((r, i) => Math.abs(r.left - posBefore[i].left) <= 1),
    JSON.stringify(posAfter.slice(0, 3).map((r, i) => r.left - posBefore[i].left)));

  // ---- P7 Esc 退出：文案复位 + 光标复位；再进入按未选中片 = 起框选（非单片拖动）
  await page.keyboard.press('Escape');
  await sleep(200);
  check('P7a Esc 退出：文案「区域选择」+ 光标复位',
    (await toggleText()) === '区域选择' && (await svgCursor()) === '');
  await page.locator('[data-testid="edit-marquee-toggle"]').click();
  await sleep(150);
  const beforeC = await pieceRects();
  await dragTo(beforeC[0].cx, beforeC[0].cy, beforeC[0].cx - 60, beforeC[0].cy - 40);
  const afterC = await pieceRects();
  check('P7b 模式内按未选中片 = 起框选不起单片拖动（该片零位移）',
    Math.abs(afterC[0].left - beforeC[0].left) <= 1,
    JSON.stringify({ dx: afterC[0].left - beforeC[0].left }));
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

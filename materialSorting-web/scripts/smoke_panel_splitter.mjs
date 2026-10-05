// 面板伸缩分隔条 UI 冒烟（2026-10-05，playwright 手动脚本不入 vitest）：
//   1. 上传预览页：.panel-splitter 存在；aside 默认宽 248
//   2. hover：::after 蓝色（#0078d4）+ cursor col-resize
//   3. 拖拽：+60px → 308 钳 300；拖回头部 → 钳 200；反向立即可回（无死区）
//   4. pointerup 后 localStorage(ms_panel_w) 落值；拖拽中 body.panel-resizing 在场
//   5. 刷新 → 宽度记忆恢复
//   6. 双击 → 重置 248
//   7. 上传 5336 样例 → 超排页 ControlPanel 同宽 + 分隔条在场（两页共享同值）
import { chromium } from 'playwright';

// 本机没下 playwright 浏览器二进制，借系统通道（Edge Win11 必有，Chrome 兜底）
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
let pass = 0;
const check = (name, ok) => {
  log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
  if (!ok) process.exitCode = 1;
  if (ok) pass += 1;
};

await page.goto('http://127.0.0.1:8010/', { waitUntil: 'networkidle' });

const splitter = page.locator('.preview-page .panel-splitter');
const aside = page.locator('.preview-page aside.panel');
await splitter.waitFor({ state: 'visible', timeout: 5000 });

// 1. 存在性 + 默认宽（双页常驻 DOM：另一页 display:none，须按页作用域定位）
check('分隔条渲染（上传预览页）', (await page.locator('.preview-page .panel-splitter').count()) === 1);
const w0 = await aside.evaluate((el) => el.getBoundingClientRect().width);
check(`默认宽 248（实测 ${w0}）`, Math.round(w0) === 248);

// 2. hover 视觉：cursor + ::after 蓝
const box = await splitter.boundingBox();
const cx = box.x + box.width / 2;
const cy = box.y + box.height / 2;
await page.mouse.move(cx, cy);
await page.waitForTimeout(300); // transition 0.12s
const hoverInfo = await page.evaluate(() => {
  const el = document.querySelector('.preview-page .panel-splitter');
  const cs = getComputedStyle(el);
  const after = getComputedStyle(el, '::after');
  return { cursor: cs.cursor, bg: after.backgroundColor, w: after.width };
});
check(`hover cursor=col-resize（实测 ${hoverInfo.cursor}）`, hoverInfo.cursor === 'col-resize');
check(`hover ::after 蓝 rgb(0,120,212)（实测 ${hoverInfo.bg}）`, hoverInfo.bg === 'rgb(0, 120, 212)');
check(`::after 视觉线 2px（实测 ${hoverInfo.w}）`, hoverInfo.w === '2px');

// 3. 拖拽钳制：+400 → 钳 300；拖到最左 → 钳 200；回中 +20 → 220（无死区）
await page.mouse.down();
const bodyClsDrag = await page.evaluate(() => document.body.classList.contains('panel-resizing'));
check('拖拽中 body.panel-resizing 在场', bodyClsDrag === true);
await page.mouse.move(cx + 400, cy, { steps: 8 });
await page.waitForTimeout(100);
const wMax = await aside.evaluate((el) => el.getBoundingClientRect().width);
check(`右拖钳 300（实测 ${Math.round(wMax)}）`, Math.round(wMax) === 300);
await page.mouse.move(50, cy, { steps: 8 });
await page.waitForTimeout(100);
const wMin = await aside.evaluate((el) => el.getBoundingClientRect().width);
check(`左拖钳 200（实测 ${Math.round(wMin)}）`, Math.round(wMin) === 200);
// 越界后反向拖回界内：delta 基准 = 按下点 cx → 移到 cx+20 总 delta = +20 → 248+20
await page.mouse.move(Math.round(cx) + 20, cy, { steps: 4 });
await page.waitForTimeout(100);
const wBack = await aside.evaluate((el) => el.getBoundingClientRect().width);
check(`越界后反向拖立即生效 → 268（实测 ${Math.round(wBack)}）`, Math.round(wBack) === 268);
await page.mouse.up();
const bodyClsIdle = await page.evaluate(() => document.body.classList.contains('panel-resizing'));
check('松手后 body.panel-resizing 摘除', bodyClsIdle === false);
const ls1 = await page.evaluate(() => localStorage.getItem('ms_panel_w'));
check(`localStorage 落值 268（实测 ${ls1}）`, ls1 === '268');

// 5. 刷新记忆
await page.reload({ waitUntil: 'networkidle' });
const wReload = await page.locator('.preview-page aside.panel').evaluate((el) => el.getBoundingClientRect().width);
check(`刷新后宽度记忆 268（实测 ${Math.round(wReload)}）`, Math.round(wReload) === 268);

// 6. 双击重置
await page.locator('.preview-page .panel-splitter').dblclick();
const wReset = await page.locator('.preview-page aside.panel').evaluate((el) => el.getBoundingClientRect().width);
check(`双击重置 248（实测 ${Math.round(wReset)}）`, Math.round(wReset) === 248);

// 7. 上传样例 → 超排页同宽 + 分隔条在场（两页共享同值）
await page.locator('input[type="file"]').setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
// 大母版 parse + commit 耗时不定 → 轮询超排 Tab 解锁（US-016：done+doc 才 enabled）
try {
  await page.waitForFunction(
    () => {
      const b = Array.from(document.querySelectorAll('button')).find(
        (x) => x.textContent?.trim() === '超排',
      );
      return !!b && !b.disabled;
    },
    { timeout: 30000 },
  );
} catch {
  const st = await page.evaluate(() => document.querySelector('[data-testid="upload-status"]')?.textContent ?? '(无状态行)');
  log(`上传状态行：${st}`);
  throw new Error('超排 Tab 30s 未解锁');
}
await page.getByRole('button', { name: '超排' }).click();
await page.waitForTimeout(500);
// 超排页容器类 = .page（无 nesting-page 后缀，见 App.tsx:84）→ 用 :not(.hidden) 作用域
const nestingAside = page.locator('.page:not(.hidden) aside.panel');
const wNest = await nestingAside.evaluate((el) => el.getBoundingClientRect().width);
const nestSplitters = await page.locator('.page:not(.hidden) .panel-splitter').count();
check(`超排页分隔条在场（${nestSplitters} 个）`, nestSplitters === 1);
check(`超排页共享同宽 248（实测 ${Math.round(wNest)}）`, Math.round(wNest) === 248);

// 超排页拖一下 → 两页联动（切回上传页宽度一致）
const s2 = (await page.locator('.page:not(.hidden) .panel-splitter').boundingBox());
await page.mouse.move(s2.x + s2.width / 2, s2.y + s2.height / 2);
await page.mouse.down();
await page.mouse.move(s2.x + s2.width / 2 + 32, s2.y + s2.height / 2, { steps: 4 });
await page.mouse.up();
const wNest2 = await page.locator('.page:not(.hidden) aside.panel').evaluate((el) => el.getBoundingClientRect().width);
check(`超排页拖拽 +32 → 280（实测 ${Math.round(wNest2)}）`, Math.round(wNest2) === 280);
await page.getByRole('button', { name: '上传预览' }).click();
await page.waitForTimeout(300);
const wPrev = await page.locator('.preview-page aside.panel').evaluate((el) => el.getBoundingClientRect().width);
check(`切回上传页同宽 280（实测 ${Math.round(wPrev)}）`, Math.round(wPrev) === 280);

log(`\n${pass} 项通过${process.exitCode ? '，存在 FAIL' : ''}`);
await browser.close();

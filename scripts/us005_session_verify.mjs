// 多会话 US-005（前端会话接入与阻断弹窗）浏览器验证 harness（Playwright + 本地
// Chrome channel，无外部依赖；范本 scripts/us004_prefix_verify.mjs）。
//
// 前置：ms-web 在 :8000 运行，且会话注册表干净 —— 运行前重启 ms-web（P4 需要
// 恰好 4 个空席；任何残留 sid / curl 探测都会让第 3/4 窗口误吃 429）。
//
//   node scripts/us005_session_verify.mjs          # 主相位（默认 TTL=300 服务器）
//   node scripts/us005_session_verify.mjs --expire  # 过期相位（需 MS_SESSION_TTL_SEC=6）
//
// 主相位 P1-P5：sid 落库/刷新不变/Header 注入；双窗口上传互不串台（弹窗徽章 +
// ptypes 响应体 + 缩略图几何三层取证）；WS ?sid=；第 5 窗口加载即弹「用户过多」；
// 阻断期间上传被拦截（swallow）。
// 过期相位 E1-E5：静置 > TTL → 操作 → 「会话已过期」弹窗 → ms_sid 已丢弃 →
// 刷新换新 sid → 干净新会话。
// 注意：P2 徽章选择器限定 .per-type-modal thead（上传预览 QtyMatrix 也有
// .qty-label-badge，全局选择器会假阳性）；大母版 commit 约 1-2 分钟，轮询给足 240s。
// playwright 是 materialSorting-web 的 devDependency（本脚本在 scripts/ 下，
// ESM 解析按脚本位置找包）—— createRequire 指向 web 包仓库相对路径解析。
import { createRequire } from 'node:module';
const { chromium } = createRequire(
  new URL('../materialSorting-web/package.json', import.meta.url),
)('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF_A = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9.dxf';
const DXF_B = 'D:/code/MaterialSorting/data/M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf';
const SID_RE = /^[0-9a-f]{32}$/;
const EXPIRE = process.argv[2] === '--expire';

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const results = [];
function check(name, ok, extra = '') {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  [' + extra + ']' : ''}`);
}
async function dismissTour(page, rounds = 6) {
  // tour 自动触发时机不定（首页 / 切 Tab 后）—— 轮询多次点跳过
  for (let i = 0; i < rounds; i++) {
    const gone = await page.evaluate(() => document.querySelector('[data-testid=tour-overlay]') === null);
    if (gone) return;
    await page.evaluate(() => {
      const btn = document.querySelector('[data-testid=tour-skip]');
      if (btn) btn.click();
    });
    await page.waitForTimeout(600);
  }
}
async function modalText(page) {
  return page.evaluate(() => {
    const el = document.querySelector('.session-block-text');
    return el ? el.textContent : null;
  });
}

if (!EXPIRE) {
  // ============================= 主相位 P1-P5 =============================
  const ctxA = await browser.newContext();
  const pageA = await ctxA.newPage();
  const reqsA = [];
  pageA.on('request', (r) => reqsA.push({ url: r.url(), sid: r.headers()['x-session-id'] || null }));
  await pageA.goto(BASE, { waitUntil: 'networkidle' });
  const sidA = await pageA.evaluate(() => localStorage.getItem('ms_sid'));
  check('P1a 窗口A localStorage ms_sid = 32hex', SID_RE.test(sidA || ''), sidA || '');
  const probeA = reqsA.find((r) => r.url.includes('/api/session'));
  check('P1b 窗口A 探测 POST /api/session 带 X-Session-Id=sidA', !!probeA && probeA.sid === sidA);
  await pageA.reload({ waitUntil: 'networkidle' });
  const sidA2 = await pageA.evaluate(() => localStorage.getItem('ms_sid'));
  check('P1c 刷新后 sid 不变', sidA === sidA2);

  const ctxB = await browser.newContext();
  const pageB = await ctxB.newPage();
  const reqsB = [];
  pageB.on('request', (r) => {
    if (r.url().includes('/api/ptypes')) reqsB.push({ sid: r.headers()['x-session-id'] || null });
  });
  await pageB.goto(BASE, { waitUntil: 'networkidle' });
  const sidB = await pageB.evaluate(() => localStorage.getItem('ms_sid'));
  check('P1d 窗口B（独立 context）sid 互不相同', sidA !== sidB && SID_RE.test(sidB || ''), sidB || '');

  async function uploadAndOpenAdvanced(page, dxf, tag) {
    await dismissTour(page);
    const input = page.locator('input[type=file]').first();
    await input.setInputFiles(dxf);
    try {
      await page.waitForSelector('button.tab:not([disabled]):has-text("超排")', { timeout: 60000 });
    } catch (e) {
      const panelText = await page.evaluate(() => document.body.innerText.slice(0, 600));
      throw new Error(tag + ' 超排 Tab 未解锁。面板文本: ' + panelText.split('\n').join(' | ').slice(0, 400));
    }
    await page.click('button.tab:has-text("超排")');
    await page.waitForTimeout(800);
    await dismissTour(page); // 切 Tab 会触发 tour 自动播放 —— 再清一次
    await page.click('button.per-type-btn');
    await page.waitForSelector('.per-type-overlay', { timeout: 15000 });
    // 轮询等「弹窗内」thead g 码徽章：commit done 才 invalidate → refetch 出 reps
    let codes = [];
    for (let i = 0; i < 120; i++) {
      codes = await page.$$eval('.per-type-modal thead .qty-label-badge', (els) =>
        [...new Set(els.map((el) => (el.textContent || '').trim()).filter((t) => /^g\d+$/.test(t)))],
      );
      if (codes.length > 0) break;
      await page.waitForTimeout(2000);
    }
    return codes;
  }
  const codesA = await uploadAndOpenAdvanced(pageA, DXF_A, 'A');
  check('P2a 窗口A 高级配置 g 码来自 5336 母版', codesA.length > 0, codesA.join(','));
  const ptypesReqsA = reqsA.filter((r) => r.url.includes('/api/ptypes'));
  check('P2b 窗口A /api/ptypes 带 X-Session-Id=sidA', ptypesReqsA.length > 0 && ptypesReqsA.every((r) => r.sid === sidA), 'n=' + ptypesReqsA.length);
  const codesB = await uploadAndOpenAdvanced(pageB, DXF_B, 'B');
  check('P2c 窗口B 高级配置 g 码来自 M1787 母版', codesB.length > 0, codesB.join(','));
  // 数据层：两母版 label 集同为 g01..g10 —— 各自 sid 直取 ptypes 响应体对比
  // （不同母版几何必不同）。cache:'no-store' 防 HTTP 缓存。裸 fetch 仅取证用。
  const bodyA = await pageA.evaluate(async (sid) => {
    const r = await fetch('/api/ptypes', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
    return r.status + ' ' + (await r.text()).slice(0, 80);
  }, sidA);
  const bodyB = await pageB.evaluate(async (sid) => {
    const r = await fetch('/api/ptypes', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
    return r.status + ' ' + (await r.text()).slice(0, 80);
  }, sidB);
  check(
    'P2d 双窗口 ptypes 响应体互不相同（数据层不串台）',
    bodyA.includes('"g01"') && bodyB.includes('"g01"') && bodyA !== bodyB,
    'A=[' + bodyA.slice(0, 50) + '] B=[' + bodyB.slice(0, 50) + ']',
  );
  check('P2e 窗口B /api/ptypes 带 X-Session-Id=sidB', reqsB.length > 0 && reqsB.every((r) => r.sid === sidB), 'n=' + reqsB.length);
  // 渲染层：两窗口高级配置弹窗 g01 缩略图 polygon points 必不同
  const thumbA = await pageA.evaluate(() => {
    const el = document.querySelector('.per-type-modal svg polygon');
    return el ? el.getAttribute('points') || '' : '';
  });
  const thumbB = await pageB.evaluate(() => {
    const el = document.querySelector('.per-type-modal svg polygon');
    return el ? el.getAttribute('points') || '' : '';
  });
  check('P2f App 渲染层不串台（g01 缩略图几何不同）', thumbA.length > 50 && thumbA !== thumbB, 'A=' + thumbA.length + 'pts B=' + thumbB.length + 'pts');
  await pageA.click('.per-type-close').catch(() => {});
  await pageB.click('.per-type-close').catch(() => {});
  await pageA.waitForTimeout(300);

  // ---- P3: WS ?sid= ----
  let wsUrl = null;
  pageA.on('websocket', (ws) => { wsUrl = ws.url(); });
  const sizeBoxes = pageA.locator('input[type=checkbox]');
  const n = await sizeBoxes.count();
  for (let i = 0; i < Math.min(3, n); i++) await sizeBoxes.nth(i).check();
  await pageA.fill('#time', '3').catch(() => {});
  await pageA.click('#start').catch(async (e) => {
    check('P3 求解启动', false, String(e).slice(0, 120));
  });
  await pageA.waitForTimeout(6000);
  check('P3a 求解 WS URL 带 ?sid=sidA', !!wsUrl && wsUrl.includes('sid=' + sidA), wsUrl || 'no ws');

  // ---- P4: 第 5 窗口超限（前置：注册表恰 4 空席 —— 运行前须重启 ms-web）----
  const ctxC = await browser.newContext(); const pageC = await ctxC.newPage();
  await pageC.goto(BASE, { waitUntil: 'networkidle' });
  const ctxD = await browser.newContext(); const pageD = await ctxD.newPage();
  await pageD.goto(BASE, { waitUntil: 'networkidle' });
  const ctxE = await browser.newContext(); const pageE = await ctxE.newPage();
  await pageE.goto(BASE, { waitUntil: 'networkidle' });
  await pageE.waitForSelector('.session-block-overlay', { timeout: 10000 }).catch(() => {});
  const textE = await modalText(pageE);
  check('P4 第 5 窗口页面加载即弹「用户过多」', textE === '当前使用用户过多（最多 4 人同时在线），请稍后尝试', textE || 'no modal');
  const noModalC = await pageC.evaluate(() => document.querySelector('.session-block-overlay') === null);
  const noModalD = await pageD.evaluate(() => document.querySelector('.session-block-overlay') === null);
  check('P4b 第 3/4 窗口正常（无弹窗）', noModalC && noModalD);

  // ---- P5: 阻断期间请求 swallow ----
  let parseCalls = 0;
  pageE.on('request', (r) => { if (r.url().includes('/api/parse-dxf')) parseCalls++; });
  const inputE = pageE.locator('input[type=file]').first();
  await inputE.setInputFiles(DXF_A).catch(() => {});
  await pageE.waitForTimeout(2000);
  check('P5 弹窗期间上传被拦截（/api/parse-dxf 不发出）', parseCalls === 0, 'parseCalls=' + parseCalls);
  const hasReload = await pageE.evaluate(() => {
    const b = document.querySelector('.session-block-reload');
    return !!b && b.textContent === '刷新页面';
  });
  check('P5b 唯一出口=刷新按钮', hasReload);
} else {
  // ============================= 过期相位 E1-E5 =============================
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const sid1 = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('E1 初始 sid 落库', SID_RE.test(sid1 || ''), sid1 || '');
  await dismissTour(page);
  // 上传 → parse → commit（后端管线），静置 8s > TTL 6s → 点开高级配置弹窗
  // （apiFetch GET /api/ptypes，读路径 create=False）→ 401 session_expired
  const input = page.locator('input[type=file]').first();
  await input.setInputFiles(DXF_A);
  await page.waitForSelector('button.tab:not([disabled]):has-text("超排")', { timeout: 60000 });
  await page.waitForTimeout(8000); // 静置 8s > TTL 6s（期间无任何会话触点）
  await page.click('button.tab:has-text("超排")');
  await dismissTour(page, 3);
  await page.click('button.per-type-btn');
  let text = null;
  for (let i = 0; i < 30; i++) {
    text = await modalText(page);
    if (text) break;
    await page.waitForTimeout(1000);
  }
  check('E2 过期后操作 → 「会话已过期」弹窗', text === '会话已过期（5 分钟无操作），请刷新页面', text || 'no modal');
  const sidAfter = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('E3 弹窗后 ms_sid 已丢弃（墓碑出口）', sidAfter === null, 'ms_sid=' + sidAfter);
  await page.click('.session-block-reload');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  const sid2 = await page.evaluate(() => localStorage.getItem('ms_sid'));
  const textAfter = await modalText(page);
  check('E4 刷新后新 sid（不等于旧 sid，32hex）', SID_RE.test(sid2 || '') && sid2 !== sid1, (sid1 || '').slice(0, 8) + '>' + (sid2 || '').slice(0, 8));
  check('E5 刷新后无弹窗（干净新会话，探测 200）', textAfter === null, textAfter || 'clean');
}

const failed = results.filter((r) => !r.ok);
console.log('\n==== 多会话 US-005 ' + (EXPIRE ? '过期相位' : '主相位') + ': ' + (results.length - failed.length) + '/' + results.length + ' passed ====');
await browser.close();
process.exit(failed.length ? 1 : 0);

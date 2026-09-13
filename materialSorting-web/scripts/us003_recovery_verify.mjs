// 会话过期自动恢复 US-003 浏览器验证（playwright，手动脚本不入 vitest；2026-09-13）。
//
// 前置：ms-web 在 :8000（prod static），且短 TTL 起服：
//   MS_SESSION_TTL_SEC=45 MS_SESSION_MAX=6 MS_EDIT_HOLD_SEC=5
//   （EDIT_HOLD_SEC 必须 >0 短值：/api/state-recover 共享 rebuild 会给新会话挂
//   2h 编辑钉住 —— 生产语义「恢复后会话 2h 不再过期」，测试须解锁「恢复后再过期」
//   才能覆盖 B 相位停留期弹窗。）
//
// 相位：
//   A1 上传 5336 母版 → commit → g01@30 改 2 → 3 码 5s 求解 done。
//   A2 捕获 /api/state-save 载荷 → 同载荷 POST /api/state-checkpoint（staged，
//      US-004 自动调度未落地，手工替代打点）。
//   A3 空闲 70s（> TTL 45s）→ reload → 启动期恢复：
//      toast「工作状态已恢复」+ sid 换新 + 母版/数量矩阵/布局回显 + 切超排 Tab +
//      __netLog 佐证 POST /api/state-recover {from_sid=旧sid} + 新 sid 重探。
//   B1 再空闲 70s → 打开高级配置弹窗（apiFetch /api/ptypes）→ 停留期 401：
//      阻断弹窗新文案「会话已过期，刷新页面后将恢复工作状态」+ ms_sid 未被清。
//   B2 点「刷新页面」→ reload → checkpoint 已被 A3 消费（single-use）→ 404 兜底：
//      toast「上次会话已过期，已开启新会话」+ 干净新会话（无母版）。
//
// 报告落 out/us003_recovery/report.txt；退出码 0 = 全 PASS。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/us003_recovery';
mkdirSync(OUT, { recursive: true });

const { chromium } = await import('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF = ROOT + '/data/5336#老六订单14%7%围加9_coded.dxf';
const SIZES = [32, 33, 34];
const SOLVE_TIME = '5';
const GATE = '180.00';
const TTL_IDLE_MS = 70_000; // > MS_SESSION_TTL_SEC=45 + daemon 扫描周期余量

const results = [];
function check(name, ok, extra) {
  results.push({ name, ok });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 160) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (s) => console.log('---', s);

/** 全导航 fetch 侦听（addInitScript）：全部 /api/* 调查日志（带时刻）。 */
const NET_SPY = () => {
  window.__t0 = Date.now();
  window.__netLog = [];
  const orig = window.fetch;
  window.fetch = async function (...args) {
    const url = String(args[0]);
    if (url.includes('/api/')) {
      const init = args[1] || {};
      const h = init.headers || {};
      const entry = {
        t: Math.round((Date.now() - window.__t0) / 1000),
        url,
        method: init.method || 'GET',
        sid: h['X-Session-Id'] || h['x-session-id'] || null,
        body: typeof init.body === 'string' ? init.body : null,
      };
      window.__netLog.push(entry);
      const res = await orig.apply(this, args);
      entry.status = res.status;
      return res;
    }
    return orig.apply(this, args);
  };
};

let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}

try {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await ctx.addInitScript(() => {
    localStorage.setItem('ms.tour.version', '8');
    localStorage.setItem('ms.tour.seen.preview', '1');
    localStorage.setItem('ms.tour.seen.nesting', '1');
  });
  await ctx.addInitScript(NET_SPY);
  const page = await ctx.newPage();

  // ---------- A1 上传 + 数量矩阵 + 短求解 ----------
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const sidA = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('A1a 页面加载铸造 sid A', /^[0-9a-f]{32}$/.test(sidA || ''), (sidA || '').slice(0, 8));

  await page.locator('input[type=file]').first().setInputFiles(DXF);
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 240000 });
  log('A1 上传 + commit done');

  const cell00 = page.locator('.qty-cell-input[data-cell="0-0"]');
  await cell00.waitFor({ timeout: 15000 });
  await cell00.fill('2');
  await cell00.press('Enter');
  await sleep(300);
  const qtyTotalBefore = await page.locator('[data-testid="qty-total"]').innerText();
  check('A1b 数量矩阵 g01@30=2 → 总片数 111', qtyTotalBefore.trim() === '111', qtyTotalBefore.trim());

  await page.locator('button.tab:not([disabled]):has-text("超排")').click();
  await sleep(800);
  for (const sz of SIZES) await page.check('#sz_' + sz);
  await page.fill('#gate', GATE);
  await page.fill('#time', SOLVE_TIME);
  await page.click('#start');
  const t0 = Date.now();
  for (;;) {
    const done = await page.evaluate(
      () => (document.querySelector('[data-testid="save-state-btn"]') || {}).disabled !== false,
    );
    if (!done || Date.now() - t0 > 120000) break;
    await sleep(500);
  }
  const saveEnabled = await page.evaluate(
    () => (document.querySelector('[data-testid="save-state-btn"]') || {}).disabled !== true,
  );
  check('A1c 5s 求解完成（保存按钮解锁 = done 态 bestRun 在案）', saveEnabled);

  // ---------- A2 捕获 state-save 载荷 → 手工打 checkpoint ----------
  // 先刷会话活性：state-save/checkpoint 均 peek 口径不刷 last_active，短 TTL 下
  // 求解管线尾声（commit 后 ~45s）打点有跨线竞态 —— 显式续命后紧邻打点。
  const sidPre = await page.evaluate(() => localStorage.getItem('ms_sid'));
  await page.evaluate(async (s) => {
    await fetch('/api/session', { method: 'POST', headers: { 'X-Session-Id': s } });
  }, sidPre);
  await page.evaluate(() => {
    window.__saveCaps = [];
    const orig = window.fetch;
    window.fetch = async function (...args) {
      const res = await orig.apply(this, args);
      if (String(args[0]).includes('/api/state-save')) {
        const init = args[1] || {};
        window.__saveCaps.push(typeof init.body === 'string' ? init.body : null);
      }
      return res;
    };
  });
  await page.click('[data-testid="save-state-btn"]');
  await page.waitForSelector('[data-testid="save-name-overlay"]', { timeout: 5000 });
  const dlP = page.waitForEvent('download', { timeout: 30000 }).then((d) => d).catch(() => null);
  await page.click('[data-testid="save-name-confirm"]');
  await dlP; // 附件落下载即可（载荷已从请求体捕获）
  const saveBody = await page.evaluate(() => (window.__saveCaps || [])[0] || null);
  const sidBeforeStage = await page.evaluate(() => localStorage.getItem('ms_sid'));
  const cp = await page.evaluate(async ({ b, sid }) => {
    const r = await fetch('/api/state-checkpoint', {
      method: 'POST',
      headers: { 'X-Session-Id': sid, 'Content-Type': 'application/json' },
      body: b,
    });
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { status: r.status, body };
  }, { b: saveBody, sid: sidBeforeStage });
  check('A2 checkpoint 打点 200 stored:true（state-save 同载荷）',
    cp.status === 200 && cp.body && cp.body.stored === true,
    cp.status + ' ' + JSON.stringify(cp.body || {}).slice(0, 60));
  const saveObj = saveBody ? JSON.parse(saveBody) : {};
  check('A2b 载荷含 run 块（恢复后应回显布局 + 切超排 Tab）',
    !!saveObj.run && Array.isArray(saveObj.run.placed) && saveObj.run.placed.length > 0,
    'placed=' + (saveObj.run?.placed || []).length);

  // ---------- A3 空闲过期 → reload → 启动期恢复 ----------
  log('A3 空闲 ' + TTL_IDLE_MS + 'ms 等 TTL 过期…');
  await sleep(TTL_IDLE_MS);
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(1500); // 恢复编排（applyRestorePayload 同步 + toast 渲染）

  const sidB = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('A3a 恢复后 sid 换新（旧 sid A → 新 sid B）',
    !!sidB && /^[0-9a-f]{32}$/.test(sidB) && sidB !== sidA, (sidB || 'null').slice(0, 8));

  const netLog = await page.evaluate(() => window.__netLog || []);
  const recoverCall = netLog.find((x) => x.url.includes('/api/state-recover'));
  check('A3b POST /api/state-recover 在场：from_sid=旧A、X-Session-Id=新B',
    !!recoverCall && JSON.parse(recoverCall.body || '{}').from_sid === sidA
      && recoverCall.sid === sidB,
    recoverCall ? 'from=' + String(JSON.parse(recoverCall.body || '{}').from_sid).slice(0, 8)
      + ' hdr=' + String(recoverCall.sid).slice(0, 8) : 'no call');
  const probes = netLog.filter((x) => x.url.includes('/api/session'));
  check('A3c 探测两跳：旧 sid 401 → 新 sid 重探 200',
    probes.length === 2 && probes[0].sid === sidA && probes[1].sid === sidB,
    probes.map((p) => String(p.sid).slice(0, 8)).join(','));

  const toastsA = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.toast-msg')).map((t) => t.textContent));
  check('A3d toast 工作状态已恢复', toastsA.includes('工作状态已恢复'), JSON.stringify(toastsA));

  const nestingVisible = await page.evaluate(() => {
    const el = document.querySelector('.tab-content .page:not(.hidden)');
    // 恢复带 run 块 → 求解按钮呈「重新求解」(#restart) 而非 #start（isIdle 判定）
    return el !== null && el.querySelector('#restart') !== null;
  });
  check('A3e 自动切超排 Tab（恢复编排 setTab(nesting)）', nestingVisible);

  const polygons = await page.evaluate(() =>
    document.querySelectorAll('.nest-card polygon').length);
  check('A3f 布局回显（nest polygon 在场）', polygons > 0, 'polygons=' + polygons);

  // 预览 Tab 数量矩阵实值回显
  await page.locator('button.tab:has-text("上传预览")').click();
  await sleep(600);
  const cell00After = await page.locator('.qty-cell-input[data-cell="0-0"]').inputValue();
  const qtyTotalAfter = await page.locator('[data-testid="qty-total"]').innerText();
  const matrixRows = await page.locator('.qty-cell-input').count();
  check('A3g 母版回显（QtyMatrix 渲染）+ 数量矩阵实值（g01@30=2 / 总片数 111）',
    matrixRows > 0 && cell00After === '2' && qtyTotalAfter.trim() === '111',
    'rows=' + matrixRows + ' cell=' + cell00After + ' total=' + qtyTotalAfter.trim());
  await page.screenshot({ path: OUT + '/a3_recovered_preview.png' });

  // ---------- B1 再过期 → 停留期 401：引导刷新弹窗（不自动恢复、不清 sid） ----------
  log('B1 空闲 ' + TTL_IDLE_MS + 'ms 等再次过期…');
  await sleep(TTL_IDLE_MS);
  await page.locator('button.tab:not([disabled]):has-text("超排")').click();
  await sleep(400);
  await page.click('[data-testid="per-type-btn"]');
  const overlayShown = await page
    .waitForSelector('.session-block-overlay', { timeout: 20000 })
    .then(() => true)
    .catch(() => false);
  if (!overlayShown) {
    const dg = await page.evaluate(() => ({
      perTypeOverlay: !!document.querySelector('[data-testid="per-type-overlay"]'),
      toasts: Array.from(document.querySelectorAll('.toast-msg')).map((t) => t.textContent),
      net: (window.__netLog || []).map((x) => x.t + 's ' + x.method + ' ' + x.url + ' ' + (x.status ?? '?')),
    }));
    console.log('DIAG B1:', JSON.stringify(dg, null, 1).slice(0, 2000));
  }
  check('B1a 停留期 401 → 阻断弹窗出现', overlayShown);
  const modalText = await page.evaluate(() =>
    document.querySelector('.session-block-text')?.textContent || '');
  check('B1a2 弹窗新文案（刷新后将恢复）',
    modalText === '会话已过期，刷新页面后将恢复工作状态', modalText);
  const sidKept = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('B1b 停留期不清 sid（留给刷新后恢复作 from_sid）', sidKept === sidB,
    (sidKept || 'null').slice(0, 8));
  const recoverCallsB = await page.evaluate(() =>
    (window.__netLog || []).filter((x) => x.url.includes('/api/state-recover')).length);
  check('B1c 停留期绝不自动恢复（无新 recover 调用）', recoverCallsB === 1, 'calls=' + recoverCallsB);
  await page.screenshot({ path: OUT + '/b1_stay_modal.png' });

  // ---------- B2 点「刷新页面」→ checkpoint 已消费 → 404 兜底新会话 ----------
  await page.click('.session-block-reload');
  await page.waitForLoadState('networkidle');
  await sleep(1500);
  const sidC = await page.evaluate(() => localStorage.getItem('ms_sid'));
  const toastsC = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.toast-msg')).map((t) => t.textContent));
  check('B2a 刷新后再换新 sid（B → C）', !!sidC && sidC !== sidB, (sidC || 'null').slice(0, 8));
  check('B2b checkpoint 已被 A3 消费 → 404 兜底 toast（已开启新会话）',
    toastsC.includes('上次会话已过期，已开启新会话'), JSON.stringify(toastsC));
  // __netLog 每次导航重置（addInitScript）—— B2 reload 后的新日志恰含本次恢复链
  const netLogC = await page.evaluate(() => window.__netLog || []);
  const recoverC = netLogC.filter((x) => x.url.includes('/api/state-recover'));
  const probesC = netLogC.filter((x) => x.url.includes('/api/session'));
  check('B2c 刷新触发恢复尝试（from_sid=B）+ 探测两跳（B 401 → C 200）',
    recoverC.length === 1 && JSON.parse(recoverC[0].body || '{}').from_sid === sidB
      && recoverC[0].status === 404
      && probesC.length === 2 && probesC[0].sid === sidB && probesC[1].sid === sidC,
    'recover=' + recoverC.length + ' probes=' + probesC.map((p) => p.sid?.slice(0, 8)).join(','));
  const cleanState = await page.evaluate(() => ({
    hasMatrix: document.querySelector('.qty-cell-input') !== null,
    hasUpload: document.querySelector('input[type=file]') !== null,
  }));
  check('B2d 干净新会话（无母版残留 = 非 ghost 恢复）',
    !cleanState.hasMatrix && cleanState.hasUpload, JSON.stringify(cleanState));
  await page.screenshot({ path: OUT + '/b2_fallback_new_session.png' });
} catch (e) {
  check('脚本异常中断', false, String(e).slice(0, 200));
} finally {
  await browser.close();
}

const pass = results.filter((r) => r.ok).length;
writeFileSync(OUT + '/report.txt',
  results.map((r) => (r.ok ? 'PASS' : 'FAIL') + '  ' + r.name).join('\n')
  + '\n' + pass + '/' + results.length + '\n');
console.log('\n' + pass + '/' + results.length + ' passed');
process.exit(pass === results.length ? 0 : 1);

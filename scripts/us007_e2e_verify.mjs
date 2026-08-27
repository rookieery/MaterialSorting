// 多会话 US-007（端到端验收）双浏览器全链路对拍 harness（Playwright + 本地 Chrome
// channel；范本 scripts/us005_session_verify.mjs —— 选择器与工具函数沿用）。
//
// 前置：ms-web 在 :8000 运行，且会话注册表干净（P7 需要 4 空席；跑前重启 ms-web）。
//
//   node scripts/us007_e2e_verify.mjs           # 主相位（默认 TTL=600 服务器）
//   node scripts/us007_e2e_verify.mjs --expire  # 生命周期相位（需 MS_SESSION_TTL_SEC=6）
//
// 主相位（双浏览器 A=5336 / B=M1787 各自上传不同母版）：
//   P1 双窗口上传+commit；P2 ptypes 互不串台（响应体/请求 Header 双取证）；
//   P3 B 求解中 A commit 第三母版（5156）→ B 不中断收到 final、manifest pids 仍属
//      B 母版、B ptypes 不漂移；P4 A 求解→停止（stopped 帧）；P5 B 导出 DXF
//      （响应 200 + sidB + M1787 文件名前缀）；P6 高级运行双会话并发（跨会话不
//      409、A 终止不影响 B）；P7 第 5 窗口超限弹「用户过多」；P8 default 无 sid
//      回归（/api/session→default、/api/ptypes 200、GET / no-cache）。
// 生命周期相位（TTL=6，单窗口 882 母版；commit 期间测试脚手架每 3s POST
// /api/session 保活 —— commit 不是被测活性场景，脚手架只为抵达「求解中」态）：
//   E1 求解中不误杀（ws 钉住 + 回调 touch：TTL=6 下 20s 求解照常 final，求解后
//      操作不弹过期）；E2 策略轮询中不误杀（2s status 轮询即活性，15s 观察）；
//   E3 空闲 >TTL → 操作弹「已过期」→ ms_sid 丢弃 → 刷新 → 干净新会话。
import { createRequire } from 'node:module';
const { chromium } = createRequire(
  new URL('../materialSorting-web/package.json', import.meta.url),
)('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF_A1 = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9.dxf';
const DXF_A2 = 'D:/code/MaterialSorting/data/5156#直筒13%7%大货围加9）双针(1).dxf';
const DXF_B = 'D:/code/MaterialSorting/data/M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf';
const DXF_W = 'D:/code/MaterialSorting/data/882#弹力商务13%9%大货贴袋机-埋夹脚口20cm.dxf';
const SID_RE = /^[0-9a-f]{32}$/;
const EXPIRE = process.argv[2] === '--expire';

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const results = [];
function check(name, ok, extra = '') {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  [' + extra + ']' : ''}`);
}
async function dismissTour(page, rounds = 6) {
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
/** 上传母版 → 等 commit 完成（超排 Tab 解锁）。timeout 默认 240s（大母版 1-2 分钟）。 */
async function uploadAndWaitCommit(page, dxf, tag, timeout = 240000) {
  await dismissTour(page);
  const input = page.locator('input[type=file]').first();
  await input.setInputFiles(dxf);
  try {
    await page.waitForSelector('button.tab:not([disabled]):has-text("超排")', { timeout });
  } catch (e) {
    const panelText = await page.evaluate(() => document.body.innerText.slice(0, 600));
    throw new Error(tag + ' 超排 Tab 未解锁。面板文本: ' + panelText.split('\n').join(' | ').slice(0, 400));
  }
}
/** 切超排 Tab 并清 tour。 */
async function openNesting(page) {
  await page.click('button.tab:has-text("超排")');
  await page.waitForTimeout(800);
  await dismissTour(page);
}
/** 勾前 n 个码号 + 设求解时长（秒）。 */
async function prepareSolve(page, nSizes, seconds) {
  const boxes = page.locator('input[type=checkbox]');
  const n = await boxes.count();
  for (let i = 0; i < Math.min(nSizes, n); i++) await boxes.nth(i).check();
  await page.fill('#time', String(seconds));
}
/** 捕获该 page 的全部 WS 帧与服务端消息（json 解析失败跳过）。
 * framereceived 载荷形状随 Playwright 版本而异（旧版 string / 新版 {payload} 对象
 * —— 后者 .toString() 得 '[object Object]' 会静默丢全部帧），统一归一为字符串。 */
function frameText(f) {
  if (typeof f === 'string') return f;
  if (f && typeof f.payload === 'string') return f.payload;
  if (f && f.payload != null && typeof f.payload === 'object') return String.fromCharCode(...f.payload);
  return '';
}
function captureWs(page) {
  const cap = { url: null, msgs: [] };
  page.on('websocket', (ws) => {
    cap.url = ws.url();
    ws.on('framereceived', (f) => {
      try { cap.msgs.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
    });
  });
  return cap;
}
async function waitMsg(cap, type, timeout = 90000) {
  const t0 = Date.now();
  for (;;) {
    const m = cap.msgs.find((x) => x && x.type === type);
    if (m) return m;
    if (Date.now() - t0 > timeout) return null;
    await new Promise((r) => setTimeout(r, 500));
  }
}
/** 页面内裸 fetch 取证（不经 apiFetch —— 不注入 sid；仅测试用）。 */
async function rawFetch(page, url, init = null) {
  return page.evaluate(async ({ u, i }) => {
    const r = await fetch(u, i);
    let body = null;
    try { body = await r.json(); } catch { body = null; }
    return { status: r.status, body, headers: Object.fromEntries(r.headers.entries()) };
  }, { u: url, i: init });
}
/** 等 commit 完成：超排 Tab 解锁只代表 parse done（commit 后台 1-2 分钟），commit
 * done 的数据层信号 = 本会话 ptypes 出现非空 representatives（commit 成功才把
 * per-doc 快照挂进会话）。prevBody 给定时还要求响应体已变化（换母版重 commit）。
 * 返回最终响应体 JSON 串。 */
async function waitCommitted(page, sid, prevBody = null, timeout = 240000) {
  const t0 = Date.now();
  for (;;) {
    const r = await rawFetch(page, '/api/ptypes', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
    const keys = Object.keys(r.body?.representatives || {});
    const body = JSON.stringify(r.body);
    if (r.status === 200 && keys.length > 0 && (prevBody === null || body !== prevBody)) return body;
    if (Date.now() - t0 > timeout) throw new Error('commit 未完成（ptypes 空）: status=' + r.status + ' keys=' + keys.length);
    await new Promise((res) => setTimeout(res, 3000));
  }
}

if (!EXPIRE) {
  // ============================= 主相位 P1-P8 =============================
  const ctxA = await browser.newContext();
  const pageA = await ctxA.newPage();
  const reqsA = [];
  pageA.on('request', (r) => reqsA.push({ url: r.url(), sid: r.headers()['x-session-id'] || null }));
  await pageA.goto(BASE, { waitUntil: 'networkidle' });
  const sidA = await pageA.evaluate(() => localStorage.getItem('ms_sid'));

  const ctxB = await browser.newContext();
  const pageB = await ctxB.newPage();
  const reqsB = [];
  pageB.on('request', (r) => reqsB.push({ url: r.url(), sid: r.headers()['x-session-id'] || null }));
  await pageB.goto(BASE, { waitUntil: 'networkidle' });
  const sidB = await pageB.evaluate(() => localStorage.getItem('ms_sid'));
  check('P1 双窗口 sid 各自 32hex 且互不相同', SID_RE.test(sidA || '') && SID_RE.test(sidB || '') && sidA !== sidB,
    (sidA || '').slice(0, 8) + ' / ' + (sidB || '').slice(0, 8));

  // P1/P2：并行上传不同母版（两次 parse 后两个 commit 服务端并发跑），waitCommitted
  // 等各自会话 ptypes 出数据（commit done 的数据层信号）
  await uploadAndWaitCommit(pageA, DXF_A1, 'A');
  await uploadAndWaitCommit(pageB, DXF_B, 'B');
  const bodyA = await waitCommitted(pageA, sidA);
  const bodyB = await waitCommitted(pageB, sidB);
  check('P1a A commit 5336 完成（ptypes 非空）', bodyA.includes('g01'));
  check('P1b B commit M1787 完成（ptypes 非空）', bodyB.includes('g01'));

  // P2：ptypes 互不串台（各自 sid 直取响应体对比 + 请求 Header 取证）
  const ptA = { status: 200, body: JSON.parse(bodyA) };
  const ptB = { status: 200, body: JSON.parse(bodyB) };
  check('P2a 双窗口 ptypes 响应体互不相同（数据层不串台）',
    ptA.status === 200 && ptB.status === 200 && bodyA.includes('g01') && bodyB.includes('g01') && bodyA !== bodyB);
  const ptReqA = reqsA.filter((r) => r.url.includes('/api/ptypes') && r.sid === sidA);
  const ptReqB = reqsB.filter((r) => r.url.includes('/api/ptypes') && r.sid === sidB);
  check('P2b 全部 /api/ptypes 请求带各自 X-Session-Id', ptReqA.length > 0 && ptReqB.length > 0
    && reqsA.filter((r) => r.url.includes('/api/ptypes')).every((r) => r.sid === sidA)
    && reqsB.filter((r) => r.url.includes('/api/ptypes')).every((r) => r.sid === sidB),
    'A n=' + ptReqA.length + ' B n=' + ptReqB.length);

  // P3：B 求解中 A commit 第三母版 —— B 不中断、结果仍属 B 母版
  await openNesting(pageB);
  const wsB = captureWs(pageB);
  await prepareSolve(pageB, 3, 150);
  await pageB.click('#start');
  const manifestB = await waitMsg(wsB, 'manifest');
  check('P3a B 求解启动收到 manifest（WS ?sid=sidB）', !!manifestB && !!wsB.url && wsB.url.includes('sid=' + sidB), wsB.url || 'no ws');
  const pidsB = (manifestB?.pieces || []).map((p) => p.id);
  const sizesB = [...new Set(pidsB.map((pid) => pid.split('_').pop()))];
  // B 求解期间（150s 预算）：A 回上传预览页换第三母版 5156 → commit（ptypes 换体 = done）
  await pageA.click('button.tab:has-text("上传预览")');
  const tCommitA2 = Date.now();
  await uploadAndWaitCommit(pageA, DXF_A2, 'A2');
  await waitCommitted(pageA, sidA, bodyA);
  const commitA2Sec = ((Date.now() - tCommitA2) / 1000).toFixed(0);
  const errDuring = wsB.msgs.find((m) => m && m.type === 'error');
  check('P3b A commit 5156 期间 B 求解无 error', !errDuring, 'commit ' + commitA2Sec + 's, err=' + (errDuring?.message || 'none'));
  const finalB = await waitMsg(wsB, 'final', 210000);
  check('P3c B 求解不被中断（收到 final）', !!finalB && finalB.density > 0, finalB ? 'density=' + finalB.density.toFixed(4) : 'no final');
  // final 帧不带 placed_items（仅 frame 帧携带）→ 取最后一帧的 placed 集合校验归属
  const framesB = wsB.msgs.filter((m) => m && m.type === 'frame');
  const placedB = framesB.at(-1)?.placed_items || [];
  const placedOk = placedB.length > 0 && placedB.every((it) => pidsB.includes(it.id));
  check('P3d B final placed 全属 B 母版 manifest（pid 无外来）', placedOk,
    'n=' + placedB.length + ' sizes=' + sizesB.join(','));
  const ptB2 = await rawFetch(pageB, '/api/ptypes', { headers: { 'X-Session-Id': sidB }, cache: 'no-store' });
  check('P3e A commit 后 B ptypes 不漂移（仍是 B 母版）',
    ptB2.status === 200 && JSON.stringify(ptB2.body) === bodyB);
  const noModalB = await pageB.evaluate(() => document.querySelector('.session-block-overlay') === null);
  check('P3f B 全程无会话阻断弹窗', noModalB);

  // P4：A 求解 → 停止（stopped 帧）
  await openNesting(pageA);
  const wsA = captureWs(pageA);
  await prepareSolve(pageA, 3, 60);
  await pageA.click('#start');
  const frameA = await waitMsg(wsA, 'frame', 90000);
  check('P4a A 求解出帧', !!frameA && !!wsA.url && wsA.url.includes('sid=' + sidA));
  await pageA.click('#stop');
  const stoppedA = await waitMsg(wsA, 'stopped', 15000);
  check('P4b A 停止 → stopped 帧（进程终止不误伤会话）', !!stoppedA && stoppedA.reason === 'user_requested');

  // P5：B 导出 DXF（响应 200 + sidB + M1787 前缀文件名）
  let exportResp = null;
  pageB.on('response', (r) => { if (r.url().includes('/export')) exportResp = r; });
  await pageB.selectOption('select.export-fmt', 'dxf');
  await pageB.click('button.export');
  for (let i = 0; i < 40 && !exportResp; i++) await pageB.waitForTimeout(500);
  const cd = exportResp ? (exportResp.headers()['content-disposition'] || '') : '';
  check('P5 B 导出 DXF 成功且属 B 会话',
    !!exportResp && exportResp.status() === 200
    && exportResp.request().headers()['x-session-id'] === sidB
    && decodeURIComponent(cd).includes('M1787'),
    exportResp ? exportResp.status() + ' ' + cd.slice(0, 60) : 'no response');

  // P6：高级运行双会话并发 —— A 启动 running 后 B 也 202（跨会话不 409）；A 终止不影响 B
  async function strategyStart(page, tag) {
    await page.click('[data-testid=strategy-btn]');
    await page.waitForSelector('[data-testid=strategy-exec-btn]', { timeout: 10000 });
    await page.selectOption('#strategy-minutes', '10');
    await page.click('[data-testid=strategy-exec-btn]');
    await page.waitForSelector('[data-testid=strategy-progress-title]', { timeout: 60000 });
    const title = await page.textContent('[data-testid=strategy-progress-title]');
    console.log('      [' + tag + '] progress: ' + (title || '').trim());
  }
  // 等进度视图大数字出值（≠'—'）= CLI 已落首个 best_frame_s*.json，
  // 此时停止才保证 result 端点有产物可读（否则 409 → 前端滞留 loading 占位）。
  async function waitDensity(page, tag, timeout = 300000) {
    const t0 = Date.now();
    for (;;) {
      const txt = ((await page.textContent('[data-testid=strategy-big-density]', { timeout: 5000 }).catch(() => null)) || '').trim();
      if (txt && txt !== '—') { console.log('      [' + tag + '] best density: ' + txt); return txt; }
      if (Date.now() - t0 > timeout) throw new Error(tag + ' 首个 best_frame 未落盘（density 仍为 —）');
      await page.waitForTimeout(3000);
    }
  }
  await strategyStart(pageA, 'A');
  check('P6a A 高级运行进入进度态（running）', true);
  await strategyStart(pageB, 'B');
  check('P6b B 高级运行并发启动（跨会话不 409）', true);
  await waitDensity(pageA, 'A');
  await waitDensity(pageB, 'B');
  const stratReqA = reqsA.filter((r) => r.url.includes('/api/strategy/')).map((r) => r.sid);
  const stratReqB = reqsB.filter((r) => r.url.includes('/api/strategy/')).map((r) => r.sid);
  check('P6c 策略请求全部带各自 sid',
    stratReqA.length > 0 && stratReqB.length > 0
    && stratReqA.every((s) => s === sidA) && stratReqB.every((s) => s === sidB),
    'A n=' + stratReqA.length + ' B n=' + stratReqB.length);
  await pageA.click('[data-testid=strategy-stop-btn]');
  await pageA.waitForSelector('[data-testid=strategy-result-head]', { timeout: 60000 });
  const headA = (await pageA.textContent('[data-testid=strategy-result-head]')) || '';
  check('P6d A 终止运行 → 结果态', headA.includes('已终止'), headA.trim());
  // A 终止后 B 不受影响：仍在进度态，或已自然跑完进入结果态（均非被杀中断）
  await pageB.waitForTimeout(2500);
  const bStillRunning = await pageB.evaluate(() => {
    const t = document.querySelector('[data-testid=strategy-progress-title]');
    const done = document.querySelector('[data-testid=strategy-result-head]');
    return (t !== null || done !== null) && document.querySelector('.session-block-overlay') === null;
  });
  check('P6e A 终止不影响 B（B 进度态或自然完成）', bStillRunning);
  const bStopBtn = await pageB.$('[data-testid=strategy-stop-btn]');
  if (bStopBtn) await pageB.click('[data-testid=strategy-stop-btn]');
  await pageB.waitForSelector('[data-testid=strategy-result-head]', { timeout: 60000 });
  const headB = (await pageB.textContent('[data-testid=strategy-result-head]')) || '';
  check('P6f B 终止运行 → 结果态', headB.includes('已终止') || headB.includes('完成'), headB.trim());
  await pageA.click('[data-testid=strategy-close]').catch(() => {});
  await pageB.click('[data-testid=strategy-close]').catch(() => {});

  // P7：超限 —— C/D 占满 4 席后第 5 窗口加载即弹「用户过多」
  const ctxC = await browser.newContext(); const pageC = await ctxC.newPage();
  await pageC.goto(BASE, { waitUntil: 'networkidle' });
  const ctxD = await browser.newContext(); const pageD = await ctxD.newPage();
  await pageD.goto(BASE, { waitUntil: 'networkidle' });
  const ctxE = await browser.newContext(); const pageE = await ctxE.newPage();
  await pageE.goto(BASE, { waitUntil: 'networkidle' });
  await pageE.waitForSelector('.session-block-overlay', { timeout: 10000 }).catch(() => {});
  const textE = await modalText(pageE);
  check('P7 第 5 窗口页面加载即弹「用户过多」', textE === '当前使用用户过多（最多 4 人同时在线），请稍后尝试', textE || 'no modal');
  const noModalCD = await pageC.evaluate(() => document.querySelector('.session-block-overlay') === null)
    && await pageD.evaluate(() => document.querySelector('.session-block-overlay') === null);
  check('P7b 第 3/4 窗口正常（无弹窗）', noModalCD);

  // P8：default 无 sid 回归（旧 curl/脚本路径；裸 fetch 取证）
  const sess = await rawFetch(pageC, '/api/session', { method: 'POST' });
  check('P8a 无 Header POST /api/session → 200 sid=default', sess.status === 200 && sess.body?.sid === 'default' && sess.body?.ok === true);
  const ptDef = await rawFetch(pageC, '/api/ptypes', { cache: 'no-store' });
  check('P8b 无 Header GET /api/ptypes → 200（default 会话，无阻断）', ptDef.status === 200 && !!ptDef.body?.representatives);
  const idx = await rawFetch(pageC, '/', { cache: 'no-store' });
  check('P8c GET / 响应头 Cache-Control: no-cache', (idx.headers['cache-control'] || '').includes('no-cache'),
    idx.headers['cache-control'] || 'none');
} else {
  // ============================= 生命周期相位 E1-E3（TTL=6）=============================
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const sid1 = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('E0 初始 sid 落库', SID_RE.test(sid1 || ''), sid1 || '');

  // 上传+commit；TTL=6 下 commit（1-2 分钟）不是被测活性场景 —— 测试脚手架每 3s
  // POST /api/session 保活，仅为抵达「已 commit 且会话活着」态（等价用户在页面上活跃）。
  const keepAlive = setInterval(() => {
    void page.evaluate(async (sid) => {
      try { await fetch('/api/session', { method: 'POST', headers: { 'X-Session-Id': sid } }); } catch { /* 忽略 */ }
    }, sid1).catch(() => {});
  }, 3000);
  await uploadAndWaitCommit(page, DXF_W, 'W');
  await waitCommitted(page, sid1);
  clearInterval(keepAlive);
  await openNesting(page);

  // E1：求解中不误杀 —— TTL=6 下跑 20s 求解（期间客户端不发消息，靠 ws 钉住 + 回调
  // touch），照常 final；求解后立刻操作不弹过期（会话活着穿过整个求解窗口）。
  const ws = captureWs(page);
  await prepareSolve(page, 3, 20);
  await page.click('#start');
  const final = await waitMsg(ws, 'final', 90000);
  check('E1a TTL=6 求解 20s 照常 final（ws 钉住不误杀）', !!final && final.density > 0,
    final ? 'density=' + final.density.toFixed(4) : 'no final');
  await page.click('button.per-type-btn');
  let gCodes = [];
  for (let i = 0; i < 15; i++) {
    gCodes = await page.$$eval('.per-type-modal thead .qty-label-badge', (els) =>
      [...new Set(els.map((el) => (el.textContent || '').trim()).filter((t) => /^g\d+$/.test(t)))],
    );
    if (gCodes.length > 0) break;
    await page.waitForTimeout(1000);
  }
  const noModalAfterSolve = await page.evaluate(() => document.querySelector('.session-block-overlay') === null);
  check('E1b 求解后操作不弹过期（会话穿过求解窗口）', gCodes.length > 0 && noModalAfterSolve, 'g 码 n=' + gCodes.length);
  await page.click('.per-type-close').catch(() => {});
  await page.waitForTimeout(300);

  // E2：策略轮询中不误杀 —— start 后弹窗 2s 轮询 status（轮询即活性），观察 15s 不弹过期。
  await page.click('[data-testid=strategy-btn]');
  await page.waitForSelector('[data-testid=strategy-exec-btn]', { timeout: 10000 });
  await page.selectOption('#strategy-minutes', '10');
  await page.click('[data-testid=strategy-exec-btn]');
  await page.waitForSelector('[data-testid=strategy-progress-title]', { timeout: 60000 });
  check('E2a 策略启动进入进度态', true);
  await page.waitForTimeout(15000);
  const stillRunning = await page.evaluate(() => {
    const t = document.querySelector('[data-testid=strategy-progress-title]');
    return t !== null && document.querySelector('.session-block-overlay') === null;
  });
  check('E2b 策略轮询 15s（>TTL 6s）不弹过期、仍在进度态', stillRunning);
  await page.click('[data-testid=strategy-stop-btn]');
  await page.waitForSelector('[data-testid=strategy-result-head]', { timeout: 60000 });
  const head = (await page.textContent('[data-testid=strategy-result-head]')) || '';
  check('E2c 终止策略 → 结果态（会话全程未被误杀）', head.includes('已终止'), head.trim());
  await page.click('[data-testid=strategy-close]').catch(() => {});
  await page.waitForTimeout(500);

  // E3：空闲 >TTL → 任一操作弹「已过期」→ ms_sid 丢弃 → 刷新 → 干净新会话。
  await page.waitForTimeout(10000); // 静置 10s > TTL 6s（无任何会话触点）
  // 触点须走 apiFetch 才会吃到 401（高级配置弹窗/超排 tab 均纯本地无请求）
  // → E1 的 final 结果还在，点导出（POST /export 恒发请求）
  await page.selectOption('select.export-fmt', 'dxf');
  await page.click('button.export');
  let text = null;
  for (let i = 0; i < 30; i++) {
    text = await modalText(page);
    if (text) break;
    await page.waitForTimeout(1000);
  }
  check('E3a 空闲 >TTL 后操作弹「会话已过期」', text === '会话已过期（10 分钟无操作），请刷新页面', text || 'no modal');
  const sidAfter = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('E3b 弹窗后 ms_sid 已丢弃', sidAfter === null, 'ms_sid=' + sidAfter);
  await page.click('.session-block-reload');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  const sid2 = await page.evaluate(() => localStorage.getItem('ms_sid'));
  const textAfter = await modalText(page);
  check('E3c 刷新后新 sid 且无弹窗（干净新会话）', SID_RE.test(sid2 || '') && sid2 !== sid1 && textAfter === null,
    (sid1 || '').slice(0, 8) + '>' + (sid2 || '').slice(0, 8));
}

const failed = results.filter((r) => !r.ok);
console.log('\n==== 多会话 US-007 ' + (EXPIRE ? '生命周期相位' : '主相位') + ': ' + (results.length - failed.length) + '/' + results.length + ' passed ====');
await browser.close();
process.exit(failed.length ? 1 : 0);

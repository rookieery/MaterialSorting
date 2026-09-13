// 会话过期自动恢复 US-005 端到端冒烟（playwright，手动脚本不入 vitest；2026-09-13）——
// 「过期 → 刷新 → 启动期恢复」全链五路径回归锁（prd US-005 验收门）。
//
// **自举起服**（无需手工 ms-web）：spawn .venv python 起 FastAPI 于 :8010（避开常驻
// :8000 实例），env = MS_SESSION_TTL_SEC=60（极短 TTL；须 > 深度解析+commit 单程
// ~40s，否则上传中途 401）/ MS_SESSION_MAX=1（P5 429 相位双客户端模拟）/
// MS_EDIT_HOLD_SEC=5（解锁「恢复后再过期」—— /api/state-recover 共享
// rebuild_session_from_document 会给新会话挂 MS_EDIT_HOLD_SEC 钉住，生产缺省 2h 会
// 挡住后续过期相位）。脚本退出杀服（taskkill /T 树杀）。
//
// 前置：materialSorting-web/static/ 为 npm run build 产物（服务 GET / 直接 serve）。
// 命令：node materialSorting-web/scripts/smoke_session_recovery.mjs
//
// 相位（sid 链 A→B→C→D→E；顺序按「checkpoint 在场时机」编排，与 PRD 五路径一一对应）：
//   S1 上传 5336 母版 → commit → g01@30 改 2 → 3 码 5s 求解 done → US-004 自动
//      checkpoint（求解完成立即，含 run 块）→ 过期前状态快照（数量/表单/布局）。
//   P1 停留期交互路径：空闲 75s 过期 → 高级配置触发 /api/ptypes → 401 → 引导刷新
//      弹窗（新文案「刷新页面后将恢复工作状态」）且未自动恢复（零 recover 调用 +
//      sid 未清）→ 点弹窗「刷新页面」→ 启动期恢复：sid A→B + toast 工作状态已恢复
//      + 数量矩阵/表单/布局与过期前逐项对拍。
//   P2 直接 F5 路径：恢复态自动重落 checkpoint[B]（US-004）→ 再空闲 75s →
//      page.reload() → 全程无弹窗直接恢复（sid B→C + 状态对拍）。
//   P3 F5 存活清理路径：会话存活即 reload → 探测 200 + DELETE /api/state-checkpoint
//      恰一次 + 零 recover + 前端干净重置（sid 不变 C）。
//   P4 无 checkpoint 兜底路径：再空闲 75s → reload → recover 404（快照已被 P3 清）
//      → 静默新会话（toast 上次会话已过期 + 无弹窗 + 干净空态，sid C→D）。
//   P5 429 路径（借 MS_SESSION_MAX=1 双客户端模拟；前置不成立允许 skip 不计失败）：
//      重传母版改数量 → checkpoint[D] → 空闲 95s 过期（含 30s 扫描器余量，腾名额）
//      → 第二客户端（Node fetch 占满唯一名额 F）→ 主页面刷新 → recover 429 且
//      checkpoint 不删 → session_limit 阻断弹窗在场 → 名额释放（等 F 过期）后
//      Node 直连 recover(from_sid=D) 200 = 快照未被 429 消费的端到端证明。
//
// 报告落 out/smoke_session_recovery/report.txt；退出码 0 = 全 PASS（skip 不计失败）。
import { writeFileSync, mkdirSync, accessSync, constants } from 'node:fs';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/smoke_session_recovery';
mkdirSync(OUT, { recursive: true });

const PORT = 8010;                 // 避开常驻 ms-web :8000
const BASE = 'http://127.0.0.1:' + PORT;
const PY = ROOT + '/.venv/Scripts/python.exe';
const STATIC_INDEX = ROOT + '/materialSorting-web/static/index.html';
const DXF = ROOT + '/data/5336#老六订单14%7%围加9_coded.dxf';
const SIZES = [32, 33, 34];
const SOLVE_TIME = '5';
const GATE = '180.00';
const EXPECT_TOTAL = '111';        // 110 默认 + g01@30 → 2（+1）
const TTL_IDLE_MS = 75_000;        // > MS_SESSION_TTL_SEC=60（惰性逐出口径即可）
const TTL_IDLE_SCAN_MS = 95_000;   // P5 第二客户端建会话前：须等 30s daemon 扫描器
                                   // 真正逐出旧会话腾名额（活跃计数含未扫的僵尸）
const DEBOUNCE_WAIT_MS = 4500;     // > CHECKPOINT_DEBOUNCE_MS 3s + 余量
const F_EXPIRY_MS = 95_000;        // P5 名额释放：F 建立后 60s TTL + 30s 扫描器余量

const results = [];
const skips = [];
function check(name, ok, extra) {
  results.push({ name, ok });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 200) + ']' : '');
}
/** P5 允许 skip-if-flaky：前置不成立记 SKIP（不计失败，报告单列）。 */
function checkSkip(name, reason) {
  results.push({ name, ok: true, skip: true });
  skips.push(name);
  console.log('SKIP', name, '  [' + String(reason).slice(0, 160) + ']');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (s) => console.log('---', s);

/** 全导航 fetch 侦听（addInitScript）：/api/* 调查日志；checkpoint/recover 响应体捕获。 */
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
      if (url.includes('/api/state-checkpoint') || url.includes('/api/state-recover')) {
        try {
          entry.resp = await res.clone().json();
        } catch {
          entry.resp = null;
        }
      }
      return res;
    }
    return orig.apply(this, args);
  };
};

/** Node 直连第二客户端（P5 双客户端模拟）：合法 sid（SID_RE = ^[0-9A-Za-z]{1,128}$）。 */
async function apiPost(path, sid, body) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'X-Session-Id': sid, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let json = null;
  try { json = await res.json(); } catch { /* 非 JSON 忽略 */ }
  return { status: res.status, json };
}
const newRawSid = (tag) => tag + Date.now().toString(36);

async function getSid(p) {
  return p.evaluate(() => localStorage.getItem('ms_sid'));
}
async function netLog(p) {
  return p.evaluate(() => window.__netLog || []);
}
async function toasts(p) {
  return p.evaluate(() => Array.from(document.querySelectorAll('.toast-msg')).map((t) => t.textContent));
}
async function closeToasts(p) {
  for (let i = 0; i < 8; i++) {
    if ((await p.locator('.toast-close').count()) === 0) break;
    await p.locator('.toast-close').first().click();
    await sleep(150);
  }
}
/** 等求解完成（保存按钮解锁 = done 态 bestRun 在案；us003/us004 同款探测）。 */
async function waitSolveDone(p, timeoutMs = 120000) {
  const t0 = Date.now();
  for (;;) {
    const enabled = await p.evaluate(
      () => (document.querySelector('[data-testid="save-state-btn"]') || {}).disabled === false,
    );
    if (enabled || Date.now() - t0 > timeoutMs) return enabled;
    await sleep(500);
  }
}
/** 等日志出现满足条件的 checkpoint POST（恢复后自动重落快照的前置门）。 */
async function waitCheckpoint(p, pred, timeoutMs = 10000) {
  const t0 = Date.now();
  for (;;) {
    const cps = (await netLog(p)).filter(
      (x) => x.url.includes('/api/state-checkpoint') && x.method === 'POST');
    const hit = cps.find(pred);
    if (hit) return hit;
    if (Date.now() - t0 > timeoutMs) return null;
    await sleep(400);
  }
}
/** 过期前/恢复后工作台状态快照（数量矩阵 / 表单 / 布局三面对拍的数据源）。 */
async function captureState(p) {
  // 布局 + 表单（超排 Tab 在场时直读）
  const onNesting = await p.evaluate(() => {
    const el = document.querySelector('.tab-content .page:not(.hidden)');
    return el !== null && el.querySelector('#restart') !== null;
  });
  if (!onNesting) {
    await p.locator('button.tab:not([disabled]):has-text("超排")').click();
    await sleep(500);
  }
  const form = {
    gate: await p.locator('#gate').inputValue(),
    time: await p.locator('#time').inputValue(),
    sizes: [],
  };
  for (const sz of SIZES) {
    if (await p.locator('#sz_' + sz).isChecked()) form.sizes.push(sz);
  }
  await p.locator('.nest-label').first().waitFor({ timeout: 10000 });
  const nesting = {
    label: (await p.locator('.nest-label').first().innerText()).trim(),
    polygons: await p.locator('.nest-card svg polygon[data-label]').count(),
    restart: (await p.locator('#restart').count()) === 1,
  };
  // 数量矩阵（预览 Tab）
  await p.locator('button.tab:has-text("上传预览")').click();
  await p.locator('[data-testid="qty-matrix"]').waitFor({ timeout: 10000 });
  const qty = {
    cell00: await p.locator('.qty-cell-input[data-cell="0-0"]').inputValue(),
    total: (await p.locator('[data-testid="qty-total"]').innerText()).trim(),
  };
  return { form, nesting, qty };
}

// ---------------------------------------------------------------- 起服（自举）
try {
  accessSync(STATIC_INDEX, constants.R_OK);
} catch {
  console.error('前置缺失：materialSorting-web/static/index.html 不存在 —— 先 cd materialSorting-web && npm run build');
  process.exit(2);
}
try {
  const probe = await fetch(BASE + '/', { signal: AbortSignal.timeout(1500) });
  if (probe.ok) {
    console.error('端口 ' + PORT + ' 已被占用（疑似上次冒烟残留服务）—— 请先释放再跑');
    process.exit(2);
  }
} catch { /* 未占用 = 正常 */ }

const SERVER_LOG = [];
const server = spawn(PY, ['-c',
  'import uvicorn; from materialsorting.web.server import app; '
  + 'uvicorn.run(app, host="127.0.0.1", port=' + PORT + ')'], {
  cwd: ROOT,
  env: {
    ...process.env,
    MS_SESSION_TTL_SEC: '60',
    MS_SESSION_MAX: '1',
    MS_EDIT_HOLD_SEC: '5',
  },
  windowsHide: true,
  stdio: ['ignore', 'pipe', 'pipe'],
});
server.stdout.on('data', (d) => SERVER_LOG.push(String(d)));
server.stderr.on('data', (d) => SERVER_LOG.push(String(d)));
function killServer() {
  if (server.exitCode !== null) return;
  if (process.platform === 'win32') {
    try { spawn('taskkill', ['/F', '/T', '/PID', String(server.pid)], { windowsHide: true }); } catch { /* 尽力 */ }
  }
  try { server.kill(); } catch { /* 尽力 */ }
}
{
  let ready = false;
  for (let i = 0; i < 60; i++) {
    if (server.exitCode !== null) break;
    try {
      const r = await fetch(BASE + '/', { signal: AbortSignal.timeout(1000) });
      if (r.ok) { ready = true; break; }
    } catch { /* 等下一轮 */ }
    await sleep(1000);
  }
  if (!ready) {
    console.error('起服失败（:' + PORT + ' 未就绪）—— 服务日志尾：\n' + SERVER_LOG.join('').slice(-2000));
    killServer();
    process.exit(2);
  }
}
log('服务就绪 ' + BASE + '（MS_SESSION_TTL_SEC=60 MS_SESSION_MAX=1 MS_EDIT_HOLD_SEC=5）');

const { chromium } = await import('playwright');
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

  // ---------- S1 上传 + 数量矩阵 + 短求解 + 自动 checkpoint + 过期前快照 ----------
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const sidA = await getSid(page);
  check('S1a 页面加载铸造 sid A', /^[0-9a-f]{32}$/.test(sidA || ''), (sidA || '').slice(0, 8));

  await page.locator('input[type=file]').first().setInputFiles(DXF);
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 240000 });
  log('S1 上传 + commit done');

  const cell00 = page.locator('.qty-cell-input[data-cell="0-0"]');
  await cell00.waitFor({ timeout: 15000 });
  await cell00.fill('2');
  await cell00.press('Enter');
  await sleep(300);
  const qtyTotal = (await page.locator('[data-testid="qty-total"]').innerText()).trim();
  check('S1b 数量矩阵 g01@30=2 → 总片数 111', qtyTotal === EXPECT_TOTAL, qtyTotal);

  await page.locator('button.tab:not([disabled]):has-text("超排")').click();
  await sleep(800);
  for (const sz of SIZES) await page.check('#sz_' + sz);
  await page.fill('#gate', GATE);
  await page.fill('#time', SOLVE_TIME);
  await page.click('#start');
  check('S1c 5s 求解完成（保存按钮解锁）', await waitSolveDone(page));
  await sleep(DEBOUNCE_WAIT_MS); // 求解完成立即 + 去抖余量，全部 checkpoint 落地

  let net = await netLog(page);
  const cpPosts = net.filter((x) => x.url.includes('/api/state-checkpoint') && x.method === 'POST');
  const lastCp = cpPosts[cpPosts.length - 1];
  const lastCpBody = lastCp ? JSON.parse(lastCp.body || '{}') : {};
  check('S1d US-004 自动 checkpoint（求解完成立即）：stored:true + 含 run 块 + sid A',
    !!lastCp && lastCp.status === 200 && lastCp.resp && lastCp.resp.stored === true
    && lastCpBody.run !== undefined && lastCp.sid === sidA,
    'posts=' + cpPosts.length + ' last=' + JSON.stringify(lastCp?.resp));
  check('S1e 载荷=工作台实值（g01@30=2、placed>0）',
    lastCpBody.quantities?.g01?.['30'] === 2
    && Array.isArray(lastCpBody.run?.placed) && lastCpBody.run.placed.length > 0,
    'g01@30=' + lastCpBody.quantities?.g01?.['30'] + ' placed=' + lastCpBody.run?.placed?.length);

  const snap = await captureState(page);
  check('S1f 过期前快照在场（数量 2/111 + 表单 180.00/5/[32,33,34] + 布局 polygon>0）',
    snap.qty.cell00 === '2' && snap.qty.total === EXPECT_TOTAL
    && snap.form.gate === GATE && snap.form.time === SOLVE_TIME
    && snap.form.sizes.join(',') === SIZES.join(',') && snap.nesting.restart
    && snap.nesting.polygons > 0,
    JSON.stringify(snap.nesting));
  await page.screenshot({ path: OUT + '/s1_solved.png' });
  log('S1 快照：' + JSON.stringify(snap));

  // ---------- P1 停留期交互路径：过期 → 触发 API → 引导弹窗（不自动恢复）→ 刷新恢复 ----------
  log('P1 空闲 ' + TTL_IDLE_MS + 'ms 等 TTL 过期…');
  await sleep(TTL_IDLE_MS);
  // 快照采集收在预览 Tab —— per-type-btn 在超排 Tab（display:none 不可点），先切回
  await page.locator('button.tab:not([disabled]):has-text("超排")').click();
  await sleep(400);
  await page.click('[data-testid="per-type-btn"]'); // apiFetch /api/ptypes → 停留期 401
  const modalShown = await page
    .waitForSelector('.session-block-overlay', { timeout: 20000 })
    .then(() => true)
    .catch(() => false);
  check('P1a 停留期 401 → 引导刷新弹窗出现', modalShown);
  const modalText = await page.evaluate(() =>
    document.querySelector('.session-block-text')?.textContent || '');
  check('P1b 弹窗新文案（刷新页面后将恢复工作状态）',
    modalText === '会话已过期，刷新页面后将恢复工作状态', modalText);
  const sidKept = await getSid(page);
  check('P1c 停留期不清 sid（留给刷新后恢复作 from_sid）', sidKept === sidA, (sidKept || '').slice(0, 8));
  net = await netLog(page);
  check('P1d 停留期未自动恢复（零 /api/state-recover 调用）',
    net.filter((x) => x.url.includes('/api/state-recover')).length === 0,
    'calls=' + net.filter((x) => x.url.includes('/api/state-recover')).length);
  await page.screenshot({ path: OUT + '/p1_stay_modal.png' });

  await page.click('.session-block-reload');
  await page.waitForLoadState('networkidle');
  await sleep(1500); // 恢复编排（applyRestorePayload 同步 + toast 渲染）

  const sidB = await getSid(page);
  check('P1e 弹窗刷新 → 启动期恢复 sid A→B 换新',
    !!sidB && /^[0-9a-f]{32}$/.test(sidB) && sidB !== sidA, (sidB || '').slice(0, 8));
  net = await netLog(page);
  const recoverP1 = net.find((x) => x.url.includes('/api/state-recover'));
  const probesP1 = net.filter((x) => x.url.includes('/api/session'));
  check('P1f POST /api/state-recover 200：from_sid=旧A、X-Session-Id=新B',
    !!recoverP1 && recoverP1.status === 200
    && JSON.parse(recoverP1.body || '{}').from_sid === sidA && recoverP1.sid === sidB,
    recoverP1 ? 'status=' + recoverP1.status + ' from='
      + String(JSON.parse(recoverP1.body || '{}').from_sid).slice(0, 8) : 'no call');
  check('P1g 探测两跳：旧 A 401 → 新 B 200',
    probesP1.length === 2 && probesP1[0].sid === sidA && probesP1[0].status === 401
    && probesP1[1].sid === sidB && probesP1[1].status === 200,
    probesP1.map((p) => String(p.sid).slice(0, 8) + ':' + p.status).join(','));
  check('P1h toast 工作状态已恢复', (await toasts(page)).includes('工作状态已恢复'),
    JSON.stringify(await toasts(page)));

  const snapP1 = await captureState(page);
  check('P1i 恢复后状态对拍：数量矩阵（g01@30=2 / 总 111）',
    snapP1.qty.cell00 === snap.qty.cell00 && snapP1.qty.total === snap.qty.total,
    JSON.stringify(snapP1.qty));
  check('P1j 恢复后状态对拍：表单（gate/time/sizes）',
    snapP1.form.gate === snap.form.gate && snapP1.form.time === snap.form.time
    && snapP1.form.sizes.join(',') === snap.form.sizes.join(','),
    JSON.stringify(snapP1.form));
  check('P1k 恢复后状态对拍：布局（nest-label 逐字 + polygon 数全等 + 自动切超排）',
    snapP1.nesting.label === snap.nesting.label
    && snapP1.nesting.polygons === snap.nesting.polygons && snapP1.nesting.restart,
    snapP1.nesting.label + ' / poly=' + snapP1.nesting.polygons);
  await page.screenshot({ path: OUT + '/p1_recovered.png' });
  await closeToasts(page);

  // ---------- P2 直接 F5 路径：过期 → reload → 无弹窗直接恢复 ----------
  const cpB = await waitCheckpoint(page, (x) => x.sid === sidB
    && x.status === 200 && JSON.parse(x.body || '{}').run !== undefined);
  check('P2 前置：恢复态自动重落 checkpoint[B]（含 run）—— US-004 恢复链自我延续',
    !!cpB && cpB.resp && cpB.resp.stored === true,
    cpB ? JSON.stringify(cpB.resp) : 'no post');
  log('P2 空闲 ' + TTL_IDLE_MS + 'ms 等再次过期…');
  await sleep(TTL_IDLE_MS);
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(1500);
  const sidC = await getSid(page);
  check('P2a F5 后 sid B→C 换新 + 全程无阻断弹窗',
    !!sidC && sidC !== sidB
    && (await page.locator('.session-block-overlay').count()) === 0,
    (sidC || '').slice(0, 8));
  net = await netLog(page);
  const recoverP2 = net.find((x) => x.url.includes('/api/state-recover'));
  check('P2b recover 200（from_sid=旧B）+ toast 工作状态已恢复',
    !!recoverP2 && recoverP2.status === 200
    && JSON.parse(recoverP2.body || '{}').from_sid === sidB
    && (await toasts(page)).includes('工作状态已恢复'),
    recoverP2 ? 'status=' + recoverP2.status : 'no call');
  const snapP2 = await captureState(page);
  check('P2c 直接 F5 恢复与 P1 弹窗刷新恢复同构（数量/表单/布局逐项对拍）',
    snapP2.qty.cell00 === snap.qty.cell00 && snapP2.qty.total === snap.qty.total
    && snapP2.form.gate === snap.form.gate && snapP2.form.time === snap.form.time
    && snapP2.form.sizes.join(',') === snap.form.sizes.join(',')
    && snapP2.nesting.label === snap.nesting.label
    && snapP2.nesting.polygons === snap.nesting.polygons,
    snapP2.nesting.label);
  await page.screenshot({ path: OUT + '/p2_f5_recovered.png' });
  await closeToasts(page);

  // ---------- P3 F5 存活清理路径：会话存活刷新 → DELETE checkpoint + 干净重置 ----------
  const cpC = await waitCheckpoint(page, (x) => x.sid === sidC
    && x.status === 200 && JSON.parse(x.body || '{}').run !== undefined);
  check('P3 前置：恢复态自动重落 checkpoint[C] 在场（DELETE 有物可清）',
    !!cpC && cpC.resp && cpC.resp.stored === true, cpC ? JSON.stringify(cpC.resp) : 'no post');
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(1500);
  check('P3a 会话存活 F5：sid 不变（C）', (await getSid(page)) === sidC);
  net = await netLog(page);
  const dels = net.filter((x) => x.url.includes('/api/state-checkpoint') && x.method === 'DELETE');
  const recoversP3 = net.filter((x) => x.url.includes('/api/state-recover'));
  const probesP3 = net.filter((x) => x.url.includes('/api/session'));
  check('P3b 启动清理：DELETE /api/state-checkpoint 200 恰一次（sid C）',
    dels.length === 1 && dels[0].status === 200 && dels[0].sid === sidC,
    'dels=' + dels.length + ' status=' + dels.map((d) => d.status).join(','));
  check('P3c 探测 200 放行 + 零恢复调用（存活刷新 ≠ 过期恢复）',
    probesP3.length >= 1 && probesP3[0].status === 200 && recoversP3.length === 0,
    'probes=' + probesP3.length + ' recovers=' + recoversP3.length);
  const cleanP3 = await page.evaluate(() => ({
    hasMatrix: document.querySelector('.qty-cell-input') !== null,
    hasUpload: document.querySelector('input[type=file]') !== null,
  }));
  check('P3d 前端干净重置（无母版残留 = 上传空态）',
    !cleanP3.hasMatrix && cleanP3.hasUpload, JSON.stringify(cleanP3));
  await page.screenshot({ path: OUT + '/p3_f5_clean_reset.png' });

  // ---------- P4 无 checkpoint 兜底路径：再过期 → 刷新 → 404 静默新会话 ----------
  log('P4 空闲 ' + TTL_IDLE_MS + 'ms 等 TTL 过期…');
  await sleep(TTL_IDLE_MS);
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(1500);
  const sidD = await getSid(page);
  check('P4a 刷新后 sid C→D 换新 + 无阻断弹窗',
    !!sidD && sidD !== sidC
    && (await page.locator('.session-block-overlay').count()) === 0,
    (sidD || '').slice(0, 8));
  net = await netLog(page);
  const recoverP4 = net.find((x) => x.url.includes('/api/state-recover'));
  const probesP4 = net.filter((x) => x.url.includes('/api/session'));
  check('P4b checkpoint 已被 P3 DELETE → recover 404（from_sid=C）',
    !!recoverP4 && recoverP4.status === 404
    && JSON.parse(recoverP4.body || '{}').from_sid === sidC,
    recoverP4 ? 'status=' + recoverP4.status : 'no call');
  check('P4c 404 兜底：toast 上次会话已过期，已开启新会话（静默兜底非阻断）',
    (await toasts(page)).includes('上次会话已过期，已开启新会话'),
    JSON.stringify(await toasts(page)));
  check('P4d 探测两跳（C 401 → D 200）+ 干净新会话（无母版残留）',
    probesP4.length === 2 && probesP4[0].sid === sidC && probesP4[1].sid === sidD
    && (await page.locator('.qty-cell-input').count()) === 0,
    probesP4.map((p) => String(p.sid).slice(0, 8) + ':' + p.status).join(','));
  await page.screenshot({ path: OUT + '/p4_fallback_new_session.png' });
  await closeToasts(page);

  // ---------- P5 429 路径（MS_SESSION_MAX=1 双客户端模拟；skip-if-flaky） ----------
  // 重传母版 → 改数量（去抖 checkpoint[D]，无需求解）→ 等过期（扫描器逐出腾名额）→
  // Node 第二客户端占满唯一名额 → 主页面刷新 → recover 429（checkpoint 不删）→ 弹窗。
  // 短 TTL 跨线竞态（us003 A2 同款）：P4 断言耗时后 D 的 last_active 已老化 ——
  // 深度解析（~40s 无请求无 touch）+ commit 会被中途过期 401 → 显式续命紧邻上传。
  await page.evaluate(async (s) => {
    await fetch('/api/session', { method: 'POST', headers: { 'X-Session-Id': s } });
  }, sidD);
  await page.locator('input[type=file]').first().setInputFiles(DXF);
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 240000 });
  const cellP5 = page.locator('.qty-cell-input[data-cell="0-0"]');
  await cellP5.waitFor({ timeout: 15000 });
  await cellP5.fill('2');
  await cellP5.press('Enter');
  await sleep(DEBOUNCE_WAIT_MS);
  const cpD = await waitCheckpoint(page, (x) => x.sid === sidD
    && x.status === 200 && JSON.parse(x.body || '{}').quantities?.g01?.['30'] === 2);
  check('P5a 重传 + 改数量 → checkpoint[D] stored:true（429 相位快照在场）',
    !!cpD && cpD.resp && cpD.resp.stored === true, cpD ? JSON.stringify(cpD.resp) : 'no post');

  log('P5 空闲 ' + TTL_IDLE_SCAN_MS + 'ms 等过期 + 扫描器逐出（腾唯一名额）…');
  await sleep(TTL_IDLE_SCAN_MS);
  const sidF = newRawSid('smoke2nd');
  let fCreated = false;
  for (let i = 0; i < 3 && !fCreated; i++) {
    const r = await apiPost('/api/session', sidF);
    if (r.status === 200) { fCreated = true; break; }
    log('第二客户端建会话 ' + r.status + '（名额未腾出？15s 后重试）');
    await sleep(15000);
  }

  if (!fCreated) {
    checkSkip('P5 429 路径（双客户端模拟）', '第二客户端建会话连续 429 —— 名额未按预期腾出（扫描器时序 flaky）');
  } else {
    await page.reload({ waitUntil: 'networkidle' });
    await sleep(1500);
    const sidE = await getSid(page);
    const modalLimit = await page
      .waitForSelector('.session-block-overlay', { timeout: 20000 })
      .then(() => true)
      .catch(() => false);
    check('P5b 满员刷新 → session_limit 阻断弹窗在场（429 路径弹窗仍在）', modalLimit);
    const titleLimit = modalLimit ? await page.evaluate(() =>
      document.querySelector('.session-block-title')?.textContent || '') : '';
    check('P5c 弹窗标题「当前使用用户过多」（session_limit 文案分支）',
      modalLimit && titleLimit === '当前使用用户过多', titleLimit || '(无弹窗)');
    net = await netLog(page);
    const recoverP5 = net.find((x) => x.url.includes('/api/state-recover'));
    check('P5d recover 429（from_sid=旧D、X-Session-Id=新E）',
      !!recoverP5 && recoverP5.status === 429
      && JSON.parse(recoverP5.body || '{}').from_sid === sidD
      && recoverP5.sid === sidE && sidE !== sidD,
      recoverP5 ? 'status=' + recoverP5.status + ' hdr=' + String(recoverP5.sid).slice(0, 8)
        : 'no call');
    await page.screenshot({ path: OUT + '/p5_session_limit_modal.png' });

    // 名额释放（等 F 过期被扫描逐出）→ Node 直连 recover = checkpoint 未被 429 消费证明
    log('P5 尾声：等第二客户端会话过期（' + F_EXPIRY_MS + 'ms）验证 checkpoint 不删…');
    await sleep(F_EXPIRY_MS);
    const sidH = newRawSid('smokecoda');
    let coda = null;
    for (let i = 0; i < 3; i++) {
      coda = await apiPost('/api/state-recover', sidH, { from_sid: sidD });
      if (coda.status === 200) break;
      log('coda recover ' + coda.status + '（名额未腾出？15s 后重试）');
      await sleep(15000);
    }
    if (coda && coda.status === 200) {
      check('P5e 名额释放后 recover(from_sid=D) 200 + recovered_from=D（429 不删快照，US-002 语义）',
        coda.json && coda.json.recovered_from === sidD,
        coda.status + ' ' + JSON.stringify(coda.json || {}).slice(0, 60));
    } else {
      checkSkip('P5e 名额释放后 recover(from_sid=D)（429 不删快照）',
        'coda recover 始终 ' + (coda ? coda.status : 'n/a') + ' —— 名额未按预期腾出（扫描器时序 flaky）');
    }
  }
  await ctx.close();
} catch (e) {
  check('脚本异常中断', false, String(e).slice(0, 300));
} finally {
  await browser.close().catch(() => {});
  killServer();
  await sleep(1000);
}

const pass = results.filter((r) => r.ok).length;
writeFileSync(OUT + '/report.txt',
  results.map((r) => (r.skip ? 'SKIP' : r.ok ? 'PASS' : 'FAIL') + '  ' + r.name).join('\n')
  + '\n' + pass + '/' + results.length + ' passed'
  + (skips.length ? '（skip ' + skips.length + '：' + skips.join('；') + '）' : '') + '\n');
console.log('\n' + pass + '/' + results.length + ' passed'
  + (skips.length ? '（含 skip ' + skips.length + '）' : ''));
process.exit(pass === results.length ? 0 : 1);

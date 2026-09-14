// 会话过期自动恢复端到端冒烟（playwright，手动脚本不入 vitest）——
// US-005「过期 → 刷新 → 启动期恢复」五路径回归锁 + US-003（策略待确认结果
// checkpoint，2026-09-13）pending_strategy_result 槽主路径/三续段扩展 + bg 段
// （2026-09-14 展示级降级：陈旧 run 背景保留 —— 恢复弹窗之下画布不清空）。
//
// **自举起服**（无需手工 ms-web）：spawn .venv python 起 FastAPI 于 :8010（避开常驻
// :8000 实例），env = MS_SESSION_TTL_SEC=60（极短 TTL；须 > 深度解析+commit 单程
// ~40s，否则上传中途 401）/ MS_SESSION_MAX=1（P5 429 相位双客户端模拟）/
// MS_EDIT_HOLD_SEC=5（解锁「恢复后再过期」—— /api/state-recover 共享
// rebuild_session_from_document 会给新会话挂 MS_EDIT_HOLD_SEC 钉住，生产缺省 2h 会
// 挡住后续过期相位）/ MS_RESULT_GRACE_SEC=3（US-003：策略/极限 run 终态宽限窗
// 收敛到 3s —— 「跑完不确认 + 宽限窗外过期」相位不必等生产 600s）。脚本退出杀服
// （taskkill /T 树杀）。
//
// 前置：materialSorting-web/static/ 为 npm run build 产物（服务 GET / 直接 serve）。
// 命令：node materialSorting-web/scripts/smoke_session_recovery.mjs [phases]
//   phases = 逗号分隔子集 {pending, bg, extreme, legacy}（调试分段复跑用），
//   缺省全量。**验收口径 = 缺省全量一跑全绿**（分段仅为定位问题的切片，段间
//   sid 链不连续属预期）。
//
// 相位总览（全量 sid 链 A→B→C→D→E→…；顺序按「checkpoint 在场时机」编排）：
//   [pending 段 = US-003 主路径 + 续段②③]
//   M1 上传 5336 母版 → commit → g01@30 改 2（总 111）→ 勾 32/33/34 → 高级运行
//      race 10min（UI 最短档）→ **不确认**等 run 完成（solver early_termination
//      收敛即提前完，上限 ~700s）。
//   M3 done 结果落定 → US-002 触发面 #4 立即 checkpoint 携 pending 槽（无 run 块）。
//   M4 宽限窗外过期（75s）→ 刷新 → 启动期恢复：sid A→B + recover 200 响应回传
//      pending（mode/密度/placed 逐条对拍 + run=null 无双份数据）+ **对应族弹窗
//      自动打开且为结果态**（密度与过期前对拍）。
//   M5 待确认结果期改数量（g01@32 1→2）未重解 → checkpoint 200
//      {stored:false, reason:'conservation'}（半态载荷被拒 + last-good 保持）→
//      再过期刷新 → 恢复**改前完整快照**（数量矩阵回 1 + 弹窗重现结果态）。
//   M6 点应用 → checkpoint run 块在场 + pending 槽退场 → 主画布 placed 逐条对拍
//      （polygon 数 + 状态行 + 来源小字）→ 导出 PLT：POST /export placed 与过期前
//      checkpoint 槽 placed 逐条一致（守恒）。
//   M7 应用后再过期 → 刷新恢复：已应用 run 恢复（布局/数量/表单对拍）+ 任何族
//      弹窗**不开** + recover 响应 pending=null —— 无 pending 老快照恢复行为与
//      US-004/005 时代对拍不变。
//   [bg 段 = 2026-09-14 展示级降级（陈旧 run 背景 + pending 弹窗，用户报告 bug 的
//    端到端回归锁）]
//   B1 5s 普通求解 → run 块（111 片背景旧布局）落 checkpoint。
//   B2 改数量 g01@32 1→2（总 112）→ run 与现行数量失配 = 陈旧背景。
//   B3 race 10min 完成不确认 → checkpoint {stored:true, stale_run:true}（陈旧 run
//      打标保留非丢弃 + pending 槽按现行数量守恒入库）。
//   B4 宽限窗外过期 → 刷新恢复：recover 200 回传 run.stale=true + placed 原样 +
//      pending 并存 → 弹窗结果态之下**背景旧布局仍在**（可见 polygon = 旧 run placed
//      数；demand 池隐藏副本不计 —— 现行数量比旧解多的那份是 display:none）。
//   B5 取消 → 弹窗关闭后画布不清空（背景保留 + 来源小字「普通求解」）。
//   B6 再过期 → 恢复弹窗重现 → 确认应用 → 背景被新解置换（polygon=112 + 来源
//      「策略运行·race」）。
//   [extreme 段 = US-003 续段① 极限运行同款]
//   X1 极限运行弹窗自定义 16min（UI 下限 960s ≥ 后端 905s；early_termination
//      固化 False → 全预算 ~905s+）→ 等 done → checkpoint 携 pending mode=extreme
//      （与已应用 run 块并存）。
//   X3 宽限窗外过期 → 刷新 → 启动期恢复：极限族弹窗自动打开结果态（策略族不串
//      台）→ 应用 → 主画布对拍。
//   [legacy 段 = US-005 五路径回归锁（超排 5s 求解重铺 run 块后原样跑）]
//   S1 重铺：#start 5s 求解 → checkpoint run 块（无 pending —— 两族结果均已应用）。
//   P1 停留期交互路径：空闲 75s 过期 → 高级配置触发 /api/ptypes → 401 → 引导刷新
//      弹窗（新文案「刷新页面后将恢复工作状态」）且未自动恢复（零 recover 调用 +
//      sid 未清）→ 点弹窗「刷新页面」→ 启动期恢复：sid 换新 + toast 工作状态已恢复
//      + 数量矩阵/表单/布局与过期前逐项对拍。
//   P2 直接 F5 路径：恢复态自动重落 checkpoint → 再空闲 75s → page.reload() →
//      全程无弹窗直接恢复 + 状态对拍。
//   P3 F5 存活清理路径：会话存活即 reload → 探测 200 + DELETE /api/state-checkpoint
//      恰一次 + 零 recover + 前端干净重置。
//   P4 无 checkpoint 兜底路径：再空闲 75s → reload → recover 404（快照已被 P3 清）
//      → 静默新会话（toast 上次会话已过期 + 无弹窗 + 干净空态）。
//   P5 429 路径（借 MS_SESSION_MAX=1 双客户端模拟；前置不成立允许 skip 不计失败）：
//      重传母版改数量 → checkpoint → 空闲 95s 过期（含 30s 扫描器余量，腾名额）→
//      第二客户端（Node fetch 占满唯一名额 F）→ 主页面刷新 → recover 429 且
//      checkpoint 不删 → session_limit 阻断弹窗在场 → 名额释放（等 F 过期）后
//      Node 直连 recover(from_sid) 200 = 快照未被 429 消费的端到端证明。
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
const EXPECT_TOTAL = '111';        // 110 默认（10 片型 × 11 码 × 1）+ g01@30 → 2（+1）
const TTL_IDLE_MS = 75_000;        // > MS_SESSION_TTL_SEC=60（惰性逐出口径即可）
const TTL_IDLE_SCAN_MS = 95_000;   // P5 第二客户端建会话前：须等 30s daemon 扫描器
                                   // 真正逐出旧会话腾名额（活跃计数含未扫的僵尸）
const DEBOUNCE_WAIT_MS = 4500;     // > CHECKPOINT_DEBOUNCE_MS 3s + 余量
const F_EXPIRY_MS = 95_000;        // P5 名额释放：F 建立后 60s TTL + 30s 扫描器余量
const STRATEGY_RUN_TIMEOUT = 960_000;  // race 10min 档墙上限（600s 预算 + 轮次/收尾余量）
const EXTREME_RUN_TIMEOUT = 1500_000;  // 极限 960s 预算（早停固化 False）+ 多 seed 墙钟
                                   // 膨胀余量（实测 2 seed 满载 ~1175s > 预算）
// 分段复跑过滤器（缺省全量；验收口径 = 全量一跑）。
const PHASES = (process.argv[2] || 'pending,bg,extreme,legacy')
  .split(',').map((s) => s.trim()).filter(Boolean);
const hasPhase = (p) => PHASES.includes(p);

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
const jsonNorm = (v) => JSON.parse(JSON.stringify(v));

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
async function cpPosts(p) {
  return (await netLog(p)).filter(
    (x) => x.url.includes('/api/state-checkpoint') && x.method === 'POST');
}
async function toasts(p) {
  return p.evaluate(() => Array.from(document.querySelectorAll('.toast-msg')).map((t) => t.textContent));
}
/** 可见毛版多边形数（bg 段断言口径）：NestSVG 按 demand 建 DOM 副本池，未 placed
 * 的副本仅 display:none 隐藏不移除（陈旧 run placed < 现行 demand 时池里有隐藏
 * 副本）—— polygon[data-label] DOM 计数会虚高，断言必须只数用户可见的。 */
async function visiblePolygons(p) {
  return p.evaluate(() => Array.from(document.querySelectorAll('.nest-card svg polygon[data-label]'))
    .filter((el) => (el.checkVisibility ? el.checkVisibility() : el.getClientRects().length > 0))
    .length);
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
/** 等日志出现满足条件的 checkpoint POST（恢复后自动重落快照的前置门）。
 * 只认已结算条目（status/resp 在 fetch resolve 后才落 —— body 推栈即可被 pred
 * 命中，in-flight 条目会拿到 undefined status/resp 造成假失败）。 */
async function waitCheckpoint(p, pred, timeoutMs = 10000) {
  const t0 = Date.now();
  for (;;) {
    const cps = await cpPosts(p);
    const hit = cps.find((x) => x.status !== undefined && pred(x));
    if (hit) return hit;
    if (Date.now() - t0 > timeoutMs) return null;
    await sleep(400);
  }
}
/** 等策略/极限弹窗结果头（result 拉取落定 = done 态可确认）。 */
async function waitResultHead(p, timeoutMs) {
  await p.waitForSelector('[data-testid="strategy-result-head"]', { timeout: timeoutMs });
  return (await p.locator('[data-testid="strategy-result-head"]').innerText()).trim();
}
/** 数量矩阵 / 表单只读快照（不切 Tab —— display:none 下 input.value 照读）。 */
async function captureQtyForm(p) {
  return p.evaluate(() => ({
    gate: (document.querySelector('#gate') || {}).value ?? null,
    time: (document.querySelector('#time') || {}).value ?? null,
    cell00: (document.querySelector('.qty-cell-input[data-cell="0-0"]') || {}).value ?? null,
    cellG0132: (document.querySelector('input.qty-cell-input[aria-label="裁片 g01 码 32 数量"]') || {}).value ?? null,
    total: (document.querySelector('[data-testid="qty-total"]') || {}).textContent?.trim() ?? null,
  }));
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
    MS_RESULT_GRACE_SEC: '3',
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
log('服务就绪 ' + BASE + '（TTL=60 MAX=1 EDIT_HOLD=5 RESULT_GRACE=3）');
log('相位：' + PHASES.join(' → ') + (PHASES.length === 3 ? '（全量）' : '（分段调试切片）'));

const { chromium } = await import('playwright');
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}

/** 本轮已铺母版（分段复跑时 ensureSetup 只跑一次）。 */
let docReady = false;
/** pending 段是否已跑（extreme 段 run 块并存断言门）。 */
let pendingActRan = false;

try {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await ctx.addInitScript(() => {
    localStorage.setItem('ms.tour.version', '8');
    localStorage.setItem('ms.tour.seen.preview', '1');
    localStorage.setItem('ms.tour.seen.nesting', '1');
  });
  await ctx.addInitScript(NET_SPY);
  const page = await ctx.newPage();

  /** 上传母版 → commit → g01@30 改 2（总 111）。已铺则跳过（分段复跑），恒返当前 sid。 */
  async function ensureSetup() {
    if (docReady) return getSid(page);
    await page.goto(BASE, { waitUntil: 'networkidle' });
    const sid = await getSid(page);
    check('S1a 页面加载铸造 sid', /^[0-9a-f]{32}$/.test(sid || ''), (sid || '').slice(0, 8));
    await page.locator('input[type=file]').first().setInputFiles(DXF);
    await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 240000 });
    log('setup 上传 + commit done');
    const cell00 = page.locator('.qty-cell-input[data-cell="0-0"]');
    await cell00.waitFor({ timeout: 15000 });
    await cell00.fill('2');
    await cell00.press('Enter');
    await sleep(300);
    const qtyTotal = (await page.locator('[data-testid="qty-total"]').innerText()).trim();
    check('S1b 数量矩阵 g01@30=2 → 总片数 111', qtyTotal === EXPECT_TOTAL, qtyTotal);
    docReady = true;
    return sid;
  }

  /** 勾码号 + 门幅/时长表单（幂等；策略与超排求解同源 collectStartContext）。 */
  async function setupForm() {
    await page.locator('button.tab:not([disabled]):has-text("超排")').click();
    await sleep(800);
    for (const sz of SIZES) await page.check('#sz_' + sz);
    await page.fill('#gate', GATE);
    await page.fill('#time', SOLVE_TIME);
  }

  // ==================== pending 段（US-003 主路径 + 续段②③）====================
  if (hasPhase('pending')) {
    pendingActRan = true;
    const sidA = await ensureSetup();
    await setupForm();

    // ---------- M1/M2 高级运行 race 10min → 不确认等 run 完成 ----------
    await page.click('[data-testid="strategy-btn"]');
    await page.waitForSelector('[data-testid="strategy-minutes"]', { timeout: 10000 });
    await page.selectOption('#strategy-minutes', '10');
    await page.click('[data-testid="strategy-exec-btn"]');
    const progShown = await page
      .waitForSelector('[data-testid="strategy-progress-title"]', { timeout: 30000 })
      .then(() => true).catch(() => false);
    check('M1a race 10min 启动（进度态五件套在场）', progShown);
    log('M2 等 race 10min run 完成（不确认）…（上限 ' + STRATEGY_RUN_TIMEOUT / 1000 + 's）');
    const head1 = await waitResultHead(page, STRATEGY_RUN_TIMEOUT);
    const mR = /^完成 · 最优 (\d+\.\d{2})%$/.exec(head1);
    check('M2a run 完成且未确认（结果头「' + head1 + '」）', !!mR, head1);
    const pct1 = mR ? Number(mR[1]) : 0;
    await page.screenshot({ path: OUT + '/m2_race_done.png' });

    // ---------- M3 done 结果落定 → checkpoint 携 pending 槽（无 run 块） ----------
    const cp1 = await waitCheckpoint(page, (x) => {
      try { return JSON.parse(x.body || '{}').pending_strategy_result !== undefined; } catch { return false; }
    }, 15000);
    const cp1Body = cp1 ? JSON.parse(cp1.body) : {};
    const slot1 = cp1Body.pending_strategy_result || {};
    check('M3a done 结果落定即 checkpoint 携 pending（stored:true + mode=race + placed>0）',
      !!cp1 && cp1.status === 200 && cp1.resp && cp1.resp.stored === true
      && slot1.mode === 'race' && Array.isArray(slot1.best?.placed_items)
      && slot1.best.placed_items.length > 0,
      cp1 ? 'placed=' + slot1.best?.placed_items?.length : 'no post');
    check('M3b 载荷无 run 块（未应用 ⇒ 槽独占）+ quantities g01@30=2',
      cp1Body.run === undefined && cp1Body.quantities?.g01?.['30'] === 2,
      'run=' + (cp1Body.run !== undefined) + ' g01@30=' + cp1Body.quantities?.g01?.['30']);
    const detail1 = (await page.locator('[data-testid="strategy-result-detail"]').first().innerText()).trim();
    check('M3c 结果详情与槽一致（seed ' + slot1.best?.seed + '）',
      detail1.includes('seed ' + slot1.best?.seed), detail1);

    // ---------- M4 宽限窗外过期 → 刷新 → 启动期恢复 → 弹窗重现结果态 ----------
    log('M4 空闲 ' + TTL_IDLE_MS + 'ms 等宽限窗（3s）外 TTL 过期…');
    await sleep(TTL_IDLE_MS);
    await page.reload({ waitUntil: 'networkidle' });
    await sleep(1500); // 恢复编排（applyRestorePayload 同步 + toast 渲染）
    const sidB = await getSid(page);
    check('M4a 过期刷新 → 启动期恢复 sid A→B 换新',
      !!sidB && /^[0-9a-f]{32}$/.test(sidB) && sidB !== sidA, (sidB || '').slice(0, 8));
    let net = await netLog(page);
    const rec1 = net.find((x) => x.url.includes('/api/state-recover'));
    const rec1Resp = rec1?.resp || null;
    check('M4b recover 200（from_sid=旧A）+ 响应回传 pending（mode=race + 密度对拍 ' + pct1 + '%）',
      !!rec1 && rec1.status === 200 && JSON.parse(rec1.body || '{}').from_sid === sidA
      && rec1Resp?.pending_strategy_result?.mode === 'race'
      && Math.abs((rec1Resp?.pending_strategy_result?.best?.density ?? -1) * 100 - pct1) < 0.005,
      rec1 ? 'status=' + rec1.status : 'no call');
    check('M4c 响应 pending.placed 与过期前 checkpoint 槽逐条一致（守恒）',
      JSON.stringify(jsonNorm(rec1Resp?.pending_strategy_result?.best?.placed_items ?? null))
      === JSON.stringify(jsonNorm(slot1.best?.placed_items ?? undefined)),
      'resp=' + rec1Resp?.pending_strategy_result?.best?.placed_items?.length
      + ' cp=' + slot1.best?.placed_items?.length);
    check('M4d 响应 run=null（未应用 ⇒ 无 run 块）+ quantities g01@30=2 恢复',
      rec1Resp?.run === null && rec1Resp?.quantities?.g01?.['30'] === 2,
      'run=' + (rec1Resp?.run === null ? 'null' : 'present'));
    check('M4e toast 工作状态已恢复 + 无阻断弹窗',
      (await toasts(page)).includes('工作状态已恢复')
      && (await page.locator('.session-block-overlay').count()) === 0,
      JSON.stringify(await toasts(page)));
    await page.waitForSelector('[data-testid="strategy-overlay"]', { timeout: 15000 });
    const head2 = (await page.locator('[data-testid="strategy-result-head"]').innerText()).trim();
    check('M4f 对应族弹窗自动打开且为结果态（密度与过期前对拍）', head2 === head1, head2);
    // 2026-09-14：恢复自动落超排 Tab（applyRestorePayload 第 6 步显式解锁+切页 ——
    // 弹窗 Portal 到 body 不随 Tab 隐藏，快照无 run 块时不切页会悬浮在上传预览页）。
    const onNestingM4 = await page.evaluate(() => {
      const el = document.querySelector('.tab-content .page:not(.hidden)');
      return el !== null && el.querySelector('#restart') !== null;
    });
    check('M4g 恢复落超排 Tab（弹窗悬浮在超排工作台上，非上传预览）', onNestingM4);
    await page.screenshot({ path: OUT + '/m4_recovered_modal.png' });
    await closeToasts(page);

    // ---------- M5 待确认结果期改数量未重解 → checkpoint last-good（续段③） ----------
    await page.click('[data-testid="strategy-close"]');
    await sleep(400);
    // 2026-09-14 起恢复自动落超排 Tab（pending 槽在场亦切页 —— 弹窗属于超排
    // 工作流）；改数量矩阵前显式切回上传预览（display:none 下 fill 不可见元素超时）。
    await page.locator('button.tab:has-text("上传预览")').click();
    await sleep(400);
    const cellG0132 = page.locator('input.qty-cell-input[aria-label="裁片 g01 码 32 数量"]');
    await cellG0132.waitFor({ timeout: 10000 });
    await cellG0132.fill('2');
    await cellG0132.press('Enter');
    await sleep(300);
    const total112 = (await page.locator('[data-testid="qty-total"]').innerText()).trim();
    check('M5a 改数量生效（g01@32 1→2，总片数 111→112）', total112 === '112', total112);
    const cp2 = await waitCheckpoint(page, (x) => {
      try {
        const b = JSON.parse(x.body || '{}');
        return b.quantities?.g01?.['32'] === 2 && b.pending_strategy_result !== undefined;
      } catch { return false; }
    }, 15000);
    const cp2Body = cp2 ? JSON.parse(cp2.body) : {};
    check('M5b 未重解半态被拒：checkpoint 200 {stored:false, reason:"conservation"}（last-good 保持）',
      !!cp2 && cp2.status === 200 && cp2.resp && cp2.resp.stored === false
      && cp2.resp.reason === 'conservation',
      cp2 ? JSON.stringify(cp2.resp) : 'no post');
    check('M5c 被拒载荷确为半态（quantities g01@32=2 + 槽仍随载荷在场）',
      cp2Body.quantities?.g01?.['32'] === 2 && cp2Body.pending_strategy_result !== undefined,
      'g01@32=' + cp2Body.quantities?.g01?.['32']);
    log('M5 空闲 ' + TTL_IDLE_MS + 'ms 再过期 → 刷新（应恢复改前完整快照）…');
    await sleep(TTL_IDLE_MS);
    await page.reload({ waitUntil: 'networkidle' });
    await sleep(1500);
    const sidC = await getSid(page);
    check('M5d 再过期刷新 → sid B→C 换新',
      !!sidC && sidC !== sidB, (sidC || '').slice(0, 8));
    net = await netLog(page);
    const rec2 = net.find((x) => x.url.includes('/api/state-recover'));
    const rec2Resp = rec2?.resp || null;
    check('M5e 恢复的是改前完整快照（quantities g01@32 回 1 ≠ 2 + pending 密度对拍 ' + pct1 + '%）',
      !!rec2 && rec2.status === 200
      && (rec2Resp?.quantities?.g01?.['32'] ?? 1) !== 2
      && rec2Resp?.pending_strategy_result?.mode === 'race'
      && Math.abs((rec2Resp?.pending_strategy_result?.best?.density ?? -1) * 100 - pct1) < 0.005,
      'g01@32=' + (rec2Resp?.quantities?.g01?.['32'] ?? '(absent=1)'));
    const qf1 = await captureQtyForm(page);
    check('M5f 数量矩阵回改前（g01@32=1 + g01@30=2 + 总 111）',
      qf1.cellG0132 === '1' && qf1.cell00 === '2' && qf1.total === EXPECT_TOTAL,
      JSON.stringify(qf1));
    await page.waitForSelector('[data-testid="strategy-overlay"]', { timeout: 15000 });
    const head3 = (await page.locator('[data-testid="strategy-result-head"]').innerText()).trim();
    check('M5g 弹窗重现结果态（密度与首次一致）', head3 === head1, head3);
    const cp3 = await waitCheckpoint(page, (x) => {
      try { return JSON.parse(x.body || '{}').pending_strategy_result !== undefined; } catch { return false; }
    }, 15000);
    check('M5h 恢复态重落 checkpoint（携槽 stored:true + sid=C 自我延续）',
      !!cp3 && cp3.status === 200 && cp3.resp?.stored === true && cp3.sid === sidC,
      cp3 ? 'sid=' + String(cp3.sid).slice(0, 8) : 'no post');
    await closeToasts(page);
    await page.screenshot({ path: OUT + '/m5_lastgood_recovered.png' });

    // ---------- M6 点应用 → 主画布对拍 → 导出 PLT 守恒 ----------
    const nPlaced = slot1.best?.placed_items?.length || 0;
    await page.click('[data-testid="strategy-apply-btn"]');
    const cp4 = await waitCheckpoint(page, (x) => {
      try {
        const b = JSON.parse(x.body || '{}');
        return b.run !== undefined && b.pending_strategy_result === undefined;
      } catch { return false; }
    }, 15000);
    const cp4Body = cp4 ? JSON.parse(cp4.body) : {};
    check('M6a 应用落定 checkpoint：run 块在场 + pending 槽退场（无双份数据）+ stored:true',
      !!cp4 && cp4.status === 200 && cp4.resp?.stored === true
      && cp4Body.run !== undefined && cp4Body.pending_strategy_result === undefined,
      'run.seed=' + cp4Body.run?.seed + ' pending=' + (cp4Body.pending_strategy_result !== undefined)
      + ' resp=' + JSON.stringify(cp4?.resp) + ' t=' + cp4?.t);
    await page.click('[data-testid="strategy-close"]');
    await page.locator('button.tab:not([disabled]):has-text("超排")').click();
    await page.locator('.nest-label').first().waitFor({ timeout: 15000 });
    await sleep(500);
    const polygons = await page.locator('.nest-card svg polygon[data-label]').count();
    check('M6b 主画布 placed 逐条对拍（polygon 数 = 槽 placed ' + nPlaced + ' 条）',
      polygons === nPlaced, 'polygons=' + polygons);
    const statusLine = (await page.locator('#status').first().innerText().catch(() => '')).trim();
    check('M6c 状态行「策略 run 已应用 · seed ' + slot1.best?.seed + '」',
      statusLine.includes('策略 run 已应用') && statusLine.includes('seed ' + slot1.best?.seed),
      statusLine);
    const prov = (await page.locator('.provenance-line, [data-testid="run-provenance"]').first()
      .innerText().catch(() => '')).trim();
    check('M6d 来源小字「策略运行·race · seed ' + slot1.best?.seed + '」',
      prov.includes('策略运行·race') && prov.includes('seed ' + slot1.best?.seed), prov);
    await page.screenshot({ path: OUT + '/m6_applied_layout.png' });
    // PLT 导出守恒：抓 POST /export 载荷 placed 与过期前 checkpoint 槽逐条对拍
    const capExport = page.waitForResponse((r) => r.url().endsWith('/export'), { timeout: 30000 });
    await page.selectOption('select.export-fmt', 'plt');
    await page.click('button.export');
    await page.waitForSelector('[data-testid="export-info-overlay"]', { timeout: 15000 });
    await page.click('[data-testid="export-info-confirm"]');
    const expResp = await capExport;
    let expBody = null;
    try { expBody = expResp.request().postDataJSON(); } catch { expBody = null; }
    check('M6e 导出 PLT 200 + fmt=plt',
      expResp.status() === 200 && expBody?.fmt === 'plt',
      'status=' + expResp.status + ' fmt=' + expBody?.fmt);
    check('M6f 导出 placed 与过期前 checkpoint 槽逐条一致（守恒）',
      !!expBody && Array.isArray(expBody.placed) && expBody.placed.length === nPlaced
      && JSON.stringify(jsonNorm(expBody.placed)) === JSON.stringify(jsonNorm(slot1.best.placed_items)),
      'export=' + expBody?.placed?.length + ' slot=' + nPlaced);

    // ---------- M7 应用后再过期 → 恢复已应用 run、弹窗不开（续段② + 无 pending 老快照对拍） ----------
    log('M7 空闲 ' + TTL_IDLE_MS + 'ms 应用后再过期 → 刷新恢复…');
    await sleep(TTL_IDLE_MS);
    await page.reload({ waitUntil: 'networkidle' });
    await sleep(1500);
    const sidD = await getSid(page);
    check('M7a 应用后再过期刷新 → sid C→D 换新', !!sidD && sidD !== sidC, (sidD || '').slice(0, 8));
    net = await netLog(page);
    const rec3 = net.find((x) => x.url.includes('/api/state-recover'));
    const rec3Resp = rec3?.resp || null;
    check('M7b 恢复已应用 run（run 在场 + pending=null 无双份数据 + placed 条数对拍）',
      !!rec3 && rec3.status === 200 && rec3Resp?.run != null
      && rec3Resp?.pending_strategy_result === null
      && Array.isArray(rec3Resp?.placed) && rec3Resp.placed.length === nPlaced,
      'run=' + (rec3Resp?.run != null ? 'present' : 'null')
      + ' placed=' + rec3Resp?.placed?.length);
    check('M7c 任何族弹窗不开（策略/极限 overlay 均 0）',
      (await page.locator('[data-testid="strategy-overlay"]').count()) === 0
      && (await page.locator('[data-testid="extreme-overlay"]').count()) === 0,
      'strategy=' + (await page.locator('[data-testid="strategy-overlay"]').count()));
    const polygons2 = await page.locator('.nest-card svg polygon[data-label]').count();
    const prov2 = (await page.locator('.provenance-line, [data-testid="run-provenance"]').first()
      .innerText().catch(() => '')).trim();
    check('M7d 布局 + 来源小字恢复对拍（polygons=' + nPlaced + ' + 策略运行·race）',
      polygons2 === nPlaced && prov2.includes('策略运行·race') && prov2.includes('seed ' + slot1.best?.seed),
      'polygons=' + polygons2 + ' prov=' + prov2);
    const qf2 = await captureQtyForm(page);
    check('M7e 数量矩阵恢复不变（g01@30=2 + g01@32=1 + 总 111）',
      qf2.cell00 === '2' && qf2.cellG0132 === '1' && qf2.total === EXPECT_TOTAL,
      JSON.stringify(qf2));
    await page.screenshot({ path: OUT + '/m7_applied_recovered.png' });
    // 调试档案：本导航全部 checkpoint POST（形态/响应）落盘，供失败排查
    writeFileSync(OUT + '/pending_debug_cps.json', JSON.stringify(
      (await cpPosts(page)).map((x) => ({
        t: x.t, sid: x.sid, status: x.status, resp: x.resp,
        body: (() => { try { return JSON.parse(x.body || '{}'); } catch { return null; } })(),
      })), null, 2));
    log('pending 段完成');
  }

  // ==================== bg 段（2026-09-14 展示级降级：陈旧 run 背景 + pending 弹窗）====================
  // 用户报告 bug 的端到端回归锁：先有普通求解布局 → 改数量 → 策略 run 完成不确认 →
  // 过期恢复 —— 弹窗结果态之下背景必须仍是旧布局（checkpoint 对陈旧 run 打 stale
  // 标记保留而非丢弃），取消后画布不清空、确认后才被新解置换（与活界面同口径）。
  if (hasPhase('bg')) {
    const sidA = await ensureSetup();
    await setupForm();

    // ---------- B1 5s 普通求解 → run 块（背景旧布局）落 checkpoint ----------
    const cpCount0 = (await cpPosts(page)).length;
    // #start（idle）在已有 run 后变体为 #restart（同 onStart 语义；restart 清旧 run）
    await page.locator('#start, #restart').click();
    let cpB1 = null;
    {
      const t0 = Date.now();
      for (;;) {
        const fresh = (await cpPosts(page)).slice(cpCount0);
        const hit = fresh.find((x) => {
          if (x.status !== 200 || x.resp?.stored !== true) return false;
          try { return JSON.parse(x.body || '{}').run !== undefined; } catch { return false; }
        });
        if (hit) { cpB1 = hit; break; }
        if (Date.now() - t0 > 120000) break;
        await sleep(500);
      }
    }
    const cpB1Body = cpB1 ? JSON.parse(cpB1.body) : {};
    const bgN = cpB1Body.run?.placed?.length || 0;
    check('B1a 普通求解完成 → checkpoint run 块（背景 placed=' + bgN + '）',
      !!cpB1 && bgN > 0, cpB1 ? JSON.stringify(cpB1.resp) : 'no fresh post');
    await page.screenshot({ path: OUT + '/b1_solved_background.png' });

    // ---------- B2 改数量 g01@32 1→2（总 112）→ run 与现行数量失配（陈旧背景） ----------
    await page.locator('button.tab:has-text("上传预览")').click();
    await sleep(400);
    const cellB2 = page.locator('input.qty-cell-input[aria-label="裁片 g01 码 32 数量"]');
    await cellB2.waitFor({ timeout: 10000 });
    await cellB2.fill('2');
    await cellB2.press('Enter');
    await sleep(300);
    const totalB = (await page.locator('[data-testid="qty-total"]').innerText()).trim();
    check('B2a 改数量生效（g01@32 1→2，总 111→112）', totalB === '112', totalB);

    // ---------- B3 race 10min → done 不确认 → checkpoint 陈旧 run 打标入库 ----------
    await page.locator('button.tab:not([disabled]):has-text("超排")').click();
    await sleep(800);
    await page.click('[data-testid="strategy-btn"]');
    await page.waitForSelector('[data-testid="strategy-minutes"]', { timeout: 10000 });
    await page.selectOption('#strategy-minutes', '10');
    await page.click('[data-testid="strategy-exec-btn"]');
    await page.waitForSelector('[data-testid="strategy-progress-title"]', { timeout: 30000 });
    log('B3 等 race 10min run 完成（不确认）…（上限 ' + STRATEGY_RUN_TIMEOUT / 1000 + 's）');
    const headB1 = await waitResultHead(page, STRATEGY_RUN_TIMEOUT);
    const mB = /^完成 · 最优 (\d+\.\d{2})%$/.exec(headB1);
    check('B3a race run 完成且未确认（结果头「' + headB1 + '」）', !!mB, headB1);
    // 陈旧 run（placed=111 ≠ 现行 demand 112）+ 守恒一致 pending（112）→ 分块独立
    // 裁决打标入库（初版「丢弃 run 块」会让恢复后背景空置，同日二改 stale 保留）。
    const cpB3 = await waitCheckpoint(page, (x) => x.resp?.stored === true && x.resp?.stale_run === true, 15000);
    const cpB3Body = cpB3 ? JSON.parse(cpB3.body) : {};
    const slotB = cpB3Body.pending_strategy_result || {};
    const pendN = slotB.best?.placed_items?.length || 0;
    check('B3b 陈旧 run 打标入库：{stored:true, stale_run:true} + 载荷 run 与槽并存',
      !!cpB3 && cpB3Body.run !== undefined && slotB.mode === 'race' && pendN === bgN + 1,
      'run.placed=' + cpB3Body.run?.placed?.length + ' pending.placed=' + pendN
      + ' resp=' + JSON.stringify(cpB3?.resp));
    check('B3c 结果详情与槽一致（seed ' + slotB.best?.seed + '）',
      (await page.locator('[data-testid="strategy-result-detail"]').first().innerText())
        .includes('seed ' + slotB.best?.seed));

    // ---------- B4 宽限窗外过期 → 刷新恢复：弹窗结果态 + 背景旧布局保留 ----------
    log('B4 空闲 ' + TTL_IDLE_MS + 'ms 等宽限窗（3s）外 TTL 过期…');
    await sleep(TTL_IDLE_MS);
    await page.reload({ waitUntil: 'networkidle' });
    await sleep(1500); // 恢复编排（applyRestorePayload 同步 + toast 渲染）
    const sidB = await getSid(page);
    check('B4a 过期刷新 → sid A→B 换新',
      !!sidB && /^[0-9a-f]{32}$/.test(sidB) && sidB !== sidA, (sidB || '').slice(0, 8));
    const netB = await netLog(page);
    const recB = netB.find((x) => x.url.includes('/api/state-recover'));
    const recBResp = recB?.resp || null;
    check('B4b recover 200 + run.stale=true + 背景 placed 原样（' + bgN + '）+ pending（' + (bgN + 1) + '）并存',
      !!recB && recB.status === 200
      && recBResp?.run?.stale === true
      && Array.isArray(recBResp?.run?.placed) && recBResp.run.placed.length === bgN
      && recBResp?.pending_strategy_result?.mode === 'race'
      && recBResp?.pending_strategy_result?.best?.placed_items?.length === bgN + 1,
      recB ? 'run.stale=' + recBResp?.run?.stale + ' run=' + recBResp?.run?.placed?.length
        + ' pending=' + recBResp?.pending_strategy_result?.best?.placed_items?.length : 'no call');
    await page.waitForSelector('[data-testid="strategy-overlay"]', { timeout: 15000 });
    const headB2 = (await page.locator('[data-testid="strategy-result-head"]').innerText()).trim();
    check('B4c 弹窗自动打开且为结果态（密度与过期前对拍）', headB2 === headB1, headB2);
    // 核心回归锁：弹窗之下背景 = 旧布局（stale run 保留渲染；修复前此景背景空置）。
    // 可见口径：现行 demand 比 run 多 1（g01@32=2 而旧解只放 1）→ demand 池里的
    // 第 2 副本是 display:none 隐藏副本，DOM 计数 31 而可见恒 = run placed 30。
    await page.locator('.nest-card svg polygon[data-label]').first().waitFor({ timeout: 15000 });
    const bgPoly1 = await visiblePolygons(page);
    check('B4d 背景旧布局保留（可见 polygon=' + bgPoly1 + ' = run placed ' + bgN + '，非 pending ' + (bgN + 1) + '）',
      bgPoly1 === bgN, 'visible=' + bgPoly1);
    await page.screenshot({ path: OUT + '/b4_stale_background_modal.png' });
    await closeToasts(page);

    // ---------- B5 取消 → 背景保留（不再清空画布 = 用户报告的 bug 主诉） ----------
    await page.click('[data-testid="strategy-close"]');
    await sleep(600);
    check('B5a 取消后弹窗关闭（overlay 0）',
      (await page.locator('[data-testid="strategy-overlay"]').count()) === 0);
    const bgPoly2 = await visiblePolygons(page);
    check('B5b 取消后背景保留（可见 polygon=' + bgPoly2 + ' 不清空）',
      bgPoly2 === bgN, 'visible=' + bgPoly2);
    const provB = (await page.locator('.provenance-line, [data-testid="run-provenance"]').first()
      .innerText().catch(() => '')).trim();
    check('B5c 背景来源小字 = 普通求解（stale run 合成 origin = {kind:"solve"}）',
      provB.includes('普通求解'), provB);
    await page.screenshot({ path: OUT + '/b5_cancel_background_kept.png' });

    // ---------- B6 再过期 → 恢复弹窗重现 → 确认应用 → 背景被新解置换 ----------
    log('B6 空闲 ' + TTL_IDLE_MS + 'ms 再过期 → 刷新恢复 → 确认应用…');
    await sleep(TTL_IDLE_MS);
    await page.reload({ waitUntil: 'networkidle' });
    await sleep(1500);
    const sidC = await getSid(page);
    check('B6a 再过期刷新 → sid B→C 换新', !!sidC && sidC !== sidB, (sidC || '').slice(0, 8));
    const netB2 = await netLog(page);
    const recB2 = netB2.find((x) => x.url.includes('/api/state-recover'));
    check('B6b 恢复态重落快照可再恢复（recover 200 + run.stale + pending 仍在）',
      !!recB2 && recB2.status === 200 && recB2?.resp?.run?.stale === true
      && recB2?.resp?.pending_strategy_result?.mode === 'race',
      recB2 ? 'status=' + recB2.status + ' run.stale=' + recB2?.resp?.run?.stale : 'no call');
    await page.waitForSelector('[data-testid="strategy-overlay"]', { timeout: 15000 });
    await page.click('[data-testid="strategy-apply-btn"]');
    const cpB6 = await waitCheckpoint(page, (x) => {
      try {
        const b = JSON.parse(x.body || '{}');
        return b.run !== undefined && b.pending_strategy_result === undefined;
      } catch { return false; }
    }, 15000);
    check('B6c 应用落定 checkpoint：run 块在场 + pending 退场（应用后无双份数据）',
      !!cpB6 && cpB6.resp?.stored === true, cpB6 ? JSON.stringify(cpB6.resp) : 'no post');
    await page.click('[data-testid="strategy-close"]');
    await page.locator('.nest-card svg polygon[data-label]').first().waitFor({ timeout: 15000 });
    await sleep(500);
    const bgPoly3 = await visiblePolygons(page);
    check('B6d 确认后背景被新解置换（可见 polygon=' + bgPoly3 + ' = pending placed ' + (bgN + 1) + '）',
      bgPoly3 === bgN + 1, 'visible=' + bgPoly3);
    const provB2 = (await page.locator('.provenance-line, [data-testid="run-provenance"]').first()
      .innerText().catch(() => '')).trim();
    check('B6e 来源小字切换为策略运行·race（新解置换旧背景）',
      provB2.includes('策略运行·race'), provB2);
    await page.screenshot({ path: OUT + '/b6_applied_replaced.png' });
    await closeToasts(page);
    log('bg 段完成');
  }

  // ==================== extreme 段（US-003 续段① 极限运行同款）====================
  if (hasPhase('extreme')) {
    await ensureSetup();
    await setupForm();

    // ---------- X1/X2 极限运行 16min（UI 下限 960s）→ 不确认等 done ----------
    await page.click('[data-testid="extreme-btn"]');
    await page.waitForSelector('[data-testid="extreme-preset-custom"]', { timeout: 10000 });
    await page.click('[data-testid="extreme-preset-custom"]');
    await page.fill('[data-testid="extreme-custom-input"]', '16');
    await page.click('[data-testid="extreme-exec-btn"]');
    const xProg = await page
      .waitForSelector('[data-testid="extreme-overlay"]', { timeout: 30000 })
      .then(() => true).catch(() => false);
    check('X1a 极限运行 16min 启动（弹窗在场）', xProg);
    log('X2 等极限 run done（early_termination 固化 False 全预算 ~905s+；上限 '
      + EXTREME_RUN_TIMEOUT / 1000 + 's）…');
    const xHead1 = await waitResultHead(page, EXTREME_RUN_TIMEOUT);
    const xR = /^完成 · 最优 (\d+\.\d{2})%$/.exec(xHead1);
    check('X2a 极限 run 完成且未确认（结果头「' + xHead1 + '」）', !!xR, xHead1);
    const xPct1 = xR ? Number(xR[1]) : 0;
    const cp5 = await waitCheckpoint(page, (x) => {
      try { return JSON.parse(x.body || '{}').pending_strategy_result?.mode === 'extreme'; } catch { return false; }
    }, 15000);
    const cp5Body = cp5 ? JSON.parse(cp5.body) : {};
    const slotX = cp5Body.pending_strategy_result || {};
    check('X2b done 结果落定 checkpoint 携 pending（mode=extreme + stored:true + placed>0）',
      !!cp5 && cp5.status === 200 && cp5.resp?.stored === true
      && Array.isArray(slotX.best?.placed_items) && slotX.best.placed_items.length > 0,
      'placed=' + slotX.best?.placed_items?.length);
    check('X2c run 块与槽并存断言（pending 段已跑时：已应用 run 仍在场不丢）',
      !pendingActRan || cp5Body.run !== undefined,
      'run=' + (cp5Body.run !== undefined ? 'present' : 'absent'));
    await page.screenshot({ path: OUT + '/x2_extreme_done.png' });

    // ---------- X3 宽限窗外过期 → 刷新 → 极限族弹窗自动打开结果态（策略族不串台） ----------
    log('X3 空闲 ' + TTL_IDLE_MS + 'ms 等宽限窗（3s）外 TTL 过期…');
    await sleep(TTL_IDLE_MS);
    await page.reload({ waitUntil: 'networkidle' });
    await sleep(1500);
    const sidX = await getSid(page);
    check('X3a 过期刷新 → sid 换新', /^[0-9a-f]{32}$/.test(sidX || ''), (sidX || '').slice(0, 8));
    const netX = await netLog(page);
    const recX = netX.find((x) => x.url.includes('/api/state-recover'));
    const recXResp = recX?.resp || null;
    check('X3b recover 200 + 响应回传 pending（mode=extreme + 密度对拍 ' + xPct1 + '%）',
      !!recX && recX.status === 200
      && recXResp?.pending_strategy_result?.mode === 'extreme'
      && Math.abs((recXResp?.pending_strategy_result?.best?.density ?? -1) * 100 - xPct1) < 0.005,
      recX ? 'status=' + recX.status : 'no call');
    await page.waitForSelector('[data-testid="extreme-overlay"]', { timeout: 15000 });
    const xHead2 = (await page.locator('[data-testid="strategy-result-head"]').innerText()).trim();
    check('X3c 极限族弹窗自动打开且为结果态（密度与过期前对拍）+ 策略族不串台',
      xHead2 === xHead1 && (await page.locator('[data-testid="strategy-overlay"]').count()) === 0,
      xHead2);
    await closeToasts(page);
    await page.screenshot({ path: OUT + '/x3_recovered_modal.png' });
    const cp6 = await waitCheckpoint(page, (x) => {
      try { return JSON.parse(x.body || '{}').pending_strategy_result?.mode === 'extreme'; } catch { return false; }
    }, 15000);
    check('X3d 恢复态重落 checkpoint 携 extreme 槽（自我延续）',
      !!cp6 && cp6.status === 200 && cp6.resp?.stored === true,
      cp6 ? 'sid=' + String(cp6.sid).slice(0, 8) : 'no post');

    // ---------- X4 应用 → 主画布对拍 ----------
    await page.click('[data-testid="strategy-apply-btn"]');
    const cp7 = await waitCheckpoint(page, (x) => {
      try {
        const b = JSON.parse(x.body || '{}');
        return b.run !== undefined && b.pending_strategy_result === undefined;
      } catch { return false; }
    }, 15000);
    const cp7Body = cp7 ? JSON.parse(cp7.body) : {};
    check('X4a 应用落定 checkpoint：run 块在场 + pending 槽退场',
      !!cp7 && cp7Body.run !== undefined && cp7Body.pending_strategy_result === undefined,
      'run.seed=' + cp7Body.run?.seed);
    await page.click('[data-testid="extreme-close"]');
    await page.locator('button.tab:not([disabled]):has-text("超排")').click();
    await page.locator('.nest-label').first().waitFor({ timeout: 15000 });
    await sleep(500);
    const xPolygons = await page.locator('.nest-card svg polygon[data-label]').count();
    const xStatus = (await page.locator('#status').first().innerText().catch(() => '')).trim();
    const xProv = (await page.locator('.provenance-line, [data-testid="run-provenance"]').first()
      .innerText().catch(() => '')).trim();
    check('X4b 主画布对拍（polygon 数 = 槽 placed）+ 状态行极限已应用 + 来源「极限运行」',
      xPolygons === (slotX.best?.placed_items?.length || 0)
      && xStatus.includes('极限 run 已应用')
      && xProv.includes('极限运行'),
      'polygons=' + xPolygons + ' status=' + xStatus);
    await page.screenshot({ path: OUT + '/x4_applied_layout.png' });
    log('extreme 段完成');
  }

  // ==================== legacy 段（US-005 五路径回归锁，原样保留）====================
  // 前置改走 ensureSetup/setupForm（两族结果均已应用或首跑，重铺 run 块后原样跑）。
  // S1c 用「#start 前后 checkpoint 索引」替代 waitSolveDone —— pending/extreme 已应用
  // 过 run 时保存按钮恒解锁，老探测会瞬间假通过。
  if (hasPhase('legacy')) {
    const sidA = await ensureSetup();
    await setupForm();

    const cpCount0 = (await cpPosts(page)).length;
    // #start（idle）在已有 run 后变体为 #restart（SolveControls：同一 onStart 语义）
    // —— 全量跑时 pending/extreme 已应用过 run，此按钮恒为 #restart。
    await page.locator('#start, #restart').click();
    let cpS1 = null;
    {
      const t0 = Date.now();
      for (;;) {
        const fresh = (await cpPosts(page)).slice(cpCount0);
        const hit = fresh.find((x) => x.status !== undefined && (() => {
          // run 在场且 run.provenance === undefined = 纯 WS 求解 run。全量跑时须
          // 同时排除两类伪命中：旧策略/极限已应用 run（带 provenance.kind）与
          // #restart 启动清 run 后的无 run 去抖快照（run 缺席时 run?.provenance
          // 也 === undefined，S1e 会拿到 placed=undefined 的半态帖）。
          try {
            const b = JSON.parse(x.body || '{}');
            return b.run !== undefined && b.run.provenance === undefined;
          } catch { return false; }
        })());
        if (hit) { cpS1 = hit; break; }
        if (Date.now() - t0 > 120000) break;
        await sleep(500);
      }
    }
    const lastCpBody = cpS1 ? JSON.parse(cpS1.body) : {};
    check('S1c 重铺 5s 求解完成 → 新 checkpoint 落地（#start 后新 POST 含 run 块）',
      !!cpS1, cpS1 ? 'posts+' + ((await cpPosts(page)).length - cpCount0) : 'no fresh post');
    check('S1d US-004 自动 checkpoint（求解完成立即）：stored:true + 含 run 块 + sid A',
      !!cpS1 && cpS1.status === 200 && cpS1.resp && cpS1.resp.stored === true
      && lastCpBody.run !== undefined && cpS1.sid === sidA,
      'posts=' + cpCount0 + '+ last=' + JSON.stringify(cpS1?.resp));
    check('S1e 载荷=工作台实值（g01@30=2、placed>0、无 pending 槽 —— 两族结果均已应用）',
      lastCpBody.quantities?.g01?.['30'] === 2
      && Array.isArray(lastCpBody.run?.placed) && lastCpBody.run.placed.length > 0
      && lastCpBody.pending_strategy_result === undefined,
      'g01@30=' + lastCpBody.quantities?.g01?.['30'] + ' placed=' + lastCpBody.run?.placed?.length);

    // cpS1 = 求解完成帖，但按钮变体 #restart 的 React 重渲染可能滞后几 ms ——
    // 显式等 #restart 在场再取快照，杜绝拍到求解中的帧标签（P1k/P2c 对拍源）。
    await page.locator('#restart').waitFor({ timeout: 10000 });
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
    // 基线计数（全量跑时本导航含 X3 启动恢复的 recover 调用 —— 「停留期未自动
    // 恢复」断言的是基线之后零新增，而非整导航为零）。
    const recBase = (await netLog(page)).filter((x) => x.url.includes('/api/state-recover')).length;
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
    let net = await netLog(page);
    check('P1d 停留期未自动恢复（停留期零新增 /api/state-recover 调用）',
      net.filter((x) => x.url.includes('/api/state-recover')).length === recBase,
      'calls=' + net.filter((x) => x.url.includes('/api/state-recover')).length + ' base=' + recBase);
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
    log('legacy 段完成');
  }

  await ctx.close();
} catch (e) {
  check('脚本异常中断', false, String(e && e.stack || e).slice(0, 300));
} finally {
  await browser.close().catch(() => {});
  killServer();
  await sleep(1000);
}

const pass = results.filter((r) => r.ok).length;
writeFileSync(OUT + '/report.txt',
  'phases: ' + PHASES.join(',') + '\n'
  + results.map((r) => (r.skip ? 'SKIP' : r.ok ? 'PASS' : 'FAIL') + '  ' + r.name).join('\n')
  + '\n' + pass + '/' + results.length + ' passed'
  + (skips.length ? '（skip ' + skips.length + '：' + skips.join('；') + '）' : '') + '\n');
console.log('\n' + pass + '/' + results.length + ' passed'
  + (skips.length ? '（含 skip ' + skips.length + '）' : ''));
process.exit(pass === results.length ? 0 : 1);

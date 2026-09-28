// key 授权 US-010 全链路冒烟（prd-key-authorization-system 收官）—— 起真 keyserver
// + ms-web 双服务自举，从生产入口（:8010 静态 bundle）走完用户主链路：
//
//   T0 双 token 生产姿态（MS_KEY_ADMIN_TOKEN + MS_KEY_CLIENT_TOKEN 均设、无 DEV
//      逃生）—— 管理/消费端无 token 401、带 token 过鉴权（404 key 不存在）
//   A  生产 bundle 含新代码：:8010 首页引用的 /static/assets/index-*.js 含
//      /api/key/precheck 与 key-info-* 锚点；且不含 keyserver 端点/URL env 锚
//      （MS_KEY_SERVER_URL、/api/key/bind、/api/key/validate —— keyserver 永不
//      出现在浏览器，全链路无跨域，FR-11）
//   B  样例载入免闸（三入口）：未绑任何 key 时样例应用 → 普通/高级/极限运行
//      全部放行（precheck 回包 {ok:true, reason:'sample'} 对拍），且不扣次
//   C  真实母版（样例字节改名上传 → basename 脱离白名单）+ 未绑 key → 三入口
//      全拦：普通 StatusLine+Toast+不进 WS；高级/极限弹窗红字且 /start 零发出
//   D  假 key 保存 → 中文红字「key 不存在」（keyserver 4xx 透传，不落盘）
//   E  真 key 绑定（时长型）+ 批量合并两 source → 明细/共转移/截止更新；
//      keyserver 侧 source 置「已合并」保留不物理删除
//   F  换绑次数型 key（真 key 绑定）→ 总数/已用/剩余 + 正在使用徽标 + 镜像双写
//   G  绑定有效 key 后普通运行放行（真实母版进 WS running → 停止）
//   H  keyserver 侧断言：count key 扣次恰 +1（used 1/30）+ 使用统计三指标
//      （total=1 峰=1 均=1.0 = key_daily_usage 当日 +1）；时长 key 统计零记录
//
// 前置：materialSorting-web/static/ 为 npm run build 产物（脚本自检，缺则退出 2）；
//   :8010 与 :8130 空闲；.venv 在 repo 根（keyserver 与 materialsorting 均已安装）。
// 命令：node materialSorting-web/scripts/smoke_key_gate.mjs
// 产物：out/smoke_key_gate/{report.txt, report.json, 0*.png, ms_out/, keys.db}；
//   退出码 0 = 全部检查 PASS。模板 = smoke_sample_picker.mjs（Edge 通道 +
//   ms.tour.* addInitScript 防 tour-overlay 拦截）+ smoke_session_recovery.mjs
//   （自举起服 / taskkill 树杀）+ us007_key_gate_verify.mjs（三入口断言 / fetch
//   计数）。MS_OUT_DIR 临时目录隔离 web 事实源与 key_state.json（env 值一律
//   正斜杠，us007 实勘）；keyserver DB 同目录，每次运行重铸（断言确定性）。
import { writeFileSync, mkdirSync, rmSync, copyFileSync, existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve, sep } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const ROOT_F = ROOT.split(sep).join('/');        // env 值一律正斜杠（us007 实勘）
const OUT = ROOT_F + '/out/smoke_key_gate';
const MS_OUT = OUT + '/ms_out';                  // ms-web 临时 OUT_DIR（隔离事实源/license）
const KEY_DB = OUT + '/keys.db';                 // keyserver 临时账本（每次重铸）
const PY = ROOT + '/.venv/Scripts/python.exe';
const STATIC_INDEX = ROOT + '/materialSorting-web/static/index.html';
const BASELINE_INTERMEDIATE =
  ROOT_F + '/materialSorting-server/out/sparrow_baseline/pieces_intermediate.json';

const MS_PORT = 8010;    // AC：用户入口 = 生产构建 :8010（dev:5173 通过不算数）
const KEY_PORT = 8130;   // 冒烟专用（避开 keyserver 缺省 8110 与常驻服务）
const MS = 'http://127.0.0.1:' + MS_PORT;
const KEY = 'http://127.0.0.1:' + KEY_PORT;
const ADMIN_TOKEN = 'smoke-admin-token';   // 双 token 生产姿态（无 MS_KEY_DEV）
const CLIENT_TOKEN = 'smoke-client-token';

const MSG_NO_KEY = '未绑定授权 key：请在「当前系统 key 属性」中输入并保存';
const FAKE_KEY = 'MS-FAKE-NOPE';
const PARSE_TIMEOUT = 150_000;   // 样例/母版深度解析 + commit 单程（3069 实测 <90s）

const results = [];
function check(name, ok, extra) {
  results.push({ name, ok: !!ok });
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name + (extra ? '  [' + String(extra).slice(0, 200) + ']' : ''));
}
function log(msg) { console.log('-- ' + msg); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- 前置自检
if (!existsSync(STATIC_INDEX)) {
  console.error('前置缺失：materialSorting-web/static/index.html 不存在 —— 先 cd materialSorting-web && npm run build');
  process.exit(2);
}
if (!existsSync(PY)) {
  console.error('前置缺失：.venv/Scripts/python.exe 不存在（keyserver/materialsorting 需已安装）');
  process.exit(2);
}
for (const [port, what] of [[MS_PORT, 'ms-web'], [KEY_PORT, 'keyserver']]) {
  try {
    const probe = await fetch('http://127.0.0.1:' + port + '/', { signal: AbortSignal.timeout(1500) });
    if (probe.ok) {
      console.error('端口 ' + port + ' 已被占用（' + what + '，疑似残留服务）—— 请先释放再跑');
      process.exit(2);
    }
  } catch { /* 未占用 = 正常 */ }
}
// 临时目录重铸（断言确定性：key_state/账本/上传产物每跑从零开始）
rmSync(MS_OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
mkdirSync(MS_OUT + '/sparrow_baseline', { recursive: true });
rmSync(KEY_DB, { force: true });
rmSync(KEY_DB + '-wal', { force: true });
rmSync(KEY_DB + '-shm', { force: true });
if (existsSync(BASELINE_INTERMEDIATE)) {
  copyFileSync(BASELINE_INTERMEDIATE, MS_OUT + '/sparrow_baseline/pieces_intermediate.json');
}

// ---------------------------------------------------------------- 自举起服
function spawnServer(name, code, env) {
  const srvLog = [];
  const srv = spawn(PY, ['-c', code], {
    cwd: ROOT, env: { ...process.env, ...env },
    windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  srv.stdout.on('data', (d) => srvLog.push(String(d)));
  srv.stderr.on('data', (d) => srvLog.push(String(d)));
  const kill = () => {
    if (srv.exitCode !== null) return;
    if (process.platform === 'win32') {
      try { spawn('taskkill', ['/F', '/T', '/PID', String(srv.pid)], { windowsHide: true }); } catch { /* 尽力 */ }
    }
    try { srv.kill(); } catch { /* 尽力 */ }
  };
  return { name, srv, srvLog, kill };
}
async function waitReady(base, path, holder) {
  for (let i = 0; i < 90; i++) {
    if (holder.srv.exitCode !== null) break;
    try {
      const r = await fetch(base + path, { signal: AbortSignal.timeout(1000) });
      if (r.ok) return true;
    } catch { /* 等下一轮 */ }
    await sleep(1000);
  }
  console.error(holder.name + ' 起服失败（' + base + ' 未就绪）—— 服务日志尾：\n'
    + holder.srvLog.join('').slice(-2000));
  return false;
}

const keyserver = spawnServer('keyserver',
  'import uvicorn; from keyserver.app import app; '
  + 'uvicorn.run(app, host="127.0.0.1", port=' + KEY_PORT + ')', {
    MS_KEY_DB: KEY_DB,
    MS_KEY_ADMIN_TOKEN: ADMIN_TOKEN,     // 双 token 生产姿态（决策台账：frp 双 token 强制）
    MS_KEY_CLIENT_TOKEN: CLIENT_TOKEN,
  });
const msweb = spawnServer('ms-web',
  'import uvicorn; from materialsorting.web.server import app; '
  + 'uvicorn.run(app, host="127.0.0.1", port=' + MS_PORT + ')', {
    MS_KEY_SERVER_URL: KEY,              // keygate URL 解析链 ①env
    MS_KEY_CLIENT_TOKEN: CLIENT_TOKEN,   // keygate 自动附 X-Client-Token（US-009 链）
    MS_OUT_DIR: MS_OUT,                  // 正斜杠；隔离真实 out/ 与 license/
  });

// 起服等待（try 外：失败 = 前置错误 exit 2，杀净双服务不留残留）
let bootOk = await waitReady(KEY, '/api/key/health', keyserver);
if (bootOk) bootOk = await waitReady(MS, '/', msweb);
if (!bootOk) {
  msweb.kill();
  keyserver.kill();
  process.exit(2);
}

let browser = null;
const pageRef = { page: null };            // 异常兜底截图用（page 声明在 try 内）
try {
  log('双服务就绪：keyserver :' + KEY_PORT + '（双 token）+ ms-web :' + MS_PORT + '（MS_OUT_DIR 临时目录）');

  // ---- T0 双 token 生产姿态（管理/消费端族无 token 401；带 token 过鉴权）----
  const adminNoTok = await fetch(KEY + '/api/admin/keys');
  check('T0 管理端无 token 401（MS_KEY_ADMIN_TOKEN 强制）', adminNoTok.status === 401, 'HTTP ' + adminNoTok.status);
  const consumerNoTok = await fetch(KEY + '/api/key/info', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: 'MS-XXXXX-XXXXX-XXXXX', machine_guid: 'probe' }),
  });
  check('T0 消费端无 X-Client-Token 401（MS_KEY_CLIENT_TOKEN 强制）', consumerNoTok.status === 401, 'HTTP ' + consumerNoTok.status);
  const consumerWithTok = await fetch(KEY + '/api/key/info', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Client-Token': CLIENT_TOKEN },
    body: JSON.stringify({ key: 'MS-XXXXX-XXXXX-XXXXX', machine_guid: 'probe' }),
  });
  check('T0 消费端带 token 过鉴权（404 key 不存在 = 已过 401 层）', consumerWithTok.status === 404, 'HTTP ' + consumerWithTok.status);

  // ---- 建 key（管理端 API，X-Admin-Token）：S1/S2 合并 source + D 时长 target + C 次数 ----
  async function createKey(payload) {
    const r = await fetch(KEY + '/api/admin/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Token': ADMIN_TOKEN },
      body: JSON.stringify(payload),
    });
    if (r.status !== 201) throw new Error('create key 失败 HTTP ' + r.status + ': ' + (await r.text()));
    return (await r.json()).key_plaintext;
  }
  const SRC_A = await createKey({ key_type: 'duration', duration_days: 3, remark: 'US010-source-a' });
  const SRC_B = await createKey({ key_type: 'duration', duration_days: 4, remark: 'US010-source-b' });
  const DUR_KEY = await createKey({ key_type: 'duration', duration_days: 10, remark: 'US010-target' });
  const COUNT_KEY = await createKey({ key_type: 'count', total_uses: 30, remark: 'US010-count' });
  log('key 就绪：source ' + SRC_A + ' / ' + SRC_B + '；target ' + DUR_KEY + '；count ' + COUNT_KEY);

  async function adminKeys() {
    const r = await fetch(KEY + '/api/admin/keys', { headers: { 'X-Admin-Token': ADMIN_TOKEN } });
    return (await r.json()).keys;
  }
  const countBefore = (await adminKeys()).find((k) => k.key_plaintext === COUNT_KEY);
  check('T0 count key 初始 0/30 未绑定', countBefore.detail === '0/30' && countBefore.status === '未绑定',
    countBefore.detail + ' / ' + countBefore.status);

  // ---- A 生产 bundle 含新代码（:8010 首页引用的 JS 产物锚点断言）----
  const html = await (await fetch(MS + '/')).text();
  const m = html.match(/src="(\/static\/assets\/index-[^"]+\.js)"/);
  check('A 首页引用生产 bundle', Boolean(m), m ? m[1] : html.slice(0, 120));
  const bundle = m ? await (await fetch(MS + m[1])).text() : '';
  check('A bundle 含三入口预检（/api/key/precheck）', bundle.includes('/api/key/precheck'));
  check('A bundle 含 key 属性弹窗（key-info-*）',
    bundle.includes('key-info-overlay') && bundle.includes('key-info-merge-input'));
  check('A bundle 不含 keyserver 端点/URL（全链路无跨域，FR-11）',
    !bundle.includes('MS_KEY_SERVER_URL') && !bundle.includes('/api/key/bind') && !bundle.includes('/api/key/validate'));

  // ---- 浏览器（Edge 通道免装浏览器 + ms.tour.* 预置防 tour-overlay 拦截）----
  const { chromium } = await import('playwright');
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
    // fetch 日志：URL 计数（/start 零发出断言）+ precheck 回包捕获（豁免 reason 对拍）
    const log = [];
    window.__fetchLog = log;
    const orig = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = String(typeof input === 'string' ? input : input.url);
      const entry = { url, res: null };
      log.push(entry);
      const r = await orig(input, init);
      if (url.includes('/api/key/precheck')) {
        try { entry.res = await r.clone().json(); } catch { /* 半截响应容忍 */ }
      }
      return r;
    };
  });
  const page = await context.newPage();
  pageRef.page = page;                     // catch 兜底截图可达（try 块 const 不入 catch 域）
  const toastTexts = () => page.locator('.toast-stack .toast-msg').allInnerTexts();
  const fetchCount = (fragment) => page.evaluate(
    (f) => window.__fetchLog.filter((e) => e.url.includes(f)).length, fragment);
  const precheckResults = () => page.evaluate(
    () => window.__fetchLog.filter((e) => e.url.includes('/api/key/precheck') && e.res !== null).map((e) => e.res));

  async function waitForCommitDone() {
    await page.waitForFunction(() => {
      const els = document.querySelectorAll('[data-testid="commit-status"]');
      return Array.from(els).some((e) => e.textContent && e.textContent.includes('已应用至超排'));
    }, { timeout: PARSE_TIMEOUT });
  }
  async function gotoNestingTab() {
    await page.locator('button.tab', { hasText: '超排' }).click();
    await page.locator('#start, #restart').first().waitFor({ timeout: 8000 });
  }
  async function checkFirstSize() {
    const cb = page.locator('.sizes input[type=checkbox]').first();
    if (!(await cb.isChecked())) await cb.check();
  }
  /** 结果态（上轮 run 常驻）→ 「重新配置」回配置态；首跑无历史时本就在配置态。 */
  async function resetModalToConfig() {
    const again = page.locator('[data-testid="strategy-again-btn"]');
    if ((await again.count()) > 0) await again.click();
  }

  await page.goto(MS + '/', { waitUntil: 'networkidle' });

  // ==== B 样例载入免闸（三入口；全程未绑任何 key）====
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="sample-select"]');
    return el && el.options.length > 1;
  }, { timeout: 8000 });
  await page.locator('[data-testid="sample-apply"]').click();
  await waitForCommitDone();
  const sampleName = await page.locator('[data-testid="sample-select"]').inputValue();
  check('B 样例应用 commit 完成（免闸前置）', true, '样例 ' + sampleName.slice(0, 24) + '…');
  await gotoNestingTab();
  await checkFirstSize();

  // B1 普通：#start → running（#stop 在场）→ 停止
  await page.locator('#start').click();
  await page.locator('#stop').waitFor({ timeout: 20_000 });
  check('B1 样例免闸·普通运行放行（进 WS running）', true);
  await page.screenshot({ path: OUT + '/01-sample-run.png' });
  await page.locator('#stop').click();
  await page.locator('#start, #restart').first().waitFor({ timeout: 30_000 });
  check('B1 样例免闸·停止回非 running', true);

  // B2 高级：exec → 202 进度态 → 停止 → 结果态
  await page.locator('[data-testid="strategy-btn"]').click();
  await page.locator('[data-testid="strategy-overlay"], .strategy-modal').first().waitFor({ timeout: 8000 });
  await page.locator('[data-testid="strategy-exec-btn"]').click();
  await page.locator('[data-testid="strategy-stop-btn"]').waitFor({ timeout: 30_000 });
  check('B2 样例免闸·高级运行放行（202 起 worker）', true);
  check('B2 /api/strategy/start 已发出', (await fetchCount('/api/strategy/start')) === 1);
  // 等 seed 臂产出首帧 best_frame（大数字利用率非「—」）再停 —— starting 期停止
  // 无 run_dir，result 端点 409「运行未产出 run 目录」→ 前端 result 恒 null、
  // 结果态只剩常驻「正在读取运行结果…」占位（无「再次运行」出口），C2 相位重开
  // 弹窗将无法回配置态（首轮实勘）。有帧后停止 → result 回落 best_frame 边车 →
  // 结果态完整可读。
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="strategy-big-density"]');
    const t = el && el.textContent;
    return !!t && t.includes('%') && t !== '—';
  }, { timeout: 120_000 });
  await page.locator('[data-testid="strategy-stop-btn"]').click();
  await page.locator('[data-testid="strategy-result-head"]').waitFor({ timeout: 30_000 });
  check('B2 停止后结果态可读（best_frame 回落，留「再次运行」出口）', true);
  await page.locator('[data-testid="strategy-close"]').click();
  await sleep(800);

  // B3 极限：同款（策略/极限同会话 409 单飞互斥 → 上一轮已到终态再起）
  await page.locator('[data-testid="extreme-btn"]').click();
  await page.locator('[data-testid="extreme-overlay"]').waitFor({ timeout: 8000 });
  await page.locator('[data-testid="extreme-exec-btn"]').click();
  await page.locator('[data-testid="strategy-stop-btn"]').waitFor({ timeout: 30_000 });
  check('B3 样例免闸·极限运行放行（202 起 worker）', true);
  check('B3 /api/extreme/start 已发出', (await fetchCount('/api/extreme/start')) === 1);
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="strategy-big-density"]');
    const t = el && el.textContent;
    return !!t && t.includes('%') && t !== '—';
  }, { timeout: 120_000 });
  await page.locator('[data-testid="strategy-stop-btn"]').click();
  await page.locator('[data-testid="strategy-result-head"]').waitFor({ timeout: 30_000 });
  check('B3 停止后结果态可读（best_frame 回落，留「再次运行」出口）', true);
  await page.locator('[data-testid="extreme-close"]').click();
  await sleep(600);
  // precheck 回包对拍：样例豁免 reason（免闸的判定序证据，非仅行为放行）
  const bPrechecks = await precheckResults();
  check('B precheck 回包 reason=sample（样例豁免穿透预检）',
    bPrechecks.length >= 3 && bPrechecks.slice(0, 3).every((r) => r && r.ok === true && r.reason === 'sample'),
    JSON.stringify(bPrechecks.slice(0, 3)));
  const bPrecheckCount = await fetchCount('/api/key/precheck');

  // ==== C 真实母版 + 未绑 key → 三入口全拦 ====
  const samples = (await (await fetch(MS + '/api/samples')).json()).samples;
  const blob = await (await fetch(MS + '/api/samples/file?name=' + encodeURIComponent(samples[0].name))).blob();
  const buf = await blob.arrayBuffer();
  await page.locator('button.tab', { hasText: '上传预览' }).click();
  await page.setInputFiles('input[type=file]', {
    name: '工单-US010-冒烟.dxf',          // basename 脱离 data/ 白名单 → 无样例豁免
    mimeType: 'application/dxf',
    buffer: Buffer.from(buf),
  });
  await waitForCommitDone();
  check('C 真实母版改名上传 commit 完成', true, '样例字节 → 工单-US010-冒烟.dxf');
  await gotoNestingTab();
  await checkFirstSize();

  // C1 普通：StatusLine + Toast + 不进 WS
  await page.locator('#start, #restart').first().click();
  await page.waitForFunction(
    () => document.querySelector('#status')?.textContent?.includes('未绑定授权 key'),
    { timeout: 8000 },
  );
  const cStatus = await page.locator('#status').innerText();
  check('C1 未绑 key·普通运行拦截 StatusLine 中文', cStatus.includes(MSG_NO_KEY), cStatus);
  check('C1 未绑 key·普通运行拦截 Toast', (await toastTexts()).some((t) => t.includes(MSG_NO_KEY)),
    (await toastTexts()).join(' | '));
  check('C1 未绑 key·不进 WS（#start/#restart 仍在）', (await page.locator('#start, #restart').count()) === 1);
  await page.screenshot({ path: OUT + '/02-blocked-normal.png' });

  // C2 高级：弹窗红字 + /start 零新发（B 相位发过 1 次 → 计数不变）
  await page.locator('[data-testid="strategy-btn"]').click();
  await page.locator('[data-testid="strategy-overlay"], .strategy-modal').first().waitFor({ timeout: 8000 });
  await resetModalToConfig();           // B2 停止后结果态常驻 → 先回配置态
  const preStratCount = await fetchCount('/api/strategy/start');
  await page.locator('[data-testid="strategy-exec-btn"]').click();
  await page.locator('[data-testid="strategy-error"]').waitFor({ timeout: 8000 });
  const cStratErr = await page.locator('[data-testid="strategy-error"]').innerText();
  check('C2 未绑 key·高级运行弹窗红字中文', cStratErr.includes(MSG_NO_KEY), cStratErr);
  check('C2 高级运行不发 /start', (await fetchCount('/api/strategy/start')) === preStratCount);
  await page.screenshot({ path: OUT + '/03-blocked-strategy.png' });
  await page.locator('[data-testid="strategy-close"]').click();
  await sleep(400);

  // C3 极限：同款（结果态组件族共用 strategy-again-btn）
  await page.locator('[data-testid="extreme-btn"]').click();
  await page.locator('[data-testid="extreme-overlay"]').waitFor({ timeout: 8000 });
  await resetModalToConfig();
  const preExtCount = await fetchCount('/api/extreme/start');
  await page.locator('[data-testid="extreme-exec-btn"]').click();
  await page.locator('[data-testid="strategy-error"]').waitFor({ timeout: 8000 });
  const cExtErr = await page.locator('[data-testid="strategy-error"]').innerText();
  check('C3 未绑 key·极限运行弹窗红字中文', cExtErr.includes(MSG_NO_KEY), cExtErr);
  check('C3 极限运行不发 /start', (await fetchCount('/api/extreme/start')) === preExtCount);
  await page.locator('[data-testid="extreme-close"]').click();
  await sleep(400);
  const cPrechecks = (await precheckResults()).filter((r) => r && r.ok === false);
  check('C precheck 回包 ok=false 且三入口文案一致',
    cPrechecks.length >= 3 && cPrechecks.every((r) => r.message === MSG_NO_KEY),
    JSON.stringify(cPrechecks.slice(0, 3)));
  check('C 三入口各发一次 precheck（计数 +3）',
    (await fetchCount('/api/key/precheck')) >= bPrecheckCount + 3);

  // ==== D 假 key 保存报错（keyserver 404 中文透传，不落盘）====
  await page.locator('[data-testid="key-entry-btn"]').click();
  await page.locator('[data-testid="key-info-overlay"]').waitFor({ timeout: 8000 });
  await page.locator('[data-testid="key-info-key-input"]').fill(FAKE_KEY);
  await page.locator('[data-testid="key-info-save"]').click();
  await page.locator('[data-testid="key-info-save-error"]').waitFor({ timeout: 8000 });
  const dErr = await page.locator('[data-testid="key-info-save-error"]').innerText();
  check('D 假 key 保存中文红字（key 不存在）', dErr.includes('key 不存在'), dErr);
  await page.screenshot({ path: OUT + '/04-fake-key.png' });

  // ==== E 真 key 绑定（时长型）+ 批量合并 ====
  // source 预绑到本机（merge 前置：source 须绑定当前系统）—— 走 MS 后端 save 端点
  //（机器级全局无会话闸门；keygate 附 X-Client-Token，与 UI 保存同链路）
  for (const k of [SRC_A, SRC_B]) {
    const r = await fetch(MS + '/api/key/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: k }),
    });
    check('E source 预绑本机 ' + k.slice(0, 11) + '…', r.ok, 'HTTP ' + r.status);
  }
  // 时长型 key 绑定（真 key 绑定 ①）：属性 = 生效/截止/剩余天数
  await page.locator('[data-testid="key-info-key-input"]').fill(DUR_KEY);
  await page.locator('[data-testid="key-info-save"]').click();
  await page.locator('[data-testid="key-attr-days"]').waitFor({ timeout: 8000 });
  const eAct = await page.locator('[data-testid="key-attr-activated"]').innerText();
  const eDays = await page.locator('[data-testid="key-attr-days"]').innerText();
  check('E 时长 key 绑定即激活（生效时间在案 + 剩余天数）', /\d{4}/.test(eAct) && eDays.includes('10'),
    eAct + ' | ' + eDays);
  const dBadge = await page.locator('[data-testid="key-attr-status"] .key-status-badge').innerText();
  check('E 时长 key 正在使用徽标', dBadge === '正在使用', dBadge);
  const expiresBefore = await page.locator('[data-testid="key-attr-expires"]').innerText();
  // 批量合并两 source（含空行/尾随空白 → strip 韧性）
  await page.locator('[data-testid="key-info-merge-input"]')
    .fill(SRC_A + '\n' + SRC_B + '\n\n  ');
  await page.locator('[data-testid="key-info-merge-btn"]').click();
  await page.locator('[data-testid="key-info-merge-total"]').waitFor({ timeout: 8000 });
  const rows = await page.locator('[data-testid="key-info-merge-row"]').allInnerTexts();
  check('E 批量合并明细两行（每 key 转移天数）', rows.length === 2, JSON.stringify(rows));
  check('E 明细含 source key', rows[0].includes(SRC_A) && rows[1].includes(SRC_B), rows.join(' ; '));
  const eTotal = await page.locator('[data-testid="key-info-merge-total"]').innerText();
  check('E 共转移 ~3+4 天（秒级转移四舍五入）', /共转移\s*[67]/.test(eTotal), eTotal);
  const expiresAfter = await page.locator('[data-testid="key-attr-expires"]').innerText();
  check('E 截止时间随合并延长', expiresAfter !== expiresBefore, expiresBefore + ' → ' + expiresAfter);
  await page.screenshot({ path: OUT + '/05-merge-result.png' });
  const eKeys = await adminKeys();
  const eSrc = eKeys.filter((k) => k.key_plaintext === SRC_A || k.key_plaintext === SRC_B);
  check('E keyserver 侧 source 已合并（保留不物理删除）',
    eSrc.length === 2 && eSrc.every((k) => k.status === '已合并'),
    eSrc.map((k) => k.status).join(','));
  const eDur = eKeys.find((k) => k.key_plaintext === DUR_KEY);
  check('E keyserver 侧 target 正在使用', eDur.status === '正在使用', eDur.status);

  // ==== F 换绑次数型 key（真 key 绑定 ②，运行用 key）====
  await page.locator('[data-testid="key-info-key-input"]').fill(COUNT_KEY);
  await page.locator('[data-testid="key-info-save"]').click();
  await page.locator('[data-testid="key-attr-total"]').waitFor({ timeout: 8000 });
  const fTotal = await page.locator('[data-testid="key-attr-total"]').innerText();
  const fUsed = await page.locator('[data-testid="key-attr-used"]').innerText();
  const fRemain = await page.locator('[data-testid="key-attr-remaining"]').innerText();
  check('F 次数 key 属性 总数/已用/剩余 = 30/0/30',
    fTotal.includes('30') && fUsed.includes('0') && fRemain.includes('30'),
    fTotal + ' / ' + fUsed + ' / ' + fRemain);
  const fBadge = await page.locator('[data-testid="key-attr-status"] .key-status-badge').innerText();
  check('F 次数 key 正在使用徽标', fBadge === '正在使用', fBadge);
  const mirror = await page.evaluate(() => localStorage.getItem('ms_key'));
  check('F localStorage ms_key 镜像双写', mirror === COUNT_KEY, String(mirror));
  await page.screenshot({ path: OUT + '/06-count-attrs.png' });
  await page.keyboard.press('Escape');
  await page.locator('[data-testid="key-info-overlay"]').waitFor({ state: 'detached', timeout: 8000 });

  // ==== G 绑定有效 key 后运行跑通（真实母版，全程唯一一次扣次）====
  await page.locator('#start, #restart').first().click();
  await page.locator('#stop').waitFor({ timeout: 20_000 });
  check('G 绑定 count key 后普通运行放行（进 WS running）', true);
  await page.screenshot({ path: OUT + '/07-run-allowed.png' });
  await page.locator('#stop').click();
  await page.locator('#start, #restart').first().waitFor({ timeout: 30_000 });
  check('G 停止回非 running', true);

  // ==== H keyserver 侧断言：扣次恰 +1 + 使用统计当日 +1 ====
  const hKeys = await adminKeys();
  const hCount = hKeys.find((k) => k.key_plaintext === COUNT_KEY);
  check('H count key 扣次恰 +1（used 1/30）', hCount.detail === '1/30', hCount.detail);
  check('H count key 状态正在使用', hCount.status === '正在使用', hCount.status);
  const stats = hCount.usage_stats;
  check('H 使用统计 daily +1（total=1 峰=1 均=1.0）',
    stats !== null && stats.total === 1 && stats.max_daily === 1 && Number(stats.avg_daily) === 1,
    JSON.stringify(stats));
  const hDur = hKeys.find((k) => k.key_plaintext === DUR_KEY);
  check('H 时长 key 统计零记录（绑定/合并不动账）', hDur.usage_stats === null, JSON.stringify(hDur.usage_stats));
} catch (err) {
  check('脚本异常中断', false, String(err));
  try { if (pageRef.page) await pageRef.page.screenshot({ path: OUT + '/99-error.png' }); } catch { /* 尽力 */ }
} finally {
  try { if (browser) await browser.close(); } catch { /* 尽力 */ }
  msweb.kill();
  keyserver.kill();
}

const failed = results.filter((r) => !r.ok);
const report = {
  ts: new Date().toISOString(),
  ms: MS, keyserver: KEY,
  posture: '双 token 生产姿态（MS_KEY_ADMIN_TOKEN + MS_KEY_CLIENT_TOKEN，无 MS_KEY_DEV）',
  bundleEntry: 'ms-web :8010 生产构建（materialSorting-web/static/，npm run build 产物）',
  checks: results, pass: failed.length === 0,
};
writeFileSync(OUT + '/report.json', JSON.stringify(report, null, 2));
writeFileSync(OUT + '/report.txt',
  results.map((r) => (r.ok ? 'PASS' : 'FAIL') + '  ' + r.name).join('\n') + '\n');
console.log('\n' + (results.length - failed.length) + '/' + results.length + ' PASS -> ' + OUT + '/report.txt');
if (failed.length) console.log('FAILED:\n' + failed.map((r) => '  ' + r.name).join('\n'));
process.exitCode = failed.length ? 1 : 0;

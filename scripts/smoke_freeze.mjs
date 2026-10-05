// 冻结验收自动化（US-004，权威 PRD：tasks/prd-local-deploy-freeze.md）—— 把冻结版
// 验收固化成可重复脚本：隔离用户目录 + 全功能冒烟 + 单实例/端口回退/数据落点三专项。
//
//   node scripts/smoke_freeze.mjs [--exe <MaterialSorting.exe>] [--keep] [--rerun-family]
//
// 编排（对齐 PRD AC1~AC5）：
//   P0 预检：dist exe 存在（缺失 → 明确报错指路 build_freeze，exit 2 = dev 形态
//      验收入口）+ `--check` frozen/warm/version/OUT_DIR env 注入四断言 + key
//      sidecar 回归锁（两文件捆绑在 dist exe 旁 + 净化 env 下 URL/token 解析自
//      「exe 旁」= 2026-09-29 交付包缺 sidecar 事故回归锁，全新客户机语义）；
//   P1 端口回退专项（AC2-1）：临时 MS_OUT_DIR（模拟 LOCALAPPDATA 隔离）→ 预占
//      8010 → 拉 dist exe（环境注入 OUT_DIR 覆盖）→ 等健康 → 断言实际用 8011 且
//      web_port.txt 内容一致；首启 watcher 自动开浏览器 URL（BROWSER=cmd echo 捕获
//      日志，webbrowser.open 实参取证，不起真浏览器）；
//   P2 核心动线（AC1，playwright Edge 通道，沿用 smoke_edit_polish.mjs 套路）：
//      样例双端点断言（列表非空 + 取文件字节在案 = 2026-09-29 无样例事故回归锁）
//      → 样例应用 5336（豁免收紧后免 key 路径）→ parse 数量矩阵 → 3 码短预算求解 → final → 导出 PLT-clean /
//      DXF(R12 POLYLINE) / PNG 三格式落盘探针 → 状态保存 .msn 下载 + gunzip 断言；
//   P3 高级运行专项（AC2-4，冻结 spawn exe --cli 链路）：/api/strategy/start race →
//      running + run_dir 落临时 OUT_DIR config_runs/web_* + best_frame 出帧 +
//      运行中 exe 进程数 ≥2 → stop 收敛 stopped / 进程数回落；
//   P4 既有 smoke 族复跑（可选 --rerun-family）：smoke_prefix_extra / smoke_state_file
//      / smoke_edit_polish 经 SMOKE_BASE_URL 参数指向冻结实例（:8011）复跑，产物
//      报告仍落各自 out/smoke_*；
//   P5 单实例专项（AC2-2）：二次启动 exit 0 + stdout「检测到已在运行的实例」URL
//      指向既有端口 + webbrowser.open 实调 URL 同端口 + MaterialSorting.exe 进程
//      数不增；
//   P6 数据落点专项（AC2-3）：uploads/ 母版、sparrow_baseline intermediate、
//      config_runs/web_* 全落临时 OUT_DIR；dist 安装目录 stat 快照（文件清单/大小/
//      mtime）+ exe sha256 前后零变化（只读安全）。
//
// 退出码（AC3）：全部检查过 = 0；任一失败 = 1 并逐条打印失败项；dist 产物缺失 = 2
// （dev 形态明确报错指路 build_freeze）。输出含通过项计数（N/N 惯例）；报告 =
// out/smoke_freeze/report.json。临时 OUT_DIR 失败时保留诊断（--keep 恒保留）。
//
// 前置：dist 已构建（.venv/Scripts/python.exe scripts/build_freeze.py）；8010/8011
// 空闲（有 ms-web 在跑请先停）。人工运营 checklist（无 Python 虚拟机安装 / 三杀软
// 观察 / CPU 基线话术）= US-005 发版手册运营步骤，非本脚本自动判据。
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import net from 'node:net';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';

// playwright 借 materialSorting-web 的安装（repo 根无 node_modules，smoke_edit_layout 同款）
const { chromium } = createRequire(
  new URL('../materialSorting-web/package.json', import.meta.url),
)('playwright');

// ---------------------------------------------------------------- 常量与参数
const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '..');
const args = process.argv.slice(2);
const argOf = (name) => {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : null;
};
const KEEP = args.includes('--keep');
const RERUN_FAMILY = args.includes('--rerun-family');

const DIST_APP_DIR = resolve(ROOT, 'dist/MaterialSorting.dist');
const EXE = argOf('--exe') || resolve(DIST_APP_DIR, 'MaterialSorting.exe');
const OUT = resolve(ROOT, 'out/smoke_freeze');            // 报告与导出探针落点（repo out）
const MS_OUT_DIR = resolve(OUT, 'ms_out');                // 临时 OUT_DIR（模拟 LOCALAPPDATA 隔离）
const BROWSER_LOG = resolve(OUT, 'browser_calls.log');    // webbrowser.open 实参捕获（cmd echo）
const SERVER_LOG = resolve(OUT, 'server_stdout.log');

const PORT_OCCUPIED = 8010;   // 预占端口（触发回退）
const EXPECT_PORT = 8011;     // 期望回退落点
const BASE = `http://127.0.0.1:${EXPECT_PORT}`;
const SAMPLE_NAME = '5336#老六订单14%7%围加9.dxf';   // P2 样例应用目标（data/ 同名；豁免收紧后的免 key 路径，见 P2b 注释）
const DXF = resolve(ROOT, 'data', SAMPLE_NAME);
const SIZES = [32, 33, 34];   // 5336 码集；3 码 × 10 片型 × 默认 1 = Σdemand 30
const EXPECT_PLACED = 30;
const SOLVE_TIME = '12';
const EXE_IMAGE = 'MaterialSorting.exe';

// BROWSER=cmd echo %s>>log：webbrowser 退 GenericBrowser（get() 走 '%s' 分支
// shlex.split），webbrowser.open 实参追加进捕获日志 —— 不起真浏览器 + 单实例
// 「浏览器 URL 指向既有端口」的确定性取证（US-003 E2E 的 BROWSER=findstr 升级版；
// shlex 不吃反斜杠，路径一律正斜杠 + 引号防空格）。
const toFwd = (p) => p.replace(/\\/g, '/');
const BROWSER_CMD = `cmd /c echo %s>>"${toFwd(BROWSER_LOG)}"`;

// ---------------------------------------------------------------- 基础设施
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail: String(detail ?? '') });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + String(detail).slice(0, 300) : ''}`);
  return ok;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (msg) => console.log('==== ' + msg);
/** 2026-10-05：普通运行先开 NormalRunModal（#time 已移入弹窗，id 保留）——
 *  点 #start/#restart → 弹窗内填时长（省略 = 预填值）→ 确认启动。 */
async function runNormal(p, timeSec) {
  await p.locator('#start, #restart').first().click();
  await p.locator('#time').waitFor({ timeout: 8000 });
  if (timeSec !== undefined) await p.locator('#time').fill(String(timeSec));
  await p.locator('[data-testid="normal-run-confirm"]').click();
}

async function httpOk(port, timeoutMs = 3000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`http://127.0.0.1:${port}/`, { signal: ctrl.signal });
    return r.status >= 200 && r.status < 300;
  } catch { return false; } finally { clearTimeout(t); }
}
async function waitHealth(port, timeoutMs, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (await httpOk(port)) return true;
    await sleep(500);
  }
  throw new Error(`健康等待超时（${label}，${Math.round(timeoutMs / 1000)}s）：http://127.0.0.1:${port}`);
}
function portFree(port) {
  return new Promise((res) => {
    const s = net.createServer();
    s.once('error', () => res(false));
    s.once('listening', () => s.close(() => res(true)));
    s.listen(port, '127.0.0.1');
  });
}

function exeProcs() {
  const r = spawnSync('tasklist', ['/FO', 'CSV', '/NH', '/FI', `IMAGENAME eq ${EXE_IMAGE}`],
    { timeout: 60_000 });
  if (r.status !== 0) throw new Error('tasklist 失败: ' + r.stderr);
  return String(r.stdout)
    .split(/\r?\n/)
    .filter((l) => l.toLowerCase().startsWith(`"${EXE_IMAGE.toLowerCase()}"`)).length;
}
async function waitExeCount(n, timeoutMs) {
  const t0 = Date.now();
  let last = -1;
  while (Date.now() - t0 < timeoutMs) {
    last = exeProcs();
    if (last === n) return n;
    await sleep(1000);
  }
  return last;   // 未收敛，返回最后观测值交断言裁决
}

function treeSnapshot(dir) {
  const map = new Map();
  const walk = (d, rel) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const p = resolve(d, e.name);
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) walk(p, r);
      else {
        const st = statSync(p);
        map.set(r, { size: st.size, mtimeMs: st.mtimeMs });
      }
    }
  };
  walk(dir, '');
  return map;
}
function sha256File(p) {
  return createHash('sha256').update(readFileSync(p)).digest('hex');
}

const browserLogLines = () => {
  try { return readFileSync(BROWSER_LOG, 'utf8').split(/\r?\n/).filter((l) => l.trim()); }
  catch { return []; }
};

// ---------------------------------------------------------------- 进程编排
let serverProc = null;
let dummy8010 = null;
function childEnv() {
  // MS_SESSION_MAX 放宽（6→16）：--rerun-family 全族背靠背复跑同一冻结实例，
  // P2/P3 核心动线 + 三个 smoke 各自的会话在 TTL 600s 内累积 >6，第 7 个
  // POST /api/session 429（首轮实勘：edit_polish 超排 Tab 永不解锁即此因）。
  // 会话上限行为本身由 test_web_sessions 锁定，非本脚本被测面。
  const env = { ...process.env, MS_OUT_DIR, BROWSER: BROWSER_CMD };
  if (RERUN_FAMILY) env.MS_SESSION_MAX = '16';
  return env;
}
function startServer() {
  mkdirSync(OUT, { recursive: true });
  const fd = openSync(SERVER_LOG, 'a');
  serverProc = spawn(EXE, [], { cwd: DIST_APP_DIR, env: childEnv(), stdio: ['ignore', fd, fd] });
  closeSync(fd);
  serverProc.once('exit', (code, sig) => {
    console.log(`[server] exe 退出 code=${code} sig=${sig}`);
  });
  return serverProc;
}
function killServer() {
  if (serverProc && serverProc.exitCode === null) {
    spawnSync('taskkill', ['/PID', String(serverProc.pid), '/T', '/F'], { timeout: 60_000 });
  }
}

// ---------------------------------------------------------------- 主流程
const report = {
  ts: new Date().toISOString(), exe: EXE, base: BASE, ms_out_dir: MS_OUT_DIR,
  dxf: DXF, solve_time_s: SOLVE_TIME, family: RERUN_FAMILY,
  check: null, port: null, core: null, advanced: null, single: null, data: null,
  results, pass: false,
};

// dev 形态入口（AC5）：dist 产物缺失 → 明确报错指路 build_freeze，exit 2。
if (!existsSync(EXE)) {
  console.error('');
  console.error('[smoke_freeze] 冻结产物缺失：' + EXE);
  console.error('  本验收脚本只测冻结形态（dist exe）。请先构建：');
  console.error('    .venv/Scripts/python.exe scripts/build_freeze.py');
  console.error('  （US-003 六步流水：前端 static 检查 → 环境自检 → spyrrow 钉板 → 孤儿扫描 → Nuitka 编译 → dist 自检）');
  console.error('  或用 --exe <path> 显式指定 MaterialSorting.exe 位置。');
  process.exit(2);
}

let browser = null;
try {
  // ---- P0 预检：--check 自检断言（env 注入 MS_OUT_DIR → OUT_DIR 落临时目录）--
  mkdirSync(OUT, { recursive: true });
  rmSync(MS_OUT_DIR, { recursive: true, force: true });
  mkdirSync(MS_OUT_DIR, { recursive: true });
  writeFileSync(BROWSER_LOG, '');
  log('P0 预检：dist exe --check（frozen/warm/version/OUT_DIR 注入）');
  const chk = spawnSync(EXE, ['--check'], { cwd: DIST_APP_DIR, env: childEnv(), encoding: 'utf8', timeout: 180_000 });
  const chkOut = (chk.stdout || '') + (chk.stderr || '');
  check('P0a exe --check 退出 0', chk.status === 0, 'status=' + chk.status);
  check('P0b --check frozen=True（freeze_entry 桥接生效）', /^frozen: True$/m.test(chkOut));
  check('P0c --check warm_start_supported=True（spyrrow 元数据捆绑红线）', /^warm_start_supported: True$/m.test(chkOut));
  check('P0d --check version 在案', /^version: (?!（未知)/m.test(chkOut), (chkOut.match(/^version: .*$/m) || [''])[0]);
  check('P0e --check paths.OUT_DIR = 临时 MS_OUT_DIR（env 注入覆盖生效）',
    new RegExp(`^paths\\.OUT_DIR: ${MS_OUT_DIR.replace(/\\/g, '\\\\')}$`, 'm').test(chkOut),
    (chkOut.match(/^paths\.OUT_DIR: .*$/m) || [''])[0]);
  // key sidecar 回归锁（红线④，2026-09-29「交付包缺 sidecar」事故 —— 打包先于
  // 手工铺文件，客户机全报「授权服务器未配置」）：① 两文件捆绑在 dist exe 旁；
  // ② 净化 env（删 MS_KEY_SERVER_URL/MS_KEY_CLIENT_TOKEN，防跑冒烟的机器设了
  // env 盖掉 sidecar 来源标注）+ MS_OUT_DIR 指向本脚本刚清空的临时目录
  // （license/ 回落档为空）再跑 --check → 全新客户机语义：URL/token 只可能解析
  // 自 exe 旁 sidecar。
  const keySidecarNames = ['key_server_url.txt', 'key_client_token.txt'];
  const sidecarBytes = keySidecarNames.map((n) => {
    try { return statSync(resolve(DIST_APP_DIR, n)).size; } catch { return -1; }
  });
  check('P0f key sidecar 两文件在 dist exe 旁（key 接线随包捆绑，红线④）',
    sidecarBytes.every((b) => b > 0),
    keySidecarNames.map((n, i) => `${n}:${sidecarBytes[i] >= 0 ? sidecarBytes[i] + 'B' : '缺失'}`).join(' '));
  const keyEnv = { ...childEnv() };
  delete keyEnv.MS_KEY_SERVER_URL;
  delete keyEnv.MS_KEY_CLIENT_TOKEN;
  const kchk = spawnSync(EXE, ['--check'], { cwd: DIST_APP_DIR, env: keyEnv, encoding: 'utf8', timeout: 180_000 });
  const kOut = (kchk.stdout || '') + (kchk.stderr || '');
  check('P0g --check key_server_url 解析自 exe 旁 sidecar（净化 env + 空 license 回落 = 全新客户机语义）',
    /^key_server_url: \S+（来源：key_server_url\.txt（exe 旁））$/m.test(kOut),
    (kOut.match(/^key_server_url: .*$/m) || [''])[0]);
  check('P0h --check key_client_token 已配置且来源 exe 旁（值不回显）',
    /^key_client_token: 已配置（来源：key_client_token\.txt（exe 旁），不回显值）$/m.test(kOut),
    (kOut.match(/^key_client_token: .*$/m) || [''])[0]);
  report.check = { status: chk.status, out: chkOut };

  // dist 只读安全基线快照（P6 对拍）
  const distSnap0 = treeSnapshot(DIST_APP_DIR);
  const exeHash0 = sha256File(EXE);
  report.dist_snapshot_files = distSnap0.size;

  // ---- P1 端口回退专项：预占 8010 → 实际用 8011 + web_port.txt 一致 ----------
  log('P1 端口回退：预占 8010 → 拉 dist exe → 期望 8011');
  if (!(await portFree(PORT_OCCUPIED))) {
    throw new Error('8010 已被占用（多半是 dev ms-web 在跑）—— 请先停 ms-web 再跑本验收');
  }
  if (!(await portFree(EXPECT_PORT))) {
    throw new Error('8011 已被占用，无法确定回退落点 —— 请释放后重跑');
  }
  dummy8010 = net.createServer();
  await new Promise((res, rej) => {
    dummy8010.once('error', rej);
    dummy8010.listen(PORT_OCCUPIED, '127.0.0.1', res);
  });
  check(`P1a 预占 ${PORT_OCCUPIED} 成功`, true);

  startServer();
  await waitHealth(EXPECT_PORT, 120_000, '冻结实例冷启动');
  check(`P1b 服务健康落在 ${EXPECT_PORT}（8010 被占自动回退）`, true);
  const portFile = resolve(MS_OUT_DIR, 'web_port.txt');
  const portTxt = existsSync(portFile) ? readFileSync(portFile, 'utf8').trim() : '(缺失)';
  check(`P1c web_port.txt 内容一致（=${EXPECT_PORT}）`, portTxt === String(EXPECT_PORT), 'web_port.txt=' + portTxt);

  // 首启 watcher 自动开浏览器 URL（健康后开，不早于服务就绪）
  const firstUrl = await (async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 60_000) {
      const lines = browserLogLines();
      if (lines.length) return lines[0].trim();
      await sleep(500);
    }
    return null;
  })();
  check(`P1d 首启自动开浏览器 URL=${BASE}（BROWSER 捕获，不早于就绪）`, firstUrl === BASE, 'captured=' + firstUrl);
  report.port = { occupied: PORT_OCCUPIED, actual: EXPECT_PORT, web_port_txt: portTxt, first_browser_url: firstUrl };

  // ---- P2 核心动线（playwright Edge 通道，沿用 smoke_edit_polish 套路）-------
  log('P2 核心动线：样例应用 → parse 数量矩阵 → 短预算求解 → 三格式导出 → .msn 保存');
  try { browser = await chromium.launch({ channel: 'msedge', headless: true }); }
  catch { browser = await chromium.launch({ channel: 'chrome', headless: true }); }
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();

  const dismissTour = async (p, rounds = 6) => {
    for (let i = 0; i < rounds; i++) {
      const gone = await p.evaluate(() => document.querySelector('[data-testid=tour-overlay]') === null);
      if (gone) return;
      await p.evaluate(() => { const b2 = document.querySelector('[data-testid=tour-skip]'); if (b2) b2.click(); });
      await p.waitForTimeout(600);
    }
  };
  const rawFetch = (p, url, init = null) => p.evaluate(async ({ u, i }) => {
    const r = await fetch(u, i);
    let body = null;
    try { body = await r.json(); } catch { body = null; }
    return { status: r.status, body };
  }, { u: url, i: init });

  const frameText = (f) => {
    if (typeof f === 'string') return f;
    if (f && typeof f.payload === 'string') return f.payload;
    if (f && f.payload != null && typeof f.payload === 'object') return String.fromCharCode(...f.payload);
    return '';
  };
  const cap = { msgs: [] };
  page.on('websocket', (ws) => {
    ws.on('framereceived', (f) => {
      try { cap.msgs.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
    });
  });
  const waitMsg = async (type, timeout = 180_000) => {
    const t0 = Date.now();
    for (;;) {
      const m = cap.msgs.find((x) => x && x.type === type);
      if (m) return m;
      if (Date.now() - t0 > timeout) return null;
      await sleep(500);
    }
  };

  await page.goto(BASE, { waitUntil: 'networkidle' });
  const sid = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('P2a 页面载入（tabbar）+ 会话 sid', !!(await page.evaluate(() => !!document.querySelector('.tabbar')))
    && /^[0-9a-f]{32}$/.test(sid || ''), 'sid=' + (sid || '').slice(0, 8));
  await dismissTour(page);

  // 样例端到端（2026-09-29「exe 无可用样例」事故回归锁）：frozen dist 捆绑
  // data/ 顶层 .dxf + launcher MS_DATA_DIR 重定向 exe 旁 data/ —— 任一缺失即
  // 此处红（此前 46 项无一覆盖样例动线，事故静默漏网）。列表非空 + 取回首样例
  // 字节在案；名字含 #/（）/中文走 encodeURIComponent query（与 SamplePicker 同口径）。
  const samplesRes = await rawFetch(page, '/api/samples', { cache: 'no-store' });
  const sampleNames = (samplesRes.body?.samples || []).map((s) => s.name);
  check('P2a-s1 样例列表非空（data/ 捆绑 + MS_DATA_DIR 重定向）',
    samplesRes.status === 200 && sampleNames.length >= 1,
    `status=${samplesRes.status} n=${sampleNames.length}`);
  if (sampleNames.length >= 1) {
    const sf = await page.evaluate(async (n) => {
      const r = await fetch(`/api/samples/file?name=${encodeURIComponent(n)}`);
      const b = await r.arrayBuffer();
      return { status: r.status, bytes: b.byteLength };
    }, sampleNames[0]);
    check(`P2a-s2 样例取文件 200 且字节在案（${sampleNames[0].slice(0, 16)}…）`,
      sf.status === 200 && sf.bytes > 1000,
      `status=${sf.status} bytes=${sf.bytes}`);
  }

  // P2b 入口 = 「样例」应用同一 5336（2026-09-29 豁免收紧后的设计免 key 路径）：
  // 直传上传同名文件不再豁免（9abb927），key 闸门在 precheck 拦下求解（本脚本
  // 临时 MS_OUT_DIR 无绑定 key，frozen 态 MS_KEY_MODE=off 亦不可绕 —— 收紧前
  // 三轮实拍：commit → precheck → 无 WS 连接即 P2d 超时）；样例应用经
  // SamplePicker 声明 sampleName → commit 期 sha256 对拍铸 doc.sample 标记 →
  // 闸门②样例豁免放行（P2 求解与 P3 策略 run 同读会话 doc 标记）。同一文件 →
  // 下游常量（SIZES/EXPECT_PLACED/ptypes g01..g10）全不变；直传上传路径由
  // --rerun-family 三冒烟的 dev 形态覆盖（dev 环境 out/license 已绑 key 过闸）。
  await page.waitForSelector('[data-testid=sample-select] option',
    { timeout: 60_000, state: 'attached' });   // option 在收起 select 内恒非 visible，attached 判在场
  await page.selectOption('[data-testid=sample-select]', SAMPLE_NAME);
  const parseDone = page.waitForResponse(
    (r) => r.url().includes('/api/parse-dxf') && r.status() === 200,
    { timeout: 300_000 });
  await page.click('[data-testid=sample-apply]');
  await parseDone;
  await page.waitForSelector('.qty-matrix', { timeout: 300_000 });
  check('P2b 样例应用 5336 → parse 出数量矩阵', true);
  await page.waitForSelector('button.tab:not([disabled]):has-text("超排")', { timeout: 300_000 });
  // commit-done 判据 = ptypes 代表裁片非空（超排 tab 解锁于 parse 完成而 commit 仍在
  // 后台跑 —— 单发会拿到空会话态，#start 抢跑会被 WS 以「排料数据为空」拒；edit_polish
  // 同款轮询）。
  let ptypes = null;
  const tP = Date.now();
  while (Date.now() - tP < 240_000) {
    const r = await rawFetch(page, '/api/ptypes', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
    if (r.status === 200 && Object.keys(r.body?.representatives || {}).length > 0) { ptypes = r.body; break; }
    await sleep(2000);
  }
  check('P2c commit 完成（ptypes 代表裁片非空）', !!ptypes,
    'labels=' + Object.keys(ptypes?.representatives || {}).join(','));
  await page.click('button.tab:has-text("超排")');
  await sleep(800);
  await dismissTour(page);
  for (const sz of SIZES) await page.check('#sz_' + sz);
  await runNormal(page, SOLVE_TIME);
  const finalMsg = await waitMsg('final', 240_000);
  const lastFrame = cap.msgs.filter((x) => x && x.type === 'frame').at(-1);
  const placed = lastFrame?.placed_items || [];
  check(`P2d 短预算求解 final（${SOLVE_TIME}s，density/width 在案）`,
    !!finalMsg && finalMsg.density > 0.5 && finalMsg.width_mm > 0,
    finalMsg ? `density=${(finalMsg.density * 100).toFixed(2)}% width=${Math.round(finalMsg.width_mm)}mm`
      : 'no final; ws errors=' + JSON.stringify(cap.msgs.filter((x) => x && x.type === 'error')).slice(0, 200));
  check(`P2e 末帧 placed = Σdemand（${EXPECT_PLACED}）`, placed.length === EXPECT_PLACED,
    'placed=' + placed.length);
  await page.screenshot({ path: OUT + '/01_final.png' });
  report.core = {
    density_pct: finalMsg ? +(finalMsg.density * 100).toFixed(3) : null,
    width_mm: finalMsg?.width_mm, placed: placed.length,
  };

  // 导出三格式：页内 fetch 包装捕获响应字节（btoa 二进制安全，PNG 不走 TextDecoder）
  await page.evaluate(() => {
    window.__exportCaps = [];
    window.__exportOrigFetch = window.fetch;
    const orig = window.__exportOrigFetch;
    window.fetch = async function (...args) {
      const res = await orig.apply(this, args);
      if (String(args[0]).includes('/export')) {
        try {
          const bytes = new Uint8Array(await res.clone().arrayBuffer());
          let bin = '';
          for (let i = 0; i < bytes.length; i += 0x8000)
            bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
          window.__exportCaps.push({ url: String(args[0]), status: res.status,
            type: res.headers.get('content-type'), cd: res.headers.get('content-disposition'),
            b64: btoa(bin), bytes: bytes.length });
        } catch (e) { window.__exportCaps.push({ err: String(e) }); }
      }
      return res;
    };
  });
  const exportDir = resolve(OUT, 'exports');
  mkdirSync(exportDir, { recursive: true });
  const exportOnce = async (fmt, modal) => {
    const before = await page.evaluate(() => (window.__exportCaps || []).length);
    await page.selectOption('select.export-fmt', fmt);
    await sleep(200);
    await page.click('button.export');
    if (modal === 'info') {
      await page.waitForSelector('[data-testid=export-info-overlay]', { timeout: 15_000 });
      await page.waitForSelector('.export-ro-row', { timeout: 15_000 });
      await page.click('[data-testid=export-info-confirm]');
    } else {
      await page.waitForSelector('[data-testid=save-name-overlay]', { timeout: 15_000 });
      await page.click('[data-testid=save-name-confirm]');
    }
    let capd = null;
    const t0 = Date.now();
    while (Date.now() - t0 < 60_000) {
      const caps = await page.evaluate(() => window.__exportCaps || []);
      if (caps.length > before) { capd = caps[caps.length - 1]; break; }
      await sleep(500);
    }
    return capd;
  };
  const saveCap = (capd, name) => {
    const buf = Buffer.from(capd.b64 || '', 'base64');
    writeFileSync(resolve(exportDir, name), buf);
    return buf;
  };

  // PLT-clean：唛架净版（PU/PD 笔画 + PS_ 哨兵零泄漏）
  const cPlt = await exportOnce('plt-clean', 'info');
  check('P2f-1 导出 PLT-clean 200（.plt 附件）', !!cPlt && cPlt.status === 200
    && decodeURIComponent(cPlt.cd || '').includes('.plt'), cPlt ? cPlt.cd : 'no capture');
  const pltBuf = cPlt ? saveCap(cPlt, 'freeze_smoke.plt') : Buffer.alloc(0);
  const pltTxt = pltBuf.toString('latin1');
  check('P2f-2 PLT 正文在案（PU 笔 ≥100）+ PS_ 组合片零泄漏',
    (pltTxt.match(/^PU/gm) || []).length >= 100 && pltBuf.length > 10_000 && !pltTxt.includes('PS_'),
    'bytes=' + pltBuf.length + ' PU=' + (pltTxt.match(/^PU/gm) || []).length);

  // DXF：R12 + POLYLINE 红线（ET2008 兼容，非 LWPOLYLINE）
  const cDxf = await exportOnce('dxf', 'name');
  check('P2g-1 导出 DXF 200（.dxf 附件）', !!cDxf && cDxf.status === 200
    && decodeURIComponent(cDxf.cd || '').includes('.dxf'), cDxf ? cDxf.cd : 'no capture');
  const dxfBuf = cDxf ? saveCap(cDxf, 'freeze_smoke.dxf') : Buffer.alloc(0);
  const dxfTxt = dxfBuf.toString('latin1');
  check('P2g-2 DXF = R12 POLYLINE（AC1009）无 LWPOLYLINE',
    dxfTxt.includes('AC1009') && dxfTxt.includes('POLYLINE') && !dxfTxt.includes('LWPOLYLINE'),
    'bytes=' + dxfBuf.length);

  // PNG：matplotlib 渲染路径（冻结捆绑字体/数据）
  const cPng = await exportOnce('png', 'name');
  check('P2h-1 导出 PNG 200（.png 附件）', !!cPng && cPng.status === 200
    && decodeURIComponent(cPng.cd || '').includes('.png'), cPng ? cPng.cd : 'no capture');
  const pngBuf = cPng ? saveCap(cPng, 'freeze_smoke.png') : Buffer.alloc(0);
  check('P2h-2 PNG 魔数 + 正文在案（matplotlib 路径）',
    pngBuf.length > 10_000 && pngBuf[0] === 0x89 && pngBuf[1] === 0x50 && pngBuf[2] === 0x4e && pngBuf[3] === 0x47,
    'bytes=' + pngBuf.length);

  // 状态保存 .msn：下载事件 → Node gunzip → schema 断言
  const dlP = page.waitForEvent('download', { timeout: 30_000 }).then((d) => d).catch(() => null);
  await page.click('[data-testid=save-state-btn]');
  await page.waitForSelector('[data-testid=save-name-overlay]', { timeout: 5_000 });
  await page.click('[data-testid=save-name-confirm]');
  const dl = await dlP;
  const msnPath = resolve(exportDir, 'freeze_smoke.msn');
  let msn = {};
  if (dl) {
    await dl.saveAs(msnPath);
    try { msn = JSON.parse(gunzipSync(readFileSync(msnPath)).toString('utf8')); } catch { msn = {}; }
  }
  check('P2i-1 保存 .msn 下载（附件 .msn）', !!dl && dl.suggestedFilename().endsWith('.msn'),
    dl ? dl.suggestedFilename() : 'no download');
  check('P2i-2 .msn gunzip schema（schema_version=1/app/doc/form/quantities/run）',
    msn.schema_version === 1 && msn.app === 'materialsorting'
    && ['doc', 'form', 'quantities', 'run'].every((k) => k in msn),
    'keys=' + Object.keys(msn).join(','));
  check(`P2i-3 .msn run.placed = 末帧守恒（${EXPECT_PLACED}）`,
    Array.isArray(msn.run?.placed) && msn.run.placed.length === EXPECT_PLACED,
    'len=' + (msn.run?.placed || []).length);

  // ---- P3 高级运行专项：冻结 spawn exe --cli 链路 + run_dir 落临时 OUT_DIR ----
  log('P3 高级运行：strategy race（冻结 spawn exe --cli）');
  const baseCount = await waitExeCount(1, 60_000);
  check('P3a 基线 exe 进程数 = 1（核心动线收敛后）', baseCount === 1, 'count=' + baseCount);
  const hdr = { 'Content-Type': 'application/json', 'X-Session-Id': sid };
  const startRes = await rawFetch(page, '/api/strategy/start', {
    method: 'POST', headers: hdr,
    body: JSON.stringify({ mode: 'race', minutes: 10, sizes: SIZES, seed: 0 }),
  });
  check('P3b /api/strategy/start 202（mode=race）', startRes.status === 202, 'status=' + startRes.status);

  const statusGet = () => rawFetch(page, '/api/strategy/status', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
  let st = null, runDir = null;
  const tRun = Date.now();
  while (Date.now() - tRun < 180_000) {
    const s = await statusGet();
    if (s.body && s.body.state && s.body.state !== 'starting') { st = s.body; runDir = s.body.run_dir || null; break; }
    await sleep(2000);
  }
  const cfgRunsDir = resolve(MS_OUT_DIR, 'config_runs');
  check('P3c run 进入 running', st?.state === 'running' || st?.state === 'done', 'state=' + (st?.state ?? 'timeout'));
  check('P3d run_dir 落临时 OUT_DIR config_runs/web_*（AC2-4）',
    !!runDir && runDir.replace(/\\/g, '/').startsWith(toFwd(cfgRunsDir) + '/')
    && (runDir.split(/[\\/]/).pop() || '').startsWith('web_') && existsSync(runDir),
    'run_dir=' + runDir);

  // best_frame 出帧（子进程真实求解证据；race 首 seed 数秒级出首帧）
  let best = null;
  const tBest = Date.now();
  while (Date.now() - tBest < 240_000) {
    const s = await statusGet();
    if (s.body?.current) { best = s.body.current; break; }
    if (s.body && ['done', 'error', 'stopped'].includes(s.body.state)) { st = s.body; break; }
    await sleep(3000);
  }
  check('P3e best_frame 出帧（冻结子进程真实求解）', !!best && typeof best.density === 'number',
    best ? `seed=${best.seed} density=${(best.density * 100).toFixed(2)}%` : 'no best_frame in 240s');

  const runCount = exeProcs();
  check('P3f 运行中 exe 进程数 ≥2（冻结 spawn exe --cli 链路）', runCount >= 2, 'count=' + runCount);

  const stopRes = await rawFetch(page, '/api/strategy/stop', { method: 'POST', headers: hdr });
  check('P3g stop 停止（stopped=true）', stopRes.status === 200 && stopRes.body?.stopped === true,
    'status=' + stopRes.status);
  let stoppedState = null;
  const tStop = Date.now();
  while (Date.now() - tStop < 60_000) {
    const s = await statusGet();
    stoppedState = s.body?.state;
    if (stoppedState === 'stopped' || stoppedState === 'done') break;
    await sleep(1500);
  }
  const afterCount = await waitExeCount(1, 90_000);
  check('P3h stop 收敛（state=stopped/done + 进程数回落 1）',
    (stoppedState === 'stopped' || stoppedState === 'done') && afterCount === 1,
    'state=' + stoppedState + ' count=' + afterCount);
  report.advanced = { run_dir: runDir, best: best ?? null, run_count: runCount,
    stop_state: stoppedState, after_count: afterCount };

  await context.close();
  await browser.close();
  browser = null;

  // ---- P4 既有 smoke 族复跑（可选：SMOKE_BASE_URL 指向冻结实例）---------------
  if (RERUN_FAMILY) {
    log('P4 既有 smoke 族复跑（SMOKE_BASE_URL=' + BASE + '）');
    const famEnv = {
      ...process.env,
      SMOKE_BASE_URL: BASE,
      SMOKE_PREFIX_RUNS: resolve(MS_OUT_DIR, 'prefix_runs'),
    };
    const scriptsFam = [
      'smoke_prefix_extra.mjs',
      'smoke_state_file.mjs',
      'smoke_edit_polish.mjs',
    ].map((f) => resolve(ROOT, 'materialSorting-web/scripts', f));
    for (const sc of scriptsFam) {
      const rc = await new Promise((res) => {
        const c = spawn(process.execPath, [sc], { env: famEnv, stdio: 'inherit' });
        const killer = setTimeout(() => { try { c.kill(); } catch {} }, 900_000);
        c.once('exit', (code) => { clearTimeout(killer); res(code); });
      });
      check(`P4 既有 smoke 复跑：${sc.split(/[\\/]/).pop()} exit 0`, rc === 0, 'exit=' + rc);
    }
  }

  // ---- P5 单实例专项：二次启动 exit 0 / 进程数不增 / 浏览器 URL 指向既有端口 --
  log('P5 单实例：二次启动');
  const linesBefore = browserLogLines().length;
  const countBefore = exeProcs();
  const second = await new Promise((res) => {
    const c = spawn(EXE, [], { cwd: DIST_APP_DIR, env: childEnv(), stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    c.stdout.on('data', (d) => { out += d.toString('utf8'); });
    c.stderr.on('data', (d) => { out += d.toString('utf8'); });
    const killer = setTimeout(() => { try { c.kill(); } catch {} }, 90_000);
    c.once('exit', (code) => { clearTimeout(killer); res({ code, out }); });
  });
  await sleep(1500);   // 等 cmd echo 落日志
  const linesAfter = browserLogLines();
  const newUrls = linesAfter.slice(linesBefore).map((l) => l.trim());
  const countAfter = exeProcs();
  check('P5a 二次启动 exit 0（不起服务直接返回）', second.code === 0, 'exit=' + second.code);
  check(`P5b stdout 单实例提示 + URL 指向既有端口 ${BASE}`,
    second.out.includes('检测到已在运行的实例') && second.out.includes(BASE),
    second.out.split(/\r?\n/).filter((l) => l.includes('实例')).join(' | ').slice(0, 160));
  check(`P5c webbrowser.open 实调 URL = 既有端口（BROWSER 捕获新增 ${newUrls.length} 行）`,
    newUrls.some((u) => u === BASE), 'urls=' + JSON.stringify(newUrls));
  check(`P5d MaterialSorting.exe 进程数不增（${countBefore} → ${countAfter}）`,
    countAfter === countBefore && countBefore === 1, `${countBefore} -> ${countAfter}`);
  check('P5e 首实例仍健康（二次启动不扰动服务）', await httpOk(EXPECT_PORT));
  report.single = { exit: second.code, urls: newUrls, count_before: countBefore, count_after: countAfter };

  // ---- P6 数据落点专项：产物全落临时 OUT_DIR + dist 安装目录零变化 ------------
  log('P6 数据落点：临时 OUT_DIR 产物清点 + dist 只读安全对拍');
  const uploads = existsSync(resolve(MS_OUT_DIR, 'uploads'))
    ? readdirSync(resolve(MS_OUT_DIR, 'uploads')).filter((f) => f.toLowerCase().endsWith('.dxf')) : [];
  check('P6a 上传母版落临时 OUT_DIR（uploads/*.dxf ≥1）', uploads.length >= 1,
    'uploads=' + uploads.length + ' 例：' + uploads.slice(0, 3).join(','));
  const inter = resolve(MS_OUT_DIR, 'sparrow_baseline/pieces_intermediate.json');
  check('P6b intermediate 落临时 OUT_DIR（commit 双写镜像）', existsSync(inter));
  const cfgRuns = existsSync(cfgRunsDir)
    ? readdirSync(cfgRunsDir).filter((f) => f.startsWith('web_')) : [];
  check('P6c 高级运行产物 config_runs/web_* 落临时 OUT_DIR', cfgRuns.length >= 1,
    'web_*=' + cfgRuns.length + ' 例：' + cfgRuns.slice(0, 2).join(','));
  const prefixRuns = existsSync(resolve(MS_OUT_DIR, 'prefix_runs'))
    ? readdirSync(resolve(MS_OUT_DIR, 'prefix_runs')).length : 0;
  if (RERUN_FAMILY) {
    check('P6d prefix_runs 工件落临时 OUT_DIR（smoke 族复跑侧证）', prefixRuns > 0, 'files=' + prefixRuns);
  }
  check('P6e web_port.txt 落临时 OUT_DIR', existsSync(portFile));

  const distSnap1 = treeSnapshot(DIST_APP_DIR);
  const exeHash1 = sha256File(EXE);
  const changed = [];
  for (const [k, v] of distSnap0) {
    const v1 = distSnap1.get(k);
    if (!v1 || v1.size !== v.size || v1.mtimeMs !== v.mtimeMs) changed.push(k);
  }
  for (const k of distSnap1.keys()) if (!distSnap0.has(k)) changed.push('+' + k);
  check(`P6f dist 安装目录零变化（${distSnap0.size} 文件 stat 全等，只读安全）`,
    changed.length === 0, changed.slice(0, 5).join(', '));
  check('P6g dist exe sha256 前后一致', exeHash0 === exeHash1, exeHash0.slice(0, 12) + '..');
  report.data = { uploads: uploads.length, intermediate: existsSync(inter),
    config_runs_web: cfgRuns.length, prefix_runs: prefixRuns,
    dist_files: distSnap0.size, dist_changed: changed.slice(0, 10), exe_sha256: exeHash0.slice(0, 16) };
} catch (e) {
  console.error('\nHARNESS-ERR:', e && e.stack ? e.stack.split(/\r?\n/).slice(0, 6).join('\n') : e);
  check('HARNESS 无异常', false, String((e && e.message) || e));
} finally {
  // ---- 清理：杀冻结实例树 + 关浏览器 + 放 8010；临时 OUT_DIR 成功才删 ----------
  if (browser) { try { await browser.close(); } catch {} }
  killServer();
  if (dummy8010) { try { dummy8010.close(); } catch {} }
  const failed = results.filter((r) => !r.ok);
  const okN = results.length - failed.length;
  report.pass = failed.length === 0;
  report.checks_total = results.length;
  writeFileSync(resolve(OUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log('');
  if (failed.length) {
    console.log('失败项：');
    for (const f of failed) console.log(`  FAIL  ${f.name}${f.detail ? '  -- ' + f.detail.slice(0, 200) : ''}`);
  }
  if (report.pass && !KEEP) {
    rmSync(MS_OUT_DIR, { recursive: true, force: true });
  } else if (!KEEP) {
    console.log(`（失败保留诊断目录：${MS_OUT_DIR}；服务日志 ${SERVER_LOG}）`);
  }
  console.log(`==== smoke_freeze: ${okN}/${results.length} PASS | report -> ${resolve(OUT, 'report.json')} ====`);
  process.exit(failed.length ? 1 : 0);
}

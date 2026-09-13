// US-002 浏览器验证（一次性脚本，不入 vitest）：pending_strategy_result 槽全链 ——
// 离线铸造带槽 .msn（真实 commit intermediate + build_state_document）→ 上传恢复 →
// 弹窗自动开在结果态 →（自动 checkpoint 携槽）→ 空闲过期 → 刷新启动期恢复 → 弹窗
// 重现（密度对拍）→ 应用 → 布局 polygon 数对拍 + 来源小字 → PLT 导出 placed 逐条对拍。
//
// 前置：materialSorting-web/static 为 npm run build 产物（脚本自行校验）。
// 自举起服 :8020（避开常驻 :8000 与冒烟 :8010），MS_SESSION_TTL_SEC=60；退出树杀。
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/us002_pending_verify';
mkdirSync(OUT, { recursive: true });

const PORT = 8020;
const BASE = 'http://127.0.0.1:' + PORT;
const PY = ROOT + '/.venv/Scripts/python.exe';
const DXF = ROOT + '/data/5336#老六订单14%7%围加9_coded.dxf';
const MSN = OUT + '/pending_race.msn';
const SIZE = 30;                 // 槽 placed 取 30 码全集（demand 全 1）
const TTL_IDLE_MS = 75_000;      // > MS_SESSION_TTL_SEC=60

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: !!ok, detail });
  console.log((ok ? 'PASS' : 'FAIL') + ' | ' + name + (detail ? ' | ' + detail : ''));
}
function log(msg) { console.log('-- ' + msg); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!existsSync(ROOT + '/materialSorting-web/static/index.html')) {
  console.error('缺少 static/index.html —— 先 cd materialSorting-web && npm run build');
  process.exit(2);
}
try {
  const probe = await fetch(BASE + '/', { signal: AbortSignal.timeout(1500) });
  if (probe.ok) { console.error('端口 ' + PORT + ' 被占用（疑似残留服务）'); process.exit(2); }
} catch { /* 未占用 = 正常 */ }

// ---------------------------------------------------------------- 起服
const SERVER_LOG = [];
const server = spawn(PY, ['-c',
  'import uvicorn; from materialsorting.web.server import app; '
  + 'uvicorn.run(app, host="127.0.0.1", port=' + PORT + ')'], {
  cwd: ROOT,
  env: { ...process.env, MS_SESSION_TTL_SEC: '60', MS_EDIT_HOLD_SEC: '5' },
  windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
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
    console.error('起服失败：\n' + SERVER_LOG.join('').slice(-2000));
    killServer(); process.exit(2);
  }
}
log('服务就绪 ' + BASE);

// ---------------------------------------------------------------- Phase 1：HTTP commit（真实 intermediate）
const sidA = 'a'.repeat(32);
const fd = new FormData();
fd.append('file', new Blob([readFileSync(DXF)]), '5336_coded.dxf');
const parseR = await fetch(BASE + '/api/parse-dxf', {
  method: 'POST', body: fd, headers: { 'X-Session-Id': sidA },
});
check('P1a POST /api/parse-dxf 200', parseR.ok, 'status=' + parseR.status);
const parseBody = await parseR.json();
check('P1b 拿到 doc_id', typeof parseBody.doc_id === 'string' && parseBody.doc_id.length > 0,
  String(parseBody.doc_id));
const commitR = await fetch(BASE + '/api/commit-to-nesting', {
  method: 'POST', body: JSON.stringify({ doc_id: parseBody.doc_id }),
  headers: { 'Content-Type': 'application/json', 'X-Session-Id': sidA },
});
check('P1c POST /api/commit-to-nesting 200', commitR.ok, 'status=' + commitR.status);
log('commit 完成');

// ---------------------------------------------------------------- Phase 2：Python 铸造带槽 .msn
const CRAFTER = [
  'import json',
  'from materialsorting import paths',
  'from materialsorting.web.statefile import (build_state_document,',
  '    serialize_state, expected_demand_map)',
  '',
  'doc = json.load(open(paths.INTERMEDIATE, encoding="utf-8"))',
  'pieces = doc["pieces"]',
  'sizes = [' + SIZE + ']',
  'demand = expected_demand_map(pieces, sizes=sizes)',
  'by_pid = {p["pid"]: p for p in pieces}',
  'placed, cursor, gap = [], 0.0, 20.0',
  'for i, pid in enumerate(sorted(demand)):',
  '    b = by_pid[pid]["bbox"]',
  '    w = (b[2] - b[0]) or 300.0',
  '    item = {"id": pid, "rotation": 0, "translation": [round(cursor, 2), 0.0]}',
  '    if i % 2 == 1:',
  '        item["mirror"] = True',
  '    placed.append(item)',
  '    cursor += w + gap',
  'gate = float(doc["gate_mm"])',
  'width = round(cursor, 2)',
  'area = sum(by_pid[pid]["area_mm2"] for pid in demand)',
  'density = round(area / (width * gate), 6)',
  'pending = {',
  '    "mode": "race",',
  '    "best": {"seed": 7, "frame_index": 42, "elapsed": 311.2,',
  '             "density": density, "density_sparrow": round(density + 0.012, 6),',
  '             "width_mm": width, "placed_items": placed},',
  '    "summary": {"per_seed": [',
  '                    {"seed": 0, "killed": True, "kill_reason": "gate",',
  '                     "best_density": 0.5, "elapsed": 90, "phase": "race"},',
  '                    {"seed": 7, "killed": False, "kill_reason": None,',
  '                     "best_density": density, "elapsed": 311.2, "phase": "extension"}],',
  '                "mode": "race",',
  '                "race": {"gate_seconds": 90, "kept_seeds": [7],',
  '                         "gated_seeds": [0, 1, 2, 3, 4, 5, 6]}},',
  '}',
  'form = {"sizes": [' + SIZE + '], "gate": "%.2f" % (gate / 10.0), "time": "60", "seed": "0",',
  '        "multi_seed": False, "seed_count": "3", "per_type": {},',
  '        "band_enabled": False, "band_label": "", "prefix_enabled": False,',
  '        "prefix_front": "", "prefix_back": ""}',
  'document = build_state_document({"doc": doc}, form, None, None, None, pending)',
  'import sys',
  'out = sys.argv[1]',
  'open(out, "wb").write(serialize_state(document))',
  'print(json.dumps({"count": len(placed), "density": density, "width_mm": width,',
  '                  "gate_mm": gate, "pid0": placed[0]["id"]}))',
].join('\n');
const craft = spawnSync(PY, ['-c', CRAFTER, MSN], { cwd: ROOT, encoding: 'utf-8', windowsHide: true });
if (craft.status !== 0) {
  console.error('铸造 .msn 失败：\n' + String(craft.stderr));
  killServer(); process.exit(2);
}
const msnMeta = JSON.parse(craft.stdout.trim().split('\n').pop());
writeFileSync(OUT + '/msn_meta.json', JSON.stringify(msnMeta, null, 2));
const DENSITY_PCT = (msnMeta.density * 100).toFixed(2) + '%';
log('msn 铸造：' + JSON.stringify(msnMeta) + ' → 期望密度文案 ' + DENSITY_PCT);
check('P2a .msn 铸造（placed=' + msnMeta.count + ' 条）', msnMeta.count > 0);

// ---------------------------------------------------------------- 浏览器
const { chromium } = await import('playwright');
let browser;
try { browser = await chromium.launch({ channel: 'msedge' }); }
catch { browser = await chromium.launch({ channel: 'chrome' }); }

const NET_SPY = () => {
  window.__t0 = Date.now();
  window.__netLog = [];
  const orig = window.fetch;
  window.fetch = async function (...args) {
    const url = String(args[0]);
    if (url.includes('/api/')) {
      const init = args[1] || {};
      const h = init.headers || {};
      const entry = { t: Math.round((Date.now() - window.__t0) / 1000), url,
        method: init.method || 'GET',
        sid: h['X-Session-Id'] || h['x-session-id'] || null,
        body: typeof init.body === 'string' ? init.body : null };
      window.__netLog.push(entry);
      const res = await orig.apply(this, args);
      entry.status = res.status;
      if (url.includes('/api/state-checkpoint') || url.includes('/api/state-recover')) {
        try { entry.resp = await res.clone().json(); } catch { entry.resp = null; }
      }
      return res;
    }
    return orig.apply(this, args);
  };
};

async function netLog(p) { return p.evaluate(() => window.__netLog || []); }
async function getSid(p) { return p.evaluate(() => localStorage.getItem('ms_sid')); }
async function toasts(p) {
  return p.evaluate(() => Array.from(document.querySelectorAll('.toast-msg')).map((t) => t.textContent));
}
async function waitCheckpoint(p, pred, timeoutMs = 12000) {
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

try {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await ctx.addInitScript(() => {
    localStorage.setItem('ms.tour.version', '8');
    localStorage.setItem('ms.tour.seen.preview', '1');
    localStorage.setItem('ms.tour.seen.nesting', '1');
  });
  await ctx.addInitScript(NET_SPY);
  const page = await ctx.newPage();

  // ---------------- Phase 3：上传 .msn → 恢复 → 弹窗自动开在结果态
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const sidB = await getSid(page);
  await page.locator('input[type=file]').first().setInputFiles(MSN);
  await page.waitForSelector('[data-testid="strategy-overlay"]', { timeout: 30000 });
  const headText = (await page.locator('[data-testid="strategy-result-head"]').innerText()).trim();
  check('P3a .msn 恢复 → 高级运行弹窗自动打开且为结果态（完成 · 最优 ' + DENSITY_PCT + '）',
    headText === '完成 · 最优 ' + DENSITY_PCT, headText);
  const detailText = (await page.locator('[data-testid="strategy-result-detail"]').first().innerText()).trim();
  check('P3b 结果详情 seed 7 · 用布 ' + (msnMeta.width_mm / 10).toFixed(2) + ' cm',
    detailText.includes('seed 7') && detailText.includes((msnMeta.width_mm / 10).toFixed(2) + ' cm'),
    detailText);
  const modeText = (await page.locator('[data-testid="strategy-mode-summary"]').innerText()).trim();
  check('P3c race 门杀文案渲染（race 模式子段回显）',
    modeText.startsWith('race：') && modeText.includes('门杀'), modeText);
  check('P3d .msn 恢复 toast', (await toasts(page)).some((t) => t.startsWith('状态文件已恢复：')),
    JSON.stringify(await toasts(page)));
  await page.screenshot({ path: OUT + '/p3_restored_modal.png' });

  // US-002 触发面 #4：done 结果落定（恢复写回同触发）→ 立即 checkpoint 携槽
  const cp = await waitCheckpoint(page, (x) => {
    try { return x.body && JSON.parse(x.body).pending_strategy_result !== undefined; } catch { return false; }
  });
  check('P3e 自动 checkpoint 携 pending_strategy_result 且 stored:true（US-001 后端入槽）',
    !!cp && cp.status === 200 && cp.resp && cp.resp.stored === true,
    cp ? JSON.stringify(cp.resp) : 'no checkpoint');
  const cpBody = cp ? JSON.parse(cp.body) : {};
  check('P3f 槽形态：mode=race / placed 条数=' + msnMeta.count + ' / best 数值键齐',
    cpBody.pending_strategy_result?.mode === 'race'
      && cpBody.pending_strategy_result?.best?.placed_items?.length === msnMeta.count
      && typeof cpBody.pending_strategy_result?.best?.density === 'number'
      && typeof cpBody.pending_strategy_result?.best?.width_mm === 'number',
    'placed=' + cpBody.pending_strategy_result?.best?.placed_items?.length);

  // ---------------- Phase 4：空闲过期 → 刷新 → 启动期恢复 → 弹窗重现
  log('P4 空闲 ' + TTL_IDLE_MS + 'ms 等 TTL 过期…');
  await sleep(TTL_IDLE_MS);
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(1500); // 恢复编排 + toast 渲染
  const sidC = await getSid(page);
  check('P4a 刷新后 sid 换新（B→C，恢复链）', !!sidC && sidC !== sidB, (sidC || '').slice(0, 8));
  const net = await netLog(page);
  const rec = net.find((x) => x.url.includes('/api/state-recover'));
  check('P4b POST /api/state-recover 200（from_sid=旧B）',
    !!rec && rec.status === 200 && JSON.parse(rec.body || '{}').from_sid === sidB,
    rec ? 'status=' + rec.status : 'no call');
  check('P4c 恢复 toast（工作状态已恢复）', (await toasts(page)).includes('工作状态已恢复'));
  await page.waitForSelector('[data-testid="strategy-overlay"]', { timeout: 15000 });
  const headText2 = (await page.locator('[data-testid="strategy-result-head"]').innerText()).trim();
  check('P4d 过期恢复后弹窗重现结果态（密度与过期前对拍 ' + DENSITY_PCT + '）',
    headText2 === '完成 · 最优 ' + DENSITY_PCT, headText2);
  await page.screenshot({ path: OUT + '/p4_recovered_modal.png' });
  // 恢复态重落 checkpoint（自我延续）：携槽
  const cp2 = await waitCheckpoint(page, (x) => {
    try { return JSON.parse(x.body || '{}').pending_strategy_result !== undefined; } catch { return false; }
  });
  check('P4e 恢复态重落 checkpoint（携槽，新会话自我延续）',
    !!cp2 && cp2.status === 200 && cp2.resp && cp2.resp.stored === true,
    cp2 ? 'sid=' + String(cp2.sid).slice(0, 8) : 'no checkpoint');

  // ---------------- Phase 5：应用 → 布局渲染 → PLT 导出 placed 逐条对拍
  await page.click('[data-testid="strategy-apply-btn"]');
  await sleep(800);
  // 应用不自动关弹窗（显式按钮语义）—— 手动关闭后进超排 Tab 看布局
  await page.click('[data-testid="strategy-close"]');
  await page.locator('button.tab:not([disabled]):has-text("超排")').click();
  await page.locator('.nest-label').first().waitFor({ timeout: 15000 });
  await sleep(500);
  const polygons = await page.locator('.nest-card svg polygon[data-label]').count();
  check('P5a 应用后主画布 polygon 数 = 槽 placed 条数（' + msnMeta.count + '）',
    polygons === msnMeta.count, 'polygons=' + polygons);
  const statusLine = (await page.locator('#status').first()
    .innerText().catch(() => '')).trim();
  check('P5b 状态行「策略 run 已应用 · seed 7」',
    statusLine.includes('策略 run 已应用') && statusLine.includes('seed 7'), statusLine);
  const prov = (await page.locator('.provenance-line, [data-testid="run-provenance"]').first()
    .innerText().catch(() => '')).trim();
  check('P5c 来源小字（策略运行 · seed 7）',
    prov.includes('策略运行') && prov.includes('seed 7'), prov);
  await page.screenshot({ path: OUT + '/p5_applied_layout.png' });

  // PLT 导出（export-info 弹窗确认）→ 抓 POST /export 载荷 placed
  const capExport = page.waitForResponse((r) => r.url().endsWith('/export'), { timeout: 30000 });
  await page.selectOption('select.export-fmt', 'plt');
  await page.click('button.export');
  await page.waitForSelector('[data-testid="export-info-overlay"]', { timeout: 15000 });
  await page.click('[data-testid="export-info-confirm"]');
  const expResp = await capExport;
  check('P5d POST /export 200', expResp.status() === 200, 'status=' + expResp.status());
  let expBody = null;
  try { expBody = expResp.request().postDataJSON(); } catch { expBody = null; }
  const msnPlaced = cpBody.pending_strategy_result.best.placed_items;
  const norm = (items) => JSON.parse(JSON.stringify(items));
  check('P5e 导出 placed 与待确认结果逐条一致（translation/rotation/mirror）',
    !!expBody && Array.isArray(expBody.placed) && expBody.placed.length === msnPlaced.length
      && JSON.stringify(norm(expBody.placed)) === JSON.stringify(norm(msnPlaced)),
    'export=' + expBody?.placed?.length + ' msn=' + msnPlaced?.length);

  // 应用后 checkpoint：pending 槽退场、run 块承载（无双份数据）
  const cp3 = await waitCheckpoint(page, (x) => {
    try { return JSON.parse(x.body || '{}').run !== undefined; } catch { return false; }
  });
  const cp3Body = cp3 ? JSON.parse(cp3.body) : {};
  check('P5f 应用后 checkpoint：run 块在场且 pending 槽退场（无双份数据）',
    !!cp3 && cp3Body.run !== undefined && cp3Body.pending_strategy_result === undefined,
    'run.seed=' + cp3Body.run?.seed);
} catch (e) {
  check('脚本执行异常', false, String((e && e.stack) || e));
} finally {
  try { await browser.close(); } catch { /* 尽力 */ }
  killServer();
  await sleep(800);
}

writeFileSync(OUT + '/report.json', JSON.stringify({
  at: new Date().toISOString(), results,
  passed: results.filter((r) => r.ok).length, failed: results.filter((r) => !r.ok).length,
}, null, 2));
log('报告 → ' + OUT + '/report.json');
const failed = results.filter((r) => !r.ok).length;
console.log(failed === 0 ? 'ALL PASS (' + results.length + ')' : 'FAILED ' + failed + '/' + results.length);
process.exit(failed === 0 ? 0 : 1);


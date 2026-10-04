// prd-initial-layout US-007（2026-10-04）端到端 UI 冒烟 —— 普通运行接线 + warm_state
// 回报 + stale 降级。模板 = us006_il_modal_verify.mjs（弹窗编排/拖片/伪卡片）+
// smoke_edit_polish.mjs（playwright Edge 通道 + WS 抓包 waitMsg）。
//
// 前置：ms-web 在 $SMOKE_BASE_URL（缺省 http://127.0.0.1:8010，prod 模式需先
// npm run build）；data/ 样例母版在案（sample-apply 走真实 parse+commit 管线，
// sample 标记免 key 闸门）。产物 out/smoke_initial_layout/{report.json, *.png}；
// 退出码 0 = 全部检查 PASS。
//
// 相位（PRD 验收）：
//   P plain 主线：5336 样例 → 3 码 → 弹窗自动生成（seed=0）→ 拖一片 → 保存 →
//     伪卡片 + chip「将基于初始布局运行」+ 附注「仅普通运行生效」→ 普通运行
//     （time=30，start 载荷带 initial）→ **首帧 width == 保存料长（delta≤1mm）+
//     首帧 density ≈ 保存利用率（delta≤0.005）** → final warm_state.engaged=true
//     → 状态行「已从初始布局热启动」；
//   S stale：预览页改数量（g01@32 1→2）→ chip「初始布局已失效（参数已变更）」
//     → 再运行 start 载荷**无 initial 键** + 帧流照常（≥1 帧）→ 停止收场；
//   B band 变体：band g05 开 → 弹窗自动生成（组合宇宙，composite 含 WB_）→
//     组拖（g05 整组同位移 + 非成员不动）→ 保存 → chip fresh → 运行 →
//     final warm_state.engaged=true。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/smoke_initial_layout';
mkdirSync(OUT, { recursive: true });

const BASE = (process.env.SMOKE_BASE_URL || 'http://127.0.0.1:8010').replace(/\/+$/, '');
const SAMPLE = '5336#老六订单14%7%围加9.dxf';
const SIZES = [32, 33, 34];
const SOLVE_TIME = '30';

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

// ---- 抓包：WS 双向（start 载荷 / manifest·frame·final）+ 生成请求/响应 ----
function frameText(f) {
  if (typeof f === 'string') return f;
  if (f && typeof f.payload === 'string') return f.payload;
  if (f && f.payload != null && typeof f.payload === 'object')
    return String.fromCharCode(...f.payload);
  return '';
}
const conns = []; // 每个 /ws/solve 连接：{ sent: [], received: [] }
page.on('websocket', (ws) => {
  if (!ws.url().includes('/ws/solve')) return;
  const rec = { sent: [], received: [] };
  conns.push(rec);
  ws.on('framesent', (f) => {
    try { rec.sent.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
  });
  ws.on('framereceived', (f) => {
    try { rec.received.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
  });
});
const genReqs = [];
const genResps = [];
page.on('request', (req) => {
  if (req.url().includes('/api/initial-layout/generate')) {
    let seed = null;
    try { seed = JSON.parse(req.postData() ?? '{}').seed ?? null; } catch { /* ignore */ }
    genReqs.push({ seed });
  }
});
page.on('response', async (resp) => {
  if (resp.url().includes('/api/initial-layout/generate')) {
    try { genResps.push(await resp.json()); } catch { /* ignore */ }
  }
});

const OVERLAY = '[data-testid="initial-layout-overlay"]';

async function gotoNesting() {
  await page.locator('[data-testid="sample-select"]').selectOption(SAMPLE);
  await page.locator('[data-testid="sample-apply"]').click();
  await page.waitForFunction(() => {
    const els = document.querySelectorAll('[data-testid="commit-status"]');
    return Array.from(els).some((e) => e.textContent && e.textContent.includes('已应用至超排'));
  }, null, { timeout: 90000 });
  await page.locator('button.tab', { hasText: '超排' }).click();
  await page.locator('[data-testid="initial-layout-btn"]').waitFor({ state: 'visible', timeout: 8000 });
  await sleep(300);
}

/** 画布片落场等待（生成 ~10s + 子进程启停余量）。 */
async function waitCanvas(timeoutMs = 45000) {
  await page.waitForFunction(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    return svg != null && svg.querySelectorAll(':scope g > polygon').length > 0;
  }, null, { timeout: timeoutMs });
}

/** 弹窗打开 → busy 起落 + 画布落场（自动生成完整周期）。 */
async function openAndGenerate() {
  await page.locator('[data-testid="initial-layout-btn"]').click();
  await page.locator(OVERLAY).waitFor({ state: 'visible', timeout: 5000 });
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'visible', timeout: 6000 });
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'hidden', timeout: 45000 });
  await waitCanvas(5000);
  await sleep(400); // EditCanvas 首帧计数/组标记回填
}

/** 画布片 idx 屏幕中心。 */
async function pieceInfo(idx) {
  return page.evaluate((i) => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    const polys = svg.querySelectorAll(':scope g > polygon');
    const pr = polys[i].getBoundingClientRect();
    return { cx: pr.x + pr.width / 2, cy: pr.y + pr.height / 2, n: polys.length };
  }, idx);
}

/** 屏幕像素直拖（片 idx → (tx,ty) 屏幕坐标）。 */
async function dragTo(idx, tx, ty) {
  const info = await pieceInfo(idx);
  await page.mouse.move(info.cx, info.cy);
  await page.mouse.down();
  await page.mouse.move(tx, ty, { steps: 8 });
  await sleep(60);
  await page.mouse.up();
  await sleep(150);
}

/** 画布最右片下标（max x1 —— 右移恒不产生重叠：所有其余片 x1 ≤ 其旧 x1）。 */
async function rightmostIdx() {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    const polys = Array.from(svg.querySelectorAll(':scope g > polygon'));
    let best = -1;
    let bestX1 = -Infinity;
    polys.forEach((p, i) => {
      const r = p.getBoundingClientRect();
      if (r.right > bestX1) {
        bestX1 = r.right;
        best = i;
      }
    });
    return best;
  });
}

/** 重生成等待：busy 浮层先起后落完整周期 + 画布片在场（us006 同款防竞态）。 */
async function waitRegen(timeoutMs = 45000) {
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'visible', timeout: 8000 });
  await page.locator('[data-testid="initial-layout-generating"]').waitFor({ state: 'hidden', timeout: timeoutMs });
  await waitCanvas(5000);
  await sleep(300);
}

/** 保存 → 弹窗关闭 + 伪卡片挂载（label 文本 + 状态条读数返回）。
 *  伪卡片检索扫全部 .nest-label（B 相位时网格已含 P/S 阶段 run 卡片，
 *  querySelector 首个命中可能是普通 run 卡 —— P3 期网格尚空所以首查即中）。 */
async function saveLayout() {
  const widthText = ((await page.locator('[data-testid="initial-layout-width"]').textContent()) ?? '').trim();
  const densityText = ((await page.locator('[data-testid="initial-layout-density"]').textContent()) ?? '').trim();
  await page.locator('[data-testid="initial-layout-save"]').click();
  await page.locator(OVERLAY).waitFor({ state: 'hidden', timeout: 5000 });
  await page.waitForFunction(() => {
    return Array.from(document.querySelectorAll('.nest-label')).some(
      (el) => (el.textContent ?? '').includes('初始布局（未求解）'),
    );
  }, null, { timeout: 8000 });
  const labelText = await page.evaluate(() => {
    const el = Array.from(document.querySelectorAll('.nest-label')).find((e) =>
      (e.textContent ?? '').includes('初始布局（未求解）'),
    );
    return el ? el.textContent : '';
  });
  return {
    widthMm: parseFloat((widthText.match(/料长 (\d+) mm/) || [])[1] ?? 'NaN'),
    density: parseFloat((densityText.match(/利用率 (\d+(?:\.\d+)?)%/) || [])[1] ?? 'NaN') / 100,
    labelText: String(labelText),
  };
}

/** 通用轮询等待（fn 返回真值即返回；超时返回 null）。 */
async function waitFor(fn, timeoutMs) {
  const t0 = Date.now();
  for (;;) {
    const v = await fn();
    if (v) return v;
    if (Date.now() - t0 > timeoutMs) return null;
    await sleep(200);
  }
}

/** 等第 ordinal 个 /ws/solve 连接对象在场（key 预检是异步链 —— WS 构造晚于 click）。 */
async function waitConn(ordinal, timeoutMs = 15000) {
  return waitFor(() => conns[ordinal] ?? null, timeoutMs);
}

/** 等某连接收到指定 type 消息（final / stopped…）。 */
async function waitReceived(conn, type, timeoutMs) {
  const t0 = Date.now();
  for (;;) {
    const m = conn.received.find((x) => x && x.type === type);
    if (m) return m;
    if (Date.now() - t0 > timeoutMs) return null;
    await sleep(400);
  }
}

/** 等 start 载荷（连接 sent 首条 action=start）。 */
async function waitStartPayload(conn) {
  for (let i = 0; i < 50; i++) {
    const m = conn.sent.find((x) => x && x.action === 'start');
    if (m) return m;
    await sleep(200);
  }
  return null;
}

/** 等 first frame（warm 签名断言数据源）。 */
async function waitFirstFrame(conn) {
  for (let i = 0; i < 100; i++) {
    const m = conn.received.find((x) => x && x.type === 'frame');
    if (m) return m;
    await sleep(300);
  }
  return null;
}

/** 预览页数量矩阵写值（aria-label 寻址 + Enter 提交，smoke_prefix_extra 同款）。 */
async function setQty(label, size, value) {
  await page.evaluate(async (arg) => {
    const inp = document.querySelector(
      'input[aria-label="裁片 ' + arg.label + ' 码 ' + arg.size + ' 数量"]');
    if (!inp) throw new Error('qty input not found: ' + arg.label + '@' + arg.size);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(inp, String(arg.value));
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 80));
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await new Promise((r) => setTimeout(r, 80));
  }, { label, size, value });
}

/** 弹窗内组成员（data-edit-group=band）+ 非成员的世界 x（组拖断言数据源）。
 *  两层口径修正（首轮 [46.4,46.4,147.2]/[99.8,99.8,316.4] 假阴性复盘）：
 *  ① 世界 mm = polygon points 属性（屏幕 rect 会被 viewBox 随包络伸缩的重排污染）；
 *  ② 稳定键 = data-label_data-size —— selectPiece 提层（re-append）会改 DOM 序，
 *     按序号对齐会把同移组误判为各移各异。 */
function groupRects() {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-testid="initial-layout-overlay"] svg');
    const minX = (poly) => {
      let m = Infinity;
      for (const pair of (poly.getAttribute('points') ?? '').split(/\s+/)) {
        const x = parseFloat(pair.split(',')[0]);
        if (Number.isFinite(x) && x < m) m = x;
      }
      return m;
    };
    const keyOf = (p) => `${p.dataset.label ?? '?'}_${p.dataset.size ?? '?'}`;
    const groups = Array.from(svg.querySelectorAll('[data-edit-group="band"]'))
      .map((el) => ({ tag: 'band', key: keyOf(el), x: minX(el) }));
    const plain = Array.from(svg.querySelectorAll(':scope g > polygon'))
      .filter((p) => p.closest('[data-edit-group]') == null)
      .slice(0, 3)
      .map((p) => ({ tag: 'plain', key: keyOf(p), x: minX(p) }));
    return { groups, plain };
  });
}

try {
  // ---- P1 样例载入 + 3 码 + 短预算
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await gotoNesting();
  check('P1a 5336 样例载入 + 超排 Tab 解锁', true);
  for (const sz of SIZES) await page.check('#sz_' + sz);
  await page.fill('#time', SOLVE_TIME);
  check('P1b 勾选 3 码（32/33/34）+ time=30', true);

  // ---- P2 弹窗自动生成（无 saved → seed=0）
  const genCountBefore = genReqs.length;
  await openAndGenerate();
  check('P2a 打开自动生成（busy 起落 + 画布片落场）', true);
  check('P2b 生成请求恰好 1 次 + seed=0',
    genReqs.length - genCountBefore === 1 && genReqs[genReqs.length - 1].seed === 0,
    JSON.stringify(genReqs.map((g) => g.seed)));
  check('P2c 生成响应 plain 无 composite 键（band/prefix 关）',
    genResps.length > 0 && genResps[genResps.length - 1].composite === undefined);
  await page.screenshot({ path: OUT + '/01_plain_generated.png' });

  // ---- P3 拖一片（最右片右移 —— 恒合法：所有其余片 x1 ≤ 其旧 x1）→ 保存 → 伪卡片 + chip
  const idxR = await rightmostIdx();
  const pr = await pieceInfo(idxR);
  await dragTo(idxR, pr.cx + 80, pr.cy);
  check('P3x 拖片后保存闸放行（无非法重叠）',
    !(await page.locator('[data-testid="initial-layout-save"]').isDisabled()),
    ((await page.locator('[data-testid="initial-layout-save"]').getAttribute('title')) ?? ''));
  const saved = await saveLayout();
  check('P3a 保存后伪卡片挂载（初始布局（未求解）· pct% · 长度 cm）',
    /初始布局（未求解）/.test(saved.labelText), saved.labelText);
  check('P3b 保存料长/利用率读数在案', Number.isFinite(saved.widthMm) && Number.isFinite(saved.density),
    'width=' + saved.widthMm + 'mm density=' + saved.density);
  const chipText = ((await page.locator('[data-testid="initial-chip"]').textContent()) ?? '').trim();
  check('P3c chip fresh「将基于初始布局运行」', chipText.includes('将基于初始布局运行'), chipText);
  const noteText = ((await page.locator('[data-testid="initial-chip-note"]').textContent()) ?? '').trim();
  check('P3d 附注「仅普通运行生效」', noteText === '仅普通运行生效', noteText);
  await page.screenshot({ path: OUT + '/02_saved_chip.png' });

  // ---- P4 普通运行（time=30）→ start 载荷带 initial + 首帧 warm 签名 + engaged
  const connIdx0 = conns.length;
  await page.click('#start');
  const conn0 = await waitConn(connIdx0);
  const startPayload = await waitStartPayload(conn0);
  check('P4a start 载荷在案且带 initial 键',
    startPayload != null && startPayload.initial != null && Array.isArray(startPayload.initial.placed)
      && startPayload.initial.placed.length > 0,
    startPayload ? 'placed=' + startPayload.initial.placed.length : 'no payload');
  const firstFrame = await waitFirstFrame(conn0);
  check('P4b 首帧在案', firstFrame != null);
  if (firstFrame != null) {
    const dw = Math.abs(firstFrame.width_mm - saved.widthMm);
    check('P4c 首帧料长 == 保存料长（delta≤1mm，warm 恢复签名）',
      dw <= 1, 'first=' + firstFrame.width_mm + ' saved=' + saved.widthMm + ' delta=' + dw.toFixed(3));
    const dd = Math.abs(firstFrame.density - saved.density);
    check('P4d 首帧密度 ≈ 保存利用率（delta≤0.005）',
      dd <= 0.005, 'first=' + firstFrame.density.toFixed(4) + ' saved=' + saved.density.toFixed(4) + ' delta=' + dd.toFixed(4));
  }
  await page.screenshot({ path: OUT + '/03_first_frame_warm.png' });
  const final0 = await waitReceived(conn0, 'final', 90000);
  check('P4e final warm_state.engaged === true',
    final0 != null && final0.warm_state != null && final0.warm_state.engaged === true,
    final0 ? JSON.stringify(final0.warm_state) : 'no final');
  await sleep(600);
  const statusP = ((await page.locator('#status').textContent()) ?? '').trim();
  check('P4f 状态行「已从初始布局热启动」', statusP.includes('已从初始布局热启动'), statusP);
  check('P4g engaged 路径无降级 toast',
    (await page.locator('.toast', { hasText: '已按普通方式运行' }).count()) === 0);

  // ---- S stale：改数量 → chip stale → 再运行无 initial + 帧流照常
  await page.locator('button.tab', { hasText: '上传预览' }).click();
  await page.waitForSelector('.qty-matrix', { timeout: 8000 });
  await setQty('g01', 32, 2);
  await page.locator('button.tab', { hasText: '超排' }).click();
  await sleep(400);
  const staleText = ((await page.locator('[data-testid="initial-chip-stale"]').textContent()) ?? '').trim();
  check('S1 数量漂移 → chip stale「初始布局已失效（参数已变更）」',
    staleText.includes('初始布局已失效'), staleText);
  check('S2 stale 态无 fresh chip', (await page.locator('[data-testid="initial-chip"]').count()) === 0);
  const connIdx1 = conns.length;
  await page.click('#restart, #start');
  const conn1 = await waitConn(connIdx1);
  const stalePayload = await waitStartPayload(conn1);
  check('S3 再运行 start 载荷无 initial 键（stale 不附带、不拦截）',
    stalePayload != null && !('initial' in stalePayload),
    stalePayload ? 'keys=' + Object.keys(stalePayload).join(',') : 'no payload');
  const anyFrame = await waitFirstFrame(conn1);
  check('S4 帧流照常（≥1 帧，运行未被拦截）', anyFrame != null);
  await page.click('#stop');
  const stopped1 = await waitReceived(conn1, 'stopped', 20000);
  check('S5 停止收场（stopped 消息）', stopped1 != null);

  // ---- B band 变体：开 band g05 → 生成（组合宇宙）→ 组拖 → 保存 → 运行 engaged
  await page.click('[data-testid="per-type-btn"]');
  await page.waitForSelector('[data-testid="per-type-overlay"]', { timeout: 8000 });
  await page.check('[data-testid="band-enabled"]');
  await page.selectOption('[data-testid="band-label-select"]', 'g05');
  await sleep(500); // band 预览请求非阻塞
  await page.click('.per-type-btn-confirm');
  await sleep(400);
  const genCountB = genReqs.length;
  const respCountB = genResps.length;
  await openAndGenerate();
  check('B1 band 开 → 自动生成（busy 起落 + 画布落场）', true);
  check('B2 生成请求恰好 +1', genReqs.length - genCountB === 1,
    JSON.stringify(genReqs.slice(genCountB)));
  const respB = genResps[respCountB];
  const compositePids = respB?.composite?.placed_items?.map((p) => p.id) ?? [];
  check('B3 生成响应 composite 在场且含 WB_ 组合片',
    compositePids.some((pid) => pid.startsWith('WB_')),
    compositePids.filter((p) => p.startsWith('WB_')).join(',') || 'none');
  check('B4 composite.demand_map 在场（组合宇宙需求映射）',
    respB?.composite?.demand_map != null && Object.keys(respB.composite.demand_map).length > 0);
  await page.screenshot({ path: OUT + '/04_band_generated.png' });

  // 组拖：data-edit-group=band 全体同位移 + 非成员不动
  const before = await groupRects();
  check('B5 组成员标记在案（≥1 片 data-edit-group=band）', before.groups.length >= 1,
    'n=' + before.groups.length);
  // 命中点 = 组成员毛版多边形（data-edit-group 直接落在 polygon 上 —— pieceDom
  // 各层直挂翻转组）内部一点：bbox 中心可落在 L/弧形片凹口空白（首轮 deltas=[0,0,0]
  // 即此因）。elementFromPoint 逐候选验证（客户坐标 = mouse 同系）。
  const g0Info = await page.evaluate(() => {
    const poly = document.querySelector('[data-testid="initial-layout-overlay"] svg [data-edit-group="band"]');
    const r = poly.getBoundingClientRect();
    const cands = [];
    for (let t = 0.5; t > 0.02; t -= 0.08) {
      cands.push([t, 0.5], [0.5, t], [1 - t, 0.5], [0.5, 1 - t], [t, t], [1 - t, 1 - t], [t, 1 - t], [1 - t, t]);
    }
    for (const [fx, fy] of cands) {
      const x = r.x + r.width * fx;
      const y = r.y + r.height * fy;
      const el = document.elementFromPoint(x, y);
      if (el != null && (el === poly || poly.contains(el) || el.contains(poly))) return { cx: x, cy: y };
    }
    return { cx: r.x + r.width / 2, cy: r.y + r.height / 2 };
  });
  await page.mouse.move(g0Info.cx, g0Info.cy);
  await page.mouse.down();
  await page.mouse.move(g0Info.cx + 80, g0Info.cy, { steps: 8 });
  await sleep(60);
  await page.mouse.up();
  await sleep(200);
  const after = await groupRects();
  // 按稳定键对齐（data-label_data-size）后取世界位移：刚性组 = 全员互差 ≤0.5mm
  // 且确有位移（≥10mm；+80px 屏幕位移的世界值随缩放比浮动，不断言具体值）。
  const bmap = new Map(before.groups.map((g) => [g.key, g.x]));
  const deltas = after.groups
    .filter((g) => bmap.has(g.key))
    .map((g) => g.x - bmap.get(g.key));
  const med = deltas.slice().sort((a, b) => a - b)[Math.floor(deltas.length / 2)];
  check('B6 整组拖动：全部 band 成员同位移（世界 mm 互差≤0.5）',
    after.groups.length === before.groups.length
      && deltas.length === before.groups.length
      && deltas.every((d) => Math.abs(d - med) <= 0.5)
      && Math.abs(med) >= 10,
    'deltas=' + JSON.stringify(deltas.map((d) => +d.toFixed(1))));
  const pmap = new Map(before.plain.map((g) => [g.key, g.x]));
  const plainDeltas = after.plain
    .filter((g) => pmap.has(g.key))
    .map((g) => g.x - pmap.get(g.key));
  check('B7 非组成员不动（世界 mm |d|≤0.5）',
    plainDeltas.length > 0 && plainDeltas.every((d) => Math.abs(d) <= 0.5),
    'deltas=' + JSON.stringify(plainDeltas.map((d) => +d.toFixed(1))));
  await page.screenshot({ path: OUT + '/05_band_group_drag.png' });

  // 组拖落位不保证合法（整组 +80px 可能压邻片）→ 布局刷新丢弃编辑重生成（组拖
  // 判据已收口在 B6/B7 测量；保存态取新生成合法布局 —— seed 换代防同帧复现）。
  await page.locator('[data-testid="initial-layout-refresh"]').click();
  await page.waitForSelector('[data-testid="edit-confirm-message"]', { timeout: 5000 });
  await page.click('[data-testid="edit-confirm-ok"]');
  await waitRegen();
  check('B7b 刷新丢弃组拖编辑（重生成 seed 换代）', true);

  const savedB = await saveLayout();
  check('B8 保存 → 伪卡片（band 布局）', /初始布局（未求解）/.test(savedB.labelText), savedB.labelText);
  const chipB = ((await page.locator('[data-testid="initial-chip"]').textContent()) ?? '').trim();
  check('B9 chip fresh 回场', chipB.includes('将基于初始布局运行'), chipB);

  const connIdxB = conns.length;
  await page.click('#restart, #start');
  const connB = await waitConn(connIdxB);
  const startB = await waitStartPayload(connB);
  check('B10 band 运行 start 载荷带 initial（placed 含 WB_ + demand_map）',
    startB != null && startB.initial != null && startB.initial.demand_map != null
      && startB.initial.placed.some((p) => p.id.startsWith('WB_')),
    startB ? 'placed=' + startB.initial.placed.length + ' map=' + Object.keys(startB.initial.demand_map).length : 'no payload');
  const finalB = await waitReceived(connB, 'final', 90000);
  check('B11 band final warm_state.engaged === true',
    finalB != null && finalB.warm_state != null && finalB.warm_state.engaged === true,
    finalB ? JSON.stringify(finalB.warm_state) : 'no final');
  await sleep(600);
  const statusB = ((await page.locator('#status').textContent()) ?? '').trim();
  check('B12 状态行「已从初始布局热启动」（band 变体）', statusB.includes('已从初始布局热启动'), statusB);
  await page.screenshot({ path: OUT + '/06_band_final.png' });
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

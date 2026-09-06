// edit-drag-snap US-004 端到端冒烟（prd-edit-drag-snap，2026-09-06）—— 右键贴附双护栏收官
// 回归锁死：吸附功能护栏 + 左键零回归红线护栏（同一求解布局内背靠背对拍）。
//
// 模板对齐 scripts/smoke_edit_polish.mjs（Playwright 流程骨架/导出抓包套路）+
// smoke-band-preview.mjs（addInitScript 预置 ms.tour.* 防 tour-overlay 拦截）；
// 浏览器 = Edge 通道（本机无 playwright 二进制，借系统通道 msedge，Chrome 兜底
// —— 同目录其余冒烟同款）。期望吸附坐标由 Node 导入 esbuild 即时 bundle 的
// 真实引擎（src/lib/snap.ts + overlap.ts + editGeometry.ts）在 WS 帧数据上
// 预计算 —— 浏览器 DOM points 串复用键盘用例数学锚点法（lib/geometry pointsStr
// 的 r2 复刻）逐字节对拍，不是脚本自算自证。
// 物理毛版口径（2026-09-06 统一）：画布 layer1/指标/吸附全切 raw_polygon —— 脚本
// 侧锚点（physOf）与 DOM/引擎同源；d=0 布局两者天然一致，d>0 布局按 raw 对拍。
//
// 前置：ms-web 在 :8000 运行 + 新 static 构建（prod 模式）。
//
//   node materialSorting-web/scripts/smoke_drag_snap.mjs
//
// 相位：
//   S1 上传 5336 母版 → commit → 3 码（32/33/34）20s 求解 30 片 → 基线 PLT 导出
//      （placed 与 WS 末帧逐位全等 —— 后续全精度/回读对拍的基准端）。
//   S2 编辑弹窗 → 真实引擎预模拟选片对（attract / trusted-click-free /
//      far-free / retreat / final-attract 五路全预测通过才采用，全流程确定性）。
//   B  右键（button:2）pointer 序列：留 5mm 小缝松手 attract（DOM points ==
//      引擎 tr + 伙伴高亮轮廓 == partnerKey 世界轮廓 + 指标面板重叠 0.0）→
//      高亮淡出 → trusted 右键无位移 click（contextmenu 被吞 + 无吸附位移 +
//      选中保持）→ 右键继续拖离远端恢复自由（拖动中合成 contextmenu 被吞 +
//      原样落点 + 指标 0.0）→ 右键深叠松手 retreat（DOM points == 引擎 tr +
//      终态独立布尔交干净 + 指标 == 引擎终态）。
//   R  左键红线两连（回归红线）：同深叠目标压线落点原样（重叠 > 1000mm²
//      如实保留永不 retreat）+ 同小缝目标落点原样（attract 永不发生）。
//   C  末次右键留 2mm 小缝松手 attract 回贴 → 保存 → 导出 PLT：POST placed 30 条 +
//      被拖片 translation 与引擎吸附值全精度贯通（|Δ| ≤ 1e-6 + y 逐位恒等 +
//      亚 0.01mm 精度未截断 + 终态接触几何首触 ≈ 1nm/全邻居布尔交 = 0）+
//      rot/mirror 原样 + 其余 29 项与求解末帧逐位全等；PLT 正文回读：PU 笔与
//      笔画数守恒 + 其余 29 片笔画逐位全等 + 被拖片笔画 == 基线平移吸附位移
//      （±2 HPGL unit、y 分量逐位全等）—— 导出链零回归。
//
// 报告落 out/smoke_drag_snap/report.json；退出码 0 = 全 PASS。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

// 路径锚定脚本位置（任意 CWD 可跑）：materialSorting-web/scripts/ -> repo 根
const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const WEB = ROOT + '/materialSorting-web';
const OUT = ROOT + '/out/smoke_drag_snap';

const { chromium } = await import('playwright');
const { build: esbuildBuild } = await import('esbuild');

const BASE = 'http://127.0.0.1:8000';
const DXF = ROOT + '/data/5336#老六订单14%7%围加9.dxf';
const SIZES = [32, 33, 34]; // 5336 码集；3 码 × 10 片 = 30 片（Σdemand 默认 1/格）
const SOLVE_TIME = '20';
const EXPECT_TOTAL = 30;

mkdirSync(OUT, { recursive: true });

// ---------- 真实引擎 bundle（esbuild 即时构建 src 源码，非复刻） ----------
// 全部期望吸附坐标 = 引擎自己在 WS 帧数据上的答案；脚本侧只复刻 pointsStr 的
// r2 舍入（键盘用例数学锚点法 —— DOM points 串逐字节对拍用）。
writeFileSync(OUT + '/engine_entry.ts', [
  "export { ATTRACT_MAX_GAP_MM, COLLIDE_AREA_EPS_MM2, computeSnapCorrection } from '../../materialSorting-web/src/lib/snap';",
  "export { applyEditPlacement, computeOverlap, precomputeEditPiecesFromItems } from '../../materialSorting-web/src/lib/overlap';",
  "export { firstContactDistance, transformPolygon } from '../../materialSorting-web/src/lib/editGeometry';",
  '',
].join('\n'));
await esbuildBuild({
  entryPoints: [OUT + '/engine_entry.ts'],
  outfile: OUT + '/engine_bundle.mjs',
  bundle: true,
  format: 'esm',
  platform: 'node',
  logLevel: 'warning',
});
const ENG = await import(pathToFileURL(OUT + '/engine_bundle.mjs').href);
// 独立布尔交口径（DOM points 解析后的全邻居重叠复核，不依赖引擎池）
const pcMod = await import(pathToFileURL(WEB + '/node_modules/polygon-clipping/dist/polygon-clipping.esm.js').href);
const pcIntersection = (pcMod.default ?? pcMod).intersection;

// ---------- 浏览器（Edge 通道，Chrome 兜底）+ tour 预置 ----------
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true });
} catch {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
}
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
// 预置引导层已读（TOUR_VERSION='7'，smoke-band-preview 套路）防 tour-overlay 拦截点击
await context.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '7');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page = await context.newPage();
const results = [];
function check(name, ok, extra = '') {
  results.push({ name, ok, extra: String(extra) });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 200) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function dismissTour(p, rounds = 4) {
  for (let i = 0; i < rounds; i++) {
    const gone = await p.evaluate(() => document.querySelector('[data-testid=tour-overlay]') === null);
    if (gone) return;
    await p.evaluate(() => {
      const btn = document.querySelector('[data-testid=tour-skip]');
      if (btn) btn.click();
    });
    await sleep(600);
  }
}
async function rawFetch(p, url, init = null) {
  return p.evaluate(async ({ u, i }) => {
    const r = await fetch(u, i);
    let body = null;
    try { body = await r.json(); } catch { body = null; }
    return { status: r.status, body };
  }, { u: url, i: init });
}
const cap = { msgs: [] };
function frameText(f) {
  if (typeof f === 'string') return f;
  if (f && typeof f.payload === 'string') return f.payload;
  if (f && f.payload != null && typeof f.payload === 'object') return String.fromCharCode(...f.payload);
  return '';
}
page.on('websocket', (ws) => {
  ws.on('framereceived', (f) => {
    try { cap.msgs.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
  });
});
async function waitMsg(type, timeout = 150000) {
  const t0 = Date.now();
  for (;;) {
    const m = cap.msgs.find((x) => x && x.type === type);
    if (m) return m;
    if (Date.now() - t0 > timeout) return null;
    await sleep(500);
  }
}

// ---------- Node 侧几何/解析助手（数学锚点法 + 独立对拍） ----------
const shoelace = (ring) => {
  let s = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    s += x1 * y2 - x2 * y1;
  }
  return s / 2;
};
const overlapArea = (a, b) => {
  try {
    const mp = pcIntersection([a], [b]);
    let area = 0;
    for (const poly of mp) {
      area += Math.abs(shoelace(poly[0]));
      for (let h = 1; h < poly.length; h++) area -= Math.abs(shoelace(poly[h]));
    }
    return Math.max(0, area);
  } catch { return -1; }
};
const r2 = (x) => Math.round(x * 100) / 100;
/** pointsStr 逐字节复刻（lib/geometry.ts 同款 r2 舍入 —— DOM points 串数学锚点）。 */
const pointsStrJs = (poly, rot, tr, mirror = false) => {
  const r = (rot * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  let out = '';
  for (let i = 0; i < poly.length; i++) {
    const x = mirror ? -poly[i][0] : poly[i][0];
    const y = poly[i][1];
    out += (i ? ' ' : '') + r2(x * c - y * s + tr[0]) + ',' + r2(x * s + y * c + tr[1]);
  }
  return out;
};
const parsePts = (s) => s.trim().split(/\s+/).map((p) => p.split(',').map(Number));
const centroidMean = (pts) => {
  let x = 0;
  let y = 0;
  for (const p of pts) { x += p[0]; y += p[1]; }
  const n = Math.max(1, pts.length);
  return [x / n, y / n];
};
const unit = (v) => {
  const len = Math.hypot(v[0], v[1]);
  return len > 0 ? [v[0] / len, v[1] / len] : null;
};
const bboxOfJs = (poly) => {
  let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
  for (const [x, y] of poly) {
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY };
};
/** PLT/HPGL 正文 → 笔画列表（PU 起新笔、PD 续画；clean 版层序 = 门幅框 +
 *  30 片毛版轮廓（placed 序）在前，标注/表格笔画在后 ⇒ stroke[0]=边框、
 *  stroke[k+1]=placed[k] 毛版轮廓；PD ≤10 点分块自动拼接）。 */
function parsePltStrokes(text) {
  const strokes = [];
  let cur = null;
  for (const raw of text.split(/\r\n|\r|\n/)) {
    const line = raw.trim();
    if (/^PU-?\d/.test(line)) {
      const m = line.slice(2).replace(/;$/, '').split(',');
      cur = [[parseInt(m[0], 10), parseInt(m[1], 10)]];
      strokes.push(cur);
    } else if (/^PD-?\d/.test(line) && cur) {
      const nums = line.slice(2).replace(/;$/, '').split(',').map(Number);
      for (let i = 0; i + 1 < nums.length; i += 2) cur.push([nums[i], nums[i + 1]]);
    }
  }
  return strokes;
}
/** 指标面板重合面积数值（React flush 余量 80ms；null = 面板不在案）。 */
const metricsAreaNum = async () => {
  await sleep(80);
  const t = await page.evaluate(() => {
    const el = document.querySelector('[data-testid=edit-metrics-area]');
    return el ? el.textContent : null;
  });
  return t == null ? null : Number(String(t).split(' ')[0]);
};
const partnerPointsAttr = () => page.evaluate(() => {
  const el = document.querySelector('[data-testid=edit-snap-partner]');
  return el ? el.getAttribute('points') : null;
});
/** 右键（button:2）单跳拖动：pointerdown(片) → [可选中点帧 + 合成 contextmenu]
 *  → pointermove(落点) → pointerup。attract/retreat 断言路径恒单 move 帧（与
 *  预模拟的 lastSafeTr 会话模型逐帧一致 —— 加中点帧会改变 retreat 锚点）；中点帧
 *  仅用于 free 落点路径（远端安全 ⇒ 锚点恒 = 落点，中点帧无影响）。 */
const dragPiece = (el, dxMm, button, midContext = false) => page.evaluate(({ el, dxPx, button, midContext }) => {
  const svg = document.querySelector('svg.edit-layout-svg');
  const r = svg.getBoundingClientRect();
  const x0 = r.x + 80;
  const y0 = r.y + 80;
  const x1 = x0 + dxPx;
  let ctxPrevented = null;
  el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 41, clientX: x0, clientY: y0, button }));
  if (midContext) {
    svg.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 41, clientX: (x0 + x1) / 2, clientY: y0 }));
    const ev = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    svg.dispatchEvent(ev);
    ctxPrevented = ev.defaultPrevented;
  }
  svg.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 41, clientX: x1, clientY: y0 }));
  svg.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 41, clientX: x1, clientY: y0, button }));
  return {
    points: el.getAttribute('points'),
    partner: !!document.querySelector('[data-testid=edit-snap-partner]'),
    ctxPrevented,
  };
}, { el, dxPx: dxMm * S, button, midContext });
/** trusted 右键 click（真实鼠标事件链）：contextmenu 计数挂在 svg 上；点击点
 *  探测 elementFromPoint === 被拖片（悬浮卡均 pointer-events:none 不挡命中）。 */
async function trustedRightClick(el) {
  await page.evaluate(() => {
    window.__ctx = { fired: 0, prevented: 0 };
    const svg = document.querySelector('svg.edit-layout-svg');
    svg.addEventListener('contextmenu', (e) => {
      window.__ctx.fired += 1;
      if (e.defaultPrevented) window.__ctx.prevented += 1;
    });
  });
  const pt = await page.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const cands = [
      [r.x + r.width * 0.5, r.y + r.height * 0.5],
      [r.x + r.width * 0.35, r.y + r.height * 0.35],
      [r.x + r.width * 0.65, r.y + r.height * 0.6],
    ];
    for (const [cx, cy] of cands) {
      if (document.elementFromPoint(cx, cy) === el) return [cx, cy];
    }
    return null;
  }, el);
  if (!pt) return { probed: false };
  await page.mouse.click(pt[0], pt[1], { button: 'right' });
  return await page.evaluate((el) => ({
    probed: true,
    ctx: window.__ctx,
    points: el.getAttribute('points'),
    metrics: !!document.querySelector('[data-testid=edit-metrics]'),
  }), el);
}
/** 点选格式 → 导出 → 抓 POST /export 请求载荷与响应正文。PLT 族走 ExportInfoModal
 *  确认；响应正文 = 页内 fetch 包装捕获（apiFetch 单点；Playwright 网络层对
 *  fetch→blob 消费后的附件 body 常拿不到 —— smoke_edit_polish 同套路）。 */
async function exportOnce(fmt, tag) {
  let captured = null;
  const onResp = (r) => { if (r.url().endsWith('/export')) captured = r; };
  await page.evaluate(() => {
    window.__exportCaps = [];
    if (!window.__exportOrigFetch) window.__exportOrigFetch = window.fetch;
    const orig = window.__exportOrigFetch;
    window.fetch = async function (...args) {
      const res = await orig.apply(this, args);
      if (String(args[0]).includes('/export')) {
        try {
          const buf = await res.clone().arrayBuffer();
          window.__exportCaps.push({ bytes: buf.byteLength, text: new TextDecoder().decode(buf) });
        } catch (e) {
          window.__exportCaps.push({ bytes: 0, text: '', err: String(e) });
        }
      }
      return res;
    };
  });
  await page.selectOption('select.export-fmt', fmt);
  await sleep(200);
  page.on('response', onResp);
  await page.click('button.export');
  if (fmt === 'plt' || fmt === 'plt-clean') {
    await page.waitForSelector('[data-testid=export-info-overlay]', { timeout: 15000 });
    await page.waitForSelector('.export-ro-row', { timeout: 15000 });
    await page.click('[data-testid=export-info-confirm]');
  }
  for (let i = 0; i < 60; i++) {
    const n = await page.evaluate(() => (window.__exportCaps || []).length);
    if (captured && n > 0) break;
    await sleep(500);
  }
  const caps = await page.evaluate(() => window.__exportCaps || []);
  await page.evaluate(() => {
    if (window.__exportOrigFetch) window.fetch = window.__exportOrigFetch;
  });
  page.off('response', onResp);
  const cap = caps[caps.length - 1] || { bytes: 0, text: '' };
  const cd = captured ? (captured.headers()['content-disposition'] || '') : '';
  let reqBody = null;
  try { reqBody = captured ? captured.request().postDataJSON() : null; } catch { reqBody = null; }
  check(tag + ' POST /export 200（.' + fmt.replace('plt-clean', 'plt') + ' 附件）',
    !!captured && captured.status() === 200
      && decodeURIComponent(cd).includes('.' + fmt.replace('plt-clean', 'plt')),
    captured ? captured.status() + ' ' + decodeURIComponent(cd).slice(0, 60) : 'no response');
  return { reqBody, respBody: cap.text || '' };
}

// ---------- S1 上传 5336 + 短求解 + 基线 PLT 导出 ----------
await page.goto(BASE, { waitUntil: 'networkidle' });
const sid = await page.evaluate(() => localStorage.getItem('ms_sid'));
check('S0 页面加载落会话 sid', /^[0-9a-f]{32}$/.test(sid || ''), (sid || '').slice(0, 8));

await page.locator('input[type=file]').first().setInputFiles(DXF);
await page.waitForSelector('button.tab:not([disabled]):has-text("超排")', { timeout: 240000 });
let committed = false;
for (let i = 0; i < 80; i++) {
  const r = await rawFetch(page, '/api/ptypes', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
  if (r.status === 200 && Object.keys(r.body?.representatives || {}).length > 0) {
    committed = true; break;
  }
  await sleep(3000);
}
check('S1a 上传 5336 + commit 完成（ptypes 非空）', committed);
if (!committed) {
  writeFileSync(OUT + '/report.json', JSON.stringify({ at: new Date().toISOString(), results }, null, 2));
  await browser.close();
  process.exit(1);
}

await page.click('button.tab:has-text("超排")');
await sleep(800);
await dismissTour(page);
for (const sz of SIZES) await page.check('#sz_' + sz);
await page.fill('#time', SOLVE_TIME);
await page.click('#start');
const final1 = await waitMsg('final', 150000);
const manifest = cap.msgs.find((x) => x && x.type === 'manifest') || null;
const solverPlaced = cap.msgs.filter((x) => x && x.type === 'frame').slice(-1)[0]?.placed_items || [];
check('S1b 短求解 20s 出 final（3 码 30 片 = Σdemand）',
  !!final1 && !!manifest && solverPlaced.length === EXPECT_TOTAL,
  final1 ? 'density=' + final1.density.toFixed(4) + ' placed=' + solverPlaced.length : 'no final');

// 基线 PLT 导出（编辑弹窗开之前；placed 与 WS 末帧逐位全等 = 后续对拍基准端）
const exp0 = await exportOnce('plt-clean', 'S1c');
const placed0 = exp0.reqBody?.placed || null;
const strokes0 = parsePltStrokes(exp0.respBody || '');
check('S1c 基线 PLT placed 守恒（30 条且与 WS 求解末帧逐位全等）',
  !!placed0 && placed0.length === EXPECT_TOTAL
    && JSON.stringify(placed0) === JSON.stringify(solverPlaced),
  'len=' + (placed0 || []).length + ' strokes=' + strokes0.length);

// ---------- S2 编辑弹窗 + 真实引擎预模拟选片 ----------
check('S2a 引擎常量契约（ATTRACT_MAX_GAP_MM=10 / COLLIDE_AREA_EPS_MM2=1e-9 —— snap.ts 导出锁值）',
  typeof ENG.computeSnapCorrection === 'function'
    && ENG.ATTRACT_MAX_GAP_MM === 10 && ENG.COLLIDE_AREA_EPS_MM2 === 1e-9);

await page.click('[data-testid=edit-controls-edit]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { timeout: 5000 });
check('S2b 编辑弹窗打开 + 指南卡贴附行（右键拖动松手贴附）',
  await page.evaluate(() => {
    const el = document.querySelector('[data-testid=edit-guide]');
    return !!el && el.textContent.includes('右键拖动松手贴附');
  }));
await page.screenshot({ path: OUT + '/s2_edit_open.png' });

const EPS = ENG.COLLIDE_AREA_EPS_MM2;
const byId = new Map(manifest.pieces.map((p) => [p.id, p]));
// 物理毛版口径（2026-09-06 统一）：脚本侧一切几何锚（选片 bbox / DOM points 数学
// 锚点串）与画布同源切 raw_polygon（raw ?? polygon 老后端回退）；引擎 bundle 打包
// 当前源码自动跟随（overlap 池 = raw）。
const physOf = (p) => (p.raw_polygon && p.raw_polygon.length >= 3 ? p.raw_polygon : p.polygon);
const items = solverPlaced;
const worlds = items.map((it) => ENG.transformPolygon(
  physOf(byId.get(it.id)), it.rotation, it.translation, it.mirror === true));
const boxes = worlds.map(bboxOfJs);
const pool0 = ENG.precomputeEditPiecesFromItems(manifest, items);

// 单跳拖动会话模型（与浏览器事件流逐帧一致）：pointerdown@S 落基线、单 move 帧@R
// 之后 up —— 落点安全则 lastSafeTr=R（零位移退化 attract），否则锚点停在 S（retreat）。
let pick = null;
const rej = { gap: 0, yov: 0, base: 0, attract: 0, click: 0, free: 0, retreat: 0, final: 0 };
outer:
for (let k = 0; k < worlds.length && !pick; k++) {
  const rotK = items[k].rotation;
  const mirK = items[k].mirror === true;
  const t0 = [items[k].translation[0], items[k].translation[1]];
  const epK = { ...pool0[k] };
  const minXAt = (tr) => { ENG.applyEditPlacement(epK, rotK, tr, mirK); return epK.bbox.minX; };
  const ovAt = (tr) => { ENG.applyEditPlacement(epK, rotK, tr, mirK); return ENG.computeOverlap(epK, pool0).areaMm2; };
  const predictSnap = (S, R) => {
    const baseline = ovAt(S);
    const ovR = ovAt(R);
    const sess = {
      lastSafeTr: ovR <= baseline + EPS ? [R[0], R[1]] : [S[0], S[1]],
      startOverlapMm2: baseline,
    };
    ENG.applyEditPlacement(epK, rotK, R, mirK);
    return ENG.computeSnapCorrection(epK, R, sess, pool0, { gate: manifest.gate_mm });
  };
  for (let m = 0; m < worlds.length; m++) {
    if (m === k) continue;
    const g = boxes[k].minX - boxes[m].maxX; // m 在 k 左侧的 bbox x 缝
    if (g < -5 || g > 40) { rej.gap++; continue; }
    const yOv = Math.min(boxes[k].maxY, boxes[m].maxY) - Math.max(boxes[k].minY, boxes[m].minY);
    if (yOv < 40) { rej.yov++; continue; }
    // B0 左键基准位 = +30mm（须干净 —— 指标 0.0 断言的前提）
    const S0 = [t0[0] + 30, t0[1]];
    if (ovAt(S0) > 0.05) { rej.base++; continue; }
    // B1 右键落点 = 距 m 5mm bbox 缝 → attract
    const R1 = [S0[0] + (boxes[m].maxX + 5) - minXAt(S0), S0[1]];
    const res1 = predictSnap(S0, R1);
    if (res1.kind !== 'attract' || res1.partnerKey == null
      || Math.abs(R1[0] - res1.tr[0]) < 1 || ovAt(R1) > 0.05 || ovAt(res1.tr) > 0.05) { rej.attract++; continue; }
    // （trusted 右键无位移 click 不设门槛：contact−1nm 位即使退化零位移 attract 也
    //  不动 points（B5 只断言 contextmenu 被吞 + points 不动 + 选中保持），配对更鲁棒）
    // B6 右键拖离远端（越过所有其它片 +60mm）必须 free
    const maxXAll = Math.max(...boxes.filter((_, i) => i !== k).map((b) => b.maxX));
    const R4 = [res1.tr[0] + (maxXAll + 60) - minXAt(res1.tr), res1.tr[1]];
    if (R4[0] < 0 || predictSnap(res1.tr, R4).kind !== 'free' || ovAt(R4) > 0.05) { rej.free++; continue; }
    // B7 右键深叠（越过 m 近缘 60mm）必须 retreat 且回退可见、落点重叠够大
    const R2 = [R4[0] + (boxes[m].maxX - 60) - minXAt(R4), R4[1]];
    const res2 = predictSnap(R4, R2);
    if (res2.kind !== 'retreat' || Math.abs(res2.tr[0] - R2[0]) < 20
      || ovAt(R2) < 1000 || ovAt(res2.tr) > 0.05) { rej.retreat++; continue; }
    // R1f/R1c：R1 同 x 在「吸附后链上 y」的重访位 —— attract 沿质心连线方向移动
    // （y 分量非 0），B1 之后整条链的 y = res1.tr[1]（后续水平拖动/retreat 均不改 y）。
    // R1f 距 m 的缝 ≈ B1 吸拢量 attractDx（≥1mm 门槛保证）；末次右键推距在小步长
    // 梯度里搜索（推过头会违 attract 谓词退化 retreat —— 布局相关，不能写死）。
    const R1f = [R1[0], res1.tr[1]]; // 左键小缝红线落点（小缝、不吸附）
    let R1c = null;
    let resF = null;
    for (const push of [0.5, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8, 3.2, 0.3, 0.65, 1.0, 1.4]) {
      const cand = [R1f[0] - push, R1f[1]];
      if (cand[0] < 0) continue;
      const rf2 = predictSnap(R1f, cand);
      if (rf2.kind === 'attract' && rf2.partnerKey != null
        && Math.abs(cand[0] - rf2.tr[0]) >= 0.3 && ovAt(rf2.tr) <= 0.05) {
        R1c = cand;
        resF = rf2;
        break;
      }
    }
    if (!resF) { rej.final++; continue; }
    pick = { k, m, g, S0, R1, res1, R4, R2, res2, R1f, R1c, resF, rotK, mirK, t0 };
    break outer;
  }
}
check('S2c 选片决策在案（真实引擎预模拟：attract/click-free/far-free/retreat/final-attract 五路全预测）',
  !!pick,
  pick ? ('k=' + pick.k + ' m=' + pick.m + ' pid=' + items[pick.k].id + ' 缝=' + pick.g.toFixed(1)
    + 'mm 吸拢=' + (pick.R1[0] - pick.res1.tr[0]).toFixed(2)
    + 'mm 回退=' + (pick.res2.tr[0] - pick.R2[0]).toFixed(2)
    + 'mm 末次吸拢=' + (pick.R1c[0] - pick.resF.tr[0]).toFixed(2) + 'mm')
    : JSON.stringify(rej));
if (!pick) {
  writeFileSync(OUT + '/report.json', JSON.stringify({ at: new Date().toISOString(), rejected: rej, results }, null, 2));
  await browser.close();
  process.exit(1);
}
const KI = pick.k;
const kBase = physOf(byId.get(items[KI].id)); // 物理毛版（画布 layer1 points 同源）
const expPts = (tr) => pointsStrJs(kBase, pick.rotK, tr, pick.mirK);
const kh = await page.evaluateHandle((want) => {
  const svg = document.querySelector('svg.edit-layout-svg');
  return Array.from(svg.querySelectorAll('g > polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55')
    .find((p) => p.getAttribute('points') === want);
}, expPts(pick.t0));
check('S2d 被拖片按 points 内容寻址（恰 1 片）', kh.asElement() !== null, 'k=' + KI + ' pid=' + items[KI].id);
const S = await page.evaluate(() => {
  const svg = document.querySelector('svg.edit-layout-svg');
  const r = svg.getBoundingClientRect();
  const vb = svg.getAttribute('viewBox').split(' ').map(Number);
  return Math.min(r.width / vb[2], r.height / vb[3]);
});
check('S2e 视图比尺 > 0（px/mm）', S > 0, 's=' + S.toFixed(4));
const overlapWithAll = (pts) => {
  const w = parsePts(pts);
  let sum = 0;
  for (let j = 0; j < worlds.length; j++) {
    if (j === KI) continue;
    const a = overlapArea(w, worlds[j]);
    if (a < 0) continue;
    sum += a;
  }
  return sum;
};

// ---------- B 右键贴附行为段 ----------
// B0 左键基准 +30mm（引擎外路径，原样落点）
const r0 = await dragPiece(kh, pick.S0[0] - pick.t0[0], 0);
check('B0 左键基准 +30mm 原样（引擎外路径）+ 无伙伴', r0.points === expPts(pick.S0) && !r0.partner);

// B1 右键留 5mm 小缝松手 → attract（DOM points == 引擎 tr，数学锚点串全等）
const r1 = await dragPiece(kh, pick.R1[0] - pick.S0[0], 2);
check('B1 右键 5mm 缝松手 attract：DOM points == 引擎 tr（数学锚点串全等，rot/mirror 原样）',
  r1.points === expPts(pick.res1.tr),
  '吸拢=' + (pick.R1[0] - pick.res1.tr[0]).toFixed(3) + 'mm partnerKey=' + pick.res1.partnerKey);
const pk1 = pick.res1.partnerKey;
const partnerExpect = pointsStrJs(pool0[pk1].basePolygon, pool0[pk1].rot, pool0[pk1].tr, pool0[pk1].mirror);
const pp1 = await partnerPointsAttr();
check('B2 伙伴高亮轮廓 == partnerKey 世界轮廓（引擎裁决的贴附目标）',
  pp1 != null && pp1 === partnerExpect, 'key=' + pk1);
const area1 = await metricsAreaNum();
check('B3 指标面板重叠 0.0（attract 终态，与引擎终态一致）',
  area1 != null && area1 < 0.05, 'area=' + area1);
await page.screenshot({ path: OUT + '/b1_attract.png' });

// B4 伙伴高亮 ~1.2s 淡出移除（900ms 常驻 + 300ms 淡出）
await sleep(1300);
check('B4 伙伴高亮 ~1.2s 淡出移除',
  await page.evaluate(() => document.querySelector('[data-testid=edit-snap-partner]') === null));

// B5 trusted 右键无位移 click：contextmenu 被吞 + 无吸附位移 + 选中保持
const tc = await trustedRightClick(kh);
check('B5a trusted 右键 click contextmenu 被吞（svg listener fired≥1 prevented≥1）',
  tc.probed === true && tc.ctx.fired >= 1 && tc.ctx.prevented >= 1,
  JSON.stringify(tc.ctx || { probed: tc.probed }));
check('B5b trusted 右键无位移：points 不动（contact−1nm 位零位移吸附不动 points）+ 选中保持（指标面板在案）',
  tc.probed === true && tc.points === r1.points && tc.metrics === true, 'metrics=' + tc.metrics);
// 退化零位移吸附若触发伙伴高亮（900+300ms），等淡出再进 B6 的「无伙伴」断言
await sleep(1300);

// B6 右键继续拖离远端恢复自由（中点帧 + 拖动中合成 contextmenu 一并验证被吞）
const r4 = await dragPiece(kh, pick.R4[0] - pick.res1.tr[0], 2, true);
check('B6a 右键拖动中合成 contextmenu 被吞（defaultPrevented，拖动照常完成）',
  r4.ctxPrevented === true, 'prevented=' + r4.ctxPrevented);
const area4 = await metricsAreaNum();
check('B6b 右键拖离远端恢复自由：原样落点 + 无伙伴 + 指标 0.0',
  r4.points === expPts(pick.R4) && !r4.partner && area4 != null && area4 < 0.05, 'area=' + area4);

// B7 右键深叠松手 → retreat（DOM points == 引擎 tr）
const rr2 = await dragPiece(kh, pick.R2[0] - pick.R4[0], 2);
const partner2 = await page.evaluate(() => document.querySelector('[data-testid=edit-snap-partner]') !== null);
check('B7 右键深叠松手 retreat：DOM points == 引擎 tr（回退到首个安全界）',
  rr2.points === expPts(pick.res2.tr),
  '回退=' + (pick.res2.tr[0] - pick.R2[0]).toFixed(3) + 'mm');
const ov2 = overlapWithAll(rr2.points);
const area2 = await metricsAreaNum();
check('B8 retreat 终态干净（独立布尔交 < 50mm² vs 全邻居）+ 指标 0.0 + 伙伴在案',
  ov2 < 50 && area2 != null && area2 < 0.05 && partner2,
  '独立重叠=' + ov2.toFixed(2) + 'mm² 指标=' + area2);
await page.screenshot({ path: OUT + '/b7_retreat.png' });
await sleep(1300); // 伙伴高亮淡出，避免污染后续「无伙伴」红线断言

// ---------- R 左键零回归红线段（永不吸附） ----------
// R1 同深叠目标压线落点：原样保留、重叠 > 1000mm² 如实显示（左键永不 retreat）
const rl = await dragPiece(kh, pick.R2[0] - pick.res2.tr[0], 0);
const ovl = overlapWithAll(rl.points);
const areal = await metricsAreaNum();
check('R1 左键压线深叠红线：原样落点 + 重叠 > 1000mm² 如实保留 + 无伙伴（永不 retreat）',
  rl.points === expPts(pick.R2) && ovl > 1000 && !rl.partner && areal != null && areal > 900,
  '重叠=' + ovl.toFixed(0) + 'mm² 指标=' + areal);
// R2 同小缝目标落点：原样（左键永不 attract；y = 吸附链上 y，与 R1 同 x）
const rf = await dragPiece(kh, pick.R1f[0] - pick.R2[0], 0);
const areaf = await metricsAreaNum();
check('R2 左键小缝红线：原样落点（attract 永不发生）+ 无伙伴 + 指标 ~0',
  rf.points === expPts(pick.R1f) && !rf.partner && areaf != null && areaf < 0.05, 'area=' + areaf);

// ---------- C 末次吸附 → 保存 → 导出全精度贯通 ----------
// C1 从 R1f（5mm 缝位）右键再推 3mm 留 2mm 缝松手 → attract 回贴（保存终态）
const rc = await dragPiece(kh, pick.R1c[0] - pick.R1f[0], 2);
const partnerC = await page.evaluate(() => document.querySelector('[data-testid=edit-snap-partner]') !== null);
const areaC = await metricsAreaNum();
check('C1 末次右键 2mm 缝 attract 回贴：DOM points == 引擎 tr + 伙伴在案 + 指标 0.0',
  rc.points === expPts(pick.resF.tr) && partnerC && areaC != null && areaC < 0.05,
  '吸拢=' + (pick.R1c[0] - pick.resF.tr[0]).toFixed(3) + 'mm');
await page.screenshot({ path: OUT + '/c1_final_snap.png' });

// C2 保存（lastFrame = 吸附末态，编辑草稿落笔）
await page.click('[data-testid=edit-layout-save]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { state: 'detached', timeout: 5000 });
check('C2 吸附终态保存（弹窗关闭）', true);

// C3 导出 PLT（plt-clean 默认口径）
const exp1 = await exportOnce('plt-clean', 'C3');
const placed1 = exp1.reqBody?.placed || [];
const strokes1 = parsePltStrokes(exp1.respBody || '');

// C4 全精度贯通：导出 placed[KI].translation 与引擎吸附值（浮点事件链噪声 ≤ 1e-6mm、
//    y 分量逐位恒等（dy=0）、x 分量携带亚 0.01mm 精度（未被 DOM 显示口径截断）、
//    终态接触几何在导出值上复核（首触 ≈ 1nm + 全邻居布尔交 = 0）
const trOut = placed1[KI] && placed1[KI].translation ? placed1[KI].translation : null;
let c4ok = false;
let c4info = 'n/a';
if (trOut && placed1.length === EXPECT_TOTAL) {
  const dxErr = Math.abs(trOut[0] - pick.resF.tr[0]);
  const dyErr = Math.abs(trOut[1] - pick.resF.tr[1]); // 吸附沿质心连线 → y 与引擎值比对
  const dyExact = dyErr <= 1e-6;
  const subCm = trOut[0] !== r2(trOut[0]);
  const pkF = pick.resF.partnerKey;
  const wK = ENG.transformPolygon(kBase, pick.rotK, trOut, pick.mirK);
  const cK = centroidMean(wK);
  const wP = ENG.transformPolygon(pool0[pkF].basePolygon, pool0[pkF].rot, pool0[pkF].tr, pool0[pkF].mirror);
  const d = unit([centroidMean(wP)[0] - cK[0], centroidMean(wP)[1] - cK[1]]);
  const contactT = d ? ENG.firstContactDistance(wK, wP, d) : null;
  let contactOv = 0;
  for (let j = 0; j < worlds.length; j++) {
    if (j === KI) continue;
    contactOv = Math.max(contactOv, overlapArea(wK, worlds[j]));
  }
  c4ok = dxErr <= 1e-6 && dyExact && subCm
    && contactT != null && contactT >= 0 && contactT <= 1e-6 && contactOv < 1e-6
    && placed1[KI].rotation === items[KI].rotation
    && (placed1[KI].mirror === undefined) === (items[KI].mirror === undefined);
  c4info = 'dxErr=' + dxErr.toExponential(1) + 'mm dyErr=' + dyErr.toExponential(1) + 'mm'
    + ' 亚0.01mm=' + subCm
    + ' 接触t=' + (contactT == null ? 'null' : contactT.toExponential(1)) + 'mm'
    + ' maxOv=' + contactOv.toExponential(1) + 'mm²';
}
check('C4 placed 全精度贯通（translation |Δ|≤1e-6（x/y）& 亚 0.01mm 未截断 & 接触几何 t≈1nm/overlap=0 & rot/mirror 原样）',
  c4ok, c4info);

// C5 其余 29 项与求解末帧逐位全等（未动片零漂移）
const othersEq = placed1.length === EXPECT_TOTAL
  && placed1.every((p, j) => j === KI || JSON.stringify(p) === JSON.stringify(items[j]));
check('C5 其余 29 项 placed 与求解末帧逐位全等（未动片零漂移）', othersEq, 'n=' + placed1.length);

// C6 PLT 正文在案（笔画数允许小幅漂移 —— 被拖片标注笔画可被 gate 裁剪分裂、
//    表格数值字宽可变；正文结构断言在 C7/C8 收紧）
writeFileSync(OUT + '/plt_baseline.plt', exp0.respBody || '');
writeFileSync(OUT + '/plt_final.plt', exp1.respBody || '');
const pu1 = ((exp1.respBody || '').match(/^PU/gm) || []).length;
const dStrokes = strokes1.length - strokes0.length;
check('C6 PLT 正文在案（PU 笔 ≥100 + 笔画数 31+ 且与基线漂移 |Δ|≤12）',
  pu1 >= 100 && strokes1.length >= EXPECT_TOTAL + 1 && Math.abs(dStrokes) <= 12,
  'PU=' + pu1 + ' strokes=' + strokes0.length + '->' + strokes1.length + ' Δ=' + dStrokes);

// C7 PLT 回读：其余 29 片毛版轮廓笔画逐位全等（stroke[0]=门幅框随料长伸缩、
//    stroke[KI+1]=被拖片、后续标注/表格笔画随编辑几何联动 —— 均属预期差分；
//    轮廓区索引 = 1..30 按 placed 序稳定，未动片字节级不变是导出零回归的判据）
let othersStrokesEq = strokes0.length >= EXPECT_TOTAL + 1 && strokes1.length >= EXPECT_TOTAL + 1;
if (othersStrokesEq) {
  for (let j = 0; j < EXPECT_TOTAL; j++) {
    if (j === KI) continue;
    if (JSON.stringify(strokes1[j + 1]) !== JSON.stringify(strokes0[j + 1])) { othersStrokesEq = false; break; }
  }
}
check('C7 PLT 回读其余 29 片轮廓笔画逐位全等（未动片零回归）', othersStrokesEq);

// C8 PLT 回读：被拖片轮廓笔画 == 基线笔画平移吸附位移（±2 HPGL unit，x/y 两轴 ——
//    吸附沿质心连线，位移含 y 分量；_plt_pt 逐点取整 ⇒ 复合取整差 ≤1 unit，容 2）
const dxW = trOut ? trOut[0] - pick.t0[0] : 0;
const dyW = trOut ? trOut[1] - pick.t0[1] : 0;
let c8ok = false;
let c8err = 0;
if (trOut && strokes0.length > KI + 1 && strokes1.length > KI + 1) {
  const s0k = strokes0[KI + 1];
  const s1k = strokes1[KI + 1];
  if (s0k.length === s1k.length) {
    const dxU = Math.round(dxW * 40);
    const dyU = Math.round(dyW * 40);
    c8ok = true;
    for (let i = 0; i < s1k.length; i++) {
      const ex = Math.max(0, s0k[i][0] + dxU);
      const ey = s0k[i][1] + dyU;
      c8err = Math.max(c8err, Math.abs(ex - s1k[i][0]), Math.abs(ey - s1k[i][1]));
      if (Math.abs(ex - s1k[i][0]) > 2 || Math.abs(ey - s1k[i][1]) > 2) c8ok = false;
    }
  }
}
check('C8 PLT 回读被拖片轮廓笔画 == 基线平移吸附位移（±2 HPGL unit，x/y 两轴）',
  c8ok, 'dx=' + dxW.toFixed(3) + 'mm dy=' + dyW.toFixed(3) + 'mm err=' + c8err.toFixed(2) + 'unit');

// ---------- 汇总 ----------
writeFileSync(OUT + '/report.json', JSON.stringify({
  at: new Date().toISOString(),
  solve: { density: final1?.density, placed: EXPECT_TOTAL },
  pair: pick ? {
    k: pick.k, m: pick.m, pid: items[pick.k].id, gapMm: pick.g,
    attractDxMm: pick.R1[0] - pick.res1.tr[0],
    retreatBackMm: pick.res2.tr[0] - pick.R2[0],
    finalAttractDxMm: pick.R1c[0] - pick.resF.tr[0],
    partnerKeyFinal: pick.resF.partnerKey,
  } : null,
  exportChain: {
    predictedTr: pick ? pick.resF.tr : null,
    exportedTr: trOut,
    dxUnits: Math.round(dxW * 40),
    dyUnits: Math.round(dyW * 40),
    pltErrUnits: c8err,
  },
  results,
}, null, 2));
const failed = results.filter((r) => !r.ok);
console.log('\n==== edit-drag-snap 冒烟: ' + (results.length - failed.length) + '/' + results.length + ' PASS ====');
await browser.close();
process.exit(failed.length ? 1 : 0);

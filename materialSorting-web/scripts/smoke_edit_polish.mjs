// edit-polish US-004 端到端冒烟（prd-edit-polish，2026-09-05）—— 智能微调整条链路
// 回归锁死：上传 → per_type 放开 d/tol（制造重合与旋转）→ 短求解 → 编辑弹窗微调
// （报告四段 + 守恒不等式）→ 撤销恢复 → 再微调（确定性双跑全等）→ 保存 → 导出
// DXF/PLT placed 守恒（=Σdemand）→ band on 场景 exclude 生效（带形态区域不动）。
//
// 模板对齐 scripts/smoke_edit_layout.mjs（repo 根，Playwright 流程骨架/抓包套路）
// + smoke_prefix_extra.mjs（per_type 写值/导出格式切换）；浏览器 = Edge 通道
//（本机无 playwright 二进制，借系统通道 msedge，Chrome 兜底 —— 同目录其余冒烟同款）。
//
// 前置：ms-web 在 :8000 运行 + 新 static 构建（prod 模式）。
//
//   node materialSorting-web/scripts/smoke_edit_polish.mjs
//
// 相位：
//   S1 上传 5336 母版 → commit → per_type 全 g 码 d=3/tol=30（工艺余量制造重合与
//      旋转，polish 有实事可做）→ 超排 3 码（32/33/34，30 片）20s 求解 → final。
//   S2 编辑弹窗 → 智能微调：请求 200 + 载荷形态（placed 30/gate_mm/无 exclude 键）
//      + 报告四段 + 四守恒（overlap_pairs 严格下降、rotΣ 下降、width ≤ before、
//      density ≥ before−1e-6）+ 对比卡渲染。
//   S3 撤销微调：画布 points 逐片回微调前 + 卡清空。
//   S4 再微调：确定性双跑 —— placed 与 report（elapsed_sec 除外）与首次全等。
//   S5 保存 → 导出 PLT（默认 plt-clean）+ DXF：payload placed 条数 = Σdemand = 30
//      且与微调响应 placed 深相等（守恒）；DXF 正文 R12 POLYLINE 无 LWPOLYLINE。
//   S6 band on 场景抽验：per_type 开腰头成带 g05 → 重解 → 编辑弹窗微调 →
//      请求带 exclude.labels=['g05'] + 带形态区域（g05 全部毛版）points 前后不变
//      + report.excluded 恰覆盖 g05 实例。
//   S7 compact 压缩回收档（US-005）：对比卡内勾选「回收空隙缩短料长」→ 再微调
//      → 请求带 compact:true + width ≤ 非 compact 档（S6 结果）+ 密度不降 +
//      重合对不增 + placed 守恒。
//   S8 键盘/镜像段（edit-keyboard US-007）：S7 compact 结果保存 → 导出镜像前基线
//      DXF → 重开 → 合成 pointerdown 选中一片（按 points 内容寻址）→ O 键镜像
//      （DOM 恰改一片 + 质心锚定反射对拍）→ 保存 → 导出 PLT/DXF：placed 恰一项
//      mirror:true（其余 29 项逐位不动）+ **正文几何镜像坐标对拍**（镜像前 DXF
//      layer1 轮廓经 R·M·R⁻¹ 复合 = 镜像后正文轮廓，PLT ±2 HPGL unit / DXF
//      ±0.05mm，且非镜像反事实远离 = mirror 键真实驱动几何）→ 重开承接镜像片 →
//      微调 mirror 逐位透传 → R 键重置该片 points 逐字节回算法基线。
//
// 报告落 out/smoke_edit_polish/report.json；退出码 0 = 全 PASS。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

// 路径锚定脚本位置（任意 CWD 可跑）：materialSorting-web/ -> repo 根
const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');

const { chromium } = await import('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF = ROOT + '/data/5336#老六订单14%7%围加9.dxf';
const OUT = ROOT + '/out/smoke_edit_polish';
const SIZES = [32, 33, 34]; // 5336 码集；3 码 × 10 片 = 30 片（Σdemand 默认 1/格）
const SOLVE_TIME = '20';
const BAND_LABEL = 'g05';
const EXPECT_TOTAL = 30;

mkdirSync(OUT, { recursive: true });
// Edge 通道（Win11 必有），Chrome 兜底 —— 同目录其余冒烟同款
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true });
} catch {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
}
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
const results = [];
function check(name, ok, extra = '') {
  results.push({ name, ok, extra: String(extra) });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 200) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function dismissTour(p, rounds = 6) {
  for (let i = 0; i < rounds; i++) {
    const gone = await p.evaluate(() => document.querySelector('[data-testid=tour-overlay]') === null);
    if (gone) return;
    await p.evaluate(() => {
      const btn = document.querySelector('[data-testid=tour-skip]');
      if (btn) btn.click();
    });
    await p.waitForTimeout(600);
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
function frameText(f) {
  if (typeof f === 'string') return f;
  if (f && typeof f.payload === 'string') return f.payload;
  if (f && f.payload != null && typeof f.payload === 'object') return String.fromCharCode(...f.payload);
  return '';
}
const cap = { msgs: [] };
page.on('websocket', (ws) => {
  ws.on('framereceived', (f) => {
    try { cap.msgs.push(JSON.parse(frameText(f))); } catch { /* 非 JSON 忽略 */ }
  });
});
async function waitMsg(type, timeout = 120000) {
  const t0 = Date.now();
  for (;;) {
    const m = cap.msgs.find((x) => x && x.type === type);
    if (m) return m;
    if (Date.now() - t0 > timeout) return null;
    await sleep(500);
  }
}
/** 弹窗内全部毛版 polygon（US-003 教训：提层后 DOM 序 ≠ working 序 —— points 寻址）。 */
const roughPoints = () => page.evaluate(() => {
  const g = document.querySelector('svg.edit-layout-svg g');
  return Array.from(g.querySelectorAll('polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55')
    .map((p) => p.getAttribute('points'));
});
/** 弹窗内按 data-label 过滤的毛版 polygon points（band 带形态区域快照用）。 */
const labelPoints = (label) => page.evaluate((lb) => {
  const g = document.querySelector('svg.edit-layout-svg g');
  return Array.from(g.querySelectorAll('polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55' && p.dataset.label === lb)
    .map((p) => p.getAttribute('points'));
}, label);
// ---------- edit-keyboard US-007 S8 段共用算子（纯 Node 侧，零页面依赖） ----------
/** r2/pointsStr：lib/geometry.ts 逐字节复刻（prod 构建无法页面内 import 源码模块；
 *  Math.round(x*100)/100 + V8 Number→string 与前端同引擎同语义）—— 用于按 points
 *  内容寻址毛版 polygon（working 下标 ↔ DOM 元素，提层置顶后 DOM 序不可用）与
 *  R 键基线串对拍。 */
const r2 = (x) => Math.round(x * 100) / 100;
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
/** points 串 → [[x,y],...]（世界坐标；EditCanvas 顶点均值质心同款累加顺序）。 */
const parsePts = (s) => s.trim().split(/\s+/).map((p) => p.split(',').map(Number));
const centroidMean = (pts) => {
  let x = 0;
  let y = 0;
  for (const p of pts) {
    x += p[0];
    y += p[1];
  }
  const n = Math.max(1, pts.length);
  return [x / n, y / n];
};
const rotCs = (deg) => {
  const r = (deg * Math.PI) / 180;
  return [Math.cos(r), Math.sin(r)];
};
/** 反射矩阵 H = R(θ)·diag(−1,1)·R(−θ)（O 键镜面在世界系的表达；det=−1）。 */
const reflH = (rot) => {
  const [c, s] = rotCs(rot);
  return [[s * s - c * c, -2 * c * s], [-2 * c * s, c * c - s * s]];
};
/** 排序串数组的鲁棒多重集差（O 键/R 键「恰改一片」判据）。 */
function multisetDiff(aSorted, bSorted) {
  const removed = [];
  const added = [];
  let i = 0;
  let j = 0;
  while (i < aSorted.length && j < bSorted.length) {
    if (aSorted[i] === bSorted[j]) {
      i++;
      j++;
    } else if (aSorted[i] < bSorted[j]) {
      removed.push(aSorted[i]);
      i++;
    } else {
      added.push(bSorted[j]);
      j++;
    }
  }
  while (i < aSorted.length) removed.push(aSorted[i++]);
  while (j < bSorted.length) added.push(bSorted[j++]);
  return { removed, added };
}
/** R12 ASCII DXF → layer '1' 闭合 POLYLINE 顶点列（placed 序；门幅边框无 layer 键
 *  落缺省 '0' 不入列，净版 14/内部线 8 同理过滤）。整文件 code/value 严格成对
 *  （含 SECTION 头），ENTITIES 段起两两步进。 */
function parseDxfOutlines(text) {
  const lines = text.split(/\r\n|\r|\n/);
  let start = 0;
  for (let i = 0; i + 1 < lines.length; i += 2) {
    if (lines[i].trim() === '0' && lines[i + 1].trim() === 'ENTITIES') {
      start = i + 2;
      break;
    }
  }
  const outlines = [];
  let cur = null;
  for (let i = start; i + 1 < lines.length; i += 2) {
    const code = lines[i].trim();
    const val = lines[i + 1].trim();
    if (code === '0') {
      if (val === 'POLYLINE') cur = { layer: null, verts: [] };
      else if (val === 'VERTEX' && cur) cur.verts.push(null);
      else if ((val === 'SEQEND' || val === 'ENDSEC') && cur) {
        if (cur.layer === '1' && cur.verts.length) outlines.push(cur.verts);
        cur = null;
        if (val === 'ENDSEC') break;
      } else if (val !== 'VERTEX') {
        cur = null; // TEXT/LINE/POINT 等实体头（毛版 POLYLINE 已 SEQEND 收口）
      }
    } else if (cur) {
      if (code === '8') cur.layer = val;
      else if (code === '10' && cur.verts.length && cur.verts[cur.verts.length - 1] === null) {
        cur.verts[cur.verts.length - 1] = [parseFloat(val), null];
      } else if (code === '20' && cur.verts.length) {
        const last = cur.verts[cur.verts.length - 1];
        if (Array.isArray(last) && last[1] === null) last[1] = parseFloat(val);
      }
    }
  }
  return outlines;
}
/** PLT/HPGL 正文 → 笔画列表（PU 起新笔、PD 续画；毛版 clean 版层序 = 门幅框 +
 *  30 片毛版轮廓（placed 序）在前，标注笔画/表格在后 ⇒ stroke[0]=边框、
 *  stroke[k+1]=placed[k] 毛版轮廓，PD ≤10 点分块自动拼接）。 */
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
/** 按 points 内容寻址选中（合成 pointerdown 直发毛版 polygon + up 冒泡 svg ——
 *  真实 hit-testing 会被叠片抢 target，usk006 verify 同款确定性寻址）。 */
const selectByPoints = (want) => page.evaluate((want) => {
  const svg = document.querySelector('svg.edit-layout-svg');
  if (!svg) return false;
  const poly = Array.from(svg.querySelectorAll('g > polygon'))
    .filter((p) => p.getAttribute('fill-opacity') === '0.55')
    .find((p) => p.getAttribute('points') === want);
  if (!poly) return false;
  const r = svg.getBoundingClientRect();
  poly.dispatchEvent(new PointerEvent('pointerdown',
    { bubbles: true, pointerId: 11, clientX: r.x + 40, clientY: r.y + 40 }));
  svg.dispatchEvent(new PointerEvent('pointerup',
    { bubbles: true, pointerId: 11, clientX: r.x + 40, clientY: r.y + 40 }));
  return true;
}, want);
/** 键盘前置：blur 聚焦控件（按钮点击后 activeElement=BUTTON 会命中守卫②全键禁用）。 */
const blurActive = () => page.evaluate(() => {
  if (document.activeElement && document.activeElement !== document.body) {
    document.activeElement.blur();
  }
  return true;
});
/** 抓一次微调：点击按钮 → 等待 /api/edit-polish 响应（请求载荷 + body 双捕获）。 */
async function polishOnce() {
  let reqBody = null;
  let respBody = null;
  const handler = async (r) => {
    if (!r.url().endsWith('/api/edit-polish')) return;
    try { reqBody = JSON.parse(r.request().postData()); } catch { reqBody = null; }
    try { respBody = await r.json(); } catch { respBody = null; }
  };
  page.on('response', handler);
  await page.click('[data-testid=edit-polish-btn]');
  for (let i = 0; i < 120 && !respBody; i++) await sleep(500);
  page.off('response', handler);
  return { reqBody, respBody };
}
/** 点选格式 → 导出 → 抓 POST /export 请求载荷与响应正文。PLT 族走 ExportInfoModal
 *  确认（ControlPanel.handleExport 分流：plt/plt-clean 才开弹窗）；DXF 直发无弹窗。
 *  响应正文 = 页内 fetch 包装捕获（apiFetch 走 window.fetch 单点；Playwright 网络层
 *  对 fetch→blob 消费后的附件响应 body 常拿不到 —— smoke_prefix_extra __fetchCaps 同套路）。 */
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
  // 等网络层 captured + 页内包装正文落定（body 走 res.clone()，晚于响应事件）
  for (let i = 0; i < 60; i++) {
    const n = await page.evaluate(() => (window.__exportCaps || []).length);
    if (captured && n > 0) break;
    await sleep(500);
  }
  const caps = await page.evaluate(() => window.__exportCaps || []);
  // 还原 fetch（避免包装层影响后续路径断言）
  await page.evaluate(() => {
    if (window.__exportOrigFetch) window.fetch = window.__exportOrigFetch;
  });
  page.off('response', onResp);
  const cap = caps[caps.length - 1] || { bytes: 0, text: '' };
  const respBody = cap.text || '';
  const cd = captured ? (captured.headers()['content-disposition'] || '') : '';
  let reqBody = null;
  try { reqBody = captured ? captured.request().postDataJSON() : null; } catch { reqBody = null; }
  check(tag + ' POST /export 200（.' + fmt.replace('plt-clean', 'plt') + ' 附件）',
    !!captured && captured.status() === 200
      && decodeURIComponent(cd).includes('.' + fmt.replace('plt-clean', 'plt')),
    captured ? captured.status() + ' ' + decodeURIComponent(cd).slice(0, 60) : 'no response');
  return { reqBody, respBody };
}

// ---------- S1 上传 5336 + per_type 放开 d/tol + 短求解 ----------
await page.goto(BASE, { waitUntil: 'networkidle' });
const sid = await page.evaluate(() => localStorage.getItem('ms_sid'));
check('S0 页面加载落会话 sid', /^[0-9a-f]{32}$/.test(sid || ''), (sid || '').slice(0, 8));

await dismissTour(page);
await page.locator('input[type=file]').first().setInputFiles(DXF);
await page.waitForSelector('button.tab:not([disabled]):has-text("超排")', { timeout: 240000 });
let committed = false;
let ptypesBody = null;
for (let i = 0; i < 80; i++) {
  const r = await rawFetch(page, '/api/ptypes', { headers: { 'X-Session-Id': sid }, cache: 'no-store' });
  if (r.status === 200 && Object.keys(r.body?.representatives || {}).length > 0) {
    committed = true; ptypesBody = r.body; break;
  }
  await sleep(3000);
}
check('S1a 上传 5336 + commit 完成（ptypes 非空）', committed,
  ptypesBody ? 'labels=' + Object.keys(ptypesBody.representatives).join(',') : 'no ptypes');

await page.click('button.tab:has-text("超排")');
await sleep(800);
await dismissTour(page);
// 高级配置：全部 g 码 d=3mm / tol=30°（制造工艺余量重合与旋转，polish 有实事可做）
await page.click('[data-testid=per-type-btn]');
await page.waitForSelector('[data-testid=per-type-overlay]', { timeout: 5000 });
const labels = await page.evaluate(() => {
  const els = document.querySelectorAll('[data-testid^="d-"]');
  return Array.from(els).map((e) => e.getAttribute('data-testid').slice(2));
});
for (const lb of labels) {
  await page.fill(`[data-testid="d-${lb}"]`, '3');
  await page.fill(`[data-testid="tol-${lb}"]`, '30');
}
await page.click('[data-testid=per-type-confirm]');
await sleep(400);
for (const sz of SIZES) await page.check('#sz_' + sz);
await page.fill('#time', SOLVE_TIME);
await page.click('#start');
const final1 = await waitMsg('final', 150000);
const solverPlaced = cap.msgs.filter((x) => x && x.type === 'frame').slice(-1)[0]?.placed_items || [];
check('S1b 短求解 20s 出 final（3 码 30 片 = Σdemand）',
  !!final1 && solverPlaced.length === EXPECT_TOTAL,
  final1 ? 'density=' + final1.density.toFixed(4) + ' placed=' + solverPlaced.length : 'no final');

// ---------- S2 编辑弹窗 + 智能微调（报告四段 + 守恒不等式） ----------
await page.click('[data-testid=edit-controls-edit]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { timeout: 5000 });
check('S2a 编辑弹窗打开 + 工具区智能微调按钮在案',
  await page.evaluate(() => {
    const tools = document.querySelector('.edit-layout-canvas-tools');
    const btn = document.querySelector('[data-testid=edit-polish-btn]');
    return !!tools && !!btn && tools.contains(btn) && !btn.disabled;
  }));
await page.screenshot({ path: OUT + '/s2_before_polish.png' });
const pointsBefore = await roughPoints();

const p1 = await polishOnce();
const rep1 = p1.respBody?.report || {};
const ok1 = p1.respBody?.ok === true;
check('S2b 微调请求 200 + 载荷形态（placed 30 / gate_mm / 无 exclude 键）+ 报告四段',
  ok1 && p1.reqBody?.placed?.length === EXPECT_TOTAL && p1.reqBody?.gate_mm > 0
    && !('exclude' in p1.reqBody) && !!rep1.before && !!rep1.after
    && Array.isArray(rep1.moves) && Array.isArray(rep1.residual),
  'placed=' + p1.reqBody?.placed?.length + ' gate=' + p1.reqBody?.gate_mm
    + ' overlap ' + rep1.before?.overlap_pairs + '->' + rep1.after?.overlap_pairs
    + ' rotΣ ' + rep1.before?.rotation_dev_sum_deg + '->' + rep1.after?.rotation_dev_sum_deg
    + ' width ' + rep1.before?.width_mm + '->' + rep1.after?.width_mm
    + ' density ' + rep1.before?.density + '->' + rep1.after?.density
    + ' moves=' + rep1.moves?.length + ' residual=' + rep1.residual?.length);
check('S2c 重合对下降（after < before，或可解时 =0）',
  rep1.after?.overlap_pairs < rep1.before?.overlap_pairs
    || rep1.after?.overlap_pairs === 0,
  rep1.before?.overlap_pairs + ' -> ' + rep1.after?.overlap_pairs);
check('S2d 旋转偏差 Σ 下降（after < before）',
  rep1.after?.rotation_dev_sum_deg < rep1.before?.rotation_dev_sum_deg,
  rep1.before?.rotation_dev_sum_deg + ' -> ' + rep1.after?.rotation_dev_sum_deg + '°');
check('S2e 料长不增（after.width ≤ before.width）',
  rep1.after?.width_mm <= rep1.before?.width_mm + 1e-9,
  rep1.before?.width_mm + ' -> ' + rep1.after?.width_mm + 'mm');
check('S2f 密度不降（after ≥ before − 1e-6）',
  rep1.after?.density >= rep1.before?.density - 1e-6,
  rep1.before?.density + ' -> ' + rep1.after?.density + '%');
check('S2g 对比卡渲染（六指标前→后 + 撤销按钮 + 按钮title口径注记）',
  await page.evaluate(() => {
    const card = document.querySelector('[data-testid=edit-polish-card]');
    if (!card) return false;
    const ids = ['edit-polish-overlap', 'edit-polish-depth', 'edit-polish-rot',
      'edit-polish-rotsum', 'edit-polish-width', 'edit-polish-density'];
    // 口径注记 2026-09-05 三轮迭代起在按钮 title 悬浮（卡内可见脚注已移除不占空间）
    const btnTitle = document.querySelector('[data-testid=edit-polish-btn]')
      ?.getAttribute('title') || '';
    return ids.every((id) => {
        const el = card.querySelector('[data-testid=' + id + ']');
        return el && el.textContent.includes('→');
      })
      && !card.textContent.includes('物理毛版轮廓口径')
      && btnTitle.includes('物理毛版轮廓口径')
      && !!card.querySelector('[data-testid=edit-polish-undo]');
  }));
await page.screenshot({ path: OUT + '/s2_polish_report.png' });

// ---------- S3 撤销微调（画布 points 回微调前 + 卡清空） ----------
await page.click('[data-testid=edit-polish-undo]');
await sleep(400);
const pointsUndone = await roughPoints();
const undoneEqual = pointsBefore.length === pointsUndone.length
  && pointsBefore.every((p, i) => p === pointsUndone[i]);
check('S3a 撤销恢复快照（points 逐片回微调前）+ 卡清空/撤销按钮消失',
  undoneEqual && await page.evaluate(() =>
    document.querySelector('[data-testid=edit-polish-card]') === null),
  'pointsEqual=' + undoneEqual);
await page.screenshot({ path: OUT + '/s3_after_undo.png' });

// ---------- S4 再微调：确定性双跑全等（placed + report 除 elapsed_sec） ----------
const p2 = await polishOnce();
const rep2 = p2.respBody?.report || {};
const strip = (r) => {
  const c = { ...r };
  delete c.elapsed_sec;
  return c;
};
const placedEqual = JSON.stringify(p1.respBody?.placed) === JSON.stringify(p2.respBody?.placed);
const reportEqual = JSON.stringify(strip(rep1)) === JSON.stringify(strip(rep2));
check('S4a 确定性双跑全等（placed 深相等 + report 除 elapsed_sec 全等）',
  p2.respBody?.ok === true && placedEqual && reportEqual,
  'placed=' + placedEqual + ' report=' + reportEqual
    + ' moves1=' + rep1.moves?.length + ' moves2=' + rep2.moves?.length);

// ---------- S5 保存 → 导出 PLT + DXF（placed 守恒 = Σdemand） ----------
await page.click('[data-testid=edit-layout-save]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { state: 'detached', timeout: 5000 });
check('S5a 微调结果保存（弹窗关闭）', true);
const expPlt = await exportOnce('plt-clean', 'S5b');
const placedConserved = expPlt.reqBody?.placed?.length === EXPECT_TOTAL
  && JSON.stringify(expPlt.reqBody?.placed) === JSON.stringify(p2.respBody?.placed);
check('S5c PLT 导出 placed 守恒（条数 = Σdemand = 30 且与微调响应 placed 深相等）',
  placedConserved,
  'len=' + expPlt.reqBody?.placed?.length
    + ' deepEqual=' + (JSON.stringify(expPlt.reqBody?.placed) === JSON.stringify(p2.respBody?.placed)));
check('S5d PLT 正文在案（PU 笔 ≥100）',
  ((expPlt.respBody || '').match(/^PU/gm) || []).length >= 100,
  'bytes=' + (expPlt.respBody || '').length);
const expDxf = await exportOnce('dxf', 'S5e');
const placedConservedDxf = expDxf.reqBody?.placed?.length === EXPECT_TOTAL
  && JSON.stringify(expDxf.reqBody?.placed) === JSON.stringify(p2.respBody?.placed);
check('S5f DXF 导出 placed 守恒（条数 = 30 且与微调响应 placed 深相等）',
  placedConservedDxf, 'len=' + expDxf.reqBody?.placed?.length);
check('S5g DXF 正文 R12 POLYLINE（无 LWPOLYLINE —— ET2008 兼容口径）',
  (expDxf.respBody || '').includes('POLYLINE') && !(expDxf.respBody || '').includes('LWPOLYLINE'),
  'bytes=' + (expDxf.respBody || '').length);

// ---------- S6 band on 场景抽验：exclude 生效 + 带形态区域 bbox 前后不变 ----------
await page.click('[data-testid=per-type-btn]');
await page.waitForSelector('[data-testid=per-type-overlay]', { timeout: 5000 });
await page.check('[data-testid=band-enabled]', { force: true });
await page.selectOption('[data-testid=band-label-select]', BAND_LABEL);
await sleep(600); // 等成带预演缩略三态落定（预演不阻塞确定）
await page.click('[data-testid=per-type-confirm]');
await sleep(400);
for (const sz of SIZES) {
  const checked = await page.isChecked('#sz_' + sz);
  if (!checked) await page.check('#sz_' + sz);
}
await page.fill('#time', SOLVE_TIME);
cap.msgs.length = 0;
// 求解后 phase=done → 按钮是 #restart（SolveControls 五态钩子；idle 期才是 #start）
await page.click('#restart, #start');
const final2 = await waitMsg('final', 150000);
const solverPlaced2 = cap.msgs.filter((x) => x && x.type === 'frame').slice(-1)[0]?.placed_items || [];
const bandCount = solverPlaced2.filter((p) => p.id.startsWith(BAND_LABEL + '_')).length;
check('S6a band on 重解出 final（30 片，其中 ' + BAND_LABEL + ' ' + bandCount + ' 片）',
  !!final2 && solverPlaced2.length === EXPECT_TOTAL && bandCount === SIZES.length,
  final2 ? 'density=' + final2.density.toFixed(4) + ' placed=' + solverPlaced2.length : 'no final');

await page.click('[data-testid=edit-controls-edit]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { timeout: 5000 });
const bandBefore = await labelPoints(BAND_LABEL);
check('S6b 编辑弹窗内带形态区域快照（g05 毛版 ' + bandBefore.length + ' 片在案）',
  bandBefore.length === bandCount, 'n=' + bandBefore.length);
// S8 备档：首开时刻全量毛版 points 多重集（= 算法基线渲染；R 键重置的「回基线」
// 逐字节判据之一 —— 重置后的 points 串必在本快照内）。
const m6Points = await roughPoints();
const p3 = await polishOnce();
const rep3 = p3.respBody?.report || {};
check('S6c 微调请求带 exclude.labels=[' + BAND_LABEL + ']（band 记录 → labels 键）',
  p3.respBody?.ok === true && Array.isArray(p3.reqBody?.exclude?.labels)
    && p3.reqBody.exclude.labels.length === 1 && p3.reqBody.exclude.labels[0] === BAND_LABEL,
  'exclude=' + JSON.stringify(p3.reqBody?.exclude));
const bandAfter = await labelPoints(BAND_LABEL);
const bandUnchanged = bandBefore.length === bandAfter.length
  && bandBefore.every((p, i) => p === bandAfter[i]);
check('S6d 带形态区域前后不变（g05 全部毛版 points 逐一相同 —— exclude 生效）',
  bandUnchanged, 'n=' + bandAfter.length + ' unchanged=' + bandUnchanged);
const excludedIdx = rep3.excluded || [];
const expectedExcluded = solverPlaced2
  .map((p, i) => (p.id.startsWith(BAND_LABEL + '_') ? i : -1)).filter((i) => i >= 0);
check('S6e report.excluded 恰覆盖 g05 实例（引擎排除语义对拍）',
  JSON.stringify(excludedIdx) === JSON.stringify(expectedExcluded),
  'excluded=' + JSON.stringify(excludedIdx) + ' expected=' + JSON.stringify(expectedExcluded));
await page.screenshot({ path: OUT + '/s6_band_exclude.png' });

// ---------- S7 compact 压缩回收档（US-005）：勾选 checkbox → 再微调 ----------
// S6 微调后对比卡在案（checkbox 随卡渲染，默认不勾）；勾选 → compact:true 随
// 下次微调请求发出。断言（AC 口径）：width ≤ 非 compact 档（rep3.after，同一
// working 上的非 compact 微调结果）+ 本轮守恒不等式（width 不增/密度不降/
// 重合对不增）+ placed 条数守恒。
const cbBefore = await page.isChecked('[data-testid="edit-polish-compact"]');
check('S7a compact checkbox 随对比卡渲染且默认不勾', cbBefore === false);
await page.check('[data-testid="edit-polish-compact"]');
check('S7b 勾选态受控在案', await page.isChecked('[data-testid="edit-polish-compact"]') === true);
const p4 = await polishOnce();
const rep4 = p4.respBody?.report || {};
check('S7c compact 微调请求 200 + 载荷 compact:true + placed 守恒',
  p4.respBody?.ok === true && p4.reqBody?.compact === true
    && p4.respBody?.placed?.length === EXPECT_TOTAL,
  'compact=' + p4.reqBody?.compact + ' placed=' + p4.respBody?.placed?.length
    + ' width ' + rep4.before?.width_mm + '->' + rep4.after?.width_mm
    + ' density ' + rep4.before?.density + '->' + rep4.after?.density
    + ' overlap ' + rep4.before?.overlap_pairs + '->' + rep4.after?.overlap_pairs);
check('S7d compact 后料长 ≤ 非 compact 档（width ≤ S6 微调结果）',
  rep4.after?.width_mm <= rep3.after?.width_mm + 1e-6,
  'compact=' + rep4.after?.width_mm + ' vs 非 compact=' + rep3.after?.width_mm + 'mm');
check('S7e compact 守恒不等式（本轮 width 不增 / 密度不降 / 重合对不增）',
  rep4.after?.width_mm <= rep4.before?.width_mm + 1e-9
    && rep4.after?.density >= rep4.before?.density - 1e-6
    && rep4.after?.overlap_pairs <= rep4.before?.overlap_pairs,
  'width ' + rep4.before?.width_mm + '->' + rep4.after?.width_mm
    + ' density ' + rep4.before?.density + '->' + rep4.after?.density);
await page.screenshot({ path: OUT + '/s7_compact.png' });

// ---------- S8 键盘/镜像段（edit-keyboard US-007）：O 镜像 → 保存 → 导出几何
// 对拍 → 微调透传 → R 重置。S7 结束态 = 弹窗在案（compact 微调结果未保存），
// 先保存落 lastFrame 再导出「镜像前基线」DXF —— 镜像几何对拍的两端：
//   期望(k) = R(θ1)·M·R(−θ0)·(oldDXF顶点 − t0) + t1（θ/t 取两次导出 POST placed[k]，
//   oldDXF = 镜像前导出 layer1 轮廓[k] = R(θ0)·p_raw + t0 的 0.01mm 舍入值）
// —— 与后端 export_geometry.apply_transform mirror 分支同公式，不依赖 intermediate
//    磁盘文件（会话几何真相随请求走），同时算「非镜像反事实」证明 mirror 键真实
//    驱动几何（不是任何平移都能凑上的平凡匹配）。
await page.click('[data-testid=edit-layout-save]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { state: 'detached', timeout: 5000 });
check('S8a S7 compact 结果保存（弹窗关闭，lastFrame = 微调末态）', true);
const expPre = await exportOnce('dxf', 'S8b');
const preEqual = JSON.stringify(expPre.reqBody?.placed) === JSON.stringify(p4.respBody?.placed);
check('S8c 镜像前基线导出 placed 守恒（= S7 compact 微调响应 placed 深相等）',
  expPre.reqBody?.placed?.length === EXPECT_TOTAL && preEqual,
  'len=' + expPre.reqBody?.placed?.length + ' deepEqual=' + preEqual);
const outlinesPre = parseDxfOutlines(expPre.respBody || '');
check('S8d 镜像前 DXF layer1 闭合轮廓在案（恰 30 片毛版 placed 序；边框落缺省 layer0）',
  outlinesPre.length === EXPECT_TOTAL, 'n=' + outlinesPre.length);

// 选片 k：镜像预测不触门幅（raw 毛版留 ≥2mm —— PLT y≤gate 裁剪/前端 clamp 双防线）
// + 镜像可辨位移 ≥20mm（反事实远离）+ 非带排除片（g05 在微调 exclude 集内，透传
// 断言走非排除路径更有区分度）。预测锚 = eroded 质心（O 键 cWorld 同源），
// newRaw = cWorld + H·(oldRaw − cWorld)（H = R(θ)·M·R(−θ)，θ = placed rotation）。
const manifestS6 = cap.msgs.filter((x) => x && x.type === 'manifest').slice(-1)[0] || null;
const polyByPid = new Map((manifestS6?.pieces || []).map((p) => [p.id, p.polygon]));
const gateS8 = expPre.reqBody?.gate_mm || 0;
const placedPre = expPre.reqBody?.placed || [];
let pickK = -1;
let pickMargin = -1e9;
let pickInfo = 'none';
for (const relax of [false, true]) {
  for (let i = 0; i < placedPre.length && i < outlinesPre.length; i++) {
    const pts = outlinesPre[i];
    const poly = polyByPid.get(placedPre[i]?.id);
    if (!pts || pts.length < 4 || !poly) continue;
    // eroded 质心（世界系）：O 键 applyKeyTransform 的 cWorld 同源（顶点均值）
    const [ca, sa] = rotCs(placedPre[i].rotation);
    const cw = centroidMean(poly.map((p) => [
      p[0] * ca - p[1] * sa + placedPre[i].translation[0],
      p[0] * sa + p[1] * ca + placedPre[i].translation[1],
    ]));
    const H = reflH(placedPre[i].rotation);
    let yMin = 1e9;
    let yMax = -1e9;
    let xMin = 1e9;
    let disp = 0;
    for (const v of pts) {
      const dx = v[0] - cw[0];
      const dy = v[1] - cw[1];
      const rx = cw[0] + H[0][0] * dx + H[0][1] * dy;
      const ry = cw[1] + H[1][0] * dx + H[1][1] * dy;
      yMin = Math.min(yMin, ry);
      yMax = Math.max(yMax, ry);
      xMin = Math.min(xMin, rx);
      disp = Math.max(disp, Math.hypot(rx - v[0], ry - v[1]));
    }
    const margin = Math.min(yMin, gateS8 - yMax, xMin);
    const band = String(placedPre[i]?.id || '').startsWith(BAND_LABEL + '_');
    if (band && !relax) continue;
    if (margin < (relax ? 0.2 : 2) || disp < (relax ? 5 : 20)) continue;
    if (margin > pickMargin) {
      pickMargin = margin;
      pickK = i;
      pickInfo = 'k=' + i + ' ' + placedPre[i].id + ' margin=' + margin.toFixed(1)
        + 'mm disp=' + disp.toFixed(0) + 'mm rot=' + placedPre[i].rotation + '°';
    }
  }
  if (pickK >= 0) break;
}
check('S8e 镜像选片决策在案（eroded 质心锚定预测不触门幅 ≥2mm + 镜像可辨 ≥20mm + 非带排除片）',
  pickK >= 0 && !!manifestS6, pickInfo);

// 重开承接 → 按 points 内容寻址选中 → O 键镜像（trusted keydown）。
await page.click('[data-testid=edit-controls-edit]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { timeout: 5000 });
const pidK = placedPre[pickK]?.id || '';
const polyK = polyByPid.get(pidK) || null;
const wantPre = polyK && placedPre[pickK]
  ? pointsStrJs(polyK, placedPre[pickK].rotation, placedPre[pickK].translation, false)
  : null;
const roughBeforeO = (await roughPoints()).slice().sort();
check('S8f 重开弹窗承接 compact 保存态（选中片 points 内容匹配恰 1 片）',
  !!wantPre && roughBeforeO.filter((s) => s === wantPre).length === 1,
  'pid=' + pidK + ' match=' + roughBeforeO.filter((s) => s === wantPre).length);
const selOk1 = wantPre ? await selectByPoints(wantPre) : false;
await sleep(300);
check('S8g 合成 pointerdown 选中（重合指标面板在案）',
  selOk1 === true && await page.evaluate(() =>
    document.querySelector('[data-testid=edit-metrics]') !== null));
await blurActive();
await page.keyboard.press('o');
await sleep(300);
const roughAfterO = (await roughPoints()).slice().sort();
const diffO = multisetDiff(roughBeforeO, roughAfterO);
const oldO = diffO.removed[0] || '';
const newO = diffO.added[0] || '';
let reflErr = 1e9;
if (diffO.removed.length === 1 && diffO.added.length === 1) {
  const a = parsePts(oldO);
  const b = parsePts(newO);
  if (a.length === b.length && a.length > 0) {
    const c = centroidMean(a); // eroded 世界顶点均值 = O 键锚（画布渲染即 eroded 轮廓）
    const H = reflH(placedPre[pickK].rotation);
    reflErr = 0;
    for (let i = 0; i < a.length; i++) {
      const dx = a[i][0] - c[0];
      const dy = a[i][1] - c[1];
      reflErr = Math.max(reflErr, Math.hypot(
        c[0] + H[0][0] * dx + H[0][1] * dy - b[i][0],
        c[1] + H[1][0] * dx + H[1][1] * dy - b[i][1]));
    }
  }
}
check('S8h O 键镜像恰改一片（多重集差 1 出 1 进 + 新 points = 质心锚定反射对拍 θ=rot）',
  diffO.removed.length === 1 && diffO.added.length === 1 && oldO === wantPre && reflErr <= 0.05,
  'out/in=' + diffO.removed.length + '/' + diffO.added.length
    + ' reflErr=' + reflErr.toFixed(4) + 'mm');
await page.screenshot({ path: OUT + '/s8_o_mirrored.png' });
await page.click('[data-testid=edit-layout-save]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { state: 'detached', timeout: 5000 });

// 导出 PLT（毛版 clean）+ DXF：placed 恰一项 mirror:true + 正文几何镜像坐标对拍。
const expMirPlt = await exportOnce('plt-clean', 'S8i');
const expMirDxf = await exportOnce('dxf', 'S8j');
const placedPlt = expMirPlt.reqBody?.placed || [];
const placedDxf = expMirDxf.reqBody?.placed || [];
const mirIdxPlt = placedPlt.map((p, i) => (p.mirror === true ? i : -1)).filter((i) => i >= 0);
const mirIdxDxf = placedDxf.map((p, i) => (p.mirror === true ? i : -1)).filter((i) => i >= 0);
// 质心锚定补偿对拍（eroded 口径与 O 键 applyKeyTransform 同源：t' = cWorld − R·M·cLocal）
let anchorErr = 1e9;
if (polyK && placedPre[pickK] && placedPlt[pickK]) {
  const it0 = placedPre[pickK];
  const it1 = placedPlt[pickK];
  const [ca, sa] = rotCs(it0.rotation);
  const cw = centroidMean(polyK.map((p) => [
    p[0] * ca - p[1] * sa + it0.translation[0],
    p[0] * sa + p[1] * ca + it0.translation[1],
  ]));
  const [cb, sb] = rotCs(it1.rotation);
  const cl = centroidMean(polyK.map((p) => [-p[0] * cb - p[1] * sb, -p[0] * sb + p[1] * cb]));
  anchorErr = Math.max(
    Math.abs(cw[0] - cl[0] - it1.translation[0]),
    Math.abs(cw[1] - cl[1] - it1.translation[1]));
}
const othersEqual = placedPlt.length === EXPECT_TOTAL && pickK >= 0
  && placedPlt.every((p, i) => i === pickK || JSON.stringify(p) === JSON.stringify(placedPre[i]));
check('S8k 导出 placed 恰一项 mirror:true（下标=选中片 + rot 不变 + 质心锚定补偿 ≤1e-6 + 其余 29 项与镜像前逐位全等 + PLT/DXF 载荷一致）',
  mirIdxPlt.length === 1 && mirIdxPlt[0] === pickK
    && mirIdxDxf.length === 1 && mirIdxDxf[0] === pickK
    && placedPlt[pickK]?.id === pidK
    && placedPlt[pickK]?.rotation === placedPre[pickK]?.rotation
    && anchorErr <= 1e-6 && othersEqual
    && JSON.stringify(placedPlt) === JSON.stringify(placedDxf),
  'k=' + pickK + '/' + mirIdxPlt.join(',') + ' anchorErr=' + anchorErr.toExponential(1)
    + ' others=' + othersEqual + ' tr ' + placedPre[pickK]?.translation.map((v) => v.toFixed(1))
    + '->' + placedPlt[pickK]?.translation.map((v) => v.toFixed(1)));

// PLT 正文几何镜像对拍（±2 unit ≈ 0.05mm；lead 自门幅框 stroke 首点推导）。
const strokesMir = parsePltStrokes(expMirPlt.respBody || '');
let pltErr = 1e9;
let pltCounter = 0;
let pltInfo = 'n/a';
if (strokesMir.length >= EXPECT_TOTAL + 1 && outlinesPre.length > pickK
    && placedPlt[pickK] && placedPre[pickK]) {
  const border = strokesMir[0];
  const leadX = border[0][0] / 40;
  const leadY = border[0][1] / 40;
  const strokeK = strokesMir[pickK + 1];
  const it0 = placedPre[pickK];
  const it1 = placedPlt[pickK];
  const [c0, s0] = rotCs(-it0.rotation);
  const [c1, s1] = rotCs(it1.rotation);
  const expMir = [];
  const expNo = [];
  for (const v of outlinesPre[pickK]) {
    const dx = v[0] - it0.translation[0];
    const dy = v[1] - it0.translation[1];
    const px = dx * c0 - dy * s0;
    const py = dx * s0 + dy * c0;
    for (const mir of [true, false]) {
      const mx = mir ? -px : px;
      (mir ? expMir : expNo).push([
        Math.max(0, Math.round((mx * c1 - py * s1 + it1.translation[0] + leadX) * 40)),
        Math.max(0, Math.round((mx * s1 + py * c1 + it1.translation[1] + leadY) * 40)),
      ]);
    }
  }
  if (strokeK && strokeK.length === expMir.length) {
    pltErr = 0;
    for (let i = 0; i < expMir.length; i++) {
      pltErr = Math.max(pltErr, Math.hypot(expMir[i][0] - strokeK[i][0], expMir[i][1] - strokeK[i][1]));
      pltCounter = Math.max(pltCounter, Math.hypot(expNo[i][0] - strokeK[i][0], expNo[i][1] - strokeK[i][1]));
    }
  }
  pltInfo = 'strokes=' + strokesMir.length + ' lead=' + leadX + '/' + leadY
    + 'mm pts=' + (strokeK || []).length + '/' + expMir.length;
}
check('S8l PLT 正文几何镜像对拍（毛版闭合轮廓逐顶点 = R·M·p+t 转 HPGL ≤2unit；非镜像反事实 ≥40unit）',
  pltErr <= 2 && pltCounter >= 40,
  pltInfo + ' err=' + (pltErr === 1e9 ? 'n/a' : pltErr.toFixed(2)) + 'unit'
    + ' counter=' + pltCounter.toFixed(0) + 'unit');

// DXF 正文几何镜像对拍（±0.05mm 舍入口径）。
const outlinesMir = parseDxfOutlines(expMirDxf.respBody || '');
let dxfErr = 1e9;
let dxfCounter = 0;
let dxfInfo = 'n/a';
if (outlinesMir.length === EXPECT_TOTAL && outlinesPre.length > pickK
    && placedPlt[pickK] && placedPre[pickK]) {
  const newPts = outlinesMir[pickK];
  const it0 = placedPre[pickK];
  const it1 = placedPlt[pickK];
  const [c0, s0] = rotCs(-it0.rotation);
  const [c1, s1] = rotCs(it1.rotation);
  if (newPts && newPts.length === outlinesPre[pickK].length) {
    dxfErr = 0;
    for (let i = 0; i < newPts.length; i++) {
      const v = outlinesPre[pickK][i];
      const dx = v[0] - it0.translation[0];
      const dy = v[1] - it0.translation[1];
      const px = dx * c0 - dy * s0;
      const py = dx * s0 + dy * c0;
      for (const mir of [true, false]) {
        const mx = mir ? -px : px;
        const d = Math.hypot(
          mx * c1 - py * s1 + it1.translation[0] - newPts[i][0],
          mx * s1 + py * c1 + it1.translation[1] - newPts[i][1]);
        if (mir) dxfErr = Math.max(dxfErr, d);
        else dxfCounter = Math.max(dxfCounter, d);
      }
    }
  }
  dxfInfo = 'outlines=' + outlinesMir.length + ' verts=' + (newPts || []).length;
}
check('S8m DXF 正文几何镜像对拍（layer1 闭合 POLYLINE 逐顶点 ≤0.05mm；非镜像反事实 ≥1mm）',
  dxfErr <= 0.05 && dxfCounter >= 1,
  dxfInfo + ' err=' + (dxfErr === 1e9 ? 'n/a' : dxfErr.toFixed(4)) + 'mm'
    + ' counter=' + dxfCounter.toFixed(1) + 'mm');

// 重开承接已保存镜像片 → 复选 → 微调（mirror 逐位透传）→ R 键重置回算法基线。
await page.click('[data-testid=edit-controls-edit]');
await page.waitForSelector('[data-testid=edit-layout-overlay]', { timeout: 5000 });
const itMir = placedPlt[pickK] || null;
const wantMir = itMir && polyK
  ? pointsStrJs(polyK, itMir.rotation, itMir.translation, true)
  : null;
const roughReopen = (await roughPoints()).slice().sort();
check('S8n 重开弹窗承接已保存镜像片（按镜像 points 内容匹配恰 1 片）',
  !!wantMir && roughReopen.filter((s) => s === wantMir).length === 1,
  'match=' + roughReopen.filter((s) => s === wantMir).length);
const selOk2 = wantMir ? await selectByPoints(wantMir) : false;
await sleep(300);
check('S8o 镜像片复选（重合指标面板在案）',
  selOk2 === true && await page.evaluate(() =>
    document.querySelector('[data-testid=edit-metrics]') !== null));
const p5 = await polishOnce();
const req5 = p5.reqBody?.placed || [];
const resp5 = p5.respBody?.placed || [];
const mirReq = req5.map((p, i) => (p.mirror === true ? i : -1)).filter((i) => i >= 0);
const mirResp = resp5.map((p, i) => (p.mirror === true ? i : -1)).filter((i) => i >= 0);
check('S8p 微调 mirror 逐位透传（请求/响应恰一项 mirror:true 同下标同 pid；其余 29 项无 mirror 键）',
  p5.respBody?.ok === true && mirReq.length === 1 && mirReq[0] === pickK
    && mirResp.length === 1 && mirResp[0] === pickK
    && req5[pickK]?.id === pidK && resp5[pickK]?.id === pidK
    && resp5.every((p, i) => i === pickK || p.mirror === undefined),
  'req@' + pickK + '=' + (req5[pickK]?.mirror === true)
    + ' resp@' + pickK + '=' + (resp5[pickK]?.mirror === true)
    + ' rot ' + req5[pickK]?.rotation + '->' + resp5[pickK]?.rotation + '°'
    + ' byteEqual=' + (JSON.stringify(req5[pickK]) === JSON.stringify(resp5[pickK])));
await page.screenshot({ path: OUT + '/s8_polish_mirror.png' });
// R 前快照须在微调结果渲染落定后取（响应捕获与页面 replaceWorking+重渲染有微竞态，
// 稳等 500ms —— 否则 R 的「恰改一片」判据会混入微调移动片）。
await sleep(500);
const roughBeforeR = (await roughPoints()).slice().sort();
await blurActive();
await page.keyboard.press('r');
await sleep(300);
const roughAfterR = (await roughPoints()).slice().sort();
const diffR = multisetDiff(roughBeforeR, roughAfterR);
const baseIt = solverPlaced2[pickK] || null;
const basePoly = polyByPid.get(baseIt?.id) || null;
const wantBase = baseIt && basePoly
  ? pointsStrJs(basePoly, baseIt.rotation, baseIt.translation, false)
  : null;
check('S8q R 键重置回算法基线（恰改一片 + points 逐字节 = S6 末帧 placement 基线串且 ∈ 首开快照 + 基线 pid 对位）',
  diffR.removed.length === 1 && diffR.added.length === 1 && !!wantBase
    && diffR.added[0] === wantBase && m6Points.includes(wantBase) && baseIt?.id === pidK,
  'out/in=' + diffR.removed.length + '/' + diffR.added.length
    + ' baseMatch=' + (diffR.added[0] === wantBase)
    + ' inM6=' + m6Points.includes(wantBase));
await page.screenshot({ path: OUT + '/s8_r_reset.png' });

// ---------- 汇总 ----------
writeFileSync(OUT + '/report.json', JSON.stringify({
  at: new Date().toISOString(),
  solve1: { density: final1?.density, width_mm: final1?.width_mm, placed: EXPECT_TOTAL },
  polish1: { before: rep1.before, after: rep1.after, moves: rep1.moves?.length,
    residual: rep1.residual?.length },
  determinism: { placedEqual, reportEqual },
  export: {
    plt: { placed: expPlt.reqBody?.placed?.length, bytes: (expPlt.respBody || '').length },
    dxf: { placed: expDxf.reqBody?.placed?.length, bytes: (expDxf.respBody || '').length },
  },
  band: { label: BAND_LABEL, pieces: bandCount, excluded: excludedIdx,
    unchanged: bandUnchanged, report: { before: rep3.before, after: rep3.after } },
  compact: { requested: p4.reqBody?.compact === true,
    widthVsNonCompact: { compact: rep4.after?.width_mm, plain: rep3.after?.width_mm },
    report: { before: rep4.before, after: rep4.after }, moves: rep4.moves?.length },
  mirror: {
    pieceIndex: pickK, pid: pidK, pick: pickInfo,
    domReflectionErrMm: reflErr < 1e9 ? reflErr : null,
    anchorErr: anchorErr < 1e9 ? anchorErr : null,
    translation: { before: placedPre[pickK]?.translation, after: placedPlt[pickK]?.translation },
    plt: { errUnits: pltErr < 1e9 ? pltErr : null, counterUnits: pltCounter },
    dxf: { errMm: dxfErr < 1e9 ? dxfErr : null, counterMm: dxfCounter },
    polishPassthrough: { req: req5[pickK]?.mirror === true, resp: resp5[pickK]?.mirror === true,
      rotAfter: resp5[pickK]?.rotation,
      byteEqual: JSON.stringify(req5[pickK]) === JSON.stringify(resp5[pickK]) },
    resetToBaseline: diffR.added.length === 1 && diffR.added[0] === wantBase,
  },
  results,
}, null, 2));
const failed = results.filter((r) => !r.ok);
console.log('\n==== edit-polish 端到端冒烟: ' + (results.length - failed.length) + '/' + results.length + ' PASS ====');
await browser.close();
process.exit(failed.length ? 1 : 0);

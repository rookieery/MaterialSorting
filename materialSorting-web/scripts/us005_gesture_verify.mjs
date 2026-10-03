// prd-initial-layout US-005（2026-10-03）EditCanvas「初始布局模式」手势矩阵浏览器
// 验证（playwright，手动脚本不入 vitest；模板 = us004_il_entry_verify.mjs 骨架 +
// smoke_drag_snap.mjs 的 esbuild 即时 bundle 真源码套路）。
//
// US-006 弹窗尚未落地（本故事只交付 EditCanvas props），无 UI 消费入口 —— 故用
// esbuild 把**真实源码** EditCanvas + editStore + runRegistry bundle 成 IIFE 注入
// 空白页挂载（零后端依赖：fixture 直接 seed editStore），浏览器（Edge 通道，
// Chrome 兜底）驱动真实指针/键盘事件核对矩阵。不跑 ms-web（后端零改动、无服务
// 残留）；产物全部落 out/（gitignored）。
//
// 相位：
//   A 默认 props（回归红线）：组标记/图例行缺席；空格四态（第一按 mirror+180、
//     四按回原始）；L 微转在场。
//   B 初始布局 props（allowMirror=false + allowFineRotate=false + pieceGroup +
//     onIllegalOverlapCountChange）：
//     B1 组成员标记（.edit-piece-grouped + data-edit-group）+ 非成员无标记 +
//        图例行「组合成员片（整组拖动）」在场；
//     B2 组成员键盘全禁（L/K/空格/O/I/R 零变换）+ 旋转手柄隐藏；
//     B3 组拖全组同 delta 联动（a+b 平移、非成员 c 不动）；
//     B4 组包络钳制（minX<0 截住 → 全组回包络左缘）；
//     B5 Alt+左键组拖不吸附（6mm 缝落点原样、无伙伴高亮）；
//     B6 非成员照常：空格两态（rot±180、mirror 恒无）、L 无效、R 重置、手柄可见；
//     B7 非成员 Alt+左键吸附照常（6mm 缝 attract 到触点）；
//     B8 非法重叠计数回调：拖 c 压入 b（红）→ 2；拖离 → 0；挂载首帧即触达。
//
// 报告落 out/us005_gesture/report.json；退出码 0 = 全 PASS。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const WEB = ROOT + '/materialSorting-web';
const OUT = ROOT + '/out/us005_gesture';
// harness 产物须落 WEB 内（esbuild node_modules 解析从入口位置上溯 —— 落 repo 根
// out/ 找不到 react/react-dom；out/ 目录名全层级 gitignored，不污染仓库）。
const HARN = WEB + '/out/us005_gesture';
mkdirSync(OUT, { recursive: true });
mkdirSync(HARN, { recursive: true });

// ---------- 真源码 harness（esbuild 即时 bundle，非复刻） ----------
const HARNESS = [
  "import { createRoot } from 'react-dom/client';",
  "import { EditCanvas } from '../../src/components/edit/EditCanvas';",
  "import { useEditStore } from '../../src/store/editStore';",
  "import { runRegistry } from '../../src/store/runRegistry';",
  "const raw = [[0, 0], [500, 0], [500, 500], [0, 500]];",
  "const mk = (id, label, size, color) => ({ id, label, size, color, area_mm2: 250000, polygon: raw });",
  "const manifest = {",
  "  type: 'manifest', gate_mm: 1000, total_area_mm2: 750000, n_eroded: 0,",
  "  pieces: [mk('a_28', 'g01', 28, '#ff0000'), mk('b_30', 'g01', 30, '#00ff00'), mk('c_32', 'g02', 32, '#0000ff')],",
  "};",
  "const PLACED = [",
  "  { id: 'a_28', rotation: 0, translation: [0, 0] },",
  "  { id: 'b_30', rotation: 0, translation: [600, 0] },",
  "  { id: 'c_32', rotation: 0, translation: [1600, 0] },",
  "];",
  "function seed() {",
  "  runRegistry.clear();",
  "  useEditStore.getState().invalidate();",
  "  const run = runRegistry.create(0);",
  "  run.manifest = manifest;",
  "  const maxX = 2100;",
  "  const frame = {",
  "    type: 'frame', index: 0, elapsed: 1, phase: 'final',",
  "    density: manifest.total_area_mm2 / (maxX * manifest.gate_mm), density_sparrow: 0.5,",
  "    width_mm: maxX,",
  "    placed_items: PLACED.map((it) => ({ id: it.id, rotation: it.rotation, translation: [it.translation[0], it.translation[1]] })),",
  "  };",
  "  run.frames.push(frame);",
  "  run.lastFrame = frame;",
  "  run.finalDensity = frame.density;",
  "  useEditStore.getState().open(run);",
  "}",
  "const bandGroup = (pid) => (pid === 'a_28' || pid === 'b_30' ? 'band:g01' : null);",
  "const root = createRoot(document.getElementById('root'));",
  "const counts = [];",
  "function mount(mode) {",
  "  if (mode === 'initial') {",
  "    root.render(<EditCanvas mode=\"full\" allowMirror={false} allowFineRotate={false} pieceGroup={bandGroup} onIllegalOverlapCountChange={(n) => { counts.push(n); }} />);",
  "  } else {",
  "    root.render(<EditCanvas mode=\"full\" />);",
  "  }",
  "}",
  "seed();",
  "window.__us005 = { counts, mount, reseed: seed, dump: () => JSON.parse(JSON.stringify(useEditStore.getState().working)) };",
  "mount('default');",
  '',
].join('\n');
writeFileSync(HARN + '/harness_entry.tsx', HARNESS);
const { build: esbuildBuild } = await import('esbuild');
await esbuildBuild({
  entryPoints: [HARN + '/harness_entry.tsx'],
  outfile: HARN + '/harness_bundle.js',
  bundle: true,
  format: 'iife',
  jsx: 'automatic',
  target: 'es2020',
  logLevel: 'warning',
});

// ---------- 浏览器（Edge 通道，Chrome 兜底；headless） ----------
const { chromium } = await import('playwright');
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true });
} catch {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
}
const context = await browser.newContext({ viewport: { width: 1400, height: 800 } });
const page = await context.newPage();
await page.setContent(
  '<!doctype html><html><head><style>' +
    'html,body{margin:0;padding:0}#root{position:fixed;inset:0}' +
    '.edit-layout-canvas-wrap{position:absolute;inset:0}' +
    '.edit-layout-svg{width:100%;height:100%;display:block}' +
    '</style></head><body><div id="root"></div></body></html>',
);
await page.addScriptTag({ path: HARN + '/harness_bundle.js' });
await page.waitForFunction(
  () => window.__us005 != null && document.querySelectorAll('svg g > polygon').length >= 3,
);

const results = [];
function check(name, ok, extra = '') {
  results.push({ name, ok, extra: String(extra) });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 200) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 片中心屏幕坐标 + 当前视图比尺（px/mm，meet 实测）。 */
async function pieceInfo(stroke) {
  return page.evaluate((st) => {
    const svg = document.querySelector('svg.edit-layout-svg');
    const poly = svg.querySelector(':scope g > polygon[stroke="' + st + '"]');
    const pr = poly.getBoundingClientRect();
    const sr = svg.getBoundingClientRect();
    const vb = svg.getAttribute('viewBox').split(' ').map(Number);
    const s = Math.min(sr.width / vb[2], sr.height / vb[3]);
    return { cx: pr.x + pr.width / 2, cy: pr.y + pr.height / 2, s };
  }, stroke);
}

/** 空白点击取消选中（顶部 letterbox 带，world y<0 → bg 命中）。 */
async function deselect() {
  await page.mouse.click(1000, 20);
  await sleep(60);
}

/** 拖片（世界位移 mm；alt=true 贴附会话）。 */
async function dragPiece(stroke, dxMm, dyMm, alt = false) {
  const info = await pieceInfo(stroke);
  if (alt) await page.keyboard.down('Alt');
  await page.mouse.move(info.cx, info.cy);
  await page.mouse.down();
  await page.mouse.move(info.cx + dxMm * info.s, info.cy - dyMm * info.s, { steps: 6 });
  await sleep(40);
  await page.mouse.up();
  if (alt) await page.keyboard.up('Alt');
  await sleep(80);
}

async function clickPiece(stroke) {
  const info = await pieceInfo(stroke);
  await page.mouse.click(info.cx, info.cy);
  await sleep(80);
}

async function dump() {
  return page.evaluate(() => window.__us005.dump());
}

async function countsNow() {
  return page.evaluate(() => [...window.__us005.counts]);
}

const closeTo = (v, t, tol) => Math.abs(v - t) <= tol;
const trans = (w, i) => w[i].translation;

// ============================ Phase A：默认 props（回归红线） ============================
console.log('--- Phase A: default props ---');

check(
  'A1 默认 props：组标记与图例行缺席（回归红线）',
  await page.evaluate(
    () =>
      document.querySelector('[data-testid="edit-guide-group-row"]') === null &&
      document.querySelectorAll('.edit-piece-grouped').length === 0,
  ),
);

await clickPiece('#0000ff'); // c（默认 props 全片单片语义）
await page.keyboard.press('Space');
await sleep(60);
let w = await dump();
check(
  'A2 默认 props 空格四态在场：第一按 = 垂直镜像（rot 180 + mirror true）',
  w[2].rotation === 180 && w[2].mirror === true,
  'rot=' + w[2].rotation + ' mirror=' + String(w[2].mirror),
);
for (let i = 0; i < 3; i++) {
  await page.keyboard.press('Space');
  await sleep(60);
}
w = await dump();
check(
  'A3 四按回原始（rot 0、mirror 无键）',
  w[2].rotation === 0 && w[2].mirror === undefined,
  'rot=' + w[2].rotation + ' mirror=' + String(w[2].mirror),
);
await page.keyboard.press('l');
await sleep(60);
w = await dump();
check('A4 默认 props L 微转在场（rot 1）', w[2].rotation === 1, 'rot=' + w[2].rotation);
await deselect();
await page.evaluate(() => window.__us005.reseed());
await sleep(80);

// ====================== Phase B：初始布局 props（US-005 手势矩阵） ======================
console.log('--- Phase B: initial-layout props ---');
await page.evaluate(() => window.__us005.mount('initial'));
await sleep(120);

check(
  'B1 组成员视觉标记 + 图例行（a/b 标记、c 无、文案在场）',
  await page.evaluate(() => {
    const svg = document.querySelector('svg.edit-layout-svg');
    const a = svg.querySelector(':scope g > polygon[stroke="#ff0000"]');
    const b = svg.querySelector(':scope g > polygon[stroke="#00ff00"]');
    const c = svg.querySelector(':scope g > polygon[stroke="#0000ff"]');
    const row = document.querySelector('[data-testid="edit-guide-group-row"]');
    return (
      a.classList.contains('edit-piece-grouped') &&
      a.getAttribute('data-edit-group') === 'band:g01' &&
      b.classList.contains('edit-piece-grouped') &&
      !c.classList.contains('edit-piece-grouped') &&
      c.getAttribute('data-edit-group') == null &&
      row != null &&
      (row.textContent || '').includes('组合成员片（整组拖动）')
    );
  }),
);

// B2 组成员键盘全禁 + 手柄隐藏
await clickPiece('#ff0000');
const beforeKeys = JSON.stringify(await dump());
for (const k of ['l', 'k', 'o', 'i', 'r', 'Space']) {
  await page.keyboard.press(k);
  await sleep(50);
}
const afterKeys = await dump();
check(
  'B2 组成员键盘全禁（L/K/O/I/R/空格 零变换）',
  JSON.stringify(afterKeys) === beforeKeys,
  JSON.stringify(trans(afterKeys, 0)),
);
check(
  'B2b 组成员旋转手柄隐藏（display:none）',
  await page.evaluate(() => {
    const h = document.querySelector('[data-testid="edit-rotate-handle"]');
    if (!h) return false;
    const g = h.closest('g');
    return g != null && g.style.display === 'none';
  }),
);
await deselect();
await page.evaluate(() => window.__us005.reseed());
await sleep(80);

// B3 组拖联动
await dragPiece('#ff0000', 300, 0);
w = await dump();
check(
  'B3 组拖全组同 delta 联动（a+b +300mm、c 不动）',
  closeTo(trans(w, 0)[0], 300, 3) &&
    closeTo(trans(w, 0)[1], 0, 3) &&
    closeTo(trans(w, 1)[0], 900, 3) &&
    closeTo(trans(w, 1)[1], 0, 3) &&
    closeTo(trans(w, 2)[0], 1600, 0.001),
  JSON.stringify([trans(w, 0), trans(w, 1), trans(w, 2)]),
);
await deselect();
await page.evaluate(() => window.__us005.reseed());
await sleep(80);

// B4 组包络钳制：向左拖远超包络 → 全组回 minX=0
await dragPiece('#ff0000', -2000, 0);
w = await dump();
check(
  'B4 组包络钳制 minX≥0（组 bbox 左缘贴 0：a x≈0、b x≈600）',
  closeTo(trans(w, 0)[0], 0, 3) && closeTo(trans(w, 1)[0], 600, 3),
  JSON.stringify([trans(w, 0), trans(w, 1)]),
);
await deselect();
await page.evaluate(() => window.__us005.reseed());
await sleep(80);

// B5 Alt+左键组拖不吸附（组右缘与非成员 c 留 ~6mm 缝，单片必吸 → 组原样）
await dragPiece('#ff0000', 494, 0, true);
w = await dump();
const b5Partner = await page.evaluate(
  () => document.querySelector('[data-testid="edit-snap-partner"]') === null,
);
check(
  'B5 Alt+左键组拖不吸附（b x≈1094 落点原样 + 无伙伴高亮）',
  closeTo(trans(w, 0)[0], 494, 3) && closeTo(trans(w, 1)[0], 1094, 3) && b5Partner,
  JSON.stringify([trans(w, 0), trans(w, 1)]) + ' partnerNone=' + b5Partner,
);
await deselect();
await page.evaluate(() => window.__us005.reseed());
await sleep(80);

// B6 非成员照常：空格两态 / L 无效 / R 重置 / 手柄可见
await clickPiece('#0000ff');
check(
  'B6a 非成员旋转手柄可见',
  await page.evaluate(() => {
    const h = document.querySelector('[data-testid="edit-rotate-handle"]');
    if (!h) return false;
    const g = h.closest('g');
    return g != null && g.style.display !== 'none';
  }),
);
await page.keyboard.press('Space');
await sleep(60);
w = await dump();
check(
  'B6b 非成员空格两态（rot 180、mirror 恒无 —— allowMirror=false 全局收窄）',
  w[2].rotation === 180 && w[2].mirror === undefined,
  'rot=' + w[2].rotation + ' mirror=' + String(w[2].mirror),
);
await page.keyboard.press('Space');
await sleep(60);
w = await dump();
check('B6c 两按回原始（rot 0）', w[2].rotation === 0, 'rot=' + w[2].rotation);
await page.keyboard.press('l');
await sleep(60);
w = await dump();
check(
  'B6d 非成员 L 无效（allowFineRotate=false 全局收窄）',
  w[2].rotation === 0,
  'rot=' + w[2].rotation,
);
await page.keyboard.press('r');
await sleep(60);
w = await dump();
check(
  'B6e 非成员 R 片级重置照常（幂等不炸）',
  Math.abs(w[2].rotation) < 1e-9,
  'rot=' + w[2].rotation,
);
await deselect();
await page.evaluate(() => window.__us005.reseed());
await sleep(80);

// B7 非成员 Alt+左键吸附照常（c 左拖 ~494mm 与 b 留 6mm 缝 → attract 到触点 1100）
await dragPiece('#0000ff', -494, 0, true);
w = await dump();
check(
  'B7 非成员 Alt+左键吸附照常（c x≈1100 attract + 伙伴高亮在场）',
  closeTo(trans(w, 2)[0], 1100, 0.01) &&
    (await page.evaluate(() => document.querySelector('[data-testid="edit-snap-partner"]') !== null)),
  'c.x=' + trans(w, 2)[0],
);
await deselect();
await page.evaluate(() => window.__us005.reseed());
await sleep(80);

// B8 非法重叠计数回调：压入（红）→ 2；拖离 → 0
const countsBefore = (await countsNow()).length;
await dragPiece('#0000ff', -700, 80); // c@[900,80] 与 b 交 200×420、pen 80 > 额度 0 → 红
w = await dump();
let cs = await countsNow();
check(
  'B8a 非法重叠计数回调触发（压入 → 2，双方各计 1）',
  cs.length > countsBefore && cs[cs.length - 1] === 2,
  'counts=' + JSON.stringify(cs) + ' c=' + JSON.stringify(trans(w, 2)),
);
await dragPiece('#0000ff', 400, 0); // c@[1300,80] 无相交邻居 → 0
cs = await countsNow();
check('B8b 拖离归零（回调终值 0）', cs[cs.length - 1] === 0, 'counts=' + JSON.stringify(cs));
const mountEmission = cs[0];
check('B8c 挂载首帧即触达且初值 0（不依赖选中态）', mountEmission === 0, 'first=' + mountEmission);

// ---------- 收尾 ----------
const failed = results.filter((r) => !r.ok);
writeFileSync(
  OUT + '/report.json',
  JSON.stringify({ passed: results.length - failed.length, failed: failed.length, results }, null, 2),
);
await context.close();
await browser.close();
console.log(failed.length === 0 ? 'ALL PASS (' + results.length + ')' : 'FAILED: ' + failed.length);
process.exit(failed.length === 0 ? 0 : 1);

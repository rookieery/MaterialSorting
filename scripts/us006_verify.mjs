// US-006 浏览器验证 harness（CDP headless Chrome，无外部依赖；范本 us005_verify.mjs）。
// 前置：ms-web 在 :8000 运行（须已能 commit 母版）。流程：
//   1) 真实 WS 求解 25s（sizes 30/32 · seed 7 · g01@30 demand=2 多副本）→ 捕获 manifest+终帧；
//   2) 页面加载前 fetch stub /api/strategy/status|result → done 结果态（best = 捕获终帧 ——
//      manifest/placed_items 与 /api/strategy/result 端点同构，几何与后端 pieces_by_id 同源）；
//   3) 真实 UI：上传母版 → commit → 超排 Tab → 高级运行弹窗（结果态断言）→「应用到主画布」；
//   4) 主画布断言：状态行 / NestCard 多副本渲染 / 翻转组 / viewBox / 红虚线 / seekbar / 导出解禁；
//   5) UI 导出 DXF + PNG（stub 记录 /export 请求体并克隆响应存盘；R12 POLYLINE 校验）。
// 截图与导出文件存 out/us006_verify/。
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9_coded.dxf';
const OUT = 'D:/code/MaterialSorting/out/us006_verify';
mkdirSync(OUT, { recursive: true });
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + String(detail).slice(0, 160) : ''}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- 1) 真实 WS 求解捕获（manifest + 终帧） ----------
async function solveCapture() {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket('ws://127.0.0.1:8000/ws/solve');
    const manifest = {};
    let lastFrame = null;
    const t = setTimeout(() => { try { ws.close(); } catch {} reject(new Error('solve timeout')); }, 180000);
    ws.onopen = () => ws.send(JSON.stringify({
      action: 'start', sizes: [30, 32], time: 25, seed: 7, gate_mm: 1980,
      params: { d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 }, per_type: null,
      quantities: { g01: { '30': 2 } }, // g01@30 demand=2 → 多副本 placement
    }));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === 'manifest') Object.assign(manifest, m);
      if (m.type === 'frame') lastFrame = m;
      if (m.type === 'final') { clearTimeout(t); ws.close(); resolve({ manifest, lastFrame, final: m }); }
      if (m.type === 'error') { clearTimeout(t); ws.close(); reject(new Error('solve error: ' + m.message)); }
    };
    ws.onerror = () => { clearTimeout(t); reject(new Error('ws error')); };
  });
}
const cap = await solveCapture();
console.log(`SOLVE captured: pieces=${cap.manifest.pieces.length} density=${(cap.final.density * 100).toFixed(2)}% width=${Math.round(cap.final.width_mm)} placed=${cap.lastFrame.placed_items.length}`);
const RESULT = {
  state: 'done', mode: 'race', run_dir: 'out/config_runs/web_race_us006verify_(mock: real 25s solve)',
  manifest: cap.manifest,
  best: {
    seed: 7, frame_index: cap.lastFrame.index, elapsed: cap.lastFrame.elapsed,
    density: cap.final.density, density_sparrow: cap.final.density_sparrow,
    width_mm: cap.final.width_mm, placed_items: cap.lastFrame.placed_items,
  },
  summary: {
    per_seed: [
      { seed: 0, killed: true, kill_reason: 'R5_race_gate', best_density: 0.75, elapsed: 92, phase: 'race' },
      { seed: 7, killed: false, kill_reason: null, best_density: cap.final.density, elapsed: 181, phase: 'race' },
    ],
    mode: 'race', race: { gate_seconds: 90, kept_seeds: [7], gated_seeds: [0] },
  },
};
const STATUS = {
  state: 'done', mode: 'race', total_budget_sec: 600, elapsed_sec: 605, run_dir: RESULT.run_dir,
  plan: { planned_seeds: [0, 7], gate_seconds: 90 },
  incumbent: { density: cap.final.density, width_mm: cap.final.width_mm, seed: 7, frame_index: cap.lastFrame.index, elapsed: cap.lastFrame.elapsed },
  current: null, per_seed: RESULT.summary.per_seed,
  events: [{ kind: 'gate', seed: 0, t: 91, d: 0.75, bar: cap.final.density, would_kill: true }],
  error: null, exit_code: 0,
};

// ---------- CDP client（页面级 target，端口 9223 避开残留 9222） ----------
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9223', '--disable-gpu', '--no-first-run',
  '--window-size=1680,1000', `--user-data-dir=${OUT}/chrome-profile`, 'about:blank',
], { stdio: 'ignore' });
try {
  async function getTargetWs() {
    for (let i = 0; i < 20; i++) {
      try {
        const list = await (await fetch('http://127.0.0.1:9223/json')).json();
        const page = list.find((t) => t.type === 'page');
        if (page) return page.webSocketDebuggerUrl;
      } catch {}
      await sleep(300);
    }
    throw new Error('CDP target not found (9223)');
  }
  let ws, nextId = 1; const pending = new Map();
  function send(method, params = {}) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async function evalJs(expr, awaitPromise = false) {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise });
    if (r.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  }
  async function poll(expr, timeoutMs, label) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      const v = await evalJs(expr);
      if (v) return v;
      await sleep(500);
    }
    throw new Error('poll timeout: ' + label);
  }
  async function shot(name) {
    const r = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.data, 'base64'));
    console.log(`SHOT  ${name}.png`);
  }

  ws = new WebSocket(await getTargetWs());
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) {
      const p = pending.get(d.id); pending.delete(d.id);
      d.error ? p.reject(new Error(JSON.stringify(d.error))) : p.resolve(d.result);
    }
  };
  await send('Page.enable'); await send('Runtime.enable'); await send('DOM.enable');

  // fetch stub：策略 status/result → mock done；/export 透传并记录请求体 + 克隆响应存盘。
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `
    (() => {
      window.__exportBodies = [];
      const real = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        if (url.includes('/api/strategy/status'))
          return new Response(JSON.stringify(${JSON.stringify(STATUS)}), { status: 200, headers: { 'Content-Type': 'application/json' } });
        if (url.includes('/api/strategy/result'))
          return new Response(JSON.stringify(${JSON.stringify(RESULT)}), { status: 200, headers: { 'Content-Type': 'application/json' } });
        if (url.includes('/export')) {
          window.__exportBodies.push(init && init.body ? JSON.parse(String(init.body)) : null);
          const res = await real(input, init);
          const clone = res.clone();
          clone.arrayBuffer().then((buf) => {
            window.__exportLast = { headers: res.headers.get('Content-Disposition'), bytes: Array.from(new Uint8Array(buf)) };
          }).catch(() => {});
          return res;
        }
        return real(input, init);
      };
    })();` });

  await send('Page.navigate', { url: APP });
  await sleep(2500);
  check('App 载入（TabBar）', await evalJs(`!!document.querySelector('.tabbar')`));

  // ---- 上传母版（真实 UI 路径）→ 矩阵 + 自动 commit ----
  const doc = await send('DOM.getDocument');
  const inputNode = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' });
  if (!inputNode.nodeId) throw new Error('file input not found');
  await send('DOM.setFileInputFiles', { files: [DXF], nodeId: inputNode.nodeId });
  await poll(`!!document.querySelector('.qty-matrix')`, 90000, 'qty-matrix');
  await poll(`(() => { const b = [...document.querySelectorAll('.tab')].find(x => x.textContent.includes('超排')); return b && !b.disabled; })()`, 90000, 'commit done');
  await evalJs(`[...document.querySelectorAll('.tab')].find(x => x.textContent.includes('超排')).click()`);
  await sleep(600);
  shot('1_nesting_idle');

  // ---- 高级运行弹窗：mock done → 结果态断言 ----
  await evalJs(`document.querySelector('[data-testid=strategy-btn]').click()`);
  await poll(`!!document.querySelector('[data-testid=strategy-result-head]')`, 10000, 'result state');
  await sleep(400);
  const rs = await evalJs(`(() => ({
    head: document.querySelector('[data-testid=strategy-result-head]')?.textContent,
    detail: document.querySelector('[data-testid=strategy-result-detail]')?.textContent,
    summary: document.querySelector('[data-testid=strategy-mode-summary]')?.textContent,
    applyDisabled: document.querySelector('[data-testid=strategy-apply-btn]')?.disabled,
  }))()`);
  const pct = (cap.final.density * 100).toFixed(2) + '%';
  check('结果态：完成 · 最优 ' + pct, rs.head === `完成 · 最优 ${pct}`, rs.head);
  check('结果态：seed 7 · 用布', /seed 7 · 用布 [\d.]+m/.test(rs.detail || ''), rs.detail);
  check('结果态：race 汇总', (rs.summary || '').includes('race：2 轮中 1 轮门杀'), rs.summary);
  check('应用按钮已接线（非 disabled）', rs.applyDisabled === false);
  shot('2_modal_result');

  // ---- 应用到主画布 ----
  await evalJs(`document.querySelector('[data-testid="strategy-apply-btn"]').click()`);
  await sleep(1200);
  const ap = await evalJs(`(() => {
    const svg = document.querySelector('.nest-card svg');
    const g = svg && svg.querySelector('g');
    const polys = [...document.querySelectorAll('.nest-card svg polygon')];
    return {
      status: document.querySelector('#status')?.textContent || '',
      nestCards: document.querySelectorAll('.nest-card').length,
      visiblePolys: polys.filter(p => p.style.display !== 'none').length,
      nestLabel: document.querySelector('.nest-label')?.textContent || '',
      flip: g ? g.getAttribute('transform') : null,
      viewBox: svg ? svg.getAttribute('viewBox') : null,
      plotLine: svg ? !!svg.querySelector('line[stroke="#e53e3e"]') : false,
      curve: !!document.querySelector('.curve-wrap svg'),
      seekDisabled: document.querySelector('#seek')?.disabled,
      seekMax: document.querySelector('#seek')?.max,
      exportDisabled: document.querySelector('.export-btns button.export')?.disabled,
      restart: !!document.querySelector('#restart'),
    };
  })()`);
  check('状态行：策略 run 已应用', ap.status.includes(`策略 run 已应用：seed 7 · ${pct}`), ap.status);
  check('NestCard 恰 1 张（seeds=[7]）', ap.nestCards === 1);
  check('NestLabel：seed 7 · ' + pct, ap.nestLabel.includes('seed 7') && ap.nestLabel.includes(pct), ap.nestLabel);
  // 可见 polygon = 毛版层 + 净版层（capture 的 manifest 每片带 net_polygon）≥ placed 数
  check('NestSVG 多副本全可见（≥ placed 数）', ap.visiblePolys >= cap.lastFrame.placed_items.length, `visible=${ap.visiblePolys} placed=${cap.lastFrame.placed_items.length}`);
  check('翻转组 scale(1,-1) 保留', ap.flip === 'translate(0 1980) scale(1 -1)', ap.flip);
  check('viewBox = best width × gate', !!(ap.viewBox && ap.viewBox.startsWith('0 0 ') && ap.viewBox.endsWith('1980') && Math.abs(parseFloat(ap.viewBox.split(' ')[2]) - cap.final.width_mm) < 1), ap.viewBox);
  check('红虚线实际排料边界在场', ap.plotLine === true);
  check('收敛曲线在场', ap.curve === true);
  check('seekbar 解禁（max=ceil(elapsed)）', ap.seekDisabled === false && Number(ap.seekMax) >= Math.ceil(cap.lastFrame.elapsed), `max=${ap.seekMax}`);
  check('ExportButtons 解禁', ap.exportDisabled === false);
  check('SolveControls #restart（phase=done）', ap.restart === true);
  shot('3_after_apply');

  // ---- 导出 DXF（默认格式）→ /export 请求体 = 合成帧 ----
  await evalJs(`document.querySelector('.export-btns button.export').click()`);
  await poll(`window.__exportLast && window.__exportLast.bytes && window.__exportLast.bytes.length > 1000`, 30000, 'dxf export bytes');
  const dxfBody = await evalJs(`window.__exportBodies[window.__exportBodies.length-1]`);
  check('导出载荷：seed/width/density = best', dxfBody.seed === 7 && Math.abs(dxfBody.width_mm - cap.final.width_mm) < 1 && Math.abs(dxfBody.density - cap.final.density) < 1e-9, JSON.stringify({ seed: dxfBody.seed, width_mm: dxfBody.width_mm, density: dxfBody.density }));
  check('导出载荷：placed 含 demand 多副本', dxfBody.placed.filter(p => p.id === 'g01_30').length === 2, `g01_30=${dxfBody.placed.filter(p => p.id === 'g01_30').length}`);
  const dxfLast = await evalJs(`window.__exportLast`);
  const dxfBytes = Buffer.from(dxfLast.bytes);
  writeFileSync(`${OUT}/applied.dxf`, dxfBytes);
  const dxfTxt = dxfBytes.toString('latin1');
  check('导出 DXF：R12（AC1009）', dxfTxt.includes('AC1009'));
  check('导出 DXF：POLYLINE 实体（非 LWPOLYLINE）', dxfTxt.includes('POLYLINE') && !dxfTxt.includes('LWPOLYLINE'));
  console.log(`FILE  applied.dxf (${dxfBytes.length} bytes)`);

  // ---- 导出 PNG ----
  await evalJs(`(() => { const s = document.querySelector('select.export-fmt');
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, 'png');
    s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  await sleep(300);
  await evalJs(`window.__exportLast = null; document.querySelector('.export-btns button.export').click()`);
  await poll(`window.__exportLast && window.__exportLast.bytes[0] === 137`, 30000, 'png export bytes');
  const pngLast = await evalJs(`window.__exportLast`);
  const pngBytes = Buffer.from(pngLast.bytes);
  writeFileSync(`${OUT}/applied.png`, pngBytes);
  check('导出 PNG：magic 头有效', pngBytes[0] === 0x89 && pngBytes[1] === 0x50 && pngBytes[2] === 0x4e && pngBytes[3] === 0x47, `${pngBytes.length} bytes`);
  console.log(`FILE  applied.png (${pngBytes.length} bytes)`);

  const statusAfter = await evalJs(`document.querySelector('#status')?.textContent || ''`);
  check('状态行：已导出', statusAfter.includes('已导出'), statusAfter);
} finally {
  try { chrome.kill(); } catch {}
}
const failed = results.filter(r => !r.ok);
console.log(`\n==== US-006 verify: ${results.length - failed.length}/${results.length} PASS ====`);
process.exit(failed.length ? 1 : 0);

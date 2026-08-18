// US-003 浏览器验证 harness（CDP headless Chrome，无外部依赖）。
// 流程：上传母版 → 矩阵 g 码/Σ 总片数断言 → 放大预览 g 码徽章 →
//      高级配置 g 码列 + 二层预览 → 求解渲染 polygon[data-label] + tooltip g 码。
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf';
const OUT = 'D:/code/MaterialSorting/out/us003_verify';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + detail : ''}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- CDP client ----------
async function getTargetWs() {
  for (let i = 0; i < 20; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:9222/json')).json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(300);
  }
  throw new Error('CDP target not found');
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

// ---------- main ----------
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9222', '--disable-gpu', '--no-first-run',
  '--window-size=1680,1000', `--user-data-dir=${OUT}/chrome-profile`, 'about:blank',
], { stdio: 'ignore' });
try {
  const wsUrl = await getTargetWs();
  ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) {
      const p = pending.get(d.id); pending.delete(d.id);
      d.error ? p.reject(new Error(JSON.stringify(d.error))) : p.resolve(d.result);
    }
  };
  await send('Page.enable'); await send('Runtime.enable'); await send('DOM.enable');
  await send('Page.navigate', { url: APP });
  await sleep(2500);
  check('App 载入（标题 + TabBar）', await evalJs(`!!document.querySelector('.tabbar') || !!document.title`));

  // ---- 上传母版（真实 UI 路径：DOM.setFileInputFiles 触发 change → useParseDxf）----
  const doc = await send('DOM.getDocument');
  const inputNode = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' });
  if (!inputNode.nodeId) throw new Error('file input not found');
  await send('DOM.setFileInputFiles', { files: [DXF], nodeId: inputNode.nodeId });
  console.log('UPLOAD dispatched, waiting parse+matrix...');
  await poll(`!!document.querySelector('.qty-matrix')`, 90000, 'qty-matrix');
  await sleep(1500);
  await shot('01_matrix');

  // ---- 矩阵断言：g 码列头 / 零中文名 / Σ 总片数 ----
  const badges = await evalJs(`Array.from(document.querySelectorAll('thead .qty-label-badge')).map(b=>b.textContent)`);
  check('矩阵列头 = g01..g10（10 列）', badges.length === 10 && badges[0] === 'g01' && badges[9] === 'g10', badges.join(','));
  const headText = await evalJs(`document.querySelector('.qty-matrix thead').textContent`);
  check('矩阵列头零中文名', !/前片|后片|腰|袋|裤耳|机头/.test(headText), '');
  const sums = await evalJs(`(() => {
    const cells = Array.from(document.querySelectorAll('.qty-matrix tbody input[type=number]')).map(i=>parseInt(i.value||'0',10));
    const total = parseInt(document.querySelector('[data-testid=qty-total]').textContent,10);
    const foot = Array.from(document.querySelectorAll('tfoot .qty-subtotal')).map(t=>parseInt(t.textContent,10));
    const n = cells.reduce((a,b)=>a+b,0);
    return { n, total, footSum: foot.slice(0,-1).reduce((a,b)=>a+b,0), footLast: foot[foot.length-1] };
  })()`);
  check('总片数 = Σ 格子数量（数量即一切，无乘数）', sums.n === sums.total, JSON.stringify(sums));
  check('每裁片合计行之和 = 总片数', sums.footSum === sums.total && sums.footLast === sums.total, '');
  const noPairedBadge = await evalJs(`!document.querySelector('.qty-paired-badge')`);
  check('无 ×2 配对徽章残留', noPairedBadge);

  // ---- PieceZoomModal：g 码徽章 / 无 name span ----
  await evalJs(`document.querySelector('thead .qty-thumb').click()`);
  await sleep(600);
  const zoom = await evalJs(`(() => {
    const m = document.querySelector('.piece-zoom-modal');
    return { badge: m?.querySelector('.piece-card-label')?.textContent, nameSpan: !!m?.querySelector('.piece-zoom-name'), aria: m?.getAttribute('aria-label') };
  })()`);
  check('放大预览头部 = g 码徽章（无 name span）', zoom.badge === 'g01' && !zoom.nameSpan && /g01/.test(zoom.aria || ''), JSON.stringify(zoom));
  await shot('02_zoom_modal');
  await evalJs(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  await sleep(300);

  // ---- 高级配置：g 码列 + 二层裁片预览 ----
  await evalJs(`document.querySelector('.per-type-btn').click()`);
  await poll(`document.querySelectorAll('.per-type-overlay thead .qty-label-badge').length >= 10`, 15000, 'per-type cols');
  await sleep(400);
  const ov = await evalJs(`(() => {
    const o = document.querySelector('.per-type-overlay');
    const badges = Array.from(o.querySelectorAll('thead .qty-label-badge')).map(b=>b.textContent);
    return { badges, hasPtypeName: !!o.querySelector('.ptype-name'), thumbs: o.querySelectorAll('.ptype-thumb svg').length };
  })()`);
  check('高级配置列 = g 码（g01..g10，无 .ptype-name）', ov.badges.length === 10 && ov.badges[0] === 'g01' && !ov.hasPtypeName, JSON.stringify(ov));
  await shot('03_per_type_modal');
  await evalJs(`document.querySelector('.per-type-overlay .ptype-thumb').click()`);
  await sleep(800);
  const pv = await evalJs(`(() => {
    const m = document.querySelector('.ptype-preview-modal');
    return { badge: m?.querySelector('.piece-card-label')?.textContent, aria: m?.getAttribute('aria-label') };
  })()`);
  check('二层裁片预览头部 = g 码徽章', pv.badge === 'g01' && pv.aria === 'g01-放大预览', JSON.stringify(pv));
  await shot('04_ptype_preview');
  await evalJs(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  await sleep(200);
  await evalJs(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  await sleep(300);

  // ---- 求解渲染：polygon[data-label] + tooltip g 码 ----
  await evalJs(`document.querySelector('#sz_28')?.click()`);
  await sleep(200);
  await evalJs(`document.querySelector('#sz_30')?.click()`);
  await sleep(300);
  const startEnabled = await evalJs(`!document.querySelector('#start')?.disabled`);
  check('勾选 28+30 后 #start 解灰', startEnabled);
  await evalJs(`document.querySelector('#start').click()`);
  console.log('SOLVE started, waiting first frame...');
  const polys = await poll(`(() => { const p = document.querySelectorAll('svg polygon[data-label]'); return p.length > 0 ? p.length : 0; })()`, 120000, 'nest polygons');
  await sleep(2500);
  await shot('05_nest_render');
  const nest = await evalJs(`(() => {
    const ps = Array.from(document.querySelectorAll('svg polygon[data-label]'));
    const labels = [...new Set(ps.map(p=>p.dataset.label))].sort();
    const legacyPtype = document.querySelectorAll('svg polygon[data-ptype]').length;
    return { n: ps.length, labels, legacyPtype };
  })()`);
  check('排料渲染 polygon 带 data-label（g 码）', nest.n > 0 && nest.labels.length > 0, JSON.stringify(nest));
  check('零 data-ptype 残留', nest.legacyPtype === 0);
  const tip = await evalJs(`(() => {
    const p = document.querySelector('svg polygon[data-label]');
    p.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
    const t = document.querySelector('.tooltip') || document.querySelector('[data-testid=tooltip]');
    return t ? t.textContent || t.innerHTML : null;
  })()`);
  const tipOk = !!tip && /g\d+\s*·\s*码\d+/.test(String(tip)) && !/前片|后片|腰|袋|裤耳/.test(String(tip));
  check('悬浮 tooltip = g 码 · 码X', tipOk, String(tip).slice(0, 80));
  await shot('06_tooltip');
  await evalJs(`document.querySelector('#stop')?.click()`);
  await sleep(800);
} catch (e) {
  check('HARNESS 无异常', false, e.message);
} finally {
  const failed = results.filter((r) => !r.ok);
  console.log(`\n==== ${results.length - failed.length}/${results.length} PASS ====`);
  chrome.kill();
  process.exit(failed.length ? 1 : 0);
}

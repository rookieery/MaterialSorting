// US-004 浏览器验证 harness（CDP headless Chrome，无外部依赖）。
// 流程：上传母版 → 高级配置矩阵弹窗（行=码号 × 列=g 码、格=d/tol 双输入、≡ 整列设值、
//       双层 modal）→ 配 g03@28 d=1.5 + g05 整列 d=2 → 求解 → 断言 WS start payload
//       per_type.g03['28'].d === 1.5（两级嵌套新格式）。
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf';
const OUT = 'D:/code/MaterialSorting/out/us004_verify';
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
  check('App 载入', await evalJs(`!!document.querySelector('.tabbar') || !!document.title`));

  // ---- 上传母版（真实 UI 路径：DOM.setFileInputFiles 触发 change → useParseDxf）----
  const doc = await send('DOM.getDocument');
  const inputNode = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' });
  if (!inputNode.nodeId) throw new Error('file input not found');
  await send('DOM.setFileInputFiles', { files: [DXF], nodeId: inputNode.nodeId });
  console.log('UPLOAD dispatched, waiting parse+matrix...');
  await poll(`!!document.querySelector('.qty-matrix')`, 90000, 'qty-matrix');
  await sleep(1200);

  // ---- 高级配置矩阵弹窗 ----
  await evalJs(`document.querySelector('.per-type-btn').click()`);
  await poll(`document.querySelectorAll('.per-type-overlay thead .qty-label-badge').length >= 10`, 15000, 'per-type cols');
  await sleep(500);
  const ov = await evalJs(`(() => {
    const o = document.querySelector('.per-type-overlay');
    const badges = Array.from(o.querySelectorAll('thead .qty-label-badge')).map(b=>b.textContent);
    const rowHeads = Array.from(o.querySelectorAll('tbody .per-type-rowhead')).map(h=>h.textContent);
    const inputs = o.querySelectorAll('tbody input[type=number]').length;
    const missing = o.querySelectorAll('td.per-type-cell.missing').length;
    const fillBtns = o.querySelectorAll('thead .qty-rowfill-btn').length;
    const g0328 = !!o.querySelector('[data-testid="d-g03-28"]') && !!o.querySelector('[data-testid="tol-g03-28"]');
    const headTitle = o.querySelector('thead .per-type-rowhead')?.textContent;
    return { badges, rowHeads, inputs, missing, fillBtns, g0328, headTitle };
  })()`);
  check('弹窗列 = 当前母版 g 码并集（g01..g10 动态列）',
    ov.badges.length === 10 && ov.badges[0] === 'g01' && ov.badges[9] === 'g10', ov.badges.join(','));
  check('弹窗行 = 参与排料码号（doc.sizes）+ 行头「码号」',
    ov.rowHeads.length >= 8 && ov.headTitle === '码号', ov.rowHeads.join(','));
  check('格 = (g 码, 码号) d/tol 双输入（d-g03-28 / tol-g03-28 存在）', ov.g0328, '');
  check('每列「≡」整列设值 icon（QtyMatrix 同款）', ov.fillBtns === 10, String(ov.fillBtns));
  await shot('01_matrix_modal');

  // ---- 双层 modal：缩略图 → PtypePreviewModal；ESC 独立 ----
  await evalJs(`document.querySelector('.per-type-overlay .ptype-thumb').click()`);
  await sleep(800);
  const pv = await evalJs(`(() => {
    const m = document.querySelector('.ptype-preview-modal');
    return { badge: m?.querySelector('.piece-card-label')?.textContent, aria: m?.getAttribute('aria-label') };
  })()`);
  check('二层裁片预览头部 = g 码徽章（label 键联调）', pv.badge === 'g01' && pv.aria === 'g01-放大预览', JSON.stringify(pv));
  await shot('02_ptype_preview');
  await evalJs(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  await sleep(250);
  const layer = await evalJs(`(() => ({
    preview: !!document.querySelector('.ptype-preview-modal'),
    modal: !!document.querySelector('.per-type-overlay'),
  }))()`);
  check('ESC 只关预览，底层弹窗保留（双层独立）', !layer.preview && layer.modal, JSON.stringify(layer));
  await evalJs(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  await sleep(300);
  const closed = await evalJs(`!document.querySelector('.per-type-overlay')`);
  check('再按 ESC 关闭高级配置弹窗（草稿丢弃，重新打开）', closed, '');
  await evalJs(`document.querySelector('.per-type-btn').click()`);
  await poll(`document.querySelectorAll('.per-type-overlay thead .qty-label-badge').length >= 10`, 15000, 'reopen modal');

  // ---- 配置：g03@28 d=1.5 + g05 整列 d=2（≡ 弹层）----
  await evalJs(`(() => {
    const i = document.querySelector('[data-testid="d-g03-28"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(i, '1.5');
    i.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await evalJs(`document.querySelector('[data-testid="per-type-fill-btn-g05"]').click()`);
  await poll(`!!document.querySelector('.qty-fill-popover')`, 5000, 'fill popover');
  await shot('03_fill_popover');
  await evalJs(`(() => {
    const i = document.querySelector('[data-testid="per-type-fill-d"]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(i, '2');
    i.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await evalJs(`document.querySelector('.qty-fill-apply').click()`);
  await sleep(250);
  const fillApplied = await evalJs(`(() => {
    const cells = Array.from(document.querySelectorAll('.per-type-overlay [data-testid^="d-g05-"]'));
    const nonEmpty = cells.filter(c => c.value === '2').length;
    const tolEmpty = cells.filter(c => document.querySelector('[data-testid="' + c.dataset.testid.replace('d-','tol-') + '"]').value === '').length;
    const g03 = document.querySelector('[data-testid="d-g03-28"]').value;
    return { cols: cells.length, nonEmpty, tolEmpty, g03, popoverClosed: !document.querySelector('.qty-fill-popover') };
  })()`);
  check('≡ 整列设值：g05 列全部行 d=2、tol 留空继承', fillApplied.popoverClosed && fillApplied.nonEmpty === fillApplied.cols && fillApplied.tolEmpty === fillApplied.cols && fillApplied.g03 === '1.5', JSON.stringify(fillApplied));
  await evalJs(`document.querySelector('.per-type-btn-confirm').click()`);
  await sleep(300);
  check('确定后弹窗关闭（配置已写回 form）', await evalJs(`!document.querySelector('.per-type-overlay')`));

  // ---- 求解：捕获 WS start payload，断言 per_type 两级嵌套 ----
  await evalJs(`(() => {
    window.__sentFrames = [];
    const orig = WebSocket.prototype.send;
    WebSocket.prototype.send = function (data) { window.__sentFrames.push(String(data)); return orig.call(this, data); };
  })()`);
  await evalJs(`document.querySelector('#sz_28')?.click()`);
  await sleep(200);
  await evalJs(`document.querySelector('#sz_30')?.click()`);
  await sleep(300);
  check('勾选 28+30 后 #start 解灰', await evalJs(`!document.querySelector('#start')?.disabled`));
  await evalJs(`document.querySelector('#start').click()`);
  console.log('SOLVE started, waiting first frame...');
  await poll(`(() => { const p = document.querySelectorAll('svg polygon[data-label]'); return p.length > 0 ? p.length : 0; })()`, 120000, 'nest polygons');
  await sleep(2000);
  await shot('04_nest_render');
  const payload = await evalJs(`(() => {
    for (const f of window.__sentFrames) {
      try { const j = JSON.parse(f); if (j.action === 'start') return j; } catch {}
    }
    return null;
  })()`);
  check('WS start payload 捕获成功', !!payload, payload ? '' : 'no start frame');
  const pt = payload && payload.per_type;
  check('per_type.g03["28"].d === 1.5（端到端 AC）', !!pt && pt.g03 && pt.g03['28'] && pt.g03['28'].d === 1.5, JSON.stringify(pt && pt.g03));
  const g05keys = pt && pt.g05 ? Object.keys(pt.g05).sort((a,b)=>a-b) : [];
  const g05ok = pt && pt.g05 && g05keys.length >= 8 && g05keys.every(k => pt.g05[k].d === 2);
  check('per_type.g05 整列 d=2（全部码号键）', g05ok, g05keys.join(','));
  const g05tolsEmpty = pt && pt.g05 && g05keys.every(k => pt.g05[k].tol === undefined);
  check('g05 tol 未写（留空侧继承默认）', g05tolsEmpty, '');
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

// US-005 prefix A/B 验收浏览器终验（CDP headless Chrome，无外部依赖；范本
// us004_prefix_verify.mjs）。与后端验收器同源同构（P0 全表数量 + 7 码 + 60s +
// seed 0 + **P0 口径 per_type**，布局设置弹窗逐码填 d/tol = 5336_coded_really.json）
// —— 本跑 = prefix_accept on 臂 seed0 的 UI 交叉对拍（密度差 ≤0.05pt 即口径闭环）。
// 截图落 .docs/business/（PRD US-005 形态判据「截图落 .docs/」）。前置：
// ms-web 在 :8000 运行（prod build）。流程：
//   1) 上传 5336 母版 → 矩阵（默认数量全 1）；
//   2) 矩阵写 P0 全表数量（g01~g05/g09/g10：31→1/36→3/其余→2；g06~g08 全 1）
//      + 勾选 7 码 31~38；
//   3) 弹窗勾选 prefix（默认预选 g02/g03）→ 确定 → #start 解灰；
//   4) 求解 60s：stage('prefix') size 回显（∈ 资格码 {32,33,34,35,38}）
//      + 状态行「起始端成套构造中（尺码 N）…」；
//   5) final 形态判据：4 成员（g02×2+g03×2 同码）无 PS_ 泄漏、min_x ≤ 6mm、
//      竖排贴触（相邻 y 缝隙 ≤1mm，负值 = 交集>0 咬合）、头尾 180° 交替；
//      final.prefix.pin 回显在案；
//   6) 与 prefix_accept 报告 on 臂 seed0 密度交叉对拍（≤0.05pt，US-014 同线）；
//   7) 截图 → .docs/business/us005_prefix_{stage,final,head_column}.png。
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9_coded.dxf';
const OUT = 'D:/code/MaterialSorting/out/us005_prefix_verify';
const DOCS = 'D:/code/MaterialSorting/.docs/business';
const REPORT = 'D:/code/MaterialSorting/materialSorting-server/out/config_runs/_probes/prefix_accept_report.json';
mkdirSync(OUT, { recursive: true });
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + String(detail).slice(0, 200) : ''}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9225', '--disable-gpu', '--no-first-run',
  '--window-size=1680,1000', `--user-data-dir=${OUT}/chrome-profile`, 'about:blank',
], { stdio: 'ignore' });
try {
  async function getTargetWs() {
    for (let i = 0; i < 20; i++) {
      try {
        const list = await (await fetch('http://127.0.0.1:9225/json')).json();
        const page = list.find((t) => t.type === 'page');
        if (page) return page.webSocketDebuggerUrl;
      } catch {}
      await sleep(300);
    }
    throw new Error('CDP target not found (9225)');
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
      await sleep(400);
    }
    throw new Error('poll timeout: ' + label);
  }
  async function shot(name, clip) {
    const params = { format: 'png' };
    if (clip) params.clip = clip;
    const r = await send('Page.captureScreenshot', params);
    const dest = `${DOCS}/${name}.png`;
    writeFileSync(dest, Buffer.from(r.data, 'base64'));
    console.log(`SHOT  ${dest}`);
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

  // WS stub：录全部 server 消息（stage 序 / final 形态判据数据源）+ 受控写值助手。
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `
    (() => {
      window.__wsMsgs = [];
      const OrigWS = window.WebSocket;
      function WrappedWS(...args) {
        const sock = new OrigWS(...args);
        sock.addEventListener('message', (ev) => {
          try { window.__wsMsgs.push(JSON.parse(ev.data)); } catch {}
        });
        return sock;
      }
      WrappedWS.prototype = OrigWS.prototype;
      window.WebSocket = WrappedWS;
      window.__setVal = async (sel, value, evName = 'input') => {
        const el = document.querySelector(sel);
        if (!el) return 'no-el';
        const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, String(value));
        el.dispatchEvent(new Event(evName, { bubbles: true }));
        await new Promise((r) => setTimeout(r, 60));
        return 'ok';
      };
      window.__setQty = async (label, size, value) => {
        const inp = document.querySelector('input[aria-label="裁片 ' + label + ' 码 ' + size + ' 数量"]');
        if (!inp) return 'no-input';
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(inp, String(value));
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        await new Promise((r) => setTimeout(r, 80));
        inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
        await new Promise((r) => setTimeout(r, 60));
        return inp.value === String(value) ? 'ok' : 'mismatch:' + inp.value;
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
  await sleep(800);
  // 切「超排」Tab（双页同挂 DOM；不切则 nesting 区 display:none → svg rect 0×0 截图失败）。
  await evalJs(`[...document.querySelectorAll('.tab')].find(x => x.textContent.includes('超排')).click()`);
  await sleep(800);

  // ---- 矩阵写 P0 全表数量（验收器同构口径）----
  const QTY = { 31: 1, 32: 2, 33: 2, 34: 2, 35: 2, 36: 3, 38: 2 };
  const DOUBLE = ['g01', 'g02', 'g03', 'g04', 'g05', 'g09', 'g10'];
  const SINGLE = ['g06', 'g07', 'g08'];
  let writeFail = 0;
  for (const label of DOUBLE) {
    for (const [size, q] of Object.entries(QTY)) {
      if (q === 1) continue;                       // 默认已 1
      const r = await evalJs(`window.__setQty('${label}', ${size}, ${q})`, true);
      if (r !== 'ok') { writeFail++; check(`矩阵写值 ${label}@${size}=${q}`, false, r); }
    }
  }
  check('矩阵写值全成功（g06~g08 保持默认 1）', writeFail === 0, `fail=${writeFail}`);
  const qsum = await evalJs(`(() => {
    const cells = Array.from(document.querySelectorAll('.qty-matrix tbody input[type=number]')).map(i=>parseInt(i.value||'0',10));
    return { n: cells.reduce((a,b)=>a+b,0), total: parseInt(document.querySelector('[data-testid=qty-total]').textContent,10) };
  })()`);
  check('矩阵写值一致（Σ格子 = 总片数）', qsum.n === qsum.total, JSON.stringify(qsum));

  // ---- 勾选 7 码（P0 口径 31~38 去 37）→ 弹窗勾选 prefix（预选 g02/g03）→ 确定 ----
  for (const sz of [31, 32, 33, 34, 35, 36, 38]) {
    await evalJs(`document.querySelector('#sz_${sz}')?.click()`);
    await sleep(120);
  }
  await sleep(300);
  await evalJs(`document.querySelector('.per-type-btn').click()`);
  await poll(`!!document.querySelector('[data-testid=per-type-prefix-row]')`, 15000, 'prefix row');
  await sleep(500);
  await evalJs(`document.querySelector('[data-testid=prefix-enabled]').click()`);
  await sleep(400);
  const p1 = await evalJs(`(() => ({
    frontVal: document.querySelector('[data-testid=prefix-front-select]').value,
    backVal: document.querySelector('[data-testid=prefix-back-select]').value,
    warn: document.querySelector('[data-testid=per-type-prefix-warn]')?.textContent || null,
  }))()`);
  check('勾选 prefix 默认预选 g02/g03 + P0 数量无警示', p1.frontVal === 'g02' && p1.backVal === 'g03' && p1.warn === null, JSON.stringify(p1));

  // ---- P0 口径 per_type（与验收器同源：data/configs/5336_coded_really.json）----
  // 终验绑定 P0 口径（PRD 基准 −0.14pt / 双开 89.33%/90.05% 出自它；web 全 0
  // 口径 60s 不收敛 → 密度对拍口径必须一致，见 prefix_accept.py 模块 docstring）。
  const PER_TYPE = { g01: [5, 8], g02: [2, 1], g03: [2, 1], g04: [0.4, 3],
    g05: [0.4, 3], g06: [10, 45], g07: [10, 15], g08: [10, 15], g09: [0.4, 30], g10: [0.4, 1] };
  for (const [g, [d, tol]] of Object.entries(PER_TYPE)) {
    await evalJs(`window.__setVal('[data-testid=d-${g}]', ${d})`, true);
    await evalJs(`window.__setVal('[data-testid=tol-${g}]', ${tol})`, true);
  }
  const pt = await evalJs(`(() => {
    const get = (s) => document.querySelector('[data-testid=' + s + ']')?.value;
    return ['g01','g02','g03','g04','g05','g06','g07','g08','g09','g10']
      .map((g) => g + '=' + get('d-' + g) + '/' + get('tol-' + g)).join(' ');
  })()`);
  check('P0 口径 per_type 填入（d/tol 逐码）', /g01=5\/8 .*g02=2\/1 .*g03=2\/1 .*g10=0\.4\/1/.test(pt), pt);
  await evalJs(`document.querySelector('.per-type-btn-confirm').click()`);
  await sleep(400);
  check('#start 解灰（prefix 闸门通过）', await evalJs(`document.querySelector('#start')?.disabled`) === false);

  // ---- 求解 60s（与验收器 on 臂同预算）----
  await evalJs(`window.__setVal('#time', 60)`, true);
  await evalJs(`window.__wsMsgs.length = 0`);
  await evalJs(`document.querySelector('#start').click()`);
  console.log('SOLVE started, waiting stage...');
  const stageText = await poll(`(() => { const s = document.querySelector('#status')?.textContent || ''; return s.includes('起始端成套构造中') ? s : null; })()`, 30000, 'stage status line');
  check('状态行 stage 提示（含尺码回显）', /起始端成套构造中（尺码 \d+）/.test(stageText), stageText);
  const finalMsg = await poll(`(() => { const m = window.__wsMsgs.filter(x=>x.type==='final'); return m.length ? m[m.length-1] : null; })()`, 180000, 'final');
  const msgs = await evalJs(`window.__wsMsgs.map(m=>m.type + (m.type==='stage'?':'+m.stage:''))`);
  const stageMsg = (await evalJs(`window.__wsMsgs.filter(x=>x.type==='stage'&&x.stage==='prefix')`))[0];
  check("stage('prefix') 在 manifest 之前", msgs.indexOf('stage:prefix') >= 0 && msgs.indexOf('manifest') > msgs.indexOf('stage:prefix'), JSON.stringify(msgs.slice(0, 4)));
  const ELIGIBLE = [32, 33, 34, 35, 38];
  check('stage.size 回显资格码 ∈ {32,33,34,35,38}', ELIGIBLE.includes(stageMsg?.size), String(stageMsg?.size));
  const size = stageMsg?.size;
  check('final.prefix 统计段在场（pid/pin 回显）', !!finalMsg.prefix && /PS_/.test(String(finalMsg.prefix.pid)) && finalMsg.prefix.size === size
    && finalMsg.prefix.pin && typeof finalMsg.prefix.pin.skipped === 'boolean',
    JSON.stringify(finalMsg.prefix?.pin));

  // PS_ 泄漏哨兵：manifest pieces pid + 全部帧 placed id（final.prefix.pid 是设计内
  // 统计回显不算泄漏；routes_ws 转发的 final 无 placed_items —— 前端权威渲染 = 末帧）
  const leakProbe = await evalJs(`(() => {
    const man = window.__wsMsgs.filter(x=>x.type==='manifest')[0];
    const pids = ((man && man.pieces) || []).map(p => p.pid || p.id || '').join(',');
    const placedIds = window.__wsMsgs.filter(x=>x.type==='frame').flatMap(f => (f.placed_items||[]).map(p => p.id)).join(',');
    return { man: pids.includes('PS_'), frames: placedIds.includes('PS_') };
  })()`);
  check('PS_ 组合片零泄漏（manifest pieces + 帧序列）', !leakProbe.man && !leakProbe.frames, JSON.stringify(leakProbe));

  // 4 成员守恒（末帧 = 前端权威渲染源）：g02_{size}×2 + g03_{size}×2
  const placed = (await evalJs(`(() => { const f = window.__wsMsgs.filter(x=>x.type==='frame'); return f[f.length-1].placed_items; })()`)) || [];
  const members = placed.filter(p => p.id === 'g02_' + size || p.id === 'g03_' + size);
  const frontN = placed.filter(p => p.id === 'g02_' + size).length;
  const backN = placed.filter(p => p.id === 'g03_' + size).length;
  check('4 成员守恒（g02×2 + g03×2 @码' + size + '）', frontN === 2 && backN === 2, 'front=' + frontN + ' back=' + backN + ' total=' + placed.length);

  // 形态判据：头尾 180° 交替（placed 构造序 = interleave 展开序；translation.y
  // 排序不可用 —— rot180 成员局部原点≠bbox 原点，US-004 踩坑记档）
  const seq = members.slice();
  const isFront = (p) => p.id.startsWith('g02_');
  const interleaveOk = seq.length === 4 && seq.slice(1).every((m, i) => isFront(m) !== isFront(seq[i]));
  const rotOk = seq.length === 4 && seq.slice(1).every((m, i) => {
    const d = Math.abs(((m.rotation - seq[i].rotation) % 360 + 360) % 360);
    return Math.min(d, 360 - d) >= 175;
  });
  check('interleave 交错序（前后前后连续展开）', interleaveOk, seq.map(m => m.id).join(' → '));
  check('头尾 180° 交替（相邻成员 rotation 差 ≈180°）', rotOk,
    seq.map(m => m.id + '@' + Math.round(m.rotation) + '°').join(' → '));

  // 形态判据（DOM polygon 世界坐标 bbox，SVG points DOM API —— 避开字符串解析）：
  // 竖排贴触 + min_x ≤ 6mm
  const geo = await evalJs(`(function () {
    var want = String(${size});
    var polys = Array.from(document.querySelectorAll('.nest-card svg polygon[data-label]'))
      .filter(function (p) { return (p.dataset.label === 'g02' || p.dataset.label === 'g03') && p.dataset.size === want; })
      .map(function (p) {
        var pts = Array.from(p.points).map(function (pt) { return [pt.x, pt.y]; });
        var xs = pts.map(function (q) { return q[0]; }), ys = pts.map(function (q) { return q[1]; });
        return { label: p.dataset.label, x0: Math.min.apply(null, xs), x1: Math.max.apply(null, xs), y0: Math.min.apply(null, ys), y1: Math.max.apply(null, ys), n: pts.length };
      });
    var all = Array.from(document.querySelectorAll('.nest-card svg polygon[data-label]')).map(function (p) {
      return Math.min.apply(null, Array.from(p.points).map(function (pt) { return pt.x; }));
    });
    return { members: polys, globalMinX: Math.min.apply(null, all) };
  })()`);
  check('4 成员 polygon 在场（毛版层、多顶点）', geo.members.length === 4 && geo.members.every(m => m.n >= 8), JSON.stringify(geo.members.map(m => m.label + '/' + m.n)));
  const minX = Math.min(...geo.members.map(m => m.x0));
  check('前缀锚定布头（min_x ≤ 6mm，实测 ' + minX.toFixed(2) + 'mm）', minX <= 6, 'global min_x = ' + geo.globalMinX.toFixed(2));
  const stack = geo.members.slice().sort((a, b) => a.y0 - b.y0);
  const gaps = stack.slice(1).map((m, i) => +(m.y0 - stack[i].y1).toFixed(2));
  check('竖排贴触（相邻 y 缝隙 ≤1mm，负值 = 交集>0 咬合）', gaps.every(g => g <= 1.0), 'gaps=' + JSON.stringify(gaps));
  const spanY = Math.max(...stack.map(m => m.y1)) - Math.min(...stack.map(m => m.y0));
  const sumH = stack.reduce((a, m) => a + (m.y1 - m.y0), 0);
  check('竖排形态（4 片 y 跨度 < Σ片高 = 竖向叠放）', spanY < sumH && spanY > sumH * 0.5, 'span=' + spanY.toFixed(0) + ' Σh=' + sumH.toFixed(0));

  // 截图：stage 状态行（回放已过，截最终态）+ 全版 + 布头第一列放大
  await sleep(1500);
  await shot('us005_prefix_final_full');
  const rect = await evalJs(`(() => { const r = document.querySelector('.nest-card svg polygon[data-label]')?.closest('svg')?.getBoundingClientRect(); return r && r.height > 10 ? { x: r.x, y: r.y, w: r.width, h: r.height } : null; })()`);
  if (rect) {
    await shot('us005_prefix_head_column', { x: rect.x, y: rect.y, width: Math.max(120, rect.w * 0.28), height: rect.h, scale: 1 });
  }
  const dens = (finalMsg.density * 100).toFixed(3);
  console.log('FINAL: density=' + dens + '% width=' + Math.round(finalMsg.width_mm) + 'mm placed=' + placed.length + ' size=' + size + ' pin.skipped=' + finalMsg.prefix?.pin?.skipped);
  console.log('MEMBERS: ' + stack.map(m => m.label + ' x[' + m.x0.toFixed(1) + ',' + m.x1.toFixed(1) + '] y[' + m.y0.toFixed(1) + ',' + m.y1.toFixed(1) + ']').join(' | '));

  // 与后端验收器 on 臂 seed0 交叉对拍（同源同构：P0 表 + 7 码 + 60s + seed 0）
  if (existsSync(REPORT)) {
    const rep = JSON.parse(readFileSync(REPORT, 'utf-8'));
    const row = (rep.density_ab?.per_seed || []).find(r => r.seed === 0);
    if (row && row.on && row.on.density_pct != null) {
      const d = Math.abs(row.on.density_pct - parseFloat(dens));
      check('与验收器 on 臂 seed0 密度交叉对拍（差 ' + d.toFixed(3) + 'pt ≤ 0.05pt）', d <= 0.05,
        'ui=' + dens + '% harness=' + row.on.density_pct + '%');
    } else {
      check('验收器报告可读（on 臂 seed0 行）', false, 'row missing');
    }
  } else {
    check('验收器报告在场（先跑 prefix_accept）', false, REPORT);
  }
} catch (e) {
  check('HARNESS 无异常', false, e.message);
} finally {
  try { chrome.kill(); } catch {}
  const failed = results.filter((r) => !r.ok);
  console.log('\n==== US-005 prefix verify: ' + (results.length - failed.length) + '/' + results.length + ' PASS ====');
  process.exit(failed.length ? 1 : 0);
}

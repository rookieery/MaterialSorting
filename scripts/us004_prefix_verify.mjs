// US-004 prefix（起始端成套前后幅）浏览器验证 harness（CDP headless Chrome，无外部依赖；
// 范本 us006_verify.mjs）。前置：ms-web 在 :8000 运行。流程：
//   1) 上传 5336 母版 → 矩阵（默认数量全 1）；
//   2) 高级配置弹窗「布局设置」prefix 分区：未勾选下拉 disabled / 勾选默认预选 g02·g03
//      （面积最大两片，决策⑤）/ 无资格码警示（默认数量 1 → 2+2 无资格）/
//      front==back 警示 / 取消丢弃草稿 / 暗色主题截图；
//   3) 矩阵设 g02·g03 @码{33,34} = 2 → 勾选码 33+34 → 重开弹窗警示消失 → 确定；
//   4) ControlPanel：#start 解灰、策略入口互斥（disabled+title）；
//   5) 求解 25s：WS stub 录全程消息 → stage('prefix') 序（manifest 前）+ size 回显
//      + 状态行「起始端成套构造中（尺码 N）…」；
//   6) final 形态判据：4 成员（g02×2+g03×2 同码）无 PS_ 泄漏、min_x ≤ 6mm、
//      竖排贴触（相邻 y 缝隙 ≤1mm）、头尾 180° 交替（相邻 rotation 差 ≈180°）；
//   7) 截图：弹窗暗色主题 / 全版渲染 / 布头第一列放大。
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/5336#老六订单14%7%围加9_coded.dxf';
const OUT = 'D:/code/MaterialSorting/out/us004_prefix_verify';
mkdirSync(OUT, { recursive: true });
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + String(detail).slice(0, 200) : ''}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9224', '--disable-gpu', '--no-first-run',
  '--window-size=1680,1000', `--user-data-dir=${OUT}/chrome-profile`, 'about:blank',
], { stdio: 'ignore' });
try {
  async function getTargetWs() {
    for (let i = 0; i < 20; i++) {
      try {
        const list = await (await fetch('http://127.0.0.1:9224/json')).json();
        const page = list.find((t) => t.type === 'page');
        if (page) return page.webSocketDebuggerUrl;
      } catch {}
      await sleep(300);
    }
    throw new Error('CDP target not found (9224)');
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

  // WS stub：录全部 server 消息（stage 序 / final 形态判据数据源）。
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
      // 受控 input/setSelect 通用写值（React onChange 走原生 setter + input/change 事件）。
      window.__setVal = async (sel, value, evName = 'input') => {
        const el = document.querySelector(sel);
        if (!el) return 'no-el';
        const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, String(value));
        el.dispatchEvent(new Event(evName, { bubbles: true }));
        await new Promise((r) => setTimeout(r, 60));
        return 'ok';
      };
      // 数量矩阵格子写值（draft → Enter commit；aria-label 定位）。
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
  const sizesRow = await evalJs(`Array.from(document.querySelectorAll('.qty-rowhead .qty-size-btn')).map(b=>b.textContent)`);
  console.log('DOC sizes:', JSON.stringify(sizesRow));
  // 切「超排」Tab（双页同挂 DOM；不切则 nesting 区 display:none → svg rect 0×0 截图失败）。
  await evalJs(`[...document.querySelectorAll('.tab')].find(x => x.textContent.includes('超排')).click()`);
  await sleep(800);


  // ---- 弹窗第一轮：默认数量（全 1）+ 未选码 → 无资格码警示 + 预选启发式 ----
  await evalJs(`document.querySelector('.per-type-btn').click()`);
  await poll(`!!document.querySelector('[data-testid=per-type-prefix-row]')`, 15000, 'prefix row');
  await sleep(600);
  const p1 = await evalJs(`(() => {
    const row = document.querySelector('[data-testid=per-type-prefix-row]');
    return {
      note: document.querySelector('[data-testid=per-type-prefix-note]')?.textContent || '',
      checked: document.querySelector('[data-testid=prefix-enabled]').checked,
      frontDisabled: document.querySelector('[data-testid=prefix-front-select]').disabled,
      backDisabled: document.querySelector('[data-testid=prefix-back-select]').disabled,
      frontVal: document.querySelector('[data-testid=prefix-front-select]').value,
      backVal: document.querySelector('[data-testid=prefix-back-select]').value,
      warn: document.querySelector('[data-testid=per-type-prefix-warn]')?.textContent || null,
      modalBg: getComputedStyle(document.querySelector('.per-type-modal')).backgroundColor,
      bandRowAbove: !!row.previousElementSibling?.classList?.contains('per-type-band-row'),
    };
  })()`);
  check('prefix 分区在 band 行之后、说明文案在场', p1.bandRowAbove && p1.note.includes('满足 2+2 的尺码将自动选取'), p1.note);
  check('未勾选：checkbox false + 两下拉 disabled', !p1.checked && p1.frontDisabled && p1.backDisabled);
  check('暗色主题（#26282e modal 背景）', p1.modalBg === 'rgb(38, 40, 46)', p1.modalBg);
  await shot('01_modal_dark_prefix_row');

  // 勾选 → 默认预选面积最大两片（5336 = g02 前 / g03 后，决策⑤）
  await evalJs(`document.querySelector('[data-testid=prefix-enabled]').click()`);
  await sleep(400);
  const p2 = await evalJs(`(() => ({
    frontVal: document.querySelector('[data-testid=prefix-front-select]').value,
    backVal: document.querySelector('[data-testid=prefix-back-select]').value,
    frontDisabled: document.querySelector('[data-testid=prefix-front-select]').disabled,
    backDisabled: document.querySelector('[data-testid=prefix-back-select]').disabled,
    warn: document.querySelector('[data-testid=per-type-prefix-warn]')?.textContent || null,
    thumbFront: !!document.querySelector('[data-testid=prefix-thumb-g02]'),
    thumbBack: !!document.querySelector('[data-testid=prefix-thumb-g03]'),
  }))()`);
  check('勾选即默认预选 g02/g03（面积最大两片）', p2.frontVal === 'g02' && p2.backVal === 'g03', JSON.stringify({ f: p2.frontVal, b: p2.backVal }));
  check('勾选后两下拉解灰', !p2.frontDisabled && !p2.backDisabled);
  check('默认数量(1)+未选码 → 警示「当前数量无 2+2 资格码」', !!p2.warn && p2.warn.includes('当前数量无 2+2 资格码'), p2.warn);
  check('前/后幅 80×80 缩略图徽章在场', p2.thumbFront && p2.thumbBack);
  await shot('02_modal_checked_no_eligible');

  // front==back 警示（同码拦截本地预检）
  await evalJs(`window.__setVal('[data-testid=prefix-back-select]', 'g02', 'change')`, true);
  await sleep(300);
  const p3 = await evalJs(`document.querySelector('[data-testid=per-type-prefix-warn]')?.textContent || null`);
  check('front==back → 警示「须为不同 g 码」', !!p3 && p3.includes('不同 g 码'), p3);
  await evalJs(`window.__setVal('[data-testid=prefix-back-select]', 'g03', 'change')`, true);
  await sleep(300);

  // 取消丢弃草稿（draft+confirm 语义）
  await evalJs(`document.querySelector('.per-type-btn-cancel').click()`);
  await sleep(400);
  await evalJs(`document.querySelector('.per-type-btn').click()`);
  await poll(`!!document.querySelector('[data-testid=per-type-prefix-row]')`, 15000, 'prefix row 2');
  await sleep(400);
  const p4 = await evalJs(`(() => ({
    checked: document.querySelector('[data-testid=prefix-enabled]').checked,
    frontVal: document.querySelector('[data-testid=prefix-front-select]').value,
  }))()`);
  check('取消丢弃草稿（重开 checkbox false + front 空）', !p4.checked && p4.frontVal === '', JSON.stringify(p4));
  await evalJs(`document.querySelector('.per-type-btn-cancel').click()`);
  await sleep(300);

  // ---- 矩阵设量：5336 真实单 g02/g03 数量（31→1、36→3、其余→2；P0 口径）----
  const ELIGIBLE = [32, 33, 34, 35, 38];
  const PICK_SIZES = [31, 32, 33, 34, 35, 36, 38];
  const QTY = { 31: 1, 32: 2, 33: 2, 34: 2, 35: 2, 36: 3, 38: 2 };
  for (const label of ['g02', 'g03']) {
    for (const size of PICK_SIZES) {
      const r = await evalJs(`window.__setQty('${label}', ${size}, ${QTY[size]})`, true);
      if (r !== 'ok') check(`矩阵写值 ${label}@${size}=${QTY[size]}`, false, r);
    }
  }
  const qsum = await evalJs(`(() => {
    const cells = Array.from(document.querySelectorAll('.qty-matrix tbody input[type=number]')).map(i=>parseInt(i.value||'0',10));
    return { n: cells.reduce((a,b)=>a+b,0), total: parseInt(document.querySelector('[data-testid=qty-total]').textContent,10) };
  })()`);
  check('矩阵写值成功（Σ格子 = 总片数）', qsum.n === qsum.total, JSON.stringify(qsum));

  // ---- 勾选码（真实 7 码 31~38，P0 口径）→ 重开弹窗：警示消失 + 确定 ----
  for (const sz of PICK_SIZES) {
    await evalJs(`document.querySelector('#sz_${sz}')?.click()`);
    await sleep(150);
  }
  await sleep(300);
  await evalJs(`document.querySelector('.per-type-btn').click()`);
  await poll(`!!document.querySelector('[data-testid=per-type-prefix-row]')`, 15000, 'prefix row 3');
  await sleep(500);
  await evalJs(`document.querySelector('[data-testid=prefix-enabled]').click()`);
  await sleep(400);
  const p5 = await evalJs(`(() => ({
    frontVal: document.querySelector('[data-testid=prefix-front-select]').value,
    backVal: document.querySelector('[data-testid=prefix-back-select]').value,
    warn: document.querySelector('[data-testid=per-type-prefix-warn]')?.textContent || null,
  }))()`);
  check('资格码存在（码32/33/34/35/38 2+2）→ 无警示', p5.warn === null, p5.warn);
  check('预选仍 g02/g03', p5.frontVal === 'g02' && p5.backVal === 'g03', JSON.stringify(p5));
  await shot('03_modal_eligible_ok');
  await evalJs(`document.querySelector('.per-type-btn-confirm').click()`);
  await sleep(400);

  // ---- ControlPanel：start 解灰 + 策略互斥 ----
  const cp = await evalJs(`(() => ({
    startDisabled: document.querySelector('#start')?.disabled,
    strategyDisabled: document.querySelector('[data-testid=strategy-btn]')?.disabled,
    strategyTitle: document.querySelector('[data-testid=strategy-btn]')?.title || '',
  }))()`);
  check('确定回写后 #start 解灰（prefix 闸门通过）', cp.startDisabled === false);
  check('策略入口互斥（disabled + title 说明）', cp.strategyDisabled === true && /互斥/.test(cp.strategyTitle), cp.strategyTitle);

  // ---- 求解 60s（P0 常态负载：组合片自然锚定布头，pin skip）----
  await evalJs(`window.__setVal('#time', 60)`, true);
  const timeVal = await evalJs(`document.querySelector('#time').value`);
  check('时长设 60s', timeVal === '60', timeVal);
  await evalJs(`window.__wsMsgs.length = 0`);
  await evalJs(`document.querySelector('#start').click()`);
  console.log('SOLVE started, waiting stage...');
  const stageText = await poll(`(() => { const s = document.querySelector('#status')?.textContent || ''; return s.includes('起始端成套构造中') ? s : null; })()`, 30000, 'stage status line');
  check('状态行 stage 提示（含尺码回显）', /起始端成套构造中（尺码 \d+）/.test(stageText), stageText);
  await shot('04_stage_status');
  const finalMsg = await poll(`(() => { const m = window.__wsMsgs.filter(x=>x.type==='final'); return m.length ? m[m.length-1] : null; })()`, 180000, 'final');
  const msgs = await evalJs(`window.__wsMsgs.map(m=>m.type + (m.type==='stage'?':'+m.stage:''))`);

  // stage 序：prefix stage 在 manifest 前，size ∈ {33,34}
  const stageIdx = msgs.indexOf('stage:prefix');
  const manifestIdx = msgs.indexOf('manifest');
  const stageMsg = (await evalJs(`window.__wsMsgs.filter(x=>x.type==='stage'&&x.stage==='prefix')`))[0];
  check("stage('prefix') 在 manifest 之前", stageIdx >= 0 && manifestIdx > stageIdx, JSON.stringify(msgs.slice(0, 4)));
  check('stage.size 回显资格码 ∈ {32,33,34,35,38}', ELIGIBLE.includes(stageMsg?.size), String(stageMsg?.size));
  const size = stageMsg?.size;

  // PS_ 泄漏哨兵：manifest pieces pid + 全部帧 placed id（final.prefix.pid 是设计内
  // 统计回显不算泄漏；routes_ws 转发的 final 无 placed_items —— 前端权威渲染 = 末帧）
  const leakProbe = await evalJs(`(() => {
    const man = window.__wsMsgs.filter(x=>x.type==='manifest')[0];
    const pids = ((man && man.pieces) || []).map(p => p.pid || p.id || '').join(',');
    const placedIds = window.__wsMsgs.filter(x=>x.type==='frame').flatMap(f => (f.placed_items||[]).map(p => p.id)).join(',');
    return { man: pids.includes('PS_'), frames: placedIds.includes('PS_') };
  })()`);
  check('PS_ 组合片零泄漏（manifest pieces + 帧序列）', !leakProbe.man && !leakProbe.frames, JSON.stringify(leakProbe));
  check('final.prefix 统计段在场（pid/pin 回显）', !!finalMsg.prefix && /PS_/.test(String(finalMsg.prefix.pid)) && finalMsg.prefix.size === size, JSON.stringify(finalMsg.prefix));

  // 4 成员守恒（末帧 = 前端权威渲染源）：g02_{size}×2 + g03_{size}×2
  const placed = (await evalJs(`(() => { const f = window.__wsMsgs.filter(x=>x.type==='frame'); return f[f.length-1].placed_items; })()`)) || [];
  const members = placed.filter(p => p.id === 'g02_' + size || p.id === 'g03_' + size);
  const frontN = placed.filter(p => p.id === 'g02_' + size).length;
  const backN = placed.filter(p => p.id === 'g03_' + size).length;
  check('4 成员守恒（g02×2 + g03×2 @码' + size + '）', frontN === 2 && backN === 2, 'front=' + frontN + ' back=' + backN + ' total=' + placed.length);

  // 形态判据①：头尾 180° 交替。placed_items 中 4 成员连续（_emit_placed 按构造序
  // 展开 = interleave 前后前后；translation.y 排序不可用 —— rot180 成员局部原点≠bbox 原点）。
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

  // 形态判据②③（DOM polygon 世界坐标 bbox，SVG points DOM API —— 避开字符串解析）：竖排贴触 + min_x ≤ 6mm
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
  check('竖排贴触（相邻 y 缝隙 ≤1mm，负值 = 交集>0）', gaps.every(g => g <= 1.0), 'gaps=' + JSON.stringify(gaps));
  const spanY = Math.max(...stack.map(m => m.y1)) - Math.min(...stack.map(m => m.y0));
  const sumH = stack.reduce((a, m) => a + (m.y1 - m.y0), 0);
  check('竖排形态（4 片 y 跨度 < Σ片高 = 竖向叠放）', spanY < sumH && spanY > sumH * 0.5, 'span=' + spanY.toFixed(0) + ' Σh=' + sumH.toFixed(0));

  // 截图：全版 + 布头第一列放大（SVG 左 ~28%；tab 已切超排，rect 非 0）
  await sleep(1500);
  await shot('05_final_full');
  const rect = await evalJs(`(() => { const r = document.querySelector('.nest-card svg polygon[data-label]')?.closest('svg')?.getBoundingClientRect(); return r && r.height > 10 ? { x: r.x, y: r.y, w: r.width, h: r.height } : null; })()`);
  if (rect) {
    await shot('06_head_column', { x: rect.x, y: rect.y, width: Math.max(120, rect.w * 0.28), height: rect.h, scale: 1 });
  }
  console.log('FINAL: density=' + (finalMsg.density * 100).toFixed(2) + '% width=' + Math.round(finalMsg.width_mm) + 'mm placed=' + placed.length + ' size=' + size);
  console.log('MEMBERS: ' + stack.map(m => m.label + ' x[' + m.x0.toFixed(1) + ',' + m.x1.toFixed(1) + '] y[' + m.y0.toFixed(1) + ',' + m.y1.toFixed(1) + ']').join(' | '));
} catch (e) {
  check('HARNESS 无异常', false, e.message);
} finally {
  try { chrome.kill(); } catch {}
  const failed = results.filter((r) => !r.ok);
  console.log('\n==== US-004 prefix verify: ' + (results.length - failed.length) + '/' + results.length + ' PASS ====');
  process.exit(failed.length ? 1 : 0);
}

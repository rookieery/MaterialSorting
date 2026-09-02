// US-005（2026-09-02 异码补片）端到端 UI 冒烟 —— 上传 → 布局设置开 prefix →
// 预览 5 片 + 异码标注 → 求解 → 状态行 → final 形态判据 → 导出 PLT 无 PS_。
// 套路范本 scripts/smoke-band-preview.mjs（playwright 流程骨架）+ out/us004_extra_verify
// /verify.mjs（CDP headless 实装，Node >=22 原生 WebSocket，零额外依赖）。
// 前置：ms-web 在 :8000 运行（static/ 已 npm run build；intermediate 由本脚本上传
// commit 自动生成）。产物：out/smoke_prefix_extra/{report.json, 0*.png, export_on.plt,
// prefix_artifact.json}；退出码 0 = 全部检查 PASS。
import { spawn } from 'node:child_process';
import { writeFileSync, copyFileSync, readdirSync, statSync, readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// 路径锚定脚本位置（任意 CWD 可跑）：scripts/ -> materialSorting-web/ -> repo 根
const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const APP = 'http://127.0.0.1:8000/';
const DXF = resolve(ROOT, 'data/5336#老六订单14%7%围加9_coded.dxf');
const OUT = resolve(ROOT, 'out/smoke_prefix_extra');
mkdirSync(OUT, { recursive: true });
// prefix_runs 工件真实位置 = paths.OUT_DIR（materialSorting-server/out/，包位置上溯）
const PREFIX_RUNS = resolve(ROOT, 'materialSorting-server/out/prefix_runs');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
// P0 口径（与 prefix_accept / 5336_coded_really 同源）：7 码 + 全量数量阵（Sdemand=105）
// + per_type g02/g03 d=2 tol=1（d_g=2 -> 选码 @38 + 顶部 g02@32，residual ~1.5mm）。
const ELIGIBLE = [32, 33, 34, 35, 38];
const PICK_SIZES = [31, 32, 33, 34, 35, 36, 38];
const FULL_LABELS = ['g01', 'g02', 'g03', 'g04', 'g05'];
const SOLVE_TIME = 60;
const EXPECT_TOTAL = 105; // 5x14 + 5x7（5336_coded_really 限 7 码 Sdemand）

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail: String(detail ?? '') });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + String(detail).slice(0, 300) : ''}`);
  return ok;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9226', '--disable-gpu', '--no-first-run',
  '--window-size=1680,1000', `--user-data-dir=${OUT}/chrome-profile`, 'about:blank',
], { stdio: 'ignore' });

// ---- report 骨架（形态判据逐项打点在案）------------------------------------
const report = {
  ts: new Date().toISOString(),
  app: APP, dxf: DXF, solve_time_s: SOLVE_TIME,
  config: { sizes: PICK_SIZES, full_labels: FULL_LABELS,
    per_type: { g02: { d: 2, tol: 1 }, g03: { d: 2, tol: 1 } }, expect_total: EXPECT_TOTAL },
  preview: null, stage: null, final: null, form: null, conservation: null,
  ps_leak: null, export: null, artifact: null, checks: results, pass: false,
};

try {
  async function getTargetWs() {
    for (let i = 0; i < 20; i++) {
      try {
        const list = await (await fetch('http://127.0.0.1:9226/json')).json();
        const page = list.find((t) => t.type === 'page');
        if (page) return page.webSocketDebuggerUrl;
      } catch {}
      await sleep(300);
    }
    throw new Error('CDP target not found (9226)');
  }
  let ws, nextId = 1; const pending = new Map();
  function send(method, params = {}) {
    const id = nextId++;
    return new Promise((resolve_, reject) => {
      pending.set(id, { resolve: resolve_, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async function evalJs(expr, awaitPromise = false) {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise });
    if (r.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.exceptionDetails).slice(0, 2000));
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

  // WS 抓包（stage/final 帧）+ fetch 抓包（/export 响应字节 = PLT 泄漏判据数据源）
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `
    (() => {
      window.__wsMsgs = [];
      window.__fetchCaps = [];
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
      const OrigFetch = window.fetch;
      window.fetch = async function (...args) {
        const res = await OrigFetch.apply(this, args);
        const url = String(args[0]);
        if (url.includes('/export') || url.includes('plt-table-preview')) {
          const cap = { url, status: res.status, type: res.headers.get('content-type'),
                        cd: res.headers.get('content-disposition') };
          try {
            const buf = await res.clone().arrayBuffer();
            const bytes = new Uint8Array(buf);
            let bin = '';
            for (let i = 0; i < bytes.length; i += 0x8000)
              bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
            cap.b64 = btoa(bin); cap.bytes = bytes.length;
          } catch (e) { cap.err = String(e); }
          window.__fetchCaps.push(cap);
        }
        return res;
      };
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
  check('1a App 载入（TabBar）', await evalJs(`!!document.querySelector('.tabbar')`));

  // ---- 上传母版 → 数量矩阵 + 自动 commit → 切「超排」-----------------------
  const doc = await send('DOM.getDocument');
  const inputNode = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' });
  if (!inputNode.nodeId) throw new Error('file input not found');
  await send('DOM.setFileInputFiles', { files: [DXF], nodeId: inputNode.nodeId });
  await poll(`!!document.querySelector('.qty-matrix')`, 90000, 'qty-matrix');
  await poll(`(() => { const b = [...document.querySelectorAll('.tab')].find(x => x.textContent.includes('超排')); return b && !b.disabled; })()`, 90000, 'commit done');
  await sleep(800);
  await evalJs(`[...document.querySelectorAll('.tab')].find(x => x.textContent.includes('超排')).click()`);
  await sleep(800);

  // ---- 矩阵设量（P0 全量口径）+ 勾选 7 码 ---------------------------------
  for (const label of FULL_LABELS) {
    for (const size of [32, 33, 34, 35, 38]) {
      const r = await evalJs(`window.__setQty('${label}', ${size}, 2)`, true);
      if (r !== 'ok') check(`矩阵写值 ${label}@${size}=2`, false, r);
    }
    const r36 = await evalJs(`window.__setQty('${label}', 36, 3)`, true);
    if (r36 !== 'ok') check(`矩阵写值 ${label}@36=3`, false, r36);
  }
  for (const sz of PICK_SIZES) {
    await evalJs(`document.querySelector('#sz_${sz}')?.click()`);
    await sleep(120);
  }
  await sleep(300);

  // ---- 布局设置：per_type d/tol → 开 prefix → 预览 5 片 + 异码标注 -------
  await evalJs(`document.querySelector('.per-type-btn').click()`);
  await poll(`!!document.querySelector('[data-testid=per-type-prefix-row]')`, 15000, 'prefix row');
  await sleep(400);
  for (const [tid, v] of [['d-g02', 2], ['tol-g02', 1], ['d-g03', 2], ['tol-g03', 1]]) {
    const r = await evalJs(`window.__setVal('[data-testid="${tid}"]', ${v})`, true);
    if (r !== 'ok') check(`per_type 写值 ${tid}=${v}`, false, r);
  }
  await sleep(200);
  await evalJs(`document.querySelector('[data-testid=prefix-enabled]').click()`);
  await sleep(400);
  const thumbInfo = await poll(`(() => {
    const t = document.querySelector('[data-testid="prefix-thumb-g02+g03"]');
    if (!t) return null;
    const ms = t.querySelectorAll('[data-role=band-member]');
    return { n: ms.length, sizes: Array.from(ms).map(p => p.dataset.size),
      fills: Array.from(ms).map(p => p.getAttribute('fill')) };
  })()`, 30000, 'prefix thumb');
  check('2a 预览缩略 5 片（4 同码基座 + 顶部异码补片）', thumbInfo.n === 5, JSON.stringify(thumbInfo));
  const fills = thumbInfo.fills;
  const baseFill = fills[0];
  check('2b 4 基座同色 + 顶片异色（size_color(B) 跨片型同码同色）',
    fills.slice(0, 4).every(f => f === baseFill) && fills[4] !== baseFill,
    'fills=' + JSON.stringify(fills));
  const extraSizePreview = thumbInfo.sizes[4];
  check('2c 顶片尺码 != 基座码（异码）', extraSizePreview !== thumbInfo.sizes[0],
    'sizes=' + JSON.stringify(thumbInfo.sizes));
  await shot('01_prefix_thumb_5');

  // 放大层：异码标注文案「＋ 顶部 B@码 异码片 · 余 X mm 近满幅」
  await evalJs(`document.querySelector('[data-testid="prefix-thumb-g02+g03"]').click()`);
  await poll(`!!document.querySelector('[data-testid=prefix-zoom-overlay]')`, 8000, 'zoom open');
  await sleep(500);
  const zoom = await evalJs(`(() => ({
    hint: document.querySelector('.band-zoom-hint')?.textContent || '',
    stats: document.querySelector('.band-zoom-stats')?.textContent || '',
    labels: Array.from(document.querySelectorAll('[data-role=band-size-label]')).map(l => l.textContent),
  }))()`);
  const m = zoom.hint.match(/＋\s*顶部\s*(g\d+)@(\d+)\s*异码片\s*·\s*余\s*([\d.]+)mm\s*近满幅/);
  check('2d 放大层异码标注「＋ 顶部 B@码 异码片 · 余 X mm 近满幅」', !!m, zoom.hint);
  check('2e 放大层标注 5 片（含异码补片 g 码）', zoom.labels.length === 5, JSON.stringify(zoom.labels));
  const extraLabelPreview = m ? m[1] : '';
  const extraSizeFromHint = m ? m[2] : '';
  const residualPreview = m ? parseFloat(m[3]) : -1;
  report.preview = { ...thumbInfo, extra_label: extraLabelPreview,
    extra_size: extraSizeFromHint, residual_mm: residualPreview };
  await shot('02_prefix_zoom_extra');
  await evalJs(`document.querySelector('[data-testid=prefix-zoom-close]').click()`);
  await sleep(200);
  await evalJs(`document.querySelector('.per-type-btn-confirm').click()`);
  await sleep(400);

  // ---- 求解 60s → 状态行 → final ----------------------------------------
  await evalJs(`window.__setVal('#time', ${SOLVE_TIME})`, true);
  await evalJs(`window.__wsMsgs.length = 0`);
  const solveT0 = Date.now();
  await evalJs(`document.querySelector('#start').click()`);
  console.log('SOLVE started, waiting prefix stage...');
  const stageText = await poll(`(() => { const s = document.querySelector('#status')?.textContent || ''; return s.includes('起始端成套构造中') ? s : null; })()`, 45000, 'stage status line');
  const sm = stageText.match(/起始端成套构造中（尺码 (\d+)＋(g\d+)@(\d+)）…/);
  check('3a 求解状态行双形态「尺码 A＋B@码」（异码码在案）', !!sm, stageText);
  await shot('03_stage_status_extra');
  const finalMsg = await poll(`(() => { const f = window.__wsMsgs.filter(x=>x.type==='final'); return f.length ? f[f.length-1] : null; })()`, 180000, 'final');
  const stageMsg = (await evalJs(`window.__wsMsgs.filter(x=>x.type==='stage'&&x.stage==='prefix')`))[0];
  // WS final 帧不带 placed_items（协议：密度/宽/prefix 统计段）；末帧 placed = 权威布局
  //（frame 经 _emit_placed 单点展开，组合片在求解器放置位展开 —— us004 同口径）。
  const placedFinal = (await evalJs(`(() => { const f = window.__wsMsgs.filter(x=>x.type==='frame'); return f[f.length-1].placed_items; })()`)) || [];
  report.stage = stageMsg; report.final = {
    density_pct: +(finalMsg.density * 100).toFixed(3), width_mm: finalMsg.width_mm,
    placed: placedFinal.length, prefix: finalMsg.prefix,
  };
  const size = stageMsg?.size;
  const msgs = await evalJs(`window.__wsMsgs.map(m=>m.type + (m.type==='stage'?':'+m.stage:''))`);
  const stageIdx = msgs.indexOf('stage:prefix');
  const manifestIdx = msgs.indexOf('manifest');
  check("3b stage('prefix') 在 manifest 之前", stageIdx >= 0 && manifestIdx > stageIdx, JSON.stringify(msgs.slice(0, 4)));
  check('3c stage.size 回显资格码 ∈ {32,33,34,35,38}', ELIGIBLE.includes(size), String(size));
  check('3d stage 新键：extra_label/extra_size 在案 + fallback=false',
    !!stageMsg?.extra_label && !!stageMsg?.extra_size && stageMsg?.fallback === false,
    JSON.stringify({ l: stageMsg?.extra_label, s: stageMsg?.extra_size, fb: stageMsg?.fallback }));
  check('3e stage.residual_mm 近满幅（0 <= r <= 50mm）',
    typeof stageMsg?.residual_mm === 'number' && stageMsg.residual_mm >= 0 && stageMsg.residual_mm <= 50,
    'residual=' + stageMsg?.residual_mm);
  // 预览 <-> 求解同选（同 payload => 同一 select_prefix_plan 真相源）
  check('3f 预览 <-> 求解同选（extra 码一致）',
    !!m && !!sm && m[1] === sm[2] && String(m[2]) === String(sm[3]) && String(m[2]) === String(stageMsg?.extra_size),
    `preview=${extraLabelPreview}@${extraSizeFromHint} stage=${stageMsg?.extra_label}@${stageMsg?.extra_size}`);
  const extraLabel = stageMsg?.extra_label, extraSize = stageMsg?.extra_size;

  // ---- PS_ 零泄漏（manifest + 帧序列 + final）-----------------------------
  const leakProbe = await evalJs(`(() => {
    const man = window.__wsMsgs.filter(x=>x.type==='manifest')[0];
    const pids = ((man && man.pieces) || []).map(p => p.pid || p.id || '').join(',');
    const frameIds = window.__wsMsgs.filter(x=>x.type==='frame').flatMap(f => (f.placed_items||[]).map(p => p.id)).join(',');
    // final 帧协议上不带 placed_items（密度/宽/prefix 统计段；prefix.pid 是回显键
    // 属设计而非泄漏）—— 判据 = final 无 placed_items 键（组合片条目无处可藏）。
    const finalHasPlaced = window.__wsMsgs.filter(x=>x.type==='final').some(f => 'placed_items' in f);
    return { man: pids.includes('PS_'), frames: frameIds.includes('PS_'), final_has_placed: finalHasPlaced };
  })()`);
  report.ps_leak = leakProbe;
  check('4a PS_ 组合片零泄漏（manifest + 帧序列 + final 无 placed 键）',
    !leakProbe.man && !leakProbe.frames && !leakProbe.final_has_placed, JSON.stringify(leakProbe));

  // ---- 守恒：4 基座 + 顶异码按矩阵量 + placed = Sdemand --------------------
  const frontN = placedFinal.filter(p => p.id === 'g02_' + size).length;
  const backN = placedFinal.filter(p => p.id === 'g03_' + size).length;
  const extraN = placedFinal.filter(p => p.id === extraLabel + '_' + extraSize).length;
  report.conservation = { front: frontN, back: backN, extra: extraN, total: placedFinal.length, expect: EXPECT_TOTAL };
  check('4b 4 基座守恒（g02x2 + g03x2 @码' + size + '）+ 顶异码片按矩阵量（2）',
    frontN === 2 && backN === 2 && extraN === 2,
    'front=' + frontN + ' back=' + backN + ' extra=' + extraN);
  check('4c placed 守恒 = Sdemand（' + EXPECT_TOTAL + '，部分扣减不丢片）',
    placedFinal.length === EXPECT_TOTAL, 'placed=' + placedFinal.length);

  // ---- 形态判据（帧序 = 求解器放置序，组合片展开在位）---------------------
  const placed = placedFinal;
  const chunkSeq = placed.slice(0, 5);
  const isFront = (p) => p.id.startsWith('g02_');
  const base4 = chunkSeq.slice(0, 4);
  const interleaveOk = base4.length === 4 && base4.slice(1).every((p, i) => isFront(p) !== isFront(base4[i]));
  const rotOk = base4.slice(1).every((p, i) => {
    const d = Math.abs(((p.rotation - base4[i].rotation) % 360 + 360) % 360);
    return Math.min(d, 360 - d) >= 175;
  });
  check('5a 形态·interleave 交错序（前后前后）', interleaveOk, base4.map(p => p.id).join(' -> '));
  check('5b 形态·头尾 180° 交替', rotOk, base4.map(p => p.id + '@' + Math.round(p.rotation) + '°').join(' -> '));
  check('5c 形态·5 成员（4 同码基座 + 顶异码 ' + extraLabel + '_' + extraSize + '）',
    chunkSeq[4]?.id === extraLabel + '_' + extraSize, chunkSeq.map(p => p.id).join(' -> '));

  // DOM 几何：竖排贴触（含基座<->补片缝）+ 近满幅 + min_x 锚定 + 顶片在簇端
  const geo = await evalJs(`(function () {
    function bboxOf(p) {
      var pts = Array.from(p.points).map(function (pt) { return [pt.x, pt.y]; });
      var xs = pts.map(function (q) { return q[0]; }), ys = pts.map(function (q) { return q[1]; });
      return { x0: Math.min.apply(null, xs), x1: Math.max.apply(null, xs), y0: Math.min.apply(null, ys), y1: Math.max.apply(null, ys), n: pts.length };
    }
    var all = Array.from(document.querySelectorAll('.nest-card svg polygon[data-label]'));
    var base = all.filter(function (p) { return (p.dataset.label === 'g02' || p.dataset.label === 'g03') && p.dataset.size === '${size}'; }).map(bboxOf);
    var extra = all.filter(function (p) { return p.dataset.label === '${extraLabel}' && p.dataset.size === '${extraSize}'; }).map(bboxOf);
    var globalMinX = Math.min.apply(null, all.map(function (p) { return bboxOf(p).x0; }));
    return { base: base, extra: extra, globalMinX: globalMinX };
  })()`);
  check('5d 形态·4 基座 polygon 在场（毛版层、多顶点）',
    geo.base.length === 4 && geo.base.every(b => b.n >= 8), JSON.stringify(geo.base.map(b => b.n)));
  const col = geo.base.concat(geo.extra);
  const minX = Math.min(...col.map(b => b.x0));
  const pin = finalMsg.prefix?.pin || {};
  const anchored = minX <= 6;
  const pinOk = pin.skipped === true || (pin.skipped === false && pin.rolled_back === false);
  check('5e 形态·min_x <= 6mm 锚定（实测 ' + minX.toFixed(2) + 'mm；或置换钉位路径正常）',
    anchored || pinOk, 'min_x=' + minX.toFixed(2) + ' pin=' + JSON.stringify(pin).slice(0, 120));
  const stack = col.slice().sort((a, b) => a.y0 - b.y0);
  const gaps = stack.slice(1).map((b, i) => +(b.y0 - stack[i].y1).toFixed(2));
  check('5f 形态·相邻贴触缝隙 <=1mm（DOM erode 口径，负值 = 咬合）',
    gaps.every(g => g <= 1.0), 'gaps=' + JSON.stringify(gaps));
  // 近满幅：DOM 渲染 erode 后 manifest 几何（d_g=2 双侧内缩 ~2*d_g），列高 ~ gate - residual - 2*d_g
  const spanY = Math.max(...stack.map(b => b.y1)) - Math.min(...stack.map(b => b.y0));
  const gate = 1980;
  const colResidual = +(gate - spanY).toFixed(2);
  check('5g 形态·组合片 H 近满幅（residual 打点：stage=' + stageMsg?.residual_mm + 'mm，DOM 列高残量 ' + colResidual + '，差 <=8mm 覆盖 erode）',
    Math.abs(colResidual - stageMsg?.residual_mm) <= 8, 'colResidual=' + colResidual);
  const baseMinY0 = Math.min(...geo.base.map(b => b.y0));
  const baseMaxY1 = Math.max(...geo.base.map(b => b.y1));
  const touching = (b) => geo.base.some(x => b.y0 <= x.y1 && b.y1 >= x.y0);
  const atEnd = geo.extra.filter(b => (b.y0 <= baseMinY0 || b.y1 >= baseMaxY1) && touching(b));
  check('5h 形态·异码补片在簇端（顶或底）+ 与基座列贴触（组合片可整体 180° 翻转）',
    atEnd.length === 1, 'endCandidates=' + JSON.stringify(atEnd.map(b => [b.y0, b.y1])) +
    ' base[' + baseMinY0.toFixed(1) + ',' + baseMaxY1.toFixed(1) + ']');
  report.form = {
    order: chunkSeq.map(p => p.id), rots: chunkSeq.map(p => Math.round(p.rotation)),
    interleave: interleaveOk, rot_alt: rotOk, dom_gaps_mm: gaps, span_y_mm: +spanY.toFixed(1),
    col_residual_mm: colResidual, stage_residual_mm: stageMsg?.residual_mm,
    min_x_mm: +minX.toFixed(2), anchored, pin, at_end: atEnd.length === 1,
  };
  await sleep(1500);
  await shot('04_final_full');
  const rect = await evalJs(`(() => { const r = document.querySelector('.nest-card svg polygon[data-label]')?.closest('svg')?.getBoundingClientRect(); return r && r.height > 10 ? { x: r.x, y: r.y, w: r.width, h: r.height } : null; })()`);
  if (rect) {
    await shot('05_head_column', { x: rect.x, y: rect.y, width: Math.max(140, rect.w * 0.3), height: rect.h, scale: 1 });
  }
  console.log(`FINAL: density=${(finalMsg.density * 100).toFixed(2)}% width=${Math.round(finalMsg.width_mm)}mm placed=${placedFinal.length}`);
  console.log(`PREFIX: base@${size} + ${extraLabel}@${extraSize} residual=${stageMsg?.residual_mm}mm fallback=${stageMsg?.fallback}`);

  // ---- 导出 PLT（弹窗 -> 14 字段预览 -> 确认 -> 抓 /export 响应字节）------
  await evalJs(`window.__fetchCaps.length = 0`);
  const selR = await evalJs(`window.__setVal('select.export-fmt', 'plt', 'change')`, true);
  if (selR !== 'ok') check('6a 导出格式切 PLT', false, selR);
  await evalJs(`document.querySelector('button.export').click()`);
  await poll(`!!document.querySelector('[data-testid=export-info-overlay]')`, 8000, 'export modal');
  await poll(`document.querySelectorAll('[data-testid^=export-info-auto-]').length >= 8`, 15000, 'table preview rows');
  await shot('06_export_modal');
  await evalJs(`document.querySelector('[data-testid=export-info-confirm]').click()`);
  const cap = await poll(`(() => { const c = (window.__fetchCaps||[]).filter(x=>x.url.includes('/export')); return c.length ? c[c.length-1] : null; })()`, 60000, 'export response');
  const buf = Buffer.from(cap.b64 || '', 'base64');
  const puCount = (buf.toString('latin1').match(/^PU/gm) || []).length;
  report.export = {
    status: cap.status, type: cap.type, cd: cap.cd, bytes: buf.length,
    ps_absent: !buf.includes('PS_'), pu_count: puCount,
    plt_name: (cap.cd || '').includes('.plt'),
  };
  writeFileSync(`${OUT}/export_on.plt`, buf);
  check('6b /export 200 + application/plt', cap.status === 200 && (cap.type || '').includes('plt'),
    `status=${cap.status} type=${cap.type}`);
  check('6c PLT 文件名 .plt（Content-Disposition 附件）', report.export.plt_name, cap.cd);
  check('6d PLT 字节无 PS_（组合片哨兵零泄漏）', report.export.ps_absent, 'bytes=' + buf.length);
  check('6e PLT 正文在案（PU 笔 >=100，实测 ' + puCount + '）', puCount >= 100 && buf.length > 10000,
    'bytes=' + buf.length + ' PU=' + puCount);

  // ---- prefix_runs 工件快照（构造回放在案：成员/extra/residual/gaps）------
  try {
    const arts = readdirSync(PREFIX_RUNS)
      .filter(f => f.includes('_PS_') && f.endsWith('.json'))
      .map(f => ({ f, mt: statSync(resolve(PREFIX_RUNS, f)).mtimeMs }))
      .filter(a => a.mt > solveT0 - 1000)
      .sort((a, b) => a.mt - b.mt);
    if (!arts.length) throw new Error('no new artifact since solve start');
    const artPath = resolve(PREFIX_RUNS, arts[arts.length - 1].f);
    const art = JSON.parse(readFileSync(artPath, 'utf-8'));
    copyFileSync(artPath, `${OUT}/prefix_artifact.json`);
    report.artifact = {
      file: artPath, pid: art.pid, n_members: art.chunk.members.length,
      extra: art.extra, residual_mm: art.residual_mm, fallback: art.fallback,
      gaps: art.gaps,
      pin: art.pin ? { skipped: art.pin.skipped, a: art.pin.a, rolled_back: art.pin.rolled_back } : null,
    };
    check('7a prefix_runs 工件在案（' + art.pid + '：5 成员 + extra 回显 + fallback=false）',
      art.chunk.members.length === 5 && !!art.extra && art.fallback === false,
      'n=' + art.chunk.members.length + ' extra=' + JSON.stringify(art.extra));
    check('7b 工件 gaps 全 <=1mm（版师贴触口径，构造时打点）',
      art.gaps.every(g => g <= 1.0), 'gaps=' + JSON.stringify(art.gaps));
  } catch (e) {
    check('7a prefix_runs 工件在案', false, String(e.message));
  }
} catch (e) {
  console.error('HARNESS-ERR:', e.message); check('HARNESS 无异常', false, e.message);
} finally {
  try { chrome.kill(); } catch {}
  const failed = results.filter((r) => !r.ok);
  report.pass = failed.length === 0;
  report.checks = results;
  writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 2));
  console.log(`\n==== smoke_prefix_extra: ${results.length - failed.length}/${results.length} PASS | report -> ${OUT}/report.json ====`);
  process.exit(failed.length ? 1 : 0);
}

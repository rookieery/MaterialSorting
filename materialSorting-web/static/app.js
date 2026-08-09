'use strict';
// 排料可视化工作台 · 前端（阶段 A/B/C）
// - A：单 seed 求解过程可视化（WS → SVG，节流渲染 + 全量帧存）
// - B：v0.3 参数面板（erode/旋转 内外两档 + 高级每片型）
// - C：多 seed 并排对比回放（按 elapsed 时间对齐）+ 片 hover 信息 + 收敛曲线阶段/seed 着色
//
// 统一用 runs 数组（长度 1 = 单 seed，>1 = 多 seed 对比）。每 run 一个独立 WS 连接（server 不改）。

const SIZES = [28, 29, 30, 31, 33, 34, 35, 36];
const PHASE_COLORS = { exploring: '#1f77b4', compressing: '#ff7f0e', final: '#2ca02c' };
const SEED_COLORS  = ['#1f77b4', '#d62728', '#2ca02c', '#ff7f0e', '#9467bd', '#17becf'];
const SVGNS = 'http://www.w3.org/2000/svg';
const RENDER_INTERVAL_MS = 100;   // 全局 ~10fps 重绘闸（所有 run 共享）

// v0.3 每片型工艺上限（d=重合mm, tol=旋转°）+ 内/外档标记（与 constraints.py 一致）
const V03 = {
  '前片':  { d: 2,   tol: 1,  internal: false },
  '后片':  { d: 2,   tol: 1,  internal: false },
  '腰':    { d: 0.4, tol: 3,  internal: false },
  '前袋':  { d: 0.4, tol: 30, internal: false },
  '后袋':  { d: 0.4, tol: 1,  internal: false },
  '机头':  { d: 0.4, tol: 3,  internal: false },
  '单排':  { d: 10,  tol: 15, internal: true  },
  '双排':  { d: 10,  tol: 15, internal: true  },
  '火机袋': { d: 5,  tol: 8,  internal: true  },
  '裤耳':  { d: 10,  tol: 45, internal: true  },
};
const PTYPES = Object.keys(V03);

const $ = id => document.getElementById(id);
const nestsBox = $('nests'), curve = $('curve');

let runs = [];              // 活跃 run 列表
let gateH = 0;              // 共享门幅（所有 run 同实例）
let solving = false;
let globalLastDraw = 0;     // 全局渲染节流
let tooltipEl, hoveredEl = null;

const svgEl = name => document.createElementNS(SVGNS, name);
const r2 = x => Math.round(x * 100) / 100;

// ---- 码号多选 ----
(function renderSizePicker() {
  const box = $('sizes');
  for (const s of SIZES) {
    const c = document.createElement('input');
    c.type = 'checkbox'; c.id = `sz_${s}`; c.value = s; c.checked = true;
    const lab = document.createElement('label');
    lab.htmlFor = c.id; lab.textContent = s;
    const wrap = document.createElement('span');
    wrap.className = 'chip';
    wrap.appendChild(c); wrap.appendChild(lab);
    box.appendChild(wrap);
  }
})();

// ---- 每片型高级覆盖面板 ----
(function renderPerType() {
  const box = $('per_type');
  for (const pt of PTYPES) {
    const v = V03[pt];
    const row = document.createElement('div');
    row.className = 'pt-row';
    row.innerHTML =
      `<span class="pt-name">${pt}${v.internal ? '<i>内</i>' : ''}</span>`
      + `<input data-pt="${pt}" data-k="d" type="number" min="0" step="0.5" placeholder="d≤${v.d}">`
      + `<input data-pt="${pt}" data-k="tol" type="number" min="0" step="1" placeholder="t≤${v.tol}">`;
    box.appendChild(row);
  }
})();

// tooltip 元素（全局一个，跟随鼠标）
tooltipEl = document.createElement('div');
tooltipEl.className = 'tooltip';
tooltipEl.style.display = 'none';
document.body.appendChild(tooltipEl);

// ---- 预设 ----
$('preset_preview').addEventListener('click', () => { $('time').value = 120; });
$('preset_exact').addEventListener('click', () => { $('time').value = 600; });

function selectedSizes() {
  return [...document.querySelectorAll('#sizes input:checked')].map(c => parseInt(c.value, 10));
}
function num(id, def) { const v = parseFloat($(id).value); return isNaN(v) ? def : v; }
function collectParams() {
  const params = { d_ext: num('d_ext', 0), d_int: num('d_int', 0), tol_ext: num('tol_ext', 0), tol_int: num('tol_int', 0) };
  const per_type = {};
  document.querySelectorAll('#per_type .pt-row input').forEach(inp => {
    if (inp.value.trim() !== '') {
      const pt = inp.dataset.pt, k = inp.dataset.k;
      (per_type[pt] = per_type[pt] || {})[k] = parseFloat(inp.value);
    }
  });
  return { params, per_type: Object.keys(per_type).length ? per_type : null };
}

function setStatus(t) { $('status').textContent = t; }

// ===================== Run 生命周期 =====================
function makeRun(seed) {
  const card = document.createElement('div');
  card.className = 'nest-card';
  const label = document.createElement('div');
  label.className = 'nest-label';
  label.textContent = `seed ${seed} …`;
  const svg = svgEl('svg');
  card.appendChild(label); card.appendChild(svg);
  nestsBox.appendChild(card);
  return {
    seed, card, svg, label,
    pieces: new Map(), frames: [], viewBoxMaxW: 0,
    bgRect: null, fabricRect: null, flipGroup: null,
    ws: null, done: false, finalDensity: 0, lastFrame: null,
  };
}

function startSolve() {
  if (solving) return;
  const sizes = selectedSizes();
  if (sizes.length === 0) { setStatus('请至少选一个码号'); return; }
  const time = parseInt($('time').value, 10) || 120;
  const baseSeed = parseInt($('seed').value, 10) || 0;
  const { params, per_type } = collectParams();

  // 清理旧 run
  for (const r of runs) if (r.ws) { try { r.ws.close(); } catch (e) {} }
  runs = [];
  nestsBox.innerHTML = '';
  curve.innerHTML = '';
  gateH = 0; globalLastDraw = 0;
  hoveredEl = null; tooltipEl.style.display = 'none';
  $('seek').disabled = true; $('seek').max = 0; $('seek').value = 0;
  $('seek-readout').textContent = '—';
  updateExportButtons();   // 清空 runs → 禁用导出，求解中保持禁用

  const multi = $('multi_seed').checked;
  const n = multi ? Math.min(Math.max(parseInt($('seed_count').value, 10) || 3, 2), 6) : 1;

  solving = true;
  $('start').disabled = true;
  setStatus(n > 1 ? `启动 ${n} 个 seed 对比…` : '连接中…');

  for (let i = 0; i < n; i++) {
    const run = makeRun(baseSeed + i);
    runs.push(run);
    connectRun(run, sizes, time, params, per_type);
  }
}

function connectRun(run, sizes, time, params, per_type) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/solve`);
  run.ws = ws;
  ws.onopen = () => { ws.send(JSON.stringify({ action: 'start', sizes, time, seed: run.seed, params, per_type })); };
  ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'manifest') onManifest(run, msg);
    else if (msg.type === 'frame') onFrame(run, msg);
    else if (msg.type === 'final') onFinal(run, msg);
    else if (msg.type === 'error') { run.label.textContent = `seed ${run.seed} 错误：${msg.message}`; run.done = true; checkAllDone(); }
  };
  ws.onclose = () => { run.done = true; checkAllDone(); };
  ws.onerror = () => {};
}

function finishSolve() { solving = false; $('start').disabled = false; }
$('start').addEventListener('click', startSolve);

// ===================== 导出最优方案 =====================
function bestRun() {
  const cand = runs.filter(r => r.lastFrame);   // 有最终帧的 run 才参与
  if (!cand.length) return null;
  return cand.reduce((a, r) => (r.finalDensity > a.finalDensity ? r : a), cand[0]);
}

function updateExportButtons() {
  const ok = runs.length > 0 && runs.some(r => r.lastFrame);
  $('export_png').disabled = !ok;
  $('export_dxf').disabled = !ok;
}

async function exportAs(fmt) {
  const run = bestRun();
  if (!run || !run.lastFrame) { setStatus('无可导出的方案（请先求解）'); return; }
  const f = run.lastFrame;
  const body = {
    fmt, sizes: selectedSizes(), seed: run.seed,
    gate_mm: gateH, width_mm: f.width_mm, density: run.finalDensity,
    placed: f.placed_items,
  };
  setStatus(`正在生成 ${fmt.toUpperCase()} …`);
  $('export_png').disabled = true; $('export_dxf').disabled = true;
  try {
    const res = await fetch('/export', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!res.ok) { setStatus(`导出失败：${(await res.json()).error || res.statusText}`); return; }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : `nesting.${fmt}`;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    setStatus(`已导出 ${name}`);
  } catch (e) {
    setStatus(`导出失败：${e}`);
  } finally {
    updateExportButtons();
  }
}
$('export_png').addEventListener('click', () => exportAs('png'));
$('export_dxf').addEventListener('click', () => exportAs('dxf'));

// ===================== 消息处理 =====================
function onManifest(run, m) {
  gateH = m.gate_mm;
  run.pieces.clear();
  run.svg.innerHTML = '';

  const bg = svgEl('rect'); bg.setAttribute('fill', '#eef0f3');
  const fab = svgEl('rect'); fab.setAttribute('fill', '#fff'); fab.setAttribute('fill-opacity', '0.55');
  fab.setAttribute('stroke', '#8a8a8a'); fab.setAttribute('stroke-dasharray', '8 5'); fab.setAttribute('stroke-width', '1.5');
  const g = svgEl('g'); g.setAttribute('transform', `translate(0 ${m.gate_mm}) scale(1 -1)`);
  run.bgRect = bg; run.fabricRect = fab; run.flipGroup = g;
  run.svg.appendChild(bg); run.svg.appendChild(fab); run.svg.appendChild(g);

  for (const p of m.pieces) {
    const poly = svgEl('polygon');
    poly.setAttribute('fill', p.color); poly.setAttribute('fill-opacity', '0.55');
    poly.setAttribute('stroke', p.color); poly.setAttribute('stroke-width', '1.2');
    poly.style.display = 'none';
    poly.dataset.ptype = p.ptype; poly.dataset.size = p.size; poly.dataset.area = p.area_mm2;
    g.appendChild(poly);
    run.pieces.set(p.id, { polygon: p.polygon, color: p.color, el: poly });
  }
  setupHover(run.svg);
  run.label.textContent = `seed ${run.seed} · ${m.pieces.length} 片`;
}

function onFrame(run, f) {
  run.frames.push(f);
  run.lastFrame = f;
  if (f.width_mm > run.viewBoxMaxW) run.viewBoxMaxW = f.width_mm;

  const now = performance.now();
  if (now - globalLastDraw > RENDER_INTERVAL_MS) {   // 全局节流：重绘所有 run 最新帧
    globalLastDraw = now;
    for (const r of runs) if (r.lastFrame) renderFrame(r, r.lastFrame);
    drawCurve();
  }
  run.label.textContent = `seed ${run.seed} · ${(f.density * 100).toFixed(2)}%`;
}

function onFinal(run, m) {
  run.done = true;
  run.finalDensity = m.density;
  if (run.frames.length) run.lastFrame = run.frames[run.frames.length - 1];
  if (run.lastFrame) renderFrame(run, run.lastFrame);
  checkAllDone();
}

function checkAllDone() {
  if (!solving || runs.length === 0) return;
  if (!runs.every(r => r.done)) return;

  drawCurve();
  const me = Math.ceil(maxElapsed());
  if (me > 0) {
    $('seek').disabled = false;
    $('seek').max = Math.max(me, 1);
    $('seek').value = me;
    renderAtTime(me);
  }
  const summary = runs.map(r => `s${r.seed} ${(r.finalDensity * 100).toFixed(2)}%`).join(' / ');
  const best = runs.reduce((a, r) => (r.finalDensity > a.finalDensity ? r : a), runs[0]);
  setStatus(`完成 ${runs.length} seed：${summary} | best = s${best.seed} ${(best.finalDensity * 100).toFixed(2)}%`);
  finishSolve();
  updateExportButtons();   // 求解完成 → 启用导出
}

// ===================== 渲染 =====================
function renderFrame(run, f) {
  if (!run.flipGroup) return;
  const W = Math.max(run.viewBoxMaxW, f.width_mm, 1);
  run.svg.setAttribute('viewBox', `0 0 ${W} ${gateH}`);
  run.svg.setAttribute('preserveAspectRatio', 'xMinYMid meet');
  run.bgRect.setAttribute('x', 0); run.bgRect.setAttribute('y', 0);
  run.bgRect.setAttribute('width', W); run.bgRect.setAttribute('height', gateH);
  run.fabricRect.setAttribute('x', 0); run.fabricRect.setAttribute('y', 0);
  run.fabricRect.setAttribute('width', f.width_mm); run.fabricRect.setAttribute('height', gateH);

  const placed = new Set();
  for (const it of f.placed_items) {
    const p = run.pieces.get(it.id);
    if (!p) continue;
    placed.add(it.id);
    p.el.setAttribute('points', pointsStr(p.polygon, it.rotation, it.translation));
    p.el.style.display = '';
  }
  for (const [id, p] of run.pieces) if (!placed.has(id)) p.el.style.display = 'none';
}

function pointsStr(poly, rot, tr) {
  const r = rot * Math.PI / 180, c = Math.cos(r), s = Math.sin(r), tx = tr[0], ty = tr[1];
  let out = '';
  for (let i = 0; i < poly.length; i++) {
    const x = poly[i][0], y = poly[i][1];
    out += (i ? ' ' : '') + r2(x * c - y * s + tx) + ',' + r2(x * s + y * c + ty);
  }
  return out;
}

// ===================== 收敛曲线（多 run 叠加）=====================
function drawCurve() {
  if (runs.length === 0 || runs.every(r => r.frames.length === 0)) return;
  const multi = runs.length > 1;
  const W = 1000, H = 220, padL = 46, padR = 14, padT = 12, padB = 26;
  let maxT = 1, yMin = Infinity, yMax = -Infinity;
  for (const r of runs) for (const f of r.frames) {
    if (f.elapsed > maxT) maxT = f.elapsed;
    const d = f.density * 100;
    if (d < yMin) yMin = d; if (d > yMax) yMax = d;
  }
  yMin = Math.max(0, yMin - 3); yMax = Math.max(93, yMax + 2);
  const sx = t => padL + (t / maxT) * (W - padL - padR);
  const sy = d => H - padB - ((d - yMin) / (yMax - yMin)) * (H - padT - padB);

  curve.setAttribute('viewBox', `0 0 ${W} ${H}`);
  curve.setAttribute('preserveAspectRatio', 'xMinYMid meet');

  let svg = '';
  svg += `<line x1="${padL}" y1="${sy(90)}" x2="${W - padR}" y2="${sy(90)}" stroke="#444" stroke-dasharray="5 4"/>`;
  svg += `<text x="${padL + 4}" y="${sy(90) - 4}" font-size="11" fill="#444">90% 生死线</text>`;

  runs.forEach((r, ri) => {
    if (r.frames.length === 0) return;
    const col = multi ? SEED_COLORS[ri % SEED_COLORS.length] : '#1f77b4';
    const step = Math.max(1, Math.floor(r.frames.length / 400));
    const pts = [];
    for (let i = 0; i < r.frames.length; i += step) pts.push(r.frames[i]);
    const last = r.frames[r.frames.length - 1];
    if (pts[pts.length - 1] !== last) pts.push(last);

    if (!multi) {   // 单 seed：阶段着色散点
      for (const f of pts)
        svg += `<circle cx="${sx(f.elapsed)}" cy="${sy(f.density * 100)}" r="2" fill="${PHASE_COLORS[f.phase] || '#888'}" opacity="0.55"/>`;
    }
    let best = -1, path = '';
    for (const f of pts) { best = Math.max(best, f.density * 100); path += (path ? 'L' : 'M') + r2(sx(f.elapsed)) + ' ' + r2(sy(best)); }
    svg += `<path d="${path}" fill="none" stroke="${col}" stroke-width="2"/>`;
    svg += `<circle cx="${sx(last.elapsed)}" cy="${sy(last.density * 100)}" r="3" fill="${col}"/>`;
    if (multi) svg += `<text x="${sx(last.elapsed) - 5}" y="${sy(last.density * 100) - 6}" font-size="10" fill="${col}" text-anchor="end">s${r.seed}</text>`;
  });

  // 图例
  svg += '<g class="legend">';
  if (multi) {
    runs.forEach((r, ri) => {
      const col = SEED_COLORS[ri % SEED_COLORS.length], y = padT + ri * 15 + 4;
      svg += `<rect x="${padL + 8}" y="${y - 3}" width="12" height="3" fill="${col}"/>`;
      svg += `<text x="${padL + 24}" y="${y}" font-size="10" fill="#ccd">seed ${r.seed}</text>`;
    });
  } else {
    let y = padT + 8;
    for (const [ph, col] of Object.entries(PHASE_COLORS)) {
      svg += `<circle cx="${padL + 14}" cy="${y}" r="3" fill="${col}" opacity="0.75"/>`;
      svg += `<text x="${padL + 22}" y="${y + 3}" font-size="10" fill="#ccd">${ph}</text>`;
      y += 15;
    }
  }
  svg += '</g>';

  svg += `<text x="${padL}" y="${H - 8}" font-size="10" fill="#888">0s</text>`;
  svg += `<text x="${W - padR - 34}" y="${H - 8}" font-size="10" fill="#888">${maxT.toFixed(0)}s</text>`;
  curve.innerHTML = svg;
}

// ===================== 回放（按 elapsed 时间对齐各 seed）=====================
function maxElapsed() {
  let m = 0;
  for (const r of runs) if (r.frames.length) m = Math.max(m, r.frames[r.frames.length - 1].elapsed);
  return m;
}
function frameAtTime(run, t) {
  const fr = run.frames;
  if (fr.length === 0) return null;
  let lo = 0, hi = fr.length - 1, ans = 0;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (fr[mid].elapsed <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
  return fr[ans];
}
function renderAtTime(t) {
  const parts = [`t=${t.toFixed(1)}s`];
  for (const r of runs) {
    const f = frameAtTime(r, t);
    if (f) { renderFrame(r, f); parts.push(`s${r.seed} ${(f.density * 100).toFixed(2)}%`); }
  }
  $('seek-readout').textContent = parts.join(' | ');
}
$('seek').addEventListener('input', () => {
  if (runs.length === 0) return;
  renderAtTime(parseInt($('seek').value, 10));
});

// ===================== hover 片信息（事件委托）=====================
function setupHover(svg) {
  svg.addEventListener('mousemove', e => {
    const poly = e.target.closest('polygon');
    if (poly && poly.dataset.ptype) {
      if (hoveredEl !== poly) {
        if (hoveredEl) hoveredEl.classList.remove('hover');
        poly.classList.add('hover');
        hoveredEl = poly;
      }
      tooltipEl.style.display = 'block';
      tooltipEl.style.left = (e.clientX + 14) + 'px';
      tooltipEl.style.top = (e.clientY + 14) + 'px';
      tooltipEl.innerHTML = `${poly.dataset.ptype} · 码${poly.dataset.size}<br>面积 ${(parseFloat(poly.dataset.area) / 100).toFixed(1)} cm²`;
    } else {
      if (hoveredEl) { hoveredEl.classList.remove('hover'); hoveredEl = null; }
      tooltipEl.style.display = 'none';
    }
  });
  svg.addEventListener('mouseleave', () => {
    if (hoveredEl) { hoveredEl.classList.remove('hover'); hoveredEl = null; }
    tooltipEl.style.display = 'none';
  });
}

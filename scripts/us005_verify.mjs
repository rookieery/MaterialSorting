// US-005 浏览器验证 harness（CDP headless Chrome，无外部依赖；范本 us003_verify.mjs）。
// 流程：上传母版+commit → 超排 Tab → 高级运行入口 → 配置态断言 →
//      race 10min 真跑（执行 → 进度五件套 → 关弹窗徽标 → 重开恢复 → 门杀事件 →
//      终局 done 结果态断言）→ 再次运行回配置态。全程截图存 out/us005_verify/。
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';

const APP = 'http://127.0.0.1:8000/';
const DXF = 'D:/code/MaterialSorting/data/M1787#直筒14%7%大货围加9）双针30码脚口8英寸(1)(2).dxf';
const OUT = 'D:/code/MaterialSorting/out/us005_verify';
mkdirSync(OUT, { recursive: true });
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + String(detail).slice(0, 160) : ''}`);
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
  '--headless=new', '--remote-debugging-port=9223', '--disable-gpu', '--no-first-run',
  '--window-size=1680,1000', `--user-data-dir=${OUT}/chrome-profile`, 'about:blank',
], { stdio: 'ignore' });
try {
  // 端口 9223：避开本机可能残留的 9222。
  async function getTargetWs9223() {
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
  const wsUrl = await getTargetWs9223();
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
  check('App 载入（TabBar）', await evalJs(`!!document.querySelector('.tabbar')`));

  // ---- 上传母版（真实 UI 路径）→ 矩阵 + 自动 commit ----
  const doc = await send('DOM.getDocument');
  const inputNode = await send('DOM.querySelector', { nodeId: doc.root.nodeId, selector: 'input[type=file]' });
  if (!inputNode.nodeId) throw new Error('file input not found');
  await send('DOM.setFileInputFiles', { files: [DXF], nodeId: inputNode.nodeId });
  console.log('UPLOAD dispatched, waiting parse+matrix+commit...');
  await poll(`!!document.querySelector('.qty-matrix')`, 90000, 'qty-matrix');
  await poll(`(() => { const b = document.querySelector('[data-tour=tab-nesting]'); return b && !b.disabled; })()`, 90000, 'commit done (nesting tab unlocked)');
  await sleep(500);

  // ---- 超排 Tab：勾选码号 28/30（执行按钮解禁的前提）----
  await evalJs(`document.querySelector('[data-tour=tab-nesting]').click()`);
  await sleep(600);
  await evalJs(`document.querySelector('#sz_28')?.click()`);
  await sleep(150);
  await evalJs(`document.querySelector('#sz_30')?.click()`);
  await sleep(300);

  // ---- 高级运行入口 + 配置态断言 ----
  check('入口按钮在场且可点（已 commit）', await evalJs(`(() => { const b = document.querySelector('[data-testid=strategy-btn]'); return !!b && !b.disabled; })()`));
  await evalJs(`document.querySelector('[data-testid=strategy-btn]').click()`);
  await poll(`!!document.querySelector('.strategy-modal')`, 10000, 'strategy modal');
  // 上一次 run 的 result 常驻（server 内存终态 + 页面刷新 refresh 恢复结果态 —— 设计行为）：
  // 若开弹窗即结果态，先「再次运行」回配置态再断言。
  const prevResultHead = await evalJs(`document.querySelector('[data-testid=strategy-result-head]')?.textContent || ''`);
  if (prevResultHead) {
    check('结果态常驻：页面刷新后重开弹窗恢复上次结果（' + prevResultHead + '）', prevResultHead.includes('最优'));
    await evalJs(`document.querySelector('[data-testid=strategy-again-btn]').click()`);
    await poll(`!!document.querySelector('[data-testid=strategy-minutes]')`, 10000, 'config state after 再次运行');
  }
  const cfg = await evalJs(`(() => {
    const mins = document.querySelector('[data-testid=strategy-minutes]');
    const mode = document.querySelector('[data-testid=strategy-mode]');
    return {
      nMinOpts: mins ? mins.options.length : 0,
      minLabels: mins ? Array.from(mins.options).map(o=>o.textContent) : [],
      nModeOpts: mode ? mode.options.length : 0,
      desc: document.querySelector('[data-testid=strategy-mode-desc]')?.textContent || '',
      minHint: document.querySelector('[data-testid=strategy-min-hint]')?.textContent || '',
      panelHint: Array.from(document.querySelectorAll('.strategy-hint')).some(h=>h.textContent.includes('排料参数取当前面板')),
      execDisabled: document.querySelector('[data-testid=strategy-exec-btn]')?.disabled,
      nInputs: document.querySelectorAll('.strategy-modal input').length,
      role: document.querySelector('.strategy-modal')?.getAttribute('role'),
    };
  })()`);
  check('配置态：时长四档（10/20/30/1小时）', cfg.nMinOpts === 4 && cfg.minLabels.join('|').includes('10 分钟') && cfg.minLabels.join('|').includes('1 小时'), JSON.stringify(cfg.minLabels));
  check('配置态：模式两项（race/se）', cfg.nModeOpts === 2);
  check('配置态：race 说明行（90s 门）', cfg.desc.includes('90s 门处严格破纪录才续跑'));
  check('配置态：10min 提示 + 排料参数提示', cfg.minHint.includes('10 分钟档两模式与均分打平，20 分钟起有增益') && cfg.panelHint);
  check('配置态：不暴露 4 个策略参数（无输入框）', cfg.nInputs === 0);
  check('配置态：role=dialog + 执行可点（码号已勾选）', cfg.role === 'dialog' && cfg.execDisabled === false);
  // 模式切换说明行
  await evalJs(`(() => { const s = document.querySelector('[data-testid=strategy-mode]'); const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set; set.call(s,'se'); s.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await sleep(200);
  check('模式切换：SE 说明行', (await evalJs(`document.querySelector('[data-testid=strategy-mode-desc]').textContent`)).includes('多轮短筛选后冠军 seed 加时长再战'));
  await shot('01_config_state');

  // ---- race 10min 真跑：执行 → 进度态 ----
  await evalJs(`(() => { const s = document.querySelector('[data-testid=strategy-mode]'); const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set; set.call(s,'race'); s.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await evalJs(`(() => { const s = document.querySelector('[data-testid=strategy-minutes]'); const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set; set.call(s,'10'); s.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await sleep(200);
  await evalJs(`document.querySelector('[data-testid=strategy-exec-btn]').click()`);
  console.log('EXEC clicked (race 10min), waiting progress state...');
  await poll(
    `!!document.querySelector('[data-testid=strategy-progress-title]') || !!document.querySelector('[data-testid=strategy-error]') || !!document.querySelector('[data-testid=strategy-orphan-head]')`,
    20000, 'progress/error state',
  );
  const errTxt = await evalJs(`document.querySelector('[data-testid=strategy-error]')?.textContent || ''`);
  if (errTxt) throw new Error('start 被拒（error 态）：' + errTxt);
  if (await evalJs(`!!document.querySelector('[data-testid=strategy-orphan-head]')`)) {
    throw new Error('orphan 态：' + await evalJs(`document.querySelector('[data-testid=strategy-orphan-head]').textContent`));
  }
  await poll(`!!document.querySelector('[data-testid=strategy-progress-title]')`, 10000, 'progress state');
  const progEarly = await evalJs(`(() => ({
    title: document.querySelector('[data-testid=strategy-progress-title]').textContent,
    big: document.querySelector('[data-testid=strategy-big-density]').textContent,
    hasBar: !!document.querySelector('[data-testid=strategy-budget-bar]'),
    stage: document.querySelector('[data-testid=strategy-stage]')?.textContent || '',
    chips: document.querySelectorAll('[data-testid=strategy-seed-chips] .strategy-chip').length,
    event: document.querySelector('[data-testid=strategy-event]')?.textContent || '',
    closeHint: document.querySelector('[data-testid=strategy-close-hint]')?.textContent || '',
    stopBtn: !!document.querySelector('[data-testid=strategy-stop-btn]'),
  }))()`);
  check('进度态：标题行（模式·总预算·已跑）', /race 门杀/.test(progEarly.title) && progEarly.title.includes('总预算 10 分') && progEarly.title.includes('已跑'), progEarly.title);
  check('进度态：大数字 + 预算条 + 终止按钮在场', !!progEarly.hasBar && progEarly.stopBtn);
  check('进度态：关闭不终止文案', progEarly.closeHint.includes('关闭弹窗不会终止运行'));

  // ---- 关弹窗（ESC）→ 入口徽标「运行中」；重开恢复进度（15s 低频轮询）----
  await evalJs(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  await sleep(400);
  check('ESC 关闭弹窗（run 未终止 —— 无 stop 请求）', await evalJs(`!document.querySelector('.strategy-overlay')`));
  await poll(`!!document.querySelector('[data-testid=strategy-badge]')`, 20000, 'badge 运行中');
  check('入口徽标「运行中」（关弹窗维持观测）', (await evalJs(`document.querySelector('[data-testid=strategy-badge]').textContent`)) === '运行中');
  await shot('02_badge_running');
  await evalJs(`document.querySelector('[data-testid=strategy-btn]').click()`);
  await poll(`!!document.querySelector('[data-testid=strategy-progress-title]')`, 10000, 'reopen progress');
  check('重开弹窗恢复进度（status 无状态）', await evalJs(`!!document.querySelector('[data-testid=strategy-progress-title]')`));

  // ---- 首帧数据：大数字 > 0 + chips（首 seed exempt running）----
  await poll(`(() => { const t = document.querySelector('[data-testid=strategy-big-density]').textContent; return t && t !== '—' && t !== '0.00%'; })()`, 180000, 'first best density');
  const progLive = await evalJs(`(() => ({
    big: document.querySelector('[data-testid=strategy-big-density]').textContent,
    fill: document.querySelector('.strategy-budget-fill').style.width,
    label: document.querySelector('[data-testid=strategy-budget-label]').textContent,
    stage: document.querySelector('[data-testid=strategy-stage]').textContent,
    chips: Array.from(document.querySelectorAll('[data-testid=strategy-seed-chips] .strategy-chip')).map(c=>c.textContent),
    event: document.querySelector('[data-testid=strategy-event]')?.textContent || '',
  }))()`);
  check('进度态：大数字实时密度（>0）', parseFloat(progLive.big) > 0, progLive.big);
  check('进度态：预算条 ≈ 墙钟口径', progLive.label.includes('≈') && progLive.label.includes('/ 600s'), progLive.label);
  check('进度态：阶段行（第 1/5 轮 · seed 0）', progLive.stage.includes('第 1/5 轮') && progLive.stage.includes('seed 0'), progLive.stage);
  check('进度态：seed chips 在场（5 计划 + 首 seed running）', progLive.chips.length === 5 && progLive.chips.some(c=>c.includes('●')), progLive.chips.join(' '));
  await shot('03_progress_live');

  // ---- race 门杀事件（引擎/数据相关：本 run 可能全程无门杀 —— done 先到则跳过该项，
  //      ✕门杀 chip 渲染已由 StrategyRunModal.test.tsx fixture 覆盖）----
  await poll(
    `!!document.querySelector('.strategy-chip.killed') || (document.querySelector('[data-testid=strategy-event]')?.textContent || '').includes('门杀') || !!document.querySelector('[data-testid=strategy-result-head]')`,
    520000, 'gate kill or done (whichever first)',
  );
  const hasKill = await evalJs(`!!document.querySelector('.strategy-chip.killed') || (document.querySelector('[data-testid=strategy-event]')?.textContent || '').includes('门杀')`);
  if (hasKill) {
    const gate = await evalJs(`(() => ({
      chips: Array.from(document.querySelectorAll('[data-testid=strategy-seed-chips] .strategy-chip')).map(c=>c.textContent+'|'+c.className.split(' ')[1]),
      event: document.querySelector('[data-testid=strategy-event]')?.textContent || '',
    }))()`);
    check('race 门杀：killed chip ✕门杀 + 事件行', gate.chips.some(c=>c.includes('killed')) && gate.event.includes('门杀'), gate.chips.join(' / ') + ' || ' + gate.event);
    await shot('04_gate_kill');
  } else {
    check('race 门杀：本 run 无门杀（kept 全留；引擎数据相关 —— ✕门杀 chip 渲染由单测 fixture 覆盖）', true, 'SKIP');
  }

  // ---- 终局 done → 结果态（总预算 600s 用尽；2s 轮询收口）----
  await poll(`!!document.querySelector('[data-testid=strategy-result-head]')`, 400000, 'done → result state');
  const res = await evalJs(`(() => ({
    head: document.querySelector('[data-testid=strategy-result-head]')?.textContent || '',
    detail: document.querySelector('[data-testid=strategy-result-detail]')?.textContent || '',
    summary: document.querySelector('[data-testid=strategy-mode-summary]')?.textContent || '',
    runDir: document.querySelector('[data-testid=strategy-run-dir]')?.textContent || '',
    applyDisabled: document.querySelector('[data-testid=strategy-apply-btn]')?.disabled,
    copyBtn: !!document.querySelector('[data-testid=strategy-copy-btn]'),
    badgeGone: !document.querySelector('[data-testid=strategy-badge]'),
  }))()`);
  check('结果态：完成 · 最优 X.XX%', res.head.includes('完成 · 最优'), res.head);
  check('结果态：最优 seed + 用布明细', res.detail.includes('seed') && res.detail.includes('用布'), res.detail);
  check('结果态：race 模式汇总（N 轮中 K 轮门杀）', res.summary.includes('race') && res.summary.includes('轮门杀'), res.summary);
  check('结果态：run_dir 展示（web_race 目录）+ 复制按钮', res.runDir.includes('web_race') && res.copyBtn, res.runDir);
  check('结果态：应用按钮 disabled（US-006 接线前）', res.applyDisabled === true);
  check('结果态：入口徽标消失（terminal 态）', res.badgeGone === true);
  await shot('05_result_state');

  // ---- 再次运行 → 回配置态 ----
  await evalJs(`document.querySelector('[data-testid=strategy-again-btn]').click()`);
  await poll(`!!document.querySelector('[data-testid=strategy-minutes]')`, 10000, 'config state again');
  check('再次运行 → 回配置态（时长/模式下拉回归）', await evalJs(`!!document.querySelector('[data-testid=strategy-minutes]') && !!document.querySelector('[data-testid=strategy-exec-btn]')`));
  await shot('06_config_again');
} catch (e) {
  console.error('HARNESS ERROR:', e && e.message ? e.message : e);
  try { await shot('99_error'); } catch {}
  process.exitCode = 1;
} finally {
  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== US-005 VERIFY: ${results.length - failed.length}/${results.length} PASS =====`);
  if (failed.length) for (const f of failed) console.log('FAILED: ' + f.name + '  -- ' + String(f.detail).slice(0, 200));
  try { await shot('99_final'); } catch {}
  try { chrome.kill(); } catch {}
}

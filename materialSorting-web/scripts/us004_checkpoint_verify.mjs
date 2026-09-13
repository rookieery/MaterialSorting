// 会话过期自动恢复 US-004 浏览器验证（playwright，手动脚本不入 vitest；2026-09-13）。
//
// 前置：ms-web 在 :8000（prod static，默认 TTL —— 本 AC 不涉及过期）。
//
// 相位（US-004 AC：上传母版 → 改数量 → 断言 POST /api/state-checkpoint 200
// stored:true → F5 刷新 → 干净重置 + DELETE 已发 → 数量矩阵为默认值）：
//   A1 上传 5336 母版 → commit done → sid 铸造。
//   A2 改数量（g01@30 → 2）→ 等 3s 去抖 → __netLog 断言恰一发 POST
//      /api/state-checkpoint 200 stored:true，body=数量实值且无 run 块。
//   A3 切超排 → 3 码 5s 求解 done → 求解完成立即（不等去抖）checkpoint 再落：
//      body 含 run 块（done 检出后即时读日志 —— 3s 去抖窗口内已在场）。
//   A4 F5 reload（会话存活）→ 启动清理：__netLog 断言 DELETE /api/state-checkpoint
//      200 且无 /api/state-recover；sid 不变；前端干净重置（上传空态）。
//   A5 重传同母版 → commit → 数量矩阵为默认值（g01@30=1 / 总 110 = 非恢复态）。
//
// 报告落 out/us004_checkpoint/report.txt；退出码 0 = 全 PASS。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/us004_checkpoint';
mkdirSync(OUT, { recursive: true });

const { chromium } = await import('playwright');

const BASE = 'http://127.0.0.1:8000';
const DXF = ROOT + '/data/5336#老六订单14%7%围加9_coded.dxf';
const SIZES = [32, 33, 34];
const SOLVE_TIME = '5';
const GATE = '180.00';
const DEBOUNCE_WAIT_MS = 4500; // > CHECKPOINT_DEBOUNCE_MS 3s + 余量

const results = [];
function check(name, ok, extra) {
  results.push({ name, ok });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 160) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (s) => console.log('---', s);

/** 全导航 fetch 侦听（addInitScript）：/api/* 调查日志；checkpoint 响应体克隆捕获。 */
const NET_SPY = () => {
  window.__t0 = Date.now();
  window.__netLog = [];
  const orig = window.fetch;
  window.fetch = async function (...args) {
    const url = String(args[0]);
    if (url.includes('/api/')) {
      const init = args[1] || {};
      const h = init.headers || {};
      const entry = {
        t: Math.round((Date.now() - window.__t0) / 1000),
        url,
        method: init.method || 'GET',
        sid: h['X-Session-Id'] || h['x-session-id'] || null,
        body: typeof init.body === 'string' ? init.body : null,
      };
      window.__netLog.push(entry);
      const res = await orig.apply(this, args);
      entry.status = res.status;
      if (url.includes('/api/state-checkpoint')) {
        try {
          entry.resp = await res.clone().json();
        } catch {
          entry.resp = null;
        }
      }
      return res;
    }
    return orig.apply(this, args);
  };
};

let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}

try {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await ctx.addInitScript(() => {
    localStorage.setItem('ms.tour.version', '8');
    localStorage.setItem('ms.tour.seen.preview', '1');
    localStorage.setItem('ms.tour.seen.nesting', '1');
  });
  await ctx.addInitScript(NET_SPY);
  const page = await ctx.newPage();

  // ---------- A1 上传 ----------
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const sidA = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('A1a 页面加载铸造 sid A', /^[0-9a-f]{32}$/.test(sidA || ''), (sidA || '').slice(0, 8));

  await page.locator('input[type=file]').first().setInputFiles(DXF);
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 240000 });
  log('A1 上传 + commit done');
  await page.locator('.qty-cell-input[data-cell="0-0"]').waitFor({ timeout: 15000 });

  // ---------- A2 改数量 → 去抖 checkpoint ----------
  await page.locator('.qty-cell-input[data-cell="0-0"]').fill('2');
  await page.locator('.qty-cell-input[data-cell="0-0"]').press('Enter');
  const qtyTotalEdited = await page.locator('[data-testid="qty-total"]').innerText();
  check('A2a 数量矩阵 g01@30=2 → 总片数 111', qtyTotalEdited.trim() === '111', qtyTotalEdited.trim());

  await sleep(DEBOUNCE_WAIT_MS);
  let net = await page.evaluate(() => window.__netLog || []);
  const cps = net.filter((x) => x.url.includes('/api/state-checkpoint') && x.method === 'POST');
  // 注：上传 hydrate（doc 物化默认矩阵）也会排一发去抖 —— 若此刻服务端 commit 未
  // 完成则后端 200 {stored:false,reason:'empty'}（PRD 既定容忍路径，前端零处理）。
  // 本断言锚定「改数量那一发」：body 含 g01@30=2 且恰一发（去抖合并不重复发）。
  const qtyPosts = cps.filter((x) => {
    const b = JSON.parse(x.body || '{}');
    return b.quantities && b.quantities.g01 && b.quantities.g01['30'] === 2;
  });
  check('A2b 去抖 3s 后改数量一发 POST /api/state-checkpoint 200 stored:true',
    qtyPosts.length === 1 && qtyPosts[0].status === 200
      && qtyPosts[0].resp && qtyPosts[0].resp.stored === true,
    JSON.stringify(cps.map((c) => [c.status, c.resp])));
  const body2 = qtyPosts.length ? JSON.parse(qtyPosts[0].body || '{}') : {};
  check('A2c 载荷=工作台实值（quantities.g01.30=2、无 run 块、无 save_as）',
    body2.quantities && body2.quantities.g01 && body2.quantities.g01['30'] === 2
      && body2.run === undefined && body2.save_as === undefined,
    'g01@30=' + body2.quantities?.g01?.['30'] + ' run=' + ('run' in body2));
  check('A2d checkpoint 带 sid A（peek 口径不建新会话）',
    qtyPosts.length === 1 && qtyPosts[0].sid === sidA,
    qtyPosts[0] ? qtyPosts[0].sid?.slice(0, 8) : 'none');
  await page.screenshot({ path: OUT + '/a2_debounced_checkpoint.png' });

  // ---------- A3 求解完成立即 checkpoint ----------
  await page.locator('button.tab:not([disabled]):has-text("超排")').click();
  await sleep(800);
  for (const sz of SIZES) await page.check('#sz_' + sz);
  await page.fill('#gate', GATE);
  await page.fill('#time', SOLVE_TIME);
  await page.click('#start');
  const t0 = Date.now();
  for (;;) {
    const done = await page.evaluate(
      () => (document.querySelector('[data-testid="save-state-btn"]') || {}).disabled !== false,
    );
    if (!done || Date.now() - t0 > 120000) break;
    await sleep(500);
  }
  check('A3a 求解完成（保存状态按钮解锁）', Date.now() - t0 <= 120000);
  // done 检出后即时读日志（不等 3s 去抖）—— 求解完成 checkpoint 应已在场。
  // 注：A3 开场勾码/填幅宽/填时长等 formStore 变更会再排一发去抖（body 无 run）；
  // 求解完成那一发 = **最后一条**（含 run 块，markRunDone 立即触发）。
  net = await page.evaluate(() => window.__netLog || []);
  const cps3 = net.filter((x) => x.url.includes('/api/state-checkpoint') && x.method === 'POST');
  const lastCp = cps3[cps3.length - 1];
  check('A3b 求解完成立即 checkpoint（不等去抖）且含 run 块',
    !!lastCp && lastCp.status === 200 && lastCp.resp && lastCp.resp.stored === true
      && JSON.parse(lastCp.body || '{}').run !== undefined,
    'posts=' + cps3.length + ' lastResp=' + JSON.stringify(lastCp?.resp));
  const runBody = lastCp ? JSON.parse(lastCp.body || '{}') : {};
  check('A3c run 块带终局摘要与 placed（g01 布局可恢复）',
    runBody.run && runBody.run.final && runBody.run.final.density > 0
      && Array.isArray(runBody.run.placed) && runBody.run.placed.length > 0,
    'density=' + runBody.run?.final?.density + ' placed=' + runBody.run?.placed?.length);
  await page.screenshot({ path: OUT + '/a3_solve_done_checkpoint.png' });

  // ---------- A4 F5 干净重置（会话存活 → DELETE） ----------
  await page.reload({ waitUntil: 'networkidle' });
  const sidB = await page.evaluate(() => localStorage.getItem('ms_sid'));
  check('A4a F5 后 sid 不变（会话存活）', sidB === sidA, sidB ? sidB.slice(0, 8) : 'none');

  net = await page.evaluate(() => window.__netLog || []); // 导航后新日志
  const dels = net.filter((x) => x.url.includes('/api/state-checkpoint') && x.method === 'DELETE');
  const recovers = net.filter((x) => x.url.includes('/api/state-recover'));
  const probes = net.filter((x) => x.url.includes('/api/session'));
  check('A4b 启动清理：DELETE /api/state-checkpoint 200（恰一次）',
    dels.length === 1 && dels[0].status === 200 && dels[0].sid === sidA,
    'dels=' + dels.length + ' status=' + dels.map((d) => d.status).join(','));
  check('A4c 探测 200 放行 + 无恢复调用（存活刷新 ≠ 过期恢复）',
    probes.length >= 1 && probes[0].status === 200 && recovers.length === 0,
    'probes=' + probes.length + ' recovers=' + recovers.length);
  const cleanState = await page.evaluate(() => ({
    hasMatrix: document.querySelector('.qty-cell-input') !== null,
    hasUpload: document.querySelector('input[type=file]') !== null,
  }));
  check('A4d 前端干净重置（无母版残留 = 上传空态）',
    !cleanState.hasMatrix && cleanState.hasUpload, JSON.stringify(cleanState));
  await page.screenshot({ path: OUT + '/a4_f5_clean_reset.png' });

  // ---------- A5 重传同母版 → 数量矩阵默认值（非恢复态） ----------
  await page.locator('input[type=file]').first().setInputFiles(DXF);
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 240000 });
  const cell00 = page.locator('.qty-cell-input[data-cell="0-0"]');
  await cell00.waitFor({ timeout: 15000 });
  const cellVal = await cell00.inputValue();
  const qtyTotalDefault = await page.locator('[data-testid="qty-total"]').innerText();
  check('A5a 重传后数量矩阵默认值（g01@30=1、总 110 = 非恢复态）',
    cellVal === '1' && qtyTotalDefault.trim() === '110', cellVal + ' / ' + qtyTotalDefault.trim());
  const toasts = await page.evaluate(() => document.body.innerText);
  check('A5b 无恢复 toast（幽灵回潮防线）', !toasts.includes('工作状态已恢复'), '');
  await sleep(DEBOUNCE_WAIT_MS); // 确认重传后未过期前无恢复调用掺入
  net = await page.evaluate(() => window.__netLog || []);
  check('A5c 全程零 /api/state-recover（会话存活）',
    net.filter((x) => x.url.includes('/api/state-recover')).length === 0, '');
  await page.screenshot({ path: OUT + '/a5_default_matrix.png' });
} catch (e) {
  check('脚本异常中断', false, String(e).slice(0, 200));
} finally {
  await browser.close();
}

const pass = results.filter((r) => r.ok).length;
writeFileSync(OUT + '/report.txt',
  results.map((r) => (r.ok ? 'PASS' : 'FAIL') + '  ' + r.name).join('\n')
  + '\n' + pass + '/' + results.length + '\n');
console.log('\n' + pass + '/' + results.length + ' passed');
process.exit(pass === results.length ? 0 : 1);

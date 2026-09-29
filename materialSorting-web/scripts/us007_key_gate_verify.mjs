// key 授权 US-007「三入口前端拦截」浏览器验证（playwright，手动脚本不入 vitest；
// 模板 = us006_key_modal_verify.mjs）。
//
// 前置（外部起，本脚本只做 UI 断言；见 verify 调用侧）：
//   - keyserver 在 $KEYSERVER_URL（DEV=1 无 token）；MODE=down 时已停（断网相位）
//   - ms-web 在 $MS_WEB_URL（MS_KEY_SERVER_URL 指向 keyserver；MS_OUT_DIR 临时目录）
//   - env：US007_COUNT_KEY（明文，调用侧 admin API 创建）
//
// 相位（US-007 AC）：
//   MODE=full（keyserver 在线）
//   B  未绑 key + 真实母版（样例字节改名上传 → basename 不在白名单 → 无样例豁免）
//      三入口全拦：普通 StatusLine+Toast / 高级·极限弹窗 errorMessage，且
//      /api/strategy|extreme/start 请求零发出（页面 fetch 日志断言）
//   D  绑定 count key（KeyInfoModal 保存）
//   E  放行：普通 → phase running（#stop 在场）；高级/极限 → 202 后停止
//   MODE=down（keyserver 已停，key 已绑）
//   F  断网文案「无法连接授权服务器，请检查网络后重试」三入口一致（后端映射）
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/us007_key_gate';
mkdirSync(OUT, { recursive: true });

const MS_WEB_URL = process.env.MS_WEB_URL ?? 'http://127.0.0.1:8012';
const KEYSERVER_URL = process.env.KEYSERVER_URL ?? 'http://127.0.0.1:8117';
const COUNT_KEY = process.env.US007_COUNT_KEY ?? '';
const MODE = process.env.MODE ?? 'full'; // full | down

const MSG_NO_KEY = '未绑定授权 key：请在「系统key」中输入并保存';
const MSG_DOWN = '无法连接授权服务器，请检查网络后重试';

const results = [];
function check(name, ok, extra) {
  results.push({ name, ok });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 160) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const { chromium } = await import('playwright');
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '8');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
  // fetch 日志（拦截断言：/api/strategy|extreme/start 零发出）
  const log = [];
  window.__fetchLog = log;
  const orig = window.fetch.bind(window);
  window.fetch = (input, init) => {
    try { log.push(String(typeof input === 'string' ? input : input.url)); } catch { /* noop */ }
    return orig(input, init);
  };
});
const page = await context.newPage();

async function toastTexts() {
  return (await page.locator('.toast-stack .toast-msg').allInnerTexts());
}
function fetchCount(fragment) {
  return page.evaluate(
    (f) => window.__fetchLog.filter((u) => u.includes(f)).length,
    fragment,
  );
}

try {
  // 真实母版：取样例字节改名上传（basename 不命中 data/ 白名单 → 无样例豁免）
  const samples = (await (await fetch(MS_WEB_URL + '/api/samples')).json()).samples;
  const sampleName = samples[0].name;
  const blob = await (await fetch(MS_WEB_URL + '/api/samples/file?name=' + encodeURIComponent(sampleName))).blob();
  const buf = await blob.arrayBuffer();

  await page.goto(MS_WEB_URL + '/', { waitUntil: 'networkidle' });
  async function uploadRealDoc() {
    await page.setInputFiles('input[type=file]', {
      name: '工单-US007-验证.dxf',
      mimeType: 'application/dxf',
      buffer: Buffer.from(buf),
    });
    await page.waitForFunction(() => {
      const els = document.querySelectorAll('[data-testid="upload-status"]');
      return Array.from(els).some((e) => e.className.includes('done'));
    }, { timeout: 90000 });
    await page.waitForFunction(() => {
      const els = document.querySelectorAll('[data-testid="commit-status"]');
      return Array.from(els).some((e) => e.textContent && e.textContent.includes('已应用至超排'));
    }, { timeout: 90000 });
    await page.locator('button.tab', { hasText: '超排' }).click();
    await page.locator('#start').waitFor({ timeout: 8000 });
  }
  await uploadRealDoc();

  // 勾一个码号（普通运行载荷最小集）
  await page.locator('.sizes input[type=checkbox]').first().check();

  if (MODE === 'full') {
    // ---- B 普通运行拦截（无 WS 连接：phase 停留 idle → #start 仍在场）----
    await page.locator('#start').click();
    await page.waitForFunction(
      () => document.querySelector('#status')?.textContent?.includes('未绑定授权 key'),
      { timeout: 8000 },
    );
    const statusText = await page.locator('#status').innerText();
    check('B 普通运行拦截 StatusLine 中文', statusText.includes(MSG_NO_KEY), statusText);
    check('B 普通运行拦截 Toast', (await toastTexts()).some((t) => t.includes(MSG_NO_KEY)),
      (await toastTexts()).join(' | '));
    check('B 普通运行不进 WS（phase idle，#start 仍在）', (await page.locator('#start').count()) === 1);
    check('B precheck 已发', (await fetchCount('/api/key/precheck')) >= 1);
    await page.screenshot({ path: OUT + '/blocked-normal.png' });

    // ---- B 高级运行拦截（弹窗 errorMessage + /start 零发出）----
    await page.locator('[data-testid="strategy-btn"]').click();
    await page.locator('[data-testid="strategy-overlay"], .strategy-modal').first().waitFor({ timeout: 8000 });
    await page.locator('[data-testid="strategy-exec-btn"]').click();
    await page.locator('[data-testid="strategy-error"]').waitFor({ timeout: 8000 });
    const stratErr = await page.locator('[data-testid="strategy-error"]').innerText();
    check('B 高级运行拦截 弹窗 errorMessage', stratErr.includes(MSG_NO_KEY), stratErr);
    check('B 高级运行不发 /start', (await fetchCount('/api/strategy/start')) === 0);
    await page.screenshot({ path: OUT + '/blocked-strategy.png' });
    await page.locator('[data-testid="strategy-close"]').click();

    // ---- B 极限运行拦截 ----
    await page.locator('[data-testid="extreme-btn"]').click();
    await page.locator('[data-testid="extreme-overlay"]').waitFor({ timeout: 8000 });
    await page.locator('[data-testid="extreme-exec-btn"]').click();
    await page.locator('[data-testid="strategy-error"]').waitFor({ timeout: 8000 });
    const extErr = await page.locator('[data-testid="strategy-error"]').innerText();
    check('B 极限运行拦截 弹窗 errorMessage', extErr.includes(MSG_NO_KEY), extErr);
    check('B 极限运行不发 /start', (await fetchCount('/api/extreme/start')) === 0);
    await page.screenshot({ path: OUT + '/blocked-extreme.png' });
    await page.locator('[data-testid="extreme-close"]').click();
    await sleep(400);

    // ---- D 绑定 count key（KeyInfoModal）----
    await page.locator('[data-testid="key-entry-btn"]').click();
    await page.locator('[data-testid="key-info-overlay"]').waitFor({ timeout: 8000 });
    await page.locator('[data-testid="key-info-key-input"]').fill(COUNT_KEY);
    await page.locator('[data-testid="key-info-save"]').click();
    await page.locator('[data-testid="key-attr-total"]').waitFor({ timeout: 8000 });
    check('D count key 绑定成功', true);
    await page.keyboard.press('Escape');
    await sleep(400);

    // ---- E1 普通运行放行（phase running → #stop 在场）----
    const prePrecheck = await fetchCount('/api/key/precheck');
    // Toast 不自动消失（唯一出口 ✕）—— B 相位拦截 Toast 仍在栈内属设计内；
    // 放行断言 = 计数不增（无新失败 Toast），非栈内无残留。
    const preToastCount = (await toastTexts()).length;
    await page.locator('#start').click();
    await page.locator('#stop').waitFor({ timeout: 15000 });
    check('E1 普通运行放行（进 WS，phase running）', true);
    check('E1 放行无新失败 Toast', (await toastTexts()).length === preToastCount,
      (await toastTexts()).join(' | '));
    await page.locator('#stop').click();
    await page.locator('#start, #restart').first().waitFor({ timeout: 30000 });
    check('E1 停止回非 running 态', true);
    check('E1 precheck 放行后才发（计数增长）', (await fetchCount('/api/key/precheck')) > prePrecheck);

    // ---- E2 高级运行放行（202 → 进度态 → 停止）----
    await page.locator('[data-testid="strategy-btn"]').click();
    await page.locator('[data-testid="strategy-overlay"], .strategy-modal').first().waitFor({ timeout: 8000 });
    await page.locator('[data-testid="strategy-exec-btn"]').click();
    await page.locator('[data-testid="strategy-stop-btn"]').waitFor({ timeout: 30000 });
    check('E2 高级运行放行（202 起 worker，进度态）', true);
    check('E2 /start 已发出', (await fetchCount('/api/strategy/start')) === 1);
    await page.locator('[data-testid="strategy-stop-btn"]').click();
    await sleep(1500);
    await page.locator('[data-testid="strategy-close"]').click().catch(() => {});
    await sleep(600);

    // ---- E3 极限运行放行 ----
    await page.locator('[data-testid="extreme-btn"]').click();
    await page.locator('[data-testid="extreme-overlay"]').waitFor({ timeout: 8000 });
    await page.locator('[data-testid="extreme-exec-btn"]').click();
    await page.locator('[data-testid="strategy-stop-btn"]').waitFor({ timeout: 30000 });
    check('E3 极限运行放行（202 起 worker，进度态）', true);
    check('E3 /start 已发出', (await fetchCount('/api/extreme/start')) === 1);
    await page.locator('[data-testid="strategy-stop-btn"]').click();
    await sleep(1500);
    await page.locator('[data-testid="extreme-close"]').click().catch(() => {});
    await page.screenshot({ path: OUT + '/allowed.png' });
  } else {
    // ---- MODE=down：keyserver 已停，key 已绑 → 断网文案三入口一致 ----
    await page.locator('#start').click();
    await page.waitForFunction(
      () => document.querySelector('#status')?.textContent?.includes('无法连接授权服务器'),
      { timeout: 15000 },
    );
    const statusDown = await page.locator('#status').innerText();
    check('F 普通运行断网文案', statusDown.includes(MSG_DOWN), statusDown);
    check('F 普通运行不进 WS（#start 仍在）', (await page.locator('#start').count()) === 1);
    const toastDown = (await toastTexts()).find((t) => t.includes(MSG_DOWN));
    check('F 普通运行断网 Toast', Boolean(toastDown), (await toastTexts()).join(' | '));

    await page.locator('[data-testid="strategy-btn"]').click();
    await page.locator('[data-testid="strategy-overlay"], .strategy-modal').first().waitFor({ timeout: 8000 });
    await page.locator('[data-testid="strategy-exec-btn"]').click();
    await page.locator('[data-testid="strategy-error"]').waitFor({ timeout: 15000 });
    const stratDown = await page.locator('[data-testid="strategy-error"]').innerText();
    check('F 高级运行断网文案（与普通一致）', stratDown.trim() === MSG_DOWN, stratDown);
    check('F 高级运行不发 /start', (await fetchCount('/api/strategy/start')) === 0);
    await page.locator('[data-testid="strategy-close"]').click();

    await page.locator('[data-testid="extreme-btn"]').click();
    await page.locator('[data-testid="extreme-overlay"]').waitFor({ timeout: 8000 });
    await page.locator('[data-testid="extreme-exec-btn"]').click();
    await page.locator('[data-testid="strategy-error"]').waitFor({ timeout: 15000 });
    const extDown = await page.locator('[data-testid="strategy-error"]').innerText();
    check('F 极限运行断网文案（三入口一致）', extDown.trim() === MSG_DOWN, extDown);
    check('F 极限运行不发 /start', (await fetchCount('/api/extreme/start')) === 0);
    await page.screenshot({ path: OUT + '/down-consistent.png' });
    await page.locator('[data-testid="extreme-close"]').click();
  }
} catch (err) {
  check('脚本异常中断', false, String(err));
  await page.screenshot({ path: OUT + '/error.png' }).catch(() => {});
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
writeFileSync(OUT + '/report-' + MODE + '.txt',
  results.map((r) => (r.ok ? 'PASS' : 'FAIL') + '  ' + r.name).join('\n') + '\n');
console.log('\n[' + MODE + '] ' + (results.length - failed.length) + '/' + results.length + ' PASS -> ' + OUT + '/report-' + MODE + '.txt');
process.exitCode = failed.length ? 1 : 0;

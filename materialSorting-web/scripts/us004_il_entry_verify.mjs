// 初始布局 US-004（prd-initial-layout）「高级配置：设置初始布局」入口按钮浏览器
// 验证（playwright，手动脚本不入 vitest；模板 = us006_key_modal_verify.mjs）。
//
// 前置：ms-web 在 $MS_WEB_URL（缺省 http://127.0.0.1:8010，prod 模式需先
// npm run build —— static/ 为 React 构建产物）；样例母版在 data/（sample-apply
// 走真实 parse+commit 管线生成 intermediate，无需预跑 baseline）。
//
// 相位（PRD 验收：按钮置灰两条路径 —— 无母版态 + supported=false mock 态）：
//   A  无母版态（真实后端，supported=true）：按钮置灰 + title「请先上传母版」
//      + 位于「设置算法参数」按钮正下方 + 能力探测确实请求了 /api/warm-capability；
//   B  样例载入（母版在场 + 真实 supported=true）：按钮可点 + title 空；
//   C  mock 态（page.route 拦 /api/warm-capability → supported:false + reload）：
//      C1 无母版 + false → 无母版优先（title 仍「请先上传母版」）；
//      C2 重新样例载入（母版在场 + false）→ 置灰 + title「当前 spyrrow 版本不
//      支持热启动」。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/us004_il_entry';
mkdirSync(OUT, { recursive: true });

const MS_WEB_URL = process.env.MS_WEB_URL ?? 'http://127.0.0.1:8010';

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
});
const page = await context.newPage();

/** 能力探测请求计数（真实后端侧；mock 路由启用前有效）。 */
let realCapCalls = 0;
page.on('request', (req) => {
  if (req.url().includes('/api/warm-capability')) realCapCalls += 1;
});

const BTN = '[data-testid="initial-layout-btn"]';

/** 样例载入解锁超排 Tab（us006 gotoNesting 同款：真实 parse+commit 管线）。 */
async function gotoNesting() {
  await page.locator('[data-testid="sample-apply"]').click();
  await page.waitForFunction(() => {
    const els = document.querySelectorAll('[data-testid="commit-status"]');
    return Array.from(els).some((e) => e.textContent && e.textContent.includes('已应用至超排'));
  }, { timeout: 90000 });
  await page.locator('button.tab', { hasText: '超排' }).click();
  await page.locator(BTN).waitFor({ state: 'attached', timeout: 8000 });
  await sleep(300); // 等面板显隐切换稳定
}

/** 无母版期超排 Tab 上锁（.page .hidden display:none）—— attached 级等待。 */
async function waitBtnAttached() {
  await page.locator(BTN).waitFor({ state: 'attached', timeout: 8000 });
}

async function btnState() {
  const btn = page.locator(BTN);
  return {
    disabled: await btn.isDisabled(),
    title: (await btn.getAttribute('title')) ?? '',
    // textContent（非 innerText）：无母版期面板 display:none，innerText 恒空串
    text: ((await btn.textContent()) ?? '').trim(),
  };
}

try {
  // ---- A 无母版态（真实后端能力 supported=true）
  await page.goto(MS_WEB_URL + '/', { waitUntil: 'networkidle' });
  await sleep(800); // 等 App mount probeCapability 落定
  await waitBtnAttached();
  let st = await btnState();
  check('A 按钮文案', st.text === '高级配置：设置初始布局', st.text);
  check('A 无母版 → 置灰', st.disabled === true);
  check('A title=请先上传母版', st.title === '请先上传母版', st.title);
  check('A 能力探测已请求 /api/warm-capability（App 启动拉一次）', realCapCalls >= 1, String(realCapCalls));
  const pos = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('.per-type-btn'));
    const algo = btns.find((b) => b.textContent.includes('设置算法参数'));
    const il = document.querySelector('[data-testid="initial-layout-btn"]');
    if (!algo || !il) return null;
    return algo.compareDocumentPosition(il) & Node.DOCUMENT_POSITION_FOLLOWING;
  });
  check('A 位于「设置算法参数」按钮正下方（DOM 序）', Boolean(pos));

  // ---- B 样例载入（母版在场 + 真实 supported=true）→ 可点
  await gotoNesting();
  st = await btnState();
  check('B 母版在场 + supported=true → 可点', st.disabled === false);
  check('B title 空', st.title === '', st.title);

  // ---- C mock 态：拦 /api/warm-capability → supported:false + reload
  await context.route('**/api/warm-capability', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ supported: false, version: '0.9.0-mock' }),
    }));
  await page.reload({ waitUntil: 'networkidle' });
  await sleep(800);
  await waitBtnAttached();
  st = await btnState();
  check('C1 无母版 + supported=false → 仍置灰', st.disabled === true);
  check('C1 无母版优先（title 仍指上传）', st.title === '请先上传母版', st.title);
  await gotoNesting();
  st = await btnState();
  check('C2 母版在场 + supported=false（mock 态）→ 置灰', st.disabled === true);
  check('C2 title=当前 spyrrow 版本不支持热启动', st.title === '当前 spyrrow 版本不支持热启动', st.title);
} catch (e) {
  check('脚本异常中断', false, String(e));
} finally {
  await context.close();
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
writeFileSync(OUT + '/report.json', JSON.stringify({ results, failed: failed.length }, null, 2));
console.log(failed.length === 0 ? 'ALL PASS' : `FAILED ${failed.length}`);
process.exit(failed.length === 0 ? 0 : 1);

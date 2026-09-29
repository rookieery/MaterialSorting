// key 授权 US-006「系统key」弹窗浏览器验证（playwright，手动脚本不入 vitest；
// 模板 = us004_checkpoint_verify.mjs / smoke_sample_picker.mjs）。US-011 起 ②
// 区块为「系统可使用的key」表格（替代旧批量合并 textarea，选择器全部随改）。
//
// 前置（外部起，本脚本只做 UI 断言；见 verify 调用侧）：
//   - keyserver 在 $KEYSERVER_URL（DEV=1 无 token —— keygate._key_post 不带
//     X-Client-Token，admin/consumer 双族靠 DEV 逃生口放行）；
//   - ms-web 在 $MS_WEB_URL（MS_KEY_SERVER_URL 指向 keyserver；MS_OUT_DIR 指向
//     临时目录 —— key_state.json 不落真实 out/license）；
//   - env：US006_COUNT_KEY / US006_DURATION_KEY / US006_SOURCE_A / US006_SOURCE_B
//     （明文，由调用侧 admin API 创建 + node 侧 bind source 到同一 machine_guid）。
//
// 相位（US-006 AC + US-011 表格化改版）：
//   A  样例载入解锁超排 Tab → 入口按钮在「导出最优方案」正下方
//   B  未绑定态：空输入 + 引导文案 + 三区块齐备；表格两 source 行在表但全行
//      无合并按钮（本机无正在使用 key → 无 target）；ESC 关闭重开
//   C  假 key 保存 → 中文红字透传（key 不存在）
//   D  count key 保存 → 属性（总数/已用/剩余 + 正在使用徽标）+ localStorage 双写
//      + 表格 COUNT 置顶高亮、两 source 行合并按钮在
//   E  清 localStorage + 刷新（= 清缓存/换浏览器）→ 后端文件权威补回
//   F  duration key 替换保存 → 生效/截止/剩余天数 + 表格四行 DURATION 置顶
//   G  表格启用切换：点 COUNT 行启用 → 输入框/属性/高亮随动；再切回 DURATION
//   H  表格合并 SOURCE_A → 单行明细 + 被合并行出表 + 截止更新 + keyserver 对拍
//   I  合并失败：admin 删 SOURCE_B 后点其陈旧行 → 整体红字（key 不存在）
//   J  遮罩关闭 + ✕ 关闭（ExportInfoModal 同款）
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/us006_key_modal';
mkdirSync(OUT, { recursive: true });

const MS_WEB_URL = process.env.MS_WEB_URL ?? 'http://127.0.0.1:8010';
const KEYSERVER_URL = process.env.KEYSERVER_URL ?? 'http://127.0.0.1:8110';
const COUNT_KEY = process.env.US006_COUNT_KEY ?? '';
const DURATION_KEY = process.env.US006_DURATION_KEY ?? '';
const SOURCE_A = process.env.US006_SOURCE_A ?? '';
const SOURCE_B = process.env.US006_SOURCE_B ?? '';

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

async function openModal() {
  await page.locator('[data-testid="key-entry-btn"]').click();
  await page.locator('[data-testid="key-info-overlay"]').waitFor({ timeout: 8000 });
}
async function closeModalByEsc() {
  await page.keyboard.press('Escape');
  await page.locator('[data-testid="key-info-overlay"]').waitFor({ state: 'detached', timeout: 8000 });
}

try {
  // A 样例载入（解锁超排 Tab）—— 样例链路见 smoke_sample_picker.mjs。
  // gotoNesting：样例应用 → commit done → 切超排 Tab（reload 后新会话无 doc，
  // Tab 重新上锁，须重走样例解锁；E 相位复用）。
  async function gotoNesting() {
    await page.locator('[data-testid="sample-apply"]').click();
    await page.waitForFunction(() => {
      const els = document.querySelectorAll('[data-testid="commit-status"]');
      return Array.from(els).some((e) => e.textContent && e.textContent.includes('已应用至超排'));
    }, { timeout: 90000 });
    await page.locator('button.tab', { hasText: '超排' }).click();
    await page.locator('.key-entry-group').waitFor({ timeout: 8000 });
  }
  await page.goto(MS_WEB_URL + '/', { waitUntil: 'networkidle' });
  await gotoNesting();
  const labelPos = await page.evaluate(() => {
    const exp = document.querySelector('.export-group');
    const key = document.querySelector('.key-entry-group');
    if (!exp || !key) return null;
    return exp.compareDocumentPosition(key) & Node.DOCUMENT_POSITION_FOLLOWING;
  });
  check('A 入口区块在「导出最优方案」正下方', Boolean(labelPos));
  const labelText = await page.locator('.key-entry-group .field-label').innerText();
  check('A field-label 文案', labelText === '系统key', labelText);

  // B 未绑定态（三区块 + 引导 + 表格：source 已绑本机但无正在使用 key）
  await openModal();
  const emptyHint = await page.locator('[data-testid="key-info-empty-hint"]').innerText();
  check('B 未绑定引导文案', emptyHint.includes('尚未绑定授权 key'), emptyHint);
  for (const t of ['key-info-current', 'key-info-list', 'key-info-attrs']) {
    check('B 区块在场 ' + t, (await page.locator(`[data-testid="${t}"]`).count()) === 1);
  }
  const ph = await page.locator('[data-testid="key-info-key-input"]').getAttribute('placeholder');
  check('B 空输入引导 placeholder', (ph ?? '').includes('输入授权 key'), ph);
  const rowOf = (k) => page.locator(`[data-testid="key-info-row"][data-key="${k}"]`);
  await page.locator('[data-testid="key-info-table"]').waitFor({ timeout: 8000 });
  await rowOf(SOURCE_A).waitFor({ timeout: 8000 });
  await rowOf(SOURCE_B).waitFor({ timeout: 8000 });
  check('B 表格两 source 行（已绑本机在表）',
    (await page.locator('[data-testid="key-info-row"]').count()) === 2);
  check('B 本机无正在使用 key → 全行无合并按钮',
    (await page.locator('[data-testid="key-info-merge-one"]').count()) === 0);
  check('B 无高亮行（data-active 全 false）',
    (await page.locator('[data-testid="key-info-row"][data-active="true"]').count()) === 0);
  check('B 启用按钮可点',
    !(await page.locator('[data-testid="key-info-enable"]').first().isDisabled()));
  await closeModalByEsc();
  await openModal(); // 重开（每次打开重新对账）
  await sleep(600);  // 等 fetchState 落定

  // C 假 key 保存 → 中文红字
  await page.locator('[data-testid="key-info-key-input"]').fill('MS-FAKE-NOPE');
  await page.locator('[data-testid="key-info-save"]').click();
  await page.locator('[data-testid="key-info-save-error"]').waitFor({ timeout: 8000 });
  const errText = await page.locator('[data-testid="key-info-save-error"]').innerText();
  check('C 假 key 红字透传', errText.includes('key 不存在'), errText);
  check('C 失败不落镜像', (await page.evaluate(() => localStorage.getItem('ms_key'))) === null);

  // D count key 保存 → 属性 + 徽标 + 镜像双写
  await page.locator('[data-testid="key-info-key-input"]').fill(COUNT_KEY);
  await page.locator('[data-testid="key-info-save"]').click();
  await page.locator('[data-testid="key-attr-total"]').waitFor({ timeout: 8000 });
  const total = await page.locator('[data-testid="key-attr-total"]').innerText();
  const remaining = await page.locator('[data-testid="key-attr-remaining"]').innerText();
  check('D 次数型 总数/剩余', total.includes('5') && remaining.includes('5'), total + ' | ' + remaining);
  const badge = await page.locator('[data-testid="key-attr-status"] .key-status-badge').innerText();
  check('D 正在使用徽标', badge === '正在使用', badge);
  const mirror = await page.evaluate(() => localStorage.getItem('ms_key'));
  check('D localStorage 双写', mirror === COUNT_KEY, String(mirror));
  // D 表格随动（保存成功链式刷新）：COUNT 置顶高亮 + 两 source 行合并按钮在
  await page.locator(`[data-testid="key-info-row"][data-key="${COUNT_KEY}"][data-active="true"]`)
    .waitFor({ timeout: 8000 });
  check('D 表格三行（COUNT 置顶 + 两 source）',
    (await page.locator('[data-testid="key-info-row"]').count()) === 3);
  const dTopKey = await page.locator('[data-testid="key-info-row"]').first().getAttribute('data-key');
  check('D COUNT 行置顶高亮', dTopKey === COUNT_KEY, String(dTopKey));
  check('D 两 source 行各一枚合并按钮',
    (await page.locator('[data-testid="key-info-merge-one"]').count()) === 2);
  await page.screenshot({ path: OUT + '/count-attrs.png' });

  // E 清缓存（清 localStorage）+ 刷新 → 后端文件权威补回（新会话无 doc →
  // 重走样例解锁超排 Tab）
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: 'networkidle' });
  await gotoNesting();
  await openModal();
  await page.locator('[data-testid="key-attr-total"]').waitFor({ timeout: 8000 });
  const refilled = await page.locator('[data-testid="key-info-key-input"]').inputValue();
  check('E 换浏览器/清缓存后端补回', refilled === COUNT_KEY, refilled);

  // F duration key 替换保存 → 生效/截止/剩余天数
  await page.locator('[data-testid="key-info-key-input"]').fill(DURATION_KEY);
  await page.locator('[data-testid="key-info-save"]').click();
  await page.locator('[data-testid="key-attr-days"]').waitFor({ timeout: 8000 });
  const act = await page.locator('[data-testid="key-attr-activated"]').innerText();
  const exp = await page.locator('[data-testid="key-attr-expires"]').innerText();
  const days = await page.locator('[data-testid="key-attr-days"]').innerText();
  check('F 时长型 生效/截止/剩余天数', act.includes('2026') && exp.includes('2026') && days.includes('10'),
    act + ' | ' + exp + ' | ' + days);
  // F 表格随动：四行（DURATION/COUNT/两 source）、DURATION 置顶高亮
  await page.locator(`[data-testid="key-info-row"][data-key="${DURATION_KEY}"][data-active="true"]`)
    .waitFor({ timeout: 8000 });
  check('F 表格四行 DURATION 置顶',
    (await page.locator('[data-testid="key-info-row"]').count()) === 4
      && (await page.locator('[data-testid="key-info-row"]').first().getAttribute('data-key')) === DURATION_KEY);

  // G 表格启用切换：点 COUNT 行启用 → 输入框/属性/高亮随动；再切回 DURATION
  await page.locator(`[data-testid="key-info-row"][data-key="${COUNT_KEY}"]`)
    .locator('[data-testid="key-info-enable"]').click();
  await page.locator('[data-testid="key-attr-total"]').waitFor({ timeout: 8000 });
  const gInput = await page.locator('[data-testid="key-info-key-input"]').inputValue();
  check('G 表格启用切到 COUNT（输入框对齐 + 属性次数型）', gInput === COUNT_KEY, gInput);
  await page.locator(`[data-testid="key-info-row"][data-key="${DURATION_KEY}"]`)
    .locator('[data-testid="key-info-enable"]').click();
  await page.locator(`[data-testid="key-info-row"][data-key="${DURATION_KEY}"][data-active="true"]`)
    .waitFor({ timeout: 8000 });
  const g2Input = await page.locator('[data-testid="key-info-key-input"]').inputValue();
  check('G 切回 DURATION（合并 target 就位）', g2Input === DURATION_KEY, g2Input);

  // H 表格合并 SOURCE_A → 单行明细 + 被合并行出表 + 截止更新
  const expiresBefore = exp;
  await rowOf(SOURCE_A).locator('[data-testid="key-info-merge-one"]').click();
  const detail = page.locator('[data-testid="key-info-merge-row"]').first();
  await detail.waitFor({ timeout: 8000 });
  const hDetail = await detail.innerText();
  check('H 合并明细一行（key + 转移天数）',
    hDetail.includes(SOURCE_A) && /已合并：\+\d/.test(hDetail), hDetail);
  check('H 无合计行（旧批量口径已拆）',
    (await page.locator('[data-testid="key-info-merge-total"]').count()) === 0);
  await rowOf(SOURCE_A).waitFor({ state: 'detached', timeout: 8000 });
  check('H 被合并行出表（表格随动刷新）',
    (await page.locator('[data-testid="key-info-row"]').count()) === 3);
  const expiresAfter = await page.locator('[data-testid="key-attr-expires"]').innerText();
  check('H 截止随合并更新', expiresAfter !== expiresBefore, expiresBefore + ' → ' + expiresAfter);
  await page.screenshot({ path: OUT + '/merge-result.png' });

  // keyserver 侧对拍：source 已标记合并（admin /keys detail 含「已合并」）
  const keysList = await (await fetch(KEYSERVER_URL + '/api/admin/keys')).json();
  const src = (keysList.keys ?? keysList).find?.((k) => k.key_plaintext === SOURCE_A);
  const srcStatus = src ? JSON.stringify(src) : JSON.stringify(keysList).slice(0, 200);
  check('H keyserver 侧 source 已合并', srcStatus.includes('已合并'), srcStatus);

  // I 合并失败：admin 删 SOURCE_B → 点其陈旧行合并 → 整体红字（key 不存在）
  const srcB = (keysList.keys ?? keysList).find?.((k) => k.key_plaintext === SOURCE_B);
  const del = await fetch(KEYSERVER_URL + '/api/admin/keys/' + (srcB?.id ?? 0), { method: 'DELETE' });
  check('I 前置 admin 删 SOURCE_B', del.ok, 'HTTP ' + del.status);
  await rowOf(SOURCE_B).locator('[data-testid="key-info-merge-one"]').click();
  await page.locator('[data-testid="key-info-merge-error"]').waitFor({ timeout: 8000 });
  const mErr = await page.locator('[data-testid="key-info-merge-error"]').innerText();
  check('I 合并失败原因透传', mErr.includes('key 不存在'), mErr);

  // J 遮罩关闭 + ✕ 关闭
  await page.locator('[data-testid="key-info-overlay"]').click({ position: { x: 8, y: 8 } });
  await page.locator('[data-testid="key-info-overlay"]').waitFor({ state: 'detached', timeout: 8000 });
  check('I 遮罩关闭', true);
  await openModal();
  await page.locator('[data-testid="key-info-close"]').click();
  await page.locator('[data-testid="key-info-overlay"]').waitFor({ state: 'detached', timeout: 8000 });
  check('I ✕ 关闭', true);
} catch (err) {
  check('脚本异常中断', false, String(err));
  await page.screenshot({ path: OUT + '/error.png' }).catch(() => {});
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
writeFileSync(OUT + '/report.txt',
  results.map((r) => (r.ok ? 'PASS' : 'FAIL') + '  ' + r.name).join('\n') + '\n');
console.log(`\n${results.length - failed.length}/${results.length} PASS → ${OUT}/report.txt`);
process.exitCode = failed.length ? 1 : 0;

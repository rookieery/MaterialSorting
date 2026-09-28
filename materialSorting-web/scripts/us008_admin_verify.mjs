// key 授权 US-008「keyserver 管理后台可视化单页」浏览器验证（playwright，手动脚本
// 不入 vitest；模板 = us007_key_gate_verify.mjs）。
//
// 前置（外部起，本脚本只做 UI 断言；见 verify 调用侧）：
//   - KEYSERVER_URL：主实例 —— MS_KEY_ADMIN_TOKEN 已设 + MS_KEY_DEV=1（消费端
//     免 token 供脚本 bind/validate 造态）+ MS_KEY_DB 临时库
//   - BARE_URL：裸实例 —— 无 token 无 DEV + 独立临时库（「未配置 token」指引相位）
//   - env：US008_ADMIN_TOKEN（主实例管理 token）
//
// 相位（US-008 AC）：
//   A  裸实例 /admin → 配置指引文案（双 token 必设）
//   B  登录框：错 token → 401 红字（sessionStorage 不留）
//   C  正确 token → 表格八列 + 空态
//   D  新建次数型（单位次）→ 即时入表 0/5 未绑定 统计 —
//   E  新建时长型（生效时长，默认单位天）→ 30天
//   F  编辑弹窗：改备注 + 次数型加次数 → 0/10 可见
//   G  consumer bind（node 侧）→ 刷新 → 正在使用 + 绑定系统名 + 起~止
//   H  时长型加天数 → 截止时间恰好 +10 天
//   I  使用统计一格三行（均/峰/共）+ keyserver 侧对拍 usage_stats.total
//   J  未绑定直删（无弹窗）
//   K  已用完直删（无弹窗）
//   L  正在使用 → 二段确认弹窗 → 确认（force）才删
//   M  退出登录清 sessionStorage；再登录后 reload 自动免输
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const ROOT = resolve(HERE, '../..');
const OUT = ROOT + '/out/us008_admin';
mkdirSync(OUT, { recursive: true });

const KEYSERVER_URL = process.env.KEYSERVER_URL ?? 'http://127.0.0.1:8120';
const BARE_URL = process.env.BARE_URL ?? 'http://127.0.0.1:8121';
const ADMIN_TOKEN = process.env.US008_ADMIN_TOKEN ?? 'us008-admin-token';
const GUID = 'us008-verify-guid';

const results = [];
function check(name, ok, extra) {
  results.push({ name, ok });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 160) + ']' : '');
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* node 侧 consumer/admin API 便捷封装（造态与对拍） */
async function consumer(path, body) {
  const resp = await fetch(KEYSERVER_URL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: resp.status, data: await resp.json().catch(() => null) };
}
async function adminList() {
  const resp = await fetch(KEYSERVER_URL + '/api/admin/keys', {
    headers: { 'X-Admin-Token': ADMIN_TOKEN },
  });
  return (await resp.json()).keys;
}
/* 幂等复位：清空主实例既有 key（上轮残留），让「空态」断言可重跑 */
async function resetKeys() {
  for (const k of await adminList()) {
    await fetch(KEYSERVER_URL + '/api/admin/keys/' + k.id + '?force=true', {
      method: 'DELETE',
      headers: { 'X-Admin-Token': ADMIN_TOKEN },
    });
  }
}

const { chromium } = await import('playwright');
let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await context.grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => {});
const page = await context.newPage();

async function login(tokenValue) {
  await page.locator('#token-input').fill(tokenValue);
  await page.locator('#btn-login').click();
  await page.locator('#main:not(.hidden)').waitFor({ timeout: 8000 });
}
function rowOf(keyPlaintext) {
  return page.locator('#keys-body tr[data-id]', { hasText: keyPlaintext });
}
async function cellText(keyPlaintext, colIndex) {
  const row = rowOf(keyPlaintext);
  await row.waitFor({ timeout: 8000 });
  return (await row.locator('td').nth(colIndex).innerText()).trim();
}
async function rowCount() {
  return page.locator('#keys-body tr[data-id]').count();
}
async function createKeyViaUI(type, amount, remark) {
  await page.locator('input[name=key-type][value=' + type + ']').check();
  await page.locator('#amount-input').fill(String(amount));
  await page.locator('#remark-input').fill(remark);
  // 清上一轮成功消息，防 waitForFunction 误匹配旧明文
  await page.evaluate(() => { document.getElementById('global-msg').textContent = ''; });
  await page.locator('#btn-create').click();
  // 创建后即时出现在表格：全局消息里的新明文也出现在行里
  await page.waitForFunction(
    () => {
      const msg = document.getElementById('global-msg')?.textContent || '';
      const m = msg.match(/MS-[A-Z2-9]{5}-[A-Z2-9]{5}-[A-Z2-9]{5}/);
      if (!m) return false;
      return document.querySelector('#keys-body')?.textContent.includes(m[0]);
    },
    { timeout: 8000 },
  );
  const msg = await page.locator('#global-msg').innerText();
  return msg.match(/MS-[A-Z2-9]{5}-[A-Z2-9]{5}-[A-Z2-9]{5}/)[0];
}
async function editViaUI(keyPlaintext, { remark, renew }) {
  await rowOf(keyPlaintext).locator('button[data-act=edit]').click();
  await page.locator('#edit-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  if (remark !== undefined) await page.locator('#edit-remark').fill(remark);
  if (renew !== undefined) await page.locator('#edit-renew-amount').fill(String(renew));
  await page.locator('#btn-edit-save').click();
  await page.locator('#edit-overlay').waitFor({ state: 'hidden', timeout: 8000 });
}
function parseDetailRange(detail) {
  const parts = detail.split('~').map((s) => s.trim());
  return { start: parts[0], end: parts[1] };
}

try {
  await resetKeys();

  // ---- A 裸实例（未配置 token）：配置指引文案 ----
  await page.goto(BARE_URL + '/admin', { waitUntil: 'networkidle' });
  await page.locator('#unconfigured-card:not(.hidden)').waitFor({ timeout: 8000 });
  const guide = await page.locator('#unconfigured-card').innerText();
  check('A 未配置部署显示配置指引（MS_KEY_ADMIN_TOKEN）', guide.includes('MS_KEY_ADMIN_TOKEN'), guide.slice(0, 120));
  check('A 指引含双 token 必设（frp）', guide.includes('MS_KEY_CLIENT_TOKEN') && guide.includes('frp'), '');
  check('A 未配置时登录框/表格隐藏',
    await page.locator('#token-card').isHidden() && await page.locator('#main').isHidden());
  await page.screenshot({ path: OUT + '/guidance.png' });

  // ---- B 登录框 + 错 token ----
  await page.goto(KEYSERVER_URL + '/admin', { waitUntil: 'networkidle' });
  await page.locator('#token-card:not(.hidden)').waitFor({ timeout: 8000 });
  check('B 无 token 先见登录框', await page.locator('#main').isHidden());
  await page.locator('#token-input').fill('wrong-token-xxx');
  await page.locator('#btn-login').click();
  await page.locator('#token-error:not(.hidden)').waitFor({ timeout: 8000 });
  const wrongMsg = await page.locator('#token-error').innerText();
  check('B 错 token 401 红字', wrongMsg.includes('管理 token 错误'), wrongMsg);
  const keptWrong = await page.evaluate(() => sessionStorage.getItem('ms_admin_token'));
  check('B 错 token 不落 sessionStorage', keptWrong === null, String(keptWrong));
  await page.screenshot({ path: OUT + '/login-error.png' });

  // ---- C 正确 token → 八列表格 ----
  await login(ADMIN_TOKEN);
  check('C token 存 sessionStorage', (await page.evaluate(() => sessionStorage.getItem('ms_admin_token'))) === ADMIN_TOKEN);
  const heads = await page.locator('table thead th').allInnerTexts();
  check('C 表格八列列序', heads.join('|') === '名称|绑定系统名|备注名|类型|详细信息|属性|使用统计|操作', heads.join('|'));
  const emptyHint = await page.locator('#keys-body').innerText();
  check('C 空态提示', emptyHint.includes('暂无 key'), emptyHint);

  // ---- D 新建次数型 ----
  const countKey = await createKeyViaUI('count', 5, '验证-次数');
  check('D 次数型 类型列', (await cellText(countKey, 3)) === '次数');
  check('D 次数型 详细信息 0/5', (await cellText(countKey, 4)) === '0/5');
  check('D 次数型 属性 未绑定', (await cellText(countKey, 5)) === '未绑定');
  check('D 无使用记录 —', (await cellText(countKey, 6)) === '—');
  check('D 备注名上屏', (await cellText(countKey, 2)) === '验证-次数');

  // ---- E 新建时长型（默认单位天） ----
  await page.locator('input[name=key-type][value=duration]').check();
  check('E 时长型字段切换 生效时长/天',
    (await page.locator('#amount-field').innerText()) === '生效时长'
    && (await page.locator('#amount-unit').innerText()) === '天');
  const durationKey = await createKeyViaUI('duration', 30, '验证-时长');
  check('E 时长型 类型列', (await cellText(durationKey, 3)) === '时长');
  check('E 时长型 详细信息 30天（未激活不显起止）', (await cellText(durationKey, 4)) === '30天');

  // ---- F 编辑弹窗：改备注 + 次数型加次数 → 表格即时生效 ----
  await rowOf(countKey).locator('button[data-act=edit]').click();
  await page.locator('#edit-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  const editTitle = await page.locator('#edit-key-name').innerText();
  check('F 编辑弹窗明文+型别', editTitle.includes(countKey) && editTitle.includes('次数型'), editTitle);
  check('F 次数型续期单位 次', (await page.locator('#edit-renew-unit').innerText()) === '次');
  await page.screenshot({ path: OUT + '/edit-modal.png' });
  await page.locator('#edit-remark').fill('验证-次数-改');
  await page.locator('#edit-renew-amount').fill('5');
  await page.locator('#btn-edit-save').click();
  await page.locator('#edit-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  await rowOf(countKey).locator('td').nth(4).filter({ hasText: '0/10' }).waitFor({ timeout: 8000 });
  check('F 加 5 次后 remaining 0/10 可见', (await cellText(countKey, 4)) === '0/10');
  check('F 备注名修改即时生效', (await cellText(countKey, 2)) === '验证-次数-改');

  // ---- G consumer bind 时长型（node 造态）→ 刷新 → 正在使用 ----
  const bindResp = await consumer('/api/key/bind', {
    key: durationKey, machine_guid: GUID, system_name: 'US008-VERIFY',
  });
  check('G node 侧 bind 200', bindResp.status === 200, JSON.stringify(bindResp.data).slice(0, 120));
  await page.locator('#btn-refresh').click();
  await rowOf(durationKey).locator('.badge.ok').waitFor({ timeout: 8000 });
  check('G 绑定后属性 正在使用（绿徽标）', (await cellText(durationKey, 5)) === '正在使用');
  check('G 绑定系统名只读展示', (await cellText(durationKey, 1)) === 'US008-VERIFY');
  const detailBefore = await cellText(durationKey, 4);
  check('G 激活后详细信息 起 ~ 止', detailBefore.includes('~'), detailBefore);

  // ---- H 时长型加天数 → 截止时间恰好 +10 天 ----
  await editViaUI(durationKey, { renew: 10 });
  await rowOf(durationKey).locator('td').nth(4).filter({ hasText: '~' }).waitFor({ timeout: 8000 });
  const detailAfter = await cellText(durationKey, 4);
  const before = parseDetailRange(detailBefore);
  const after = parseDetailRange(detailAfter);
  const diffDays = (new Date(after.end.replace(' ', 'T')) - new Date(before.end.replace(' ', 'T'))) / 86400000;
  check('H 截止时间 +10 天（起不变）', diffDays === 10 && after.start === before.start,
    detailBefore + ' -> ' + detailAfter);

  // ---- I 使用统计一格三行 + keyserver 侧对拍 ----
  const statsKey = await createKeyViaUI('count', 50, '验证-统计');
  await consumer('/api/key/bind', { key: statsKey, machine_guid: GUID, system_name: 'US008-VERIFY' });
  await consumer('/api/key/validate', { key: statsKey, machine_guid: GUID, deduct: true });
  await consumer('/api/key/validate', { key: statsKey, machine_guid: GUID, deduct: true });
  await page.locator('#btn-refresh').click();
  await rowOf(statsKey).locator('.stats').filter({ hasText: '共 2' }).waitFor({ timeout: 8000 });
  const statsLines = (await rowOf(statsKey).locator('.stats span').allInnerTexts()).map((s) => s.trim());
  check('I 统计三行 均/峰/共', statsLines.length === 3
    && statsLines[0] === '均 2.0/日' && statsLines[1] === '峰 2' && statsLines[2] === '共 2',
    statsLines.join(' | '));
  const serverSide = (await adminList()).find((k) => k.key_plaintext === statsKey);
  check('I keyserver 侧对拍 used/统计一致', serverSide && serverSide.usage_stats
    && serverSide.usage_stats.total === 2 && serverSide.usage_stats.max_daily === 2,
    JSON.stringify(serverSide && serverSide.usage_stats));
  await page.screenshot({ path: OUT + '/table.png' });

  // ---- J 未绑定 key 直删（无弹窗） ----
  const rowsBefore = await rowCount();
  await rowOf(countKey).locator('button[data-act=del]').click();
  await rowOf(countKey).waitFor({ state: 'detached', timeout: 8000 });
  check('J 未绑定直删行消失', (await rowCount()) === rowsBefore - 1);
  check('J 直删无确认弹窗', await page.locator('#del-overlay').isHidden());

  // ---- K 已用完直删 ----
  const exhaustedKey = await createKeyViaUI('count', 1, '验证-用完');
  await consumer('/api/key/bind', { key: exhaustedKey, machine_guid: GUID, system_name: 'US008-VERIFY' });
  const deductResp = await consumer('/api/key/validate', { key: exhaustedKey, machine_guid: GUID, deduct: true });
  check('K node 侧扣至用完 200', deductResp.status === 200, JSON.stringify(deductResp.data).slice(0, 120));
  await page.locator('#btn-refresh').click();
  await rowOf(exhaustedKey).locator('.badge.bad').waitFor({ timeout: 8000 });
  check('K 属性 已用完（红徽标）', (await cellText(exhaustedKey, 5)) === '已用完');
  await rowOf(exhaustedKey).locator('button[data-act=del]').click();
  await rowOf(exhaustedKey).waitFor({ state: 'detached', timeout: 8000 });
  check('K 已用完直删（无弹窗）', await page.locator('#del-overlay').isHidden());

  // ---- L 正在使用 → 二段确认弹窗 → force 才删 ----
  await rowOf(statsKey).locator('button[data-act=del]').click();
  await page.locator('#del-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  check('L 正在使用弹二段确认（含明文）', (await page.locator('#del-text').innerText()).includes(statsKey));
  check('L 警示文案在场', (await page.locator('#del-warning').innerText()).includes('正在使用'));
  await page.screenshot({ path: OUT + '/delete-confirm.png' });
  await page.locator('#btn-del-confirm').click();
  await rowOf(statsKey).waitFor({ state: 'detached', timeout: 8000 });
  check('L 确认后 force 删除成功', (await rowOf(statsKey).count()) === 0);
  const serverGone = (await adminList()).find((k) => k.key_plaintext === statsKey);
  check('L keyserver 侧确已删', serverGone === undefined);

  // ---- M 退出登录 / sessionStorage 持久自动登录 ----
  await page.locator('#btn-logout').click();
  await page.locator('#token-card:not(.hidden)').waitFor({ timeout: 8000 });
  check('M 退出后回登录框', await page.locator('#main').isHidden());
  check('M 退出清 sessionStorage', (await page.evaluate(() => sessionStorage.getItem('ms_admin_token'))) === null);
  await login(ADMIN_TOKEN);
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('#main:not(.hidden)').waitFor({ timeout: 8000 });
  check('M reload 免重输（sessionStorage 自动登录）', await page.locator('#main').isVisible());
} catch (err) {
  check('脚本异常中断', false, String(err));
  await page.screenshot({ path: OUT + '/error.png' }).catch(() => {});
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
writeFileSync(OUT + '/report.txt', results.map((r) => (r.ok ? 'PASS' : 'FAIL') + '  ' + r.name).join('\n') + '\n');
console.log('\n' + (results.length - failed.length) + '/' + results.length + ' PASS -> ' + OUT + '/report.txt');
process.exitCode = failed.length ? 1 : 0;

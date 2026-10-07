// key 授权 US-008「keyserver 管理后台可视化单页」浏览器验证（playwright，手动脚本
// 不入 vitest；模板 = us007_key_gate_verify.mjs）。
//
// 前置（外部起，本脚本只做 UI 断言；见 verify 调用侧）：
//   - KEYSERVER_URL：主实例 —— MS_KEY_ADMIN_TOKEN 已设 + MS_KEY_DEV=1（消费端
//     免 token 供脚本 bind/validate 造态）+ MS_KEY_DB 临时库
//   - BARE_URL：裸实例 —— 无 token 无 DEV + 独立临时库（「未配置 token」指引相位）
//   - env：US008_ADMIN_TOKEN（主实例管理 token）
//
// 相位（US-008 AC + 绑定系统名列表改版）：
//   A  裸实例 /admin → 配置指引文案（双 token 必设）
//   B  登录框：错 token → 401 红字（sessionStorage 不留）
//   C  正确 token → key 表七列 + 绑定系统名列表五列 + 双空态
//   D  新建次数型（无备注名输入框）→ 即时入表 0/5 未绑定；未绑定不派生系统行
//   E  新建时长型（生效时长，默认单位天）→ 30天
//   F  续期弹窗（无备注名字段）：次数型加次数 → 0/10 可见
//   G  consumer bind（node 侧）→ 刷新 → 正在使用 + 绑定系统名 + 起~止；
//      绑定系统名列表出现该系统行（key 数 1）
//   H  时长型加天数 → 截止时间恰好 +10 天
//   I  系统表使用统计 = 名下全部 key 合并日序列（均/峰/共）+ keyserver 侧对拍
//   I2 系统备注编辑弹窗：保存上屏 + 空串清除
//   J  未绑定直删（无弹窗；系统行不受影响）
//   K  已用完直删（无弹窗；其统计随之消失，系统表回落）
//   L  正在使用 → 二段确认弹窗 → 确认（force）才删（系统行还有 key 不消失）
//   L2 级联：删掉系统名下最后一把 key → 系统行（含备注）随之删除
//   M  退出登录清 sessionStorage；再登录后 reload 自动免输
//   N  key 表滚动容器（约表头+10 行限高、sticky 表头）+ 绑定系统名/属性表头
//      类别过滤弹窗（计数勾选/交集/全选=清过滤/全不选空态/ESC 丢弃/刷新剪枝）
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
const SYS = 'US008-VERIFY';

const results = [];
function check(name, ok, extra) {
  results.push({ name, ok });
  console.log(ok ? 'PASS' : 'FAIL', name, extra ? '  [' + String(extra).slice(0, 160) + ']' : '');
}

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
async function systemsList() {
  const resp = await fetch(KEYSERVER_URL + '/api/admin/systems', {
    headers: { 'X-Admin-Token': ADMIN_TOKEN },
  });
  return (await resp.json()).systems;
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
function sysRowOf(systemName) {
  return page.locator('#systems-body tr[data-name]', { hasText: systemName });
}
async function sysCellText(systemName, colIndex) {
  const row = sysRowOf(systemName);
  await row.waitFor({ timeout: 8000 });
  return (await row.locator('td').nth(colIndex).innerText()).trim();
}
async function createKeyViaUI(type, amount) {
  await page.locator('input[name=key-type][value=' + type + ']').check();
  await page.locator('#amount-input').fill(String(amount));
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
async function renewViaUI(keyPlaintext, amount) {
  await rowOf(keyPlaintext).locator('button[data-act=renew]').click();
  await page.locator('#edit-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  await page.locator('#edit-renew-amount').fill(String(amount));
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

  // ---- C 正确 token → key 表七列 + 系统表五列 ----
  await login(ADMIN_TOKEN);
  check('C token 存 sessionStorage', (await page.evaluate(() => sessionStorage.getItem('ms_admin_token'))) === ADMIN_TOKEN);
  const heads = await page.locator('table thead th').allInnerTexts();
  check('C 列序：key 表七列 + 系统表五列',
    heads.join('|') === '名称|绑定系统名|类型|详细信息|属性|最新使用时间|操作|绑定系统名|备注名|key 数|使用统计|操作',
    heads.join('|'));
  const emptyHint = await page.locator('#keys-body').innerText();
  check('C key 表空态提示', emptyHint.includes('暂无 key'), emptyHint);
  const sysEmpty = await page.locator('#systems-body').innerText();
  check('C 系统表空态提示', sysEmpty.includes('暂无绑定系统'), sysEmpty);

  // ---- D 新建次数型（新建表单已无备注名输入框） ----
  check('D 新建表单无备注名输入框', (await page.locator('#remark-input').count()) === 0);
  const countKey = await createKeyViaUI('count', 5);
  check('D 次数型 类型列', (await cellText(countKey, 2)) === '次数');
  check('D 次数型 详细信息 0/5', (await cellText(countKey, 3)) === '0/5');
  check('D 次数型 属性 未绑定', (await cellText(countKey, 4)) === '未绑定');
  check('D 未使用 最新使用时间 —', (await cellText(countKey, 5)) === '—');
  check('D 未绑定不派生系统行', (await page.locator('#systems-body tr[data-name]').count()) === 0);

  // ---- E 新建时长型（默认单位天） ----
  await page.locator('input[name=key-type][value=duration]').check();
  check('E 时长型字段切换 生效时长/天',
    (await page.locator('#amount-field').innerText()) === '生效时长'
    && (await page.locator('#amount-unit').innerText()) === '天');
  const durationKey = await createKeyViaUI('duration', 30);
  check('E 时长型 类型列', (await cellText(durationKey, 2)) === '时长');
  check('E 时长型 详细信息 30天（未激活不显起止）', (await cellText(durationKey, 3)) === '30天');

  // ---- F 续期弹窗（备注名已迁移为系统级，弹窗无备注字段） ----
  await rowOf(countKey).locator('button[data-act=renew]').click();
  await page.locator('#edit-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  const renewTitle = await page.locator('#edit-key-name').innerText();
  check('F 续期弹窗明文+型别', renewTitle.includes(countKey) && renewTitle.includes('次数型'), renewTitle);
  check('F 弹窗无备注名字段', (await page.locator('#edit-remark').count()) === 0);
  check('F 次数型续期单位 次', (await page.locator('#edit-renew-unit').innerText()) === '次');
  await page.screenshot({ path: OUT + '/renew-modal.png' });
  await page.locator('#edit-renew-amount').fill('5');
  await page.locator('#btn-edit-save').click();
  await page.locator('#edit-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  await rowOf(countKey).locator('td').nth(3).filter({ hasText: '0/10' }).waitFor({ timeout: 8000 });
  check('F 加 5 次后 remaining 0/10 可见', (await cellText(countKey, 3)) === '0/10');

  // ---- G consumer bind 时长型（node 造态）→ 刷新 → 正在使用 + 系统表派生行 ----
  const bindResp = await consumer('/api/key/bind', {
    key: durationKey, machine_guid: GUID, system_name: SYS,
  });
  check('G node 侧 bind 200', bindResp.status === 200, JSON.stringify(bindResp.data).slice(0, 120));
  await page.locator('#btn-refresh').click();
  await rowOf(durationKey).locator('.badge.ok').waitFor({ timeout: 8000 });
  check('G 绑定后属性 正在使用（绿徽标）', (await cellText(durationKey, 4)) === '正在使用');
  check('G 绑定系统名只读展示', (await cellText(durationKey, 1)) === SYS);
  const detailBefore = await cellText(durationKey, 3);
  check('G 激活后详细信息 起 ~ 止', detailBefore.includes('~'), detailBefore);
  check('G 系统表派生行（key 数 1）', (await sysCellText(SYS, 2)) === '1');
  check('G 系统行首列 = 绑定系统名', (await sysCellText(SYS, 0)) === SYS);
  await page.screenshot({ path: OUT + '/systems.png' });

  // ---- H 时长型加天数 → 截止时间恰好 +10 天 ----
  await renewViaUI(durationKey, 10);
  await rowOf(durationKey).locator('td').nth(3).filter({ hasText: '~' }).waitFor({ timeout: 8000 });
  const detailAfter = await cellText(durationKey, 3);
  const before = parseDetailRange(detailBefore);
  const after = parseDetailRange(detailAfter);
  const diffDays = (new Date(after.end.replace(' ', 'T')) - new Date(before.end.replace(' ', 'T'))) / 86400000;
  check('H 截止时间 +10 天（起不变）', diffDays === 10 && after.start === before.start,
    detailBefore + ' -> ' + detailAfter);

  // ---- I 系统表使用统计 = 名下全部 key 合并日序列 + keyserver 侧对拍 ----
  const statsKey = await createKeyViaUI('count', 50);
  await consumer('/api/key/bind', { key: statsKey, machine_guid: GUID, system_name: SYS });
  await consumer('/api/key/validate', { key: statsKey, machine_guid: GUID, deduct: true });
  await consumer('/api/key/validate', { key: statsKey, machine_guid: GUID, deduct: true });
  await page.locator('#btn-refresh').click();
  await sysRowOf(SYS).locator('.stats').filter({ hasText: '共 2' }).waitFor({ timeout: 8000 });
  const statsLines = (await sysRowOf(SYS).locator('.stats span').allInnerTexts()).map((s) => s.trim());
  check('I 系统统计三行 均/峰/共', statsLines.length === 3
    && statsLines[0] === '均 2.0/日' && statsLines[1] === '峰 2' && statsLines[2] === '共 2',
    statsLines.join(' | '));
  check('I 系统行 key 数 2', (await sysCellText(SYS, 2)) === '2');
  const serverSys = (await systemsList()).find((s) => s.system_name === SYS);
  check('I keyserver 侧对拍 系统统计一致', serverSys && serverSys.usage_stats
    && serverSys.usage_stats.total === 2 && serverSys.key_count === 2,
    JSON.stringify(serverSys));

  // ---- I2 系统备注编辑弹窗：保存上屏 + 空串清除 ----
  await sysRowOf(SYS).locator('button[data-act=sys-edit]').click();
  await page.locator('#sys-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  check('I2 弹窗系统名只读回显', (await page.locator('#sys-name').innerText()) === SYS);
  await page.screenshot({ path: OUT + '/sys-modal.png' });
  await page.locator('#sys-remark').fill('验证-工厂');
  await page.locator('#btn-sys-save').click();
  await page.locator('#sys-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  await sysRowOf(SYS).locator('td').nth(1).filter({ hasText: '验证-工厂' }).waitFor({ timeout: 8000 });
  check('I2 备注保存上屏', (await sysCellText(SYS, 1)) === '验证-工厂');
  const serverRemarked = (await systemsList()).find((s) => s.system_name === SYS);
  check('I2 keyserver 侧备注持久化', serverRemarked && serverRemarked.remark === '验证-工厂');
  await sysRowOf(SYS).locator('button[data-act=sys-edit]').click();
  await page.locator('#sys-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  check('I2 重开弹窗回显既有备注', (await page.locator('#sys-remark').inputValue()) === '验证-工厂');
  await page.locator('#sys-remark').fill('');
  await page.locator('#btn-sys-save').click();
  await page.locator('#sys-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  // 空串无法用 hasText 过滤等待 → waitForFunction 等重渲染后备注格真为空
  await page.waitForFunction(
    (name) => {
      const tr = document.querySelector('#systems-body tr[data-name="' + name + '"]');
      return tr && tr.querySelectorAll('td')[1].textContent.trim() === '';
    },
    SYS,
    { timeout: 8000 },
  );
  check('I2 空串清除备注', (await sysCellText(SYS, 1)) === '');

  // ---- J 未绑定 key 直删（无弹窗；系统行不受影响） ----
  const rowsBefore = await rowCount();
  await rowOf(countKey).locator('button[data-act=del]').click();
  await rowOf(countKey).waitFor({ state: 'detached', timeout: 8000 });
  check('J 未绑定直删行消失', (await rowCount()) === rowsBefore - 1);
  check('J 直删无确认弹窗', await page.locator('#del-overlay').isHidden());
  check('J 未绑定删除不碰系统行', (await sysRowOf(SYS).count()) === 1);

  // ---- K 已用完直删（其使用统计随之消失，系统表回落） ----
  const exhaustedKey = await createKeyViaUI('count', 1);
  await consumer('/api/key/bind', { key: exhaustedKey, machine_guid: GUID, system_name: SYS });
  const deductResp = await consumer('/api/key/validate', { key: exhaustedKey, machine_guid: GUID, deduct: true });
  check('K node 侧扣至用完 200', deductResp.status === 200, JSON.stringify(deductResp.data).slice(0, 120));
  await page.locator('#btn-refresh').click();
  await rowOf(exhaustedKey).locator('.badge.bad').waitFor({ timeout: 8000 });
  check('K 属性 已用完（红徽标）', (await cellText(exhaustedKey, 4)) === '已用完');
  check('K 用过 最新使用时间 = 秒级时刻（validate_deduct 口径）',
    /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(await cellText(exhaustedKey, 5)),
    await cellText(exhaustedKey, 5));
  await sysRowOf(SYS).locator('td').nth(2).filter({ hasText: '3' }).waitFor({ timeout: 8000 });
  check('K 用完 key 入系统行（key 数 3，统计共 3）',
    (await sysCellText(SYS, 2)) === '3' && (await sysRowOf(SYS).locator('.stats').innerText()).includes('共 3'));
  await rowOf(exhaustedKey).locator('button[data-act=del]').click();
  await rowOf(exhaustedKey).waitFor({ state: 'detached', timeout: 8000 });
  check('K 已用完直删（无弹窗）', await page.locator('#del-overlay').isHidden());
  await sysRowOf(SYS).locator('td').nth(2).filter({ hasText: '2' }).waitFor({ timeout: 8000 });
  check('K 删除后统计回落 共 2', (await sysRowOf(SYS).locator('.stats').innerText()).includes('共 2'));

  // ---- L 正在使用 → 二段确认弹窗 → force 才删（系统行仍有 key 不消失） ----
  await rowOf(statsKey).locator('button[data-act=del]').click();
  await page.locator('#del-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  check('L 正在使用弹二段确认（含明文+绑定系统）',
    (await page.locator('#del-text').innerText()).includes(statsKey)
    && (await page.locator('#del-text').innerText()).includes(SYS));
  check('L 警示文案在场', (await page.locator('#del-warning').innerText()).includes('正在使用'));
  await page.screenshot({ path: OUT + '/delete-confirm.png' });
  await page.locator('#btn-del-confirm').click();
  await rowOf(statsKey).waitFor({ state: 'detached', timeout: 8000 });
  check('L 确认后 force 删除成功', (await rowOf(statsKey).count()) === 0);
  const serverGone = (await adminList()).find((k) => k.key_plaintext === statsKey);
  check('L keyserver 侧确已删', serverGone === undefined);
  check('L 系统行仍有 key 不消失', (await sysCellText(SYS, 2)) === '1');

  // ---- L2 级联：删掉系统名下最后一把 key → 系统行（含备注）随之删除 ----
  await consumer('/api/key/validate', { key: durationKey, machine_guid: GUID, deduct: true });
  await rowOf(durationKey).locator('button[data-act=del]').click();
  await page.locator('#del-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  await page.locator('#btn-del-confirm').click();
  await rowOf(durationKey).waitFor({ state: 'detached', timeout: 8000 });
  await page.locator('#systems-body tr[data-name]').waitFor({ state: 'detached', timeout: 8000 });
  check('L2 最后一把 key 删除后系统行消失', (await page.locator('#systems-body tr[data-name]').count()) === 0);
  check('L2 系统表回落空态提示', (await page.locator('#systems-body').innerText()).includes('暂无绑定系统'));
  check('L2 keyserver 侧系统表为空', (await systemsList()).length === 0);

  // ---- M 退出登录 / sessionStorage 持久自动登录 ----
  await page.locator('#btn-logout').click();
  await page.locator('#token-card:not(.hidden)').waitFor({ timeout: 8000 });
  check('M 退出后回登录框', await page.locator('#main').isHidden());
  check('M 退出清 sessionStorage', (await page.evaluate(() => sessionStorage.getItem('ms_admin_token'))) === null);
  await login(ADMIN_TOKEN);
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('#main:not(.hidden)').waitFor({ timeout: 8000 });
  check('M reload 免重输（sessionStorage 自动登录）', await page.locator('#main').isVisible());

  // ---- N key 表滚动容器 + 绑定系统名/属性 列过滤（US-009） ----
  // N1 造态：12 把未绑定次数 key + 1 把绑定中的时长 key（13 行 > 10 行触发滚动）
  for (let i = 0; i < 12; i++) {
    await fetch(KEYSERVER_URL + '/api/admin/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Token': ADMIN_TOKEN },
      body: JSON.stringify({ key_type: 'count', total_uses: 5 }),
    });
  }
  const filterKeyResp = await fetch(KEYSERVER_URL + '/api/admin/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': ADMIN_TOKEN },
    body: JSON.stringify({ key_type: 'duration', duration_days: 30 }),
  });
  const filterKeyCreated = await filterKeyResp.json();
  const filterBoundKey = filterKeyCreated.key_plaintext;
  const filterBoundKeyId = filterKeyCreated.id;
  await consumer('/api/key/bind', { key: filterBoundKey, machine_guid: GUID, system_name: SYS });
  await page.locator('#btn-refresh').click();
  await rowOf(filterBoundKey).locator('.badge.ok').waitFor({ timeout: 8000 });
  check('N 造态 13 行（12 未绑定 + 1 正在使用）', (await rowCount()) === 13, String(await rowCount()));

  // N2 滚动容器：限高生效（≤374px）且 13 行超出可视区；表头 sticky 常驻
  const scrollBox = await page.locator('.table-scroll').evaluate((el) => ({
    max: getComputedStyle(el).maxHeight, client: el.clientHeight, scroll: el.scrollHeight,
  }));
  check('N 滚动容器限高生效', scrollBox.max !== 'none' && scrollBox.client <= 374, JSON.stringify(scrollBox));
  check('N 13 行超出可视区（scrollHeight > clientHeight）', scrollBox.scroll > scrollBox.client, JSON.stringify(scrollBox));
  check('N 表头 sticky（滚动时列名常驻）',
    (await page.locator('.table-scroll thead th').first().evaluate((el) => getComputedStyle(el).position)) === 'sticky');
  await page.screenshot({ path: OUT + '/table-scroll.png' });

  // N3 属性过滤：类别带计数；只勾「正在使用」→ 1 行 + 计数行 + 漏斗高亮
  await page.locator('.th-filter[data-col=status]').click();
  await page.locator('#filter-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  check('N 属性弹窗标题', (await page.locator('#filter-title').innerText()) === '过滤：属性');
  const statusCats = (await page.locator('#filter-list .filter-item').allInnerTexts()).map((t) => t.trim());
  check('N 属性类别带计数（正在使用（1）/未绑定（12））',
    statusCats.includes('正在使用（1）') && statusCats.includes('未绑定（12）'), statusCats.join(' | '));
  await page.screenshot({ path: OUT + '/filter-modal.png' });
  await page.locator('#filter-list input[data-val="未绑定"]').uncheck();
  await page.locator('#btn-filter-apply').click();
  await page.locator('#filter-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  await page.waitForFunction(() => document.querySelectorAll('#keys-body tr[data-id]').length === 1, { timeout: 8000 });
  check('N 只剩正在使用 1 行', (await cellText(filterBoundKey, 4)) === '正在使用');
  check('N 计数行 当前显示 1 / 13', (await page.locator('#filter-count').innerText()).includes('1 / 13'));
  check('N 属性漏斗高亮 active',
    await page.locator('.th-filter[data-col=status]').evaluate((el) => el.classList.contains('active')));

  // N4 绑定系统名过滤：类别清单（（未绑定）殿后）+ 两列交集 + 重开回显 + 全选=清过滤
  await page.locator('.th-filter[data-col=sys]').click();
  await page.locator('#filter-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  const sysCats = (await page.locator('#filter-list .filter-item').allInnerTexts()).map((t) => t.trim());
  check('N 系统名类别（US008-VERIFY（1）+（未绑定）（12）殿后）',
    sysCats.length === 2 && sysCats[0] === SYS + '（1）' && sysCats[1] === '（未绑定）（12）', sysCats.join(' | '));
  await page.locator('#filter-list input[data-val=""]').uncheck();
  await page.locator('#btn-filter-apply').click();
  await page.locator('#filter-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  await page.waitForFunction(() => document.querySelectorAll('#keys-body tr[data-id]').length === 1, { timeout: 8000 });
  check('N 两列交集仍 1 行（绑定 key 同时满足两过滤）', (await cellText(filterBoundKey, 1)) === SYS);
  await page.locator('.th-filter[data-col=sys]').click();
  await page.locator('#filter-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  check('N 重开回显勾选态（（未绑定）仍不勾）', !(await page.locator('#filter-list input[data-val=""]').isChecked()));
  await page.locator('#filter-all').click();
  await page.locator('#btn-filter-apply').click();
  await page.locator('#filter-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  await page.waitForFunction(() => document.querySelectorAll('#keys-body tr[data-id]').length === 1, { timeout: 8000 });
  check('N 全选应用 = 清除该列过滤（属性过滤仍生效 1 行）', (await rowCount()) === 1);
  check('N 系统名漏斗回落非 active', !(await page.locator('.th-filter[data-col=sys]').evaluate((el) => el.classList.contains('active'))));

  // N5 全不选 → 0 命中空态；ESC 丢弃未应用勾选
  await page.locator('.th-filter[data-col=status]').click();
  await page.locator('#filter-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  await page.locator('#filter-none').click();
  await page.locator('#btn-filter-apply').click();
  await page.locator('#filter-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  await page.waitForFunction(() => (document.getElementById('keys-body')?.textContent || '').includes('没有匹配'), { timeout: 8000 });
  check('N 全不选 → 0 命中空态提示', (await page.locator('#keys-body').innerText()).includes('没有匹配'));
  await page.locator('.th-filter[data-col=sys]').click();
  await page.locator('#filter-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  await page.locator('#filter-list input[data-val=""]').uncheck();
  await page.keyboard.press('Escape');
  await page.locator('#filter-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  check('N ESC 丢弃未应用勾选（行数不变仍 0）', (await rowCount()) === 0);

  // N6 刷新剪枝：属性只勾「正在使用」→ 删光该类别 → 过滤自动回落全量
  await page.locator('.th-filter[data-col=status]').click();
  await page.locator('#filter-overlay:not(.hidden)').waitFor({ timeout: 8000 });
  await page.locator('#filter-all').click();
  await page.locator('#filter-list input[data-val="未绑定"]').uncheck();
  await page.locator('#btn-filter-apply').click();
  await page.locator('#filter-overlay').waitFor({ state: 'hidden', timeout: 8000 });
  await page.waitForFunction(() => document.querySelectorAll('#keys-body tr[data-id]').length === 1, { timeout: 8000 });
  await fetch(KEYSERVER_URL + '/api/admin/keys/' + filterBoundKeyId + '?force=true', {
    method: 'DELETE', headers: { 'X-Admin-Token': ADMIN_TOKEN },
  });
  await page.locator('#btn-refresh').click();
  await page.waitForFunction(() => document.querySelectorAll('#keys-body tr[data-id]').length === 12, { timeout: 8000 });
  check('N 类别删光后过滤剪枝回落全量 12 行', (await rowCount()) === 12);
  check('N 属性漏斗剪枝后回落非 active',
    !(await page.locator('.th-filter[data-col=status]').evaluate((el) => el.classList.contains('active'))));
  await page.screenshot({ path: OUT + '/filter-pruned.png' });
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

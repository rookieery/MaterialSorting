// 状态文件 US-003 冒烟（playwright，手动脚本不入 vitest；2026-09-11）：
//   1. 上传 5336 母版 → commit → 切超排 → 5s 短求解
//   2. 导出格式切「状态文件（.msn）」→ 底部说明行切换保存范围文案（不弹 ExportInfoModal）
//   3. 点导出 → 下载 .msn（文件名含「状态」+ 时间戳）+ StatusLine「已导出 …」
//   4. 回预览页上传该 .msn → toast「状态文件校验通过，恢复编排将在下一 Story 落地」
//   5. .dxf 原路径回归：重传 .dxf → parse+commit 正常
import { chromium } from 'playwright';

let browser;
try {
  browser = await chromium.launch({ channel: 'msedge' });
} catch {
  browser = await chromium.launch({ channel: 'chrome' });
}
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
await context.addInitScript(() => {
  localStorage.setItem('ms.tour.version', '7');
  localStorage.setItem('ms.tour.seen.preview', '1');
  localStorage.setItem('ms.tour.seen.nesting', '1');
});
const page = await context.newPage();
const log = (s) => console.log(s);
const fails = [];
const check = (ok, msg) => { log(`${ok ? 'PASS' : 'FAIL'} ${msg}`); if (!ok) fails.push(msg); };

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });

// ① 上传母版 → 自动 commit → 切超排
const fileInput = page.locator('input[type="file"]');
await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 60000 });
const nestingTab = page.locator('button.tab:not(.disabled)', { hasText: '超排' });
await nestingTab.waitFor({ timeout: 60000 });
await nestingTab.click();
await page.getByTestId('strategy-btn').waitFor({ timeout: 5000 });

// ② 5s 短求解：勾前两个码 + time=5 → #start → 等 done（#restart 出现 + 导出按钮解灰）
const sizeIds = await page.locator('.sizes .chip input').evaluateAll((els) => els.map((e) => e.id));
check(sizeIds.length > 0, `size chips present (${sizeIds.length})`);
for (const id of sizeIds.slice(0, 2)) await page.locator(`#${id}`).check({ force: true });
await page.locator('#time').fill('5');
await page.locator('#start').click();
await page.locator('#restart').waitFor({ timeout: 60000 });
await page.locator('.export-btns button.export:not([disabled])').waitFor({ timeout: 10000 });
log('2 solve done, export enabled');

// ③ 格式切「状态文件」→ 说明行切换 + 无 ExportInfoModal
await page.locator('.export-fmt').selectOption('state');
const hint = await page.locator('.export-group .dim.small').innerText();
check(hint.includes('保存母版快照') && hint.includes('不含导出表格手输字段'), `state hint switched: ${hint.slice(0, 30)}…`);

// ④ 点导出 → 下载 .msn
const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
await page.locator('.export-btns button.export').click();
const download = await downloadPromise;
const fname = download.suggestedFilename();
check(fname.endsWith('.msn'), `download filename .msn: ${fname}`);
check(fname.includes('状态'), `filename contains 状态: ${fname}`);
const savedPath = 'scripts/smoke-state-file-roundtrip.msn';
await download.saveAs(savedPath);
await page.waitForTimeout(1500);
const statusText = await page.locator('#status').innerText();
check(statusText.includes('已导出') && statusText.includes('.msn'), `StatusLine 已导出: ${statusText}`);
check((await page.locator('.strategy-modal').count()) === 0, 'no ExportInfoModal for state');

// ⑤ 回预览页上传 .msn → toast 校验通过
await page.locator('button.tab', { hasText: '预览' }).first().click();
await fileInput.setInputFiles(savedPath);
await page.waitForSelector('.toast-msg', { timeout: 15000 });
const toasts = await page.locator('.toast-msg').allInnerTexts();
const okToast = toasts.some((t) => t.includes('状态文件校验通过') && t.includes('下一 Story'));
check(okToast, `restore toast: ${toasts.join(' | ').slice(0, 60)}`);

// ⑥ .dxf 原路径回归：重传母版 → parse + commit 正常
await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 60000 });
check(true, 'dxf re-upload parse+commit ok (regression)');

await page.screenshot({ path: 'scripts/shot-state-file-final.png' });
await browser.close();
log(fails.length === 0 ? 'SMOKE PASS' : `SMOKE FAIL (${fails.length})`);
process.exit(fails.length === 0 ? 0 : 1);

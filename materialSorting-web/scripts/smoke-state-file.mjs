// 状态文件 US-003 保存 + US-004 恢复最小冒烟（playwright，手动脚本不入 vitest；
// 端到端全链路断言见 scripts/smoke_state_file.mjs）：
//   1. 上传 5336 母版 → commit → 切超排 → 5s 短求解
//   2. 独立保存区块（2026-09-12 入口改判：标题「保存当前方案状态（.msn）」+ 单
//      「保存」按钮，位于「导出最优方案」上方；此前为导出下拉 state 项）在场，
//      按钮状态与导出按钮一致（求解后均可点）
//   3. 点保存 → 下载 .msn（文件名含「状态」+ 时间戳）+ StatusLine「已导出 …」
//   4. 回预览页上传该 .msn → toast「状态文件已恢复…（含排料结果）」+ 自动切超排
//      Tab + run-provenance 来源小字「来源：普通求解 · seed 0」（WS 普通求解保存
//      不写 provenance 键 → 恢复端缺省 'solve' 口径）
//   5. .dxf 原路径回归：回预览页重传 .dxf → parse+commit 正常
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

// ③ 独立保存区块（2026-09-12 入口改判）：标题在场 + 按钮状态与导出按钮一致
const saveBtn = page.locator('[data-testid="save-state-btn"]');
const groupLabel = await page.locator('.save-state-group .field-label').innerText();
check(groupLabel.trim() === '保存当前方案状态（.msn）', `group label: ${groupLabel.trim()}`);
check((await saveBtn.textContent()) === '保存', 'save button label 保存');
// 求解 done 后导出按钮可点 → 保存按钮同口径可点（用户需求的状态联动）
await page.locator('.export-btns button.export:not([disabled])').waitFor({ timeout: 10000 });
check(!(await saveBtn.isDisabled()), 'save enabled (与导出按钮同口径)');

// ④ 点保存 → 2026-09-12 文件名弹窗（预填名称主体，无扩展名）→ 确认 → 后端补 .msn 下载
const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
await saveBtn.click();
await page.locator('[data-testid="save-name-overlay"]').waitFor({ timeout: 5000 });
const prefill = await page.locator('[data-testid="save-name-input"]').inputValue();
check(/_状态_\d{8}-\d{6}$/.test(prefill), `prefill default name (no ext): ${prefill}`);
await page.locator('[data-testid="save-name-confirm"]').click();
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

// ⑤ 回预览页上传 .msn → 恢复编排（US-004）：toast「状态文件已恢复（含排料结果）」
//    + 自动切超排 Tab + provenance 小字（WS 普通求解 → 恢复缺省 'solve' 口径）
await page.locator('button.tab', { hasText: '预览' }).first().click();
await fileInput.setInputFiles(savedPath);
await page.waitForSelector('.toast-msg', { timeout: 15000 });
const toasts = await page.locator('.toast-msg').allInnerTexts();
const okToast = toasts.some((t) => t.includes('状态文件已恢复') && t.includes('含排料结果'));
check(okToast, `restore toast: ${toasts.join(' | ').slice(0, 60)}`);
// 自动切超排 + 来源小字
await page.locator('[data-testid="run-provenance"]').waitFor({ timeout: 10000 });
const prov = await page.locator('[data-testid="run-provenance"]').innerText();
check(prov === '来源：普通求解 · seed 0', `run-provenance: ${prov}`);
// 恢复后求解 done 态（#restart 在场 = phase done，导出解禁）
await page.locator('#restart').waitFor({ timeout: 10000 });
await page.locator('.export-btns button.export:not([disabled])').waitFor({ timeout: 10000 });
log('5 restore applied (tab switched + provenance + done phase)');

// ⑥ .dxf 原路径回归：回预览页重传母版 → parse + commit 正常（恢复切走的 Tab 先切回）
await page.locator('button.tab', { hasText: '预览' }).first().click();
await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 60000 });
check(true, 'dxf re-upload parse+commit ok (regression)');

await page.screenshot({ path: 'scripts/shot-state-file-final.png' });
await browser.close();
log(fails.length === 0 ? 'SMOKE PASS' : `SMOKE FAIL (${fails.length})`);
process.exit(fails.length === 0 ? 0 : 1);

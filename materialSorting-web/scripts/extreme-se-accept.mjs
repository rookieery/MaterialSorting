// 极限运行 SE 顺延臂端到端冒烟（2026-09-20 US-002；模板 extreme-band-accept.mjs）：
//   1. 上传 5336 母版 → commit → 超排 Tab → 全选码号（默认数量 1/片/码）
//   2. 极限弹窗【新行为】：模式下拉在场且默认 race → 切 SE 顺延 → 说明行含
//      「warm 顺延」+ 轮数行切换「k 轮筛选 + 1 轮延长」（120min 默认档 = 21+1；
//      自定义 16 分钟 = 1+1）→ 切回 race 复原（19 轮期望口径）
//   3. SE 执行 → 202（请求体 strategy:'se'）→ 进度态：标题「极限运行」+
//      se 形态阶段行「第 1/1 轮 · seed 0 · 求解中」（k=1）+ se chips
//      （1 筛选 chip + → 分隔 + 延长待定条目，无门杀 ✕）
//   4. API 侧对拍：/api/extreme/status 载荷 mode='extreme' + strategy='se' +
//      plan.se {k_screens:1, screen_s:300, ext_s:600, warm:true}
//   5. 终止运行（冒烟不等待 960s 跑完）→ stopped 收口
// 环境前置：ms-web 已在 :8010（新代码），static/ 已 build。
import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE_URL ?? 'http://127.0.0.1:8010/';

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
const log = (s) => console.log(s);

try {
  await page.goto(BASE, { waitUntil: 'networkidle' });

  // 1. 上传 → parse → 自动 commit → 超排 Tab。
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles('../data/5336#老六订单14%7%围加9_coded.dxf');
  await page.waitForSelector('[data-testid="commit-status"].done', { timeout: 60000 });
  const commitText = await page.locator('[data-testid="commit-status"].done').innerText();
  const nestingTab = page.locator('button.tab:not(.disabled)', { hasText: '超排' });
  await nestingTab.waitFor({ timeout: 60000 });
  log(`1 commit ok: ${commitText.replace(/\s+/g, ' ')}`);
  await nestingTab.click();
  await page.getByTestId('extreme-btn').waitFor({ timeout: 5000 });

  // 全选码号（默认数量 → 每片每码 1 份）。
  const sizeIds = await page.locator('.sizes .chip input').evaluateAll((els) =>
    els.map((e) => e.id),
  );
  for (const id of sizeIds) {
    await page.locator(`#${id}`).check({ force: true });
  }
  log(`1b sizes checked: ${await page.locator('.sizes .chip input:checked').count()} of ${sizeIds.length}`);

  // 2. 极限弹窗：模式下拉默认 race → 切 SE 顺延（说明行 / 轮数行 / 回切复原）。
  await page.getByTestId('extreme-btn').click();
  await page.waitForSelector('.strategy-modal', { timeout: 5000 });
  const modeSel = page.getByTestId('extreme-mode');
  await modeSel.waitFor({ timeout: 5000 });
  if ((await modeSel.inputValue()) !== 'race') {
    throw new Error(`模式默认值非 race: ${await modeSel.inputValue()}`);
  }
  const raceRounds = await page.getByTestId('extreme-rounds').innerText();
  if (!raceRounds.includes('预计 19 轮') || raceRounds.includes('筛选')) {
    throw new Error(`race 臂轮数行异常: ${raceRounds}`);
  }
  await modeSel.selectOption('se');
  const desc = await page.getByTestId('extreme-mode-desc').innerText();
  if (!desc.includes('warm 顺延')) throw new Error(`se 说明行缺 warm 顺延: ${desc}`);
  const seRounds = await page.getByTestId('extreme-rounds').innerText();
  if (!seRounds.includes('预计 21 轮筛选 + 1 轮延长（warm 顺延）')) {
    throw new Error(`se 臂轮数行异常（120min 默认档应 21+1）: ${seRounds}`);
  }
  log(`2 mode ok: race「${raceRounds}」→ se「${seRounds}」`);
  // 自定义 16 分钟 → 1 筛 + 1 延；切回 race 复原。
  await page.getByTestId('extreme-preset-custom').click();
  await page.getByTestId('extreme-custom-input').fill('16');
  const seRounds16 = await page.getByTestId('extreme-rounds').innerText();
  if (!seRounds16.includes('预计 1 轮筛选 + 1 轮延长')) {
    throw new Error(`se 自定义 16min 轮数行异常: ${seRounds16}`);
  }
  await modeSel.selectOption('race');
  const raceRounds16 = await page.getByTestId('extreme-rounds').innerText();
  if (!raceRounds16.includes('预计 2 轮') || raceRounds16.includes('筛选')) {
    throw new Error(`race 自定义 16min 轮数行未复原: ${raceRounds16}`);
  }
  await modeSel.selectOption('se');
  await page.screenshot({ path: 'scripts/shot-extreme-se-config.png' });

  // 3. SE 执行 → 202（请求体断言 strategy:'se'）→ 进度态 se 形态。
  const startResp = page.waitForResponse(
    (r) => r.url().includes('/api/extreme/start'),
    { timeout: 15000 },
  );
  await page.getByTestId('extreme-exec-btn').click();
  const resp = await startResp;
  if (resp.status() !== 202) {
    throw new Error(`start 非 202: ${resp.status()} ${await resp.text()}`);
  }
  const body = await resp.json();
  const reqBody = resp.request().postDataJSON();
  if (reqBody.strategy !== 'se') throw new Error(`请求体 strategy 非 se: ${JSON.stringify(reqBody)}`);
  if (body.strategy !== 'se') throw new Error(`响应体 strategy 非 se: ${JSON.stringify(body)}`);
  log(`3 start 202: run_name=${body.run_name} pid=${body.pid} strategy=${body.strategy}`);

  await page.waitForSelector('[data-testid="strategy-progress-title"]', { timeout: 30000 });
  const title = await page.getByTestId('strategy-progress-title').innerText();
  if (!title.includes('极限运行')) throw new Error(`进度标题异常: ${title}`);
  // se 形态阶段行（k=1：第 1/1 轮筛选期）+ chips（→ 分隔 + 延长条目，无 ✕门杀）。
  // run_dir 发现 + strategy.json 落盘需数秒（commit 110 片）—— 轮询阶段行直到
  // 呈现「第 1/1 轮」（此前「启动中 · 定位 run 目录…」是正常时序）。
  await page.waitForFunction(
    () => /第 1\/1 轮 · seed \d+ · 求解中/.test(
      document.querySelector('[data-testid="strategy-stage"]')?.textContent ?? ''),
    { timeout: 90000, polling: 1500 },
  );
  const stage = await page.getByTestId('strategy-stage').innerText();
  const chips = await page
    .locator('[data-testid="strategy-seed-chips"] .strategy-chip')
    .allInnerTexts();
  if (!chips.some((c) => c.includes('延长'))) throw new Error(`se chips 缺延长条目: ${chips}`);
  if (!chips.some((c) => c.includes('→'))) throw new Error(`se chips 缺分隔条: ${chips}`);
  if (chips.some((c) => c.includes('门杀'))) throw new Error(`se chips 出现门杀条目: ${chips}`);
  log(`4 progress ok: ${title} | ${stage} | chips=${JSON.stringify(chips)}`);
  await page.screenshot({ path: 'scripts/shot-extreme-se-running.png' });

  // 4. API 对拍：status 载荷 strategy='se' + plan 的 se 计划段（se 键平铺在 plan 下）。
  const sid = await page.evaluate(() => localStorage.getItem('ms_sid'));
  const st = await context.request.get(`${BASE}api/extreme/status`, {
    headers: { 'X-Session-Id': sid },
  });
  const stBody = await st.json();
  if (stBody.mode !== 'extreme' || stBody.strategy !== 'se') {
    throw new Error(`status 臂字段异常: mode=${stBody.mode} strategy=${stBody.strategy}`);
  }
  const planSe = stBody.plan ?? {};
  if (planSe.k_screens !== 1 || planSe.screen_s !== 300 || planSe.ext_s !== 600) {
    throw new Error(`plan se 段异常: ${JSON.stringify(stBody.plan)}`);
  }
  if (planSe.warm !== true) throw new Error(`plan.warm 非 true: ${JSON.stringify(planSe)}`);
  log(`5 status ok: mode=${stBody.mode} strategy=${stBody.strategy} plan=${JSON.stringify(planSe)}`);

  // 5. 终止（冒烟不等待 960s；树杀 + stopped 收口）。
  const stopResp = await context.request.post(`${BASE}api/extreme/stop`, {
    headers: { 'X-Session-Id': sid },
  });
  const stopBody = await stopResp.json();
  if (!stopBody.stopped) throw new Error(`stop 失败: ${JSON.stringify(stopBody)}`);
  log(`6 stop ok: pid=${stopBody.pid}`);
  console.log(`SID=${sid}`);
  console.log(`RUN_NAME=${body.run_name}`);
} catch (e) {
  await page.screenshot({ path: 'scripts/shot-extreme-se-fail.png' }).catch(() => {});
  console.error(`FAIL: ${e.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}

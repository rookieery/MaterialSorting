# PRD: 运行完成态结果的 checkpoint 保全与恢复

## 概述 (Overview)

高级运行（strategy se/race）与极限运行（extreme）**运行完成（done）后、用户点「应用到主画布」之前**的结果，是会话过期恢复链路上唯一的丢失点：run 结束后仅剩 10 分钟终态宽限窗（`MS_RESULT_GRACE_SEC=600`），超窗回来走 checkpoint 刷新恢复时——工作台（母版/数量/已应用 run）恢复完好，但**待确认的完成结果不可达**（它从未进 `runRegistry`，checkpoint 载荷的 run 块不含它；新 sid 的策略状态槽为空；磁盘 run_dir 产物无 UI 认领路径），用户只能重跑数十分钟的长跑。

本功能在 statefile schema **additive 新槽 `pending_strategy_result`**：前端拉到 done 结果（确认前）即随 checkpoint 落快照，恢复编排把它**还原成可再确认的弹窗态**——重新打开对应族弹窗即见结果态，一键应用链路零改动。

**范围锚定（用户定案）**：只处理「完成」态。**运行中**不触发会话过期（alive hook 滚动钉住 + 轮询刷活性，既有机制）；**终止（stopped）**是人为操作，基本不会撞上自动过期——两态均明确不入案。

## 目标 (Goals)

- run 完成后用户离开、超 10 分钟宽限窗过期、刷新恢复：**完成结果随 checkpoint 保全**，恢复后弹窗重现结果态（密度/summary 与过期前一致），点「应用到主画布」得到与不过期路径**逐条一致的 placed 布局**——无需重跑。
- done 结果拉取落定的瞬间即入 checkpoint（不等去抖、不等用户操作），丢失窗口 ≈ 0；应用后槽退出、已应用 run 经既有 `markRunDone` 观察者入档（恰一份数据）。
- 全链 additive：无 pending 的载荷/快照/.msn 逐字节不变；schema v1 不 bump（省键式，`quantities_base` 先例）；后端无新路由、前端无新组件。

## 用户故事 (User Stories)

### US-001: 后端 `pending_strategy_result` 槽——构建/校验/守恒 + checkpoint·state-save 透传 + 恢复响应回传
- **Description**: As a 排料工程师, I want 保存/恢复/checkpoint 管线认识「待确认的完成结果」槽（省键式 additive），so that 前端把它随载荷带上即被快照与恢复端点原样回传，坏数据与 run 块同一套 fail-fast 拦截。
- **Acceptance Criteria**:
  1. `statefile.py`：`build_state_document(..., pending_strategy_result=None)` additive 参数（None → 整块省略）；槽形态 = `{mode:'se'|'race'|'extreme', best:{seed, frame_index, elapsed, density, density_sparrow, width_mm, placed_items}, summary:{...}}`——**manifest/run_dir 不入档**（恢复端 manifest 已由 `rebuild_session_from_document` 用 build_pid_meta 确定性重算并随响应回传，单份几何；run_dir 前端不展示；完成态无 warning 面）。
  2. `parse_state_document` 校验链增槽（在场时）：`mode` 枚举 fail-fast（400「状态文件损坏」，文案风格同 run 块）；`best.placed_items` 逐条形态与 `run.placed` **同一判据**（id 非空 str / rotation 有限数值 / translation [x,y] / mirror 可选 bool）；placed 全命中 doc.pieces + `check_placed_conservation` 守恒终检（form/quantities 同口径、同「内部不一致」文案）；`summary` 在场须为 dict（展示级宽松，`provenance.config` 同款不承重）；`best` 其余数值键有限数值。缺席 = 旧文件零迁移；`schema_version` 不 bump（v1 内未知顶层键忽略 = 老程序读新文件不炸）。
  3. `state_save` handler：body 增 `pending_strategy_result` 键（形态/守恒校验镜像 run 块分叉；守恒失败 → 400 与 run 块**同文案**「数量矩阵/尺码选择与当前结果不一致，请先重新求解或改回数量再保存」）；`_store_checkpoint`（checkpoint.py）同镜像：守恒失败 → `200 {stored:false, reason:'conservation'}` last-good（先前好快照字节不变）。
  4. `rebuild_session_from_document` 响应 additive `pending_strategy_result: document.get('pending_strategy_result') or None`——`/api/state-restore` 与 `/api/state-recover` 成功响应同形增益（共享函数免费）。
  5. pytest：`tests/test_web_statefile.py` / `tests/test_web_checkpoint.py` 增用例——带槽往返逐字段对拍 / 缺席省键 / mode 枚举必败 / placed 守恒必败（unknown_pid + count_mismatch 两款）/ checkpoint last-good / 恢复响应回传键；既有用例零回归。
  6. Python 模块可通过 `python -m materialsorting.web.statefile`、`python -m materialsorting.web.checkpoint` 跑通（`__main__` 冒烟各增带槽路径检查）、分层依赖未反向。
- **Priority**: 1

### US-002: 前端全链——result 拉取即落快照 + `resultApplied` 标记 + 恢复编排还原弹窗态
- **Description**: As a 排料工程师, I want done 结果落定瞬间即随 checkpoint 落快照、应用后自动退出该槽；过期刷新恢复（或 .msn 恢复）后待确认结果写回对应族 store 并自动打开弹窗落在结果态，so that 我看到「上次的运行结果还在等确认」，一键应用即可，不需要知道发生过期。
- **Acceptance Criteria**:
  1. `strategyStore.ts`（`createRunStore` 工厂，两族同改）：state 增 `resultApplied: boolean`（初值 false；`start`/`reset` 随 `result: null` 一起清）+ action `markResultApplied()`；`NestingPage.applyStrategyResult` 委托 `applySyntheticRun` 后按 result 归属族调用置位。
  2. `lib/stateFile.ts` `buildSavePayload` 增发 `pending_strategy_result`（省键式）：取两族 store 中 `result !== null && !resultApplied` 者（双族 409 单飞 ⇒ 至多一个在场），`best.placed_items` 经 `deepCopyPlaced` 深拷贝（载荷与 store 解耦既有约定）；`types/stateFile.ts` 对齐。
  3. `lib/sessionCheckpoint.ts` 触发面增订阅两族 store：`result` null→非空（done 结果落定 = 价值最高时刻）→ 立即 `flushCheckpoint`（不等去抖）；`resultApplied` false→true → 立即 flush（与 `markRunDone` 观察者 flush 经 `sendQueued` 合并天然一发）。既有五触发面不变（载荷发送时刻现取，pending 自然随行）。
  4. `applyRestorePayload` 增第 6 步：`res.pending_strategy_result` 在场 → 按 `mode` 路由（`'extreme'` → `useExtremeStore`；`'se'`/`'race'` → `useStrategyStore`）`setState`：`phase: 'done'`、`status: null`、`result: {state:'done', mode, run_dir: null, manifest: {…res.manifest}（恢复端重算值）, best, summary}`、`errorMessage: null`、`lastStart: null`、`resultApplied: false`；随后 `useControlPanelStore.getState().openModal(mode === 'extreme' ? 'extreme_run' : 'strategy_run')` 自动打开对应弹窗（写回为 store 直写，不依赖组件挂载时序；`.msn` 手动恢复与启动期恢复两条路径同享）。
  5. **idle 采纳守卫**（`strategyStore.refresh`，两族同改）：`st.state === 'idle'` 且 `get().result !== null && get().phase === 'done'`（恢复写回态）→ 不降级 phase——新 sid 后端状态槽为空、refresh 恒采纳 idle 会把恢复态打回 idle 抹掉弹窗结果态（[strategyStore.ts:157](materialSorting-web/src/store/strategyStore.ts#L157) 现行为），本守卫是恢复路径成立的必要条件；`result === null` 的 stuck starting → idle 既有恢复出口不变。
  6. 弹窗结果态完整可用：summary（race 门杀/se 筛延文案）、best 密度渲染与正常路径一致；「应用到主画布」走既有 `applyStrategyResult` **零改动**链路（清场 + `applySyntheticRun` + provenance；恢复后应用 → placed 与过期前 result 逐条一致 → `/api/edit-polish` 与 `/export` 正常）。
  7. vitest：拉取落定即 flush / applied 后载荷不含该槽 / 无 result 载荷无该键（旧口径对拍）/ 恢复写回字段对拍 / idle 守卫（恢复态 refresh 不降级、stuck starting 出口不变）/ mode 路由两族 / openModal 调用；`npm run build` 通过；通过浏览器验证恢复弹窗结果态 → 应用 → 布局渲染正确。
- **Priority**: 2

### US-003: 端到端集成验收 + 文档闭环
- **Description**: As a 项目维护者, I want UI 冒烟覆盖「跑完不确认 → 过期 → 刷新恢复 → 弹窗重现 → 应用 → 导出」全链并把槽契约写进文档，so that 本功能与既有会话恢复体系一起有回归守卫。
- **Acceptance Criteria**:
  1. 扩展 `materialSorting-web/scripts/smoke_session_recovery.mjs`（playwright 套路同既有）：极短 `MS_SESSION_TTL_SEC` 起 dev → 上传母版 → 启动策略 run（短预算）→ **不确认**、等 run 完成 + 宽限窗外过期 → 刷新 → 启动期恢复 → 断言：对应族弹窗自动打开且为结果态（密度与过期前对拍）→ 点应用 → 主画布 placed 逐条对拍 → 导出 PLT 守恒。
  2. 冒烟续段：极限运行同款路径；**应用后再过期**路径（应用 → 过期 → 刷新 → 恢复已应用 run、弹窗不开）；**run 中改数量未重解**路径（checkpoint last-good：恢复的是改前完整快照而非半态）；无 pending 老快照恢复行为对拍不变。
  3. 文档：`.docs/technical/agent-api-reference.md` 的 `/api/state-save`、`/api/state-restore`、`/api/state-checkpoint`+`/api/state-recover` 专节各补 `pending_strategy_result` 键（形态/省键/守恒语义/manifest 不入档理由/仅 done 态）；CLAUDE.md `statefile.py`/`checkpoint.py` 相关行补一句口径。
  4. 全量回归：后端 pytest 全绿、前端 vitest 全绿、`npm run build` 通过、既有 `smoke_state_file.mjs` 全绿（无 pending 路径对拍不变）。
  5. Python 模块可通过 `python -m materialsorting.web.statefile`、`python -m materialsorting.web.checkpoint` 跑通、分层依赖未反向。
- **Priority**: 3

## 功能需求 (Functional Requirements)

- FR-1: **仅 done 态结果入槽**：`result` 拉取落定（确认前）即随 checkpoint 落快照，触发 = store `result` null→非空，不等去抖；既有触发面发送时刻现取载荷自然携带。
- FR-2: 槽最小面 `{mode, best(含 placed_items 深拷贝), summary}`；manifest/run_dir 不入档（恢复端 manifest 确定性重算已有）；gzip 增量 ≈ 数十 KB，`MS_CHECKPOINT_MAX=16` 内存上限 ≈3MB→≈4MB 可忽略。
- FR-3: 应用后槽退出（`resultApplied` 置位）、已应用 run 经既有 `markRunDone` 观察者入档——恰一份数据，不重复存两份 placed。
- FR-4: 守恒复用 `check_placed_conservation`（best.placed_items vs demand）：checkpoint 失败 → `{stored:false, reason:'conservation'}` last-good；state-save 失败 → 400 与 run 块同文案。
- FR-5: schema v1 不 bump、省键式（缺席 = 旧口径）；老程序读新文件忽略未知键不炸。
- FR-6: 恢复响应（state-restore / state-recover 同形）additive `pending_strategy_result` 回传；`applyRestorePayload` 按 mode 路由写回对应族 store（`phase:'done'` + 常驻 result）+ 自动打开对应弹窗落结果态；恢复后再应用走既有 `applyStrategyResult` 零改动链路。
- FR-7: `refresh()` idle 采纳不降级「恢复写回的 done + 常驻 result」态；stuck starting → idle 既有恢复出口不变。
- FR-8: 恢复后再过期可再次恢复（恢复会话的 checkpoint 调度照常，未应用则槽再随载荷发出）——闭环无损。

## 非目标 (Non-Goals)

- **运行中态**——alive hook 滚动钉住 + 轮询刷活性，运行中不触发会话过期（用户定案，无丢失面）。
- **终止（stopped）态**——人为操作，基本不会撞上自动过期；槽内也无 `state` 字段（恒 done，结构从简）。
- 终态宽限窗延长 / 策略状态槽跨 sid 认领 / run_dir 磁盘产物 Web 认领——checkpoint 保全方向已定案，server 侧 `strategy.py`/`sessions.py` 零改动。
- provenance config 段跨恢复补全（`originOfStrategyResult` 的 lastStart=null 降级为既有注释承认的可接受行为，`NestingPage` 零改动）。
- 服务重启后恢复（checkpoint 纯内存语义不变，重启 = 兜底新会话 toast）。
- 停留期自动恢复 / 恢复后自动应用（应用永远是显式按钮；恢复只由刷新触发——既有用户定案）。
- WS 普通求解的「待确认」语义（WS final 直接进主画布，无确认弹窗环节）。

## 设计考虑 (Design Considerations)

- **恢复后自动打开弹窗**：恢复写回后 `openModal('strategy_run'|'extreme_run')`——用户上次离开时弹窗正处于待确认态，还原它最符合直觉且可发现性最好（入口徽标对 done 态不亮，仅 toast 提示易被错过）；toast「工作状态已恢复」保持既有文案。
- 弹窗内 summary/best 渲染、应用按钮互斥（主画布 running 禁用）等既有交互零改动——恢复只补数据源，不动组件。
- `.msn` 手动保存天然带该槽（单一 buildSavePayload 路径）：跨机传递后对方打开弹窗即可确认——语义自洽，不加开关。

## 技术考虑 (Technical Considerations)

- **分层**：后端仅动 `statefile.py` + `checkpoint.py`（web 兄弟模块 additive，无新文件/新路由/新 env）；前端动 `lib/stateFile.ts`、`lib/sessionCheckpoint.ts`、`store/strategyStore.ts`（createRunStore 工厂一处改两族）、`types/{stateFile,strategy}.ts`。
- **依赖方向**：`sessionCheckpoint → store` 订阅（lib → store 既有先例）；strategyStore 不反向 import sessionCheckpoint；`applyRestorePayload` 直碰 store 为既有先例。
- **双族单飞 ⇒ 至多一个槽**：槽为单对象非数组；两族 store 派生取在场者（mode 单值天然消歧，恢复按 mode 路由）。
- **恢复端 manifest 口径**：`rebuild_session_from_document` 的 `build_pid_meta` + `_form_gate_mm` 与策略 result 端点同源（start 快照 = 保存时 form/quantities），恢复弹窗应用的 manifest 与原 run 一致；run 期间改过数量的场景由 FR-4 守恒拦截（last-good 保住改前完整快照）。
- **gen 代际号**：恢复写回不经 `refresh()`/`start()`，直写 state 不受代际号影响；下一次 start 覆写全清（result/resultApplied/lastStart）。
- **信任模型**：与 .msn/checkpoint 既有口径相同（无鉴权 LAN 工具），不引入新面。

## 成功指标 (Success Metrics)

- [ ] 策略 run 完成不确认 → 超宽限窗过期 → 刷新：弹窗自动打开且结果态密度/summary 与过期前对拍 → 应用 → placed 逐条一致 → 导出 PLT 守恒（UI 冒烟断言）。
- [ ] 极限运行同款路径全绿（UI 冒烟）。
- [ ] 应用后再过期再恢复：只还原已应用 run，弹窗不开、无双份数据。
- [ ] run 中改数量未重解：checkpoint last-good（恢复改前完整快照）。
- [ ] 无 pending 的载荷/.msn/恢复路径逐字节/行为对拍不变（pytest + vitest + 既有冒烟全绿）。
- [ ] 后端 pytest 全绿 + `python -m materialsorting.web.statefile` / `checkpoint` 冒烟；前端 vitest 全绿 + `npm run build` 通过。

## 待确认问题 (Open Questions)

（2026-09-13 用户定案，全部关闭：）
- ~~恢复后自动打开弹窗？~~ → **定案：自动打开**（恢复写回后 `openModal('strategy_run'|'extreme_run')`，还原用户离开时的待确认态；不做 toast+徽标降级）。
- ~~该槽是否进手动 .msn？~~ → **定案：进**（单一 buildSavePayload 路径天然携带，跨机恢复同享；不剔除、不加开关）。

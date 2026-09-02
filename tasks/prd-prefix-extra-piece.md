# PRD: 起始端第一列顶部异码补片（prefix 近满幅优化）

> 依据：2026-09-02 规划会话（方案文件 `C:\Users\ASUS\.claude\plans\wiggly-percolating-marshmallow.md`，已逐点对齐代码现状）+ 用户生产参考件截图（幅宽 170 生产唛架第一列红框形态：下方 4 片同码 31 套装 + **顶部 1 片 32 异码片**，整列几乎占满门幅、片片相切）。姊妹先例：[prd-prefix-head-set.md](prd-prefix-head-set.md)（起始端成套前后幅 US-001~005，已落地——本 PRD 是其选码与形态的增强，大量复用既有构造/展开/钉位机制）。
>
> **需求核心**：在 prefix 组合片（第一列）**顶部新增 1 片其它尺码的前幅或后幅**，使「4 片套装（2前+2后同码）+ 异码片」竖排总高（Y 向，沿门幅）**尽量接近当前设置的幅宽 gate（只允许略小，不允许超）**；该近满幅约束**联合决定**套装尺码 A 与异码片（尺码 B≠A、前/后幅）的选取——取代现行 seeded 随机选码。异码片与套装最上面那片**刚好相切**（同款 `_slide_touch_y` 滑移贴触）。
>
> **v1 2026-09-02：三项开放问题全部决策入档（见「已决策」节）**——① 无可行组合退回现行 4 片套装；② 不设缝隙阈值、永远取最接近门幅者；③ 保留组合片 0°/180° 翻转自由度。

## 概述 (Overview)

把版师生产实践「布头第一列 = 完整一套前后幅 + 顶部再补一片异码前/后幅，整列近满幅」固化为选码语义升级：现行「2+2 资格码中 seeded 随机取一」升级为**联合几何搜索**——遍历 (套装码 A ∈ 资格码) × (异码片型 ∈ {前,后}) × (异码码 B≠A, demand≥1)，对每个组合构造性滑移贴触后取「5 片原始轮廓 union bbox 总高 ≤ gate 且最大」者为胜（确定性无 RNG）。**性质仍是业务规则（布头第一列形态的构造性保证），不是利用率优化器**——近满幅列把原 4 片列的残余缝隙（5336 实测约 522mm）升级为确定性的「整列近满 + 小残余交主解 NFP 填小片」形态。协议面零改动（9 键 config / WS payload / 前端 collectPrefix 均不加键），web WS / 策略 / 极限 / CLI 四入口经 solve_worker 单点自动继承。

## 目标 (Goals)

- 第一列形态对齐生产参考件：4 片同码套装 + 顶部 1 片异码前/后幅，整列总高 H 尽量接近 gate（H ≤ gate、残余 = gate−H 全候选最小），异码片与顶片贴触缝隙 ≤1mm（版师验收口径不变）。
- 选码确定性化：近满幅几何搜索取代 seeded 随机（兜底路径才用 seeded），多 seed 策略/极限跑下各 seed 组合恒同；预览与求解同函数 ⇒ 预览 = 求解精确形态（不再依赖 seed 对齐）。
- demand 守恒不破：异码片取 1 份进组合片、余量（N−1）照排主解，placed 条数 = 全量 Σdemand；pid_meta/total_area/manifest 逐字段不变（exclude 口径事故防线沿用）。
- `PS_*` 全链路零泄漏、prefix.py 分层纯度（禁 import web/cli）、`extra_pid=None` 与现行**逐字节一致**（既有测试零改动即回归红线）。

## 用户故事 (User Stories)

### US-001: prefix 核心选码搜索 + 顶部异码补片构造
- **Description**: As a developer, I want `materialSorting-server/src/materialsorting/nesting_engine/prefix.py` 把 `build_prefix_plan` 的成员放置循环抽为内部函数 `_place_members`（4 片路径逻辑不变），签名 additive 加 `extra_pid=None`（异码补片 pid），并新增 `select_prefix_plan(pid_meta, pieces_by_id, *, front_label, back_label, quantities, sizes, d_g, gate_nest, seed, order='interleave')` 联合选码函数 so that 「近满幅决定选码」有单一真相源，web 求解与预览共用。机制：补片 = 第 5 成员，同款候选 x 集合 {0, ub[0], ub[2]−w, pb[0], pb[2]−w} + `_slide_touch_y` 滑到与已占 union 首次贴触（eroded 碰撞口径），rot 遍历 `(0.0, 180.0)`（新常量 `EXTRA_ROT_CANDIDATES`，均严格顺布纹）取 union bbox 面积增长最小、平手取 0.0；记账同权威式 `tr=(xoff−b0, yoff−b1)`（rot180 负坐标补偿）；`chunk.pid` 追加 `+{extra_label}@{extra_size}`（如 `PS_g02+g03@34+g02@32`）。
- **Acceptance Criteria**:
  1. `extra_pid=None`：既有 `tests/test_prefix.py` 全部用例**零改动通过**（= 4 片构造逐字节回归红线）；补片路径：gaps 4 条全 ≤ GAP_EPS_MM=1.0（含补片↔顶片缝隙）、members 5 条、竖排高守卫 `H ≤ gate_nest` 沿用、rot180 补片记账单测锁死（镜像现行 form_and_rot180_accounting）
  2. `select_prefix_plan` 搜索语义：elig = `eligible_sizes(...)`（空 → PrefixError 现行文案）→ 逐 A ∈ sorted(elig) 跑 `_place_members` 基座（套装自身超高/贴触失败的 A 跳过）→ 补片候选池从 **pid_meta 派生**（label∈{front,back}、数字码、≠A、demand ≥ 1）→ 逐 (片型, B, rot) 滑移 → **H = 5 片原始轮廓 union bbox 高度**（与现行竖排高守卫同口径）→ 可行 = `H ≤ gate_nest + 1e-6` 且缝隙达标 → **取 H 最大者**，平手按 `(A 升序, front 先于 back, B 升序, rot 0 先)` 确定性裁决（全流程无 RNG）
  3. 兜底（用户定案①）：全无可行组合 → `pick_prefix_size(elig, seed, ...)` + 4 片 `build_prefix_plan`，与现行行为完全一致（含 PrefixError 语义），info.fallback=True
  4. 返回 `info = {'size': A, 'extra': {'pid','label','size','rotation'} | None, 'height_mm', 'residual_mm', 'fallback': bool, 'n_candidates': int}`
  5. 单测（`tests/test_prefix.py` 新 describe）：最优拟合选取（`_prefix_ctx(h_mul=...)` 造已知高度，set@A+front@B 恰 1975/1980 最小残差 → 断言 A/B/片型、members=5、第 5 成员在顶、贴触 ≤1mm、H ≤ gate、residual=gate−H）；候选池排除 B==A 与 demand<1；两可行组合取 H 大者；兜底 chunk 与现行 `pick_prefix_size`+`build_prefix_plan` 产物一致；5 成员展开黄金用例（offset 减号，镜像 `_hand_ps_chunk` 手算）；双跑确定性 `to_dict()` 全等
  6. 冒烟入口升级：`python -m materialsorting.nesting_engine.prefix` 打印候选表 + 选定组合 + residual（5336 真实 intermediate）；pytest 全绿、分层依赖未反向、AST 守卫（禁 import web/cli）不变
- **Priority**: 1

### US-002: demand 部分扣减 + worker/WS 接线（stage / final / 工件 / 验收器）
- **Description**: As a user, I want `web/solver.py` 的 `build_instance` 把 `exclude_pids` 升级为双形态（iterable[str] = 现行整 pid 跳过，逐字节不变；`Mapping[str, int]` = 每 pid 扣 n 份：`demand = meta['demand'] − n`，≤0 跳过；pid_meta/total_area/manifest 仍不动），`web/solve_worker.py` 的 `_build_prefix` 改调 `select_prefix_plan` 且 [solve_worker.py:136](../materialSorting-server/src/materialsorting/web/solve_worker.py#L136) 接线改 `Counter(m['pid'] for m in prefix_chunk.members)`，stage 消息 / `_prefix_record` 工件 additive 加 `extra_label`/`extra_size`/`residual_mm`/`extra`/`fallback`，`web/routes_ws.py` `on_stage` 键白名单（:319）加 3 键 so that WS solve 全链路支持 5 片前缀且异码余量照排。
- **Acceptance Criteria**:
  1. `build_instance` Mapping 形态：`{pid: n}` → Item demand=N−n、≤0 跳过；iterable 形态回归不变（单测双形态对拍）；pid_meta/total_area/manifest 逐字段不变
  2. worker 接线守恒：4 片时 Counter={front_A:2, back_A:2}（demand==2 → 0，与现行集合跳过等价）；5 片时异码 pid 扣 1、余量照排；**placed 条数 = 全量 Σdemand**（exclude 移除 2+2+1 份 + PS_ 展开 5 成员）
  3. stage 消息 additive：`extra_label`/`extra_size`/`residual_mm`（兜底路径 `fallback` 置 True，StageMsg 既有协议位）；`on_stage` 白名单透传新键；final 消息 prefix 段随 record 整体透传（含 `extra`/`residual_mm`/`fallback`）；prefix_runs 工件同字段落盘
  4. `PS_` 哨兵：manifest/frame/final 无 PS_（`_emit_placed` 展开单点不变）；`_finalize_prefix`/`permute_pin`/`reinsert_evicted`/`_recheck_layout` 全部长度无关零改动
  5. [prefix_accept.py:265,274](../materialSorting-server/src/materialsorting/web/prefix_accept.py#L265) `len(stack)==4`/`len(rows)==4` 放宽为 `in (4, 5)`（US-005 回放护栏兼容新形态）
  6. `tests/test_prefix_ws.py` 扩展全绿（stage 新键透传 / placed 守恒 5 成员版 / PS_ 哨兵）；prefix 缺省路径既有测试零改动通过；`ms-web` 启动无回归、分层依赖未反向
- **Priority**: 2

### US-003: /api/prefix-preview 换选码真相源 + 线程池 + 响应扩展
- **Description**: As a 版师, I want `web/routes_views.py` `prefix_preview`（:214-330）的构造段从 `eligible→pick→build` 换成 `select_prefix_plan`（与求解同一真相 ⇒ 预览 = 求解精确形态），并挪进 `await run_in_threadpool(...)`（选码搜索秒级，防阻塞事件循环——多会话 US-003 并发下主进程卡顿），响应 additive 加 `extra`/`residual_mm`/`gate_mm`/`fallback` so that 选码时刻就能看到 5 片近满幅形态与残余缝隙。
- **Acceptance Criteria**:
  1. 预览与求解同选：同 payload（含 seed 差异）下 preview 的 (A/片型/B) 与 `select_prefix_plan` 直调一致（确定性选码不再依赖 seed 对齐，docstring seed 说明同步改写）
  2. 构造段在线程池执行（事件循环不被秒级 shapely 搜索卡住）；会话解析仍在主线程先行（401/400 早退语义不变）
  3. 响应 additive：`extra: {label, size} | null`、`residual_mm`、`gate_mm`、`fallback`；members 列表天然带第 5 片（pid/size/color/tag/polygon 泛型，前端零改动即可渲染）；**不返回 PS_ pid** 哨兵不变
  4. 失败包络不变（200 + `ok:false`，band-preview 同约定）；`tests/test_prefix_preview_api.py` 扩展全绿（新字段 / 兜底形态 / 预览=求解对拍），既有用例兼容零改动
  5. 性能红线：5336 规模（~120 组合）preview 构造段实测 <5s（worker 路径一次性成本可忽略；超线再优化——rot0 先筛、缓存 pid×rot eroded 几何——优化不得改变确定性结果）
- **Priority**: 3

### US-004: 前端类型 + 状态行 + 预览放大层文案（全部 additive）
- **Description**: As a 版师, I want `types/ws.ts` `StageMsg` 加可选 `extra_label`/`extra_size`/`residual_mm`、`types/band.ts` `PrefixPreviewResponse` 加同名字段（`n_members` 注释「恒 4」→「4（兜底）或 5（补片）」）、`NestingPage.tsx` 状态行有补片时显示「起始端成套构造中（尺码 {size}＋{extra_label}@{extra_size}）…」、`PerTypeOverridesModal.tsx` 放大层文案（:964）有补片时追加「＋ 顶部 {extra_label}@{extra_size} 异码片 · 余 {residual}mm 近满幅」so that 我在求解与预览两处都能看到选定的异码组合。
- **Acceptance Criteria**:
  1. 协议向后兼容：新键全部可选，旧后端（无键）前端不炸、文案回落现行形态；字段缺席 = 兜底 4 片路径文案不变
  2. 预览缩略 5 片自动渲染（BandPreviewMember 泛型），异码片颜色 = `size_color(B)`（同码同色跨片型，A/B 两色一眼可辨）
  3. `params.ts` / `collectPrefix` / `ControlPanel` 闸门零改动（协议无新键）；`typecheck` 干净 + vitest 扩展全绿（NestingPage 状态行双形态 / PerTypeOverridesModal 文案双形态 / types 编译）+ `npm run build` 过
  4. **通过浏览器验证**：布局设置开 prefix → 预览缩略 5 片 + 放大层异码标注 → 求解状态行含异码码 → final 第一列形态目检（4 同码 + 顶异码、近满幅、相切）
- **Priority**: 4

### US-005: 端到端验收与文档闭环
- **Description**: As a 项目负责人, I want 5336 端到端冒烟（形态判据 + 守恒 + 导出）+ 文档同步 so that 异码补片以可证方式落地合入。
- **Acceptance Criteria**:
  1. 冒烟脚本 `scripts/smoke_prefix_extra.mjs`（模板 `smoke-band-preview.mjs` 套路）：上传 → 布局设置开 prefix → 预览 5 片 + 异码标注 → 求解 → 状态行 → 导出 PLT 无 `PS_`
  2. 形态判据：5 成员（4 同码 + 顶异码）、相邻贴触缝隙 ≤1mm、组合片 H 近满幅（residual 打点在案）、组合片 min_x ≤ 6mm 锚定（或置换钉位路径正常）
  3. 密度 sanity：同源短预算 on/off 对拍不显著劣化（≤1.0pt 线；本功能定位形态规则非优化器）；同输入双跑选码组合一致 + `chunk.to_dict()` 全等
  4. 文档：CLAUDE.md（prefix.py 条目 + 数据流主线 prefix 段）、README 起始端成套节、`.docs/business/起始端成套前后幅_版师确认清单.md` 追加 §9（异码补片需求 + 三项定案）、agent-api-reference（prefix-preview 响应 + on_stage 白名单）、agent-file-map、web/AGENTS、tests/AGENTS、memory 新条目（选码口径沿革）
  5. 全量门：后端 pytest 全绿 + 前端 vitest 全绿 + build 过；`python -m materialsorting.nesting_engine.prefix` 冒烟跑通、分层依赖未反向
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: 选码语义升级为**联合几何搜索**：近满幅约束（5 片总高 H ≤ gate 且最大化）决定 (套装码 A, 异码片型, 异码码 B≠A)；全无可行组合 → 退回现行 seeded 随机 4 片（用户定案 2026-09-02 ①）。
- FR-2: 异码片候选资格 = label ∈ {front, back} 且数字码且 ≠ A 且该 pid demand ≥ 1；取 1 份进组合片，余量（N−1）经 Mapping 形态 exclude 照排主解；候选池从 pid_meta 派生（sizes/quantities 过滤已内含，单一真相）。
- FR-3: 异码片置于套装顶部（局部 +Y 端），与顶片 `_slide_touch_y` 相切（缝隙 ≤ GAP_EPS_MM=1mm 同守卫）；rot ∈ {0,180} 择优（union bbox 面积增长最小、平手取 0.0），均严格顺布纹。
- FR-4: 可行性判据 H = 5 片**原始轮廓** union bbox 高度 ≤ gate_nest（与现行竖排高守卫同口径）；**不设缝隙阈值**，永远取最接近门幅者，残余缝隙交主解 NFP 填小片（用户定案 ②）。
- FR-5: 组合片主解朝向仍 `[0., 180.]`（用户定案 ③；180° 放置时异码片在列底，贴触/近满幅形态不变，版师 FR-5 决策③ 沿革）。
- FR-6: `build_instance` `exclude_pids` 双形态：iterable[str] = 整 pid 跳过（现行，逐字节不变）；`Mapping[str, int]` = 逐 pid 扣 n 份。pid_meta/total_area/manifest 逐字段不变（禁 quantities=0 口径事故防线沿用）。
- FR-7: stage / final / prefix_runs 工件 / prefix-preview 响应全部 **additive** 加 `extra_label`/`extra_size`/`residual_mm`（工件与预览另含 `extra`/`gate_mm`/`fallback`）；旧消费方零感知。
- FR-8: `extra_pid=None` 与现行逐字节一致（回归红线）；`PS_` 全链路泄漏哨兵与 prefix.py 分层纯度（禁 import web/cli）不变。
- FR-9: 确定性：搜索无 RNG（平手确定性裁决）；兜底路径保留 crc32 seeded 选码；策略/极限多 seed 下同一布局形态恒同码组合（run_stats class_key 的 prefix 组件仍 `'front+back'`，选码结果不进 class_key——与现行「选码不进 class_key」口径一致）。
- FR-10: 协议面零改动：9 键 config `_PREFIX_KEYS=('enabled','front','back')` 不变、WS StartPayload 无新键、前端 collectPrefix 无新键；web WS / 策略 / 极限 / CLI 四入口经 solve_worker 单点自动继承。

## 非目标 (Non-Goals)

- **多片补片 / 小件构造性填缝**：生产参考件顶部另有腰头小条填缝，属主解 NFP 自然填充范畴，不构造性钉死（残余缝隙正是留给主解的空间）。
- **缝隙阈值 / 手选异码码 UI**：不出 UI 惯例沿用（如版师后续要求指定异码码，加 config 键即可，协议向后兼容）。
- **组合片朝向锁 0°**（异码片恒在视觉最上方）：已定案保留 0/180 自由度，利用率优先。
- **补片形态的封闭腔（holes）设闸**：holes 只报告不拦截（现行 FR-10 口径）；真实数据若现腔体再议 tie-break。
- LNS frozen 片概念（PC-007 欠账，prefix 与 band 共同二期项不变）。
- 帧内额外工作：帧本就经 `_emit_placed` 展开 5 成员，天然支持，无独立帧任务。

## 设计考虑 (Design Considerations)

- 预览与求解同真相（`select_prefix_plan` 单一来源）；选码确定性化后预览不再依赖 seed 对齐（现行「界面恒单 seed=0 ⇒ 预览与求解同码」的 seed 说明随之改写）。
- 前端新键全部可选 + 字段缺席回落现行文案（旧后端兼容）；异码片颜色 = `size_color(B)` 同码同色跨片型，预览里 A/B 两色一眼可辨。
- 坐标系 `scale(1,-1)` 与导出三格式零改动：成员是普通 pid，PLT「尺码*数量」标注对异码片自动覆盖（各自尺码各自标注）。
- 状态行/放大层仅在字段在场时变化，不进 phase 五态状态机（stage 秒级提示惯例沿用）。

## 技术考虑 (Technical Considerations)

- **性能**：候选 ≈ 5 资格码 × 6 异码 × 2 片型 × 2 rot ≈ 120 次滑移（每次 ~10-30ms shapely）≈ 2-5s。worker 路径（求解前一次性）可忽略；preview 走 `run_in_threadpool`；实测 >5s 再优化（rot0 先筛、缓存 pid×rot eroded 几何、筛选与精算两段），优化不得改变确定性结果。
- **筛选与最终构造同路径**：`_place_members` 抽取复用（筛选期放置 == 终期放置，确定性），滑移贴触 eroded 口径 / H 原始轮廓口径与现行守卫完全一致；胜者只跑一次完整管线（union→`_solid_region` 焊接→erode(d_g)→clean→归一化）。
- **d_g 不变**：补片 label ∈ {front, back} 两 g 码，`d_g = max(d_front, d_back)` 天然覆盖（5336 均 d=2）。
- **exclude Mapping 语义与守恒**：exclude 移除 2+2+1 份 + PS_ 展开 5 成员 ⇒ placed 条数 = 全量 Σdemand（守恒口径单测锁）。
- **兜底逐字节等价**：兜底 = `pick_prefix_size` + 4 片 `build_prefix_plan`，与现行 worker/preview 产物一致（含 PrefixError 语义）；`extra_pid=None` 红线由既有用例锁。
- **补片 rot180 记账坑**：与成员同款 `tr=(xoff−b0, yoff−b1)` 补偿（P0 踩过的坑，单测锁死）；展开权威式 `tr_f = R(c.rot)·(m.tr − offset) + c.tr` 复用，5 成员黄金用例两朝向覆盖。

## 成功指标 (Success Metrics)

- [ ] 5336 冒烟：选定组合打印（A / 片型 / B / H / residual），H ≤ gate 且 residual 为全候选最小；补片贴触缝隙 ≤1mm（截图/输出在案）
- [ ] `extra_pid=None` 逐字节回归 + 既有 pytest / vitest 全绿（零改动通过）
- [ ] placed 守恒 = 全量 Σdemand（5 成员版）+ `PS_` 零泄漏（manifest/frame/final/前端/导出五处）
- [ ] 同输入双跑选码组合一致 + `chunk.to_dict()` 全等；策略/极限多 seed 组合恒同
- [ ] 预览 = 求解形态（同函数对拍）+ preview 构造段 <5s 且不阻塞事件循环
- [ ] on/off 短预算对拍密度不显著劣化（≤1.0pt 线，形态功能定位）

## 已决策（2026-09-02 用户确认，原 Open Questions 清零）

1. **兜底 = 退回现行 4 片套装**（所有「4 片套装+异码片」组合都超门幅时，不带异码片按现行逻辑构造，日志/状态提示剩余缝隙；不报错中止）。
2. **缝隙不设阈值**（可行组合永远取最接近门幅者，残余缝隙交主解 NFP 填小片——与生产件「大件定主体+小件填缝」一致）。
3. **保留组合片 0°/180° 翻转自由度**（异码片在顶/在底对裁剪对称等价，利用率优先；版师整列头尾调换认可沿革）。

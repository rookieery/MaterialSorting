# materialSorting-web — Agent 速查

> React 18 + TypeScript 5 + Vite 5 前端。改这里之前先看 `.docs/technical/agent-component-map.md`。

## 启动 / 构建 / 校验

```bash
npm install                # 首次装依赖
npm run dev                # :5173（strictPort 锁死）；需后端 ms-web 在 :8000 同步跑
npm run build              # tsc --noEmit && vite build → static/
npm run typecheck          # 仅类型检查
npm run test               # vitest run（US-002 起会有用例）
```

## dev/prod 路径

| | dev | prod |
| --- | --- | --- |
| 入口 URL | http://localhost:5173/ | http://127.0.0.1:8000/ |
| base | `/` | `/static/` |
| 后端调用 | 相对路径 `/export`、`/api/*`、`ws://${location.host}/ws/solve` → Vite proxy → :8000 | 同源直连 :8000 |
| 触发 WS 升级 | Vite proxy `ws: true`（**必填**） | 浏览器原生 |

## 关键约束（CLAUDE.md 引用）

1. **不引入 CSS 框架**：`style.css` 由 vanilla 前身迁入，沿用命令式 + 类名约定。
2. **坐标系 `scale(1,-1)`**：sparrow Y 向上 → SVG Y 向下，flipGroup 用 setAttribute 写 transform（避免 React reconciliation 覆盖）。US-003 落地。
3. **命令式 polygon 更新**：每帧 setAttribute('points' / 'display')，由 Zustand renderTick 单字段 ~10fps 节流，**逃逸 React reconciliation**。US-003 落地。
4. **`static/` 是构建产物**（US-008 起入库 gitignore）：`npm run build` 生成，**不要手改**；旧 vanilla 三件套（`legacy/`）已删除，React 应用是唯一真相源。

## US-032 关键约定（手动入口完善 + 关闭交互打磨 + 完整单测 调用方必读）

- **TabBar 下拉两项（replay-preview / replay-nesting，仅当前 Tab 可点）**：①「查看上传预览指引」→ `start('preview')`（强制重放，不检查 seen）；②「查看超排指引」→ `start('nesting')`。置灰规则：非当前 Tab 项 `.disabled` + `aria-disabled` + native `disabled` + handler 内 `if (disabled) return` 运行时兜底（与超排 Tab 解锁闸 US-015 同款多重防御）。**原③「重置全部指引」已移除**：close 统一 markSeen 后 reset 语义冗余（重看 = 菜单 force start，不检查 seen；seen 由关闭路径自动管理）。改任一 action 需同步 TabBar.test.tsx 菜单用例（含 `tour-menu-reset` 不存在断言）。
- **关闭交互三路径统一 markSeen（bug1 修复终态）**：① ESC → `close()`；② 遮罩 mousedown（`e.target===e.currentTarget`，参考 .piece-qty-dialog-overlay 模式）→ `close()`；③ 「跳过」按钮 → `skip()`。**任何关闭路径都 markSeen**（ESC/遮罩关闭属「我不想看了」语义，视为已读；否则 seen 仍 false → 切走再切回 Tab 会重复自动触发）。spotlight `pointer-events:none` 让点击穿透到 overlay → mousedown target=overlay=currentTarget → close；bubble `pointer-events:auto` 点击 target≠overlay → 不关闭。改语义需同步 TourOverlay.test.tsx 关闭用例。
- **`skip` 与 `close` 现同语义（markSeen+close）**：`close=markSeen(activeTour)+clearPolling+storeClose`；`skip=markSeen(activeTour)+clearPolling+storeClose`。skip 保留为气泡内显式可见入口；用户想重看用右上角菜单「查看 XX 指引」（force start，不检查 seen）。useTour 暴露 `skip()` 方法（US-032），TourOverlay 跳过按钮调 `tour.skip`。
- **prefers-reduced-motion 用 matchMedia 检测**：`useEffect` 内 `window.matchMedia('(prefers-reduced-motion: reduce)')`，`matches=true` 时 overlay 加 `.tour-reduced-motion` class，CSS 禁用 spotlight/bubble `transition: all 0.15s ease-out`（直接定位，无动画）。matchMedia change listener 跟随系统设置实时切换。改检测逻辑需同步 TourOverlay.test.tsx 2 项 reduced-motion 用例（mock matchMedia）。
- **scrollIntoView 在 readRect 前调**：useLayoutEffect 内先 `document.querySelector(selector)` → `el.scrollIntoView({block:'nearest'})` → 再 `readRect(el)` 读 post-scroll 的 getBoundingClientRect。避免目标在视口外时聚光灯贴到视口边缘外（目标 scrollIntoView 后 rect 在视口内）。`typeof el.scrollIntoView === 'function'` guard 防 jsdom 未实现。
- **readRect 改为接收 element**：US-029 `readTargetRect(selector)` 改为 `readRect(el)`（US-032），避免 useLayoutEffect 内 querySelector 重复调用（scrollIntoView 和 readRect 共享同一 element 引用）。
- **StrictMode 双 mount 幂等（参考 Tooltip.tsx registerTooltipEl 范式）**：所有 listener（resize/scroll capture / ESC keydown / matchMedia change）在 `useEffect cleanup` 中卸载；StrictMode 双 mount 下 add→cleanup→add 最终仅一套 listener（与 Tooltip.tsx 模块级单例 `_el` 同语义）。advance-on-ready effect 同理：polling interval 在 cleanup 中 clearInterval（US-030 useTour.test.tsx 测 5 覆盖 close 无残留）。before() 在 StrictMode 下调两次，需幂等（previewTour `ensurePreviewTab` / nestingTour `ensureNestingTab` 均 `if (activeTab!==target) setTab(target)` 幂等）。
- **版本号策略（TOUR_VERSION）**：仅步骤内容重大变更（增删步骤 / 改 ready 语义 / 改锚点导致旧 seen 语义失效）时 bump；文案小改 / 微调 placement 不 bump。bump 后 hydrateSeen init 检测 storedVersion!==TOUR_VERSION → 清全部 seen（US-029 已实现，US-032 补 3 项单测验证）。markSeen 同步写 version key（防 localStorage 部分清除后 re-hydrate 误清）。
- **不引入 CSS 框架**：`.tour-reduced-motion .tour-spotlight, .tour-reduced-motion .tour-bubble { transition: none !important; }` 沿用 style.css（与 .tour-spotlight/.tour-bubble 暗背景 #26282e + #2ea06c 同色系）。无其它新 CSS。
- **未做浏览器验证（chrome-devtools-mcp 不在本会话工具集）**：本 Story 无 SVG/坐标变换（仅 DOM overlay 关闭交互 + matchMedia + scrollIntoView + CSS class），核心逻辑用新单测覆盖（TourOverlay 6 项：ESC/遮罩/bubble/skip/reduced-motion×2；TabBar 9 项：菜单展开两项/两项 action/点外关/ESC关/toggle/置灰×2/点置灰兜底；useTour 2 项：skip markSeen+close / skip 从等待态清轮询；tourStore 3 项：version 同步写/bump 清 seen/resetSeen 不影响 version）。浏览器端到端回归留作整体回归。

## 文件分工（US-001 Tab 框架 + US-002~US-008 全部落地；上传预览 US-005 状态层 + US-006 UploadPanel + US-007 PiecePreviewSVG + US-008 容器集成 + 上传预览 US-011 qtyStore 数量状态 + 上传预览 US-013 PieceZoomModal 放大预览模态 + 上传预览 US-014 卡片头改造+模态集成 + US-015 uiStore 扩 nestingEnabled + TabBar 置灰 + US-016 PreviewPage 联动 setNestingEnabled + US-017 SizePicker 动态读码号 + DEFAULT_FORM.sizes=[] + US-018 PerTypeOverridesModal/PtypePreviewModal 高级配置弹窗+片型缩略图+放大预览 + US-021 useCommitToNesting 解析成功自动 commit+D1 闭环 + US-022 求解输入数量 demand per-size + US-024 NestSVG 5 层渲染+共享 LAYER5_COLORS + US-027 NestingPage phase 状态机+useSolveRun.stop()+running 态冻结参数编辑 + US-029 操作指引基础设施 tourStore+TourOverlay+useTour+TabBar 右上角入口 + US-030 previewTour 5 步+advance-on-ready+首次自动触发 + US-031 nestingTour 5 步+runRegistry 帧快照联动推进 + US-032 手动入口完善+关闭交互打磨+reduced-motion+scrollIntoView+完整单测 + 矩阵化重构 US-001 qtyStore 数据层简化（删 global 模式；PieceQuantity={perSize,baseValue}；setRowAll 整行填充；hydrate 单一入口；serializeQuantities 删 global 分支线格式不变）+ 矩阵化重构 US-002 QtyMatrix 数量矩阵组件（裁片×尺码矩阵）+ 矩阵化重构 US-003 拆除旧交互+预览页集成+全 0 拦截（SizeTabs/PieceQtyDialog/Switch 删除；uploadStore 删 qtyDialog；ParsedPiecesView 只读「N份」+区标题；ControlPanel 全 0 拦截）+ 矩阵化重构 US-004 parse 透传 ptype/paired+物理片数口径（parsed.ts 可选 ptype?/paired?；QtyMatrix ×2 徽章+物理口径小计；SizePicker.computeTotalCutPieces 同口径缺字段 ×1 兜底）+ 矩阵化重构 US-005 tour 锚点迁矩阵+文档同步（previewTour parsed/set-qty 锚点→QtyMatrix qty-matrix/qty-rowhead；TOUR_VERSION '1'→'2' bump；previewTour.test.tsx 新建 5 项）+ 裁片编号化重构 US-003 前端契约与显示层去名称化（2026-08-18：ParsedPiece 删 name/ptype/paired；V03_PTYPES 删→高级配置列集 = /api/ptypes reps 键动态；controlPanelStore previewPtype→previewLabel；QtyMatrix/SizePicker 小计/总片数 Σ 数量口径（配对 ×2 删）；PieceZoomModal/PtypePreviewModal 头部只显 g 码；NestSVG dataset.label + tooltip「g03 · 码28」；TOUR_VERSION '6'→'7'）+ 高级配置矩阵化 US-004 PerTypeOverridesModal 矩阵重构（2026-08-18：行=码号 × 列=g 码 矩阵、格=(g 码,码号) d/tol 双输入（空=继承默认）；per_type 两级嵌套 {label:{sizeKey:{d,tol}}} + perTypeSizeKey 单一口径；「≡」整列设值弹层（QtyMatrix 范式）；URL 分享 perTypeToUrlParam/perTypeFromUrlParam；三层独立 ESC）+ 高级配置矩阵回退（2026-08-18：US-004 矩阵化整体回退——per_type 收敛回单级 {g 码:{d,tol}}、弹窗回 列=g 码×2 行 d/tol、删「≡」整列设值/缺片格/URL 分享函数；后端 build_instance 同步回 label 单级命中） + 策略 PRD US-005 高级运行弹窗三态进度 UI（strategyStore/useStrategyPoll/StrategyRunButton/StrategyRunModal —— HTTP 轮询 /api/strategy/*，弹窗开 2s/关 15s；关闭三通道均不终止运行）+ 策略 PRD US-006 应用到主画布与导出闭环（NestingPage.applyStrategyResult —— 弹窗结果态显式按钮清场置换合成 RunRecord（manifest/frames 与 WS 消息同形），ExportButtons/useExport//export 导出链路零改动）+ 腰头成带 US-012 前端参数链路（FormState.band_* + collectBand 三态 + bandMemberCount 三态 + StartPayload.band 透传 + case stage 写 rec.stage/onStage 不 finish + NestingPage 状态行「腰头成带中」秒级提示）+ 腰头成带 US-013 弹窗布局设置 UI（PerTypeOverridesModal「布局设置」分区：成带勾选+腰头编号下拉（reps 动态值域+80×80 缩略图+fetch 失败降级）；ControlPanel band 启动闸门（未选编号/数量全 0 置灰+StatusLine 文案）+ band×策略互斥（strategy-btn disabled+title）；**2026-08-22 简化**：/api/band/preview 预演回显、ack 硬警告二次确认、US-015 填料混带、bandStore 单向镜像与 QtyMatrix「不成对」警告已整体删除 —— band = 勾选+选 g 码极简主流程，BandConfig 恰 {enabled,label}）。+ 起始端成套 US-004 前端参数链路+布局设置 UI（FormState.prefix_* + collectPrefix 三态 + prefixEligibleSizes 2+2 本地预检 + defaultPrefixLabels 面积预选（决策⑤）+ PrefixConfig/StageMsg 扩 'prefix' + useSolveRun prefix 透传 + PerTypeOverridesModal「起始端成套前后幅」勾选+前/后幅下拉（**2026-08-25 起下拉后挂组合形态预览缩略**——POST /api/prefix-preview：4 片同码 interleave 竖排 = 求解时 PS_ 组合片精确形态，band 预览同款三态 + prefix-zoom 第三层放大；前/后幅两张单片 80×80 缩略已删；无尺码下拉——资格码后端选定（2026-08-25 seeded 随机决策②；2026-09-02 起几何搜索））+ ControlPanel prefix 闸门/策略互斥 + NestingPage stage='prefix' 状态行「起始端成套构造中（尺码 N）…」（2026-09-02 起双形态：补片在案显「尺码 A＋g@B」））+ 多会话 US-005 前端会话接入与阻断弹窗（2026-08-27：lib/session.ts sid get-or-create + lib/api.ts apiFetch 全站统一 HTTP 出口（唯一裸 fetch 点）+ lib/ws.ts ?sid= + SessionExpiredModal 阻断弹窗 + App 挂载探测；8 处裸 fetch 全部换 apiFetch）。+ 起始端成套补片 US-004 前端类型+状态行/放大层双形态（2026-09-02 prd-prefix-extra-piece：StageMsg extra_label/extra_size/residual_mm + PrefixPreviewResponse extra/residual_mm/gate_mm/fallback 全可选、旧后端回落现行形态；5 片缩略自动渲染（n_members=5 补片）；params.ts/collectPrefix/ControlPanel 闸门零改动；vitest 810→815 + typecheck/build 过 + 浏览器 25/25；详见 .docs/technical/agent-component-map.md 同日补记）。

```
src/
├── main.tsx               # US-001：createRoot + StrictMode
├── App.tsx                # US-001 ✅ Tab 骨架：TabBar + 双 .page 容器（display:none 切换）+ Tooltip 单例；US-029 ✅ 加 TourOverlay 单例；**多会话 US-005 ✅ mount useEffect probeSession()（POST /api/session 探测，429/401 code → 弹窗）+ SessionExpiredModal 单例（TourOverlay 之后）**；**2026-08-31 ✅ 加 Toast 单例（全局轻提示，非阻断，z-index 1500；首个触发源 = 解析出 null 通用码）**
├── style.css              # 由 vanilla 前身 1:1 迁入；US-001 加 .tabbar/.tab/.page/.hidden/.preview-empty；上传预览 US-006 加 .upload-panel/.drop-zone/.upload-btn/.upload-status；US-007 加 .piece-preview-svg；US-008 加 .preview-page/.preview-main/.size-tabs/.size-chip/.parsed-pieces-view/.piece-grid/.piece-card*；上传预览 US-012 加 .piece-qty-dialog 族/.switch 族；上传预览 US-013 加 .piece-zoom-overlay/.piece-zoom-modal/.piece-zoom-head/.piece-zoom-seq/.piece-zoom-meta/.piece-zoom-name/.piece-zoom-close/.piece-zoom-body；上传预览 US-014 改 .piece-card-name→.piece-card-qty(+.disabled)；US-015 加 .tab.disabled(+hover)；US-018 加 .per-type-*/.ptype-* 族（US-004 矩阵增补样式已随 2026-08-18 矩阵回退删除：.per-type-rowhead 回 48px / .ptype-col 回 80px，.per-type-cell/.per-type-missing/--per-type 弹层 modifier 移除）；策略 PRD US-005 加 .strategy-* 族（wrapper/btn/badge/overlay+modal z-index 1100 #26282e/btn-exec/btn-apply #2ea06c/stop-btn #8a3b3b/big-density 36px/budget bar/seed-chips 四态 done#6cc79a killed#e08a8a running#2ea06c pending#666/result-head/warning #d9a05b/run-dir）；**后续删除**：矩阵化重构 US-003 删 .size-tabs/.size-chip/.piece-qty-dialog 族/.switch 族；图形预览区拆除删 .parsed-pieces-*/.piece-grid/.piece-card 系列（保留 .piece-card-label 供 PieceZoomModal 头部 g 码徽章）；矩阵行头简化删 .qty-rowname/.qty-paired-badge/.qty-reset-btn 族；裁片编号化 US-003 删 .piece-zoom-seq/.piece-zoom-name（v2 头部改 .piece-zoom-qty）；腰头成带 US-013 加 .per-type-band 族（title 左边框 #2ea06c / check accent / select / thumb 80×80；**2026-08-22 简化**：preview/ack/fillers/odd 相关类已删，仅保留该基础族）；起始端成套 US-004 加 .per-type-prefix-note（dim 11px 说明文案常驻）/.per-type-prefix-warn（#2a1c1c 底 #ff8888 红字警示，front==back / 无 2+2 资格码两态）；**2026-08-25 前缀组合预览**：加 .per-type-band-thumb--prefix（96×120 高缩略）/.per-type-band-thumb-empty--prefix（loading 骨架），删 .per-type-band-thumb:disabled（单片缩略删除后唯一使用者消失）；**编辑排料 US-002 ✅ 2026-09-04 加 .edit-layout-* 族（overlay z-index 1250 = ptype-preview 1200 之上 band-zoom 1300 之下 / modal 92vw×92vh 暗色 / canvas-tools 左上竖排 / save 绿主按钮 / svg touch-action:none）**
├── vite-env.d.ts          # vite/client 类型
├── types/                 # US-002 ✅：ws.ts / piece.ts / v03.ts；策略 PRD US-005 ✅ strategy.ts（/api/strategy/* 四路由响应 TS 镜像：七态 Phase / Status 除 state 全可选 / Result manifest 嵌套键 / race·se summary 判别联合）；上传预览 US-005 ✅ parsed.ts（US-001 v2 响应契约；裁片编号化 US-003 ✅ 删 name/ptype/paired —— label 即 g 码全链路主键）；上传预览 US-011 ✅ qty.ts（PieceQuantity/PieceQuantityMap）；US-027 ✅ solvePhase.ts（SolvePhase 五态）；腰头成带 US-012 ✅ ws.ts 扩 BandConfig{enabled,label}（2026-08-22 简化后恰两键）+ StageMsg + StartPayload.band?: BandConfig|null + ServerMsg 联合加 StageMsg；起始端成套 US-004 ✅ PrefixConfig{enabled,front,back}（无 size 键——资格码后端选定，2026-09-02 起几何搜索确定性）+ StartPayload.prefix? + StageMsg 扩 stage:'prefix'（size/holes 专属键回显；**起始端成套补片 US-004 ✅ 2026-09-02 additive** extra_label?/extra_size?/residual_mm? —— 补片 g 码/尺码/gate−组合片高，null 与键缺席同判=兜底 4 片，旧后端安全）+ band.ts PrefixPreviewResponse 同日扩 extra?{label,size}|null（只两键，PS_ 永不出端点）/residual_mm?/gate_mm?/fallback?，n_members 4（兜底）或 5（补片）
├── lib/                   # US-002 ✅ ws.ts；US-003 ✅ geometry.ts；US-004 ✅ params.ts（策略 PRD US-005 ✅ 加 collectStartContext：handleStart 与策略 start 载荷同源构造器，sizes/gate_mm/seed/params/per_type/quantities 逐字段同一实现；腰头成带 US-012 ✅ FormState 加 band_enabled/band_label + collectBand 三态解析（^g\d+$ 镜像后端，2026-08-22 简化后恰返回 {enabled,label}）+ bandMemberCount（missing→1/显式 0/未选码过滤三态，后端 demand 口径对齐）+ StartContext.band；US-006 ✅ seek.ts；US-007 ✅ download.ts；BAND_LABEL_RE export（弹窗共用）；起始端成套 US-004 ✅ FormState 加 prefix_enabled/prefix_front/prefix_back + collectPrefix 三态（关/开未选或 front==back 或非 ^g\d+$ → null；开且有效 → {enabled:true,front,back}）+ prefixEligibleSizes（2+2 资格码本地预检，与后端 _parse_prefix 同口径：missing→0 非 1、'null' 通用码跳过、sizes 过滤）+ defaultPrefixLabels（决策⑤默认预选 parse doc 每 label 最大码 polygon shoelace 面积前二；5336 = g02/g03）+ StartContext.prefix；**多会话 US-005 ✅ session.ts（sid get-or-create：localStorage 键 ms_sid，uuid4 hex 32 位（RFC4122 version/variant 位置位，Math.random 降级），模块缓存 + 非法落盘值重铸；clearPersistedSessionId 墓碑出口）+ api.ts（apiFetch 全站统一 HTTP 出口 = 唯一裸 fetch 点：注入 X-Session-Id + 会话先行门 ensureSession once-promise（防 mount 竞态 401）+ 401/429 code 拦截 → triggerSessionBlock；阻断期间抛 SessionBlockedError 请求不发出；mergeSessionHeaders 归一普通对象；markSessionProbedForTest/resetSessionForTest 测试钩子）**；ws.ts 多会话 US-005 ✅ solveWsUrl 拼 ?sid=（浏览器 WS 不能自定义 Header）
├── store/                 # US-002 ✅ runRegistry.ts（腰头成带 US-012 ✅ RunRecord 加 stage: StageMsg|null 信息记录，不影响 phase/done）；US-003 ✅ appStore.ts；US-001 ✅ uiStore.ts（US-015 ✅ 扩 nestingEnabled + setNestingEnabled + setTab guard）；上传预览 US-005 ✅ uploadStore.ts（US-012 扩 qtyDialog 已随矩阵化重构 US-003 删除；US-013 扩 zoom + open/close；US-021 扩 commitStatus/commitError/commitSummary + reset 同步清）；上传预览 US-011 ✅ qtyStore.ts（矩阵化重构 US-001 简化：perSize+baseValue 单模式 + setPiecePerSize/setRowAll/resetQuantities/hydrate + clampQty/getPieceDisplay 纯函数，hydrate 双入口已合并）；US-018 ✅ controlPanelStore.ts（modal + previewLabel 双显隐字段；US-003 起 previewPtype→previewLabel 键 = g 码；策略 PRD US-005 ✅ ControlPanelModalId 加 'strategy_run'；**编辑排料 US-002 ✅ 2026-09-04 加 'edit_layout' —— 有意偏离 ESC/遮罩关闭惯例（唯一关闭 = ✕/保存）**）；**编辑排料 US-001 ✅ 2026-09-04 editStore.ts（open 快照基线/save 原地保序写回/reset/invalidate/setWorkingItem + computeLayoutStats 单一真相源，详见文末「编辑排料 US-001/002 关键约定」）**；策略 PRD US-005 ✅ strategyStore.ts（phase 七态 + status/result/errorMessage/lastStart；start/stop/refresh/reset；refresh 唯一真相入口 + isStrategyState 守卫 + done/stopped 拉 result 每 run 恰一次；**代际号 guard**：start/reset bump，在飞 refresh 过期响应丢弃）；US-029 ✅ tourStore.ts（activeTour/stepIndex/seen + localStorage 持久化 + TOUR_VERSION 版本号强制重看）；**2026-08-31 ✅ toastStore.ts（全局轻提示队列：pushToast 追加（**同文案去重**）+ dismissToast ✕ 手动关 = **唯一出口，不自动消失**（同日修订：数据异常告知不能被错过；去重防重复触发叠条）；`__resetToastsForTest` 测试隔离）**；腰头成带 US-013 的 bandStore.ts 已随 2026-08-22 简化删除（band 状态只在 ControlPanel form，无跨页镜像）；**多会话 US-005 ✅ ptypeStore/strategyStore 的 apiFetch → 统一出口（fetch → apiFetch，其余逻辑零改动）**
├── hooks/                 # US-002 ✅ useSolveRun.ts（US-022 ✅ StartConfig 加 quantities 透传；US-027 ✅ 加 stop() + case stopped；腰头成带 US-012 ✅ StartConfig.band 透传 + case stage 写 rec.stage + onStage 回调 run 不 finish；**多会话 US-005 ✅ case 'error' 分支前置 code 检查：msg.code 为 session_expired/session_limit → triggerSessionBlock（WS 侧与 HTTP 同一阻断入口）**）；US-003 ✅ useRafThrottle.ts；US-007 ✅ useExport.ts；上传预览 US-005 ✅ useParseDxf.ts（US-021 ✅ 解析成功自动 void commit；**多会话 US-005 ✅ fetch → apiFetch**；**2026-08-31 ✅ 解析成功且 doc.sizes 含 null 通用码 → pushToast 提示检查母版命名**）；上传预览 US-021 ✅ useCommitToNesting.ts（POST /api/commit-to-nesting + D1 闭环 setNestingEnabled+setTab；**多会话 US-005 ✅ fetch → apiFetch**）；策略 PRD US-005 ✅ useStrategyPoll.ts（active 态 setInterval refresh：弹窗开 2s/关 15s 双档；mount+open 切换立即 refresh；terminal 停表 —— 全应用唯一挂载点在 StrategyRunButton）；起始端成套 US-004 ✅ StartConfig.prefix 透传（缺省 → WS 序列化 null）—— stage='prefix' 复用 case stage 通道（rec.stage + onStage，run 不 finish）
├── constants/             # US-004 ✅：sizes.ts / colors.ts / v03.ts
├── __tests__/             # US-002 ✅ useSolveRun；US-003 ✅ 各模块单测；US-007 ✅ useExport；US-001 ✅ App 集成 smoke（US-015 beforeEach 加 setNestingEnabled(true) 兜底 store guard）；策略 PRD US-005 ✅ strategyStore 7 项（含 reset 代际竞态回归）+ useStrategyPoll 5 项（fake timers 2s/15s 双档）；**多会话 US-005 ✅ useSolveRun WS ?sid=/error code 分支改写 + lib/__tests__/session.test.ts（uuid4 落库幂等/刷新不变/非法重铸/version+variant 位/clearPersistedSessionId）+ lib/__tests__/api.test.ts（Header 注入合并/会话先行门 once/401·429 拦截/swallow/幂等订阅/probeSession 三态/session_expired 弃 sid vs session_limit 保留）**
└── components/
    ├── TabBar.tsx         # US-001 ✅ 顶部 Tab（超排/上传预览），订阅 uiStore.activeTab；US-015 ✅ 超排 button disabled 闸（nestingEnabled===false 时 native disabled + .disabled class + aria-disabled + onClick 运行时判）；US-029 ✅ 右上角操作指引入口（margin-left:auto .tour-entry + 下拉菜单）；US-030 ✅ 超排 button 加 data-tour="tab-nesting"；US-032 ✅ 下拉菜单两项（replay-preview→start('preview') / replay-nesting→start('nesting')，仅当前 Tab 可点+置灰；原 reset 项因 close 统一 markSeen 已移除）+ 点外部/ESC 关闭 + toggle
    ├── NestingPage.tsx    # US-001 ✅ 排料页（原 App 业务逻辑外提；持 phase/seeds/useSolveRun）；US-027 ✅ solving→phase 五态状态机 + handleStop/handleRestart + lastStartCfgRef + running 态冻结参数编辑；US-031 ✅ .nest-wrap 加 data-tour="nest-wrap"（nestingTour step4 锚点）；策略 PRD US-006 ✅ applyStrategyResult（onApplyStrategy prop 链 → 弹窗「应用到主画布」显式按钮：registry 清场 + 合成单条 RunRecord + phase='done'；__tests__/NestingPage 5 项）；腰头成带 US-012 ✅ onStage → 状态行「腰头成带中：带内聚排…」（秒级提示不进 phase 五态状态机）+ handleStart 透传 cfg.band（useSolveRun.stop.test.tsx +2 项集成）；起始端成套 US-004 ✅ onStage 分支 stage==='prefix' → 状态行「起始端成套构造中（尺码 {size}）…」（size 回显后端选中的资格码——2026-09-02 起几何搜索确定性，前端无法预知）+ handleStart 透传 cfg.prefix（与 band 可同开）；**起始端成套补片 US-004 ✅ 2026-09-02 双形态**——extra_label/extra_size 在案 →「…（尺码 A＋g@B）…」（＋全角），兜底/无补片/旧后端回落现行形态（useSolveRun.stop.test.tsx +3：有补片/兜底 null/旧后端无键）
    ├── preview/           # US-001 起：上传预览页（矩阵化重构 US-003 ✅ QtyMatrix 接入 + SizeTabs/PieceQtyDialog/Switch 拆除；**图形预览区拆除：ParsedPiecesView 已删除，右侧主体仅 QtyMatrix**）
    │   ├── PreviewPage.tsx # US-008 ✅ 容器（左 UploadPanel + 右 QtyMatrix（图形预览区拆除后右侧唯一主体）；未解析空态）；US-014 ✅ 顶层模态单例（US-003 后仅 PieceZoomModal）+ useEffect subscribe 联动 qtyStore（doc→hydrate 默认 1+baseValue 1 / doc→null→resetQuantities）；US-016 ✅ 加 useEffect subscribe uploadStore.status 联动 uiStore.setNestingEnabled（`status==='done' && doc!==null` → true，否则 false；mount 即对齐）
    │   ├── UploadPanel.tsx # 上传预览 US-006 ✅ 左侧上传面板（点击+拖拽+客户端预校验+status 反馈）；US-021 ✅ 加 commit 状态行（committing→应用中… / done→已应用至超排：N 裁片 M 码 / error→应用失败：msg）
    │   ├── PiecePreviewSVG.tsx # 上传预览 US-007 ✅ 单片（或多片）母版预览 SVG（命令式渲染 + scale(1,-1) 翻转；US-018 ✅ compact prop 供矩阵/高级配置列头缩略图）
    │   ├── PieceZoomModal.tsx  # 上传预览 US-013 ✅ 放大预览模态（声明式受控 Portal；订阅 uploadStore.zoom+doc；✕/遮罩/ESC 关闭；复用 PiecePreviewSVG pad=20；US-003 起预览页唯一模态；**裁片编号化 US-003 起头部只显 [g 码徽章] {qty}份 · 码 {sizeLabel}（v2 契约无 name、无序号）**）
    │   ├── QtyMatrix.tsx       # 矩阵化重构 US-002 ✅ 数量矩阵（US-003 ✅ 接入 PreviewPage）：行=doc.sizes 全码（行头码按钮切 activeSize）× 列=label 并集[徽章+compact 缩略图+「≡」整列设值]（2026-08-16 转置）；格内 clampQty 编辑+Enter/Tab 跳格；0/.zero、缺片/—.missing、特例/.override 三态；sticky+flex 内滚；小计 US-003 起 Σ 数量口径（配对 ×2 乘数已删，一份=母版一个轮廓）+全 0 警示；腰头成带「不成对」警告已随 2026-08-22 简化删除（QtyMatrix 不再订阅 band 状态）
    │   └── __tests__/
    │       ├── UploadPanel.test.tsx      # 上传预览 US-006 ✅ 25 项集成测试（US-021 更新 2 项 fetch 计数 + beforeEach/afterEach 加 uiStore reset）
    │       ├── PiecePreviewSVG.test.tsx  # 上传预览 US-007 ✅ 38 项单测（33 项基础：bbox 纯函数 + 5 层渲染 + 翻转 + 标注 + 切片重建；US-018 ✅ compact 5 项）
    │       ├── PreviewPage.test.tsx      # 上传预览 US-008 ✅ 基础 + US-014 ✅ 联动 + US-016 ✅ 8 项 + 矩阵化重构 US-003 ✅ 改写 + 图形预览区拆除 ✅ 改写共 22 项（QtyMatrix 挂载+行头切码 / 模态仅 PieceZoomModal（qtyDialog 字段断言不存在）/ 端到端矩阵格子编辑 A@30=3→store+小计联动；弹窗与图形预览用例已删）
    │       ├── QtyMatrix.test.tsx        # 矩阵化重构 US-002 ✅ 38 项单测 8 组（转置后行=码号 × 列=g 码；裁片编号化 US-003 ✅ 配对/×2/物理口径用例全改写为 Σ 数量口径：行列结构/行头切码/缩略图 openZoom/格内编辑/0 特例高亮/整列设值 popover/小计与总片数 Σ 联动/全 0 警示）；腰头成带「不成对」警告 4 项已随 2026-08-22 简化删除
    │       └── PieceZoomModal.test.tsx   # 上传预览 US-013 ✅ 14 项集成（null 不渲染 / doc=null 不渲染 / overlay+modal+aria / 头部 label 徽章+qty(份)+sizeLabel（**v2 契约无 name，名称 span 断言不存在**）/ qty 从 qtyStore / null 码「通用」/ body svg.piece-preview-svg / ✕ closeZoom / 遮罩 closeZoom / modal 不冒泡 / ESC closeZoom / Portal body / label 不存在兜底 / size 不存在兜底）+ US-016 ✅ PreviewPage.test.tsx 增 8 项（mount idle→false / done→true / error→false / reset→false / 重传 doc_id 变化短暂 false 后 true / 关键不变量 setNestingEnabled(false) 不强制切 Tab / uploading→false / 状态机循环 done→uploading→error→done）
    ├── nests/             # US-003 ✅ NestSVG / NestCard / NestLabel；US-005 ✅ NestsGrid；US-006 ✅ NestSVG seek+hover；**编辑排料 US-002 ✅（2026-09-04）pieceDom.ts（5 层节点构建 SVGNS/PieceEntry/createPieceEntry 自 NestSVG 机械提取共用 —— NestSVG 与 edit/EditCanvas 同构同观感地基）**
    ├── edit/              # **编辑排料 US-002 ✅（2026-09-04）**：EditLayoutModal.tsx（受控 Portal 订阅 controlPanelStore 'edit_layout' + mount 自 bestRun() open 快照 + 状态条 computeLayoutStats 单一真相源（Δ 基线同 ceil 口径）+ **禁 ESC/遮罩关闭**（唯一关闭 = 右上 ✕ / 右下保存）+ 形态 select + 空态）；EditCanvas.tsx（命令式画布：working 下标 → 每下标一份 5 层节点（出现序）/ 指针锚缩放（world→user 换算）+ 空白平移 + ±重置 / 毛板 4 层隐藏可逆 / bg 跟随 viewBox + fab 世界锚定）
    ├── ControlPanel/      # US-004 ✅ 8 子组件；US-005 ✅ MultiSeedControls（**2026-08-22 seed UI 隐藏：组件删除、ControlPanel 不再渲染；FormState.seed/multi_seed/seed_count 保留恒默认 → 载荷恒 seed=0/seed_count=1，底层多 run 能力不动**）；US-007 ✅ ExportButtons；US-018 ✅ PerTypeOverrides 改按钮触发 + PerTypeOverridesModal（高级配置弹窗；**2026-08-18 回退 US-004 矩阵化：列=g 码 × 2 行 d/tol，per_type 单级 {g 码:{d,tol}}**；**2026-08-22 标题改「高级配置：设置算法参数」+ 裁片表格上方加「裁片设置」分区标题（.per-type-band-title 同款）**）+ PtypePreviewModal（片型放大预览）；US-031 ✅ 加 data-tour 锚点（doc-banner / start-btn 父容器 / param-form 在 SizePicker / export-group 在 ExportButtons）；策略 PRD US-005 ✅ StrategyRunButton（高级运行入口 + 运行中徽标 + 单例弹窗）+ StrategyRunModal（三态：配置四档时长+双模式 / 进度五件套+seed chips+终止 / 结果最优+用布+模式汇总+run_dir 复制+应用按钮（策略 PRD US-006 ✅ 已接线 —— NestingPage 经 ControlPanel 透传 onApplyStrategy；未传回调（测试挂载）才 disabled）+error 重试+orphan 清理；ESC/遮罩/✕ 关闭均不 stop；__tests__/StrategyRunModal 13 项（三态+五件套+SE 延长+载荷同源+关闭不终止）+ StrategyRunButton 4 项）；腰头成带 US-013 ✅ PerTypeOverridesModal「布局设置」分区（band {enabled,label} 二元组草稿+下拉/缩略图）+ ControlPanel band 启动闸门（未选编号/数量全 0 置灰+StatusLine 文案）+ band×策略互斥（StrategyRunButton disabled+title；**2026-08-22 简化**：预演/ack/填料/bandStore 镜像已删，BandFormValue 恰 {enabled,label}）；起始端成套 US-004 ✅ PerTypeOverridesModal「布局设置」第二行「起始端成套前后幅」（PrefixFormValue{enabled,front,back} 草稿+confirm 同 band 通道；勾上且两码均空默认预选 defaultPrefixLabels 面积最大两片；前/后幅下拉+**组合形态预览缩略**（2026-08-25：POST /api/prefix-preview 三态 + prefix-zoom 放大层，BandPreviewSVG 复用（member.tag 覆盖标注 = 前/后幅 g 码），替换两张单片 80×80 缩略）；说明文案「满足 2+2 的尺码将自动选取」；front==back / 无资格码两态警示——prefixEligibleSizes 本地预检不阻塞确定，权威拦截在后端）+ ControlPanel prefix 启动闸门（未选前/后幅 / front==back → #start 置灰+StatusLine 文案+handleStart 兜底；无资格码**不置灰**）+ prefix×策略互斥（strategy-btn disabled+title；与 band 本身可同开）；**起始端成套补片 US-004 ✅ 2026-09-02**——prefix-zoom 放大层 hint 双形态：preview.extra 在案追加「＋ 顶部 {label}@{size} 异码片 · 余 {residual_mm}mm 近满幅」（residual 缺席显 —），无键/兜底=现行 hint；5 片缩略自动渲染（BandPreviewSVG 泛型零改动，异码片 size_color(B) 同码同色跨片型；PerTypeOverridesModal.test.tsx +2）；**编辑排料 US-002 ✅ 2026-09-04 ControlPanel 挂 `<EditLayoutModal />` 单例（ExportInfoModal 旁；打开入口 US-004 EditLayoutControls 接）**
    ├── curve/             # US-005 ✅ ConvergenceCurve
    ├── playback/          # US-006 ✅ PlaybackBar / Seekbar / SeekReadout
    ├── SessionExpiredModal.tsx  # 多会话 US-005 ✅ 阻断式全屏模态（useSyncExternalStore 订阅 lib/api 阻断态；不可点遮罩/ESC/✕ 关闭，唯一出口 = 「刷新页面」按钮 location.reload()；COPY 双码文案与后端 PRD 逐字一致；z-index 3000 盖过 tour 2000）
    └── Tooltip.tsx        # US-006 ✅ Portal 单例 + showTooltip/hideTooltip/setHovered/clearHovered
├── tour/                 # US-029 ✅ 操作指引（onboarding tour）基础设施 + US-030 ✅ previewTour + US-031 ✅ nestingTour + US-032 ✅ 手动入口完善+关闭交互打磨
│   ├── types.ts          # US-029 ✅ Placement/TourStep/TourDef 类型（TabId 从 uiStore 复用）
│   ├── TourOverlay.tsx   # US-029 ✅ 高亮引擎（Portal body z=2000；spotlight box-shadow 镂空 + bubble placement 定位 + 零尺寸居中兜底 + useLayoutEffect imperative 定位）+ US-032 ✅ ESC/遮罩/skip 关闭 + reduced-motion class + scrollIntoView
│   ├── useTour.ts        # US-029 ✅ 控制器 hook + US-030 ✅ advance-on-ready 完整轮询 + useTourAutoTrigger（首次进 Tab 自动触发）+ US-032 ✅ skip()=markSeen+close
│   ├── steps/
│   │   ├── index.ts      # US-029 ✅ TOUR_VERSION='7'（'2'←矩阵化重构 US-005 锚点迁矩阵 / '3'←图形预览区拆除 / '4'←矩阵行头简化 / '5'←行级整行设值回归 / '6'←数量矩阵行列转置 / '7'←裁片编号化 US-003 Σ 口径；完整版本历史见文件头注释）+ TOURS: Partial<Record<TabId,TourDef>>（US-030 注册 preview / US-031 注册 nesting）
│   │   ├── previewTour.ts # US-030 ✅ 上传预览 5 步（upload/parsed/set-qty/committed/goto-nesting；联动步读 uploadStore/uiStore 快照）；矩阵化重构 US-005 ✅ parsed/set-qty 锚点迁矩阵（qty-matrix/qty-rowhead）+ 文案改矩阵操作描述（图形预览区拆除后不再指引图形预览区）
│   │   └── nestingTour.ts # US-031 ✅ 超排 5 步（doc-banner/params/solve/result/export；result/export 联动步读 runRegistry.list().some(r=>r.lastFrame!==null) 帧快照）
│   └── __tests__/
│       ├── TourOverlay.test.tsx # US-029 ✅ 5 项基础 + US-030 ✅ 1 项等待态 + US-032 ✅ 6 项（ESC/遮罩/bubble/skip/reduced-motion×2）
│       ├── useTour.test.tsx     # US-030 ✅ 5 项 + US-032 ✅ 2 项（skip markSeen+close / skip 从等待态清轮询）
│       └── nestingTour.test.tsx # US-031 ✅ 5 项（ready 无帧 false / 有帧 true / 5 锚点 query 到 / 5 步 id 序列 / 前 3 告知+后 2 联动）
```

## 上传预览 US-011 关键约定（qtyStore 数量状态 调用方必读；矩阵化重构 US-001 简化）

- **qtyStore 与 uploadStore 完全解耦**：qtyStore 只持 `quantities: PieceQuantityMap` + 4 actions（setPiecePerSize / setRowAll / resetQuantities / hydrate），不读 doc/activeSize；uploadStore 不持 quantities。重传联动由 PreviewPage 集成层 subscribe doc_id 变化：有 doc → `hydrate`（默认 1 + baseValue 1）、doc→null → `resetQuantities()`。
- **label 跨码匹配同一片型**：数量 map 以 label（**g 码 g01+**，裁片编号化 US-003 起取代 A/B/C）为 key，跨码语义同片型。依赖后端 `labeling.sequential_sort_key`（group_key 前置保跨码同号 + 几何稳定序）在码间稳定（M1787 结构款成立）。v2 契约已无 name 字段（去名称化删除，不存在「用 name 做 key」问题）。
- **`getPieceDisplay` 是 UI 消费的唯一入口**：三分支严格固定 —— （a）label 未在 map → `{qty:0, editable:true}`；（b）perSize 缺 sizeKey（=该码无此裁片）→ `{qty:0, editable:false}`；（c）正常 → `{qty: perSize[sizeKey] ?? 0, editable:true}`。qty=0 是显式「该码不排此片」，仍 editable=true（区别于缺片「—」）。QtyMatrix（US-002 起）/PieceZoomModal 都调此 selector，不直接读 quantities[label]。
- **`clampQty` 是数量值唯一规整入口**：`Math.max(0, Math.min(99, Math.trunc(Number(v) || 0)))`。负数/NaN/非数字→0；小数→截断（非四舍五入）；>99→99；字符串数字→对应整数。setPiecePerSize / setRowAll 内部统一走 clampQty，调用方传入原值即可。
- **baseValue 仅 UI 特例高亮基准，不参与序列化**：hydrate 写 1、setRowAll 写填充值、setPiecePerSize 新建 label 兜底 1 且格内编辑不动它。把 baseValue 混进 serializeQuantities 会污染 WS 线格式。
- **setRowAll 非破坏合并**：sizes 列表外的既有 perSize 键保留（整行填充只覆盖所列码）；value 经 clampQty 后同时写 perSize 与 baseValue。
- **hydrate 全量重建 + 单一入口**：旧 hydrateDefault/hydrateDefaults 双入口已删（grep 0）；每 (label,sizeKey)=1 且 baseValue=1，旧值整体替换。新增初始化路径一律走 hydrate，不再加第二入口。
- **null 码 sizeKey 口径**：`sizeKey(null)='null'`（perSize key 空间，与 number 区分）；人读「通用」文案由各组件自查（qtyStore 内 sizeLabel 已随 reason 删除）。
- **纯函数 + Zustand 便于测试**：clampQty / getPieceDisplay 是纯函数导出，单测直接调；store 通过 `useQtyStore.getState()` / `setState()` 同步可读可写，无需 React 渲染。单测全部纯函数/store 级，不挂组件。
- **不进 commit / 排料**：数量仅前端 store（WS start payload 经 serializeQuantities 序列化），不进 intermediate。

## 矩阵化重构 US-002 关键约定（QtyMatrix 数量矩阵 调用方必读）

> 裁片 × 尺码数量矩阵（一屏看全 + 格内直接编辑 + 整列设值 + 即时小计）。US-003 起已接入 PreviewPage（替代 SizeTabs；SizeTabs/PieceQtyDialog/Switch 已拆除）；图形预览区拆除后为右侧唯一主体；US-005 起承载 previewTour parsed/set-qty 两步锚点（根容器 data-tour="qty-matrix" + 行头 data-tour="qty-rowhead"）。

- **行列模型（2026-08-16 行列转置）**：**行 = `doc.sizes` 全码动态**（M1787 11 码 28-38，**勿按 8 码写死**；null 码殿后显示「通用」，无 null 码不渲染该行）[行头 = button `setSize(码)` 切 activeSize + 行尾小计列]；**列 = 全码 label（g 码）并集**（doc.sizes 升序遍历首次出现排序 = 最小码 pieces 顺序优先，后续码新增 label 追加尾部）[列头 = compact 80×80 缩略图（title 恒为 g 码）+ 序号徽章 +「≡」整列设值 icon]。每 render 从 doc 重算派生（piecesByLabel Map + labelOrder），doc 稳定引用 + ~10×12 规模不做 memo。
- **整列设值只写该 label 实际存在的码**：`setRowAll(label, rowSizes(label), value)`，rowSizes = 该 label 有片的码集；给缺片码写值会造 phantom perSize 键，污染 getPieceDisplay editable 语义与 serializeQuantities 输出（红线，qtyStore 测试「no phantom key」同步守）。ColFillPopover createPortal 到 body + fixed 居中矩形容器可视区（不锚 sticky 列头，防被盖/被 overflow 裁剪）。
- **格内编辑三提交路径**：blur / Enter / Tab，值一律过 clampQty 写 setPiecePerSize；草稿不实时 clamp（允许清空重输中间态），提交时统一规整。Enter 与 Tab 同语义：preventDefault 后手动 focusNextCell（`input.qty-cell-input:not([disabled])` 平铺顺序 + 末格回卷首格，跳过缺片格）。
- **React 18 事件 flush 时序坑**：synthetic「set value + input event + blur」放同一 JS task 会丢提交（onChange flush 晚于 onBlur 读到旧草稿）——集成测试与 CDP/浏览器驱动必须把 type 和 blur 拆成两个独立 task 派发。
- **草稿同步 focusedRef 守卫**：QtyMatrixCell 的 `useEffect([value])` 仅同步未聚焦格（行填充/重置等 store 侧外部变更进 DOM）；聚焦格保持用户草稿，blur 时草稿与 store 值一致则不重复写。
- **三态格子互斥可断言**：0 = 显式「该码不排此片」（`.zero` 暗色 + title + 可编辑，计入小计贡献 0）；缺片 = 该码无此 label（disabled「—」`.missing`，不计入小计）；特例 = `.override`（判定 `!rowAllSame && v !== base`，baseValue 缺席兜底 1；整行同值不高亮防噪点）。
- **行头即切码入口**：行头是 button，点击 `setSize(该码)`，activeSize 行 `.active`（US-003 起替代 SizeTabs；图形预览区拆除后语义收敛为「行头缩略图优先显示哪个码的版本」）。缩略图 rep 优先 activeSize 版本，点击 `openZoom(label, rep.size)`（**所见即所放大**，label 缺 activeSize 片时回退码也正常弹出；图形预览区拆除后预览页唯一放大入口）复用 PieceZoomModal。
- **小计 Σdemand 口径（本 Story）**：每码小计行 = Σ该行各 label demand（缺片格不计）；label 列小计 = Σ该列各码 demand；工具条总片数 = sizeSubtotals 之和；全 0 且有格 → 红色警示。**US-003 起 Σ 数量口径（无乘数）**——一份 = 母版一个轮廓，不合成镜像；三处小计同源只做求和。
- **CSS 布局不变量（行级整行设值回归 16855fd 重构）**：`.qty-matrix` flex:1 吃满 `.preview-main` 剩余高度（**拆掉旧 45vh 任意截断**）+ `.qty-matrix-scroll` flex:1/min-height:0；表格 `table-layout:fixed`（行头 148px / 合计列 56px 定宽钉死、尺码列 auto 均分富余）+ inline `min-width` floor（行头 148 + N×64 + 56px）窄屏自然横滚；sticky 表头/首列（.qty-rowhead）/底行（tfoot）+ `border-collapse: separate` 自绘边框（collapse 会吞 sticky 格边框）。缩略图 80×80。不引入 CSS 框架。
- **~~「重置为默认 1」按钮~~（已拆）**：工具条整表重置按钮已随矩阵行头简化（85b6a8c）拆除；整表回 1 = 逐列「≡」整列设值 1（值与 baseValue 双回 1，整列同值 → 特例高亮清空）。重建工具条级批量按钮前先确认与列级入口的交互分工。

## 上传预览 US-012 关键约定（PieceQtyDialog 数量弹窗 + Switch 调用方必读）

> **⚠️ 矩阵化重构 US-001 部分取代（2026-08-16）**：「全部尺码」global 开关（draftGlobal / Switch 用法 / global 初值）已随 qtyStore 删 global 模式移除，弹窗确定仅写当前码 setPiecePerSize；弹窗与 Switch 组件整体拆除在矩阵化重构 US-003。

- **草稿 + 确定模式（非即时生效）**：PieceQtyDialogInner 用 useState 持 `draftQty`；用户编辑仅改草稿；点确定才写 qtyStore（setPiecePerSize，仅当前码）；点取消 / 遮罩 / ESC 仅 `closeQtyDialog()`，草稿丢弃。
- **key 强制重建 PieceQtyDialogInner**：`key={`${label}-${size ?? 'null'}`}`；target 切换时（点卡片头切到另一片）Inner 重建，useState 重新从 store 读初值，避免 StrictMode 双 mount / 同 label 二次 open 时草稿残留。改 key 拼合需同步「初值」用例。
- **`PieceQtyDialog` 默认 return null**：`qtyDialog === null` 时返回 `null`（不挂 DOM）；打开时 Portal 到 document.body（与 Tooltip 同口径，不被父级 transform / overflow 影响）。改 Portal 目标会破坏 z-index 与定位。
- **初值严格走 `getPieceDisplay` selector**：draftQty 初值 = `getPieceDisplay(quantities, label, size).qty`。
- **ESC 监听在 Inner 组件挂/卸载**：Inner 用 `useEffect` 在 mount 时 `window.addEventListener('keydown', onKey)`、unmount 时 `removeEventListener`。dialog 关闭（target 切 null）时 Inner 卸载 → listener 自动清理，无残留。改监听位置会破坏生命周期同步。
- **遮罩 mousedown 用 `e.target === e.currentTarget`**：只在 mousedown 落在 overlay 自身（不是冒泡上来的子元素）时 onClose；modal 内任何点击不关闭。用 mousedown（不是 click）防止用户在 modal 内拖选文本时误关。
- **input blur 时 clamp 兜底**：`handleInputBlur` 调 `clampQty(e.target.value)`；type=number input 上下箭头 / 字符串粘贴可能写入超 99 / 非数字值，blur 时统一规整到 [0,99] 整数。
- **`[-]` 在 draftQty <= 0 时 disabled**：原生 button disabled（不响应点击 + 不参与 tab 序列），与 clampQty 下界 0 一致；`[+]` 不 disabled（clampQty 兜底 99）。
- **Switch 用原生 `<button disabled>` 兜底**：Switch props.disabled=true 时 button 自带 disabled 属性（不响应点击 + 不参与 tab 序列），`handleClick` 内 `if (disabled) return` 是双重防御。
- **uploadStore 扩 qtyDialog + open/close**：新增字段 `qtyDialog: {label:string; size:number|null} | null`（默认 null）+ actions `openQtyDialog(label, size)` / `closeQtyDialog()`；`reset()` 同步清 `qtyDialog=null`。store 公开 API 扩到 4 个（reset/setSize/openQtyDialog/closeQtyDialog）；hook useParseDxf 的 setState 流程**不写 qtyDialog**（弹窗显隐仅由 UI 触发）。
- **uploadStore.reset 联动 qtyStore.resetQuantities 留到 US-014**：本故事只扩 uploadStore.reset 清 qtyDialog（同 store 内）；qtyStore 独立 store 的 resetQuantities 联动（重传清零数量）由 US-014 ParsedPiecesView 集成时挂入。

## 上传预览 US-013 关键约定（PieceZoomModal 放大预览模态 调用方必读）

- **声明式受控 Portal（区别于 Tooltip 命令式单例）**：PieceZoomModal 订阅 `uploadStore.zoom + doc`；`zoom===null || doc===null` 时 `return null`（不挂 DOM）；打开时 Portal 到 document.body（与 PieceQtyDialog / Tooltip 同 Portal 目标，不被父级 transform / overflow / display:none 影响）。改 Portal 目标会破坏 z-index 与定位。区别于排料页 Tooltip 的命令式单例（Tooltip 用模块顶层 `_el/_hovered` + showTooltip/hideTooltip；模态低频声明式更合适）。
- **uploadStore 扩 zoom + open/close**：新增字段 `zoom: {label:string; size:number|null} | null`（默认 null）+ actions `openZoom(label, size)` / `closeZoom()`；`reset()` 同步清 `zoom=null`。store 公开 API 扩到 6 个（reset/setSize/openQtyDialog/closeQtyDialog/openZoom/closeZoom）；hook useParseDxf 的 setState 流程**不写 zoom**（模态显隐仅由 UI 触发，与上传解析无关）。
- **ESC 监听在 zoom 切换时挂/卸载**：`useEffect` dep `[zoom, closeZoom]`；`zoom===null` 时 effect 早 return（不挂 listener）；`zoom!==null` 时挂 window.keydown，cleanup 函数卸载 listener。zoom 切 null（关闭）时 effect 重跑 → cleanup → 自动卸载，无残留。**hook 必须无条件调（不能在条件分支里）**，故 zoom!==null 判定在 effect 内部（与 PieceQtyDialog 把 ESC 挂在 Inner 子组件不同：PieceQtyDialog 用 key 重建 Inner，本模态无 Inner 子组件故直接在主组件判 zoom）。
- **遮罩 onClick 用 `e.target === e.currentTarget` + modal stopPropagation 双重防御**：只在 click 落在 overlay 自身（不是冒泡上来的子元素）时 closeZoom；modal 用 `onClick stopPropagation` 双重防御（即使冒泡到 overlay 也已被 stop）。用 click（不是 mousedown）—— 与 PieceQtyDialog 用 mousedown 不同；本模态无可拖选文本场景，click 语义更直观。
- **`locatePiece` 防御性兜底渲染 null**：`doc.sizes.find(s=>s.size===size)` 找不到 → null；`pieces.findIndex(p=>p.label===label) < 0` → null。理论不会发生（openZoom 由 QtyMatrix 行头缩略图在已挂载矩阵上调，必然能定位；图形预览区拆除前也可由 ParsedPiecesView 卡片调），但兜底防御 doc 切换 race / 异常 store state。
- **头部结构（裁片编号化 US-003 起现行口径）**：`[g 码徽章 .piece-card-label] {qty}份 · 码 {sizeLabel(size)}`——qty 从 `getPieceDisplay` 读；**v2 契约无 name、无序号**（原「label 徽章 + 序号(数量) + name」三段头部已随去名称化改写，`.piece-zoom-seq`/`.piece-zoom-name` 节点与 CSS 均删）。aria-label=`裁片 ${label} 码 ${sizeLabel} 放大预览`。单位「份」= 一份母版一个轮廓（数量即一切，不合成镜像）。
- **数量从 `getPieceDisplay` 读（唯一 selector）**：头部 `{display.qty}份` 中 `display = getPieceDisplay(quantities, label, size)`，**不直接读 `quantities[label]`**（矩阵化重构 US-001 起 global 模式已删，selector 三分支）。
- **PiecePreviewSVG pad=20（比卡片默认 pad=14 加大留白）**：放大显示更多内边距视觉更舒适；pad 经 PiecePreviewSVG 内 `safePad = Math.max(MIN_PAD=4, pad)` clamp，20 安全。改 pad 需视觉回归核对（M1787 每片放大模态显示宽度 ≈ 90vw）。
- **头部 padding-right 28 给 ✕ 按钮留位**：✕ 按钮绝对定位 `top:8 right:10 + 28×28`；头部 `padding-right: 28` 防头部文本被按钮遮挡（v2 无 name 后仅 qty/码号短文本，保留留位稳妥）。改 ✕ 位置 / 头部 padding 需同步视觉回归。
- **uploadStore.reset 联动 zoom 清零（不联动 qtyStore.resetQuantities）**：本故事只扩 uploadStore.reset 同步清 `zoom=null`（同 store 内）；qtyStore 独立 store 的 resetQuantities 联动（重传清零数量）仍由 US-014 集成时挂入。本故事范围仅模态组件 + store 字段 + 单测，**不集成到 PreviewPage**（PreviewPage 顶层挂 PieceZoomModal 单例是 US-014 任务）。
- **不引入 CSS 框架**：`.piece-zoom-overlay` / `.piece-zoom-modal` / `.piece-zoom-head` / `.piece-zoom-qty` / `.piece-zoom-meta` / `.piece-zoom-close` / `.piece-zoom-body` 沿用 style.css 命令式 className（`.piece-zoom-seq`/`.piece-zoom-name` 已随 v2 头部改写删除），与 piece-card / piece-qty-dialog 暗背景 `#2a2c32/#26282e` + 绿色 `#2ea06c` 强调同色系。
- **未做浏览器验证**：本故事无 SVG/坐标变换改动（仅复用 PiecePreviewSVG 加大 pad，DOM 弹窗外壳），AC 仅要求 typecheck + 单测，故跳过 chrome-devtools-mcp；US-014 集成时再统一浏览器回归（含放大模态显隐 / ✕/遮罩/ESC / 头部信息）。

## 上传预览 US-014 关键约定（ParsedPiecesView 卡片头改造 + 双模态集成 调用方必读）

> **⚠️ 已被矩阵化重构 US-003 部分取代（2026-08-16）**：卡片头数量按钮（openQtyDialog 入口）改为只读 span「N份」（编辑入口统一 QtyMatrix）；PieceQtyDialog 单例已删（PreviewPage 仅余 PieceZoomModal）；序号(qty) 头部展示改到 QtyMatrix；**图形预览区拆除后 ParsedPiecesView 组件整体删除**。本节以下描述保留作历史记录，现行契约见「矩阵化重构 US-002/US-003」节。

- **卡片头双模态入口严格分离**：`.piece-card-qty`（在 head）点击 → openQtyDialog；`.piece-card-body`（SVG 包裹层）点击 → openZoom。两个交互入口由位置分离（head vs body 平级）+ stopPropagation 双重防御（qty button onClick 调 `e.stopPropagation()`，即使未来 qty 移到 body 内也不会冒泡触发 zoom）。改分离逻辑需同步 ParsedPiecesView.test.tsx「qty 不冒泡到 body」用例。
- **.piece-card-qty 双形态渲染**：editable=true（label 未配置 / per-size 模式 / global source 码）渲染 `<button class="piece-card-qty">`，点击 openQtyDialog；editable=false（global 非 source 码）渲染 `<span class="piece-card-qty disabled">`，不可点击 + native title 提供 hover 提示文案（reason=`'该数值已在「<sizeLabel(globalSource)>」处使用全局数量'`）。qty=0 正常显示 `序号(0)`（默认态）。改双形态分支需同步「editable button / global非source span.disabled / global source button」3 项用例。
- **序号 = pieces 数组 index+1（与 PieceZoomModal locatePiece.seq 同口径）**：ParsedPiecesView 用 `pieces.map((p, idx) => seq = idx+1)`；PieceZoomModal 用 `locatePiece` 内 `pieces.findIndex+1`。两者口径一致（A=1, B=2, ...），依赖后端 `_label_for` 几何排序在码间稳定。改 seq 口径需同步两个组件 + ParsedPiecesView 11 项用例 + PieceZoomModal 14 项用例。
- **.piece-card-body a11y 完整**：role=button + tabIndex=0 + aria-label=`放大预览裁片 ${label}` + onKeyDown(Enter/Space→openZoom)。与 UploadPanel drop-zone 同模式（键盘用户可用 Tab 聚焦 + Enter/Space 触发）。改 a11y 属性需同步「role+tabIndex / Enter / Space」3 项用例。
- **重传清零用 useUploadStore.subscribe（非 useEffect+ref 对比）**：PreviewPage useEffect 内 `let prevDocId = getState().doc?.doc_id` + `subscribe((state) => { if (state.doc?.doc_id !== prevDocId) { prevDocId = ...; resetQuantities(); } })`。**subscribe 捕获所有 state 变化**（包括不触发 re-render 的 setState），比 useEffect+ref 对比 doc 更可靠。subscribe 在 unmount 时 unsub（无残留）。改实现需同步「reset 联动 / 重传清 / 切码保留」3 项用例。
- **qtyStore 与 uploadStore 解耦（reset 联动在 PreviewPage 集成层）**：uploadStore 不知道 qtyStore 存在（reset 仅清自身字段 qtyDialog/zoom 等）；qtyStore 不知道 uploadStore 存在（resetQuantities 是独立 action）。**PreviewPage 作为集成层**用 subscribe 绑定两者。改耦合（如把 resetQuantities 调用挪到 uploadStore.reset 内）会破坏 store 解耦原则。
- **三路径区分**：reset（doc→null）+ 重传（doc_id 变化）触发 resetQuantities；切 activeSize（doc_id 不变）**不触发**（保留数量）。改分支需同步「reset 联动 / 重传清 / 切码保留」3 项用例。
- **顶层模态单例（声明式受控 Portal）**：PreviewPage 顶层挂 `<PieceQtyDialog/>` + `<PieceZoomModal/>` 各一个；两者默认 return null（qtyDialog=null / zoom=null），store 写入目标时自显隐。改挂载位置（如挪到 ParsedPiecesView 内）会破坏「单例」语义（每片卡片各挂一个会多实例 clobber）。Portal 到 document.body，DOM 位置与 React 树位置无关。
- **不引入 CSS 框架**：`.piece-card-qty`（透明底 + monospace + hover `#2ea06c`）+ `.piece-card-qty.disabled`（`#666` 灰字 + cursor:not-allowed）+ `.piece-card-body cursor:zoom-in` 全部沿用 style.css 命令式 className。`.piece-card-name` 已删除（不再使用）。改 className 需同步组件 + 测试。
- **未做浏览器验证（无 SVG/坐标变换）**：本故事无 SVG 渲染、坐标变换、可视化逻辑改动（仅卡片头 DOM 结构 + 模态挂载 + 点击处理 + CSS），AC 仅要求 typecheck + 单测 + build；浏览器验证留作整体回归。

## US-005 关键约定（上传预览状态层 调用方必读）

- **状态机：idle → uploading → done | error（任一终态可 reset 回 idle）**。status 是 UploadPanel 渲染分支的唯一驱动：uploading 显示加载态、error 显示红字、done 显示文件名 + 码数概览。改状态名 / 增状态需同步 uploadStore.test.ts 7 项 + useParseDxf.test.tsx 15 项。
- **uploadStore 是单一真相源**：与 runRegistry（高频 mutable，不进 state）相反，uploadStore 把 doc/activeSize/error 全部进 React state —— 解析结果低频，进 store 触发 reconciliation 反而便于 UI 同步。新增字段需在 uploadStore + reset() + useParseDxf setState 三处同步。
- **状态过渡（uploading → done | error）由 useParseDxf 直接 `useUploadStore.setState({...})` 写入，不暴露成 store 公开 action**。store 公开 API 只含调用方语义动作（reset / setSize），避免业务组件误触发状态跳变。
- **防连击：uploadingRef + status==='uploading' 双重防护**。ref 立即生效（async 函数体同步段执行）；setState 异步生效，第二次连击会在 setState 调度前进 hook body。两者任一为 uploading 即忽略。改单重防护会回归「连击两次同时 fetch → 后写入者覆盖前者 doc」问题。
- **FormData 不手设 Content-Type**：fetch 自动加 `multipart/form-data; boundary=...`，手设会丢 boundary → 后端 python-multipart 解析失败。useParseDxf.test.tsx AC#1 有断言。
- **响应契约字段名严格与 server.py `_build_parse_payload` 一致**：`{doc_id, filename, sizes:[{size, pieces:[{label, polygon, internal_lines, notches, net_polygon, grain_line}]}]}`（US-001 v2 起 name/ptype/paired 全删，label = g 码；数量一律走前端 quantities）。改任一字段需同步后端 server.py + types/parsed.ts + useParseDxf.test.tsx AC#2。
- **activeSize 默认 = doc.sizes[0].size ?? null**：后端按数值升序、null 殿后，sizes[0] 是最小码。空 sizes 兜底 null，UI 自然显示空态。改默认需同步 useParseDxf.test.tsx 3 项 activeSize 用例。
- **错误不抛、不 rethrow**：useParseDxf 内 try/catch 兜底，所有错误（网络错 / JSON 解析错 / 4xx/5xx）统一进 uploadStore.error，UI 自取。返回 Promise<void> 仅为调用方可选 await（如「上传完成后再切 Tab」）。
- **doc / activeSize 在失败时不主动清**：uploading 时清 error 但保留 doc/activeSize（避免切 uploading 时 UI 闪烁）；error 时也只写 status/error，让用户能看到上一次成功的预览（可选 UX，由 UI 决定是否隐藏）。reset() 才彻底清零。
- **fetch URL 是相对路径 `/api/parse-dxf`**：dev 由 Vite proxy 转 :8000，prod 同源；与 useExport fetch('/export') 同口径，前端代码 dev/prod 完全一致。

## 上传预览 US-006 关键约定（UploadPanel 调用方必读）

- **整个 `<aside>` 是拖拽落区，点击触发限定在 drop-zone / button 上**：dragenter/dragover/dragleave/drop 挂在根元素（用户可落在 panel 任何子元素上松手），但点击触发文件选择只绑 drop-zone 和 upload-btn（避免点状态文本误触）。改挂载点会破坏 panel-wide DnD 语义。
- **dragCounter 防子元素 dragleave 抖动**：浏览器在 panel 子元素间移动会反复触发 dragenter/dragleave，用 ref 计数器保证只在真正离开 panel（counter=0）时清 `.dragover`。直接 toggle boolean 会因抖动出现 `.dragover` 闪烁。改实现需同步 UploadPanel.test.tsx 4 项 DnD 用例。
- **客户端预校验三件套：.dxf 后缀（MIME 容错）+ 单文件 + 20MB**：后缀判定用 `name.toLowerCase().endsWith('.dxf')`（不看 file.type，Windows 下 MIME 五花八门）；多文件 / 超大直接拦不发请求；20MB 与后端 `server.py UPLOAD_MAX_BYTES` 一致（前端先拦 + 后端兜底）。改任一项需同步 UploadPanel.test.tsx 4 项 reject / 通过用例。
- **`localError` 与 `store.error` 互斥展示（本地优先）**：客户端校验失败消息进本组件 `useState`，不污染 uploadStore 状态机（hook 仅在 HTTP 流程内切 status）；UI 渲染分支 `displayError = localError ?? (status==='error' ? store.error : null)`。改优先级会破坏错误展示口径。
- **`e.target.value = ''` 重置 input value**：否则选同一文件不触发 change（input value 去重机制），用户重试同一文件会哑火。UploadPanel.test.tsx AC#2 有断言。
- **状态驱动 UI 分支**：uploading 显示 `.upload-status.loading` + 按钮文案切「重新上传」+ disabled；done 显示文件名 + 「已解析 N 码 / M 裁片」（N=doc.sizes.length，M=sum(pieces.length)）；error 显示红字（来自 store.error 或 localError）；idle 不渲染 status 块。改分支需同步 UploadPanel.test.tsx AC#3 9 项用例。
- **drop-zone + upload-btn 双入口触发同一 handlePickClick**：不直接绑到 input.change，而是 click → inputRef.click() → input.change，便于 DnD 与点击共享校验/上传路径（drop 直接进 handleFiles 跳过 input click）。改单一入口会破坏双交互模式。
- **不引入 CSS 框架**：`.upload-panel` / `.drop-zone` / `.upload-btn` / `.upload-status` 全部沿用 style.css 命令式 className，与 ControlPanel 暗背景 `#26282e` + 绿色 `#2ea06c` 强调同色系；新增 `.drop-zone.dragover` 用绿色边框高亮。
- **jsdom 缺 DragEvent / DataTransfer，需手动 polyfill**：见 UploadPanel.test.tsx 的 `makeDropEvent` / `makeDragEvent` helper —— 构造原生 Event 并 `Object.defineProperty(ev, 'dataTransfer', ...)` 挂上 stub。jsdom 后续若支持可去掉。

## 上传预览 US-007 关键约定（PiecePreviewSVG 调用方必读）

- **命令式渲染范式（参考 NestSVG.tsx）**：React 仅渲染 `<svg ref/>` 空骨架；useEffect 内 imperative 建 flipGroup `<g>` + 各层节点（polygon / polyline / line / text），用 `setAttribute` 写 transform / points / stroke / ...，**逃逸 React reconciliation**。改任何 attr 走 JSX prop 会被 React 用 vdom 覆盖回旧值（同 NestSVG 关键约定 #2）。
- **翻转组 transform = `translate(0 ${minY+maxY}) scale(1 -1)`**：sparrow Y-up → SVG Y-down（与 PNG / R12-DXF / NestSVG 一致）。`minY+maxY` 是 bbox 的 Y 对称轴，翻转后 bbox 内几何视觉与 sparrow 视图一致（不上下颠倒）。NestSVG 是其特例（minY=0, maxY=gate → `translate(0 gate) scale(1 -1)`）。改字面量需同步 PiecePreviewSVG.test.tsx AC#3 用例。
- **label 文字标注放在翻转组 `<g>` 之外**（AC#3 不镜像；历史 A/B/C，裁片编号化起标注值 = g 码）：用屏幕坐标（SVG Y-down）直接定位 —— 锚点 = piece bbox 左上角上方 `LABEL_Y_OFFSET=3`（baseline 在 `minY - 3`），`font-size=11` / `dominant-baseline=alphabetic`。改位置 / 字号需同步 PiecePreviewSVG.test.tsx 「标注用屏幕坐标」用例。
- **viewBox = bbox + pad**（默认 `DEFAULT_PAD=14`，最小 `MIN_PAD=4` clamp）：pad 容纳 8mm 刀口半段（4mm）+ 标注文本（~10mm cap 高度）。改 pad 默认需同步「viewBox = bbox + pad」用例（默认 + 自定义 + clamp 三组）。
- **5 层渲染分层（颜色 / 线型严格固定，改需同步测试 + 版师确认）**：layer1 毛版半透明蓝实心 `rgba(80,140,200,0.22)` + `#3f7fbf` 实线边（闭合 polygon）；layer14 净版绿虚线 `#33cc33` `stroke-dasharray=6 3`（闭合 polygon，fill=none）；layer8 内部线橙实线 `#ff8c1a`（polyline 不闭合，line.length<2 跳过）；layer4 刀口黄短线段 `#ffd700`（line，端点 `P ± 4*unit_normal`，长度 `NOTCH_LEN_MM=8`，**待版师确认**）；layer7 布纹线红虚线 `#e53e3e` `stroke-dasharray=5 3`（line，grain_line=null 跳过）。
- **刀口端点 = `P ± 4 * unit_normal`**（unit_normal 来自后端 `notch[2..3]`）：法线为单位向量，half=4，端点 `(x∓4nx, y∓4ny)`，r2 截断。法线为零向量（退化边）→ 0 长度线段（点）兜底。改 NOTCH_LEN_MM 需同步 PiecePreviewSVG.test.tsx 2 项刀口用例 + 版师确认。
- **piece(s) 切换整组重建（不同于 NestSVG flipRef 幂等）**：useEffect 头部 `while (svg.firstChild) svg.removeChild(svg.firstChild)` 清空旧内容后重建。NestSVG 同 run 内 N 帧复用 DOM（高频），PiecePreviewSVG 切片是低频 UI 操作，重建简洁且开销可接受。StrictMode 双 mount 同样安全（清空再建）。
- **AC#4 多片同框**：prop 接受 `ParsedPiece | ParsedPiece[]`，归一化为数组；多片时合并 bbox 计算 viewBox（`piecesBBox`），每片独立渲染 5 层 + 各自 label 标注。现调用方均为单片场景（QtyMatrix 行缩略图 compact 无标注 / PieceZoomModal / PtypePreviewModal 等），多片能力留作未来扩展（不刻意避免重叠，由调用方决定；原 ParsedPiecesView 单片卡片已随图形预览区拆除）。
- **空片容错（polygon=[] 或全无数据）**：`piecesBBox` 返回 null → svg 清空后啥都不画（无 viewBox / 无 flipGroup / 无标注），不留残影。polygon.length<3 跳过 rough 层；其他层照常渲染。改兜底需同步「空片」「polygon<3 跳过 rough」用例。
- **pad prop 最小 4 clamp**：`safePad = Math.max(MIN_PAD, pad)`，防 8mm 刀口半段被裁。负数 / NaN（NaN 经 max 比较返回另一侧）兜底为 4。
- **导出辅助 `pieceBBox` / `piecesBBox` / `BBox` 便于测试**：纯函数 / 类型导出，单测直接调；不改 React 渲染。PiecePreviewSVG.test.tsx 5 项 bbox 用例覆盖（合并所有层顶点 / 空片 null / 无 grain 跳过 / 多片合并 / 全空片 null）。
- **不引入 CSS 框架**：`.piece-preview-svg`（display:block + width:100% + height:100% + bg `#eef0f3`，与排料图同色）由 imperative setAttribute('class', ...) 写入，沿用 style.css；与 `.nest-card svg` 同口径。

## 上传预览 US-008 关键约定（SizeTabs / ParsedPiecesView / PreviewPage 调用方必读）

> **⚠️ 已被矩阵化重构 US-003 取代（2026-08-16）**：SizeTabs 已删除（尺码切换职责移交 QtyMatrix 行头），ParsedPiecesView 已随图形预览区拆除整体删除，PreviewPage 主体改为仅 QtyMatrix。本节以下描述保留作历史记录，现行契约见「矩阵化重构 US-002/US-003」节。

- **三个新组件都从 uploadStore 读、不持本地状态**：SizeTabs 读 `doc`/`activeSize`/`setSize`；ParsedPiecesView 读 `doc`/`activeSize`；PreviewPage 读 `status`/`doc`。store 是单一真相源（US-005 关键约定），切 Tab 后状态保留 = store 是模块级 + display:none 不卸载（AC#5 由 store 持久性保证，组件本身无需任何持久化逻辑）。
- **PreviewPage 空态分支用 `hasParsed = status === 'done' && doc !== null`**：双重条件防御（done 理论必有 doc，但 TS 类型上 doc nullable）。uploading / error 时仍显示空态卡片（不显示「上传中…」之类的状态行 —— 那是 UploadPanel 的事），保持右侧稳定布局。改分支需同步 PreviewPage.test.tsx 4 项空态用例。
- **SizeTabs 的 chip 顺序 = doc.sizes 顺序**（后端按数值升序、null 殿后），**前端不二次排序**：保证 UI 顺序与后端语义一致。改排序需同步后端 `_build_parse_payload` + SizeTabs.test.tsx「渲染 doc.sizes 全部」用例。
- **null 码 chip 显示「通用」**（`NULL_SIZE_LABEL`）：母版里极少出现的「不分码」片（统计上代表通用码），用人读文案代替空字符串/「null」。改文案需同步 SizeTabs.test.tsx 「null 码渲染为通用」用例。
- **SizeTabs doc=null 时返回空 Fragment**（`return <></>`）：双重防御（PreviewPage 在 doc=null 时不挂载 SizeTabs，但组件本身也兜底）。改返回值需同步 SizeTabs.test.tsx 「doc=null」用例。
- **ParsedPiecesView 用 `doc.sizes.find(s => s.size === activeSize)` 过滤当前码**：理论必命中（SizeTabs 只能切到 doc.sizes 里的码），防御性兜底 `matched=undefined` → pieces=[] → 显示「该尺码无裁片」空态。改过滤逻辑需同步 ParsedPiecesView.test.tsx 「activeSize 不在 doc.sizes」用例。
- **piece key 用 `${label}-${name}`**：label 在码内唯一（A/B/C/...，后端 _label_for 已保证），name 是母版 block 名（GBK 解码后中文），两者拼合跨码安全。同码内可能多片同名（label 不同）或同 label 不同名 —— key 拼合兜底所有场景。改 key 需同步 ParsedPiecesView.test.tsx 「key 用 label-name」用例。
- **每片卡片用 PiecePreviewSVG 单片模式**（不传数组，US-007 AC#4 多片能力留作未来扩展）：grid 是「每片独立预览」语义，单片卡片视觉清晰。改多片模式需先与版师确认 grid 单卡承载多片的 UX 必要性。
- **piece-card 视觉沿用 .nest-card 同口径**：暗背景 `#2a2c32` + 圆角 + 上方 `.piece-card-head`（label 徽章 + 裁片名）+ 下方 `.piece-card-body`（SVG 自适应）；与排料页 NestCard 视觉一致。label 徽章用 `.piece-card-label`（绿色 `#2ea06c` 圆形 + 白字，与 StartButton / TabBar active / size-chip active 同色系）。
- **grid 用 CSS Grid `auto-fill + minmax(220px, 1fr)`**：浏览器宽度自适应列数（窗口缩小时单卡不被压扁，最小 220px 保证 SVG 不退化成窄条）。改 minmax 需视觉回归核对（M1787 每码 ~10 片 × ~180px 高度 ≈ 一屏）。
- **不引入 CSS 框架**：`.preview-page` / `.preview-main` / `.size-tabs` / `.size-chip` / `.parsed-pieces-view` / `.piece-grid` / `.piece-card*` 全部沿用 style.css 命令式 className，与 ControlPanel / NestCard 暗背景 `#26282e/#2a2c32` + 绿色 `#2ea06c` 强调同色系。
- **AC#5 切 Tab 后状态保留**：uploadStore 是模块级单例 + App 用 display:none 切页（不卸载），切回时 activeSize/doc 全部保真。**PreviewPage 不持任何本地状态**（不需要 useState 缓存 activeSize 之类的反模式），改状态来源会破坏 AC#5。
- **空态分支组件结构**：未解析时 PreviewPage 渲染 `<div class="preview-empty"><div class="preview-empty-card">…</div></div>`（沿用 US-001 占位的 className，CSS 已存在无需新增）；已解析时渲染 `<SizeTabs/> + <ParsedPiecesView/>`。改结构需同步 App.test.tsx 第 101 行的 `.preview-empty` 断言（切到 preview Tab + doc=null 时仍要找到 `.preview-empty`）。

## US-015 关键约定（uiStore 扩 nestingEnabled + TabBar 置灰 调用方必读）

- **`setTab('nesting')` 在 `nestingEnabled===false` 时静默不切（关键不变量）**：store 层 guard 兜底所有 JS 调用方（TabBar / PreviewPage / 未来 URL hash 同步）。`setTab('preview')` 永远允许（用户随时可回上传预览页，不强制留在 nesting）。改 guard 需同步 uiStore.test.ts「setTab(nesting) 在 false 时静默不切」+「setTab(preview) 在 false 时仍可切」两项。
- **三层双重防御**：TabBar `disabled` 属性（native，a11y / 键盘 tab 序列不响应）→ TabBar `onClick` 内 `if (disabled) return`（合成事件 / devtools 旁路）→ store `setTab` guard（直调 store 的 JS 旁路）。任一层失效不影响整体不可点保证。
- **`nestingEnabled` 默认 `false`，由 PreviewPage 联动 setNestingEnabled(true)（US-016）**：store 默认锁定，业务层负责解锁。改默认值会破坏「未上传母版时超排 Tab 不可点」语义。
- **上传预览 Tab 永远可点**：用户随时可回上传预览页（reset / 重传 / 切码），不被锁定。TabBar 渲染时 `disabled = t.id === 'nesting' && !nestingEnabled`（preview 永远 false）。
- **`aria-disabled` + native `disabled` 同步**：屏幕阅读器 + 键盘序列双重 a11y。`aria-disabled={disabled}`（false 时 React 渲染为 `aria-disabled="false"` 字符串，与 `aria-pressed` 同口径）。改其中一项需同步另一项。
- **不引入 CSS 框架**：`.tab.disabled` + `.tab.disabled:hover` 沿用 style.css 命令式 className；`#555` 灰字 + `cursor:not-allowed`（含 `:hover` 同色防 hover 提亮）；与 ControlPanel / TabBar active 同色系。
- **测试 beforeEach 必须重置 nestingEnabled**：`useUiStore.getState().setNestingEnabled(false)` 加到 beforeEach（与 `setTab('preview')` 同位），避免前一个测试 setNestingEnabled(true) 残留。需要切 nesting 的测试先调 setNestingEnabled(true)；App.test.tsx beforeEach 也加 setNestingEnabled(true) 绕过 store guard 测原有 nesting 渲染。
- **未做浏览器验证**：本故事无 SVG/坐标变换（仅 button disabled 态 + CSS），AC 仅要求 typecheck + 单测 + build，故跳过 chrome-devtools-mcp；浏览器视觉回归留作 US-016 集成时统一核对（disabled 灰字 + cursor:not-allowed）。

## US-016 关键约定（PreviewPage 联动 setNestingEnabled 调用方必读）

- **联动公式严格固定 `next = status==='done' && doc!==null`**：`status` 非 done 或 doc=null 都 → false；只有 done 且 doc 非空才 → true。覆盖所有路径：idle/uploading（false）/ done+doc（true）/ error（false）/ reset（doc→null false）/ 重传（status=uploading 短暂 false，done 后切回 true）。改公式需同步 PreviewPage.test.tsx 8 项 US-016 用例。
- **PreviewPage 是集成层，subscribe + mount 即对齐 + 卸载 unsub（与 US-014 qtyStore 联动同模式）**：useEffect 内 `useUploadStore.subscribe((state) => syncTab(state.status, state.doc))`；mount 时立即按 `useUploadStore.getState()` 对齐初值；unmount 时返回的 unsub 函数被 React 调用清理。uiStore 与 uploadStore 解耦（与 qtyStore 同设计原则）：uploadStore 不知道 uiStore 存在，uiStore 不知道 uploadStore 存在。改耦合（如把 setNestingEnabled 调用挪到 uploadStore.reset 内）会破坏 store 解耦原则。
- **关键不变量（AC#3）：setNestingEnabled 仅控 Tab「能否进入」，不强制切 Tab**：`uiStore.setNestingEnabled(b)` 实现仅 `set({ nestingEnabled: b })`，**不触碰 activeTab**。故用户已在 nesting Tab 时调 reset（doc→null → setNestingEnabled(false)），activeTab 仍是 nesting，preview Tab 永远可点回但**不强制切回**，避免丢失求解状态。改 setNestingEnabled 副作用（如加 setTab('preview')）会破坏此不变量。
- **调用前先判 `get().nestingEnabled !== next`**：避免无变化时无谓 setState 触发订阅者通知（zustand 内部 Object.is 也会兜底，但显式判断更省一次 set 调度）。改判断逻辑需同步 8 项 US-016 用例（不直接断言 call count，但通过「关键不变量」用例间接验证）。
- **App.test.tsx beforeEach 必须 set uploadStore done+doc**：App mount 会触发 PreviewPage mount，PreviewPage 的 US-016 effect 会按当前 uploadStore.status 对齐 nestingEnabled。若 uploadStore=idle，beforeEach 设的 nestingEnabled=true 会被覆盖回 false，导致 `setTab('nesting')` 失效。改 beforeEach 需同步 App.test.tsx 7 项集成用例。「默认 activeTab=preview」测试用例显式 reset uploadStore 到 idle 验证 `.preview-empty`；「切到 preview」测试用例把 `.preview-empty` 断言改为 `.preview-page`（已上传状态下不再走空态分支）。
- **PreviewPage 现有两份 useEffect（qtyStore 联动 + uiStore 联动）独立**：US-014 qtyStore 联动 effect 监听 `doc?.doc_id` 变化；US-016 uiStore 联动 effect 监听 `status + doc` 变化。两 effect 各自独立闭包、互不干扰，挂载/卸载时各自挂载/清理 subscribe。改 effect 结构（如合并）需同步两套用例（US-014 7 项 + US-016 8 项）。
- **未做浏览器验证**：本故事无 SVG/坐标变换（仅 store 联动 + setState），AC 仅要求 typecheck + 单测，故跳过 chrome-devtools-mcp；浏览器视觉回归（disabled 灰字 + cursor:not-allowed 随 status 切换）留作 US-021 自动 commit 集成时统一核对（届时 done→commit→切 nesting 端到端联调）。

## US-017 关键约定（SizePicker 动态读码号 + DEFAULT_FORM.sizes=[] 调用方必读）

- **SizePicker 订阅 uploadStore.doc，不再硬编码 SIZES**：`doc !== null` → chip 列表 = `doc.sizes.map(s=>s.size)`（后端已按 `_size_sort_key` 排序，**前端不二次排序**；2026-08-31 起渲染前过滤 null 通用码，见下条）；`doc === null` → fallback `constants/sizes.ts:SIZES`（保后端开发模式下排料页可用）。改订阅源会破坏「切款母版 → 码号区自动同步」语义。
- **DEFAULT_FORM.sizes = [] 强制用户选**（旧 `[...SIZES]` 全选废除）：用户必须主动勾选码号；ControlPanel「请至少选一个码号」校验保留兜底。改默认值需同步 `params.test.ts` 「DEFAULT_FORM.sizes 默认空数组」用例 + `ControlPanel.test.tsx` AC#1 / AC#7 默认态断言。
- **FormState.sizes 类型扩 `(number|null)[]`**：doc.sizes 可能含 null（通用码），selected/onChange 也扩为 `(number|null)[]`。null 用 Set 的 `===` 比较自然去重 / 命中。
- **null 通用码不渲染 chip（2026-08-31 起，取代旧「通用」文案 chip）**：null 组 = 块名末尾带不出码号的裁片（大概率母版命名有问题），且下游 WS/export 载荷本就过滤 null（通用片从不参与求解）—— 渲染 chip 只会让「总裁片数量」虚高误导。现行为 = SizePicker `chipSizes` 过滤 null（`sz_null` DOM id 不存在）+ `computeTotalCutPieces` 跳过 selected 残留 null（同 WS/export 口径，防御）+ 解析完成 toast 提示（useParseDxf 触发，文案含「带不出码号」+「通用」去向）；**预览页 QtyMatrix「通用」行是唯一排查入口**。改回渲染 / 改文案需同步 SizePicker.test.tsx 「null 通用码不渲染 chip」3 项 + ControlPanel.test.tsx US-017 渲染用例 + useParseDxf.test.tsx null-size toast 3 项。
- **标题行「全选」tri-state 勾选框（2026-08-31 起）**：`.field-label.sizes-label` 行右端 `#sz_all` checkbox —— 勾选态**纯派生**（`allChecked = chipSizes.every(∈ selected)`，不新增状态存储，chip 勾/退即重算联动）；部分勾选 → `indeterminate` 半选（DOM property，须 ref callback 设置，React 无此 prop）；点击 = 全勾→`onChange([])` / 否则（含部分勾）→`onChange([...chipSizes])` 数字码全集（null 不入集，同 WS/export 口径）；chip 列表为空（母版只有 null 码）→ 禁用；`disabled` 随 chip 冻结。改行为需同步 SizePicker.test.tsx 「全选框」describe 8 项。
- **下游 WS / export 契约仍是 `number[]`**：ControlPanel.handleStart / handleExport 用类型守卫 `(s): s is number => s !== null` 过滤 null 后再透传（StartConfig.sizes / useExport.exportAs 签名不变）。M1787 实际母版无 null 码；含 null 母版的完整端到端支持留给 US-022（数量 demand 按 (label, sizeKey) 查表，sizeKey 已支持 null）。
- **ControlPanel 订阅 uploadStore.doc 用于 StatusLine 提示**：doc=null 时 `visibleStatus = ${status} — 请先在上传预览页解析母版`；doc 非空时 `visibleStatus = status`（无后缀）。StatusLine 组件本身不动（仅渲染 text）。改提示文案需同步 ControlPanel.test.tsx US-017 「doc=null StatusLine 增提示 / doc 非空无提示」2 项。
- **不引入 CSS 框架**：`.sizes` / `.chip` / `.chip input` / `.field-label` 全部沿用 style.css（与旧 vanilla SizePicker 同 className）。`sz_null` DOM id 已随 2026-08-31 null chip 移除而消失（现仅 `sz_28` 等数字码形态）。
- **测试隔离：ControlPanel.test.tsx beforeEach/afterEach 必须 reset uploadStore**：uploadStore 是模块级单例，US-017 起 ControlPanel subscribe doc；不 reset 会让前一个测试残留的 doc 影响后续测试的 SizePicker 渲染。改 beforeEach 需同步 ControlPanel.test.tsx 23 项用例。
- **未做浏览器验证**：本故事无 SVG/坐标变换（仅 chip 渲染 + StatusLine 文案），AC 仅要求 typecheck + 单测 + build，故跳过 chrome-devtools-mcp；浏览器视觉回归（chip 渲染 / 通用 文案 / doc 切换重渲染）留作 US-021 自动 commit 集成时统一核对（届时 done→commit→切 nesting 端到端联调）。

## US-021 关键约定（useCommitToNesting 自动 commit + D1 闭环 调用方必读）

- **自动 commit 是解析成功的副作用（void commit），不阻塞预览渲染**：useParseDxf 在 `setState({status:'done', doc})` 后用 `void commit(doc.doc_id, doc.filename)`（不 await），让 doc/status 先进 store、UI 先渲染预览，commit 后台跑更新 commitStatus。改 `await commit(...)` 会阻塞 upload 返回、延迟预览上屏（破坏 AC#6 关键不变量）。
- **commitStatus 与 parse status 分离（独立字段）**：uploadStore 持两套状态机 —— `status`（parse: idle→uploading→done|error）+ `commitStatus`（commit: idle→committing→done|error），互不干扰。parse done 可以无 commit（parse fail 时 commit 不触发）；commit done 必在 parse done 之后。改合并状态会破坏「commit fail 不影响 parse done 预览可用」语义（D5 基础）。
- **D1 闭环：commit done → setNestingEnabled(true)（不自动切 Tab）**：useCommitToNesting 在 commit 成功后显式调 `useUiStore.getState().setNestingEnabled(true)`（与 PreviewPage subscribe parse done 重复但幂等，显式调保证 commit 链路自闭环），解锁超排 Tab。**不再 setTab('nesting')**——解析成功只解锁，由用户主动点击进入超排页，避免劫持预览浏览（查看裁片/调数量）。commit fail 不切 Tab（D5）。
- **D5：commit fail 不切 Tab（Tab 仍解锁，用户可重试或用旧数据）**：commit fail 时 commitStatus='error' + commitError 显示，但 activeTab 不被切到 nesting（用户留在 preview 看到错误）。nestingEnabled 仍为 true（parse done 已解锁），用户可手动点超排 Tab 用旧 intermediate 数据进入。
- **防连击：committingRef + commitStatus==='committing' 双重防护**：ref 立即生效（async 函数体同步段执行）；setState 异步生效，第二次连击会在 setState 调度前进 hook body。两者任一为 committing 即忽略（返回 `{ok:false, error:'commit already in progress'}`，不抛错）。与 useParseDxf uploadingRef 同模式。
- **fetch 用 JSON body（非 FormData）+ 手设 Content-Type**：与 useParseDxf（FormData + 不手设 Content-Type）不同 —— commit 传 doc_id/filename 引用（无文件数据），用 `JSON.stringify({doc_id, filename})` + `headers: {'Content-Type':'application/json'}`。改 body 格式需同步后端 `server.py commit_to_nesting` + useCommitToNesting.test.tsx AC#7 URL+method+body 用例。
- **uploadStore reset 同步清 commit 字段**：`reset()` 把 `commitStatus='idle'/commitError=null/commitSummary=null`（与 status/doc/error/qtyDialog/zoom 同步清）。useParseDxf 进入 uploading 时也清 commit 字段（重传时旧 commit 摘要不再适用，UI 不残留误导）。
- **commitSummary 防御性构造**：后端 commit 响应字段缺失时用空数组/0 兜底（`Array.isArray(data.sizes) ? data.sizes : []`、`typeof data.n_pieces === 'number' ? data.n_pieces : 0`），不阻塞 commit done 状态切换。改兜底逻辑需同步 useCommitToNesting.test.tsx commitSummary 断言。
- **UploadPanel commit 状态行独立于 parse status 行**：两行可同时显示（parse done 行 + commit committing/done/error 行）。commit 行复用 `.upload-status.loading/.done/.error` 同三套 className（暗绿底/暗绿底/红字），`data-testid="commit-status"` 区分（parse 行 data-testid="upload-status"）。不新增 CSS 类。
- **测试隔离：useParseDxf.test.tsx / UploadPanel.test.tsx beforeEach/afterEach 加 uiStore reset**：commit D1 副作用调 setNestingEnabled（不切 activeTab），不 reset 会跨测试污染（前一个测试的 commit resolve 把 nestingEnabled 置 true，影响下一个测试初始态）。useCommitToNesting.test.tsx 也同步 reset。
- **mockImplementation 路由 fetch（非 mockResolvedValue）**：US-021 集成测试中 parse-dxf 和 commit-to-nesting 两个 endpoint 共享同一 fetch spy，需 `mockImplementation` 按 URL 路由返回不同 Response（parse→ParsedDoc、commit→commit summary）。mockResolvedValue 共享同一 Response 对象会导致 `.json()` 二次消费 body 报错（与 US-018 PerTypeOverridesModal fetch mock 同模式）。
- **未做浏览器验证**：本故事无 SVG/坐标变换（仅 store 字段扩展 + hook + UploadPanel 状态行 DOM），AC 仅要求 typecheck + 单测 + build。浏览器视觉回归（「应用中…」loading + 「已应用至超排」摘要 + Tab 解锁（不自动切）+ commit fail 红字）留作整体回归。

## US-022 关键约定（求解输入数量 demand per-size 调用方必读）

- **qtyStore 加 `hydrateDefaults(sizes, labels)` action**：per-size 模式下为 sizes × labels 交叉积每项填 1（D3）。与已有 `hydrateDefault(entries)`（按 `{label,size}[]` 列表）语义同、入参形式不同 —— 交叉积版适合「各码 ptype 集合一致」（M1787）场景，entries 版适合「各码 ptype 集合不同」一般场景。两个 action 并存，PreviewPage 仍用 entries 版（更通用）。
- **WS StartPayload 加 `quantities` 字段**：`Record<label, Record<sizeKey, number>> | null`（label→sizeKey→demand）。`types/ws.ts` 扩字段；`useSolveRun.ts` StartConfig 加可选 `quantities`，hook 内 `cfg.quantities ?? null` 填进 payload。缺省=null → 后端全片 demand=1（向后兼容旧前端）。
- **`serializeQuantities(qtyMap, sizes)` 纯函数（`lib/params.ts`）**：把 qtyStore.quantities 扁平化。per-size 模式取 perSize（只保留选中码 sizeKey）；global 模式取 globalValue 展开到全部选中码 sizeKey。空 map / 空 sizes → null。sizeKey 口径：number→String(number)、null→'null'（与 qtyStore 一致）。单测在 `lib/__tests__/params.test.ts`（7 项）。
- **ControlPanel.handleStart 调 serializeQuantities**：读 `useQtyStore.getState().quantities`（不订阅，避免数量编辑频繁重渲染 ControlPanel）+ 过滤 null 后的 sizesNum，序列化后填进 `ControlPanelStartPayload.quantities`。NestingPage 透传到 `useSolveRun.start({quantities})`，N 个 seed 共用同一份。
- **label 对齐由后端保证**：intermediate 每片加 `label` 字段（后端 `_commit_to_nesting_sync` 用 `compute_size_ptype_labels` 标注，与 parse-dxf 响应同排序同标注）。前端 qtyStore 以 label 为 key，后端 build_instance 按 `(piece.label, str(piece.size))` 查 quantities → demand。M1787 验证 10/10 ptype 对齐。
- **demand=0 语义（D2）**：用户改某片某码为 0 → 后端 build_instance 见 0 跳过该 piece（不进 sparrow 实例）。配合 D3（hydrateDefaults 填 1）保证开箱即用 + 用户可显式排除。
- **无 SVG/坐标变换改动**：本故事仅 store/hook/payload 扩展，AC 仅要求 typecheck + 单测 + `python -c "from materialsorting.web.server import app"` 导入通过。浏览器视觉回归（改某片某码 0 → 求解结果该片不出现）留作整体回归。

## US-027 关键约定（NestingPage phase 状态机 + useSolveRun.stop() 调用方必读）

- **phase 五态由 NestingPage 持有，子组件纯受控**：`phase: SolvePhase`（idle/running/stopped/done/error）在 NestingPage useState；ControlPanel / 后续 US-028 SolveControls 都不自持 phase。phase 切换只发生在 NestingPage onDone 汇总线（全部 seed onDone 到齐后统一切）。改 phase 持有方会破坏「多 seed 所有 onDone 到齐后统一切 phase」语义。
- **onDone phase 优先级「全 stopped→stopped、有 error→error、否则 done」**：per-run `stopped` 与 `error` 互斥（useSolveRun `case 'stopped'` 和 `case 'error'` 不同时置），故 `allStopped = runs.every(r=>r.stopped)` 蕴含无 error，检查顺序安全。改优先级需同步 useSolveRun.stop.test.tsx 3 项 NestingPage phase 转换用例。
- **stop() 仅对 `readyState===WebSocket.OPEN` 的 WS 发 {action:'stop'}**：非 OPEN（CONNECTING/CLOSING/CLOSED）跳过（send 会 throw 或无意义）；`ws.send` 外包 try/catch 兜底连接刚关闭。**Mock WebSocket 必须定义静态常量 CONNECTING/OPEN/CLOSING/CLOSED**，否则 `WebSocket.OPEN` 为 undefined 导致 stop() 永远不发（测试踩坑修复：见 useSolveRun.stop.test.tsx MockWebSocketCtor）。
- **`case 'stopped'` 不重算 finalDensity**：stopped 无 final 消息，finalDensity 保持默认 0；lastFrame 保留停止时刻帧（供导出中间方案，US-028 导出按钮用）。rec.stopped=true + finish() 触发 onDone（与 final/error 路径一致）。
- **handleStop 不立即 setPhase**：等后端回 `{type:'stopped'}` → onmessage case 'stopped' → finish → onDone 统一切 phase。立即 setPhase 会与 onDone 的 phase 切换竞争（多 seed 部分 stopped 部分未停）。
- **handleRestart 用 lastStartCfgRef（上次 start 参数）**：handleStart 内 `lastStartCfgRef.current = cfg` 每次更新；handleRestart 读 ref 调 handleStart（内含 clear+reset+start）。用户在 stopped/error/done 态改参数后走 ControlPanel.onStart → handleStart（新参数覆盖 ref），故「改参数用新值」由 onStart 路径自然保证，handleRestart 仅是「用上次参数一键重跑」。
- **running 态冻结参数编辑（与 StartButton disabled 同套机制）**：ControlPanel 向 SizePicker/ParamForm/MultiSeedControls/PresetButtons/PerTypeOverrides 透传 `disabled={solving}`（= phase==='running'）；5 个输入组件各加 `disabled?: boolean` prop。stopped/done/error 态可编辑（用户可改参数后重新开始）。改 disabled 条件需同步 useSolveRun.stop.test.tsx 3d 用例。
- **ControlPanel solving prop 保留（US-028 改 phase）**：本 Story 仅传 `solving={phase==='running'}` 保持 ControlPanel API 不变；`onStop`/`onRestart`/`phase` 可选 props 不在本 Story 接线（US-028 由 SolveControls 消费）。ControlPanel 函数不解构这三个可选 props（避免 noUnusedLocals）。
- **SolvePhase 类型导出到 types/solvePhase.ts**：供 US-028 SolveControls 复用；不在 NestingPage 内联（跨组件共享类型必须入 types/）。
- **未做浏览器验证**：本 Story 无 SVG/坐标变换（仅状态机 + 输入 disabled），AC 仅要求 typecheck + 单测 + build；浏览器完整流程（idle→running→stopped→restart→done）验证留作 US-028（UI Story，SolveControls 接线后统一核对）。

## US-024 关键约定（NestSVG 5 层渲染 + 共享 LAYER5_COLORS 调用方必读）

- **5 层中 4 层仅渲染透传不参与碰撞**：`polygon`（layer1 毛版外轮廓，erode 后）是唯一参与 sparrow NFP 碰撞的几何；`net_polygon` / `internal_lines` / `notches` / `grain_line` 4 层仅渲染/导出透传，不影响求解结果或利用率。改任一层语义需同步后端 collect.LAYER_MAPPING + export_dxf + load_pieces + web/server._commit_to_nesting_sync + solver.pid_meta + web/export.py + 本组件。
- **5 层节点只在 manifest 到达时建一次（性能保护 AC#5）**：NestSVG effect 内 `if (run.manifest && !flipRef.current)` 块创建毛版 polygon + 4 层工艺节点；frame 切换只 setAttribute('points'/'x1'/'y1'/'x2'/'y2'/'display')，**不重建 DOM**；128 片 × 5 节点 ~10fps 可承受。改创建时机（如每帧重建）会破坏性能保护。
- **4 层节点 pointerEvents='none'**：事件委托只触发于毛版 polygon（dataset.ptype 必有）；4 层工艺节点不参与 mousemove tooltip 联动（US-006 hover 语义不变）。
- **5 层都在翻转组内（scale(1,-1)）**：共用 `<g transform="translate(0 gate) scale(1 -1)">`，与 US-003 关键约定 #1 一致。改其中一层挪出翻转组会破坏视觉一致性（上下颠倒）。
- **notch 端点变换：点按 point 变换 + 法线按 vector 旋转**：notch 数据模型 `(x, y, nx, ny)`，端点 = `(x ± NOTCH_LEN_MM/2 * nx, y ± NOTCH_LEN_MM/2 * ny)` 各按 rot+tr 变换（`transformPt` 与 `lib/geometry pointsStr` 同公式单点版）。half = 4。法线为零向量（退化边）→ 0 长度线段兜底。
- **LAYER5_COLORS 是 NestSVG + PiecePreviewSVG 视觉一致的单一真相源**：`constants/colors.ts LAYER5_COLORS`（ROUGH_FILL rgba(80,140,200,0.22) / ROUGH_STROKE #3f7fbf / NET #33cc33 / INTERNAL #ff8c1a / NOTCH #ffd700 / GRAIN #e53e3e）+ `NOTCH_LEN_MM = 8`。后端 `web/export.py LAYER5_COLOR_*` 字面量需与此同步。改任一层配色需同步两处。
- **layer-aware 缺字段跳过**：旧 intermediate（无 5 层字段）的 piece → netEl/internalEls/notchEls/grainEl 为 null/空，渲染时跳过；新 intermediate（含 5 层）自动多画 4 层。前后端均用 `.get()` / `?? []` / `if (p.net_polygon && len>=3)` 兜底，向后兼容。
- **transformPt 单点辅助**：与 `lib/geometry.ts pointsStr` 同公式（rad=rot*π/180, c=cos, s=sin, `x'=x*c−y*s+tx`, `y'=x*s+y*c+ty`, r2 截断），输出 `[x, y]`。用于刺口 line 端点 / 布纹线端点（line 元素的 x1/y1/x2/y2 独立属性写入，不能用 pointsStr 整段字符串）。
- **未做浏览器视觉验证**：chrome-devtools-mcp 工具不在本会话工具集；5 层渲染已用 8 项 NestSVG 单测 + e2e smoke 验证 5 层节点存在 + setAttribute 写入 + display 切换 + rotation transform 正确。版师屏幕视觉回归 + ET2008 真机读 R12-DXF（D4 硬验收）留作后续整体回归。

## US-018 关键约定（PerTypeOverridesModal/PtypePreviewModal 高级配置弹窗 调用方必读）

- **按钮触发替代旧 `<details>` 折叠**：PerTypeOverrides 从「10 行 pt-row 折叠面板」改为「单个 `.per-type-btn` 按钮 → modal」模式（D5 决策：母版 10 片型 20 input 常驻 ControlPanel 视觉噪声过大；收进 modal 后 ControlPanel 更简洁）。按钮 onClick 调 `useControlPanelStore.openModal('per_type')`；modal 订阅 `modal==='per_type'` 自显隐。改回折叠面板需同步 ControlPanel.test.tsx US-018 「button trigger」2 项用例。
- **controlPanelStore 是两模态的唯一真相源**：`modal: 'per_type' | null` + `previewLabel: string | null`（g 码）两个独立字段 + 4 个 actions（openModal/closeModal/openPreviewLabel/closePreviewLabel）。** closeModal 不影响 previewLabel，closePreviewLabel 不影响 modal**（双层独立 ESC 的基础）。改字段拆分 / 耦合需同步 controlPanelStore.test.ts 7 项用例。
- **双层独立 ESC（AC#10 关键不变量）**：PerTypeOverridesModal 的 ESC listener 在触发前判 `useControlPanelStore.getState().previewLabel !== null` → return（让上层优先处理）；PtypePreviewModal 的 ESC listener 仅判自身 `previewLabel !== null`。当放大预览打开时 ESC 只关预览，底层 modal + 草稿保真；再次 ESC 才关高级配置。改任一层 ESC 逻辑需同步 PerTypeOverridesModal.test.tsx「ESC 不关底层 / 双层独立」+ PtypePreviewModal.test.tsx「ESC closes」+「stacked close preview keeps 底层」用例。（US-004 曾扩入第三层「整列设值弹层」已随 2026-08-18 矩阵回退删除。）
- **空值预填 '0'/'0'（2026-08-18 回退 US-004 后回归 US-003 行为）**：form.per_type 已配置键 d/tol 双空 → 预填 '0'/'0'；reps 到位后未配置的新 g 码格渲染空串 + placeholder `d≤10`/`t≤45` 提示（= 继承全局默认 0/0；显式填 0 = 强制 0，两者可区分，collectParams 口径一致）。
- **草稿 + 确定模式（非即时生效）**：PerTypeOverridesModalInner 用 useState 持 `draft: Record<g码, PerTypeFormValue>`（单级字符串形状，lib/params.ts；2026-08-18 回退 US-004 两级嵌套）；用户编辑仅改草稿；点确定才 `onChange(draft)` + closeModal；点取消 / 遮罩 / ESC 仅 closeModal，草稿丢弃。**目的**：格子 input 即时写 form 会让 ControlPanel 频繁重渲染 + 用户误关时无法回滚（同 QtyMatrix 行填充同模式）。
- **`key="per-type-modal"` 强制 PerTypeOverridesModalInner 重建**：每次 modal 显隐切换时 Inner 组件重建，useState 从 form.per_type 重新拷贝 draft（避免上次草稿残留 / StrictMode 双 mount 时旧 draft 污染）。改 key 需同步「initial draft prefills 0/0 / preserves form.per_type 非空值」用例。
- **单级表格结构（列 = g 码 × 2 行 d/tol；2026-08-18 回退 US-004 矩阵化）**：列集 = /api/ptypes representatives 键 ∪ form.per_type 已配置键（fetch 失败降级空 reps 仍可配置），`compareByLabel` 数值序（先长度再字典序：g02<g99<g100，**勿去零填充**）；tbody 固定 2 行 —— 重合 d（0–10mm）+ 旋转 tol（0–45°），全局上限不按片型，blur 规整到 [0, max]。per_type 单级 `{g 码: {d, tol}}`（无码号维度：重合/旋转是片型工艺属性、与码号无关；后端 build_instance 按 label 命中对该 g 码全部码号生效）。testid = `d-${label}` / `tol-${label}` / `ptype-thumb-${label}`；aria = 「裁片 {g 码} 重合/旋转」。
- **片型缩略图来自 GET /api/ptypes（US-020 契约）**：PerTypeOverridesModal mount 时 fetch `/api/ptypes` → `PtypesResponse.representatives[label]`（US-003 起键 = g 码）；rep 存在 → `<button class="ptype-thumb">` 内渲染 PiecePreviewSVG compact（64×64，无 label，pad=2）；rep 不存在 / fetch 失败 → button disabled + 显示 g 码首字占位（loading 态「…」）。**fetch 用 cancelled flag 防 StrictMode 双 mount race**（mount→cleanup→mount，第一次 fetch 的 setState 被 cancelled 跳过）。改 fetch 逻辑需同步「mount triggers fetch」+「fetch failure degrades」+「fetch success renders compact svg」3 项。
- **PiecePreviewSVG `compact` prop**：compact=true 时（1）pad 默认 `COMPACT_PAD=2`（不是 DEFAULT_PAD=14）；（2）跳过 `renderLabel`（不渲染 label 文本）；（3）其它 5 层渲染（polygon / net_polygon / internal_lines / notches / grain_line）layer-aware 不变。改 compact 分支需同步 PiecePreviewSVG.test.tsx 5 项 compact 用例。
- **点击缩略图 → PtypePreviewModal 放大预览**：`.ptype-thumb` onClick 调 `openPreviewLabel(label)`（US-003 起 label = g 码）；PtypePreviewModal 订阅 `previewLabel` 自显隐，渲染同 rep 的 PiecePreviewSVG（pad=20，非 compact，label 叠印 g 码标注）。**PtypePreviewModal 每次打开（previewLabel 变非 null）重新 fetch /api/ptypes**（2026-08-17 修复旧缓存与弹窗缩略图数据不一致 bug；关闭态不发请求）。改 click 行为需同步 PerTypeOverridesModal.test.tsx「clicking thumbnail opens PtypePreviewModal」用例。
- **rep→Piece piece 转换**：`repToPiece(rep)` 把 PtypeRepresentative 扩展为 ParsedPiece（label=''，compact 模式不渲染标注），其余 5 层字段原样透传。PiecePreviewSVG layer-aware 渲染按字段存在性决定（polygon 缺失跳过 rough 层、net_polygon 缺失跳过 net 层等），无需 compact 分支特判。
- **z-index 层级**：tooltip(100) < piece-qty/zoom(1000) < per-type(1100) < ptype-preview(1200)。放大预览覆盖在最上；高级配置 modal 覆盖在 ControlPanel 之上。改 z-index 需同步视觉回归。（US-004 整列设值弹层 1150/1160 已随 2026-08-18 矩阵回退删除。）
- **fetch mock 必须用 mockImplementation（不是 mockResolvedValue）**：StrictMode dev 双 mount 会调 2 次 fetch；mockResolvedValue 共享同一 Response 对象，首次 `.json()` 消费完 body 后第二次调用报 "body stream already read"。测试中统一用 `vi.spyOn(globalThis, 'fetch').mockImplementation((_input) => Promise.resolve(new Response(...)))` 每次创建新 Response。改 mock 方式会让所有 fetch 测试失败（见 PerTypeOverridesModal.test.tsx / PtypePreviewModal.test.tsx / ControlPanel.test.tsx / App.test.tsx 4 处 beforeEach）。
- **App.test.tsx 也需 fetch stub**：App → ControlPanel → PerTypeOverrides（内挂 PtypePreviewModal）会在 mount 时 fetch /api/ptypes；若不 stub 会出现 act warning（fetch promise 在 act() 外 resolve）。改 beforeEach 需同步 App.test.tsx 7 项集成用例。
- **不引入 CSS 框架**：`.per-type-wrapper/.per-type-btn`（#2c5d8f 蓝）+ `.per-type-overlay/.per-type-modal`（#26282e 暗底）+ `.per-type-table-wrap`（overflow-x:auto）+ `.per-type-table`（table-layout:fixed）+ `.per-type-rowhead`（sticky left，48px）+ `.ptype-col`（80px 宽）+ `.ptype-thumb`（64×64 cursor:zoom-in）+ `.per-type-actions/.per-type-btn-cancel/.per-type-btn-confirm`（#2ea06c 绿）+ `.ptype-preview-*`（z=1200）全部沿用 style.css 命令式 className，与 ControlPanel / piece-zoom-modal 暗背景同色系；`.qty-label-badge` 跨组件复用（QtyMatrix ↔ 高级配置弹窗；US-004 曾复用的 `.qty-fill-*`/`.qty-rowfill-btn`/`--per-type` 弹层 modifier 已随矩阵回退移除，回归 QtyMatrix 专用）。
- **浏览器验证**：US-004 矩阵化曾用 scripts/us004_verify.mjs CDP harness 验证（15/15 PASS）；该 harness 已随 2026-08-18 矩阵回退删除，回退行为由 PerTypeOverridesModal.test.tsx / params.test.ts / ControlPanel.test.tsx / 后端 test_solver_label.py 单测覆盖；回退后的端到端浏览器回归留作后续整体回归。

## US-001 关键约定（Tab 框架调用方必读，US-015 已扩）

- **双页面常驻 DOM，display:none 切换**：`.page.hidden { display: none }`（不是条件渲染）。切回排料页时 NestingPage 内 useState/useRef/runRegistry 全部保真，进行中求解 / WS / seek 不中断。改策略需同步 6 项 App.test.tsx。
- **uiStore 双字段（US-015 扩，US-016 联动）**：`activeTab: 'nesting' | 'preview'`（默认 `'preview'`）+ `nestingEnabled: boolean`（默认 `false`，**US-016 由 PreviewPage subscribe uploadStore 联动 setNestingEnabled**）。求解/WS/seek 等业务状态由 NestingPage 自治，不混入 uiStore。**关键不变量**：`setTab('nesting')` 在 `nestingEnabled===false` 时静默不切（见 US-015 关键约定）；setNestingEnabled(b) 不强制切 Tab（见 US-016 关键约定）。
- **TabBar 只切 store**：`<button onClick=setTab>`；显隐由 App 订阅 activeTab 后切 `.hidden` class（解耦：未来 URL hash 同步只需改 App）。US-015 加 disabled 闸（超排 button native disabled + .disabled class + 运行时 onClick 判）。
- **Tab 顺序固定**：超排在前、上传预览在后；TABS 数组顺序不可改。
- **TabBar 视觉沿用 style.css**：暗色 `#26282e` 与 ControlPanel 同色系；active 用绿色 `#2ea06c` border-bottom（与 StartButton 同色）。US-015 加 `.tab.disabled`（`#555` 灰字 + not-allowed）。不引入 CSS 框架。
- **NestingPage 用 Fragment**：ControlPanel + main 直接作为 `.page` flex 子元素，不再包 `.app`（避免冗余 DOM + flex 嵌套层）。
- **Tooltip 仍由 App 渲染**：US-006 关键约定 #3（模块级单例）不破；NestingPage 不挂 Tooltip。

## US-029 关键约定（操作指引 tour 基础设施 调用方必读）

- **tourStore 与 TourDef 解耦**：tourStore 是纯状态层（activeTour/stepIndex/seen），不知道 TourDef/steps（步骤定义在 `src/tour/steps/`）。useTour 作为集成层读步骤定义 + 控制 advance-on-ready。tourStore.next() 仅 floor clamp（stepIndex>=0）；ceiling clamp（最后一步 next→close+markSeen）由 useTour 知道 steps.length 后兜底。改耦合会破坏层分离。
- **advance-on-ready 模型（US-029 骨架 / US-030 完整）**：告知型步（无 ready 谓词）→ 点下一步直接推进；联动型步（有 ready）→ ready()===false 切等待态+200ms 轮询+下一步 disabled，true 时自动推进。US-029 的 DEMO_PREVIEW_TOUR 两步均为告知型。轮询定时器用 useRef 持有，close/unmount/stepIndex 变化时 clearInterval（无泄漏）。
- **spotlight 用 box-shadow 镂空**：.tour-overlay 透明背景（z-index 2000），.tour-spotlight 贴目标 rect + `box-shadow:0 0 0 9999px rgba(0,0,0,0.6)` 实现镂空遮罩。spotlight `pointer-events:none`（用户可点击高亮目标）；bubble `pointer-events:auto`（按钮可点）。
- **零尺寸兜底**：querySelector 目标 display:none/全零 rect → readTargetRect 返回 null → spotlight display:none + bubble 居中（translate(-50%,-50%)）。对应 .hidden 页 display:none 场景。
- **定位用 useLayoutEffect imperative**：与 Tooltip.tsx 同模式——JSX 不带 style prop，useLayoutEffect 读 getBoundingClientRect 后写 style.left/top/width/height。改 JSX style prop 会被 React reconciliation 覆盖。
- **重算时机**：步骤切换（stepIndex 变）、resize/scroll（tick state bump → re-render）、advance-on-ready 状态变化（waiting 变）均触发 useLayoutEffect 重读 rect。scroll 用 capture=true 捕获子容器滚动。
- **TOUR_VERSION 版本号策略**：仅步骤内容重大变更时 bump（小改不改版本）。bump 后 hydrateSeen init 检测 storedVersion!==TOUR_VERSION → 清全部 seen（强制重看）。markSeen 同步写 version（防 localStorage 部分清除后 re-hydrate 误清）。不引入 zustand persist 中间件。
- **TabBar 右上角入口 class 用 .tour-entry（非 .tab）**：不干扰现有 TabBar.test.tsx 的 `button.tab` count===2 断言。下拉菜单 class 用 .tour-menu（z-index 1300）。
- **不引入 CSS 框架**：.tour-overlay/.tour-spotlight/.tour-bubble/.tour-btn-*/.tour-entry*/.tour-menu* 全部沿用 style.css 暗背景 #26282e + #2ea06c 同色系。
- **未做浏览器验证（chrome-devtools-mcp 不在本会话工具集）**：本 Story 无 SVG/坐标变换（仅 DOM overlay + CSS spotlight/bubble），核心定位逻辑用 5 项 TourOverlay 单测 + 8 项 tourStore 单测覆盖（含 mockRect 精确验证 spotlight 贴目标 rect + 零尺寸回退居中 + 步骤切换跟随）。AC 仅要求 typecheck + 单测 + build 全绿。浏览器视觉回归（resize/scroll 聚光灯跟随、ESC/跳过关闭、刷新 seen 保留）留作 US-030/032 集成时统一核对。

## US-007 关键约定（导出 PNG/DXF 调用方必读）

- **useExport 挂在 ControlPanel 内**：因为 sizes 在 ControlPanel form 里（与旧 vanilla 实现 `sizes: selectedSizes()` 同源）。App 不持有 useExport；onStatus 由 useExport → ControlPanel props.onStatus → App.setStatus → StatusLine 透传。
- **ExportPayload 七字段与旧 vanilla 实现 字节级一致**：`{ fmt, sizes, seed, gate_mm, width_mm, density, placed }`。其中 `width_mm = run.lastFrame.width_mm`、`density = run.finalDensity`、`placed = run.lastFrame.placed_items`、`gate_mm = run.manifest.gate_mm`。改任一字段必须同步 `__tests__/useExport.test.tsx` AC#2 用例。
- **bestRun = runRegistry.bestRun()**：已封装「lastFrame 存在且 finalDensity 最高」逻辑（并列取首个）。ExportButtons 的 disabled 用更宽条件 `some(r => r.lastFrame)`，不用 bestRun（bestRun 留给 useExport 内做最终选择）。
- **parseContentDisposition 优先级**：`filename*=UTF-8''xxx` > `filename="xxx"`/`filename=xxx` > `nesting.<fmt>`。decodeURIComponent 抛 URIError → 落下一级（不让导出整体失败）。改顺序同步 `download.test.ts`。
- **防连击用 ref + state 双重防护**：`exportingRef.current` 立即生效；`exporting` state 触发 UI disabled。仅 state 有 race（连击第二次在 setExporting 调度前进入 async body）。
- **ExportButtons 订阅 renderTick**：lastFrame 是 mutable push 不进 React state；通过 `useAppStore(s => s.renderTick)` + `void renderTick` 触发 reconciliation 后重算 hasLastFrame。改订阅源会破坏 final 后启用联动。
- **DOM id `export_png`/`export_dxf` 沿用 legacy CSS 选择器**：保留便于测试 + US-008 清理时一并去除。改 id 同步 `ExportButtons.test.tsx` + `ControlPanel.test.tsx` US-007 用例。
- **服务端文件名 `pct` 而非 `%`**：`server.py export` 拼 `排料_码{sizes_str}_{pct:.2f}pct_seed{seed}.{ext}`（不是 `88.42%`）。AC#5 字面写 `%` 是文档误差；实际下载 `排料_码28-30-32_88.42pct_seed0.png`。改格式需同步 server.py + useExport.test.tsx CN decode 用例。
- **jsdom 测试需 stub URL.createObjectURL + <a>.click()**：jsdom 不实现 `URL.createObjectURL`、`<a>.click()` 触发 navigation 警告。在 beforeEach 全局 stub，afterEach 调 `vi.unstubAllGlobals()` 还原（见 `__tests__/useExport.test.tsx`）。
- **PLT 导出前弹 ExportInfoModal（2026-08-30 v2 / 2026-08-31 v3）**：`ControlPanel.handleExport` fmt==='plt'/'plt-clean' 分流（PNG/DXF 直通不弹窗）；纯取消型（ESC/遮罩/✕/取消只关窗，「导出 PLT」唯一提交路径），手输草稿 localStorage `ms_export_table` 跨导出记忆（`lib/exportTable.ts`，刻意不进 FormState——form 随 doc_id 重置会连带清空）。**v3 全 14 字段预览**：mount 时 POST `/api/plt-table-preview`（bestRun 几何子集，与 /export 同源字段）→ 响应 14 行**按服务端返回列序（= 最终表格列序）交错渲染**——自动字段只读行 `.export-ro-row`（`data-testid="export-info-auto-{key}"`），手输槽位经 `KEY_TO_FIELD`（snake→camel）渲染本地草稿输入框（不消费服务端 value；未知 manual key 跳过防御）；列序/格式权威在后端 `_row_texts` 单一真相源，前端零公式镜像。
- **预览优雅降级（v3 约定）**：预览 null（加载中/网络错/rows 缺失/无 bestRun）→ v2 形态（6 手输 + `export-info-auto-hint` 提示行），确认导出**永不被预览阻塞**（导出时后端照算）；迟到响应经 `alive` flag 丢弃（弹窗先关不复活）。改输入框 id（kebab-case 契约 `export-info-bed-no` 等）/行为须同步 `ExportInfoModal.test.tsx` + `NestingPage.test.tsx` 弹窗流程用例 + `scripts/smoke_plt_table_preview.mjs`（浏览器冒烟 harness）。
- **PLT（毛版）变体（2026-08-31；当日由「净版」更名——与裁片 layer1「毛版轮廓」命名统一，协议值 `'plt-clean'`/ascii 后缀 `_clean` 不随更名变）**：`lib/download.ts` `ExportFmt` 加 `'plt-clean'`、`EXPORT_FORMATS` 加 `{value:'plt-clean', label:'PLT（毛版）'}`（数据驱动下拉框，ExportButtons 零代码改动自动出现）；**`DEFAULT_EXPORT_FMT='plt-clean'`（同日用户定案：毛版为现场主交付；此前 2026-08-24~08-30 为 'plt'）**；`parseContentDisposition` 兜底把 `-clean` 后缀去掉还原 `.plt` 扩展名。`ControlPanel` 以 `pendingPltFmt` state 记住待导出变体（选毛版 → 同一弹窗 → confirm 经 `exportAs(pendingPltFmt,...)` 原值透传，useExport 零公式新增）；`ExportInfoModal` 可选 prop `variant:'plt'|'plt-clean'`（缺省 'plt'）只改标题/aria/确认按钮/提示文案，14 字段填写与预览流程两变体**完全共用**（后端 `/export` fmt='plt-clean' → `write_marker_plt(clean=True)`：裁片只画最外层轮廓 + 尺码\*数量标注、唛架左右各一份同内容表格）。改文案/分流/默认值须同步 `ExportInfoModal.test.tsx` 毛版 describe + `ControlPanel.test.tsx` 导出接线两用例 + `ExportButtons.test.tsx` 4 选项与默认值断言 + `NestingPage.test.tsx` 导出流程用例（显式选 'plt'）。

## US-006 关键约定（回放 seek / Tooltip 调用方必读）

- **`seekTime = -1` 是 live 标志**：appStore.seekTime 默认 -1 表示「跟随 lastFrame」；`>=0` 才走 frameAtTime 分支。NestSVG / SeekReadout 都按此分支。改默认值需同步 9 项 PlaybackBar + 11 项 NestSVG.seek 单测。
- **App.onDone 全完成时 setSeekTime(me)**：`me = Math.ceil(maxElapsed(runRegistry.list()))`，与旧 vanilla 实现 `$('seek').value = me` 一致 —— 默认拖到末尾。handleStart 内必须 setSeekTime(-1) + clearHovered + hideTooltip（防 DOM 残留）。
- **Tooltip 是模块级单例**：Tooltip.tsx 用模块顶层 `let _el / let _hovered`；App 内**只能挂一个 `<Tooltip/>`**（多挂互相 clobber）。NestSVG mousemove 处理器调 `showTooltip / hideTooltip / setHovered / clearHovered` —— 高频 mousemove 不进 React state，直接 mutate style/innerHTML/classList。
- **Tooltip style 只能由 imperative 写**：Tooltip 组件 JSX **不带 style prop**（仅 className），否则 React reconciliation 重渲染时会把 display 重置为初始值，覆盖 showTooltip 写的 'block'。初始 display:none 在 useEffect 内通过 `el.style.display = 'none'` 设。
- **frameAtTime 二分与旧 vanilla 实现 字节级一致**：`lo=0, hi=n-1, ans=0; while (lo<=hi) { mid=(lo+hi)>>1; if (frames[mid].elapsed<=t) {ans=mid; lo=mid+1} else hi=mid-1 }`；返回 frames[ans]。改算法必须同步 `lib/__tests__/seek.test.ts` 9 个 frameAtTime 用例（含 1000 帧 stress 等价线性参考）。
- **flipGroup 上事件委托 mousemove + mouseleave（不是 svg）**：AC#4 明确要求；多边形均在 flipGroup 内，行为与旧 vanilla 实现 setupHover(svg) 等价。listener 在 `if (run.manifest && !flipRef.current)` 块内 attach —— 幂等保护防 StrictMode 双 mount / 多次 bump tick 双注册。
- **面积换算 mm² → cm² 用 `÷100`**：`parseFloat(dataset.area)/100` 与旧 vanilla 实现 一致；`.toFixed(1)`。改单位 / 精度需同步 `NestSVG.seek.test.tsx` 的 4 项 innerHTML 断言。
- **PlaybackBar 节流订阅**：PlaybackBar / SeekReadout 都订阅 renderTick（不是 seekTime 单独）—— frame push 后通过 tick 重算 allDone/max/readout。Seekbar 额外订阅 seekTime（受控 value 跟随）。

## US-005 关键约定（多 seed / 收敛曲线 调用方必读）

- **`ControlPanelStartPayload.seed_count` 是已 clamp 的最终值**：`parseSeedCount(form)` 返回 1（multi_seed=false）或 clamp(parseInt||3, 2, 6)。App.handleStart 直接 `for (let i=0; i<seed_count; i++) start({...cfg, seed: base+i})`，不再做边界检查。
- **App all-done 检测用 ref 不用 state**：`doneCountRef.current += 1; if (< totalSeedsRef.current) return;` —— 闭包陈旧风险靠 ref 规避。每次 handleStart 重置 `doneCountRef.current = 0` + `totalSeedsRef.current = cfg.seed_count`。
- **ConvergenceCurve 命令式 innerHTML**：React 仅 `<svg ref/>`；子节点（line/text/circle/path/g.legend）通过 `svg.innerHTML = out` 一次性写入，**不要改成 JSX**（每帧 diff 开销爆炸）。`sampleFrames` / `renderCurveInto` 导出便于纯函数测试。
- **采样算法与旧 vanilla 实现 drawCurve 字节级一致**：`step = max(1, floor(n/400))`；`pts = frames[0::step]`；`if (pts[last] !== frames[last]) pts.push(frames[last])`（末帧强制纳入）。改算法必须同步 `__tests__/ConvergenceCurve.test.tsx` 4 个采样用例。
- **配色：单 seed 走 PHASE_COLORS[phase]（散点）+ 默认蓝 `#1f77b4`（折线 / 末点）；多 seed 走 SEED_COLORS[ri]（折线 / 末点 / 标签 / 图例）**。`multi = runs.length > 1`（不是 multi_seed 表单值）。
- **useRafThrottle(seeds.length>0) 不在 solving=false 时停**：求解结束后曲线 / NestLabel 仍需 bump 重绘最终态；下次 start() 才会 runRegistry.clear + setSeeds([]) 间接停掉。
- **NestsGrid 只在 seeds 变化时挂载/卸载**：`<NestCard key={seed} run={rec}/>` 稳定 key；NestSVG 内部已订阅 renderTick 自更新，不需要 NestsGrid 介入高频重绘。

## US-004 关键约定（ControlPanel 调用方 / 改动方必读）

- **表单字段全字符串存储**：`FormState`（lib/params.ts）的 number 字段（time/seed）+ per_type 单级 `Record<g码, PerTypeFormValue{d,tol}>` 的 d/tol 都按 input.value 字符串持有。理由：per_type 必须「空串 = 继承默认」与「"0" = 显式 0」可区分（旧 vanilla 实现 inp.value.trim() !== '' 同口径）。2026-08-18 回退 US-004 两级嵌套；sizeKey 概念只在 quantities 域（serializeQuantities）。
- **collectParams(form) 纯函数（单级遍历；2026-08-18 回退 US-004 双层遍历）**：params 永远全 0（US-019 起主面板输入已删）；per_type 按 label 单层遍历，仅 trim() !== '' 档写入（缺档省略）、双档全空白剔除、整体空 → null；输出 `PerTypeOverrides = Record<g码, {d?, tol?}>`（WS payload 形状，与后端 build_instance label 命中一致）。任何修改必须同步 `lib/__tests__/params.test.ts`（collectParams 组）+ AC#2 默认值断言。
- **DEFAULT_FORM 与旧 index.html 默认 1:1**：d_int="10"、其余 0；time="60"、seed="0"；per_type 全空。**US-017 起 sizes 默认 `[]`（不再是 `[...SIZES]` 全选）**，强制用户选；SizePicker chip 列表来自 uploadStore.doc 动态渲染。改默认值需同步 AC#2 + params.test.ts + SizePicker.test.tsx。
- **ControlPanel 不调 useSolveRun**：仅 onStart(cfg) 透传到 App，App 决定是否调 useSolveRun.start（解耦多 seed / 重连 / clear 时机）。
- **DOM id / className 沿用 legacy**：`id="start" / id="status" / id="time" / id="seed"` 等保留（CSS 选择器依赖）；`.sizes / .chip / .preset` 等 className 1:1。US-008 清理 CSS 时再统一去 id。（`.per_type .pt-row` 旧折叠面板 class 已随 US-018 按钮化 + US-004 矩阵化删除。）
- **~~PerTypeOverrides 行序 = V03_PTYPES 顺序~~（已废）**：V03_PTYPES 固定 10 片型清单已删（裁片编号化 US-003）；高级配置列集 = /api/ptypes reps 键 ∪ per_type 已配置键动态并集，`compareByLabel` 数值序（详见 US-018 节单级表格结构条目；2026-08-18 回退 US-004 矩阵化）。
- **React 18 + jsdom 单测输入模拟**：number input 必须用 `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set` native setter 设值后再 dispatch `input` event，否则 React 的 value tracker 检测不到变化（见 ControlPanel.test.tsx AC#6 fill per_type 用例）。

## US-002 关键约定（hook / Registry 调用方必读）

- **WS 连接只在 `start(cfg)` 显式 new**：不要在 useEffect 里 auto-connect，React 18 StrictMode 双 mount 会双连。
- **frames 是 mutable 引用**：`runRegistry.list()` 返回的 RunRecord 本身可被 push，**不进 React state**；高频重绘由 US-003 renderTick 单字段节流。
- **per_type 空 → 序列化为 null**（与旧 vanilla 实现 collectParams 一致；Python `or None` 接住）。
- **density 双口径**：`FrameMsg.density` 是原面积·**输入幅宽**口径（`total_area/(width*gate_mm)`，2026-08-28 版师定案起与后端 `_apply_density_dual` 同式单一口径，90% 生死线以此为准；较旧 min(gate,1910) 分母 −~3.5pp，跨口径数据不可直接比），`density_sparrow` 是 erode 后 sparrow 自报（参考）。任何决策 / 显示优先 density。
- **不重连**：onclose / onerror 触发 `onDone`（done flag 防重复），交由调用层决定是否重启。
- **测试**：`npx vitest run`，需 `(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;` 才能 avoid act warning；Mock WebSocket 用 ctor 返回 mock 实例的方式（`new WebSocket(url)` 直接拿到 mock）。

## US-003 关键约定（NestSVG / 节流闸 调用方必读）

- **React 只渲染空骨架一次**：`NestSVG` JSX 仅返回 `<svg ref={svgRef}/>`；所有子节点（bg / 用布矩形 / 翻换组 `<g>` / N 个 `<polygon>`）全部 imperative 创建，由 `useRef` 持有。
- **实际排料边界红虚线已删（2026-08-28）**：`gate_nest_mm` 协议字段随「输入幅宽 = 实际幅宽」单一口径整体移除，前端不再有第 4 个骨架节点 `<line>`；`NestSVG.plotSafeLine.test.tsx` 整文件同删。
- **翻转组 transform 必须用 setAttribute 写**：`translate(0 ${gate_mm}) scale(1 -1)`，**不走 JSX prop**，否则 React reconciliation 会用 vdom 覆盖回旧值。
- **renderTick 单字段节流**：`useAppStore` 只持 `renderTick` 一个字段；`useRafThrottle(active)` 在 active=true 时每 100ms bump 一次；NestSVG / NestLabel 通过 `useAppStore(s => s.renderTick)` 订阅 → useEffect 重跑 → setAttribute imperative 更新。frames 仍 mutable push 到 runRegistry。
- **pointsStr(poly, rot, tr) 字节级对齐旧 vanilla 实现**：rad=rot*π/180，c=cos, s=sin，`x'=x*c−y*s+tx`，`y'=x*s+y*c+ty`，每点 `r2(x),r2(y)`，空格分隔。改这个函数必须同步后端 `_transform_polygon` 和 `lib/__tests__/geometry.test.ts`。
- **flipRef 幂等保护**：建 DOM 的 effect 用 `if (run.manifest && !flipRef.current)` 防御 React 18 StrictMode 双 mount / 多次 bump tick 重复建。清空只在 unmount 时发生（React 自动 GC svg 子树）。
- **viewBox 用历史最大 width 作稳定锚**：`W = max(run.viewBoxMaxW, lastFrame.width_mm, 1)`，避免收缩抖动；用布矩形按当前帧 `width_mm` 收缩（直观看到省布过程）。
- **manifest 到达后 DOM 才建**：mount 早于 manifest 时 effect 早 return；manifest 到达后下一次 renderTick bump 才建。后到 manifest 测试覆盖此路径。

## US-031 关键约定（nestingTour 5 步 + runRegistry 帧快照联动 调用方必读）

- **5 步序列：doc-banner / params / solve / result / export**（与 PRD 字面一致）。前 3 步告知型（无 ready，点下一步直接推进）；后 2 步联动型（ready 读 runRegistry 帧快照，ready()===false 切等待态 + 200ms 轮询，true 时自动推进；最后一步 export 自动完成 = markSeen('nesting') + close）。收敛曲线并入 result 步气泡附带提及（不单独高亮 / 不单独锚点）；回放 PlaybackBar 非主流程不单独成步。
- **ready 谓词读 runRegistry 模块级单例，不读局部 SolvePhase**：NestingPage 的 `phase: SolvePhase` 是 useState，tour 模块无法从外部读取（不是 React 组件，无 hook context）。`runRegistry` 是模块级 mutable 单例（`store/runRegistry.ts`），所有 useSolveRun 实例共享 —— start() 时 `create(seed)` push、WS 推 frame 时 `rec.lastFrame = msg`。故 `runRegistry.list().some(r => r.lastFrame !== null)` 等价于「用户已真实点开始求解并收到至少一帧」。**改 ready 口径需同步 nestingTour.test.tsx 测 1/2**。
- **advance-on-ready 统一 200ms 轮询（已在 US-030 useTour 落地，nestingTour 复用）**：runRegistry 无 React 订阅能力（是纯 mutable 数组），advance-on-ready 不订阅 store 变化，而是 useTour 内 `setInterval(200ms)` 调 `ready()` 重读快照。ready 翻 true 后停轮询 + 自动推进。close / stepIndex 变化 / unmount 时 clearInterval（无泄漏，US-030 useTour.test.tsx 测 5 覆盖）。
- **5 个 data-tour 锚点解耦 CSS 类名**：`[data-tour="doc-banner"]`（ControlPanel.tsx `.doc-banner`）/ `[data-tour="param-form"]`（SizePicker.tsx `.field` 根容器）/ `[data-tour="start-btn"]`（ControlPanel.tsx 内 SolveControls 父 `<div>` 包裹）/ `[data-tour="nest-wrap"]`（NestingPage.tsx `.nest-wrap`）/ `[data-tour="export-group"]`（ExportButtons.tsx `.export-group` 根）。querySelector 命中首个即可，与 CSS class 重构解耦。
- **SolveControls 父容器包裹（不侵入 SolveControls 自身）**：ControlPanel.tsx 在 `<SolveControls/>` 外包 `<div data-tour="start-btn">`，SolveControls.tsx 仍返回单一 `<button>`（保持纯受控 + 测试 `button#start` 查询不破）。包裹 div 仅作 tour 锚点 + 不影响 CSS（`button#start` CSS 选择器与父容器无关）。running 态 SolveControls 渲染 `#stop`，父 div 的 `data-tour="start-btn"` 仍在 DOM 但 tour 不查询（仅 idle 态在 step3 时查询）。
- **before 副作用 ensureNestingTab（5 步均调用）**：用户从 preview Tab 用菜单「重看超排指引」（US-032 落地）触发时需切回 nesting。幂等：`if (activeTab !== 'nesting') setTab('nesting')`。setTab 受 nestingEnabled guard 兜底（未解锁不切），与真实流程一致（commit 后才解锁 nesting Tab）。
- **首次进 nesting Tab 自动触发**：US-030 useTourAutoTrigger 已读 `TOURS[tab]` 判断该 Tab 是否有指引；TOURS.nesting 注册后自动生效（!seen.nesting && 无 tour 运行 → 延迟 300ms start('nesting')）。seen.nesting 在 export 步自动完成时 markSeen 写入（localStorage 持久化，下次进 Tab 不再自动触发）。
- **nestingTour.test.tsx 5 项单测覆盖**：测 1/2 直接调 `nestingTour.steps.find(s=>s.id==='result'/'export').ready!()`（纯 runRegistry 快照读，不挂 React）；测 3 挂 NestingPage（StrictMode + stub fetch /api/ptypes 防 act warning），5 个 data-tour 锚点全部 querySelector 命中；测 4/5 验 5 步 id 序列 + 前 3 告知型 / 后 2 联动型结构稳定性。**改 step id / ready / selector 需同步测 3/4/5**。
- **不引入 CSS 框架**：nestingTour 复用 US-029 落地的 `.tour-overlay/.tour-spotlight/.tour-bubble/.tour-btn-*` 全套样式（暗背景 #26282e + #2ea06c 同色系）。无新 CSS。
- **未做浏览器验证（chrome-devtools-mcp 不在本会话工具集）**：本 Story 无 SVG/坐标变换（仅加 DOM 锚点 + tour 步骤定义 + runRegistry 快照读），核心 advance-on-ready 逻辑用 US-030 useTour.test.tsx 5 项 + nestingTour.test.tsx 5 项 + TourOverlay 6 项覆盖（fake timers 验证轮询推进 + close 无残留 + ready 快照读取）。端到端浏览器回归（上传→commit→进超排→tour 自动起→开始求解→step4/5 自动推进→导出）留作 US-032 集成时统一核对。



- `npm run dev` 启动后 Vite 监听 `localhost:5173`，**curl 必须用 `localhost`**（不是 `127.0.0.1`），Windows 下后者可能 connection refused。
- `tsconfig.node.json` 必须 `composite: true`，否则 `tsconfig.json` 的 references 报错。
- `@types/node` 是 vite.config.ts 隐含依赖，不能省。
- 修改 `vite.config.ts` 后必须重启 `npm run dev`（Vite 自身配置不热重载）。
- `static/` 是构建产物 —— **不要手改**，改了也会被下次 `npm run build` 覆盖。
- **不要在 useEffect dep 里直接列 mutable run**：run 引用不变（registry 持有），effect 实际靠 renderTick 触发；写 `[renderTick, run]` 即可（run 只是稳定引用）。
- **写文件含 Chinese 字符 + bash heredoc 易踩坑**：用 `cat << 'EOF' > file` 单引号 heredoc 时，bash 仍可能因内部 `''`/`\'` 解析失败；安全做法是分多段 append（`cat >> file <<'TESTEND'` 多次），或用 Python heredoc 套外层（注意 `r'''...'''` 与 bash 单引号的冲突）。
- **多 seed all-done 检测不能用 `useState(doneCount)`**：每次 start 闭包值不同，onDone 内读到的是旧值；改用 `useRef` + 手动重置（US-005 落地）。
- **Mock WebSocket 必须定义静态常量 CONNECTING/OPEN/CLOSING/CLOSED**：`stop()` 内 `ws.readyState === WebSocket.OPEN` 判 OPEN；Mock 替换 `globalThis.WebSocket` 后，若 mock ctor 无静态常量则 `WebSocket.OPEN===undefined`，stop() 永远不发。见 useSolveRun.stop.test.tsx MockWebSocketCtor（US-027 踩坑修复）。

## 矩阵化重构 US-003 关键约定（拆除旧交互+预览页集成+全 0 拦截 调用方必读）

> **⚠️ 本节 ParsedPiecesView 相关条目已被后续演进取代**：①图形预览区拆除 —— ParsedPiecesView 组件已删除，右侧主体仅 QtyMatrix；②「份 = 配对片 1 份 L+R 2 物理片」口径已随裁片编号化 US-003 改为「一份 = 母版一个轮廓」（Σ 数量口径，数量即一切）。本节其余条目（唯一入口/全 0 拦截/线格式）仍现行有效。

- **数量编辑唯一入口 = QtyMatrix**：SizeTabs/PieceQtyDialog/Switch 已删除（含测试）；`grep openQtyDialog src/` = 0，uploadStore 无 qtyDialog 字段（zoom/activeSize/setSize 保留，矩阵行头/缩略图依赖）。重建任何「点数量弹窗」交互都属回退。
- **~~PreviewPage 主体 = QtyMatrix + ParsedPiecesView~~（已废）**：图形预览区拆除后右侧主体仅 QtyMatrix；顶层模态仍仅 PieceZoomModal（唯一放大入口 = 矩阵行头缩略图，`openZoom(label, rep.size)` 所见即所放大）。doc_id→hydrate/resetQuantities 与 status→setNestingEnabled 两条 subscribe effect 原样保留。
- **~~ParsedPiecesView 只读化~~（组件已删除）**：数量单位统一「份」（裁片编号化 US-003 起现行口径：一份 = 母版一个轮廓，Σ 数量求和无乘数；~~FR-9 配对 ×2~~ 已废）。
- **ControlPanel.handleStart 全 0 拦截**：`computeTotalCutPieces(doc, form.sizes, qtyStore.quantities) === 0` → `onStatus('所选码号有效裁片数为 0，请先在上传预览页数量矩阵中设置数量')` + 不发 WS start（防空 items 实例交 spyrrow 密度分母 0）。返回 null（doc=null fallback 开发模式）不拦截。改判定需同步 ControlPanel.test.tsx 5 项 start guard 用例。
- **线格式回归基线**：矩阵格内改 A@28=2 → handleStart payload `quantities.A['28']===2`（serializeQuantities 过滤未勾选码、显式 0 保留、'null' 兜底 —— 矩阵化重构 US-001 不变量延续）。ControlPanel.test.tsx 有对应回归用例。
- **previewTour 锚点已迁矩阵（US-005 落地）**：parsed 步锚点 `[data-tour="qty-matrix"]`（QtyMatrix 根容器）、set-qty 步锚点 `[data-tour="qty-rowhead"]`（行头 th，querySelector 命中首行）；旧 `size-tabs`/`piece-card-head` 选择器与 ParsedPiecesView 卡片头的死锚点属性均已删除；TOUR_VERSION '1'→'2'（后经 '3'~'7' 连续 bump，现行 '7'，见 tour index 行）。改 selector / 增删步骤必须 bump TOUR_VERSION（US-032 版本号策略 + index.ts 版本历史注释）。
- **浏览器端到端验证留作整体回归**：本会话工具集无 chrome-devtools-mcp（与 US-032 同况）；已覆盖 npm build + ms-web 冒烟（GET / 200 + parse API 200）+ jsdom 单测全绿（US-005 收口 605 项，含 previewTour.test.tsx 锚点渲染命中 5 项）。

## 矩阵化重构 US-004 关键约定（parse 透传 ptype/paired + 物理片数口径 调用方必读）

> **⚠️ 本节已整体被裁片编号化重构取代（2026-08-18）**：`ptype`/`paired` 字段已从 parse 响应契约与 `ParsedPiece` 类型删除（GROUP_NAMES/PAIR_TYPES 后端整体退场），QtyMatrix/SizePicker 小计回到 **Σ 数量口径（无乘数，一份 = 母版一个轮廓）**，×2 徽章不渲染。本节仅作历史落地记录，勿按本节实现。

- ~~**ptype/paired 是 additive 可选字段**~~（字段已删）：~~`ParsedPiece.ptype?: string` / `paired?: boolean`~~。
- ~~**物理片数口径只活在展示层**~~（已回 Σ 数量口径）：行/列小计与总片数 = Σ demand（无乘数）；WS `quantities` 线格式仍是「份」口径（serializeQuantities 零改动 —— 该不变量延续）。
- ~~**乘数按 (label, size) 逐格取**~~（multOf/pairedOf/rowPaired 已删）。
- ~~**配对徽章**~~（`.qty-paired-badge` ×2 已删，QtyMatrix.test 断言其不渲染）。
- **全 0 拦截语义不变**：`computeTotalCutPieces === 0` ⟺ 全 demand=0；ControlPanel.handleStart 拦截逻辑零改动（乘数删除后此条自然成立）。
- ~~**后端同源**~~（assign_group_no/GROUP_NAMES 链路已删；后端现行赋码单一真相源 = `nesting_engine/labeling.assign_codes`，parse 与 commit 同函数同输入 → 同 g 码，详见 materialSorting-server 各 AGENTS.md）。

## 矩阵化重构 US-005 关键约定（tour 锚点迁矩阵 + TOUR_VERSION bump 调用方必读）

- **previewTour 锚点只落 QtyMatrix**：parsed 步 = `[data-tour="qty-matrix"]`（根容器；图形预览区拆除后文案指引矩阵 + 行头缩略图放大，不再指引图形预览区）；set-qty 步 = `[data-tour="qty-rowhead"]`（每个行头 th 都带，querySelector 命中首行；doc 非空 ⟹ 行数 ≥1，锚点恒在）。ParsedPiecesView 的旧 `data-tour="piece-card-head"` 已删（死锚点不残留）。重建旧锚点属回退。
- **TOUR_VERSION bump 与锚点/步骤变更强绑定**：`'1'`（US-030 首次落地）→ `'2'`（US-005 锚点迁移）→ `'3'`（图形预览区拆除）→ `'4'`（矩阵行头简化）→ `'5'`（行级整行设值回归）→ `'6'`（数量矩阵行列转置）→ **`'7'`（现行，裁片编号化 US-003 Σ 口径）**；tourStore init 检测 storedVersion 不一致自动清全部 seen（老用户下次进 Tab 自动重看）。改 selector / 增删步骤 / 改 ready 语义必须 bump 并更新 index.ts 文件头版本历史；仅文案微调不 bump。
- **改 previewTour 步骤定义需同步 previewTour.test.tsx**：5 步 id 序列 / parsed+set-qty selector 精确值 + 旧选择器零残留 / TOUR_VERSION 值（现行 '7'）/ 文案关键词（矩阵/行头/缩略图/整列设值）/ 锚点在渲染后 QtyMatrix 上 querySelector 命中，共 5 项。TourOverlay.test.tsx 的 step1 mock 元素也用 `qty-matrix`（跟真实 selector 走）。
- **文档三处口径（改动后自查）**：`.docs/technical/agent-component-map.md`（覆盖清单 + 文件树 tour 行 + US-005 节 + US-008/014/030 节警告头）、`.docs/business/business-overview.md` 工作台交互 1/2 条、`CLAUDE.md` 数据流主线 —— 现行架构描述不得残留 SizeTabs/piece-card-head 数量编辑交互（历史落地段落除外，须带「已被矩阵化重构取代」警告头）。

## 策略 PRD US-006 关键约定（应用到主画布与导出闭环 调用方必读）

- **applyStrategyResult 住在 NestingPage，prop 链单向**：NestingPage → ControlPanel(`onApplyStrategy?`) → StrategyRunButton → StrategyRunModal（弹窗零改动 —— 只在回调缺席时 disabled）。不要把应用逻辑下沉进 strategyStore（它是「运行观测」中心，不是主画布 registry 的所有者）。
- **合成 RunRecord 与 WS 消息同形（一字段不差）**：manifest = result.manifest + `type:'manifest'` 判别键（result 端点 build_pid_meta 快照口径：erode 后几何与 placed_items 对齐、demand 已含 → NestSVG 副本池按 demand 建 N 份承接多副本 placement）；frames=[合成帧]（type:'frame'/index/elapsed/phase:'final'/density 双口径/width_mm/placed_items）+ lastFrame 同帧；finalDensity/finalDensitySparrow = best 双口径；viewBoxMaxW=best.width_mm；done=true/ws=null/stopped=false。下游（NestSVG/ConvergenceCurve/PlaybackBar/ExportButtons/useExport/bestRun()）对合成 record **零特判**。
- **应用 = 显式清场置换，绝不自动应用**：runRegistry.clear()（关旧 WS —— 会清掉主画布现有对比 run，破坏性操作由用户点击确认）；函数开头 `if (phase==='running') return` 兜底双保险。计数 ref 同步重置（doneCountRef=0/totalSeedsRef=1，防残留 onDone 闭包误判覆写状态行）。
- **导出链路零改动**：apply 后直接点既有「导出」（bestRun() 选中合成 record → POST /export placed）；母版变更后应用导出 pid 失配走后端既有 400 + 前端错误文案透传，**不在 apply 里做 pid 预检**。
- **result 常驻（US-005 不变量延续）**：关弹窗再开仍可应用；只有下一次 start/reset 才清。改 strategyStore 不得在 modal 关闭路径清 result。
- **测试基线**：`src/components/__tests__/NestingPage.test.tsx` 5 项（registry 恰 1 条字段齐全 / phase done+状态行+seekbar / ExportButtons 解禁+多副本渲染 / 导出载荷=合成帧 / 不点 apply registry 不变）。改 applyStrategyResult 或 RunRecord 字段需同步该文件。

## 腰头成带 US-013 关键约定（布局设置弹窗 / band 闸门·互斥 调用方必读）

> **⚠️ 2026-08-22 简化**：预演回显（POST /api/band/preview）、ack 硬警告二次确认、填料混带（US-015）、bandStore 单向镜像与 QtyMatrix「不成对」警告已整体删除 —— band 主流程收敛为「勾选 + 选腰头 g 码」两步，`BandConfig` 恰 `{enabled, label}`。本节仅保留现行有效条目。

- **band 草稿二元组 `{enabled, label}`，confirm 是唯一回写路径**：PerTypeOverridesModal mount 从 props 读初值，确定写回 `onBandChange`（ControlPanel patch form.band_* 两字段）；取消/遮罩/ESC 连同草稿丢弃（与 per_type 同约定）。未勾选时 label 原样保留（collectBand 对 enabled=false 恒 null）。
- **band 启动闸门（AC#3）**：`bandMissingLabel`（开未选编号）/ `bandZeroQty`（`bandMemberCount===0`）→ `startDisabled` 置灰 + StatusLine band 段具体文案（` — ` 连接）+ handleStart 运行时兜底。bandMemberCount 三态与后端 `_parse_band`/`build_pid_meta` 口径对齐（US-012 不变量延续）。
- **band×策略互斥（FR-6）**：band 开启 → strategy-btn `disabled` + `title="腰头成带与策略运行互斥：请先在高级配置 → 布局设置中关闭腰头成带"`；关 band 即恢复。后端不参与（strategy_start 白名单键天然不含 band）。
- **不合适 g 码的守卫在后端**：带内填充率 <45%（如皮带袢长条）→ 后端 `BandQualityError` → WS `{type:'error'}「成带失败」`早退；前端无形态预判（ack 启发式删除后 `FILL_FLOOR_PCT` 是唯一守门人），用户换 g 码即可恢复。
- **下拉值域 ∪ 当前选中 label**：`bandOptions = orderedLabels ∪ bandLabel` —— 已确认 label 在 reps/values 均缺席（fetch 失败/未配置）时仍显示为选中项（受控 select 的 value 缺 option 会显示空白，band 状态不可见）。
- **测试基线（简化后）**：PerTypeOverridesModal.test.tsx 布局设置 describe（分区渲染 / 未勾选 disabled+初值 / 勾选启用 / 下拉值域降级 / confirm 写回 `{'enabled': true, 'label': 'g01'}` / 取消丢弃 / 缩略图双层 modal）；ControlPanel.test.tsx（band 确定写回 → payload band = {enabled,label} / band×策略互斥两条）；params.test.ts collectBand 三态（关恒 null / 开+非法 null / 开+合法恰两键）。

## 起始端成套 US-004 关键约定（prefix 布局设置 / 闸门·互斥 调用方必读）

- **prefix 草稿三元组 `{enabled, front, back}`，confirm 同 band 通道**：PerTypeOverridesModal mount 读初值，确定 `onPrefixChange`（ControlPanel patch form.prefix_* 三字段）；取消丢弃。未勾选时 front/back 原样保留（collectPrefix 对 enabled=false 恒 null）。**无尺码下拉**——资格码由后端选定（2026-08-25 `pick_prefix_size` seeded 随机决策②；**2026-09-02 起 `select_prefix_plan` 几何搜索确定性选定，seed 仅兜底路径**），stage 消息 size 回显。
- **默认预选启发式（决策⑤）**：勾上且 front/back **均空**时 `defaultPrefixLabels(uploadStore.doc)` 预选面积最大两片（每 label 取其全部码片 polygon shoelace 面积最大值，降序前二；5336 = g02 前/g03 后）；已有选择不覆盖。启发式只是缺省建议，非片型识别（PRD 非目标）。
- **资格码本地预检不阻塞**：`prefixEligibleSizes(sizes, quantities, front, back)` 与后端 `_parse_prefix` 同口径（两码 perSize demand 均 ==2、missing→0、'null' 跳过、sizes 过滤）；空集 → 勾选区警示「当前数量无 2+2 资格码」（不阻塞 band、不置灰 #start —— 权威拦截在后端结构化 error 早退）。front==back 警示优先于无资格码。
- **prefix 启动闸门**：`prefixMissingLabel`（开未选前/后幅）/ `prefixSameLabel`（front==back）→ #start 置灰 + StatusLine prefix 段文案 + handleStart 兜底（band 同款双保险）；与 band 可同开（双开带位只记录是后端 US-003 行为，前端无额外控件）。
- **prefix×策略互斥（v1）**：prefix 开启 → strategy-btn `disabled` + `title="起始端成套与策略运行互斥：请先在高级配置 → 布局设置中关闭起始端成套前后幅"`（/api/strategy/* 的 prefix 支持是二期接口备注；band 2026-08-22 已解禁，prefix 仍锁）。
- **stage='prefix' 状态行不进 phase 五态**：NestingPage onStage 分支 →「起始端成套构造中（尺码 {size}）…」秒级提示（size 由 stage 消息回显，前端无法预知几何搜索结果）；**2026-09-02 补片双形态**——extra_label/extra_size 在案 →「…（尺码 A＋{extra_label}@{extra_size}）…」（＋全角；null 与键缺席同判回落现行形态，旧后端安全）；rec.stage 持最后一条（双开时 band→prefix 序，回调带 msg 本体判别，extra_*/residual_mm 随本体透传）。
- **测试基线**：params.test.ts（collectPrefix 三态 + prefixEligibleSizes 2+2 五态 + defaultPrefixLabels 面积预选/平手字典序/不足两 label + collectStartContext.prefix）；useSolveRun.test.tsx（prefix 透传三态 + 双开独立键 + stage(prefix) 分发不 finish）；PerTypeOverridesModal.test.tsx prefix 分区（勾选预选/警示两态/取消丢弃/confirm 回写/未勾选 disabled）；ControlPanel.test.tsx prefix 接线（闸门两态置灰文案 / payload prefix 三键 / 策略互斥 title）。浏览器 28/28：scripts/us004_prefix_verify.mjs（CDP harness，截图 out/us004_prefix_verify/）。
- **US-005 端到端验收冒烟（2026-09-02 收官，prd-prefix-extra-piece）**：`scripts/smoke_prefix_extra.mjs`（CDP 全链路，模板 smoke-band-preview；29/29 PASS，报告 `out/smoke_prefix_extra/report.json`）——上传 5336 → 数量矩阵 Σ105 → per_type g02/g03 d=2/tol=1 → 开 prefix → 预览 5 片 + hint「＋ 顶部 g02@32 异码片 · 余 1.55mm 近满幅」→ 求解状态行「尺码 38＋g02@32」→ 形态判据（贴触/interleave/近满幅/min_x 锚定）→ final 无 placed_items 键 + 末帧 placed=105 守恒 + `PS_` 零泄漏 → 导出 PLT（fetch 抓包字节 grep b'PS_' 缺席）→ prefix_runs 工件 5 成员快照。改 prefix UI 链路（预览缩略/状态行/导出）后应复跑本脚本回归。

## 多会话 US-005 关键约定（前端会话接入与阻断弹窗 调用方必读）

后端多会话（sessions.py 注册表：容量 4 / 10 分钟空闲过期 / 过期墓碑 1h）的前端侧接入，2026-08-27 落地。

- **唯一裸 fetch 出口 = `lib/api.ts` 的 `apiFetch`**：全站 HTTP 请求（useParseDxf / useCommitToNesting / useExport / ptypeStore / strategyStore×3 / PerTypeOverridesModal×2）一律走它 —— `grep 'fetch('` 应仅命中 `lib/api.ts`。新增网络请求**必须** apiFetch（结构性带 `X-Session-Id`，不落 default 会话）；裸 fetch 会绕过会话先行门与阻断拦截。
- **sid 单一真相源 = `lib/session.ts` `getSessionId()`**：localStorage 键 `ms_sid`，uuid4 hex 32 位，get-or-create（非法落盘值重铸），刷新不变。直接 import 仅 `lib/api.ts`（Header 注入）与 `lib/ws.ts`（?sid= 拼接）两处；组件层不碰 sid。
- **会话先行门（mount 竞态修复）**：React 子组件 effect 先于父组件跑 —— NestingPage 策略轮询 mount 即发请求会先于 App 探测到达后端吃 401 误弹「已过期」。apiFetch 首次调用统一 `await ensureSession()`（模块级 once-promise，POST /api/session 并发共享）；探测落定后 `probedSettled` 置位，后续调用同步直进 fetch（行为与旧裸 fetch 逐字节一致）。
- **阻断三件套**：① 拦截 —— apiFetch 对 401/429 响应 `res.clone().json()` 读 `code` 键（session_expired / session_limit 才触发；400 无 code / 网络错不触发）；WS 侧 useSolveRun case 'error' 同判 `msg.code`。② 触发 —— `triggerSessionBlock(code)`（幂等，首个 code 定终身；HTTP/WS 共用）→ SessionExpiredModal（useSyncExternalStore 订阅，阻断式全屏 z 3000，**无任何关闭路径**，唯一出口 = 「刷新页面」按钮 location.reload()；文案与后端 PRD 逐字一致）。③ swallow —— 阻断期间 apiFetch 直接抛 `SessionBlockedError`，**请求不发出**（调用方现有 catch 落自己的 error 态，被弹窗遮住不可见）。
- **session_expired 弃 sid / session_limit 保 sid（墓碑出口）**：后端墓碑保证过期 sid 1h 内不可重建 —— 刷新仍带旧 sid 只会探测 401 死循环。故 triggerSessionBlock('session_expired') 顺手 `clearPersistedSessionId()`（清 localStorage + 模块缓存），刷新即铸造全新 sid 获得干净会话；session_limit 会话本身仍有效，保 sid 稍后重试原会话续用。
- **mergeSessionHeaders 归一普通对象**：调用方 headers（Headers 实例 / 数组 / 对象）合并 sid 后返回 **plain object**（不用 Headers 实例 —— 调用方与测试可按 Record 属性直取的旧口径保持）。
- **测试钩子**：不关心会话语义的存量用例 beforeEach 调 `markSessionProbedForTest()`（预置已探测，apiFetch 不前置 POST /api/session，fetch 计数 / 首调 URL 断言零改动）；`resetSessionForTest()`（清阻断 + 探测态）；`resetSessionIdForTest()`（仅清 sid 模块缓存，不动 localStorage）。lib 层不引 zustand（阻断态是模块级 pub/sub），组件用 React 18 useSyncExternalStore 订阅。
- **浏览器验证**：`scripts/us005_session_verify.mjs`（playwright，主相位 P1-P5 + `--expire` 过期相位 E1-E5；主相位前置 = 重启 ms-web 保注册表 4 空席，过期相位前置 = `MS_SESSION_TTL_SEC=6`）。实测 15/15 + 5/5：双窗口上传互不串台三层取证（弹窗 thead 徽章限定 `.per-type-modal` —— 上传预览 QtyMatrix 同名徽章全局选择器会假阳性；ptypes 响应体直取对比；g01 缩略图 polygon 对比）、WS ?sid=、第 5 窗口加载即弹「用户过多」、阻断期间上传 0 请求、过期 → 弹窗 → ms_sid=null → 刷新新 sid 无弹窗。

## 极限运行 US-003 关键约定（双家族 store/轮询 · 极限弹窗 调用方必读）

「极限运行」前端入口（2026-08-29，extreme PRD 第三块）。核心 = **泛化优先于复制**：store 工厂 + 轮询参数化 + 弹窗四态组件导出共享，新增第三/第四个运行家族时按此范式扩。

- **strategyStore = 家族工厂 `createRunStore<P>(spec)`**：`RunFamilySpec{base,ownsMode,netError}` → `useStrategyStore`（/api/strategy）/ `useExtremeStore`（/api/extreme）双实例；改任一家族的 start/stop/refresh/reset 行为改工厂，不要单边 hack。**refresh 家族过滤是命门**：后端两族共享每会话状态槽，本族端点会看到对方家族的 running（mode 透传）—— 只认领 `state==='idle' || spec.ownsMode(st.mode)`（strategy 认 undefined/null/se/race、extreme 只认 'extreme'；idle 恒认领 = stuck 'starting' 的复位出口）。gen 计数器丢弃陈旧在途回包。
- **useStrategyPoll 参数化 `useStrategyPoll(open, store)`**：store 缺省 useStrategyStore（存量调用零改动）；**每族入口按钮恰挂一实例**、各轮询自己的端点，弹窗自身不挂轮询（防双跑不变量延续）。idle 态轻量（mount/open 翻转各一次 refresh，interval 只在 starting|running）。
- **StrategyRunModal 四态组件已导出共享**：ProgressState（`modeLabel?` 覆盖标题默认「策略运行」）/ ResultState（`extraHint?` 渲染 `strategy-result-extra-hint`）/ ErrorState / OrphanState。extreme 弹窗只自写配置态；**复用组件的 inner testid 仍 `strategy-*`**（smoke/测试按此断言，勿另起 extreme-progress-* 一套）。
- **极限载荷 = collectStartContext 同源 + `time_total_s`**：band/prefix **2026-08-30 起透传**（`ctx.band`/`ctx.prefix` 原形态随载荷下发，与 StrategyRunModal 同款；此前「恒不写键 + `extreme-layout-warning` 置灰警告」拦截已废止）；开启时弹窗显只读状态行 `extreme-layout-hint`（「将随排料参数生效：腰头成带 g05 · …」，参数本体只在高级配置里配）。409 互斥文案后端已带 mode（「已有进行中的极限运行/策略运行…」），前端 error 态透传即天然区分对方，勿前端改写。
- **轮数公式镜像常量**：`EXTREME_FIRST_ROUND_S=602.5` / `EXTREME_PER_ROUND_S=347.5`（与 cli.portfolio race_plan 同口径）→ `estimateExtremeRounds(T)=max(1,1+floor((T−602.5)/347.5))`：60min→9 / 120min→19（默认档）/ 240min→40 / 480min→82 / 16min→2。自定义 16~720 整数（`parseCustomMinutes` 越界/非整 → null → 置灰 + 提示）。改后端轮次口径须两处同步。
- **参数完全隐藏**：弹窗不出现 exploration_pct / early_termination / num_workers / quadtree_depth 字样（无输入无下拉）；结果态只一句「已固化实验参数（按实验结论固定，不可调）」（extraHint）不列值。`result.mode='extreme'` 而 `summary.mode='race'`（CLI --extreme 内部展开 race）—— 判据只用顶层 mode。
- **结果应用复用 applyStrategyResult**（US-006 约定延续）：ExtremeRunModal 应用按钮 → onApplyExtreme → 同一 NestingPage 函数，合成 RunRecord 链零改动；状态行按 mode 区分「极限/策略 run 已应用」。
- **smoke：`scripts/smoke-extreme-run.mjs`**（playwright msedge→chrome，范本 smoke-band-preview）三坑记档：① 超排 Tab 解锁联动 **parse done** 非 commit done —— 须等 `[data-testid="commit-status"].done`（`.upload-status.done` 同时命中 parse-done 元素不能只按 class 等）再进 Tab，否则极限 start 吃 422「排料数据为空」；② fresh context = 新 sid（MS_SESSION_MAX=4/TTL 600s）连跑多轮会 429 session_limit → 重启 ms-web 恢复；③ stopped 后 result 拉取异步先闪「正在读取运行结果…」→ 断言等 `strategy-result-head`。US-017 起默认码号空：进 Tab 后先勾 `.sizes .chip input`（id=`sz_<key>`）前两个再执行。
- **测试基线**：`src/store/__tests__/extremeStore.test.ts` 7 项（载荷契约无 band/prefix / 409 透传 / 家族过滤双向 / result 恰拉一次 / stop / reset）+ `ExtremeRunButton.test.tsx` 4 项 + `ExtremeRunModal.test.tsx` 17 项（公式对拍/预设切换/自定义域/参数隐藏/band 闸门/载荷等值断言/三态渲染/ESC 遮罩 ✕ 不 stop）。改家族工厂或弹窗须同步。

## 极限运行入口速查（US-004 补，2026-08-29）

前端「极限运行」入口三件套与验收锚点，细节约定见上「极限运行 US-003 关键约定」：

- **入口链**：`ExtremeRunButton`（与 StrategyRunButton 并排 `.strategy-entry-row`）→ `modal==='extreme_run'` 单例 → `useExtremeStore`（/api/extreme，家族工厂第二实例）→ 后端 spawn `ms-run-config <cfg> --name web_[<sid6>_]extreme_<rand6> --extreme --time <T> --quiet`。CLI 对应 `ms-run-config <cfg> --extreme --time <T>`（参数展开同源，`--extreme-budget` 仅 600/1200）。
- **参数固化为黑盒**：p0.70/et0/workers4/depth4（缺省）在 CLI `EXTREME_SOLVER_OPTS` 单点定义，web 无参数透传面；弹窗只收总时长（60/120 默认/240/480 分钟或自定义 16~720）+ seed/gate/码号/配比（collectStartContext 同源）。
- **轮数预估口径**：`estimateExtremeRounds(T)=1+floor((T−602.5)/347.5)`（首轮全程 602.5s + 每轮 ~0.85 门段 0.15 全程 ≈ 347.5s 期望）；「实际轮数 ≥ 预测（省出预算自动多跑）」。
- **验收**：同总预算 4h 三臂对拍（--extreme vs --strategy race 默认档 vs 均分 600s×24）报告 `.docs/business/极限运行_AB验收报告.md`；离线回放器 `scripts/extreme_ab_replay.py`（25-seed 池 + race 回放语义）；**长跑互斥的物理根据**：三臂并行实测 solver 帧数 −8%、密度 −0.5pt（墙钟预算被 CPU 争用截断），单飞槽不是形式约束。

## 编辑排料 US-001 关键约定（editGeometry / overlap / editStore 地基 调用方必读）

「编辑排料」（prd-edit-nesting-layout，2026-09-04）计算与状态地基。三模块零后端改动；渲染/交互（US-002/003）与保存接线（US-004）在其上叠加。

- **依赖方向**：`editStore → lib/overlap → lib/editGeometry → lib/params`（shoelace 单 ring 复用；params.ts 私有 `polygonArea` 已导出）；`polygon-clipping`（Martinez 纯 TS，MIT，^0.15.7）是编辑排料唯一新依赖 —— 输入输出 `number[][]` 与本仓 `Polygon=[number,number][]` 零适配，**输出 ring 首点重复闭合**，`overlap.openRing` 统一剥回「无重复起点」口径。
- **transformPolygon = 计算出口、pointsStr = 渲染出口**：同一公式（`x'=x·c−y·s+tx`）逐点一致（单测对拍锁死），但 transformPolygon **全精度不 r2** —— 布尔交/bbox/穿透深度对舍入敏感。改公式须与 pointsStr / 后端 `_transform_polygon` 三方锁步。
- **穿透深度口径（PRD 定义）**：A 内顶点落入 B / B 内顶点落入 A 的点到对方**边界**（各边最近距）的最大值；十字交叉（边交但顶点互不落入）如实低估为 0 —— 面积指标（布尔交精确）与之互补，不互相补正。
- **多副本寻址**：编辑 key = `lastFrame.placed_items` **数组下标**（同 pid 第 k 次出现 = 第 k 副本，与 NestSVG「出现序」副本池同语义）；`precomputeEditPieces` 按下标展开，`save` 原地保序写回（`placed_items` 数组身份不变，`frames[]` 内同一 FrameMsg 引用一致）⇒ 副本映射稳定。
- **computeLayoutStats 单一真相源**：`width = ceil(包络 maxX − 1e-9)`（ε 抵 90° 旋转 ~3e-14 float 噪声防未编辑即 +1mm；下限 1mm）+ `density = total_area_mm2/(width×gate_mm)`（real 口径）；弹窗实时显示与 save 写回同函数，**不许**在组件里另写密度公式。
- **save/reset 防御**：写回前校验 `runRegistry.list().includes(run)`（重解/策略应用 clear 后旧引用拒绝）+ `lastFrame`/`manifest` 非空；`viewBoxMaxW = 新料长` 双向伸缩（NestSVG `W=max(viewBoxMaxW, f.width_mm)` 随之收缩，回放 seek 帧用各自 f.width_mm 自守恒）；**density_sparrow 恒不动**（solver erode 参考值）。
- **clientToWorld 必须走 CTM 矩阵**（`flipGroup.getScreenCTM().inverse()` + `svg.createSVGPoint()`）：自动涵盖 xMinYMid meet letterbox + `scale(1,-1)` 翻转；手写 `gate−y` 会漏 letterbox 偏移。jsdom 无 CTM → 返回 null（测试 mock 见 editGeometry.test.ts）。

## 编辑排料 US-002 关键约定（弹窗渲染与查看 调用方必读）

编辑弹窗 UI 面（2026-09-04）：`edit/EditLayoutModal`（受控 Portal + 状态条 + 禁关闭）+ `edit/EditCanvas`（命令式画布 + 缩放平移）+ `nests/pieceDom`（5 层节点构建自 NestSVG 机械提取共用）。零后端改动。

- **禁 ESC/遮罩关闭（有意偏离全站弹窗惯例）**：EditLayoutModal **不挂** ESC keydown listener、遮罩**无** mousedown handler —— 编辑草稿不可被误触丢弃；唯一关闭路径 = 右上 ✕（US-004 接 dirty 二次确认）与右下「保存当前布局」（`editStore.save()` + close）。后续 story 不得「顺手补上」ESC。
- **弹窗与主视图同构**：5 层节点只经 `nests/pieceDom.createPieceEntry` 建（配色/dataset/pointer-events 逐属性一致）、points 只经 `lib/geometry.pointsStr`；EditCanvas 数据源 = `editStore.working`（**每 working 下标恰一份 5 层节点** = 出现序多副本），非 frames/renderTick。
- **状态条唯一真相源 + Δ 口径**：料长/利用率只调 `computeLayoutStats(working)`；**Δ 基线 = `computeLayoutStats(baseline.placedItems)`（同 ceil 口径）**，不是裸 `frame.density` —— solver 小数 width_mm（如 6148.38）下后者未编辑就 −0.01pt 取整伪影；Δ 只度量编辑效果，初值恒 +0.00pt。弹窗 ceil 口径与主视图 NestLabel 差 ≤0.02pt 是「料长双向伸缩」设计固有取整（保存后主视图同步 ceil 即一致），非 bug。
- **缩放锚必须 world→user 换算**：viewBox 数学在用户空间（翻转组之前），`clientToWorld` 返回世界空间（Y 向上）—— 锚点须 `userY = gate − worldY`，直接用 worldY 缩放中心上下镜像（单测 + 浏览器锁死）。CTM 不可得 → 中心锚退化。
- **视图变更必须回写 vbRef**：滚轮/±/平移/重置全以 EditCanvas `vbRef` 为当前视图 SSOT —— `zoomBy` 漏回写 ref 则第二档起锚在陈旧视图（本项目已修）。`writeViewBox` 显示值 r6 截断（CTM 反变换 float 噪声不进 attr；数学连续性走 ref 全精度）。滚轮用 **native listener + passive:false**（React 合成 wheel passive，preventDefault 告警失效）。
- **事件分层**：毛版 polygon pointerdown 归 US-003 拖动（当前 no-op 预留，`closest('polygon')` 早退不起平移）；4 层工艺节点 pointer-events:none；空白（svg/bg/fab）pointerdown = 平移（比尺 = min(宽比,高比)，letterbox 偏移在差分中抵消，无需 CTM）。视图工具按钮置**左上**，右上留给 US-003 指标面板。
- **jsdom 缺口补法**：PointerEvent 未实现（beforeEach `window.PointerEvent = class extends MouseEvent {}`）；`setPointerCapture` try/catch optional call；getScreenCTM/createSVGPoint 用 editGeometry.test.ts 的 `mockMat` 复合矩阵套路。

# 前端组件 / 模块地图（materialSorting-web/）

> 由 `/sync-docs` 维护。改前端先看这里。当前覆盖 US-001 Tab 框架 + US-002 WS 契约 + US-003 NestSVG + US-004 ControlPanel + US-005 多 seed/收敛曲线 + US-006 回放 seekbar + 片 hover tooltip + US-007 导出 PNG/DXF + DXF 上传预览 US-001 Tab 骨架。

## 顶层结构

```
materialSorting-web/
├── index.html              # Vite 入口（dev: /, prod: 被 build 覆写到 static/index.html）
├── package.json            # scripts: dev / build / preview / typecheck / test
├── vite.config.ts          # base 切换（dev '/' / build '/static/'）+ proxy /export /api /ws（US-009 加 /api）
├── vitest.config.ts        # US-002 起：jsdom + globals，独立于 vite.config.ts
├── tsconfig.json           # src/ strict TS（target ES2020, jsx react-jsx）
├── tsconfig.node.json      # vite.config.ts 单独编译（composite）
├── src/                    # 源码（US-008 起：legacy/ 已删除，src/ 是唯一真相源）
│   ├── main.tsx            # createRoot(<StrictMode><App/></StrictMode>)
│   ├── App.tsx             # US-001 Tab 骨架：TabBar + 双 .page 容器（display:none 切换）+ Tooltip 单例
│   ├── style.css           # 由 vanilla 前身 1:1 迁入；US-001 加 .tabbar/.tab/.page/.hidden/.preview-empty
│   ├── vite-env.d.ts        # vite/client 类型引用
│   ├── types/              # US-002：纯数据契约（与 server.py 字段名 1:1）
│   ├── constants/          # US-004：SIZES / PHASE_COLORS / SEED_COLORS / V03_TABLE
│   ├── lib/                # US-002 起：纯函数工具（ws / geometry / params）；US-007 download
│   ├── store/              # US-002 RunRegistry + US-003 appStore + US-001 uiStore（Tab 切换）
│   ├── hooks/              # US-002 起：useSolveRun / useRafThrottle；US-007 useExport
│   ├── components/
│   │   ├── TabBar.tsx       # US-001 顶部 Tab（排料/上传预览）；订阅 uiStore.activeTab
│   │   ├── NestingPage.tsx  # US-001 排料页（原 App.tsx 业务逻辑外提；持 solving/seeds/useSolveRun）
│   │   ├── preview/         # US-001 起：上传预览页（US-008 落地 UploadPanel/SizeTabs/PiecePreviewSVG）
│   │   │   └── PreviewPage.tsx  # US-001 占位（待 US-008 替换为左 UploadPanel + 右 SizeTabs+ParsedPiecesView）
│   │   ├── nests/          # US-003 NestSVG/NestCard/NestLabel + US-005 NestsGrid；US-006 NestSVG 加 seek+hover
│   │   ├── ControlPanel/   # US-004 8 子组件 + US-005 MultiSeedControls；US-007 ExportButtons
│   │   ├── curve/          # US-005 ConvergenceCurve（命令式 innerHTML）
│   │   ├── playback/       # US-006 PlaybackBar/Seekbar/SeekReadout
│   │   └── Tooltip.tsx     # US-006 片 hover tooltip（Portal 到 body）
│   └── __tests__/          # US-002 起：vitest 单测；US-001 加 App 集成 smoke + TabBar/uiStore 单测
└── static/                 # npm run build 产物（US-008 起 gitignore；被 FastAPI mount 到 /static）
    ├── index.html
    └── assets/index-[hash].{js,css}
```

## dev / prod 双路径

| | dev | prod |
| --- | --- | --- |
| 入口 | `npm run dev` → `localhost:5173` | `npm run build` 后由 `ms-web` (:8000) serve |
| base | `/`（Vite 默认） | `/static/`（FastAPI mount 路径） |
| 前端如何打后端 | 相对路径 `/export` `/api/*` `/ws/solve`，由 Vite proxy → `127.0.0.1:8000` | 同源 `127.0.0.1:8000/export` `/api/*` `/ws/solve`（无需 proxy） |
| 验证命令 | `curl localhost:5173/`、Python websockets 连 `ws://localhost:5173/ws/solve` | `curl 127.0.0.1:8000/`、`curl -I 127.0.0.1:8000/static/assets/index-*.js` |

## vite.config.ts 关键点

- `base` 由 `command` 决定：`build` → `/static/`，否则 `/`。**勿改成静态值**，否则 dev 或 prod 之一会断。
- `build.outDir = 'static'`、`emptyOutDir = true` —— 每次构建清空 `static/` 后重写。
- `server.proxy['/ws'] = { target, ws: true, changeOrigin: true }` —— **`ws: true` 必填**，否则 WS 升级请求会被 Vite 当普通 HTTP 处理返回 404。
- `server.proxy['/api'] = { target, changeOrigin: true }`（US-009）—— dev 下转发 `/api/parse-dxf` 等到后端 :8000；prod 同源无需 proxy。
- `server.strictPort = true` —— 锁死 :5173，便于后端 / 文档稳定引用。

## tsconfig 两文件分工

- `tsconfig.json`（include `src`）：app 代码 strict 模式，`noEmit` + `moduleResolution: bundler`，`jsx: react-jsx`（不需要 `import React`）。**`noUnusedLocals` / `noUnusedParameters` 都开**，未用的 import / 形参会直接报错 —— 测试文件同样受此约束。
- `tsconfig.node.json`（include `vite.config.ts`，`composite: true`）：被 `tsconfig.json` 通过 `references` 引用，独立检查配置文件。

## US-001 落地：顶部 Tab 框架 + NestingPage 外提

| 文件 | 角色 |
| --- | --- |
| `src/store/uiStore.ts` | Zustand 单字段 store：`activeTab: 'nesting' \| 'preview'`（默认 `'nesting'`）+ `setTab(tab)`。仅此一字段，求解/WS/seek 等业务状态仍在各 page 内 |
| `src/components/TabBar.tsx` | 顶部 Tab 切换：`<nav class="tabbar">` + 两 `<button class="tab">`（排料 / 上传预览）；点击 setTab；active 项加 `.active` class + `aria-pressed=true` |
| `src/components/NestingPage.tsx` | 排料工作台页（原 App.tsx 业务逻辑外提）：持 `seeds/solving/status/doneCountRef/totalSeedsRef` + `useSolveRun({onDone})` + `useRafThrottle(seeds.length>0)`；渲染 `<ControlPanel>` + `<main class="main">`；不挂 Tooltip（Tooltip 由父 App 渲染） |
| `src/components/preview/PreviewPage.tsx` | 上传预览页（US-001 占位）：渲染 `.preview-empty` 卡片提示「US-006~US-008 落地」；US-008 将替换为左 UploadPanel + 右 SizeTabs + ParsedPiecesView |
| `src/App.tsx` | 顶层骨架：渲染 `<TabBar>` + `<div class="tab-content">` 双 `.page` 容器（display:none 切换）+ `<Tooltip>`（单例，Portal 到 body） |
| `src/style.css` | 增 `.app{flex-direction:column}` + `.tabbar/.tab/.tab.active` + `.tab-content/.page/.page.hidden` + `.preview-empty/.preview-empty-card`（暗色与 ControlPanel 同色系） |
| `src/store/__tests__/uiStore.test.ts` | 4 项单测：默认 nesting / setTab 切换 / 切回 / 订阅者通知 |
| `src/components/__tests__/TabBar.test.tsx` | 5 项单测：DOM 结构（nav+2button）/ 默认 active / 点击切 store / 切回 / 顺序固定 |
| `src/__tests__/App.test.tsx` | 6 项集成 smoke：tabbar+2tab / 默认 nesting 页可见含 ControlPanel+main / 切 preview nesting 加 .hidden 但 DOM 仍在（不卸载）/ 切回对称 / Tooltip 单例仍 Portal body / 点击 tab 端到端 |

### 关键不变量（US-001 立，后续故事不得破坏）

1. **双页面常驻 DOM，display:none 切换** —— `.page.hidden { display: none }` 而非条件渲染 / 路由卸载。切回排料页时 NestingPage 内 `useState/useRef/runRegistry` 全部保真，进行中的求解 / WS 连接 / 播放 seek 不中断。改 `display:none` 策略为「条件渲染」会破坏此保证。
2. **uiStore 单字段** —— 仅持 `activeTab`；不混入 solving/seeds/seek 等业务状态（业务状态由 NestingPage 自治）。改 store 形状需同步 4 项 uiStore.test.ts。
3. **TabBar 只切 store，不直接切 DOM** —— `<button onClick=setTab>`；显隐由 App 订阅 `activeTab` 后切 `.hidden` class。解耦：未来加 URL hash 同步只需改 App 一处。
4. **Tooltip 单例仍挂 App** —— US-006 关键约定 #3 不破：Tooltip 是模块级单例，App 内只能挂一个；NestingPage 不挂 Tooltip。
5. **Tab 顺序固定：排料在前** —— 是默认入口（`uiStore.activeTab` 默认 `'nesting'`），TABS 数组顺序不可改。
6. **TabBar 视觉沿用 style.css** —— 不引入 CSS 框架；`.tabbar/.tab` 暗色（`#26282e`）与 ControlPanel 同色系；active 项用绿色 `#2ea06c` border-bottom 强调（与 StartButton `#2ea06c` 同色）。
7. **NestingPage 用 Fragment** —— 直接把 ControlPanel + main 作为 `.page` flex 子元素，不再包一层 `.app`（避免冗余 DOM + flex 嵌套层）。

## US-002 落地：WS 契约 + RunRegistry + useSolveRun

| 文件 | 角色 |
| --- | --- |
| `src/types/v03.ts` | `SolveParams`（d_ext/d_int/tol_ext/tol_int）+ `PerTypeOverride` / `PerTypeOverrides` |
| `src/types/ws.ts` | `StartPayload` + `ServerMsg = ManifestMsg \| FrameMsg \| FinalMsg \| ErrorMsg` 判别联合（density/density_sparrow 双口径都在 FrameMsg/FinalMsg） |
| `src/lib/ws.ts` | `solveWsUrl()` —— `${proto}://${location.host}/ws/solve`（dev/prod 自适配，**不要写死 :8000/:5173**） |
| `src/store/runRegistry.ts` | 模块级 mutable 数组持有 RunRecord（frames/lastFrame 不进 React state）；提供 `create / clear / list / bestRun` |
| `src/hooks/useSolveRun.ts` | 单 run 生命周期：`start(cfg)` 显式 `new WebSocket` → onmessage 分发 manifest/frame/final/error → Registry 落盘 + 回调；onclose/onerror → onDone（done flag 防重复），**不重连** |
| `src/__tests__/useSolveRun.test.tsx` | 6 项单测：StrictMode 双 mount 0 连接 / StartPayload 字段逐项 / manifest+frame+final 分发 + Registry 落盘 / error 分支 / URL 相对 host / per_type 透传 |

## US-003 落地：NestSVG 命令式渲染 + 节流闸（单 seed 可视化）

| 文件 | 角色 |
| --- | --- |
| `src/lib/geometry.ts` | `r2(x)` 四舍五入 2 位 + `pointsStr(poly, rot, tr)` —— 与旧 vanilla 实现 / 后端 `_transform_polygon` 字节级一致 |
| `src/store/appStore.ts` | Zustand 单字段 store：仅持 `renderTick`（+ `bumpRenderTick` action）；高频 frames 落 runRegistry 不进 React state |
| `src/hooks/useRafThrottle.ts` | `useRafThrottle(active)` —— active=true 时 rAF + 100ms 时间戳闸 bump renderTick；隐藏标签页自动暂停 |
| `src/components/nests/NestSVG.tsx` | 命令式 SVG：JSX 仅 `<svg ref/>`；manifest 到达后 imperative 建 bg/fab/flipGroup + N polygon；订阅 renderTick setAttribute('points'/'display') |
| `src/components/nests/NestLabel.tsx` | 顶部标签：`seed N · X.XX%`；订阅 renderTick 重渲染（轻量文本，可走 reconciliation） |
| `src/components/nests/NestCard.tsx` | 单 run 卡片容器（NestLabel + NestSVG） |
| `src/App.tsx` | US-003 拼装：硬编码 sizes=[30,32]/time=30/seed=0/baseline；按钮触发 useSolveRun.start + useRafThrottle(seeds.length>0) |
| `src/lib/__tests__/geometry.test.ts` | 5 项：r2 截断 / pointsStr 与旧 vanilla 实现 字节级一致（9 组对比）/ 0°/90° 可视化 sanity / 输出无尾随空格 |
| `src/components/nests/__tests__/NestSVG.test.tsx` | 8 项：空骨架 / manifest 建全 DOM（含 transform）/ 重复 bump 不重建 / frame 写 points + display / 旋转 90° 输出 / placed↔未 placed 切换 / 无 frame 不写 viewBox / 后到 manifest 路径 |

## US-004 落地：v0.3 参数面板（ControlPanel）

| 文件 | 角色 |
| --- | --- |
| `src/constants/sizes.ts` | `SIZES = [28,29,30,31,33,34,35,36]`（M1787 8 码跳 32；与后端 `nesting_bounds.DEFAULT_SIZES` 一致） |
| `src/constants/colors.ts` | `PHASE_COLORS`（exploring/compressing/final）+ `SEED_COLORS`（6 seed；US-005 ConvergenceCurve 消费） |
| `src/constants/v03.ts` | `V03_TABLE` 全 10 片型工艺上限（d / tol / internal；与后端 `constraints.py MAX_OVERLAP / ROTATION_TOL` 1:1）+ `V03_PTYPES` 顺序 |
| `src/lib/params.ts` | `FormState`（含 multi_seed/seed_count）+ `DEFAULT_FORM`（旧 index.html 默认 1:1）+ `collectParams(form)` 纯函数（与旧 vanilla 实现 字段级一致）+ `parseSeed / parseTime / parseSeedCount` |
| `src/components/ControlPanel/ControlPanel.tsx` | 顶层面板：持 form state；StartButton 触发校验 + collectParams + onStart(cfg) 透传到 App（cfg 含 seed_count） |
| `src/components/ControlPanel/SizePicker.tsx` | 8 码 chip 复选，受控；toggle 单码号 |
| `src/components/ControlPanel/ParamForm.tsx` | 时长 / base seed 输入（min/max 与旧 index.html 一致） |
| `src/components/ControlPanel/MultiSeedControls.tsx` | US-005：多 seed 对比 checkbox `#multi_seed` + 数量 input `#seed_count`（min=2 max=6 default 3） |
| `src/components/ControlPanel/ErodeInputs.tsx` | d_ext / d_int（step 0.5，min 0） |
| `src/components/ControlPanel/ToleranceInputs.tsx` | tol_ext / tol_int（max 45，min 0） |
| `src/components/ControlPanel/PresetButtons.tsx` | 预览 120s / 精排 600s 一键填 |
| `src/components/ControlPanel/PerTypeOverrides.tsx` | 渲染 V03_PTYPES 10 行；internal=true 加 `<i>内</i>` 徽章；placeholder 提示 d≤/t≤ 上限 |
| `src/components/ControlPanel/StartButton.tsx` | 启动按钮（id="start"，沿用 legacy CSS 选择器） |
| `src/components/ControlPanel/StatusLine.tsx` | 状态行（id="status"，沿用 legacy CSS） |
| `src/components/nests/NestsGrid.tsx` | US-005：seeds → runRegistry.list().find(seed) → NestCard 列表；key=seed 稳定 |
| `src/components/curve/ConvergenceCurve.tsx` | US-005：命令式 SVG（React 仅 `<svg ref/>`；子节点 innerHTML 写入）。订阅 renderTick；导出 sampleFrames / renderCurveInto 纯函数 |
| `src/App.tsx` | US-005：handleStart 启 N 个 WS（seed=base+i）；doneCountRef/totalSeedsRef all-done 检测；多 seed setStatus summary+best |
| `src/lib/__tests__/params.test.ts` | 14 项：默认 d_int=10 + per_type=null / 与 legacy collectParams 11 组对比 / per_type 单档非空 entry / 全空白 → null / 显式 "0" 区分空 / parseSeedCount 7 组（单 seed → 1 / multi + 默认 3 / clamp 2,6 / fallback 3） |
| `src/components/ControlPanel/__tests__/ControlPanel.test.tsx` | 15 项：AC#1..#7 集成 + US-005 multi_seed/seed_count 5 项（默认值 / toggle / clamp / fallback / 不开 multi 时 seed_count 忽略） |
| `src/components/nests/__tests__/NestsGrid.test.tsx` | US-005 6 项：空容器 / N 卡渲染 / registry 缺失跳过 / 顺序与 seeds 一致 / seeds 不变不重复挂载 / seeds 增减跟着变 |
| `src/components/curve/__tests__/ConvergenceCurve.test.tsx` | US-005 14 项：sampleFrames 4（空 / ≤400 / >400 / 整除）+ 渲染 10（90% 线 / 单 seed 散点+折线+末点 / 多 seed 折线+标签 / 单/多 seed 图例 / renderTick 订阅 / 多次 bump 不重建 / renderCurveInto 纯函数） |

## US-006 落地：回放 seekbar + 片 hover tooltip

| 文件 | 角色 |
| --- | --- |
| `src/lib/seek.ts` | 纯函数 `maxElapsed(runs)` + `frameAtTime(container, t)` 二分查找（与旧 vanilla 实现 `maxElapsed` / `frameAtTime` 字节级一致）；FrameContainer 最小接口解耦 RunRecord |
| `src/store/appStore.ts` | 加 `seekTime: number`（默认 -1 = live）+ `setSeekTime(t)`；renderTick/seekTime 共用同一 zustand store |
| `src/components/Tooltip.tsx` | React Portal 到 body 的单例浮层；模块级 `_el` / `_hovered` 单例 + `showTooltip / hideTooltip / setHovered / clearHovered` 命令式 API（高频 mousemove 不进 React state） |
| `src/components/playback/Seekbar.tsx` | 受控 `<input id="seek" type="range">`；disabled 时 max=0 value=0；启用时 max=ceil(maxElapsed)，value=seekTime（或末尾 fallback） |
| `src/components/playback/SeekReadout.tsx` | `t=X.Xs \| sN yy.yy% \| sM zz.zz%` 文本；未全完成显示 "—"；订阅 renderTick+seekTime |
| `src/components/playback/PlaybackBar.tsx` | `.playback` 容器（field-label + Seekbar + SeekReadout）；订阅 renderTick 算 allDone/max |
| `src/components/nests/NestSVG.tsx` | 增量：useEffect 加 `seekTime` dep，`f = seekTime>=0 ? frameAtTime(run,seekTime) : run.lastFrame`；flipGroup 上事件委托 mousemove+mouseleave（AC#4..#6） |
| `src/App.tsx` | 增量：全完成时 `setSeekTime(ceil(maxElapsed))`；handleStart 内 `setSeekTime(-1) + clearHovered + hideTooltip`；挂一个 `<Tooltip/>` |
| `src/lib/__tests__/seek.test.ts` | 16 项：frameAtTime 9（空 / 单 / 边界 / 等价线性 / 10/1000 帧 stress / duplicate elapsed）+ maxElapsed 6（空 / 多空 / 单 / 多 / 混合 / RunRecord 兼容） |
| `src/components/__tests__/Tooltip.test.tsx` | 11 项：Portal 到 body + 初始 display:none / showTooltip +14 偏移 / hideTooltip / setHovered 加 class / 同一 polygon 幂等 / 切换 polygon 移除旧 / setHovered(null) / clearHovered / no-op 兜底 |
| `src/components/playback/__tests__/PlaybackBar.test.tsx` | 9 项：无 run disabled / 求解中 disabled / 全完成启用 / ceil 非整数 / readout 单 seed / readout 多 seed / 拖动 setSeekTime / seekTime=-1 fallback 末尾 / disabled max=0 value=0 |
| `src/components/nests/__tests__/NestSVG.seek.test.tsx` | 11 项：seek 5（live / 切 frameAtTime / 边界 / 超末帧 / 无 frame）+ hover 6（mousemove 显 tooltip+加 class / 非 polygon 隐 / 切换 polygon 移除旧 / 面积换算 / mouseleave / seekTime 切换不丢 listener） |

## US-007 落地：导出 PNG / DXF

| 文件 | 角色 |
| --- | --- |
| `src/lib/download.ts` | `parseContentDisposition(cd, fmt)` —— RFC 5987 `filename*=UTF-8''xxx` → decodeURIComponent；fallback `filename="xxx"` / `filename=xxx` / `nesting.<fmt>`；`downloadBlob(blob, name)` —— `<a download>` + `URL.createObjectURL` + 10s revoke（与旧 vanilla 实现 exportAs 字节级一致） |
| `src/hooks/useExport.ts` | `useExport({ onStatus }) → { exportAs, exporting }`。exportAs(fmt, sizes)：bestRun（registry.bestRun()）→ POST `/export` {fmt, sizes, seed, gate_mm, width_mm: lastFrame.width_mm, density: run.finalDensity, placed: lastFrame.placed_items}（AC#2 逐字段对齐旧 vanilla 实现）→ blob → parseContentDisposition → downloadBlob。防连击：exportingRef + state 同步；exporting=true 时再次调用静默忽略。错误：res.ok=false 读 json.error / fetch throw → onStatus(`导出失败：…`) |
| `src/components/ControlPanel/ExportButtons.tsx` | `<ExportButtons solving exporting onExport/>` —— `.export-group` 容器 + 2 个 `button.export`（id `export_png`/`export_dxf` 沿用 legacy CSS）。disabled = solving \|\| exporting \|\| !hasLastFrame；订阅 renderTick（lastFrame 到达后 bump → 重算 hasLastFrame = `registry.list().some(r => r.lastFrame)`，与旧 vanilla 实现 updateExportButtons 一致） |
| `src/components/ControlPanel/ControlPanel.tsx` | 持 useExport({ onStatus })；handleExport(fmt) → exportAs(fmt, form.sizes)（sizes 来自本组件 form，与旧 vanilla 实现 `selectedSizes()` 同源）；JSX 把 `<ExportButtons>` 挂在 `<StatusLine>` 后（与 legacy index.html 顺序一致） |
| `src/lib/__tests__/download.test.ts` | 13 项：parseContentDisposition 10（RFC 5987 中文 / RFC 5987 ASCII / filename="xxx" / filename=xxx / 空 CD / 无 filename / malformed URI 落 fallback / filename* 空 / filename* 优先 / 大小写不敏感）+ downloadBlob 3（appendChild+click+remove+10s revoke / download 属性 = filename / href = ObjectURL） |
| `src/__tests__/useExport.test.tsx` | 15 项：无 lastFrame onStatus + 不发 fetch / bestRun 多 run 取最高密度 / ExportPayload 逐字段对齐旧 vanilla 实现 / fetch URL = `/export` / exporting 状态切换 + onStatus 正在生成 / DXF fmt 文案 / CN 文件名 decode（AC#5）/ res.ok=false 用 json.error / json 抛错用 statusText / fetch reject 用 error.message / 非 Error 用 String / 防连击仅发一次 / sizes 透传 / gate_mm 来自 manifest / 并列密度取首个 |
| `src/components/ControlPanel/__tests__/ExportButtons.test.tsx` | 14 项：DOM 结构（export-group / 2 button / id / 标签 / hint）/ disabled 条件 4（无 lastFrame / solving / exporting / 全满足启用）/ onExport(png) / onExport(dxf) / renderTick 订阅 lastFrame 启用 / clear + bump 禁用 / 多 run / 无 lastFrame run |

### 关键不变量（US-007 立，后续故事不得破坏）

1. **ExportPayload 七字段与旧 vanilla 实现 exportAs 字节级一致** —— `{ fmt, sizes, seed, gate_mm, width_mm, density, placed }`，其中 `width_mm = run.lastFrame.width_mm`、`density = run.finalDensity`、`placed = run.lastFrame.placed_items`、`gate_mm = run.manifest.gate_mm`（多 run 共享，与旧 vanilla 实现 全局 `gateH` 同源）。改任一字段需同步 `useExport.test.tsx` 的 AC#2 用例 + `__tests__/ExportButtons.test.tsx`。
2. **bestRun = lastFrame 存在且 finalDensity 最高** —— runRegistry.bestRun() 已封装该逻辑（`for r of list: if !r.lastFrame continue; if r.finalDensity > best.finalDensity: best = r`）。并列密度取首个创建的 run。修改算法必须同步 `useExport.test.tsx` 的 bestRun 用例。
3. **parseContentDisposition 优先级** —— `filename*=UTF-8''xxx` > `filename="xxx"`/`filename=xxx` > `nesting.<fmt>`。decodeURIComponent 抛 URIError → 落到下一优先级（不能让导出整体失败）。改顺序必须同步 `download.test.ts` 10 个 parseContentDisposition 用例。
4. **downloadBlob 必须appendChild → click → remove → setTimeout(revoke, 10000)** —— 与旧 vanilla 实现 字面量一致（10s revoke 给浏览器下载请求足够时间）。jsdom 测试需 stub `URL.createObjectURL` + `HTMLAnchorElement.prototype.click`（jsdom click 触发 navigation 警告 + URL.createObjectURL 未实现）。
5. **ExportButtons 订阅 renderTick 而非 runRegistry** —— lastFrame 是 mutable push 不进 React state；通过 `useAppStore(s => s.renderTick)` + `void renderTick` 触发 reconciliation 后重算 `hasLastFrame = runRegistry.list().some(r => r.lastFrame !== null)`。改订阅源会破坏「求解 final 后按钮启用」联动。
6. **防连击 useExport 必须用 ref + state 双重防护** —— `exportingRef.current` 立即生效（async 流程内读到最新值）；`exporting` state 触发 UI disabled。仅靠 state 会有 race（state 异步生效，连击第二次在 setExporting(true) 调度前已进入 async body）。
7. **DOM id `export_png` / `export_dxf` 沿用 legacy CSS 选择器** —— style.css `button.export` 不依赖 id，但保留 id 便于测试 + 未来 US-008 去 id 时一并清理。改 id 需同步 `__tests__/ExportButtons.test.tsx` 14 项 + `__tests__/ControlPanel.test.tsx` 4 项 US-007 集成。
8. **onStatus 由 useExport 透传到 ControlPanel → App.setStatus → StatusLine** —— 「正在生成 PNG/DXF…」「已导出 …」「导出失败：…」「无可导出的方案（请先求解）」四类文案由 useExport 写，ControlPanel 不参与组装。改文案需同步 `useExport.test.tsx` 4 个 onStatus 断言。
9. **服务端文件名 `pct` 而非 `%`** —— `server.py export` 路由拼 `fname_cn = 排料_码{sizes_str}_{pct:.2f}pct_seed{seed}.{ext}`（不是 `88.42%`）。AC#5 字面写 `%` 是文档误差；实际下载文件名是 `排料_码28-30-32_88.42pct_seed0.png`。改文件名格式需同步后端 server.py + useExport.test.tsx 的 CN decode 用例。

### 关键不变量（US-006 立，后续故事不得破坏）

1. **`seekTime = -1` 是 live 标志，不是合法时间** —— NestSVG / SeekReadout 必须先判 `seekTime >= 0` 再走 frameAtTime 分支；负值回退 lastFrame（live）。改默认值需同步 `PlaybackBar.test.tsx` + `NestSVG.seek.test.tsx`。
2. **App 全完成时 setSeekTime(me)，新 start 时 setSeekTime(-1)** —— `me = Math.ceil(maxElapsed(runRegistry.list()))`，与旧 vanilla 实现 `$('seek').value = me` 一致；handleStart 内必须同时 clearHovered + hideTooltip（防 DOM 残留）。
3. **Tooltip 是模块级单例** —— `_el` / `_hovered` 是模块顶层的 let 变量；Tooltip 组件 mount 时 registerTooltipEl，NestSVG mousemove 处理器调 showTooltip/hideTooltip/setHovered。**App 内只能挂一个 `<Tooltip/>`**（多挂会互相 clobber）。
4. **Tooltip style 只能由 imperative 写** —— Tooltip 组件 JSX 不带 `style` prop（仅 className）；display/left/top/innerHTML 由 showTooltip/hideTooltip 直接 mutate。React reconciliation 不会覆盖。修改时不要在 JSX 加 style，否则重渲染会 reset display:none。
5. **frameAtTime 二分必须与旧 vanilla 实现 字节级一致** —— `lo=0, hi=n-1, ans=0; while (lo<=hi) { mid=(lo+hi)>>1; if (frames[mid].elapsed<=t) {ans=mid; lo=mid+1} else hi=mid-1 }`；返回 frames[ans]。改算法必须同步 `seek.test.ts` 9 个 frameAtTime 用例（含 1000 帧 stress）。
6. **flipGroup 上事件委托 mousemove + mouseleave（不是 svg）** —— AC#4 明确要求；与旧 vanilla 实现 setupHover(svg) 行为等价（多边形均在 flipGroup 内）。listener 在 `if (run.manifest && !flipRef.current)` 块内 attach，幂等保护防止 StrictMode 双 mount 双注册。
7. **面积换算 `mm² → cm²` 用 `÷100`** —— `parseFloat(dataset.area)/100`，与旧 vanilla 实现 一致；toFixed(1)。改单位 / 精度需同步 `NestSVG.seek.test.tsx` AC#4 用例。

### 关键不变量（US-005 立，后续故事不得破坏）

1. **`ControlPanelStartPayload.seed_count` 是已 clamp 的最终值** —— `parseSeedCount(form)` 返回 1（multi_seed=false）或 clamp(parseInt||3, 2, 6)；App.handleStart 直接 `for (let i=0; i<seed_count; i++) start({...cfg, seed: base+i})`，不做边界检查。修改默认 / clamp 边界需同步 `params.test.ts` 7 个 parseSeedCount 用例 + `ControlPanel.test.tsx` 5 个 multi-seed 用例。
2. **ConvergenceCurve 命令式 innerHTML** —— React 仅渲染 `<svg ref/>`；子节点（line/text/circle/path/g.legend）通过 `svg.innerHTML = out` 一次性写入。**不要改成 JSX**（每帧 diff 开销爆炸）。采样 / 配色 / 字面量与旧 vanilla 实现 drawCurve 字节级一致；`sampleFrames` / `renderCurveInto` 导出便于纯函数测试。
3. **采样算法** —— `step = max(1, floor(n/400))`；`pts = frames[0::step]`；`if (pts[last] !== frames[last]) pts.push(frames[last])`（末帧强制纳入）。改算法必须同步 `__tests__/ConvergenceCurve.test.tsx` 4 个采样用例。
4. **App all-done 检测用 ref 不用 state** —— `doneCountRef.current += 1; if (< totalSeedsRef.current) return;`；每次 handleStart 重置两个 ref。多 seed 收尾 setStatus 含 summary + best（`runs.reduce((a,r) => r.finalDensity > a.finalDensity ? r : a)`）。
5. **配色：单 seed 走 PHASE_COLORS[phase]（散点）+ 默认蓝 `#1f77b4`（折线/末点）；多 seed 走 SEED_COLORS[ri]（折线/末点/标签/图例）**。`multi = runs.length > 1`（不是 multi_seed 表单值）。
6. **useRafThrottle(seeds.length>0) 不在 solving=false 时停** —— 求解结束后曲线 / NestLabel 仍需 bump 重绘最终态；下次 start() 才会 `runRegistry.clear + setSeeds([])` 间接停掉。
7. **NestsGrid 只在 seeds 变化时挂载/卸载** —— `<NestCard key={seed} run={rec}/>` 稳定 key；NestSVG 内部已订阅 renderTick 自更新，NestsGrid 不参与高频重绘。

### 关键不变量（US-004 立，后续故事不得破坏）

1. **表单字段全字符串存储** —— `FormState` 所有 number 字段（time/seed/d_*/tol_*）以及 `per_type[pt].d/tol` 都按 `input.value` 字符串持有；`collectParams / parseTime / parseSeed` 做解析。理由：per_type 必须「空串 = 继承」与「"0" = 显式 0」可区分。（US-005 加 multi_seed: boolean / seed_count: string 同样按字符串存。）
2. **collectParams 与旧 vanilla 实现 字段级一致** —— params 四档空 → 0 默认（`num(s, 0)`）；per_type 仅在 `trim() !== ''` 时写入；最终 per_type 整体空 → null（Python 侧 `or None` 接住）。修改必须同步 `lib/__tests__/params.test.ts` 的 11 组对比用例。
3. **DEFAULT_FORM 与旧 index.html 默认值 1:1** —— d_int="10"、其余 0；time="60"、seed="0"；sizes 全选；per_type 全空。（US-005 补：multi_seed=false / seed_count="3"。）修改任一字段需同步更新 AC#2。
4. **ControlPanel 不调 useSolveRun** —— 仅通过 `onStart(cfg)` 把载荷交给 App（解耦：未来多 seed / 重连逻辑由 App 决定）。`onStatus` 用于码号校验失败回写状态行。
5. **DOM id / className 沿用 legacy** —— `id="start" / id="status" / id="d_ext" / id="time" / id="seed"` 等保留（CSS 选择器依赖）；`.sizes / .per_type / .pt-row / .chip / .preset / .pt-name i` 等 className 1:1。US-005 新增 `id="multi_seed" / id="seed_count"` + `.cb / .seed-count` 同样沿用 legacy。US-008 清理 CSS 时再统一去 id。
6. **PerTypeOverrides 行序 = V03_PTYPES 顺序** —— 不可重排（影响测试 placeholder / 徽章断言）；`<i>内</i>` 仅 internal=true 的 4 片型（单排/双排/火机袋/裤耳）。

### 关键不变量（US-003 立，后续故事不得破坏）

1. **React 只渲染空 `<svg>` 一次** —— NestSVG 所有子节点（bg rect / 用布 rect / 翻转组 `<g>` / N 个 `<polygon>`）必须 imperative 创建，用 `useRef` 持有；任何 JSX prop 写入都会被 reconciliation 覆盖。
2. **翻转组 transform 必须用 `setAttribute` 写** —— `translate(0 ${gate_mm}) scale(1 -1)`，对应 sparrow Y 向上 → SVG Y 向下（与 PNG / R12-DXF 导出一致）。
3. **renderTick 单字段节流** —— `appStore` 只持 `renderTick` 一个字段；frames / lastFrame 仍 mutable 在 runRegistry 里；高频渲染通过订阅 renderTick → useEffect 重跑 → setAttribute。
4. **pointsStr 字节级对齐** —— `rad=rot*π/180; c=cos; s=sin; x'=x*c−y*s+tx; y'=x*s+y*c+ty`，每点 `r2(x),r2(y)` 空格分隔，无尾随空格。修改必须同步 `lib/__tests__/geometry.test.ts` 与后端 `_transform_polygon`。
5. **flipRef 幂等保护** —— effect 用 `if (run.manifest && !flipRef.current)` 防 StrictMode 双 mount / 多次 tick 重建 DOM。
6. **viewBox 用历史最大 width 作稳定锚** —— `W = max(run.viewBoxMaxW, lastFrame.width_mm, 1)`，与旧 vanilla 实现 一致，避免收缩抖动。

### 关键不变量（US-002 立，后续故事不得破坏）

1. **WS 连接只在 `start()` 显式开** —— 不在 useEffect 里 auto-connect，否则 React 18 StrictMode 双 mount 会双连。
2. **frames 是 mutable 引用** —— `runRegistry.list()` 返回的元素本身可被 hook 直接 push，不触发任何 React 调度；高频渲染由 US-003 的 `renderTick` 单字段节流。
3. **per_type 空 → 序列化为 null** —— 与旧 vanilla 实现 `collectParams` 一致（Python 侧 `or None` 接住）。
4. **`density` vs `density_sparrow` 双口径** —— `density` 是原面积口径（= `total_area / (width*gate)`，与 90% 生死线一致），`density_sparrow` 是 erode 后 sparrow 自报（参考）。前端**任何决策 / 显示都优先 density**。
5. **测试需设 `IS_REACT_ACT_ENVIRONMENT = true`** —— 否则 `act()` 会警告（但仍能跑）。Mock WebSocket 用 ctor 返回 mock 实例的方式（`new WebSocket(url)` 拿到的是 mock）。

## 与旧 vanilla 的对应（迁移基线）

| 旧（vanilla 前身） | 新位置（计划） | 故事 | 状态 |
| --- | --- | --- | --- |
| `SIZES` `PHASE_COLORS` `SEED_COLORS` `V03` 常量 | `src/constants/*.ts` | US-004 | **已落地** |
| `WebSocket` + `onmessage` dispatch | `src/lib/ws.ts` + `src/hooks/useSolveRun.ts` | US-002 | **已落地** |
| `makeRun`/`renderFrame`/`pointsStr` 命令式 SVG | `src/components/nests/NestSVG.tsx` + `src/lib/geometry.ts` + `src/components/nests/NestCard.tsx` + `src/components/nests/NestLabel.tsx` | US-003 | **已落地** |
| 全局节流闸（`globalLastDraw` + `RENDER_INTERVAL_MS`） | `src/store/appStore.ts`（renderTick 单字段）+ `src/hooks/useRafThrottle.ts` | US-003 | **已落地** |
| `collectParams` + `per_type` 面板 | `src/lib/params.ts` + `src/components/ControlPanel/*` | US-004 | **已落地** |
| `multi_seed` / `seed_count` + makeRun 多 seed | `src/components/ControlPanel/MultiSeedControls.tsx` + `src/lib/params.ts parseSeedCount` + `src/App.tsx handleStart` | US-005 | **已落地** |
| `drawCurve` 收敛曲线 | `src/components/curve/ConvergenceCurve.tsx` | US-005 | **已落地** |
| `#nests` 多 seed 容器 | `src/components/nests/NestsGrid.tsx` | US-005 | **已落地** |
| `seek` `frameAtTime` 回放 + tooltip | `src/components/playback/*` + `src/lib/seek.ts` + `src/components/Tooltip.tsx` + `src/components/nests/NestSVG.tsx`（seek+hover） | US-006 | **已落地** |
| `exportAs(fmt)` | `src/hooks/useExport.ts` + `src/components/ControlPanel/ExportButtons.tsx` + `src/lib/download.ts` | US-007 | **已落地** |
| run 状态（frames 数组 / lastFrame / finalDensity） | `src/store/runRegistry.ts` | US-002 | **已落地** |

## 已知差异（脚手架阶段）

- `src/App.tsx` US-001 起只保留 Tab 骨架（TabBar + 双 `.page` 容器 + Tooltip 单例）；原 US-005 多 seed / US-006 seek 状态机全部下移到 `src/components/NestingPage.tsx`（行为字节级保留，仅容器由 `<div className="app">` 改为 Fragment 直挂 `.page` flex）。
- `src/style.css` 由 vanilla 前身 1:1 迁入，未做 React 化拆分（沿用命令式 + 类名约定，CSS 框架不引入）。US-001 加 `.tabbar/.tab/.tab-content/.page/.page.hidden/.preview-empty` 暗色样式（与 ControlPanel 同色系）。
- `static/` US-008 起已加入 `.gitignore`（构建产物不入库）；prod 模式前必须 `npm run build` 生成。
- 导出（US-007）已落地：ControlPanel 持 useExport，ExportButtons 渲染 PNG/DXF 按钮（disabled 联动 solving/exporting/无 lastFrame）。详见 US-007 章节。
- ControlPanel DOM 沿用 vanilla 前身 id（`start / status / d_ext / time / seed / multi_seed / seed_count / export_png / export_dxf` 等）以复用 CSS。
- 上传预览页（PreviewPage）US-001 仅占位（提示卡片），待 US-006~US-008 落地 UploadPanel + SizeTabs + ParsedPiecesView + PiecePreviewSVG。

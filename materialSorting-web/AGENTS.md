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

## 文件分工（US-001 Tab 框架 + US-002~US-007 全部落地；US-005 上传预览状态层；US-008 收尾清理）

```
src/
├── main.tsx               # US-001：createRoot + StrictMode
├── App.tsx                # US-001 ✅ Tab 骨架：TabBar + 双 .page 容器（display:none 切换）+ Tooltip 单例
├── style.css              # 由 vanilla 前身 1:1 迁入；US-001 加 .tabbar/.tab/.page/.hidden/.preview-empty
├── vite-env.d.ts          # vite/client 类型
├── types/                 # US-002 ✅：ws.ts / piece.ts / v03.ts；US-005 ✅ parsed.ts（US-004 响应契约）
├── lib/                   # US-002 ✅ ws.ts；US-003 ✅ geometry.ts；US-004 ✅ params.ts；US-006 ✅ seek.ts；US-007 ✅ download.ts
├── store/                 # US-002 ✅ runRegistry.ts；US-003 ✅ appStore.ts；US-001 ✅ uiStore.ts；US-005 ✅ uploadStore.ts
├── hooks/                 # US-002 ✅ useSolveRun.ts；US-003 ✅ useRafThrottle.ts；US-007 ✅ useExport.ts；US-005 ✅ useParseDxf.ts
├── constants/             # US-004 ✅：sizes.ts / colors.ts / v03.ts
├── __tests__/             # US-002 ✅ useSolveRun；US-003 ✅ 各模块单测；US-007 ✅ useExport；US-001 ✅ App 集成 smoke
└── components/
    ├── TabBar.tsx         # US-001 ✅ 顶部 Tab（排料/上传预览），订阅 uiStore.activeTab
    ├── NestingPage.tsx    # US-001 ✅ 排料页（原 App 业务逻辑外提；持 solving/seeds/useSolveRun）
    ├── preview/           # US-001 起：上传预览页
    │   └── PreviewPage.tsx # US-001 占位（US-008 替换为 UploadPanel+SizeTabs+ParsedPiecesView）
    ├── nests/             # US-003 ✅ NestSVG / NestCard / NestLabel；US-005 ✅ NestsGrid；US-006 ✅ NestSVG seek+hover
    ├── ControlPanel/      # US-004 ✅ 8 子组件；US-005 ✅ MultiSeedControls；US-007 ✅ ExportButtons
    ├── curve/             # US-005 ✅ ConvergenceCurve
    ├── playback/          # US-006 ✅ PlaybackBar / Seekbar / SeekReadout
    └── Tooltip.tsx        # US-006 ✅ Portal 单例 + showTooltip/hideTooltip/setHovered/clearHovered
```

## US-005 关键约定（上传预览状态层 调用方必读）

- **状态机：idle → uploading → done | error（任一终态可 reset 回 idle）**。status 是 UploadPanel 渲染分支的唯一驱动：uploading 显示加载态、error 显示红字、done 显示文件名 + 码数概览。改状态名 / 增状态需同步 uploadStore.test.ts 7 项 + useParseDxf.test.tsx 15 项。
- **uploadStore 是单一真相源**：与 runRegistry（高频 mutable，不进 state）相反，uploadStore 把 doc/activeSize/error 全部进 React state —— 解析结果低频，进 store 触发 reconciliation 反而便于 UI 同步。新增字段需在 uploadStore + reset() + useParseDxf setState 三处同步。
- **状态过渡（uploading → done | error）由 useParseDxf 直接 `useUploadStore.setState({...})` 写入，不暴露成 store 公开 action**。store 公开 API 只含调用方语义动作（reset / setSize），避免业务组件误触发状态跳变。
- **防连击：uploadingRef + status==='uploading' 双重防护**。ref 立即生效（async 函数体同步段执行）；setState 异步生效，第二次连击会在 setState 调度前进 hook body。两者任一为 uploading 即忽略。改单重防护会回归「连击两次同时 fetch → 后写入者覆盖前者 doc」问题。
- **FormData 不手设 Content-Type**：fetch 自动加 `multipart/form-data; boundary=...`，手设会丢 boundary → 后端 python-multipart 解析失败。useParseDxf.test.tsx AC#1 有断言。
- **响应契约字段名严格与 server.py `_build_parse_payload` 一致**：`{doc_id, filename, sizes:[{size, pieces:[{label, name, polygon, internal_lines, notches, net_polygon, grain_line}]}]}`。改任一字段需同步后端 server.py + types/parsed.ts + useParseDxf.test.tsx AC#2。
- **activeSize 默认 = doc.sizes[0].size ?? null**：后端按数值升序、null 殿后，sizes[0] 是最小码。空 sizes 兜底 null，UI 自然显示空态。改默认需同步 useParseDxf.test.tsx 3 项 activeSize 用例。
- **错误不抛、不 rethrow**：useParseDxf 内 try/catch 兜底，所有错误（网络错 / JSON 解析错 / 4xx/5xx）统一进 uploadStore.error，UI 自取。返回 Promise<void> 仅为调用方可选 await（如「上传完成后再切 Tab」）。
- **doc / activeSize 在失败时不主动清**：uploading 时清 error 但保留 doc/activeSize（避免切 uploading 时 UI 闪烁）；error 时也只写 status/error，让用户能看到上一次成功的预览（可选 UX，由 UI 决定是否隐藏）。reset() 才彻底清零。
- **fetch URL 是相对路径 `/api/parse-dxf`**：dev 由 Vite proxy 转 :8000，prod 同源；与 useExport fetch('/export') 同口径，前端代码 dev/prod 完全一致。

## US-001 关键约定（Tab 框架调用方必读）

- **双页面常驻 DOM，display:none 切换**：`.page.hidden { display: none }`（不是条件渲染）。切回排料页时 NestingPage 内 useState/useRef/runRegistry 全部保真，进行中求解 / WS / seek 不中断。改策略需同步 6 项 App.test.tsx。
- **uiStore 单字段**：仅 `activeTab: 'nesting' | 'preview'`（默认 `'nesting'`）。求解/WS/seek 等业务状态由 NestingPage 自治，不混入 uiStore。
- **TabBar 只切 store**：`<button onClick=setTab>`；显隐由 App 订阅 activeTab 后切 `.hidden` class（解耦：未来 URL hash 同步只需改 App）。
- **Tab 顺序固定**：排料在前（默认入口）；TABS 数组顺序不可改。
- **TabBar 视觉沿用 style.css**：暗色 `#26282e` 与 ControlPanel 同色系；active 用绿色 `#2ea06c` border-bottom（与 StartButton 同色）。不引入 CSS 框架。
- **NestingPage 用 Fragment**：ControlPanel + main 直接作为 `.page` flex 子元素，不再包 `.app`（避免冗余 DOM + flex 嵌套层）。
- **Tooltip 仍由 App 渲染**：US-006 关键约定 #3（模块级单例）不破；NestingPage 不挂 Tooltip。

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

- **表单字段全字符串存储**：`FormState`（lib/params.ts）的 number 字段（time/seed/d_*/tol_*）+ per_type[pt].d/tol 都按 input.value 字符串持有。理由：per_type 必须「空串 = 继承两档」与「"0" = 显式 0」可区分（旧 vanilla 实现 inp.value.trim() !== '' 同口径）。
- **collectParams(form) 纯函数与旧 vanilla 实现 字段级一致**：params 四档空 → 0 默认；per_type 仅 trim() !== '' 写入；整体空 → null。任何修改必须同步 `lib/__tests__/params.test.ts` 11 组对比 + AC#2 默认值断言。
- **DEFAULT_FORM 与旧 index.html 默认 1:1**：d_int="10"、其余 0；time="60"、seed="0"；sizes 全选；per_type 全空。改默认值需同步 AC#2 + params.test.ts。
- **ControlPanel 不调 useSolveRun**：仅 onStart(cfg) 透传到 App，App 决定是否调 useSolveRun.start（解耦多 seed / 重连 / clear 时机）。
- **DOM id / className 沿用 legacy**：`id="start" / id="status" / id="d_ext" / id="time" / id="seed"` 等保留（CSS 选择器依赖）；`.sizes / .per_type / .pt-row / .chip / .preset / .pt-name i` 等 className 1:1。US-008 清理 CSS 时再统一去 id。
- **PerTypeOverrides 行序 = V03_PTYPES 顺序**：不可重排（影响测试 placeholder / 徽章断言）；`<i>内</i>` 仅 internal=true 的 4 片型（单排/双排/火机袋/裤耳）。
- **React 18 + jsdom 单测输入模拟**：number input 必须用 `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set` native setter 设值后再 dispatch `input` event，否则 React 的 value tracker 检测不到变化（见 ControlPanel.test.tsx AC#6 fill per_type 用例）。

## US-002 关键约定（hook / Registry 调用方必读）

- **WS 连接只在 `start(cfg)` 显式 new**：不要在 useEffect 里 auto-connect，React 18 StrictMode 双 mount 会双连。
- **frames 是 mutable 引用**：`runRegistry.list()` 返回的 RunRecord 本身可被 push，**不进 React state**；高频重绘由 US-003 renderTick 单字段节流。
- **per_type 空 → 序列化为 null**（与旧 vanilla 实现 collectParams 一致；Python `or None` 接住）。
- **density 双口径**：`FrameMsg.density` 是原面积口径（90% 生死线以此为准），`density_sparrow` 是 erode 后 sparrow 自报（参考）。任何决策 / 显示优先 density。
- **不重连**：onclose / onerror 触发 `onDone`（done flag 防重复），交由调用层决定是否重启。
- **测试**：`npx vitest run`，需 `(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;` 才能 avoid act warning；Mock WebSocket 用 ctor 返回 mock 实例的方式（`new WebSocket(url)` 直接拿到 mock）。

## US-003 关键约定（NestSVG / 节流闸 调用方必读）

- **React 只渲染空骨架一次**：`NestSVG` JSX 仅返回 `<svg ref={svgRef}/>`；所有子节点（bg / 用布矩形 / 翻换组 `<g>` / N 个 `<polygon>`）全部 imperative 创建，由 `useRef` 持有。
- **翻转组 transform 必须用 setAttribute 写**：`translate(0 ${gate_mm}) scale(1 -1)`，**不走 JSX prop**，否则 React reconciliation 会用 vdom 覆盖回旧值。
- **renderTick 单字段节流**：`useAppStore` 只持 `renderTick` 一个字段；`useRafThrottle(active)` 在 active=true 时每 100ms bump 一次；NestSVG / NestLabel 通过 `useAppStore(s => s.renderTick)` 订阅 → useEffect 重跑 → setAttribute imperative 更新。frames 仍 mutable push 到 runRegistry。
- **pointsStr(poly, rot, tr) 字节级对齐旧 vanilla 实现**：rad=rot*π/180，c=cos, s=sin，`x'=x*c−y*s+tx`，`y'=x*s+y*c+ty`，每点 `r2(x),r2(y)`，空格分隔。改这个函数必须同步后端 `_transform_polygon` 和 `lib/__tests__/geometry.test.ts`。
- **flipRef 幂等保护**：建 DOM 的 effect 用 `if (run.manifest && !flipRef.current)` 防御 React 18 StrictMode 双 mount / 多次 bump tick 重复建。清空只在 unmount 时发生（React 自动 GC svg 子树）。
- **viewBox 用历史最大 width 作稳定锚**：`W = max(run.viewBoxMaxW, lastFrame.width_mm, 1)`，避免收缩抖动；用布矩形按当前帧 `width_mm` 收缩（直观看到省布过程）。
- **manifest 到达后 DOM 才建**：mount 早于 manifest 时 effect 早 return；manifest 到达后下一次 renderTick bump 才建。后到 manifest 测试覆盖此路径。

## 已踩坑 / 注意事项

- `npm run dev` 启动后 Vite 监听 `localhost:5173`，**curl 必须用 `localhost`**（不是 `127.0.0.1`），Windows 下后者可能 connection refused。
- `tsconfig.node.json` 必须 `composite: true`，否则 `tsconfig.json` 的 references 报错。
- `@types/node` 是 vite.config.ts 隐含依赖，不能省。
- 修改 `vite.config.ts` 后必须重启 `npm run dev`（Vite 自身配置不热重载）。
- `static/` 是构建产物 —— **不要手改**，改了也会被下次 `npm run build` 覆盖。
- **不要在 useEffect dep 里直接列 mutable run**：run 引用不变（registry 持有），effect 实际靠 renderTick 触发；写 `[renderTick, run]` 即可（run 只是稳定引用）。
- **写文件含 Chinese 字符 + bash heredoc 易踩坑**：用 `cat << 'EOF' > file` 单引号 heredoc 时，bash 仍可能因内部 `''`/`\'` 解析失败；安全做法是分多段 append（`cat >> file <<'TESTEND'` 多次），或用 Python heredoc 套外层（注意 `r'''...'''` 与 bash 单引号的冲突）。
- **多 seed all-done 检测不能用 `useState(doneCount)`**：每次 start 闭包值不同，onDone 内读到的是旧值；改用 `useRef` + 手动重置（US-005 落地）。

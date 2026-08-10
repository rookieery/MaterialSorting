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

## 文件分工（US-001 Tab 框架 + US-002~US-008 全部落地；上传预览 US-005 状态层 + US-006 UploadPanel + US-007 PiecePreviewSVG + US-008 SizeTabs/ParsedPiecesView/PreviewPage 容器集成 + 上传预览 US-011 qtyStore 数量状态）

```
src/
├── main.tsx               # US-001：createRoot + StrictMode
├── App.tsx                # US-001 ✅ Tab 骨架：TabBar + 双 .page 容器（display:none 切换）+ Tooltip 单例
├── style.css              # 由 vanilla 前身 1:1 迁入；US-001 加 .tabbar/.tab/.page/.hidden/.preview-empty；上传预览 US-006 加 .upload-panel/.drop-zone/.upload-btn/.upload-status；US-007 加 .piece-preview-svg；US-008 加 .preview-page/.preview-main/.size-tabs/.size-chip/.parsed-pieces-view/.piece-grid/.piece-card*
├── vite-env.d.ts          # vite/client 类型
├── types/                 # US-002 ✅：ws.ts / piece.ts / v03.ts；上传预览 US-005 ✅ parsed.ts（US-004 响应契约）；上传预览 US-011 ✅ qty.ts（PieceQuantity/PieceQuantityMap）
├── lib/                   # US-002 ✅ ws.ts；US-003 ✅ geometry.ts；US-004 ✅ params.ts；US-006 ✅ seek.ts；US-007 ✅ download.ts
├── store/                 # US-002 ✅ runRegistry.ts；US-003 ✅ appStore.ts；US-001 ✅ uiStore.ts；上传预览 US-005 ✅ uploadStore.ts；上传预览 US-011 ✅ qtyStore.ts（+clampQty+getPieceDisplay 纯函数）
├── hooks/                 # US-002 ✅ useSolveRun.ts；US-003 ✅ useRafThrottle.ts；US-007 ✅ useExport.ts；上传预览 US-005 ✅ useParseDxf.ts
├── constants/             # US-004 ✅：sizes.ts / colors.ts / v03.ts
├── __tests__/             # US-002 ✅ useSolveRun；US-003 ✅ 各模块单测；US-007 ✅ useExport；US-001 ✅ App 集成 smoke
└── components/
    ├── TabBar.tsx         # US-001 ✅ 顶部 Tab（排料/上传预览），订阅 uiStore.activeTab
    ├── NestingPage.tsx    # US-001 ✅ 排料页（原 App 业务逻辑外提；持 solving/seeds/useSolveRun）
    ├── preview/           # US-001 起：上传预览页
    │   ├── PreviewPage.tsx # US-008 ✅ 容器（左 UploadPanel + 右 SizeTabs+ParsedPiecesView；未解析空态）
    │   ├── UploadPanel.tsx # 上传预览 US-006 ✅ 左侧上传面板（点击+拖拽+客户端预校验+status 反馈）
    │   ├── SizeTabs.tsx    # 上传预览 US-008 ✅ 尺码切换条（订阅 uploadStore.doc/activeSize；点击 setSize）
    │   ├── ParsedPiecesView.tsx # 上传预览 US-008 ✅ 当前 activeSize 下裁片 grid（每片卡片：PiecePreviewSVG+A/B/C+名）
    │   ├── PiecePreviewSVG.tsx # 上传预览 US-007 ✅ 单片（或多片）母版预览 SVG（命令式渲染 + scale(1,-1) 翻转）
    │   └── __tests__/
    │       ├── UploadPanel.test.tsx      # 上传预览 US-006 ✅ 25 项集成测试
    │       ├── PiecePreviewSVG.test.tsx  # 上传预览 US-007 ✅ 33 项单测（bbox 纯函数 + 5 层渲染 + 翻转 + 标注 + 切片重建）
    │       ├── SizeTabs.test.tsx         # 上传预览 US-008 ✅ 8 项单测（chip 列表 + active 高亮 + 点击 setSize + null 通用码）
    │       ├── ParsedPiecesView.test.tsx # 上传预览 US-008 ✅ 8 项单测（grid 渲染 + 切码刷新 + 空态）
    │       └── PreviewPage.test.tsx      # 上传预览 US-008 ✅ 9 项集成（左 panel+右 main 布局 + 已解析/未解析分支 + 端到端切码）
    ├── nests/             # US-003 ✅ NestSVG / NestCard / NestLabel；US-005 ✅ NestsGrid；US-006 ✅ NestSVG seek+hover
    ├── ControlPanel/      # US-004 ✅ 8 子组件；US-005 ✅ MultiSeedControls；US-007 ✅ ExportButtons
    ├── curve/             # US-005 ✅ ConvergenceCurve
    ├── playback/          # US-006 ✅ PlaybackBar / Seekbar / SeekReadout
    └── Tooltip.tsx        # US-006 ✅ Portal 单例 + showTooltip/hideTooltip/setHovered/clearHovered
```

## 上传预览 US-011 关键约定（qtyStore 数量状态 调用方必读）

- **qtyStore 与 uploadStore 完全解耦**：qtyStore 只持 `quantities: PieceQuantityMap` + 3 actions（setPiecePerSize / setPieceGlobal / resetQuantities），不读 doc/activeSize；uploadStore 不持 quantities。US-014 集成时 uploadStore.reset 联动 `useQtyStore.getState().resetQuantities()`（重传清零）。
- **label 跨码匹配同一片型**：数量 map 以 label（A/B/C...）为 key，跨码语义同片型。依赖后端 `_label_for` 几何排序 `(-centroid_y, centroid_x, -area_mm2, ...)` 在码间稳定（M1787 结构款成立）。name 含码号后缀（如 `noname..28`）跨码不同，故不用 name 做 key。
- **`getPieceDisplay` 是 UI 消费的唯一入口**：四分支严格固定 —— （a）label 未在 map → `{qty:0, editable:true, reason:null}`；（b）mode per-size → qty=`perSize[sizeKey(size)] ?? 0`、editable=true；（c）mode global 且 `globalSource===size` → qty=globalValue、editable=true；（d）mode global 且 `globalSource!==size` → qty=globalValue、editable=false、reason=`'该数值已在「<sizeLabel(globalSource)>」处使用全局数量'`。US-012/013/014 都调此 selector，不直接读 quantities[label]。
- **`clampQty` 是数量值唯一规整入口**：`Math.max(0, Math.min(99, Math.trunc(Number(v) || 0)))`。负数/NaN/非数字→0；小数→截断（非四舍五入）；>99→99；字符串数字→对应整数。setPiecePerSize / setPieceGlobal 内部统一走 clampQty，调用方传入原值即可。
- **从 global 切回 per-size 时 globalValue 继承到 source 码**：`setPiecePerSize(label, size, value)` 内部检测 `prev.mode==='global'`，先把 `prev.globalValue` 写到 `perSize[sizeKey(prev.globalSource)]`（globalSource=null 时 sizeKey='null' 兜底），再写新值到 `perSize[sizeKey(size)]`，最后 mode='per-size' + 清 globalValue/globalSource。改继承逻辑需同步 qtyStore.test.ts「从 global 切回时 globalValue 继承到 source 码」用例。
- **null 码 sizeKey/sizeLabel 双口径**：`sizeKey(null)='null'`（perSize key 空间，与 number 区分）；`sizeLabel(null)='通用'`（人读文案，与 SizeTabs `NULL_SIZE_LABEL` 同语义）。globalSource=null 表示用户在「通用」码切 global，访问 null 码 editable=true（source 匹配），访问 number 码 reason 含「通用」。
- **纯函数 + Zustand 便于测试**：clampQty / getPieceDisplay 是纯函数导出，单测直接调；store 通过 `useQtyStore.getState()` / `setState()` 同步可读可写，无需 React 渲染。24 项单测全部纯函数/store 级，不挂组件。
- **不进 commit / 排料**：US-011 仅前端 UI，数量存 store 不序列化到 intermediate。后端接环（数量→每片复制份数）是后续 Story。

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
- **A/B/C 文字标注放在翻转组 `<g>` 之外**（AC#3 不镜像）：用屏幕坐标（SVG Y-down）直接定位 —— 锚点 = piece bbox 左上角上方 `LABEL_Y_OFFSET=3`（baseline 在 `minY - 3`），`font-size=11` / `dominant-baseline=alphabetic`。改位置 / 字号需同步 PiecePreviewSVG.test.tsx 「A/B/C 标注用屏幕坐标」用例。
- **viewBox = bbox + pad**（默认 `DEFAULT_PAD=14`，最小 `MIN_PAD=4` clamp）：pad 容纳 8mm 刀口半段（4mm）+ 标注文本（~10mm cap 高度）。改 pad 默认需同步「viewBox = bbox + pad」用例（默认 + 自定义 + clamp 三组）。
- **5 层渲染分层（颜色 / 线型严格固定，改需同步测试 + 版师确认）**：layer1 毛版半透明蓝实心 `rgba(80,140,200,0.22)` + `#3f7fbf` 实线边（闭合 polygon）；layer14 净版绿虚线 `#33cc33` `stroke-dasharray=6 3`（闭合 polygon，fill=none）；layer8 内部线橙实线 `#ff8c1a`（polyline 不闭合，line.length<2 跳过）；layer4 刀口黄短线段 `#ffd700`（line，端点 `P ± 4*unit_normal`，长度 `NOTCH_LEN_MM=8`，**待版师确认**）；layer7 布纹线红虚线 `#e53e3e` `stroke-dasharray=5 3`（line，grain_line=null 跳过）。
- **刀口端点 = `P ± 4 * unit_normal`**（unit_normal 来自后端 `notch[2..3]`）：法线为单位向量，half=4，端点 `(x∓4nx, y∓4ny)`，r2 截断。法线为零向量（退化边）→ 0 长度线段（点）兜底。改 NOTCH_LEN_MM 需同步 PiecePreviewSVG.test.tsx 2 项刀口用例 + 版师确认。
- **piece(s) 切换整组重建（不同于 NestSVG flipRef 幂等）**：useEffect 头部 `while (svg.firstChild) svg.removeChild(svg.firstChild)` 清空旧内容后重建。NestSVG 同 run 内 N 帧复用 DOM（高频），PiecePreviewSVG 切片是低频 UI 操作，重建简洁且开销可接受。StrictMode 双 mount 同样安全（清空再建）。
- **AC#4 多片同框**：prop 接受 `ParsedPiece | ParsedPiece[]`，归一化为数组；多片时合并 bbox 计算 viewBox（`piecesBBox`），每片独立渲染 5 层 + 各自 A/B/C 标注。US-008 ParsedPiecesView 用单片卡片，多片能力留作未来扩展（不刻意避免重叠，由调用方决定）。
- **空片容错（polygon=[] 或全无数据）**：`piecesBBox` 返回 null → svg 清空后啥都不画（无 viewBox / 无 flipGroup / 无标注），不留残影。polygon.length<3 跳过 rough 层；其他层照常渲染。改兜底需同步「空片」「polygon<3 跳过 rough」用例。
- **pad prop 最小 4 clamp**：`safePad = Math.max(MIN_PAD, pad)`，防 8mm 刀口半段被裁。负数 / NaN（NaN 经 max 比较返回另一侧）兜底为 4。
- **导出辅助 `pieceBBox` / `piecesBBox` / `BBox` 便于测试**：纯函数 / 类型导出，单测直接调；不改 React 渲染。PiecePreviewSVG.test.tsx 5 项 bbox 用例覆盖（合并所有层顶点 / 空片 null / 无 grain 跳过 / 多片合并 / 全空片 null）。
- **不引入 CSS 框架**：`.piece-preview-svg`（display:block + width:100% + height:100% + bg `#eef0f3`，与排料图同色）由 imperative setAttribute('class', ...) 写入，沿用 style.css；与 `.nest-card svg` 同口径。

## 上传预览 US-008 关键约定（SizeTabs / ParsedPiecesView / PreviewPage 调用方必读）

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

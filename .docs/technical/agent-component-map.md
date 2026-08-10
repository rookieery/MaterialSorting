# 前端组件 / 模块地图（materialSorting-web/）

> 由 `/sync-docs` 维护。改前端先看这里。当前覆盖 US-001 Tab 框架 + US-002 WS 契约 + US-003 NestSVG + US-004 ControlPanel + US-005 多 seed/收敛曲线 + US-006 回放 seekbar + 片 hover tooltip + US-007 导出 PNG/DXF + DXF 上传预览 US-001 Tab 骨架 + 上传预览 US-005 类型/store/hook + 上传预览 US-006 UploadPanel 组件 + 上传预览 US-007 PiecePreviewSVG 命令式渲染 + 上传预览 US-008 SizeTabs/ParsedPiecesView/PreviewPage 容器集成。

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
│   ├── style.css           # 由 vanilla 前身 1:1 迁入；US-001 加 .tabbar/.tab/.page/.hidden/.preview-empty；US-006 加 .upload-panel/.drop-zone/.upload-status；US-007 加 .piece-preview-svg；US-008 加 .preview-page/.preview-main/.size-tabs/.size-chip/.parsed-pieces-view/.piece-grid/.piece-card*
│   ├── vite-env.d.ts        # vite/client 类型引用
│   ├── types/              # US-002：纯数据契约（与 server.py 字段名 1:1）；上传预览 US-005：parsed.ts
│   ├── constants/          # US-004：SIZES / PHASE_COLORS / SEED_COLORS / V03_TABLE
│   ├── lib/                # US-002 起：纯函数工具（ws / geometry / params）；US-007 download
│   ├── store/              # US-002 RunRegistry + US-003 appStore + US-001 uiStore；上传预览 US-005 uploadStore
│   ├── hooks/              # US-002 起：useSolveRun / useRafThrottle；US-007 useExport；上传预览 US-005 useParseDxf
│   ├── components/
│   │   ├── TabBar.tsx       # US-001 顶部 Tab（排料/上传预览）；订阅 uiStore.activeTab
│   │   ├── NestingPage.tsx  # US-001 排料页（原 App.tsx 业务逻辑外提；持 solving/seeds/useSolveRun）
│   │   ├── preview/         # US-001 起：上传预览页（US-006 UploadPanel；US-007 PiecePreviewSVG；US-008 落地 SizeTabs/ParsedPiecesView/PreviewPage 容器集成）
│   │   │   ├── PreviewPage.tsx  # US-008 容器：左 UploadPanel + 右（SizeTabs+ParsedPiecesView）；status=done+doc 时挂主体，否则 .preview-empty 空态
│   │   │   ├── UploadPanel.tsx  # US-006 左侧上传面板（点击+拖拽+客户端预校验+status 反馈）
│   │   │   ├── SizeTabs.tsx  # US-008 尺码切换条：读 uploadStore.doc/activeSize/setSize；chip 行 + active 高亮；null 码→「通用」
│   │   │   ├── ParsedPiecesView.tsx # US-008 当前 activeSize 下裁片 grid：每片卡片（PiecePreviewSVG+A/B/C 徽章+裁片名）；grid auto-fill minmax(220px,1fr)
│   │   │   ├── PiecePreviewSVG.tsx  # US-007 单片（或多片）母版预览 SVG（命令式渲染 + scale(1,-1) 翻转 + 5 层分层 + A/B/C 标注翻转组外）
│   │   │   └── __tests__/
│   │   │       ├── UploadPanel.test.tsx      # US-006 集成测试（25 项）
│   │   │       ├── PiecePreviewSVG.test.tsx  # US-007 单测（33 项：bbox 5 + 命令式 2 + 5 层 11 + 翻转/标注 9 + 单片/多片/空片 4 + 切片重建 3）
│   │   │       ├── SizeTabs.test.tsx         # US-008 单测（8 项：chip 列表 + null→通用 + role=tablist + active 高亮 + 点击 setSize + null 码 + activeSize=null 防御）
│   │   │       ├── ParsedPiecesView.test.tsx # US-008 单测（8 项：grid 渲染 + 每片含 A/B/C+名+svg + key label-name + 切码刷新 + activeSize 不在 doc + 空码空态）
│   │   │       └── PreviewPage.test.tsx      # US-008 集成（9 项：左 panel+右 main 布局 + 4 空态分支 + 已解析挂主体 + SizeTabs 列码 + 切码刷新 grid + 端到端 chip 点击）
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
| `src/components/preview/PreviewPage.tsx` | 上传预览页（**US-008 落地**）：左 UploadPanel + 右（SizeTabs+ParsedPiecesView）双栏；`hasParsed = status==='done' && doc!==null` 决定挂主体 or `.preview-empty` 空态 |
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

## 上传预览 US-005 落地：ParsedDoc 类型 + uploadStore + useParseDxf hook

| 文件 | 角色 |
| --- | --- |
| `src/types/parsed.ts` | 上传解析响应契约：`ParsedDoc` / `ParsedSize` / `ParsedPiece` + `ParsedPt` / `ParsedNotch` / `ParsedGrainLine`。与 `web/server.py _build_parse_payload()` 字段名严格一致：`{doc_id, filename, sizes:[{size, pieces:[{label, name, polygon, internal_lines, notches, net_polygon, grain_line}]}]}` |
| `src/store/uploadStore.ts` | Zustand store：`status: 'idle'\|'uploading'\|'done'\|'error'`、`doc: ParsedDoc\|null`、`activeSize: number\|null`、`error: string\|null` + actions `reset()` / `setSize(s)`。状态过渡（uploading→done\|error）由 hook 直接 `useUploadStore.setState({...})` 写入，不暴露成公开 action |
| `src/hooks/useParseDxf.ts` | 上传 hook：`upload(file)` → POST `/api/parse-dxf` (multipart FormData) → 写 uploadStore。**防连击**：uploadingRef + status==='uploading' 双重防护；成功后默认 activeSize = `doc.sizes[0]?.size ?? null`；不抛错（错误统一进 store.error） |
| `src/store/__tests__/uploadStore.test.ts` | 7 项单测：默认 idle / reset() 从 done+error 回 idle / setSize(number\|null) / 订阅者收到 status & activeSize 变化 |
| `src/hooks/__tests__/useParseDxf.test.tsx` | 15 项单测：AC#1 fetch URL=相对+POST+FormData(file)+不手设 Content-Type；AC#2 200→done+doc+activeSize=sizes[0].size / 空 sizes / null 码组；AC#3 400/413/422→error+CN msg / 非 JSON→statusText / 网络错→Error.message / 非 Error→String(e)；AC#4 防连击 fetch 仅一次 / 成功+失败后 uploadingRef 复位 / 进入 uploading 清旧 error |

### 关键不变量（上传预览 US-005 立，后续故事不得破坏）

1. **状态机：idle → uploading → done \| error** —— status 是 UploadPanel 渲染分支的唯一驱动。改状态名 / 增状态需同步 uploadStore.test.ts 7 项 + useParseDxf.test.tsx 15 项。
2. **uploadStore 是单一真相源** —— 与 runRegistry（高频 mutable，不进 state）相反，uploadStore 把 doc/activeSize/error 全部进 React state。解析结果低频，进 store 触发 reconciliation 反而便于 UI 同步。新增字段需在 uploadStore + reset() + useParseDxf setState 三处同步。
3. **状态过渡由 useParseDxf 直接 `useUploadStore.setState({...})`**，不暴露成 store 公开 action。store 公开 API 只含调用方语义动作（reset / setSize），避免业务组件误触发状态跳变。
4. **防连击：uploadingRef + status==='uploading' 双重防护** —— ref 立即生效（async 函数体同步段执行），setState 异步生效，第二次连击会在 setState 调度前进 hook body。两者任一为 uploading 即忽略。改单重防护会回归「连击两次同时 fetch → 后写入者覆盖前者 doc」问题。
5. **FormData 不手设 Content-Type** —— fetch 自动加 `multipart/form-data; boundary=...`；手设会丢 boundary → 后端 python-multipart 解析失败。useParseDxf.test.tsx AC#1 有断言。
6. **响应契约字段名严格与 server.py `_build_parse_payload` 一致** —— 改任一字段需同步后端 server.py + types/parsed.ts + useParseDxf.test.tsx AC#2。
7. **activeSize 默认 = `doc.sizes[0].size ?? null`** —— 后端按数值升序、null 殿后，sizes[0] 是最小码。空 sizes 兜底 null。改默认需同步 useParseDxf.test.tsx 3 项 activeSize 用例。
8. **错误不抛、不 rethrow** —— useParseDxf 内 try/catch 兜底，所有错误（网络错 / JSON 解析错 / 4xx/5xx）统一进 uploadStore.error，UI 自取。返回 Promise\<void\> 仅为调用方可选 await。
9. **doc / activeSize 在失败时不主动清** —— uploading 时清 error 但保留 doc/activeSize（避免切 uploading 时 UI 闪烁）；error 时也只写 status/error。reset() 才彻底清零。

## 上传预览 US-006 落地：UploadPanel 组件（点击 + 拖拽 + 客户端预校验）

| 文件 | 角色 |
| --- | --- |
| `src/components/preview/UploadPanel.tsx` | 左侧上传面板（`.panel.upload-panel`，沿用 ControlPanel 同色系，width:248px）：渲染拖拽落区（`.drop-zone`，全 panel DnD，dragCounter 防抖）+ 隐藏 `<input type=file accept=".dxf">` + 显式按钮（`.upload-btn`）+ 状态反馈块（`.upload-status.{loading,done,error}`）。订阅 uploadStore.status/doc/error；本地 `localError` 持有客户端校验失败消息（与 store.error 互斥展示，本地优先） |
| `src/components/preview/__tests__/UploadPanel.test.tsx` | 25 项集成测试：DOM 结构 / AC#1 点击 drop-zone + upload-btn + Enter/Space 键盘触发 input.click() / uploading 时禁点击；AC#2 非 .dxf / 多文件 / 超 20MB 三种客户端拒绝 + .DXF 大写后缀通过 / 单文件触发 fetch POST /api/parse-dxf / 校验通过清旧 localError / input.value 重置；AC#1 DnD dragenter/dragleave counter / .dragover 切换 / drop 后清除 / 文案切换；AC#3 status 三态 UI + localError 优先 + 端到端成功/失败路径 |

### 关键不变量（上传预览 US-006 立，后续故事不得破坏）

1. **整个 `<aside>` 是拖拽落区，点击触发限定在 drop-zone / button 上** —— dragenter/dragover/dragleave/drop 挂在根元素（用户可落在 panel 任何子元素上松手），但点击触发文件选择只绑定 drop-zone 和 upload-btn（避免点状态文本误触）。改挂载点会破坏 AC#1 panel-wide DnD 语义。
2. **dragCounter 防子元素 dragleave 抖动** —— 浏览器在 panel 子元素间移动会反复触发 dragenter/dragleave，用 ref 计数器保证只在真正离开 panel（counter=0）时清 `.dragover`。直接 toggle boolean 会因抖动出现 `.dragover` 闪烁。
3. **客户端预校验三件套：.dxf 后缀（MIME 容错）+ 单文件 + 20MB** —— 后缀判定用 `name.toLowerCase().endsWith('.dxf')`（不看 file.type，因 Windows 下 MIME 五花八门）；多文件 / 超大直接拦不发请求；20MB 与后端 `server.py UPLOAD_MAX_BYTES` 一致（双校验，前端先拦 + 后端兜底）。改任一项需同步 UploadPanel.test.tsx 3 项 reject 用例。
4. **`localError` 与 `store.error` 互斥展示（本地优先）** —— 客户端校验失败消息进本组件 `useState`，不污染 uploadStore 状态机（hook 仅在 HTTP 流程内切 status）；UI 渲染分支 `displayError = localError ?? (status==='error' ? store.error : null)`。改优先级会破坏 AC#3 错误展示口径。
5. **`e.target.value = ''` 重置 input value** —— 否则选同一文件不触发 change（input value 去重机制），用户重试同一文件会哑火。UploadPanel.test.tsx AC#2 有断言。
6. **状态驱动 UI 分支：status 是唯一驱动** —— uploading 显示 `.upload-status.loading` + 按钮文案 "重新上传" 变 "选择 DXF 文件" + disabled；done 显示文件名 + "已解析 N 码 / M 裁片"（N=doc.sizes.length，M=sum(pieces.length)）；error 显示红字（来自 store.error 或 localError）；idle 不渲染 status 块。改分支需同步 UploadPanel.test.tsx AC#3 9 项用例。
7. **drop-zone + upload-btn 双入口触发同一 handlePickClick** —— 不直接绑到 input.change，而是 click → inputRef.click() → input.change，便于 DnD 与点击共享校验/上传路径（drop 直接进 handleFiles 跳过 input click）。改单一入口会破坏 AC#1 双交互模式。
8. **不引入 CSS 框架** —— `.upload-panel` / `.drop-zone` / `.upload-btn` / `.upload-status` 全部沿用 style.css 命令式 className，与 ControlPanel 暗背景 `#26282e` + 绿色 `#2ea06c` 强调同色系；新增 `.drop-zone.dragover` 用绿色边框高亮，与 StartButton 同色。

## 上传预览 US-007 落地：PiecePreviewSVG 命令式渲染（5 层分层 + scale(1,-1) 翻转 + A/B/C 不镜像）

| 文件 | 角色 |
| --- | --- |
| `src/components/preview/PiecePreviewSVG.tsx` | 单片（或多片，AC#4）母版预览 SVG。命令式渲染范式（参考 NestSVG）：React 仅渲染 `<svg ref/>`；useEffect 内 imperative 建翻转组 `<g>` + 各层节点（polygon / polyline / line / text）。**5 层分层**：layer1 毛版半透明蓝实心 + `#3f7fbf` 实线边（闭合 polygon）；layer14 净版绿虚线 `#33cc33` `dasharray=6 3`（闭合 polygon，fill=none）；layer8 内部线橙实线 `#ff8c1a`（polyline 不闭合，line.length<2 跳过）；layer4 刀口黄短线段 `#ffd700`（line，端点 `P ± 4*unit_normal`，`NOTCH_LEN_MM=8` 待版师确认）；layer7 布纹线红虚线 `#e53e3e` `dasharray=5 3`（line，grain_line=null 跳过）。**翻转组 transform = `translate(0 minY+maxY) scale(1 -1)`**（NestSVG `translate(0 gate)` 是 minY=0/maxY=gate 的特例）；**A/B/C 文字标注在翻转组外**（屏幕坐标，避免镜像），锚点 = bbox 左上角上方 LABEL_Y_OFFSET=3（baseline 在 minY - 3），font-size=11。**viewBox = bbox + pad**（默认 14，最小 4 clamp）。**piece(s) 切换整组重建**（useEffect 头部 `while removeChild` 清空）。导出 `pieceBBox` / `piecesBBox` / `BBox` 便于单测 |
| `src/components/preview/__tests__/PiecePreviewSVG.test.tsx` | 33 项单测：bbox 纯函数 5（合并所有层顶点 / 空片 null / 无 grain 跳过 / 多片合并 / 全空片 null）；AC#1 命令式 2（React 仅 `<svg ref/>` + 子节点 imperative / StrictMode 双 mount 不残留）；AC#2 渲染分层 11（5 层颜色/线型/数据 + layer1 points 字符串 + internal line<2 跳过 + 刀口端点 P±4*normal 横/斜向 + grain null 跳过 + 全 5 层同框节点数）；AC#3 翻转+标注 9（flip transform 单片/多片合并 bbox / viewBox 默认+自定义+clamp / 标注在翻转组外 / 标注屏幕坐标 / label 空串跳过 / 多片各自标注）；AC#4 单片/多片/空片容错 4（单片 1 rough 1 label / 多片 rough=label=pieces.length / 空片啥都不画 / polygon<3 跳过 rough）；AC#5 切片重建 3（切 piece 清旧 + viewBox 重算 / 切到空片清空 / pad 变化触发 viewBox 重算 dep） |
| `src/style.css` | 加 `.piece-preview-svg { display:block; width:100%; height:100%; min-height:0; background:#eef0f3 }`（与 `.nest-card svg` 同口径，背景与排料图同色） |

### 关键不变量（上传预览 US-007 立，后续故事不得破坏）

1. **命令式渲染范式（参考 NestSVG.tsx）** —— React 仅渲染 `<svg ref/>`；useEffect 内 imperative 建 flipGroup `<g>` + 各层节点（polygon / polyline / line / text），用 `setAttribute` 写 transform / points / stroke / ...，**逃逸 React reconciliation**。改任何 attr 走 JSX prop 会被 React 用 vdom 覆盖回旧值（同 NestSVG 关键约定 #2）。React 18 StrictMode 双 mount 也安全（useEffect 头部清空 + 重建）。
2. **翻转组 transform = `translate(0 minY+maxY) scale(1 -1)`** —— sparrow Y-up → SVG Y-down（与 PNG / R12-DXF / NestSVG 一致）。`minY+maxY` 是 bbox 的 Y 对称轴，翻转后 bbox 内几何视觉与 sparrow 视图一致（不上下颠倒）。NestSVG 是其特例（minY=0, maxY=gate → `translate(0 gate) scale(1 -1)`）。改字面量需同步 PiecePreviewSVG.test.tsx AC#3 「翻转组 transform」单片 + 多片两组用例。
3. **A/B/C 文字标注放在翻转组 `<g>` 之外（AC#3 不镜像）** —— 用屏幕坐标（SVG Y-down）直接定位；锚点 = piece bbox 左上角上方 `LABEL_Y_OFFSET=3`（baseline 在 `minY - 3`），`font-size=11` / `dominant-baseline=alphabetic` / `text-anchor=start`。改位置 / 字号需同步 PiecePreviewSVG.test.tsx 「A/B/C 标注用屏幕坐标」用例。**多片同框时每片各自 bbox 锚点独立渲染**（不合并）。
4. **viewBox = bbox + pad**（默认 `DEFAULT_PAD=14`，最小 `MIN_PAD=4` clamp）—— pad 容纳 8mm 刀口半段（4mm）+ 标注文本（~10mm cap 高度，cap 顶 ≈ minY - 3 - 0.8*size = minY - 11.8，刚好在 pad=14 内）。改 pad 默认需同步 PiecePreviewSVG.test.tsx 「viewBox」用例（默认 + 自定义 + clamp 三组）。
5. **5 层渲染分层（颜色 / 线型严格固定，改需同步测试 + 版师确认）** —— layer1 毛版半透明蓝实心 `rgba(80,140,200,0.22)` + `#3f7fbf` 实线边（闭合 polygon，stroke-width=1.5）；layer14 净版绿虚线 `#33cc33` `stroke-dasharray=6 3`（闭合 polygon，fill=none，stroke-width=1.2）；layer8 内部线橙实线 `#ff8c1a`（polyline 不闭合，line.length<2 跳过，stroke-width=1）；layer4 刀口黄短线段 `#ffd700`（line，端点 `P ± 4*unit_normal`，长度 `NOTCH_LEN_MM=8`，**待版师预览时确认调整**，stroke-width=1.4）；layer7 布纹线红虚线 `#e53e3e` `stroke-dasharray=5 3`（line，grain_line=null 跳过，stroke-width=1.2）。配色口径与 `scripts/preview/*.svg` 已版师确认的方案一致。
6. **刀口端点 = `P ± 4 * unit_normal`**（unit_normal 来自后端 `notch[2..3]`）—— 法线为单位向量（后端 collect.py `_nearest_edge_with_normal` 计算），half=NOTCH_LEN_MM/2=4，端点 `(x∓4*nx, y∓4*ny)`，r2 截断。法线为零向量（退化边）→ 0 长度线段（点）兜底，不渲染异常。改 NOTCH_LEN_MM 需同步 PiecePreviewSVG.test.tsx 2 项刀口用例（横/斜向 normal）+ 版师确认。
7. **piece(s) 切换整组重建（不同于 NestSVG flipRef 幂等）** —— useEffect 头部 `while (svg.firstChild) svg.removeChild(svg.firstChild)` 清空旧内容后重建。NestSVG 同 run 内 N 帧复用 DOM（高频，renderTick ~10fps 节流），PiecePreviewSVG 切片是低频 UI 操作（用户点选某片），重建简洁且开销可接受。StrictMode 双 mount 同样安全（清空再建）。
8. **AC#4 多片同框** —— prop 接受 `ParsedPiece | ParsedPiece[]`，归一化为数组；多片时合并 bbox 计算 viewBox（`piecesBBox`），每片独立渲染 5 层 + 各自 A/B/C 标注。US-008 ParsedPiecesView 用单片卡片，多片能力留作未来扩展（不刻意避免重叠，由调用方决定是否同框）。
9. **空片容错（polygon=[] 或全无数据）** —— `piecesBBox` 返回 null → svg 清空后啥都不画（无 viewBox / 无 flipGroup / 无标注），不留残影。polygon.length<3 跳过 rough 层；net_polygon.length<3 跳过 net 层；internal line.length<2 跳过该条；其他层照常渲染。改兜底需同步 PiecePreviewSVG.test.tsx「空片」「polygon<3 跳过 rough」用例。
10. **pad prop 最小 4 clamp** —— `safePad = Math.max(MIN_PAD, pad)`，防 8mm 刀口半段被裁。负数 / NaN（NaN 经 max 比较返回另一侧）兜底为 4。
11. **导出 `pieceBBox` / `piecesBBox` / `BBox` 便于测试** —— 纯函数 / 类型导出，单测直接调；不改 React 渲染。5 项 bbox 用例覆盖（合并所有层顶点 / 空片 null / 无 grain 跳过 / 多片合并 / 全空片 null）。
12. **不引入 CSS 框架** —— `.piece-preview-svg`（display:block + width:100% + height:100% + bg `#eef0f3`，与排料图同色）由 imperative `setAttribute('class', ...)` 写入，沿用 style.css；与 `.nest-card svg` 同口径。改 CSS 需同步 `.piece-preview-svg` 规则（US-008 ParsedPiecesView 卡片复用）。

## 上传预览 US-008 落地：SizeTabs + ParsedPiecesView + PreviewPage 容器集成（Tab 打通）

| 文件 | 角色 |
| --- | --- |
| `src/components/preview/SizeTabs.tsx` | 尺码切换条。订阅 uploadStore `doc`/`activeSize`/`setSize`；渲染 `<div class="size-tabs" role="tablist">` + 每 chip `<button class="size-chip" role="tab" aria-selected>`；chip 顺序 = doc.sizes 顺序（后端按数值升序、null 殿后）；**null 码 → 「通用」文案**（`NULL_SIZE_LABEL`）；activeSize 匹配项加 `.active`；点击 → `setSize(s.size)`；**doc=null 时返回空 Fragment**（PreviewPage 兜底，双重防御） |
| `src/components/preview/ParsedPiecesView.tsx` | 当前 activeSize 下裁片 grid。订阅 uploadStore `doc`/`activeSize`；`doc.sizes.find(s => s.size === activeSize)` 过滤当前码（防御性兜底找不到 → pieces=[]）；grid 用 CSS Grid `auto-fill + minmax(220px, 1fr)`；每片 `<div class="piece-card">` 含 `.piece-card-head`（label 徽章 + name）+ `.piece-card-body`（PiecePreviewSVG 单片模式）；`key=${label}-${name}` 跨码安全；pieces=[] 时 `.parsed-pieces-empty` 「该尺码无裁片」 |
| `src/components/preview/PreviewPage.tsx` | 容器组件。订阅 uploadStore `status`/`doc`；**`hasParsed = status === 'done' && doc !== null`** 决定分支：true → `<SizeTabs/> + <ParsedPiecesView/>`；false → `.preview-empty` 空态卡片（沿用 US-001 className）；布局 `<div class="preview-page"><UploadPanel/><section class="preview-main">…</section></div>`（左 panel 固定 248px + 右 main flex:1） |
| `src/style.css` | 加 `.preview-page{flex;display}` + `.preview-main{flex-col;overflow:auto}` + `.size-tabs{flex-wrap;gap 6}` + `.size-chip{border-radius:14; #34363d bg}` + `.size-chip.active{#2ea06c bg #fff}` + `.parsed-pieces-view{padding 12;overflow:auto}` + `.piece-grid{grid auto-fill minmax(220px,1fr) gap 10}` + `.piece-card{#2a2c32 bg;radius 4;min-height 180}` + `.piece-card-head{#1c1d22 bg}` + `.piece-card-label{#2ea06c 徽章 18×18 radius 9 #fff 600}` + `.piece-card-name{#cdd word-break}` + `.piece-card-body{flex padding 6}` + `.parsed-pieces-empty{center 32 #888}` |
| `src/components/preview/__tests__/SizeTabs.test.tsx` | 8 项单测：AC#1 渲染 doc.sizes 全部 chip（按后端顺序）+ null→「通用」+ role=tablist/tab + activeSize=null 防御；AC#1 active 高亮 + aria-selected + 点击 setSize(number\|null) 切换 + .active 转移 |
| `src/components/preview/__tests__/ParsedPiecesView.test.tsx` | 8 项单测：AC#2 doc=null 空 + 渲染当前码 pieces + 每片含 label+name+svg + .piece-grid 容器 + key label-name 安全；切 activeSize grid 刷新 + activeSize 不在 doc 防御 + 空码空态 |
| `src/components/preview/__tests__/PreviewPage.test.tsx` | 9 项集成：AC#3 左 panel+右 main 结构 + 4 空态分支（idle/uploading/error/默认）；AC#3 done+doc 挂主体 + SizeTabs 列码 + ParsedPiecesView 当前码片数 + 切 activeSize→刷新 + 端到端 chip 点击切 grid |

### 关键不变量（上传预览 US-008 立，后续故事不得破坏）

1. **三个新组件都从 uploadStore 读、不持本地状态** —— SizeTabs 读 `doc`/`activeSize`/`setSize`；ParsedPiecesView 读 `doc`/`activeSize`；PreviewPage 读 `status`/`doc`。store 是单一真相源（US-005 关键约定），**切 Tab 后状态保留 = store 模块级单例 + App display:none 不卸载**（AC#5 由 store 持久性保证，组件本身无需任何持久化逻辑）。改状态来源会破坏 AC#5。
2. **PreviewPage 空态分支用 `hasParsed = status === 'done' && doc !== null`** —— 双重条件防御（done 理论必有 doc，但 TS 类型上 doc nullable）。uploading/error 时仍显示空态卡片（不显示「上传中…」之类的状态行 —— 那是 UploadPanel 的事），保持右侧稳定布局。改分支需同步 PreviewPage.test.tsx 4 项空态用例。
3. **SizeTabs chip 顺序 = doc.sizes 顺序**（后端按数值升序、null 殿后，`_size_sort_key`）—— **前端不二次排序**，保证 UI 顺序与后端语义一致。改排序需同步后端 `_build_parse_payload` + SizeTabs.test.tsx 「渲染 doc.sizes 全部」用例。
4. **null 码 chip 显示「通用」**（`NULL_SIZE_LABEL`）—— 母版里极少出现的「不分码」片（统计上代表通用码），用人读文案代替空字符串/「null」。改文案需同步 SizeTabs.test.tsx 「null 码渲染为通用」用例。
5. **SizeTabs doc=null 时返回空 Fragment**（`return <></>`）—— 双重防御（PreviewPage 在 doc=null 时不挂载 SizeTabs，组件本身也兜底）。改返回值需同步 SizeTabs.test.tsx 「doc=null」用例。
6. **ParsedPiecesView 用 `doc.sizes.find(s => s.size === activeSize)` 过滤当前码** —— 理论必命中（SizeTabs 只能切到 doc.sizes 里的码），防御性兜底 `matched=undefined` → pieces=[] → 显示「该尺码无裁片」空态。改过滤逻辑需同步 ParsedPiecesView.test.tsx 「activeSize 不在 doc.sizes」用例。
7. **piece key 用 `${label}-${name}`** —— label 在码内唯一（A/B/C/...，后端 `_label_for` 已保证），name 是母版 block 名（GBK 解码后中文），两者拼合跨码安全。同码内可能多片同名（label 不同）或同 label 不同名 —— key 拼合兜底所有场景。改 key 需同步 ParsedPiecesView.test.tsx 「key 用 label-name」用例。
8. **每片卡片用 PiecePreviewSVG 单片模式**（不传数组，US-007 AC#4 多片能力留作未来扩展）—— grid 是「每片独立预览」语义，单片卡片视觉清晰。改多片模式需先与版师确认 grid 单卡承载多片的 UX 必要性。
9. **piece-card 视觉沿用 .nest-card 同口径** —— 暗背景 `#2a2c32` + 圆角 + 上方 `.piece-card-head`（label 徽章 + 裁片名）+ 下方 `.piece-card-body`（SVG 自适应）；与排料页 NestCard 视觉一致。label 徽章 `.piece-card-label` 用绿色 `#2ea06c` 圆形 + 白字，与 StartButton / TabBar active / size-chip active 同色系。
10. **grid 用 CSS Grid `auto-fill + minmax(220px, 1fr)`** —— 浏览器宽度自适应列数（窗口缩小时单卡不被压扁，最小 220px 保证 SVG 不退化成窄条）。改 minmax 需视觉回归核对（M1787 每码 ~10 片 × ~180px 高度 ≈ 一屏）。
11. **不引入 CSS 框架** —— `.preview-page` / `.preview-main` / `.size-tabs` / `.size-chip` / `.parsed-pieces-view` / `.piece-grid` / `.piece-card*` 全部沿用 style.css 命令式 className，与 ControlPanel / NestCard 暗背景 `#26282e/#2a2c32` + 绿色 `#2ea06c` 强调同色系。
12. **AC#5 切 Tab 后状态保留验证（App.test.tsx）** —— App.test.tsx 切到 preview Tab 后断言 `.preview-empty` 仍在（doc=null 默认状态走空态分支，与 US-001 占位的 className 一致 —— 复用 `.preview-empty`/`.preview-empty-card`，不破坏 US-001 App 集成 smoke 测试）。改 PreviewPage 空态 className 需同步 App.test.tsx 第 101 行断言。

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
- 上传预览页（PreviewPage）US-001 仅占位（提示卡片），待 US-008 落地 SizeTabs + ParsedPiecesView + 容器布局（左 UploadPanel + 右切码 + 裁片 grid）。US-006 UploadPanel + US-007 PiecePreviewSVG 已落地，等 US-008 拼装。

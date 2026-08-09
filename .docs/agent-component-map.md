# 前端组件 / 模块地图（materialSorting-web/）

> 由 `/sync-docs` 维护。改前端先看这里。当前覆盖 US-001 脚手架 + US-002 WS 契约；US-003..007 落地后逐节补全。

## 顶层结构

```
materialSorting-web/
├── index.html              # Vite 入口（dev: /, prod: 被 build 覆写到 static/index.html）
├── package.json            # scripts: dev / build / preview / typecheck / test
├── vite.config.ts          # base 切换（dev '/' / build '/static/'）+ proxy /export /ws
├── vitest.config.ts        # US-002 起：jsdom + globals，独立于 vite.config.ts
├── tsconfig.json           # src/ strict TS（target ES2020, jsx react-jsx）
├── tsconfig.node.json      # vite.config.ts 单独编译（composite）
├── legacy/                 # 旧 vanilla 三件套归档（index.html/app.js/style.css，仅参考）
├── src/                    # 源码
│   ├── main.tsx            # createRoot(<StrictMode><App/></StrictMode>)
│   ├── App.tsx             # US-001 占位骨架（panel + main + bottom 三段）
│   ├── style.css           # 由 legacy/style.css 迁入，暂未拆模块
│   ├── vite-env.d.ts        # vite/client 类型引用
│   ├── types/              # US-002：纯数据契约（与 server.py 字段名 1:1）
│   ├── lib/                # US-002 起：纯函数工具
│   ├── store/              # US-002 起：RunRegistry（mutable，不进 React state）
│   ├── hooks/              # US-002 起：useSolveRun（单 run 生命周期）
│   └── __tests__/          # US-002 起：vitest 单测
└── static/                 # npm run build 产物（被 FastAPI mount 到 /static）
    ├── index.html
    └── assets/index-[hash].{js,css}
```

## dev / prod 双路径

| | dev | prod |
| --- | --- | --- |
| 入口 | `npm run dev` → `localhost:5173` | `npm run build` 后由 `ms-web` (:8000) serve |
| base | `/`（Vite 默认） | `/static/`（FastAPI mount 路径） |
| 前端如何打后端 | 相对路径 `/export` `/ws/solve`，由 Vite proxy → `127.0.0.1:8000` | 同源 `127.0.0.1:8000/export` `/ws/solve`（无需 proxy） |
| 验证命令 | `curl localhost:5173/`、Python websockets 连 `ws://localhost:5173/ws/solve` | `curl 127.0.0.1:8000/`、`curl -I 127.0.0.1:8000/static/assets/index-*.js` |

## vite.config.ts 关键点

- `base` 由 `command` 决定：`build` → `/static/`，否则 `/`。**勿改成静态值**，否则 dev 或 prod 之一会断。
- `build.outDir = 'static'`、`emptyOutDir = true` —— 每次构建清空 `static/` 后重写。
- `server.proxy['/ws'] = { target, ws: true, changeOrigin: true }` —— **`ws: true` 必填**，否则 WS 升级请求会被 Vite 当普通 HTTP 处理返回 404。
- `server.strictPort = true` —— 锁死 :5173，便于后端 / 文档稳定引用。

## tsconfig 两文件分工

- `tsconfig.json`（include `src`）：app 代码 strict 模式，`noEmit` + `moduleResolution: bundler`，`jsx: react-jsx`（不需要 `import React`）。**`noUnusedLocals` / `noUnusedParameters` 都开**，未用的 import / 形参会直接报错 —— 测试文件同样受此约束。
- `tsconfig.node.json`（include `vite.config.ts`，`composite: true`）：被 `tsconfig.json` 通过 `references` 引用，独立检查配置文件。

## US-002 落地：WS 契约 + RunRegistry + useSolveRun

| 文件 | 角色 |
| --- | --- |
| `src/types/piece.ts` | `Pt` / `Polygon` / `PieceInfo` / `PlacedItem` —— 与 server.py / solver.py 字段名 1:1 |
| `src/types/v03.ts` | `SolveParams`（d_ext/d_int/tol_ext/tol_int）+ `PerTypeOverride` / `PerTypeOverrides` |
| `src/types/ws.ts` | `StartPayload` + `ServerMsg = ManifestMsg \| FrameMsg \| FinalMsg \| ErrorMsg` 判别联合（density/density_sparrow 双口径都在 FrameMsg/FinalMsg） |
| `src/lib/ws.ts` | `solveWsUrl()` —— `${proto}://${location.host}/ws/solve`（dev/prod 自适配，**不要写死 :8000/:5173**） |
| `src/store/runRegistry.ts` | 模块级 mutable 数组持有 RunRecord（frames/lastFrame 不进 React state）；提供 `create / clear / list / bestRun` |
| `src/hooks/useSolveRun.ts` | 单 run 生命周期：`start(cfg)` 显式 `new WebSocket` → onmessage 分发 manifest/frame/final/error → Registry 落盘 + 回调；onclose/onerror → onDone（done flag 防重复），**不重连** |
| `src/__tests__/useSolveRun.test.tsx` | 6 项单测：StrictMode 双 mount 0 连接 / StartPayload 字段逐项 / manifest+frame+final 分发 + Registry 落盘 / error 分支 / URL 相对 host / per_type 透传 |

## US-003 落地：NestSVG 命令式渲染 + 节流闸（单 seed 可视化）

| 文件 | 角色 |
| --- | --- |
| `src/lib/geometry.ts` | `r2(x)` 四舍五入 2 位 + `pointsStr(poly, rot, tr)` —— 与旧 app.js / 后端 `_transform_polygon` 字节级一致 |
| `src/store/appStore.ts` | Zustand 单字段 store：仅持 `renderTick`（+ `bumpRenderTick` action）；高频 frames 落 runRegistry 不进 React state |
| `src/hooks/useRafThrottle.ts` | `useRafThrottle(active)` —— active=true 时 rAF + 100ms 时间戳闸 bump renderTick；隐藏标签页自动暂停 |
| `src/components/nests/NestSVG.tsx` | 命令式 SVG：JSX 仅 `<svg ref/>`；manifest 到达后 imperative 建 bg/fab/flipGroup + N polygon；订阅 renderTick setAttribute('points'/'display') |
| `src/components/nests/NestLabel.tsx` | 顶部标签：`seed N · X.XX%`；订阅 renderTick 重渲染（轻量文本，可走 reconciliation） |
| `src/components/nests/NestCard.tsx` | 单 run 卡片容器（NestLabel + NestSVG） |
| `src/App.tsx` | US-003 拼装：硬编码 sizes=[30,32]/time=30/seed=0/baseline；按钮触发 useSolveRun.start + useRafThrottle(seeds.length>0) |
| `src/lib/__tests__/geometry.test.ts` | 5 项：r2 截断 / pointsStr 与旧 app.js 字节级一致（9 组对比）/ 0°/90° 可视化 sanity / 输出无尾随空格 |
| `src/components/nests/__tests__/NestSVG.test.tsx` | 8 项：空骨架 / manifest 建全 DOM（含 transform）/ 重复 bump 不重建 / frame 写 points + display / 旋转 90° 输出 / placed↔未 placed 切换 / 无 frame 不写 viewBox / 后到 manifest 路径 |

### 关键不变量（US-003 立，后续故事不得破坏）

1. **React 只渲染空 `<svg>` 一次** —— NestSVG 所有子节点（bg rect / 用布 rect / 翻转组 `<g>` / N 个 `<polygon>`）必须 imperative 创建，用 `useRef` 持有；任何 JSX prop 写入都会被 reconciliation 覆盖。
2. **翻转组 transform 必须用 `setAttribute` 写** —— `translate(0 ${gate_mm}) scale(1 -1)`，对应 sparrow Y 向上 → SVG Y 向下（与 PNG / R12-DXF 导出一致）。
3. **renderTick 单字段节流** —— `appStore` 只持 `renderTick` 一个字段；frames / lastFrame 仍 mutable 在 runRegistry 里；高频渲染通过订阅 renderTick → useEffect 重跑 → setAttribute。
4. **pointsStr 字节级对齐** —— `rad=rot*π/180; c=cos; s=sin; x'=x*c−y*s+tx; y'=x*s+y*c+ty`，每点 `r2(x),r2(y)` 空格分隔，无尾随空格。修改必须同步 `lib/__tests__/geometry.test.ts` 与后端 `_transform_polygon`。
5. **flipRef 幂等保护** —— effect 用 `if (run.manifest && !flipRef.current)` 防 StrictMode 双 mount / 多次 tick 重建 DOM。
6. **viewBox 用历史最大 width 作稳定锚** —— `W = max(run.viewBoxMaxW, lastFrame.width_mm, 1)`，与旧 app.js 一致，避免收缩抖动。

### 关键不变量（US-002 立，后续故事不得破坏）

1. **WS 连接只在 `start()` 显式开** —— 不在 useEffect 里 auto-connect，否则 React 18 StrictMode 双 mount 会双连。
2. **frames 是 mutable 引用** —— `runRegistry.list()` 返回的元素本身可被 hook 直接 push，不触发任何 React 调度；高频渲染由 US-003 的 `renderTick` 单字段节流。
3. **per_type 空 → 序列化为 null** —— 与旧 app.js `collectParams` 一致（Python 侧 `or None` 接住）。
4. **`density` vs `density_sparrow` 双口径** —— `density` 是原面积口径（= `total_area / (width*gate)`，与 90% 生死线一致），`density_sparrow` 是 erode 后 sparrow 自报（参考）。前端**任何决策 / 显示都优先 density**。
5. **测试需设 `IS_REACT_ACT_ENVIRONMENT = true`** —— 否则 `act()` 会警告（但仍能跑）。Mock WebSocket 用 ctor 返回 mock 实例的方式（`new WebSocket(url)` 拿到的是 mock）。

## 与旧 vanilla 的对应（迁移基线）

| 旧（legacy/app.js） | 新位置（计划） | 故事 | 状态 |
| --- | --- | --- | --- |
| `SIZES` `PHASE_COLORS` `SEED_COLORS` `V03` 常量 | `src/constants/*.ts` | US-004 | TODO |
| `WebSocket` + `onmessage` dispatch | `src/lib/ws.ts` + `src/hooks/useSolveRun.ts` | US-002 | **已落地** |
| `makeRun`/`renderFrame`/`pointsStr` 命令式 SVG | `src/components/nests/NestSVG.tsx` + `src/lib/geometry.ts` + `src/components/nests/NestCard.tsx` + `src/components/nests/NestLabel.tsx` | US-003 | **已落地** |
| 全局节流闸（`globalLastDraw` + `RENDER_INTERVAL_MS`） | `src/store/appStore.ts`（renderTick 单字段）+ `src/hooks/useRafThrottle.ts` | US-003 | **已落地** |
| `collectParams` + `per_type` 面板 | `src/components/ControlPanel/*` | US-004 | TODO |
| `drawCurve` 收敛曲线 | `src/components/curve/ConvergenceCurve.tsx` | US-005 | TODO |
| `seek` `frameAtTime` 回放 | `src/components/playback/*` + `src/lib/seek.ts` | US-006 | TODO |
| `exportAs(fmt)` | `src/hooks/useExport.ts` + `src/components/ControlPanel/ExportButtons.tsx` | US-007 | TODO |
| run 状态（frames 数组 / lastFrame / finalDensity） | `src/store/runRegistry.ts` | US-002 | **已落地** |

## 已知差异（脚手架阶段）

- `src/App.tsx` US-003 已拼装 NestCard + useRafThrottle（硬编码 sizes=[30,32]/time=30/seed=0/baseline 参数）；US-004 ControlPanel 接管参数输入后，移除硬编码常量。
- `src/style.css` 是 `legacy/style.css` 的 1:1 副本，未做 React 化拆分（US-008 收尾时清理）。
- `static/` 当前在 git 跟踪中（US-001 验证需要）；US-008 计划加入 `.gitignore`。
- 单 seed 仅：多 seed 对比 + 收敛曲线（US-005）/ 回放 seekbar（US-006）/ 导出（US-007）尚未拼装，`<div className="bottom">` 仍为占位。

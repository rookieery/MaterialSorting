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
| `makeRun`/`renderFrame`/`pointsStr` 命令式 SVG | `src/components/nests/NestSVG.tsx` + `src/lib/geometry.ts` | US-003 | TODO |
| `collectParams` + `per_type` 面板 | `src/components/ControlPanel/*` | US-004 | TODO |
| `drawCurve` 收敛曲线 | `src/components/curve/ConvergenceCurve.tsx` | US-005 | TODO |
| `seek` `frameAtTime` 回放 | `src/components/playback/*` + `src/lib/seek.ts` | US-006 | TODO |
| `exportAs(fmt)` | `src/hooks/useExport.ts` + `src/components/ControlPanel/ExportButtons.tsx` | US-007 | TODO |
| run 状态（frames 数组 / lastFrame / finalDensity） | `src/store/runRegistry.ts` | US-002 | **已落地** |

## 已知差异（脚手架阶段）

- `src/App.tsx` 仅为占位（panel + main + bottom 三段壳）。真实控制面板、SVG 排料图、曲线、回放从 US-002 起逐故事填入。
- `src/style.css` 是 `legacy/style.css` 的 1:1 副本，未做 React 化拆分（US-008 收尾时清理）。
- `static/` 当前在 git 跟踪中（US-001 验证需要）；US-008 计划加入 `.gitignore`。

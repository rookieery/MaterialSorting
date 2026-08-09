# materialSorting-web — Agent 速查

> React 18 + TypeScript 5 + Vite 5 前端。改这里之前先看 `.docs/agent-component-map.md`。

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
| 后端调用 | 相对路径 `/export`、`ws://${location.host}/ws/solve` → Vite proxy → :8000 | 同源直连 :8000 |
| 触发 WS 升级 | Vite proxy `ws: true`（**必填**） | 浏览器原生 |

## 关键约束（CLAUDE.md 引用）

1. **不引入 CSS 框架**：style.css 由 legacy 迁入，沿用命令式 + 类名约定。
2. **坐标系 `scale(1,-1)`**：sparrow Y 向上 → SVG Y 向下，flipGroup 用 setAttribute 写 transform（避免 React reconciliation 覆盖）。US-003 落地。
3. **命令式 polygon 更新**：每帧 setAttribute('points' / 'display')，由 Zustand renderTick 单字段 ~10fps 节流，**逃逸 React reconciliation**。US-003 落地。
4. **legacy/ 勿改**：仅作迁移参考。US-008 删除。

## 文件分工（US-002 起填入）

```
src/
├── main.tsx               # US-001：createRoot + StrictMode
├── App.tsx                # US-001 占位壳 → 后续故事拼装 ControlPanel + NestsGrid + Curve + Playback
├── style.css              # legacy 1:1 副本（US-008 清理）
├── vite-env.d.ts          # vite/client 类型
├── types/                 # US-002：ws.ts / piece.ts / v03.ts
├── lib/                   # US-002..007：ws.ts / geometry.ts / params.ts / seek.ts / download.ts
├── store/                 # US-002..006：runRegistry.ts / appStore.ts
├── hooks/                 # US-002..007：useSolveRun.ts / useRafThrottle.ts / useExport.ts
├── constants/             # US-004..005：sizes.ts / colors.ts / v03.ts
└── components/
    ├── nests/             # US-003..005：NestSVG / NestCard / NestLabel / NestsGrid
    ├── ControlPanel/      # US-004, US-007
    ├── curve/             # US-005：ConvergenceCurve
    ├── playback/          # US-006：PlaybackBar / Seekbar / SeekReadout
    └── Tooltip.tsx        # US-006
```

## 已踩坑 / 注意事项

- `npm run dev` 启动后 Vite 监听 `localhost:5173`，**curl 必须用 `localhost`**（不是 `127.0.0.1`），Windows 下后者可能 connection refused。
- `tsconfig.node.json` 必须 `composite: true`，否则 `tsconfig.json` 的 references 报错。
- `@types/node` 是 vite.config.ts 隐含依赖，不能省。
- 修改 `vite.config.ts` 后必须重启 `npm run dev`（Vite 自身配置不热重载）。
- `static/` 是构建产物 —— **不要手改**，改了也会被下次 `npm run build` 覆盖。

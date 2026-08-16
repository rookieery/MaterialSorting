# Todo

> 由 `.claude/scripts/add-todo.sh` 与 `/todo` skill 维护。分区占位符（`*(No ...)*`）请勿删除 —— 脚本靠 sed 定位插入。

## Open Issues

*(No open issues)*

## Pending Tasks

*(No pending tasks)*

## Suggestions

*(No suggestions)*

## Recently Completed

- [x] US-001 Vite+React+TS 脚手架与 dev/prod 联通（tsc 0 error / build / dev proxy / ms-web serve 全绿） — completed on 2026-08-09 16:26
- [x] US-002 WS 类型 + RunRegistry + useSolveRun hook（6 项单测：StrictMode / payload / manifest+frame+final / error / URL / per_type） — completed on 2026-08-09 16:32
- [x] US-003 NestSVG 命令式渲染 + renderTick 节流闸（单 seed 硬编码参数 + WS 端到端验证 354 帧 / final 66.82%） — completed on 2026-08-09 16:45
- [x] US-004 v0.3 参数面板 ControlPanel（17 项单测：collectParams 与 legacy 11 组对比 + AC#1..#7 集成） — completed on 2026-08-09 17:05
- [x] US-006 回放 seekbar + 片 hover tooltip（47 项单测：seek 16 / Tooltip 11 / PlaybackBar 9 / NestSVG.seek 11；端到端 WS 220 帧验证 maxElapsed/frameAtTime 与旧 vanilla 实现 等价） — completed on 2026-08-09 17:35
- [x] US-007 导出 PNG/DXF（46 项单测：download 13 + useExport 15 + ExportButtons 14 + ControlPanel 集成 +4；端到端 POST /export 验证 PNG 58KB / DXF 66KB + AC#7 ezdxf 回读几何一致） — completed on 2026-08-09 18:00
- [x] US-008 清理 legacy + 更新文档 + CI（删 materialSorting-web/legacy/；repo grep 旧 vanilla 文件名 / 命令式 DOM 查找 0 命中；README + CLAUDE.md 启动顺序明确 dev/prod；static/ 加入 .gitignore；tsc + vitest 161/161 全绿；ms-web 启动 serve 新构建产物 DRLuzXqu 验证） — completed on 2026-08-09 18:10
- [x] 上传预览 US-007 PiecePreviewSVG 命令式渲染（33 项单测：bbox 5 + 命令式 2 + 5 层 11 + 翻转/标注 9 + 单片/多片/空片 4 + 切片重建 3；后端 curl POST /api/parse-dxf M1787+5156 验证 payload 结构匹配 ParsedPiece；浏览器验证延后到 US-008 集成） — completed on 2026-08-10 19:10
- [x] US-024 展示+导出切新版裁片 5 层（前端 497/497 全绿 typecheck clean；后端 e2e smoke 176 片 5 层全链路：master→collect→write_piece_dxf 5 层→_read_piece_full 5 层（notch 法线按最近边重算）→load_nest_pieces 共享 transform→intermediate.json net=128/internal=88/notch=104/grain=128→manifest→NestSVG 渲染 5 层；export.py PNG+R12-DXF 5 层独立 POLYLINE/POINT/LINE entity；DXF layer id 集 {0,1,4,7,8,14}；constants/colors.ts LAYER5_COLORS 共享；/api/ptypes 10 ptype 代表裁片带 5 层） — completed on 2026-08-11 22:40
- [x] US-027 前端 stop() + 求解状态机 phase（idle/running/stopped/done/error）（前端 520/520 全绿 typecheck clean build 无报错；useSolveRun 新增 stop()+case stopped；RunRecord 加 stopped 字段；NestingPage solving→phase 五态 + handleStop/handleRestart + lastStartCfgRef；ControlPanel 5 个输入组件加 disabled prop running 态冻结；types/solvePhase.ts 导出供 US-028 复用；6 项新单测覆盖 stop OPEN/CLOSED + stopped finish + 3 phase 转换 + running 冻结） — completed on 2026-08-12 12:45

- [x] US-029 Tour 基础设施：tourStore + TourOverlay 高亮引擎 + useTour 控制器 + TabBar 右上角入口（tourStore: activeTour/stepIndex/seen + start/next/prev/close/markSeen/resetSeen + localStorage 持久化 seen 与 TOUR_VERSION 版本号不一致清 seen；TourOverlay: Portal body z-index 2000 + spotlight box-shadow 镂空 + bubble 按 placement 定位 + 零尺寸居中兜底 + resize/scroll(capture) 重算；useTour advance-on-ready 骨架；types.ts Placement/TourStep/TourDef；steps/index DEMO_PREVIEW_TOUR；TabBar .tour-entry 按钮 + 下拉菜单；13 新增单测 tourStore.test.ts 8 + TourOverlay.test.tsx 5，552 total 全绿） — completed on 2026-08-13 11:52

- [x] US-030 preview tour 全量 + advance-on-ready 完整 + 首次自动触发（5 步 previewTour：upload/parsed/set-qty/committed/goto-nesting；advance-on-ready 改检查当前步 ready 语义 + 200ms 轮询自动推进 + 最后一步自动完成；useTourAutoTrigger 独立 hook App 调用 subscribe activeTab 首次进入自动触发；data-tour 锚点 5 处；前端 558/558 全绿 typecheck clean build 无报错；useTour.test.tsx 5 项 + TourOverlay 等待态 1 项单测覆盖 advance-on-ready） — completed on 2026-08-13 12:12

- [x] US-031 nesting tour 全量 + 求解状态联动（5 步 nestingTour：doc-banner/params/solve/result/export；result/export 联动步 ready 读 runRegistry.list().some(r=>r.lastFrame!==null) 帧快照绕开 NestingPage useState 外部不可读；前 3 步告知型；5 锚点 data-tour 落地 doc-banner/param-form/start-btn/nest-wrap/export-group；TOURS 注册 nesting 复用 US-030 自动触发；前端 563/563 全绿 typecheck clean build 无报错；nestingTour.test.tsx 5 项单测覆盖 ready 谓词 + 锚点 query + 步骤结构） — completed on 2026-08-13 12:25

- [x] US-032 手动入口完善 + 关闭交互打磨 + 完整单测（TabBar 下拉两项「查看上传预览/超排指引」+ 仅当前 Tab 可点置灰规则；close 统一 markSeen 消除切回 Tab 重复触发 bug1；TourOverlay ESC/遮罩/skip 关闭 + flipPlacement 四方向级联回退修 bug3 + prefers-reduced-motion + scrollIntoView；+18 新单测 TourOverlay +6 / TabBar +7 / useTour +2 / tourStore +3，581 total 全绿；菜单最终两项由 21102a3 fix 收敛） — completed on 2026-08-13 12:34

- [x] 矩阵化重构 US-002 QtyMatrix 数量矩阵组件（新建 QtyMatrix.tsx 主组件 + QtyMatrixCell/RowFillPopover 同文件子组件 + style.css .qty-matrix 系列；行=label 并集[徽章+名+compact 缩略图+填充 popover] × 列=doc.sizes 全码[列头 button setSize+active 高亮]；格内 clampQty 编辑 + Enter/Tab 跳格跳过缺片格 + 0/.zero 与特例/.override 与缺片/— 三态；sticky 表头/首列/底行 + 45vh 内滚 + Σdemand 小计 + 全 0 警示 + 重置 1；32 项新单测 616 total 全绿 typecheck clean build 无报错；CDP headless Chrome 24/24 浏览器断言（11 码横排/sticky/编辑/填充/切码/openZoom/窄屏横滚）；未接入 PreviewPage（US-003 集成）） — completed on 2026-08-16 15:30

- [x] 矩阵化重构 US-003 拆除旧交互+预览页集成+全 0 拦截（SizeTabs/PieceQtyDialog/Switch 及三测试删除，grep openQtyDialog src/=0、uploadStore 删 qtyDialog/QtyDialogTarget/open-closeQtyDialog；PreviewPage 挂 QtyMatrix 替 SizeTabs、删 PieceQtyDialog 单例（仅余 PieceZoomModal），两条 subscribe 联动 effect 不动；ParsedPiecesView 降级为按码图形预览（卡片头只读「N 份」+ 区标题「图形预览 · 码 X」，openZoom+a11y 保留）；PieceZoomModal 单位改「份」；ControlPanel.handleStart 全 0 拦截（computeTotalCutPieces===0 → onStatus 提示+不发 WS start，doc=null 不拦）；新增 5 项 start guard 单测含线格式回归 A@28=2→payload；589/589 全绿 typecheck clean build 无报错；ms-web 冒烟 GET / 200 + parse API 200（chrome-devtools-mcp 不在本会话工具集，浏览器端回归留作 US-005）） — completed on 2026-08-16 16:20

- [x] 矩阵化重构 US-004 parse 透传 ptype/paired+物理片数口径（server.py `_build_parse_payload` 对全码 pieces 整体 assign_group_no（与 commit 同 gmap），每片 additive 加 ptype（GROUP_NAMES 链路，无映射 null）+ paired（ptype ∈ PAIR_TYPES，nesting_bounds.load_pieces 导入，分层合规）；types/parsed.ts 加可选 ptype?/paired?（缺字段 ×1 兜底）；QtyMatrix 新增 pairedOf/multOf/rowPaired + 行头 .qty-paired-badge「×2」徽章 + 行合计/每码小计/工具条总片数升级物理口径 Σdemand×(paired?2:1)；SizePicker.computeTotalCutPieces 同口径（全 0 拦截语义不变：乘数≥1）；QtyMatrix.test 32→38 + SizePicker.test +6；601/601 全绿 typecheck clean build 无报错 + 后端 39 tests 过 + M1787 curl 110 片全含两字段（paired=PAIR_TYPES 六类）+ label 对齐 0 失配回归；杀遗留 8000 端口旧进程后验证（chrome-devtools-mcp 不在本会话工具集，浏览器端回归留作 US-005）） — completed on 2026-08-16 16:40

- [x] 矩阵化重构 US-005 tour 锚点迁矩阵+文档同步（previewTour parsed/set-qty 锚点 size-tabs/piece-card-head → qty-matrix/qty-rowhead，QtyMatrix 落地两 data-tour 锚点 + ParsedPiecesView 删死锚点；文案改矩阵操作描述（列头切码/格内编辑/行头填充/特例高亮/×2）；TOUR_VERSION '1'→'2' bump 强制老用户重看 + index.ts 版本历史注释；previewTour.test.tsx 新建 5 项（id 序列/锚点零残留/版本号/文案/渲染命中）+ TourOverlay step1 mock 锚点跟迁；文档同步 agent-component-map（覆盖清单+文件树+US-005 节+US-008/014/030 警告头）+ business-overview 工作台交互 1/2 条 + CLAUDE.md 数据流主线 + AGENTS.md US-005 节；606/606 全绿 typecheck clean build 无报错；chrome-devtools-mcp 不在本会话工具集，锚点渲染命中由 previewTour.test.tsx jsdom 断言覆盖） — completed on 2026-08-16 17:00

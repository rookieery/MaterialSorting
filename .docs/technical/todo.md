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

- [x] US-030 preview tour 全量 + advance-on-ready 完整 + 首次自动触发（5 步 previewTour：upload/parsed/set-qty/committed/goto-nesting；advance-on-ready 改检查当前步 ready 语义 + 200ms 轮询自动推进 + 最后一步自动完成；useTourAutoTrigger 独立 hook App 调用 subscribe activeTab 首次进入自动触发；data-tour 锚点 5 处；前端 558/558 全绿 typecheck clean build 无报错；useTour.test.tsx 5 项 + TourOverlay 等待态 1 项单测覆盖 advance-on-ready） — completed on 2026-08-13 12:12

- [x] US-031 nesting tour 全量 + 求解状态联动（5 步 nestingTour：doc-banner/params/solve/result/export；result/export 联动步 ready 读 runRegistry.list().some(r=>r.lastFrame!==null) 帧快照绕开 NestingPage useState 外部不可读；前 3 步告知型；5 锚点 data-tour 落地 doc-banner/param-form/start-btn/nest-wrap/export-group；TOURS 注册 nesting 复用 US-030 自动触发；前端 563/563 全绿 typecheck clean build 无报错；nestingTour.test.tsx 5 项单测覆盖 ready 谓词 + 锚点 query + 步骤结构） — completed on 2026-08-13 12:25

*(No completed items)*

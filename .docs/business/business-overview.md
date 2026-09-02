# 业务概览 — 牛仔裤排料引擎

> 项目"是什么、为谁做、到哪一步"的一页速览。需求/方案/规则细节见同目录其它文档；技术实现见 [technical/](../technical/)。
> 权威约束 spec：[排料规则_详细版.md](排料规则_详细版.md)。

## 产品概述

**MaterialSorting** 是一套牛仔裤排料（marker making）引擎与可视化工作台，从 `D:\Pattern_Making` 的排料模块迁移而来，重构为正经 Python 包并与打板模块完全解耦。

**核心目标**：把 M1787 直筒款套排的布料利用率做到 **90%+** —— 版师认可的"行业生死线"。**当前对拍基线（US-005，2026-08-18）**：110 片（母版全码 g01–g10 × 11 码、全 demand=1、无合成镜像）600s `{0,180}` 无 erode seed 0 → **real 85.59%**（原面积口径 `total_area/(width×1980)`，用布 5459.4mm；sparrow 自报 88.72% 是 1910 约束带口径）。旧基线 85.79%（176 片、含 L/R 合成镜像，实例口径已废）**归档不再对拍**。距 90% 仍有约 4 个百分点，是后续 v0.3 约束层（旋转公差 + 内片重合）要攻的主目标。

**用户**：版师 / 排料工程师。交付物是可直接裁剪的 marker（PNG 预览 + R12-DXF 给 ET2008 刻绘）。

## 当前状态

| 模块 | 状态 | 说明 |
|------|------|------|
| DXF 解析（dxf_parser） | ✅ 稳定 | 抗住母版 3 怪癖；`collect.py`（US-003）深度解析 5 层 IR（毛版/净版/内部线/刺口/布纹线） |
| 裁片加载（nesting_bounds） | ✅ 稳定 | manifest 驱动：单裁片 → 布纹对齐 → 归一化（**US-001 v2 起无 L/R 镜像展开，引擎不合成任何片**）；**US-024 起 5 层透传**（notch 法线按 outline 最近边读时重算）。母版全码 → 110 NestPiece（M1787 = 10 片 × 11 码） |
| intermediate 事实源 | ✅ 稳定 | `pieces_intermediate.json`（schema v2：每片 polygon + 5 层 + label（g 码），无 ptype/side；全流程事实源，US-022 起 label 字段供 demand 编辑） |
| sparrow 基线求解 | ✅ 跑通 | **新基线 85.59%**（US-005：110 片全 demand=1，600s `{0,180}` 无 erode seed 0，real 口径）；旧 85.79%（176 片含合成镜像）已归档 |
| v0.3 约束层 | ⚠️ 部分 | 2026-08-17 起重合/旋转改**全局上限**（`MAX_OVERLAP_MM=10` / `MAX_ROTATION_TOL_DEG=45`，每片型钳制表已删，版师按片型的工艺参考值留在排料规则文档）+ 校验已写；旋转公差 solver 侧未主动实施 |
| 实验框架（experiments） | ✅ 跑通 | free_rot / v0_rot / erode / erode_rot 四模式 + 多种子方差 |
| 母版上传 → 解析 → commit | ✅ 落地 | `/api/parse-dxf`（US-004）+ `/api/commit-to-nesting`（US-010 Path A）+ `/api/ptypes`（US-020）；解析成功自动 commit + 解锁超排 Tab（US-021） |
| 求解输入 demand | ✅ 落地 | US-022：per-size 数量编辑（qtyStore），0=该码跳过；前端 qtyStore → WS `quantities` |
| 可视化工作台（web） | ✅ 落地 | FastAPI + WS，React 18 + TS 5 + Vite 5 前端（US-001~US-028：Tab 框架 + 上传预览 + 5 层渲染 + 求解停止/重启状态机） |
| 求解停止 / 重启 | ✅ 落地 | US-025 进程化（`solve_with_callback_proc` + `solve_worker`）+ US-026 WS stop 协议 + US-027 phase 五态状态机 + US-028 SolveControls 按钮组 |
| 导出 PNG / R12-DXF / PLT | ✅ 落地 | 用原始母版轮廓，**US-024 起 5 层叠加**（毛版+净版+内部线+刺口+布纹线），ET2008 兼容；**US-033 起 PLT/HPGL**（WT V8.8 / LIKE 绘图仪原生链路，DXF 在该软件实测无法打印）；**2026-08 撞机修正**：PLT 门幅框/内容按输入 gate_mm 裁剪（2026-08-28 起单一幅宽口径，幅宽受限设备直接输入更小门幅）+ PD 分块 ≤10点/≤110B + 走纸引导（设备级差异详见 [technical/agent-api-reference.md](../technical/agent-api-reference.md)） |
| 配置驱动求解 CLI（cli 子包） | ✅ 落地 | 2026-08-19：`ms-run-config <config.json>`（**9 键**配置：master_dxf/gate_mm 必填 + sizes/time/seeds/per_type/quantities + band——第 8 键 2026-08-22 起：`band={'enabled':true,'label':g码}` 腰头成带，worker 进程内成带+展开 + prefix——第 9 键 2026-08-25 起：`prefix={'enabled':true,'front':g码,'back':g码}` 起始端成套前后幅，worker 进程内构造+展开；band/prefix on 时 `--lns` 自动 warn 跳过）→ 独立 commit → **串行**多 seed 求解 + best 汇总（real 口径）；产物只落 `out/config_runs/<run>_<时间戳>/`（pieces/ + intermediate + result.json + curve_s\*/best_frame_s\* 逐帧轨迹），物理隔离 web 事实源，与 ms-web 可并行互不干扰，无需浏览器。**PC-001（2026-08-19）起求解进程化**：`solve_pieces` 走多进程 + 逐帧 `should_stop` 中止（terminate 杀子进程、best-so-far 帧交付）+ `curve_s{seed}.json`/`best_frame_s{seed}.json` 落盘（标定/kill 规则数据源），Ctrl-C（退出码 130）不丢已完成轮。**PC-002（2026-08-19）起串行 seed portfolio 控制器**（`cli/portfolio.py`）：逐帧 incumbent banking（`best` 升级为帧级全局最优、含完整布局，被 kill/中断 seed 的最优帧同样参与）+ R0 达标即停（`--target`，任一帧达标 → 当前 seed 被 stop + 剩余队列不启动，退出码 0）+ R4 队列耗尽交付；result.json 新增 `portfolio` 段；`--params` 标定参数文件旗标（PC-003/004 消费）；单 seed 无 `--target` 保持旧 best 语义（冒烟对拍兼容）。**策略双模式/极限运行旗标**：`--strategy [se|race]` 与 `--extreme`（race 门杀 × 实验结论参数糖衣，见上表对应行；与 `--kill`/`--lns` 等互斥关系见 README「配置驱动求解」） |
| 母版编号植入脚本 | ✅ 可用 | 2026-08-18：`python scripts/embed_piece_codes.py <母版.dxf>` 把 g01+ 编号 TEXT 植入母版（与 Web parse 同源 `assign_codes`，幂等 + 自校验）—— 版师在 ET2008 打开母版即可把图面片对上 g 码；`_coded.dxf` 产物可直接再上传 Web，g 码不变 |
| 腰头成带（waist_band） | ✅ v2 纯腰链构造（现行） | **US-009 核心模块**（`nesting_engine/waist_band.py`）+ **US-011~013 编排/UI** + **v2 构造性链构造重写**（2026-08-21：N 条单副本异码链降序滑移贴靠 + 整链点对称翻转 ⇒ 开口朝左 + 最大码在最右；替换 v1 spyrrow 带内子求解/US-014 成对重试；贴触口径链内缝隙 0.00mm）；端到端 A/B **+2.27pt**（ON 88.35% vs OFF 86.08%）。**2026-08-22 简化**：US-015 填料混带 / US-013 预演与 ack 硬警告 / US-010 go-no-go 闸门 / US-014 验收 CLI 整体删除（历史报告 `.docs/business/腰头成带_AB验收报告_US014/US015.md` 留档），band 收敛「勾选 + 选 g 码」极简主流程（`fill<45%` 唯一守门人）；同日 **band×策略解禁**（`/api/strategy/start` 复用 `_parse_band` 单一校验点把 band 写进 8 键 config，worker 进程内成带） |
| 起始端成套前后幅（prefix） | ✅ US-005 收官（accept） | 建议1 v2（PRD `tasks/prd-prefix-head-set.md`，五项决策 2026-08-25 入档）：用户指认前/后幅 g 码 → 资格码（该码前、后 demand 均 ==2，版师 P2）seeded 随机取一（不出 UI）→ 4 片同码构造性竖排贴靠成 `PS_*` 组合片自由进主解（跨界填充，版师 P3）。**US-001 已落地**（`nesting_engine/prefix.py`，探针 `out/tmp_probe/prefix_lib.py` 移植收敛）：interleave 交错序定稿（0 封闭腔 vs grouped 2）、rot180 负坐标记账单测锁死、展开契约复用 `expand_placements`（rot0/rot180 黄金用例+包络断言）、冒烟 `python -m materialsorting.nesting_engine.prefix` 对拍 P0（5336 size34：bbox 1155×1458 / fill 83.3% / 贴触 0.00mm / 封闭腔 0；资格码 {32,33,34,35,38}）。P0 探针密度代价 −0.14pt ≈ 0、组合片 4/4 seed 自然锚定布头。**US-002 已落地**（同文件）：段置换钉位守卫 —— 组合片 min_x ≤ 6mm 已锚定即整体跳过（P0 常态 4/4 seed a=0.145~0.333mm ⇒ 零成本），未锚定时 c1 硬切/c2 软切（flex 400mm 取跨线片最少）A/C/B 三组刚性重组钉布头，跨线片驱逐后三优先序回填（home+微调梯 → 右起滑贴 → 尾追加兜底），`constraints.validate` 全图复检失败回滚；三守卫参数单测锁死（skip_at_head=6/eps=5/flex=400），`--pin-demo` 冒烟 4/4 seed PASS（PIN≡FREE Δ0.00pt）。**US-003 已落地**（web 编排，2026-08-25）：WS StartPayload 可缺省 `prefix={enabled,front,back}`（无 size，seeded 选码）；`_parse_prefix` 单一校验点（front≠back + 无资格码 error 文案指路数量矩阵「配成 2+2」）；worker `_build_prefix` 进程内构造 + `exclude_pids` pid 级扣减（manifest on/off 逐字段一致）+ PS_ 组合片 extra_items + `_emit_placed` 同单点展开 + final 置换挂钩（min_x≤6mm 跳过，P0 常态）；双开 band+prefix 只记录带位（band_pos 进 prefix_runs 工件与 final，不置换，决策④）；前缀工件 `out/prefix_runs/*.json`（US-005 A/B 回放源）；CLI `--lns` prefix 双 warn 预埋。真实 5336 冒烟：stage prefix/38/fill 83.6%/holes 0、119 片无 PS_ 泄漏、pin skipped、密度 87.33%；双开 band_pos min_x 1169/max_x 2310/距布尾 5567mm、密度 86.13%。**US-004 已落地**（前端链路）：`lib/params.ts` prefix 解析 + 资格码预检（无 2+2 资格码本地提示）、`useSolveRun` prefix 透传 + stage 状态行「起始端成套构造中（尺码 N）…」、布局设置弹窗「起始端成套前后幅」分区（勾选 + 前/后幅下拉，80×80 缩略图 + 徽章复用 band 模式，默认预选面积最大两片 = 5336 g02/g03，无尺码控件）。**US-005 已收官（2026-08-25 accept，验收器 `python -m materialsorting.web.prefix_accept`）**：五判据全 PASS —— 4-seed 均值 **−0.675pt（on 88.17% 反超 off 87.50%）**、形态 4/4（贴触 0/y 咬合/180° 交替/锚定布头）、双开 89.86%/90.35%（P0 基准同量级 + 带位记录）、确定性同 seed 重跑 1042==1042 帧逐帧全等、导出三格式 `PS_` 零泄漏；浏览器 CDP 19/19（UI 密度 0.000pt 对拍）。终验绑定 **P0 口径 per_type**（web 全 0 口径 60s 不收敛、帧位随速率漂移，实测入档）；报告 `.docs/business/起始端成套前后幅_AB验收报告_US005.md`。**2026-09-02 增补开工（prd-prefix-extra-piece，引擎层 US-001 已落地）**：顶部异码补片 + 近满幅联合选码 —— `build_prefix_plan` additive `extra_pid`（第 5 成员同款贴触滑移，pid 如 `PS_g02+g03@34+g02@32`，extra_pid=None 逐字节回归）+ 新 `select_prefix_plan` 几何搜索取代 seeded 随机（遍历 资格码×片型×异码×rot 取 5 片原始轮廓 union 高 ≤ gate 最大者，无 RNG；全无可行兜底回 4 片 seeded——用户三项定案：兜底/不设缝隙阈值/保留 0°/180°）；5336 实测 120 组合选 套装@38+顶部 g02@32 H=1978.4mm residual=1.6mm 贴触全 0；web worker/WS/预览/前端接线在后续 US-002~004。**增补 US-002 已落地（2026-09-02，web 接线）**：`solve_worker._build_prefix` 切 `select_prefix_plan`（兜底 fallback=True 回 seeded 4 片）；主解 `exclude_pids` 双形态 —— worker 传 `Counter(m['pid'] for m in members)` 部分扣减（异码 pid 扣组合片实际占用的份数、余量照排主解，placed 条数守恒 = 全量 Σdemand）；stage 消息 additive `extra_label`/`extra_size`/`residual_mm`（经 routes_ws 白名单透传）、final 消息 prefix 段同携 extra/fallback；`prefix_accept` 长度护栏 4→`in (4,5)`；真实 5336 双码量复测 placed=105=Σdemand、g02_31 恰 1 份（chunk 顶部补片独占）。**增补 US-003 已落地（2026-09-02，预览端点对齐）**：`/api/prefix-preview` 选码换同一 `select_prefix_plan` 真相源（同 payload 与求解同选 A/片型/B/rot，选码确定性化后不再依赖 seed 对齐）；构造段（build_pid_meta+搜索，秒级）经 `run_in_threadpool` 线程池化防阻塞事件循环（会话解析/校验仍主线程先行）；响应 additive `extra:{label,size}|null`/`residual_mm`/`gate_mm`/`fallback`（`n_members` 4 或 5，成员循环泛型天然带第 5 片，无 PS_ 哨兵不变）；5336 端到端实测 4.45s < 5s 红线、选定与 worker 全等（套装@38+顶部 g02@32 residual 1.55mm）；前端类型/文案接线在 US-004。**增补 US-004 已落地（2026-09-02，前端类型+双形态文案）**：`types/ws.ts` StageMsg additive `extra_label`/`extra_size`/`residual_mm`（可选，null 与键缺席同判=兜底，旧后端安全）+ `types/band.ts` PrefixPreviewResponse additive `extra:{label,size}|null`/`residual_mm`/`gate_mm`/`fallback`（n_members 4（兜底）或 5（补片），5 片缩略自动渲染、异码片 size_color 同码同色跨片型）；求解状态行双形态「起始端成套构造中（尺码 A＋g@B）…」、prefix-zoom 放大层 hint 追加「＋ 顶部 g@B 异码片 · 余 Xmm 近满幅」（兜底/无键回落现行形态）；vitest 815 全过 + CDP 浏览器 25/25（预览与求解同选 @38+g02@32 residual 1.55mm 对拍一致、final 88.03% 首列 5 片形态目检）。二期：带尾置换四割线、LNS frozen（**CLI/策略 prefix 接口已于 2026-08-25 落地**：`/api/strategy/start` 复用 `_parse_prefix` 校验写进 9 键 config，`ms-run-config --strategy` 与手写 config 直跑均支持） |
| 策略双模式 + 极限运行（cli `--strategy`/`--extreme` + web 四路由） | ✅ 落地 | **策略双模式 `--strategy [se|race]`（2026-08-25）**：给定总预算换更高利用率（race 门杀默认档 180s/门 90s：门处严格破 bar 才续跑、省出预算再投资、首 seed 豁免；se 筛延 90s 筛 + 180s 冠军延长），web「高级运行」`/api/strategy/*` 四路由 + 弹窗，band/prefix 可透传。**极限运行 `--extreme`（2026-08-30）**：糖衣旗标 = race 门杀 × 5336 实验结论参数（`--extreme-budget` 600（缺省）/1200 × 门 τ=0.5 × p0.70/et=false/workers4，参数是实验结论固化非可调项），目标从「期望最优」换「右尾最优」；web `/api/extreme/*` 四路由 + 前端独立按钮（与高级运行同会话 409 单飞互斥——三臂并行实测 CPU 争抢截断墙钟预算），band/prefix 随载荷透传；同总预算 4h 三臂对拍 extreme **91.71%** ≥ race 默认 91.31%（accept，[极限运行_AB验收报告.md](极限运行_AB验收报告.md)） |
| 90% 利用率目标 | 🎯 进行中 | 距 90% 生死线约 4pp（M1787 基线口径），主攻旋转公差 + 内片重合；**5336 上 4h 极限运行右尾 91.71% 已破线**（长跑 + 实验参数 + 门杀省预算合力，M1787 主线仍在攻） |

## 核心业务实体

### 片型（10 类）

> **口径注记（US-005，2026-08-18）**：本表是**版师工艺参考表**，不是代码数据模型 —— 现行实现中片型中文名（GROUP_NAMES/PAIR_TYPES/INTERNAL_TYPES）已全部删除，代码/界面/导出对单片一律用 **g 码**（g01+，单一真相源 `nesting_engine/labeling.py`）标识；「配对?」「重合/旋转参考值」列仅为工艺范围参考（求解钳制是全局上限，见下注）。M1787 每码 10 片 = g01..g10（跨码同号同片型，由母版 block 编号复用/几何稳定排序保证）。

| 片型（工艺参考名） | 配对? | 重合参考值 (mm) | 旋转参考值 (°) | 说明 |
|------|------|------------------|------------------|------|
| 前片 | L+R | 2.0 | 1 | 主片，严格布纹 |
| 后片 | L+R | 2.0 | 1 | 主片，严格布纹 |
| 腰 | L+R | 0.4 | 3 | |
| 前袋 | L+R | 0.4 | 30 | 允许较大旋转 |
| 后袋 | L+R | 0.4 | 1 | |
| 机头 | L+R | 0.4 | 3 | |
| 单排 | 单片 | 10.0 | 15 | 内片，可重合可旋 |
| 双排 | 单片 | 10.0 | 15 | 内片 |
| 火机袋 | 单片 | 5.0 | 8 | 内片 |
| 裤耳 | 单片 | 10.0 | 45 | 内片，几乎任意角 |

> **2026-08-17 起本表降为版师参考值**：求解钳制不再按片型 —— 后端全局上限 `MAX_OVERLAP_MM=10` / `MAX_ROTATION_TOL_DEG=45`（`constraints.py`），用户在高级配置弹窗按 g 码逐片显式填 0–10mm / 0–45°（默认 0 = 不重合 / 锁布纹线；2026-08-18 回退 US-004 矩阵化后不再按码号细分），solver 按 `min(申请值, 全局上限)` 收边。上表数值作为各片型工艺合理范围的参考保留。

> **引擎不合成镜像（US-001 v2 起，数量即一切）**：旧口径"配对片由单裁片镜像展开为 L+R 两份"已删除 —— 引擎对母版轮廓零合成、零丢弃（WYSIWYG：母版 N 个轮廓 → intermediate N 条 NestPiece）。要排左右两片就在数量矩阵把该（g 码 × 码号）数量填 2；母版本身自带左右两片轮廓的（如 M1787），两片各自有独立 g 码。内片（单排/双排/火机袋/裤耳等小片）仍是利用率提升的"填充料"。

### 码号

`DEFAULT_SIZES = [28, 29, 30, 31, 33, 34, 35, 36]` —— 8 码套排（刻意跳过 32，版师要求），仅作 `load_nest_pieces` 默认兜底，**不是现行排料口径**。

> **码号口径（US-001 v2 起）**：工作台上传母版经 `/api/commit-to-nesting`（US-010）取**母版实际全码**（M1787 = 11 码 [28-38]）→ **110 NestPiece**（每码 10 片 × 11 码；= 母版 size≠None 轮廓数，无镜像合成）。前端 SizePicker（US-017）从上传 doc 动态读码号，demand（US-022）按码可设 0 跳过、按（g 码 × 码号）可设 N 份。

### 门幅（单一口径，2026-08-28 版师定案）

| 常量 | 值 | 口径 |
|------|-----|------|
| `GATE_MM` | 1980 | 缺省门幅。**输入幅宽 = 实际幅宽**：UI viewBox / PNG·DXF·PLT 外框 / WS manifest `gate_mm` / **求解约束带**（spyrrow strip 高度）/**密度分母** 全部同一门幅，不减布边 |

单一事实源在 `nesting_bounds/load_pieces.py`，换布幅改输入值即可。幅宽受限的设备（无法处理 1980）由用户直接输入更小门幅。

> **历史口径迁移记录**：2026-08 撞机后曾引入 `PLOT_SAFE_MAX_Y_MM=1910`（绘图仪 Y 可写幅宽）+ `NEST_GATE_MM=min(两者)`（求解钳制 + 密度分母），70mm 内部差求解不排、PLT 再按 y≤1910 二道裁剪；2026-08-28 版师定案撞机系当时那台机器无法处理 1980 幅宽（机器问题非口径问题），70mm 钳制链（含 PLT 二道防线与前端红虚线）整体移除。同布局密度较钳制期 −~3.5pp（分母 1910→1980），跨口径历史数字不可直接对比。

### 利用率（双口径，关键）

| 口径 | 公式 | 用途 |
|------|------|------|
| **real（原面积·实际幅宽）** | `total_area / (width × gate_mm)` | ★ 90% 生死线判定；导出为 `density`；版师口径。2026-08-28 起输入幅宽 = 实际幅宽单一口径（分母/求解带/导出同门幅；2026-08-20~27 曾为 min(gate_mm,1910) 分母，同布局口径切换 −~3.5pp，跨口径历史数字不可直接对比） |
| sparrow（erode 后） | spyrrow 自报 | 仅参考，偏低（erode 缩小了分子） |

**任何对版师的汇报、前端显示、目标判定都用 real 口径。**

## 数据流主线

```
用户上传母版 DXF
   ↓ /api/parse-dxf + /api/commit-to-nesting（US-004/010）
out/uploads/<doc_id>_pieces/{g码}_{码号}.dxf + pieces_manifest.json sidecar（母版全码，每片 5 层 US-024）
   ↓ load_nest_pieces（manifest 驱动：布纹对齐水平 + 归一化原点 + 5 层共享 transform，无镜像展开）
NestPiece（母版全码 110 = 母版 size≠None 轮廓数，WYSIWYG）
   ↓ server._commit_to_nesting_sync（labeling.assign_codes 最先赋 g 码，名称无关、零丢片零合成）
out/sparrow_baseline/pieces_intermediate.json   ← 全流程事实源（schema v2：每片 polygon + 5 层 + label，无 ptype/side）
   ↓
   ├─ ms-sparrow-baseline / ms-sparrow-exp（sparrow 求解 → result/svg/curve）
   └─ ms-web（启动期 _PIECES_STATE 读取 + commit 后 reload + 实时可视化 5 层 + 导出 PNG/R12-DXF/PLT 5 层）
```

> **CLI 平行通道**（2026-08-19）：`ms-run-config <config.json>` 从 `data/configs/` 9 键配置出发，走同一编排链独立 commit 到 `out/config_runs/<run>_<时间戳>/` 再串行多 seed 求解 —— **不经上述 web 事实源**（不写 `out/sparrow_baseline/` 与 `out/uploads/`），可与 ms-web 并行互不干扰。

详细函数链见 [technical/agent-file-map.md](../technical/agent-file-map.md#数据流主线)。

## 后端架构

五层单向依赖（`cli → web → nesting_engine → nesting_bounds → dxf_parser`），下层禁 import 上层：

- **cli**：最上层编排者（2026-08-19 新增）。`config`（9 键 JSON 严格校验，中文报错含字段名；2026-08-22 起第 8 键 `band` 腰头成带、2026-08-25 起第 9 键 `prefix` 起始端成套前后幅——均与 `--strategy` 策略模式兼容，on 时 `--lns` 自动跳过）、`pipeline`（commit 管线镜像 `server._commit_to_nesting_sync` + `solve_pieces` 求解封装：复用 `web.solver.build_instance` 与 web 同代码路径；PC-001 起多进程求解 + 逐帧 `should_stop` 中止 + curve/best_frame 落盘）、`portfolio`（PC-002 串行 seed 控制器：incumbent banking + R0 达标即停 + R4 队列耗尽）、`run_config`（`ms-run-config` 入口：逐 seeds 经控制器串行多轮 + best/portfolio 汇总，result.json 逐轮重写，`--target`/`--params` 旗标）；绝不 import `web.server`，产物只落 `out/config_runs/`。
- **dxf_parser**：底层 DXF 读写。`reader`（ezdxf recover + GBK + R12 POLYLINE）、`geometry`（纯几何）、`model`（PieceOutline，US-002 扩 5 层字段）、`explore`（母版探索）、`collect`（US-003 母版深度解析 5 层 IR）、`export_dxf`（单裁片 5 层导出）。仅 stdlib + ezdxf。
- **nesting_bounds**：`load_pieces` 把单裁片 → 布纹对齐 → 归一化（US-001 v2 起 manifest 驱动、无 L/R 镜像展开）；US-024 起 `_read_piece` 读 5 层 + notch 法线按 outline 最近边重算。定义 `NestPiece`、`GATE_MM=1980`、`DEFAULT_SIZES`。
- **nesting_engine**：sparrow 求解。`constraints`（v0.3 常量 + 位图腐蚀 + 校验）、`sparrow_baseline`（基线 + ★共享层）、`sparrow_experiments`（公差实验）、`labeling`（**g 码赋号单一真相源**，US-001 v2：assign_codes + 母版编号复用，无名称映射）、`waist_band`（US-009 腰头成带 v2 构造性链构造；2026-08-22 简化后 `fill<45%` 唯一守门人，禁 import web）、`prefix`（US-001 起始端成套前后幅核心构造：eligible_sizes/pick_prefix_size/build_prefix_plan → `PS_*` 组合片，BandChunk 同构直接喂 expand_placements；US-002 段置换钉位 permute_pin/reinsert_evicted/pin_prefix_layout 含 validate 复检回滚；禁 import web/cli）。intermediate 由 `web/server._commit_to_nesting_sync` 生成（US-001 v2 label 先行 / US-024 5 层，schema v2）。
- **web**：`server`（FastAPI + WS + 启动期 `_PIECES_STATE` reload + parse/commit/ptypes 路由 + WS stop 协议）、`solver`（build_instance + demand + 旧 threading / **US-025 多进程** `solve_with_callback_proc`）、`solve_worker`（US-025 子进程入口）、`export`（PNG + R12-DXF marker，US-024 起 5 层叠加）。

文件级细节见 [technical/agent-file-map.md](../technical/agent-file-map.md)；HTTP/WS 契约见 [technical/agent-api-reference.md](../technical/agent-api-reference.md)。

## 工作台交互（用户视角）

双 Tab：**上传预览**（默认入口）+ **超排**（未上传母版时锁定，US-015/016）。

1. **上传母版**（上传预览 Tab）：拖拽/点击上传 `.dxf` → `/api/parse-dxf` 深度解析 → 按码分组 + **g 码标注**（g01+，`labeling.py` 单一真相源，无中文名）+ 5 层（毛版/净版/内部线/刺口/布纹线）数据（US-004~008；裁片编号化 US-001~005）。
2. **编辑数量**（US-011/022；矩阵化重构 + 裁片编号化后 =「码号 × g 码」数量矩阵；图形预览区已拆除）：QtyMatrix 行 = 码号、列 = g 码（列头缩略图 + 序号徽章 + 「≡」整列设值），全部码数量分布一屏看全；格内直接编辑每（g 码 × 码号）排料份数（0 = 该码不排此片）、「≡」整列设统一值（个别码不同 = 应用后单格再改，高亮为特例）；点列头缩略图放大查看裁片图形（US-013 PieceZoomModal，5 层）、点行头（码号）切换列头缩略图显示的码；每码小计/底部合计/总片数 = **Σ 数量口径**（一份 = 母版一个轮廓，引擎不合成镜像）；数量随求解 start payload 按（g 码 × 码号）下发（demand per-size）。
3. **自动应用**（US-021）：解析成功后台自动 `/api/commit-to-nesting` 把母版转 intermediate（母版全码 110 片，无合成）+ reload 后端 + 解锁超排 Tab（不强制切，用户主动点入）。
4. **求解配置**（超排 Tab）：SizePicker 从上传 doc 动态读码号（US-017）+ 总裁片数量实时显示（Σ 数量口径）；高级配置弹窗（重合/旋转，US-018；按 g 码逐片 d/tol —— 2026-08-18 回退 US-004 码号矩阵化；**g 码缩略图 2026-08-25 起会话级缓存**——只在重传母版 commit 后失效，开关弹窗零请求零闪烁）+ g 码缩略图/放大预览 + **布局设置**（开启腰头成带勾选 + 腰头 g 码下拉 + **成带形态预览缩略**（2026-08-24：求解前即可见链内贴触/码序降序/开口朝左/最大码在最右，构造失败前置到选码时刻，点击放大）；2026-08-22 简化后极简两键，预演/ack/填料已删；US-004 起「起始端成套前后幅」分区：勾选 + 前/后幅下拉，默认预选面积最大两片 + **4 片组合形态预览缩略**（2026-08-25：同码 interleave 竖排 = 求解时 PS_ 组合片精确形态，前/后幅成员 g 码标注，点击放大；2026-09-02 起 4（兜底）或 5（顶部异码补片）片自动渲染，放大层 hint 有补片时追加「＋ 顶部 g@B 异码片 · 余 Xmm 近满幅」）；两项均可进「高级运行」——prefix 互斥 2026-08-25 解除）；时长输入（**2026-08-22 起 seed/多 seed 控件隐藏**，界面单 seed 模式，多种子探索由「高级运行」承接）。
5. **求解**（US-025~028）：点"开始求解"→ WS 推 manifest（5 层骨架）→ 持续推 frame（每 ~0.2s，利用率实时爬升）→ final。**可随时"停止"**（后端 terminate 子进程 → `{type:'stopped'}`）→ stopped 态保留中间方案可导出 → "重新开始"用上次参数一键重跑。phase 五态：idle/running/stopped/done/error。
6. **多 seed 并发对比**（最多 6 路），自动保留最优 run（**2026-08-22 起 UI 隐藏**：界面单 seed，底层多 run 能力保留；多种子探索走「高级运行」race/SE 策略编排，后端给定总预算拿更高利用率；2026-08-30 起另有「极限运行」独立按钮 = race 门杀 × 实验结论参数，同预算右尾最优，与高级运行互斥单飞）。
7. **回放**：seekbar 拖动看任意时间点布局（US-006）。
8. **导出最优 run** → PNG（预览）/ R12-DXF（给 ET2008 刻绘，5 层叠加 US-024）/ PLT（US-033，给 WT V8.8 / LIKE 绘图仪，封装口径对齐生产 PLT：PS 纸长 + PW0.08 + PU;PG 收尾 + CRLF；门幅框/内容按输入 gate_mm 裁剪（2026-08-28 起单一幅宽口径）+ PD 分块 ≤10点/≤110B + 走纸引导），文件名 = 上传母版名前缀 + 码号 + 利用率 + 种子（多款号导出凭前缀区分）。

## 关键技术决策

- **DXF 导出走 R12 + POLYLINE**（非 LWPOLYLINE）：ET2008 读 LWPOLYLINE 轮廓会消失。
- **sparrow 不改源码**：作为 pip 包（`spyrrow`）引用，v0.3 服装约束（重合/旋转/布纹线）在外层 `constraints.py` + `solver.build_instance` 包装实现。
- **坐标系**：spyrrow X=用布长度(0..width)，Y=门幅(0..gate)，Y 向上；前端 SVG `scale(1,-1)` 翻转后与 PNG / R12-DXF 一致。
- **多 seed 并发公平性**：`ThreadPoolExecutor(max_workers=6)` 跑 `run_solve`，每 seed 独立子进程（US-025 进程化），seed 间同等 CPU 竞争 → 排名公平。WS stop / 客户端断开 → `Process.terminate()` 可靠终止 Rust 原生 solve（US-026）。
- **前端 React 18 + TS 5 + Vite 5**：Zustand 状态 + 命令式 SVG 渲染（逃逸 React reconciliation 处理高频帧）。不引入 CSS 框架。坐标系 `scale(1,-1)` 必须保留。

## 验收标准（90% 目标的硬指标）

- ✅ `real_density = total_area/(width×gate_mm)` 达到 90%（实际幅宽口径，非 sparrow 自报密度；2026-08-28 起输入幅宽 = 实际幅宽单一口径 —— 2026-08-20~27 曾为 min(gate_mm,1910) 分母，同布局口径切换 −~3.5pp，跨口径历史数字不可直接对比）。
- ✅ commit-to-nesting 生成的 intermediate 含母版全码 NestPiece（M1787 = 110 片 = 母版 size≠None 轮廓数，无镜像合成；每片 label = g 码）。
- ✅ 基线对拍（US-005）：同 seed（0）重跑 110 片基线 density 一致；新基线 **real 85.59%** 记录在案（旧 176 片/85.79% 基线随镜像概念归档，不再对拍）。
- ✅ 导出 DXF 可被 ET2008 正确读出轮廓（R12 + POLYLINE）。
- ✅ 分层依赖未反向（`web→engine→bounds→parser`）。
- ✅ Python 模块可通过 `python -m materialsorting.<sub>.<module>` 跑通。

## 相关文档

- 权威约束：[排料规则_详细版.md](排料规则_详细版.md)
- 后端文件地图：[technical/agent-file-map.md](../technical/agent-file-map.md)
- 前端组件地图：[technical/agent-component-map.md](../technical/agent-component-map.md)
- API/WS 契约：[technical/agent-api-reference.md](../technical/agent-api-reference.md)
- 各阶段规划/方案/反馈：见本目录其余文档

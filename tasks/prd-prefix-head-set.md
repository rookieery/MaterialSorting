# PRD: 起始端成套前后幅（建议1 · prefix 前缀机制 v2）

> 依据：[.docs/business/起始端成套前后幅_版师确认清单.md](../.docs/business/起始端成套前后幅_版师确认清单.md)（v3 2026-08-25：版师 P1~P5 答复入档 + P0 探针五步全部完成）。姊妹先例：[prd-waist-band.md](prd-waist-band.md)（建议2 腰头成带，已落地——本 PRD 大量复用其组合片机制与编排模式）。
>
> **P0 探针实测（5336 真实数据，探针脚本 `out/tmp_probe/`）**：资格码 {32,33,34,35,38}；组合片 interleave 1155×1458 / fill 83.3% / 贴触 0.00mm / 0 封闭腔；三臂 A/B 4-seed 均值代价 **−0.14pt ≈ 0**（OFF 86.92% vs FREE 86.78%，PIN≡FREE 且 4/4 置换跳过——组合片自然锚定布头 comp_min_x 0.0~0.2mm）；band×prefix 双开 **89.33% / 90.05%**（全实验最高值）。
>
> **v2 2026-08-25：五项开放问题全部决策入档（见「已决策」节）**——① 交错顺序 interleave 定稿；② 资格码自动 seeded 随机选取、不出 UI；③ 组合片 orientations 放开 [0.,180.]；④ 双开不置换、只记录带位（原独立带尾置换 Story 降级合并进 US-003，Story 6→5）；⑤ 前后幅默认预选面积最大两片、用户可改。

## 概述 (Overview)

把版师「排料第一列（布头端）要有一套尺码完整的前幅+后幅（2+2 共 4 片）」的经验固化为可开关的求解编排：用户指认前/后幅 g 码后，系统在用户所排尺码中自动选取一个满足 2+2 资格的码（seeded 随机，不出 UI），4 片按版师形态构造性竖排贴靠成 `PS_*` 组合片，作为普通自由 Item 进主求解（前缀空隙与外部空隙由求解器 NFP 邻接**跨界共同填充**——版师 P3 答复的字面实现），解后在组合片未锚定布头时用纯几何段置换钉到 x=0（常态零触发）。**性质是业务规则（布头成套形态保证），不是利用率优化器**——验收线是 min_x=0 形态保证 + 密度不显著劣化（A/B ≤1.0pt），P0 实测为 ≈0 代价。

## 目标 (Goals)

- 用户只需指认前/后幅 g 码（默认预选面积最大两片，可改），资格码自动 seeded 随机选取（2+2 规则：该码前、后 demand 均 ==2；总量 2 或 6 片的码不合格——版师 P2 原话），布头第一列形态构造性保证（同码竖排贴触 + 头尾 180° 交替——版师 P1 参照图，interleave 交错序定稿），不依赖求解器自发涌现。
- 前缀空隙与外部空隙**跨界共同填充**（P3）：填充片可同时占前缀凹口与外部空间，密度代价 ≤1.0pt（P0 实测 −0.14pt）。
- 组合片 pid（`PS_*`）全链路（manifest/frame/final/前端/导出）零泄漏，下游渲染导出零改动（band US-011 同纪律）。
- prefix 关闭路径与主干 HEAD 行为一致（既有测试零回归）；prefix 开启同 seed 确定性重放（含资格码选取）。
- 双开（band+prefix）兼容：带位**只记录不置换**（2026-08-25 拍板），A/B 不劣化（P0 双开自由解 89.33%/90.05% 为历史最高，双开本身是密度增益组合）。

## 用户故事 (User Stories)

### US-001: prefix 核心构造模块（资格码 + PS 组合片 + 展开契约）
- **Description**: As a developer, I want `materialSorting-server/src/materialsorting/nesting_engine/prefix.py`（`eligible_sizes` / `pick_prefix_size` / `build_prefix_plan` / 常量；探针 `out/tmp_probe/prefix_lib.py` 移植收敛）so that 组合片构造有单一真相源，web 与未来 CLI 共用。机制：4 片（前×2 + 后×2 同码）按版师形态构造性竖排——相邻片头尾相对 180° 交替（排料规则 §3.1 姿态模型）、`_slide_touch` Y 轴向贴触（粗扫+二分，无 RNG）、interleave 交错序（前后前后，定稿）→ 原始轮廓 union → `erode(d_g)`（d_g = max(d_front, d_back) 保守）→ `_clean_polygon` → 归一化到原点；BandChunk 同构（直接喂 `waist_band.expand_placements`，offset 减号权威式复用）。
- **Acceptance Criteria**:
  1. `eligible_sizes(quantities, front_label, back_label)`：P2 资格规则逐码校验（两码 demand 均 ==2），5336 g02/g03 → {32,33,34,35,38}（31=1+1、36=3+3 不合格）；单测覆盖 0/1/2/3/缺码五态
  2. `pick_prefix_size(eligible, *, seed, front, back)`：资格码集合中 seeded 随机取一（`zlib.crc32(f'{seed}|{front}|{back}')` 派生 `random.Random`，**勿用全局 random/hash()**）；同 seed 两跑同码、空集合抛 `PrefixError`；单测锁确定性
  3. `build_prefix_plan(pid_meta, pieces_by_id, *, front_pid, back_pid, d_g, gate_nest, order='interleave')`：5336 size34 对拍 P0 直测数字（bbox 1155×1458、fill 83.3%、成员贴触缝隙全 ≤1mm、封闭腔 0）；rot180 负坐标框架正确（每成员先归一原点再做候选+滑触，记账 tr=(xoff−b0, yoff−b1) 补偿——P0 踩过的坑锁进单测）
  4. 守卫：竖排高 > min(gate_nest, 1910) 抛 `PrefixError`（不静默截断）；order 非法值抛 ValueError；2+2 副本不齐抛 `PrefixError`
  5. 展开契约：组合片 **rot=0 与 rot=180 两组**黄金用例（180° = 整列头尾调换，orientations 放开 [0.,180.] 后必须覆盖）手算对拍（复用 `expand_placements`）；包络断言 union(成员原轮廓@展开位) ⊆ composite@主解位 ⊕ d_g（容差 0.5mm）；展开后恰 4 条成员 placement
  6. 确定性：构造无 RNG，同输入两跑 `to_dict()` JSON 相等；`tests/test_prefix.py` 全绿 + AST 守卫禁 import web（镜像 `test_waist_band.py` 套路）；模块仅依赖 stdlib + shapely + 兄弟引擎模块
- **Priority**: 1

### US-002: 段置换钉位 + 驱逐重插模块（P5 严格顶零位的守卫路径）
- **Description**: As a developer, I want `nesting_engine/prefix.py` 增补 `permute_pin` / `reinsert_evicted`（探针同名函数移植）so that 组合片未自然锚定布头时（P0 实测 4/4 锚定，本模块是零成本兜底）仍能构造性达成 min_x=0。机制（确认清单 §3.3/3.4）：割线 c1=a 硬性 + c2∈[b, b+flex] 柔性选线（最小化 straddler 数）→ A/C/B 三组刚体重排（组间 x 区间不相交 ⇒ 无新重叠、总长不增）→ straddler 驱逐重插（①随组平移 +x 微调梯回原窝 ②`_slide_touch` 自由空间滑触 ③尾端贴触追加兜底）→ `constraints.validate` + y≤1910 全版复检，失败回退置换前布局（LNS 纪律）。
- **Acceptance Criteria**:
  1. `permute_pin` 三守卫参数锁进单测：`skip_at_head=6.0`（组合片已在头部整体跳过——P0 灾难 −17.72pt 的修复）、`eps=5.0`（≥ d 包络 2mm，防贴墙片误判 straddler）、`flex=400.0`；返回 (placements, shift, stats) 且 stats 含 skipped/nA/nC/nB/n_evicted
  2. 构造性用例：人为把组合片放到版面中部（模拟异常解）→ 置换后组合片 min_x ≤ 6mm、全版 validate 通过、总长不增（new_L ≤ L + 0.5mm 容差）
  3. `reinsert_evicted` 三优先序单测：原窝回位（多数零代价）/ 滑触贴插 / 尾端追加（width_growth 计入 stats，超阈值 warn）；确定性（面积降序 tie-break，无 RNG）
  4. P0 回归：probe2 三臂场景 FREE≈PIN（4/4 seed 置换跳过、密度差 =0.00pt）复现为单测或冒烟脚本断言
  5. `python -m materialsorting.nesting_engine.prefix` 冒烟入口跑通（构造+置换演示，5336 数据）；pytest 全绿、分层依赖未反向
- **Priority**: 2

### US-003: web 编排接线（exclude_pids + 展开 + stage + WS 校验 + 双开带位记录）
- **Description**: As a user, I want `web/solver.py` 的 `build_instance` 加 `exclude_pids` 参数（**pid 级**扣减 {front_size, back_size}——band 的 `exclude_labels` 是 label 级，prefix 只用该码 2+2 份、同码其他码照排，故必须 pid 级；同样禁 quantities=0 方式）、`web/solve_worker.py` 加 `prefix` 参数（`_build_prefix` 进程内同步构造：`eligible_sizes` → `pick_prefix_size` seeded 随机选码 → `build_prefix_plan`；失败只投 error 不投 manifest——band 同契约）+ `_emit_placed` 展开单点扩展（PS_ 与 WB_ 同一序列化器）+ final 后置换挂钩（FR-6）+ **双开带位记录**（FR-7：prefix on 且 band on 时把 WB 落位 min_x/max_x/距布尾距离写进 prefix_runs 工件与 final stats，**不置换**）+ `web/routes_ws.py` 解析 StartPayload `prefix` 键并服务端校验 + 新增 stage 消息 so that WS solve 全链路支持前缀成套。
- **Acceptance Criteria**:
  1. prefix 缺省/null：`solve_worker` 走原路径，`test_solve_proc.py` / `test_ws_stop.py` / `test_waist_band_ws.py` **零改动通过**；prefix on/off 下 manifest 的 `total_area` 与 pieces 列表逐字段一致（一致性单测，band US-011 #1 同款）
  2. prefix 开启：WS 依序收到 `stage('prefix', {size, fill_pct, bbox, holes, elapsed})`（**size 回显选中资格码**）→ manifest（无 `PS_`）→ frames/final（placed_items 无 `PS_`、4 成员 pid 各 2 条）；band 同开时 stage 两条（band→prefix→manifest），PS_ 与 WB_ 互不干扰
  3. 服务端校验 `_parse_prefix`（`routes_ws` 单一校验点，`_parse_band` 同模式）：front/back 须匹配 `^g\d+$` 且存在于母版且 front≠back；**须存在 ≥1 个资格码**（两码 demand==2 的码），无资格码（含 quantities=null 全 demand=1 场景）= 结构化 error 早退 + 显式 close，文案指路「请在数量矩阵把所选码前后幅配成 2+2」
  4. final 置换挂钩：组合片 min_x > 6mm 时 permute + 驱逐重插 + validate 复检（失败回退），min_x ≤ 6mm 跳过（stats 落 prefix_runs 工件，写失败仅 warn）；帧不置换（FR-6，常态锚定下帧本在头部）
  5. 双开带位记录：prefix on 且 band on 时，WB 世界 bbox（min_x/max_x/距布尾 mm）写进 prefix_runs 工件与 final 统计段，布局不动（FR-7，2026-08-25 拍板不置换）；单开各自行为与无对方时完全一致
  6. prefix on 时 LNS 互斥：`ms-run-config --lns` 遇 prefix 配置 warn 跳过（band 同款双 warn 点）——CLI 预埋，CLI 完整接入在非目标
  7. 新增 `tests/test_prefix_ws.py`（TestClient 套路）全绿；`ms-web` 启动无回归、分层依赖未反向
- **Priority**: 3

### US-004: 前端参数链路 + 高级配置弹窗「布局设置」UI
- **Description**: As a 版师, I want `lib/params.ts`（`FormState.prefix_enabled/prefix_front/prefix_back` + `collectStartContext` prefix 解析 + 资格码存在性检查函数）、`types/ws.ts`（`PrefixConfig` + StageMsg 扩 'prefix'）、`useSolveRun.ts`（prefix 透传 + stage 分支状态行「起始端成套构造中（尺码 {size}）…」）、`PerTypeOverridesModal.tsx`「布局设置」分区新增「起始端成套前后幅」勾选 + 前幅/后幅 g 码下拉（80×80 缩略图 + 徽章复用 band 下拉模式；**默认自动预选 parse doc 面积最大两片**，5336 = g02/g03，用户可改；**无尺码下拉**——资格码由后端 seeded 随机选取，stage 回显）so that 我能安全指认前缀参数。
- **Acceptance Criteria**:
  1. 资格码存在性前端本地预检（qtyStore quantities → 2+2 规则，与后端 `_parse_prefix` 同口径）：无任何资格码时勾选区提示「当前数量无 2+2 资格码」，开始求解仍交后端权威校验拦截；未勾选时两个下拉 disabled（draft+confirm 语义沿用）
  2. `collectStartContext`：关 / 开但前或后未选 → null；开且有效 → `{enabled:true,front,back}`；StartPayload 含 `prefix`；stage('prefix') 状态行回显选中尺码（不进 phase 五态）
  3. 校验：勾选未选前/后幅 → 开始求解置灰 + StatusLine 具体文案；front==back 拦截；prefix 与 band 可同开（双开记录带位是 US-003 行为，前端无额外控件）；与「高级运行」策略入口 v1 互斥（disabled + title 说明，band 先例 FR-6）
  4. `params.test.ts` / `useSolveRun.test.tsx` / `PerTypeOverridesModal.test.tsx` / `ControlPanel.test.tsx` 扩展全绿；`npm run build`（tsc --noEmit && vite build）通过；**通过浏览器验证**：弹窗暗色主题一致、勾选→下拉→确认→stage 提示→final 头部第一列 4 片形态目检（同码、竖排贴触、头尾交替）
- **Priority**: 4

### US-005: A/B 验收与形态判据闭环
- **Description**: As a 项目负责人, I want 5336 同源同构 on/off 4-seed 终验 + 形态判据 + 导出验证 + 文档更新 so that 前缀功能以可证方式达到验收线后合入。
- **Acceptance Criteria**:
  1. 形态：4 成员同码（前 2 后 2）且 min_x(前缀) ≤ 6mm（4/4 seed）；竖排贴触（相邻 y 区间交集 >0、缝隙 ≤1mm）；头尾 180° 交替（相邻成员 rot 差 ≈180°）
  2. 密度：A/B 同源对照（60s×4 seed，raw-width=生产 real 口径）均值劣化 ≤1.0pt（P0 基准 −0.14pt）；双开档（band+prefix，不置换）另报一列（P0 自由解基准 89.33%/90.05%），带位记录在案
  3. 确定性：同 seed 重跑资格码选取一致 + placed_items/density 序列逐帧相等（非 byte-identity，帧含 wall-clock）；prefix_runs 工件可回放对拍
  4. 导出：PNG/R12-DXF/PLT 三格式成功，后端日志 grep 无「导出跳过：pid」（`PS_` 泄漏哨兵）；prefix 关闭路径产物与 HEAD 行为一致
  5. 文档：CLAUDE.md 数据流主线补 prefix 支线一句 + `.docs/business/` A/B 报告落盘 + 确认清单 v4 回写终值 + business-overview 状态表更新；`pytest` + `npm run build` + `npm test` 全绿
- **Priority**: 5

## 功能需求 (Functional Requirements)

- FR-1: StartPayload 新增可缺省 `prefix: {enabled: bool, front: string, back: string} | null`（**无 size 键**——资格码后端选取），缺省/null/{} = 关闭，旧行为逐字节不变；服务端校验（labels 合法、front≠back、≥1 资格码）。
- FR-2: 新增 server→client 消息 `{'type':'stage','stage':'prefix', size, fill_pct, bbox, holes, elapsed}`，仅 prefix 开启时在 manifest 前发一次（band 同开时 band→prefix→manifest）；旧前端 default:break 静默忽略。
- FR-3: prefix 成员 = 资格码选取后 {(front,size), (back,size)} 两 pid 的全部副本（2+2 恰用尽该码 demand）；主实例 `exclude_pids` **pid 级**扣减（区别于 band 的 label 级——同码其他码照排），pid_meta/total_area/manifest 逐字段不变。
- FR-4: 资格码自动选取：`pick_prefix_size` 在用户所排尺码（quantities demand>0 口径）中满足 2+2 的码集合里 **seeded 随机取一**（`zlib.crc32(f'{seed}|{front}|{back}')` 派生）；空集合 = 结构化 error；不出 UI。
- FR-5: `PS_*` 组合片 orientations=**[0., 180.]**（2026-08-25 版师认可整列头尾调换；构造形态不变，180° 只整列翻转）。
- FR-6: 展开发生在 `solve_worker._emit_placed` 单点（与 WB_ 同一序列化器），`PS_` 永不出现在任何对前端可见数据；`_write_prefix_artifact` 落 `paths.OUT_DIR/prefix_runs/*.json`（写失败仅 warn）。
- FR-7: final 置换守卫：组合片 min_x ≤ `skip_at_head`(6mm) 跳过（P0 实测常态）；否则 permute + 驱逐重插 + validate 复检失败回退。帧不置换（帧保持求解器原样，final 为权威布局）。
- FR-8: **双开（prefix on 且 band on）只记录带位、不置换**（2026-08-25 拍板）：WB 世界 bbox（min_x/max_x/距布尾）写 prefix_runs 工件与 final 统计，布局不动；band 单开无位置约束（band FR-8 口径不变）；带尾置换四割线机制留档确认清单 §3.3，二期如需启用另行立项。
- FR-9: 资格码规则 = front demand==2 且 back demand==2（版师 P2：「总量 2 片或 6 片的码不行」）。
- FR-10: 交错顺序定稿 interleave（前后前后，P0 实测 0 封闭腔 vs grouped 2 个 = spyrrow 死区；版师勾选 SVG 存档 `.docs/business/建议1_P0_前缀34_*.svg` 备查，如未来否决只切默认值）。
- FR-11: prefix on 时 `--lns` warn 跳过（波段重排拆钉位，band 同款）。
- FR-12: 确定性：构造贴触/置换/重插无 RNG（tie-break 面积降序）；资格码选取 seeded 派生（FR-4）；同 seed 重放选码 + placed/density 序列逐帧相等。

## 非目标 (Non-Goals)

- **带尾置换（P4）四割线实现**——2026-08-25 拍板双开只记录带位（FR-8）；机制设计留档确认清单 §3.3，二期如版师反馈带位不可接受再立项。
- CLI（ms-run-config 9 键 schema）prefix 支持、策略运行（/api/strategy/*）prefix 支持、run_stats prefix 字段——均为二期接口备注（band 先例：2026-08-22 补齐，同路径跟进），本期只在 US-003 #6 预埋 LNS 互斥。
- 帧内廉价置换（每帧钉位展示）——常态锚定下不需要，final 权威布局足够；若验收发现帧尾跳变不可接受再补。
- 前后幅 g 码的引擎级自动识别（片型识别已整体退场，g 码即一切）——UI 默认预选（面积最大两片）只是缺省值建议，不是识别功能。
- 资格码手动选取 UI（2026-08-25 拍板不出下拉；如版师后续要求指定码，加回 size 键即可，协议向后兼容）。
- LNS frozen 片概念（PC-007 欠账，prefix 与 band 共同的二期项）。
- 带位约束的求解期硬实现（2026-08-21 实测结构性右置 −2.10pt 已否决；解后置换路径也已拍板暂缓，本期纯记录）。

## 设计考虑 (Design Considerations)

- 弹窗「布局设置」分区在 band 两键之后追加一组：勾选 + 前幅/后幅两下拉（缩略图 + 徽章复用现有模式）；**无尺码控件**——勾选区说明文案「满足 2+2 的尺码将自动选取」；暗色主题、不引入 CSS 框架，样式进现有 `style.css`。
- 无资格码款型（如 quantities=null 全 demand=1）时勾选区提示，不阻塞 band 使用。
- stage('prefix') 秒级提示「起始端成套构造中（尺码 {size}）…」不进 phase 五态状态机（band stage 同款），size 由 stage 消息回显（前端无法预知 seeded 随机结果）。
- 坐标系 `scale(1,-1)` 翻转约定不变；导出三格式对展开后 placements 零改动（成员是普通 pid，PLT「尺码*数量」标注自动覆盖）。

## 技术考虑 (Technical Considerations)

- **为什么组合片自由进解**（可行性核心，确认清单 §2）：spyrrow Item 无固定片/障碍概念 + CLAUDE.md「sparrow 不改源码」⇒ 钉 x=0 不能进求解；P3 跨界填充要求前缀与填充片同次求解自由邻接 ⇒ 组合片路线是唯一解，钉位只能是解后几何变换。band FR-9 同机制已实证（凹口 NFP 回收 +2.27pt）。
- **extra_items 必须构造期传入**：spyrrow `instance.items` 是 Rust 侧副本 list，构造后 append 静默失效（band US-011 实测坑，`build_instance` 已有该参数）。
- **exclude 用 pid 级**：prefix 只消耗该码 2+2 份；`exclude_labels` 会把整码前后幅全排除（5336 其他码 10+ 份全丢，密度崩）。两参数并存：band 用 labels、prefix 用 pids，互不干扰。
- **seeded 随机的确定性口径**：资格码选取用 `zlib.crc32(f'{seed}|{front}|{back}')` 派生 `random.Random`（band seed 同套路），勿用全局 `random`/`hash()`；多 seed portfolio 下各 seed 独立选码属正确语义（同 band 各 seed 独立成带）。
- **quantities=null 边界**：缺省全片 demand=1 ⇒ 无任何 2+2 资格码 ⇒ `_parse_prefix` 结构化 error（文案指路数量矩阵），不是静默关闭。
- **d_g = max(d_front, d_back)**：前后幅 per_type d 可能不同（5336 均为 2），union 后单次 erode 取 max 保证重叠公差最严格片不超限。
- **rot180 负坐标框架坑**（P0 踩过）：成员关于原点旋转后落负坐标区，必须先归一到原点再做候选对齐 + 滑触，记账平移补偿 tr=(xoff−b0, yoff−b1)；单测锁死。
- **置换三守卫缺一不可**（P0 灾难 −17.72pt 三因）：skip_at_head=6.0（常态锚定零触发）、eps=5.0 ≥ d 包络（防贴墙片误判）、c2 柔性选线（最小化驱逐）。
- **展开权威式复用**：`rot_f = m.rot + c.rot`；`tr_f = R(c.rot)·(m.tr − offset) + c.tr`（offset 减号）——band 黄金单测同式；组合片 rot∈{0,180} 两态都要有黄金用例。
- **性能**：构造毫秒级（无子求解）；置换仅异常解触发（几何 O(n)）；帧零额外开销。

## 成功指标 (Success Metrics)

- [ ] A/B 同源对照（5336、60s、seed 0/1/2/3）：prefix on 均值劣化 ≤1.0pt（P0 基准 −0.14pt ≈ 0）
- [ ] 形态：4/4 seed 前缀 min_x ≤ 6mm、4 片同码竖排贴触缝隙 ≤1mm、头尾 180° 交替（截图在案）
- [ ] 双开档（band+prefix，不置换）：密度与 P0 自由解基准（89.33%/90.05%）同量级不劣化，带位记录在案
- [ ] `PS_` 全链路零泄漏（manifest/frame/final/前端/导出日志五处验证）
- [ ] 同 seed 重放：资格码选取一致 + placed_items/density 序列逐帧相等
- [ ] prefix 关闭路径：既有 pytest + 前端 vitest 全绿，产物与 HEAD 行为一致

## 已决策（2026-08-25 用户确认，原 Open Questions 清零）

1. **交错顺序 = interleave 定稿**（前后前后；P0 实测 0 封闭腔优。版师勾选 SVG 存档备查，如未来否决切 grouped 只改默认值一行）。
2. **资格码自动 seeded 随机选取、不出 UI**（在用户所排尺码中满足 2+2 的码里随机取一；FR-4 确定性口径）。
3. **组合片 180° 放开 [0.,180.]**（版师认可整列头尾调换；FR-5）。
4. **双开不置换、只记录带位**（FR-8；原独立带尾置换 Story 撤销，机制设计留档二期）。
5. **前后幅默认预选面积最大两片、用户可改**（heuristic 不升级，dropdown 兜底）。

# PRD: prefix 套装成员序优化（同型成对堆叠，参考生产件互锁形态）

> 依据：2026-09-03 用户需求 + 分析会话实测（探针 `out/tmp_probe/prefix_swap_probe.py` / `prefix_swap_deep.py`，复用生产放置管线 monkeypatch 只读探针，可复跑）+ 用户生产参考件截图（同片型 180° 头尾互锁、刀缝级贴合）。姊妹先例：[prd-prefix-head-set.md](prd-prefix-head-set.md)（FR-10 interleave 定稿）、[prd-prefix-extra-piece.md](prd-prefix-extra-piece.md)（顶部异码补片，本 PRD 的直接上游）。
>
> **需求核心**：把 prefix 4 片套装「最上面与最下面裁片互换位置、并各逆时针旋转 180°」——即成员序从现行 interleave `[F@0, B@180, F@0, B@180]` 改为 `[B@0, B@180, F@0, F@180]`（自下而上），3 条拼接缝从「全异型（前↔后曲率不匹配 → 开放楔形空隙）」变为「2 同型（同片 180° 自吻合互锁）+ 1 异型」。
>
> **分析已定论（5336 真实数据）**：同组合（@35+g02@38 五片）bbox 浪费 −63,199mm²、fill 81.03%→83.33%；全量选码胜者漂移至 套装@38+g02@36、fill **84.45%（+3.42pt）**、可行组合 54/60→60/60、贴触全 0.00mm；4 片 seeded 路径 83.64%→86.01%。**代价** = 同型深互锁的残余细隙被 closing 焊接封口成封闭腔死区（胜者 3 腔共 47,236mm² ≈ 组合片 2%，折全局 ≈0.27pt 量级，主解永不可填）；开放楔隙 −124,360mm²，其中 ~77k 为真节约。全局净效应需端到端 A/B 定论。

## 概述 (Overview)

把版师生产实践「同片型头尾互锁堆叠」固化为 prefix 套装默认成员序：同型对内部曲率完全吻合（凸弧嵌凹弧），消除现行 interleave 全异型缝的开放楔形空隙。改动收敛在 `nesting_engine/prefix.py` 的 `_member_spec` 成员序 + 两处默认 `order` 值，选码搜索 `select_prefix_plan`、FR-3 补片朝向委派、贴触滑移、置换钉位机制全部零改动自动适应。协议面零变化（9 键 config / WS / 前端零改动），web WS / 策略 / 极限 / CLI 四入口经 solve_worker 单点自动继承。

## 目标 (Goals)

- 套装形态对齐生产参考件：同型对 180° 互锁（后后、前前相邻），组合片 bbox 内浪费实测 −50k~63k mm²，局部 fill +2.3~3.4pt。
- 死区透明化：封闭腔数量/面积如实观测（holes 字段 + 冒烟打印死区面积），不静默；全局净效应以 on/on' A/B ≤1.0pt 门线定生死。
- 确定性不变：成员序是纯静态规则（无 RNG），同输入恒同形态；选码平手裁决序不变。
- 回滚便利：现行 interleave 序保留为备档 order 值（与 grouped 同等待遇），A/B 对照与回退零成本。

## 用户故事 (User Stories)

### US-001: 引擎层成员序切换 + 测试重锁
- **Description**: As a developer, I want `materialSorting-server/src/materialsorting/nesting_engine/prefix.py` 新增 order 值 `'paired'`（成员序 `[B@0, B@180, F@0, F@180]`，rots 仍交替 [0,180,0,180] 头尾相对），`PREFIX_ORDERS` 收录、`build_prefix_plan`（[:452](../materialSorting-server/src/materialsorting/nesting_engine/prefix.py#L452)）与 `select_prefix_plan`（[:621](../materialSorting-server/src/materialsorting/nesting_engine/prefix.py#L621)）的默认 order 从 `'interleave'` 切为 `'paired'`，旧 interleave 保留备档 so that 所有入口（worker/预览/CLI/策略/极限）单点继承新形态，协议与调用方零改动。
- **Acceptance Criteria**:
  1. `_member_spec('paired')` 返回 `[(back,0),(back,180),(front,0),(front,180)]`；非法 order 早抛语义不变；interleave / grouped 备档行为逐字节不变
  2. 既有测试重锁（[tests/test_prefix.py:215-218](../materialSorting-server/tests/test_prefix.py#L215-L218) 成员序断言改 `[back, back, front, front]` + rots 仍 `[0.0, 180.0, 0.0, 180.0]`；[:302-309](../materialSorting-server/tests/test_prefix.py#L302-L309) interleave 封闭腔测试保留 + 新增 paired 序腔数如实断言；[FR-3 回归锁 :1016-1049](../materialSorting-server/tests/test_prefix.py#L1016-L1049) 凸台/凹腔夹具按新成员序**重新手算**锁定；选码胜者断言 [:861-879](../materialSorting-server/tests/test_prefix.py#L861-L879) 按合成夹具新胜者重锁）；`extra_pid=None` 4 片红线在 paired 下重锁（贴触全 ≤1mm、rot180 记账、展开黄金用例）
  3. 5336 冒烟（`python -m materialsorting.nesting_engine.prefix`）：新胜者 = 套装@38 + g02@36（FR-3 内定朝向）、H ≈1956.2 ≤ gate−10、fill ≈84.45%、贴触 0.00、封闭腔 3 个 + 死区面积 ≈47,236mm² 打印在案；4 片 seeded 对拍数字同步更新
  4. 确定性：同输入双跑 `chunk.to_dict()` 全等；`_pin_demo`（PIN≡FREE Δ0.00pt）在新序下复验
  5. pytest 全量绿；`python -m materialsorting.nesting_engine.prefix` 跑通、分层依赖未反向、AST 守卫（禁 import web/cli）不变
- **Priority**: 1

### US-002: 端到端 A/B 验收 + 文档闭环
- **Description**: As a 项目负责人, I want 新旧成员序背靠背 A/B（同会话 stash 对照套路）+ UI 冒烟 + 文档同步 so that 「局部更紧但引入封闭腔死区」的全局净效应以可证方式定案合入。
- **Acceptance Criteria**:
  1. `prefix_accept` 同源短预算 **on/on' A/B**（新代码 prefix=on vs 旧代码 prefix=on，stash 背靠背）：均值劣化 ≤1.0pt PASS；劣化超线 → 备案后备优化方向（`_place_next` 代价加封闭腔惩罚）不盲改
  2. UI 冒烟 `scripts/smoke_prefix_extra.mjs` 29/29（形态判据按新序核对：4 同码 + 顶异码、贴触、近满幅、锚定——判据若涉 F/B 顺序则更新）
  3. 守恒/哨兵复验：placed 条数 = 全量 Σdemand、`PS_` 五处零泄漏（manifest/frame/final/前端/导出）、导出 PLT 无 PS_
  4. 文档五处：CLAUDE.md（prefix 条目成员序描述 + FR-10 沿革注记「2026-09-03 用户依生产件改判 paired」+ 数据流主线）、prefix.py 模块 docstring、`.docs/business/起始端成套前后幅_版师确认清单.md` 追加 §10、README 起始端成套节、memory 更新（成员序沿革 + grouped 等价性发现）；progress.txt 记条
  5. 全量门：后端 pytest 全绿 + 前端 vitest 全绿 + `npm run build` 过（前端零改动即过）
- **Priority**: 2

## 功能需求 (Functional Requirements)

- FR-1: 成员序新默认 `'paired'` = 自下而上 `[后幅@0, 后幅@180, 前幅@0, 前幅@180]`；所有成员仍严格 {0,180} 顺布纹；贴触滑移 / H 守卫（gate−PREFIX_GATE_MARGIN_MM）口径零变化。
- FR-2: `PREFIX_ORDERS` 三值 `('paired', 'grouped', 'interleave')`：paired 为默认；interleave（旧默认）与 grouped（备档）保留可显式请求，行为逐字节不变。
- FR-3: 补片朝向委派机制零改动：顶部异码补片自动改蹬 `前幅@180`（原 `后幅@180`），FR-3 面积增长最小择优自适应（5336 实测新胜者 rot0 嵌入仍胜出）。
- FR-4: 封闭腔如实观测不设闸：`holes` 字段（现行已有）+ 冒烟打印死区面积；不拦截、不改选码平手裁决序（沿用「holes 只报告」口径）。
- FR-5: 协议面零改动：9 键 config / WS StartPayload / 前端 collectPrefix 无新键；run_stats class_key 的 prefix 组件仍 `'front+back'`（成员序不进 class_key，与「选码不进 class_key」口径一致）。
- FR-6: `permute_pin` / `reinsert_evicted` / `_recheck_layout` / `expand_placements` 长度与顺序无关，零改动；`PS_` pid 命名规则不变（成员序不影响 pid）。

## 非目标 (Non-Goals)

- **封闭腔消除优化**（`_place_next` 代价函数加封闭腔惩罚 / 选码 tie-break 纳入 holes）：后备方向，仅当 A/B 劣化超 1.0pt 才立做。
- **web / 前端改动**：预览经 `select_prefix_plan` 单一真相源自动跟随，类型/文案/状态行零改动。
- **组合片主解朝向**（0°/180° 自由度）与 4 片兜底路径的选码语义：均不动（兜底 4 片同样切 paired 序，属 FR-1 范畴而非独立开关）。
- **interleave / grouped 备档删除**：保留（回滚与 A/B 对照零成本）。
- 腰头成带（`waist_band`）成员序：另一构造族，不在本 PRD 范围。

## 设计考虑 (Design Considerations)

- 预览 = 求解形态自动保持（同函数单一真相源）；异码片颜色 `size_color(B)` 口径不变，前端零感知。
- 死区视觉：红块观测仅探针/冒烟层，不进 UI（版师界面维持现状）。
- FR-10 沿革注记必须写进文档：interleave 是 2026-08 版师 P1 形态定稿，本次是用户依生产参考件的**改判**，非静默变更。

## 技术考虑 (Technical Considerations)

- **等价性陷阱**：4 片级 `BBFF ≡ grouped(FFBB)` 整体 180° 翻转（H 1513.0 vs 1513.1，构造路径噪声）；但**带顶部补片时不等价**（补片蹬的成员不同：F@180 vs B@180，实测 fill 83.33% vs 82.86%）——实现必须写显式 BBFF 序，不可复用 grouped 分支。
- **死区机理**：同型对互锁的残余细隙（口径 <2mm）被 `_solid_region` closing 焊接（WELD_RADIUS_MM 起步加倍）封口 → `_exterior_coords` 只取外环 → 腔内空气并入组合片声明占用，主解永不可填。当年 grouped 备档被否的「2 封闭腔」即同一现象，本次以 A/B 门线重新权衡。
- **FR-3 夹具重手算是最大测试工作量**：凸台朝向随成员序变化（interleave 下成员 2/4 转 180°；paired 下同位置是不同片型），凸台/凹腔用例的嵌入 H 数字需重算（可参照探针套路先跑后锁）。
- **选码胜者漂移属预期**：更紧的堆叠让更大码套装可行（54/60→60/60），max-H 判据自动够到 @38；真实数据断言进冒烟、合成夹具断言进单测（合成几何胜者需实测后锁）。
- **性能**：成员序切换不改变搜索空间规模（60 组合 × 每组合一次 `_place_members`），无新增成本。

## 成功指标 (Success Metrics)

- [ ] 5336 冒烟：胜者 套装@38+g02@36、H ≈1956.2 ≤ 1970、fill ≈84.45%、贴触 0.00、死区 3 腔 ≈47,236mm² 打印在案
- [ ] 同输入双跑 `chunk.to_dict()` 全等；PIN≡FREE Δ0.00pt 复验
- [ ] pytest 全量绿（含重锁用例）；前端 vitest/build 零改动即过
- [ ] UI 冒烟 29/29；placed 守恒 = Σdemand；`PS_` 五处零泄漏
- [ ] on/on' 背靠背 A/B 劣化 ≤1.0pt（全局净效应定案门线）
- [ ] 文档五处 + memory + progress.txt 同步

## 已决策（2026-09-03 用户确认，原 Open Questions 清零）

1. **实现形态 = 新增 `'paired'` order 值 + 切默认**（`PREFIX_ORDERS` 三值并存，interleave/grouped 保留备档，回滚与 A/B 对照零成本）。
2. **A/B 劣化超线 → 触发后备优化再一轮**：若 on/on' 劣化 >1.0pt，不备案直接合入，先做 `_place_next` 贴触代价加封闭腔惩罚的优化迭代（形态对齐生产件与全局密度双达标才合入）。
3. **死区观测 = 工件 additive 加字段**：prefix_runs 工件 `info` 加 `dead_area_mm2`（封闭腔死区面积，冒烟同步打印；旧消费方零感知，协议 additive）。
4. **合成夹具胜者断言以实测定数**：单测选码胜者随成员序漂移，实现期先跑后锁（真实数据断言进冒烟、合成夹具断言进单测）。

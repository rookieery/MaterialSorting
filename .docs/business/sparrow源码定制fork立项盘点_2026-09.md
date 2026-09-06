# sparrow 源码定制 fork · 立项盘点

- **日期**：2026-09-06（同日增补 v2：版本基线锚定 + sparrow 0.2.0 增量核查）
- **背景**：镜像姿态分析（`.docs/business/镜像姿态收益实验报告_2026-09.md`）确认"改源码加镜像"技术可行但收益为负。用户提出：既然考虑改源码，不如把项目里所有被 sparrow 源码制约的地方一并盘点，评估一次性 fork 的总账。
- **证据基础**：实读上游三层源码（spyrrow→sparrow→jagua-rs），存档 `out/mirror_experiment/upstream/`（17 个 .rs + 2 个 Cargo.toml）与 `out/mirror_experiment/`（3 份文件树 JSON + 1 份 881cdcbd→main 全量 compare JSON + PyPI 元数据）。sparrow 层源码取自 PaulDL-RS fork main（0.1.0 世代，与我们运行的同代）；0.2.0 增量经 compare patch 逐文件核对。**非推测，全部有源码出处。**

---

## 0. 上游结构与版本基线（盘点的地基）

```
spyrrow 0.9.0 (Python/pyo3 薄封装, PyPI wheel ← 我们当前用的, 2026-03-16 后无新版)
   └── JeroenGar/sparrow @ rev 881cdcbd = sparrow 0.1.0   ← 我们实际运行的求解器
         └── jagua-rs 0.7.0 (crates.io)
上游 main（2026-09-05）：sparrow 0.2.0 + jagua-rs 0.8.1（crates.io 0.8.1 为 2026-09-04 发布）
```

- **上游政策**（sparrow README Development 节原文）：论文忠实实现，只收 bugfix/性能 PR；*"Feel free to fork the repository if you want to ... expand the functionality"*。⇒ **任何功能改动 = 永久自维护 fork，无合流出口**。
- **上游活跃度（v2 修正）**：此前按"论文实现低频迭代"估计，实际 2026-09 一周内连发 jagua-rs 0.8.0/0.8.1 + sparrow 0.2.0 + TUI——活跃度**中等**，rebase 维护成本按中等估；"pin 死版本不追"的策略不变（见 §0.1）。
- **姿态语言**：`DTransformation{rotation,translation}`（proper rigid）贯穿 PlacedItem/SPPlacement/解快照/序列化；`Transformation::decompose()` 用 atan2 提角，**镜像矩阵经它分解会静默丢反射**。
- **需求记账**：`SPProblem.item_demand_qtys: Vec<usize>`，按 Item 记账——组级共享需求池是全新概念。
- **解的外部格式**（`jagua-rs io/ext_repr.rs`）：`ExtPlacedItem{item_id, transformation{rotation_deg, translation}}` —— **与 MS 的 placed 列表（pid/rotation/translation）几乎 1:1**。

### 0.1 sparrow 0.1.0 → 0.2.0 增量内容（881cdcbd → main，21 commits，已逐文件核对）

**① 算法/性能（对我们有实质意义）**
- **#149 碰撞评估提前终止**（2026-09-01）：删除旧 `specialized_jaguars_pipeline.rs`（212 行），新增 `eval/collision_loss.rs`（92 行）有界损失评估器——损失累计超上界即退出，不再遍历全部碰撞边。separator 热路径真优化，同预算下搜索更充分（我们实测 5336 每 seed 200~416s 进入平台期，评估提速直接转化为平台期深度；race/extreme 长跑同样受益）。量级未测，上游有 bench gate 流程把关。
- **jagua-rs 引擎 0.7.0 → 0.8.1**（0.7.1/0.7.2 修复 + 0.8.0/0.8.1，后两者 2026-09-01/04 刚发）。
- 依赖更新（itertools 0.14→0.15 等）。

**② CLI/TUI（与我们无关）**：新增 sparrow 终端仪表盘 TUI（~1300 行）；CLI 重构出 `cli.rs` 并加 `--workers`/`--min-item-separation` 覆盖项。我们经 pyo3 调 lib 层不走 main.rs，拿不到也不需要。

**③ 工程杂务**：Rust 最低版本 1.86→**1.90**、README/资助/CI 清理。

**对盘点结论的影响核查（重要）**：
- 0.2.0 对 optimizer 层的全部改动是 **TUI 进度管道**（`SolutionListener` 新增 `report_phase`/`report_separation_progress`/`report_compression_progress` 默认空实现 + separator/compress 埋点）——**墙钟 terminator、`move_items_multi` 并行聚合结构均未变** ⇒ §2.E 的机制分析与设计在 0.2.0 上成立；§2.B 的 frozen 过滤触点（separator/worker/compress/explore）结构未变，仅 explore.rs 一处 API 适配（`SecondaryMap`→`BasicHazardCollector`，jagua-rs 0.8 接口变更）。
- `optimize(..., initial_solution)` 参数**在我们现行的 881cdcbd 上已存在**（optimizer/mod.rs:29，已抓档核对）⇒ §2.A 的前提双版本成立。
- 附带红利：新 `SeparationProgress{strip_width, density, iteration, min_loss}` / `SeparationResult{evals, moves, iterations}` 进度钩子比 spyrrow 现有 ProgressQueue 信息更丰富，若自建 wheel 可顺手暴露给我们的 WS 进度汇报。
- 确定性提醒：#149 改变碰撞评估路径 ⇒ 0.1.0→0.2.0 帧轨迹必然漂移，确定性基线无论如何要重标（与是否改源码无关）。

---

## 1. 盘点总表

| # | 需求 | 现状外挂机制 | 源码级方案 | 上游已有能力 | 量级 | 优先级 |
|---|---|---|---|---|---|---|
| **0** | **版本基线升级 0.1.0→0.2.0** | 现行 spyrrow 0.9.0 pin 死 881cdcbd | spyrrow rev pin 改 main + `maturin build` 私有 wheel（**一行依赖改动**） | 上游全部现成 | 极小（2–4 天含确定性重标） | **P0 前置** |
| A | 真 se 顺延 + 录入初始布局 | se"延长"=同 seed 重放 180s；无布局录入 | pyo3 暴露 `initial_solution` + MS⇄jagua 格式转换器 | **`optimize(..., initial_solution)` lib 层已实现**（881cdcbd 与 0.2.0 双版本核查） | 小（1–2 周） | **P0** |
| B | 固定裁片/裁片集位置 | prefix 钉位=外部置换 `permute_pin`；编辑后无"保固定重解其余" | 预放置（`place_item` 已有）+ frozen 候选过滤 | place_item/import_solution 已有；候选过滤需新写 | 中（2–3 周） | P1 |
| C | 镜像姿态 | 无（编辑器空格四态人工兜底） | 组变体 + 共享需求池 | 无 | 大（3–6 周） | 缓 |
| D | 智能微调原生化 | `polish.py` 后处理 + erode/物理双口径红字 | warm-start(A) + 未腐蚀 instance 二次只跑 compress | warm-start(A) 即前置；**几乎零 Rust 增量** | 小（1 周, 依赖 A） | P2 |
| E | 跨 run 确定性重放 | num_workers=4 帧漂移，A/B 判据③受累 | iteration-budget terminator 替代墙钟 | Terminator 是 trait，加实现即可 | 小（1 周） | P1 |
| F | panic 优雅化 | `except BaseException` 兜 + `PREFIX_GATE_MARGIN_MM=10` 外部余量 | runaway 检测返回 Result | 无 | 小（几天） | P3 |
| G | band/prefix 刚性组原生化 | `PS_*`/`WB_*` 外部构造 + expand + exclude 双形态 + 置换钉位 | rigid cluster 概念 | 无 | 大 | 缓（纯重构无质量收益） |

---

## 2. 逐项分析

### 0 · 版本基线升级（fork 第 0 步）【P0 前置 · 一行改动，三重价值】

**方案**：fork spyrrow，Cargo.toml 里 `sparrow = { git = ..., rev = "881cdcbd..." }` 改指 main（0.2.0），`maturin build` 出私有 wheel 替换 PyPI 0.9.0。**这是"最小 fork"——不改任何算法代码。**

**三重价值**：
1. **白拿性能**：#149 碰撞评估提前终止 + jagua-rs 0.7→0.8.1 修复，600s/race/extreme 全档受益；
2. **流水线验证前置**：Rust 工具链（≥1.90）、maturin、wheel 安装、确定性重标全部在此步打通——A/E/B 的代码改动落在一条已验证的构建链上，工程风险前移消化；
3. **决策减压**：若升级后全量回归（pytest/vitest/UI 冒烟/prefix_accept 复跑）出问题，止损成本只有几天，fork 决策可随时回退 PyPI 0.9.0。

**成本与风险**：2–4 天（工具链搭建 + 重标确定性基线 + 全量回归）；#149 必然改变帧轨迹（既有确定性口径作废重立）；jagua-rs 0.7→0.8 的 pyo3 接口面经 sparrow 适配后不变，MS 调用链零改动（待回归实证）。

### A · warm-start 家族：真 se 顺延 / 录入初始布局 【P0 · 上游能力已存在】

**本轮最重要的发现**：sparrow lib 的求解入口签名（`sparrow/src/main.rs:111-119`）：

```rust
let solution = optimize(instance, rng, ..., initial_solution.as_ref());  // Option<&SPSolution>
```

且 jagua-rs 有完整的 `probs::spp::io::import_solution(&instance, &ext_solution)` / `export()`。**热启动是 lib 级一等能力，sparrow CLI 的 `-i solution.json` 用的就是它——spyrrow 0.9.0 只是没暴露这个参数。**（该参数在我们现行的 881cdcbd 与 0.2.0 main 均存在，已双版本核查。）

- **改动**：① spyrrow pyo3 加 `instance.solve(config, initial_solution=...)`（透传 Option）；② MS 侧转换器：我们的 placed 列表 ⇄ `ExtSPSolution` JSON（字段 1:1，注意 pid→item_id 映射与 demand 多副本展开——同 pid N 副本 = N 条 ExtPlacedItem）；③ 接线：se 策略"延长"改为灌入冠军解真顺延；编辑器"保存的布局"可作为初始布局入口。
- **直接收益**：
  - se 策略去掉重放浪费（当前延长段 180s 从头跑，前 ~200s 白跑已知结果；真顺延把全部预算花在增量搜索上）；
  - 新能力：版师/排料师录入初始布局（含从历史唛架导入）继续机器优化 = 人机协同工作流；
  - LNS（`cli/lns.py`）波段重排可改用同通道，省掉外部构造子实例的部分脚手架。
- **风险**：低（纯 additive 参数）；RNG 轨迹与现有重放不同 → se 策略确定性基线需重标；warm 起点的 strip_width 语义要接对（ExtSPSolution.strip_width 续跑而非重新收缩）。
- **量级**：Rust 几百行 + Python 转换/接线 ≈ **1–2 周含验证**。

### B · 固定裁片/裁片集位置（frozen items）【P1】

**现状痛点**：prefix"钉位"靠 `permute_pin` 三组刚性置换把组合片换到布头（x 区间不交所以无新重叠，但本质是事后重排 hack）；编辑器改完布局只能整体导出，**没有"我固定这几片、其余重解"**——这是版师真实工作流（手排关键区域 + 机器填其余）的硬缺口。

**源码设计**（纯 sparrow 层，jagua-rs 基本不动；0.2.0 核查：触点结构未变）：
- 预放置：`SPProblem::place_item` 本就支持任意 `SPPlacement`（demand 记账 `register_included_item` 天然扣减）——经 A 的 import 通道灌入即可；
- 冻结：`SeparatorWorker::move_items` 的可移动候选枚举排除 frozen PItemKey；`disrupt_solution`（explore.rs）的 large_items 选择同样过滤；compress 阶段的移动候选同理。
- **收缩保护**：exploration 的 shrink 步骤要加下限 = frozen 片的 x 包络（frozen 片不能被挤窄）。

- **收益**：prefix 钉位从置换 hack 变原生语义；编辑器获得"局部固定 + 重解其余"；band/prefix 外挂机器（G）虽可继续保留但有了替代路径。
- **量级**：候选过滤散布在 separator/worker/compress/explore 四处 + 冻结集合的数据结构 + 收缩保护 ≈ **2–3 周含验证**。

### C · 镜像姿态【缓 · 实测收益 ≈0/负】

详见专门报告与上一轮分析。组变体设计（原形/镜像形为两个 Item + 组级共享 demand 池，sparrow 选择层把候选片升级为"组"双评取优）是正确姿势——几何层/碰撞引擎零改动。在 fork 大盘里与 B 共享部分记账基建，边际成本略降，但 **5336 三口径实测（E2 贴靠零增益/g04 −28%、E3 端到端 −0.32pt）不支持为它付 3–6 周**。维持触发条件：新款式"非对称片占比高且 R180 互扣不佳"的证据出现再启动。

### D · 智能微调原生化（原生 settle/压缩档）【P2 · 依赖 A，几乎零 Rust 增量】

**现状痛点**：`polish.py` 是求解器外的贪心后处理（离散化/去重/左滑压缩），只能修局部不能发现全局更优；编辑画布（erode 轮廓）与 polish 报告（物理毛版）双口径红字差异是文档级约定，长期是认知负担。

**源码设计（关键：被 A 解锁，不需要新引擎改动）**：
- 现在 Python 侧预腐蚀 polygon 喂 `build_instance`（d_g 公差）⇒ 求解结果物理片间隙 ≥ d_a+d_b；
- **原生 polish = 二次求解**：构造**未腐蚀** instance（同一批片、物理轮廓）→ 把一次解的 placement 经 A 通道 warm-start 灌入（此时存在 d_a+d_b 量级的"合法重叠"）→ 只跑 compress 阶段消重叠并压宽度；
- 相比 polish.py：GLS/LBF 全局优化器接管收敛（比逐片贪心移动强），旋转离散集可换更细档，物理口径天然统一（全程一个 instance 一种轮廓）；
- spyrrow 需要补的只有 phase 控制（exploration 时长=0 只跑 compress；CLI 的 `-e/-c` 在 lib config 里有对应字段，pyo3 暴露即可）。

- **量级**：MS 编排 + pyo3 两个小参数 ≈ **1 周（依赖 A 落地）**；polish.py 保留为离线/无 Rust 依赖的降级路径。
- **风险**：二次求解的宽度收益需 A/B 实测（预期与 polish 同源但更强；polish 实测 110 片 0.5s，原生档秒级~分钟级）。

### E · 跨 run 确定性重放【P1 · 工程健康度，性价比最高的小改】

**现状痛点**（prefix 验收实录）：num_workers=4 下主解帧轨迹漂移（判据③ FAIL 先查此桶）、num_workers=1 逐帧全等——确定性边界写进验收文档当已知现象供着。

**本轮源码定位的机制**：`Separator::separate` 主循环 `while !term.kill()`（separator.rs:83）+ 内层迭代上限——**terminator 是墙钟时间驱动**；`move_items_multi` 用 rayon `par_iter_mut` 并行 4 worker 再 `min_by_key` 聚合（separator.rs:146-178）。单线程时调度抖动小近似确定；4 线程时墙钟检查点落点漂移 → 迭代边界不同 → 帧轨迹分叉。**（0.2.0 核查：optimizer 层 diff 均为 TUI 进度管道，terminator 与并行聚合结构未变，本分析在 0.2.0 成立。）**

**源码设计**：Terminator 是 trait（`util/terminator.rs`）——加一个 `IterationBudget` 实现（按 move/iter 计数终止，墙钟只作保险丝）+ config 开关。漂移源若另有出处（如 min_by_key 平手裁决顺序），顺带按 worker index 稳定裁决。
- **收益**：跨 run 逐帧确定性 → A/B 验收判据③常态化、回归测试可逐帧对拍、`run_stats` 聚合口径更干净。
- **量级**：改动小（trait 实现 + 接线），但**需先做漂移源实证**（对拍两种 terminator 的帧轨迹）≈ **1 周**。

### F · panic 优雅化【P3 · 已有缓解，低优先】

现状：`strip-width running away` panic 是 BaseException，MS 已 `except BaseException` 兜住透传真因（2026-09-02 修复），组合片高度用 `PREFIX_GATE_MARGIN_MM=10` 外部留余量防御。源码侧改为 runaway 检测 + Result 错误返回可去掉 magic number 防御层，但现状已不痛。**几天量级，排在顺手做。**

### G · band/prefix 刚性组原生化【缓 · 纯重构】

现状外挂机器：`select_prefix_plan`/`build_prefix_plan` 构造 `PS_*`、`waist_band` 构造 `WB_*`、`expand_placements` 展开、`exclude_pids` 双形态扣减、`permute_pin` 置换钉位——一大套已验收的脚手架。源码级"rigid cluster"（N 片固定相对变换作为单一放置单元）能整体替代之，但**质量不会变**（构造性成带/选码本身在 Python 层，逻辑还是要写），属于架构简化不是能力提升。现有机器工作良好 ⇒ 缓。B 落地后钉位部分先行原生，剩余构造逻辑可长期保留。

---

## 3. 共享基础设施与依赖关系

```
0 (基线升级 0.2.0 + 私有 wheel 流水线)   ← 一切的前置：验证构建链 + 白拿性能
   └── A (warm-start 暴露 + 转换器) ──┬── 真 se 顺延
                                      ├── 录入初始布局（版师人机协同）
                                      ├── D 原生微调（未腐蚀二次求解）
                                      ├── B 的预放置通道（frozen 片灌入）
                                      └── LNS 原生化（可选）
E (确定性 terminator)          独立，但让 0/A/D/B 的验收都变容易
C (镜像组变体)                 与 B 共享组记账基建，独立可缓
F (panic) / G (刚性组)         独立小项/重构项
```

**0+A 是整个 fork 的杠杆链**：第 0 步验证流水线并升级基线，A 在其上用最小改动解锁最多能力。

## 4. 工程总账

| 项 | 内容 |
|---|---|
| 开发量 | 0+A+E 最小闭环 ≈ **3–4 周**；0+A+B+D+E ≈ 6–9 周；全量含 C/G ≈ 3–4 月 |
| 仓库 | fork spyrrow（rev pin 指向我们自己的 sparrow fork 或上游 main）；sparrow 本体仅在 A 之外的项（B/E/F/G）才需要 fork；maturin 构建 wheel |
| 工具链 | Windows Rust **≥1.90**（0.2.0 要求；SIMD 需 nightly）+ maturin + pyo3 0.27；本机直连 GitHub 不通（既有记忆），需走代理/镜像拉取与推送 |
| 维护 | 上游活跃度中等（2026-09 一周内 jagua-rs 0.8.0/0.8.1 + sparrow 0.2.0 + TUI 连发）；策略 = pin 死 rev 长期不动、按需主动升级（0.2.0 无我们必须跟的修复，升级时机自选）；**`不改 sparrow 源码`铁律正式废除，改为`私有 fork 单一真相源`** |
| 验证 | 确定性基线全部重标（基线升级本身即重置帧轨迹口径，§0.1）；全量回归 = pytest 681+ / vitest 1022 / UI 冒烟 / prefix_accept & band A/B 复跑 |

## 5. 决策建议

1. **若立项，第 0 步先做基线升级**（一行 rev pin + maturin，2–4 天）：白拿 #149 与 jagua-rs 0.8.1、打通并验证整条私有 wheel 流水线、全量回归兜底——它把"要不要 fork"的风险决策变成可低成本回退的实验。
2. **值得立项的最小闭环 = 0 + A + E**（约 3–4 周）：上游已实现的 warm-start 暴露 + 确定性 terminator。A/E 不赌任何未证实的算法收益——A 买确定的预算效率（se 重放浪费）+ 新工作流能力（录入布局/人机协同），E 买验收与回归的工程确定性。**即使 C/D/B 后来都不做，这三项也独立回本。**
3. **第二步视 A 落地后的实测再定**：D（原生微调）是 A 的直接红利，1 周量级，用 A/B 实测宽度收益说话；B（frozen）看版师对"局部固定重解"的真实需求强度。
4. **C（镜像）与 G（刚性组重构）维持缓办**，理由见 §2。
5. 若决定只做 A 不想背 fork：向 spyrrow 上游提 PR 暴露 `initial_solution` 参数（纯 API 暴露、不改算法，符合 spyrrow "open to contributions" 口径）——**这是唯一有机会回上游的项，建议先试这条路**；spyrrow 若发新版也会自然带上新 sparrow（但截至 2026-09-06 其 fork 停在 0.1.0/jagua 0.7.0，短期未必跟进）。
6. **若完全不立项，留在 0.9.0 现状没有风险**：0.2.0 中无任何我们必须跟的修复（panic/strip-width runaway 等我们的已知问题不在其中），TUI/CLI 部分与我们无关。

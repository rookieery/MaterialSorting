# spyrrow-ms 侧需求规格：私有 wheel 流水线 + initial_solution 暴露（warm-start 一期）

- **日期**：2026-09-07
- **交付方式**：本文档为 **`D:\code\spyrrow-ms` 项目（待建）的需求规格**，实现工作在该项目进行；本文档在 MaterialSorting 仓库留档作为跨项目契约的单一真相源。MS 侧对接范围见 [tasks/prd-warm-start-phase1.md](../../tasks/prd-warm-start-phase1.md)。
- **背景**：[sparrow源码定制fork立项盘点_2026-09.md](sparrow源码定制fork立项盘点_2026-09.md) §2.A + §2.0。用户定案：基线 rev 锚 **881cdcbd**（与现行 PyPI wheel 算法全等，A 纯 additive；0.2.0 升级另立后续项）；工程布局 = 项目外兄弟仓（`D:\code\spyrrow-ms` fork + `D:\code\sparrow-ms` 镜像 clone），MaterialSorting 仓库只持双源切换助手与 rev 钉板。
- **证据基础**：上游源码存档 `out/mirror_experiment/upstream/`（17 个 .rs + 2 个 Cargo.toml，MaterialSorting 仓库内）。本文引用的事实（F1–F4）全部有存档出处，非推测。

## 0. 目标与红线

**目标**：① 阶段 0a —— 不改任何算法代码，自建 spyrrow 0.9.0 等价私有 wheel（版本 `0.9.0+ms0`），替换 PyPI 版并行为全等验证（整条构建链是后续一切 fork 改动的地基）；② 阶段 A1 —— pyo3 暴露 `instance.solve(config, progress=None, initial_solution=None)`，透传 sparrow lib 层已有的 `optimize(..., initial_solution)` 参数。

**贯穿红线**：`initial_solution=None`（缺省）路径与上游 0.9.0 **逐字节一致** —— 不碰现有分支、不引入任何行为差异；MS 侧回归红线同款（不传即不变）。

## 1. 事实依据（设计输入，实读上游源码钉死）

| # | 事实 | 出处（存档路径） |
|---|---|---|
| F1 | sparrow `optimize` 7 参签名含 `initial_solution: Option<&SPSolution>`；warm 分支 = `SPProblem::restore(init_sol)`，release 构建无 validate（直接信任输入） | `sp_optimizer_mod_881cdcbd.rs:22-45` |
| F2 | **restore 不补放新片**：demand 计数重置后逐 placed 扣减；exploration/compression 只有 move/shrink，无放置调用 ⇒ **初始解必须是完整解**（每 id 条数 == 该 Item demand），否则剩余片永远不会被放上 | `spp_problem.rs:104-115` + `explore_fork.rs` / `sp_compress.rs` 全文 |
| F3 | strip_width 语义 = 续跑：restore 直接采纳灌入宽度，exploration 从该宽度起收缩，不走 LBF 重铺 | `spp_problem.rs:94-102`、`explore_fork.rs:22-28` |
| F4 | jagua `ExtSPSolution{strip_width, layout{container_id, placed_items[{item_id: u64, transformation{rotation: 度, translation: (f32,f32)}}], density}, run_time_sec}`；`import_solution` 调用点 infallible（无 `?`），**其实现源（jagua-rs 0.7.0 `probs/spp/io/import.rs`，2866B）未存档 —— A1.0 首任务补抓核实** | `spp_ext_repr.rs` / `core_ext_repr.rs` / `sp_main.rs:83-85` |
| F5 | spyrrow `Item.id` 是字符串（MS 传 pid），pid → jagua u64 `item_id` 映射在 spyrrow Rust 内部 ⇒ 暴露层用字符串 id，jagua 细节不外漏 | spyrrow `__init__.pyi` + MS `solver.py` 调用形 |
| F6 | 本机网络现实：GitHub 直连超时（ls-remote exit 124）、无本地代理；PyPI 走清华源（spyrrow 每版带 sdist）；crates.io 走 rsproxy 镜像；仅 sparrow 仓库需一次性加速镜像 clone | 实测（2026-09-06/07） |

## 2. 阶段 0a：私有 wheel 构建流水线

### 2.1 工具链（本机全缺，一次性安装）

- **rustup**：经 rsproxy 镜像安装 stable 最新（`RUSTUP_DIST_SERVER=https://rsproxy.cn`、`RUSTUP_UPDATE_ROOT=https://rsproxy.cn/rustup`；sparrow 0.1.0 世代 edition 2024 需 ≥1.85）。
- **VS Build Tools 2022**：C++ workload（link.exe；winget 或官网，数 GB 下载）。
- **maturin**：`pip install maturin`（清华源）。
- **cargo 镜像**：`~/.cargo/config.toml` 配 rsproxy crates.io source replacement（jagua-rs 等依赖走镜像）。

### 2.2 源码获取（GitHub 不通对策，全部一次性）

- **spyrrow 0.9.0**：`pip download spyrrow==0.9.0 --no-binary :all: --no-deps`（清华源有 sdist）→ 解压建 git 仓 `D:\code\spyrrow-ms`，**首 commit = 上游 sdist 原样**（补丁独立 commit —— 未来 rebase 上游 / 提 PR 干净）。
- **sparrow @ 881cdcbd**：加速镜像 clone（如 `https://ghfast.top/https://github.com/JeroenGar/sparrow` 前缀式，备选 gh-proxy.com / 用户代理窗口）→ `D:\code\sparrow-ms`，`git checkout 881cdcbd`。
- **Cargo.toml 改造**：`spyrrow-ms` 的 sparrow 依赖 `git = ...` → `path = "../sparrow-ms"`（**此后构建永不再碰 GitHub**）；jagua-rs 0.7.0 维持 crates.io（rsproxy 镜像拉取）。

### 2.3 构建与版本

- `maturin build --release` → wheel 版本号 `0.9.0+ms0`（PEP 440 local tag，构建脚本注入；MS 侧 `warm_start_supported()` 以 `+ms` 子串判定，见 prd US-001 —— **local tag 命名是跨项目契约，勿改**）。
- 安装到 MS 的 `.venv`：`pip install --force-reinstall <wheel>`（或经 MS 侧 `scripts/spyrrow_wheel.py use-local`）。

### 2.4 验收 gate（0a 出口）

1. **行为全等对拍**：MS 侧同 seed 同短预算 CLI 求解（5336 `--time 30 --seeds 0`），best density 与 PyPI 0.9.0 一致（同 rev 同算法，期望 density 全等；帧级允许既有 num_workers=4 漂移口径）+ 新 wheel 背靠背两次自身逐帧一致。
2. MS 侧全量回归：pytest + vitest 全绿（执行入口与判据归 MS 侧 US-005，本文档只要求 wheel 可用）。
3. **止损点**：工具链装不上 / 构建不过且短期无解 ⇒ 整体不立项，MS 回退 PyPI 0.9.0（成本仅几天工具链时间）—— 此结论同时约束 MS 侧二期规划。

## 3. 阶段 A1：pyo3 暴露 initial_solution

### 3.1 A1.0 前置核实（首个任务，半天）

抓 jagua-rs 0.7.0 源码包（rsproxy `cargo fetch` 后读 registry 缓存，或 crates.io 镜像直接下 .crate）读 `probs/spp/io/import.rs`（2866B），核实：item_id 越界 / demand 不符 / 重叠输入时 `import_solution` 是 panic 还是容忍。结论决定 3.3 校验放几层（pyo3 把 Rust panic 转 `PanicException`（BaseException 系），MS 侧已 `except BaseException` 兜 —— 但 **Python 层校验前置是主防线**，不让脏数据进 Rust）。

### 3.2 接口形态（跨项目契约，MS 侧按此对接）

`solve` 增第三个关键字参数（additive，默认 None）：

```python
instance.solve(config, progress=None, initial_solution: Optional[str] = None)
# initial_solution 为 JSON 字符串：
# {"strip_width": float,                      # mm，restore 续跑起点（F3）
#  "placed_items": [{"id": "<pid>", "rotation": <deg>, "translation": [x, y]}, ...]}
```

- Rust 内部：用 spyrrow 既有 pid → jagua item 映射逐条转 `ExtPlacedItem{item_id: u64, transformation: ExtTransformation{rotation: 度, translation: (f32, f32)}}`，组装 `ExtSPSolution`（`layout.container_id` / `density` / `run_time_sec` 填占位）→ `jagua_rs::probs::spp::io::import_solution` → `optimize(..., Some(&sol))`。
- **字符串 id**（F5）：jagua u64 映射不外漏；MS placed 格式 `{id, rotation(度), translation:[x,y]}` 与 spyrrow `PlacedItem` 1:1。
- 数值：`ExtTransformation` 是 f32；translation mm 级精度 1e-4，f64→f32 收窄安全（MS 侧 <1e-3 判等）。
- **`.pyi` stub 同步**（`solve` 签名 + 文档字符串）—— MS 侧类型检查依赖它。

### 3.3 Rust 侧校验（fail-fast 抛 `ValueError`，不 panic）

- JSON 解析失败 / 未知 id / **每 id 条数 ≠ 该 Item.demand**（F2 完整解硬约束）→ `ValueError` 带明确消息（MS 侧经 error 消息通道透出给用户）。
- `initial_solution=None` 路径与上游 0.9.0 完全一致（不碰现有分支，红线）。

### 3.4 验证

1. Python 直调最小验证（该仓内测试）：2 片小实例求解 → 解转 JSON 灌入再求解 → 断言 (a) 首帧宽度 ≈ 灌入 strip_width（续跑语义，F3）(b) placed 条数守恒 == Σdemand (c) 不传参数行为与 0a 基线一致。
2. 冒烟：MS `.venv` 换新 wheel 后跑 0a.4 同款对拍（MS 侧 US-005 执行）。

## 4. 工程约定

- **仓库边界**：Rust target/ 构建产物（GB 级）只在 `D:\code\spyrrow-ms` / `D:\code\sparrow-ms`；MaterialSorting 仓库只收 wheel 文件安装，不入库任何构建产物。
- **rev 钉板**：MS 侧 `materialSorting-server/spyrrow_build.json` 记 `{spyrrow_ms_commit, sparrow_rev, wheel_version, built_at}` —— spyrrow-ms 每次出新 wheel 后同步该文件（跨项目协作的审计点）。
- **版本递增**：A1 落地后 wheel 版本 `0.9.0+ms1`（local tag 递增，MS 探测逻辑不变）。
- **升级路径（预留不执行）**：0.2.0 升级 = sparrow-ms checkout main + 确定性基线重标（#149 改变帧轨迹），独立后续项。

## 5. 范围外（本规格不含）

- MS 侧全部改动（warmstart 校验模块 / se 接线 / 双源助手）—— 见 [tasks/prd-warm-start-phase1.md](../../tasks/prd-warm-start-phase1.md)。
- 编辑器镜像片（`mirror: true`）支持 —— sparrow 姿态语言是 proper rigid（`DTransformation` 无反射），镜像输入明确拒绝（MS 层校验拦截，Rust 层无需处理）。
- 0.2.0 / jagua-rs 0.8 升级、B frozen、D 原生微调 —— 后续项。

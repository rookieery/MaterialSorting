# spyrrow 私有 wheel 构建与升级手册（MS 侧视角）

- **日期**：2026-09-19（warm-start 一期 US-004 落地）
- **定位**：本仓（MaterialSorting）在「PyPI spyrrow 0.9.0 ↔ spyrrow-ms 私有 wheel（`0.9.0+msN`）」双源之间的**消费与切换手册**。构建工具链 / 源码获取 / 构建命令本体在 spyrrow-ms 侧规格与台账（见 §6），本手册不重复。
- **配套**：跨项目契约 = [sparrow-ms侧需求规格_warm-start暴露_2026-09.md](../business/sparrow-ms侧需求规格_warm-start暴露_2026-09.md)；0a 行为全等对拍归档 = [0a行为全等对拍_spyrrow私有wheel_2026-09.md](0a行为全等对拍_spyrrow私有wheel_2026-09.md)；fork 立项盘点 = [sparrow源码定制fork立项盘点_2026-09.md](../business/sparrow源码定制fork立项盘点_2026-09.md)。
- **切换工具**：`scripts/spyrrow_wheel.py`（仅标准库，无新依赖）。

## 1. 双源是什么、为什么

| 源 | 版本形态 | 语义 |
|----|---------|------|
| PyPI 线上版 | `0.9.0`（无 local tag） | 上游原版，算法锚 = sparrow rev `881cdcbd` |
| spyrrow-ms 私有 wheel | `0.9.0+msN`（PEP 440 local tag） | 本机兄弟仓 `D:/code/spyrrow-ms` 构建：ms0 = 纯重建（行为与 PyPI 逐字节全等，0a 对拍已归档）；ms1 起 = 含 `initial_solution` 暴露（warm 真顺延） |

- **ms0 与 PyPI 0.9.0 行为全等**（三跑 best 五字段 + 帧级语义轨迹逐帧全等）：日常开发生产在 ms0 态零影响；切回 PyPI 仅是「换到同算法的另一份二进制」。
- **warm 能力判定**（`nesting_engine/warmstart.py`）：`+ms<N>` 且 **N ≥ 1** 才 `warm_start_supported() == True`——ms0 是对拍用纯重建 wheel，没有 `initial_solution` 参数，不算支持。当前态 ms0 ⇒ se 延长轮 warm 回退 `unsupported`，属预期。
- **红线**：MaterialSorting 仓库**不入库任何 Rust 构建产物**（wheel 只安装不落 repo；`target/` GB 级产物只存在于 spyrrow-ms / sparrow-ms 兄弟仓）。

## 2. 快速上手（三条命令）

repo 根、用本仓 `.venv` 解释器直跑（**pip 永远走 `sys.executable -m pip`，不假设 PATH**）：

```
python scripts/spyrrow_wheel.py status              # 现场诊断（无子命令时的缺省）
python scripts/spyrrow_wheel.py use-pypi            # 回 PyPI 线上版
python scripts/spyrrow_wheel.py use-local <wheel>   # 装私有 wheel
```

私有 wheel 的位置：`D:/code/spyrrow-ms/target/wheels/spyrrow-0.9.0+msN-cp311-cp311-win_amd64.whl`（maturin 默认产物目录；具体以 spyrrow-ms 侧交付台账为准）。

### status 输出判读（当前态实例）

```
== spyrrow 双源状态 ==
  解释器：D:\code\MaterialSorting\.venv\Scripts\python.exe（pip = sys.executable -m pip）
  已装版本：0.9.0+ms0
  安装源：私有 wheel（local tag +ms0）
  warm_start_supported()：False —— 不支持（se warm 将回退 unsupported，属预期）
  钉板 spyrrow_build.json：
    spyrrow_ms_commit: '1589839…'
    sparrow_rev: '881cdcb…'
    wheel_version: '0.9.0+ms0'
    built_at: '2026-09-07T13:09:13+08:00'
  一致性：已装版本 == 钉板 wheel_version，一致
```

- **解释器行是自证**：脚本被哪个解释器跑就切哪个环境（拿系统 Python 跑会切到系统环境，首行立刻暴露）。
- **一致性行三种态**：一致 / 钉板落后（已装私有 wheel 版本 ≠ 钉板，需按 spyrrow-ms 台账更新四字段）/ 回线上临时态（PyPI 源 + 钉板记录私有谱系，属正常组合）。

### use-local 的防御矩阵（全部 exit 1 + stderr 清晰报错，绝不触碰 pip）

| 输入 | 报错 |
|------|------|
| 路径不存在 | `wheel 路径不存在：<解析后的绝对路径>` + 用法示例 |
| 非 `.whl` 文件 | `不是 wheel 文件（须 .whl）` |
| 文件名非 `spyrrow-` 开头 | `不是 spyrrow 发行版的 wheel`（`--force-reinstall` 装错发行版会破坏 .venv） |

### 安装行为细节

- `use-local` = `pip install --force-reinstall --no-deps <wheel>`：只换 spyrrow 一个发行版，**不连带重装 shapely 等依赖**（依赖由本仓 `.venv` 锁定；`--force-reinstall` 全量重装依赖既慢又可能漂移版本）。
- `use-pypi` = `pip install --force-reinstall spyrrow==0.9.0`（依赖按需从索引解析，本机走清华源）。
- 装后**读回验证**：`importlib.invalidate_caches()` 后再查 `importlib.metadata.version('spyrrow')`（同进程内 pip 改了 site-packages，元数据查找有缓存，不失效会读到旧版本）；读回与 wheel 文件名版本不符会打 `[警告]`。

## 3. rev 钉板（spyrrow_build.json）

`materialSorting-server/spyrrow_build.json` 四字段：

| 字段 | 语义 |
|------|------|
| `spyrrow_ms_commit` | 构建该 wheel 的 spyrrow-ms 仓 commit |
| `sparrow_rev` | 配对 sparrow-ms 仓 rev（算法真相源；现行锚 `881cdcbd`） |
| `wheel_version` | wheel 版本串（`0.9.0+msN`） |
| `built_at` | ISO8601 构建时间 |

- **单一真相源在 spyrrow-ms 侧**：每次出新 wheel 交付 MS 时，由 spyrrow-ms 侧同步写入该文件（规格 §4，跨项目审计点）。MS 侧 `use-local` **只读 + 漂移提示，不自动改写**——`spyrrow_ms_commit`/`sparrow_rev`/`built_at` 三字段 MS 侧无从得知，半自动拼装会造出无法审计的假钉板。
- 装入版本 ≠ 钉板 `wheel_version` 时，`use-local` 会打印 `[提示更新钉板]` 块（含四字段 JSON 模板与新版本号），按 spyrrow-ms 侧交付台账（`D:/code/spyrrow-ms/.docs/technical/0a-exit-gate_2026-09.md`）抄录其余三字段后提交。
- `use-pypi` 回线上是**临时态**：钉板不动（它记录的是私有 wheel 交付谱系），`status` 的一致性行会标注「属正常组合」。

## 4. 什么时候切换（场景）

| 场景 | 动作 |
|------|------|
| 怀疑私有 wheel 引入回归，需要上游对照 | `use-pypi` → 复跑对拍（同 seed 同预算 best density 背靠背比较；判据见 0a 归档 §1）→ `use-local <wheel>` 回私有态 |
| spyrrow-ms 交付新 wheel（ms1、ms2…） | `use-local D:/code/spyrrow-ms/target/wheels/spyrrow-0.9.0+msN-*.whl` → 按提示更新钉板 → 跑本仓回归（pytest 全量 + 涉求解面的 `prefix_accept` 等） |
| 只想看当前装的是哪份 | `status`（或缺省无参直跑） |

- **与 8000 在线后端隔离**：切换只动本仓 `.venv` 的 spyrrow 一个发行版。生产 `ms-web` 若跑在系统 Python 的 PyPI 0.9.0 上，`.venv` 级切换互不影响（0a 对拍即在此隔离下完成）；反之亦然。
- **ms1 交付后的集成验收**（warm 端到端 + se A/B 判据 + 全量回归 + 文档收官）是独立故事（本仓 PRD US-005），不在本手册展开。

## 5. 升 rev 流程（0.2.0，预留不执行）

上游 sparrow 0.1.0 → 0.2.0（#149 碰撞评估提前终止 + jagua-rs 0.7→0.8.1）是**独立后续项**，届时的大致流程（钉点备忘，细节以 spyrrow-ms 侧规格为准）：

1. sparrow-ms 仓 `git checkout main`（0.2.0），spyrrow-ms 侧按其构建流程出新 wheel（local tag 继续递增，如 `0.2.0+ms<N>`）；
2. `use-local` 装入 + 按提示更新钉板（`sparrow_rev` 换新 rev）；
3. **确定性基线重标**：#149 改变帧轨迹，既有 curve/best 跨时代不可直接混比（2026-09-16 帧发射层白名单口径同款注意事项），race 门/kill 判据参数（`controller_params.json`）需重标定；
4. 全量回归（pytest + vitest + UI 冒烟 + `prefix_accept`）+ 对拍判据重立（对照 0.2.0 前后 best density 跨会话漂移口径不可用历史记录）；
5. 若回归不过：`use-pypi` / `use-local` 回 `881cdcbd` 世代 wheel 即回滚（钉板同步回退）。

## 6. Troubleshooting

| 症状 | 处置 |
|------|------|
| `wheel 路径不存在` 但文件明明在 | 检查路径是 `target/wheels/` 而非 `dist/`（maturin 默认产物目录）；相对路径按 **repo 根 CWD** 解析，建议直接给绝对路径 |
| `use-pypi` 拉包超时 | 本机网络现实：GitHub 直连不通、PyPI 走清华源（pip 配置层面的事，本工具不加 `--index-url`，尊重既有 pip 配置；配置见 spyrrow-ms 侧 toolchain 文档 §网络） |
| 装完 `status` 版本没变 | 本工具装后已 `invalidate_caches` 读回；若仍不符，确认跑的是 `.venv` 解释器（status 首行自证），必要时新开终端再查 |
| `warm_start_supported()` 与预期不符 | ms0 = False 属预期（N≥1 才支持）；若装了 ms1+ 仍 False，`status` 看实装版本串是否真带 `+ms1`（pip 可能装了别的源） |
| 钉板读起来怪 / 四字段缺失 | 以 spyrrow-ms 侧 `0a-exit-gate` 台账为准恢复；本工具对钉板损坏只降级提示不炸 |
| 后端 8000 还在跑旧版 | 切换只影响 `.venv`；在线后端需自身重启才换版本（正常，见 §4 隔离说明） |

## 7. 边界与相关文档

- 本手册只写 **MS 侧消费与切换**；工具链安装（rustup / VS Build Tools / maturin / rsproxy 镜像）、源码获取（GitHub 不通对策）、构建命令本体 = spyrrow-ms 侧 `D:/code/spyrrow-ms/.docs/technical/toolchain-setup_2026-09.md`；wheel 交付台账 = 同仓 `0a-exit-gate_2026-09.md`（每次出新 wheel 后更新台账 + MS 侧 `spyrrow_build.json`）。
- 护栏测试：`materialSorting-server/tests/test_spyrrow_wheel.py`（纯桩：命令形态 / 错误矩阵不触 pip / 钉板漂移提示 / pip 退出码透传）。

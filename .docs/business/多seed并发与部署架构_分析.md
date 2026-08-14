# 排料引擎 · 多 seed 并发与部署架构分析

> 时间：2026-08-14
> 输入：对当前代码的一次并发承载能力深挖 + 三种部署形态（单机 / 服务器多租户 / Windows exe）的并发安全性评估
> 定位：**分析推演文档**。除"一、现状"为代码事实外，动态 seed 上限、按 doc_id 隔离、Windows exe 打包等均为**未实现的前瞻性建议**，请勿当作已落地特性引用。
> 关联：[排料引擎技术分析.md](排料引擎技术分析.md) · [排料规则_详细版.md](排料规则_详细版.md)

---

## 一、现状：多 seed 并发求解的承载能力（代码事实）

### 1.1 结论：最多 6 个 seed 真并发

当前架构下，多 seed 并发上限 = **6**，由三处独立、分散的硬编码共同锁死（非单一常量驱动）：

| 层 | 位置 | 机制 |
|---|---|---|
| 前端 UI | `materialSorting-web/src/components/ControlPanel/MultiSeedControls.tsx:42` | `<input type="number" min={2} max={6}>` |
| 前端解析 | `materialSorting-web/src/lib/params.ts:140` | `parseSeedCount = clamp(int ‖ 3, 2, 6)` |
| 后端调度 | `materialSorting-server/src/materialsorting/web/server.py:105` | `_executor = ThreadPoolExecutor(max_workers=6)` |

### 1.2 调度链路（1 个 seed 穿透到底）

```
前端 NestingPage.handleStart
  └─ for i in [0..seed_count): start({seed: base+i})     # fire-and-forget，几乎同时 new N 个 WebSocket
        每条 WS → 后端 /ws/solve
              └─ run_in_executor(_executor, run_solve)    # 抢 6 个 worker 槽位之一
                    └─ solve_with_callback_proc
                          └─ multiprocessing.Process(solve_worker)   # spawn 1 个 OS 子进程
                                └─ build_instance → spyrrow.solve(config{num_workers=4})
```

- **并发单元是子进程，不是线程**。每个 seed = 1 条 WS = 1 个 `multiprocessing.Process`。
- 后端 `_executor`（Python 线程池，6 槽）是异步包装 + 并发闸门，限制「同时存活的 solve 子进程数」。第 7 条 WS 的 `run_solve` 在队列里**排队**。
- 前端 `NestingPage.tsx:129` 在 `for` 循环里同步顺序 `start()`，每次内部 `new WebSocket()`，6 条 WS 几乎同时建立 → 真并发。

### 1.3 资源账（本机实测：24 物理核 + 超线程 = 32 逻辑线程，31.7 GB 内存）

每个子进程内部 spyrrow 配置 `num_workers=4`（`solver.py:166`，Rust 碰撞检测线程，非 Python GIL 线程）。满载 6 seed：

| 项目 | 数量 |
|---|---|
| solve 子进程 | 6 |
| Rust 碰撞检测线程（6 × 4） | **24** |
| 碰撞检测线程占用 / 32 逻辑线程 | **24 / 32 = 75%** |

`6 × 4 = 24 < 32`，逻辑核不超载。`num_workers=4` 在两处写死：`solver.py:166` 与 `sparrow_experiments.py:125`。

### 1.4 公平性设计意图

`server.py:105` 注释点明：

> 多 seed 对比最多 6 个并发求解（seed 间同等 CPU 竞争 → 排名仍公平）

多 seed 对比的核心目的是横向挑密度最优的 seed。只要 6 个同时竞争 CPU、彼此压力均等，密度排名才有意义。一旦 **>6**，第 7 个排队不消耗 CPU，等前面跑完才补位 → 等待者求解环境不对等 → **排名失真**。所以 6 不只是性能上限，更是测量公平性的硬约束。

### 1.5 并列入口对比

| 入口 | 并发模型 | 上限 |
|---|---|---|
| Web 工作台 `/ws/solve` | 真并发 | 6 进程 × 4 线程 |
| CLI `sparrow_experiments.py --seeds 0,1,2,...` | **串行** for 循环（`sparrow_experiments.py:191`） | 1 进程，4 线程，CPU 仅用 12.5% |

---

## 二、提高 seed 数的两个杠杆（分析 · 未实现）

### 2.1 "只渲染一个 seed"几乎无效——渲染不是后端瓶颈

系统里"渲染"与"求解"处在**不同 CPU 域**，必须分开：

| CPU 域 | 内容 | 是否随 seed 数增长 | 受"只渲染一个"影响 |
|---|---|---|---|
| **后端求解** | N 进程 × 4 = 24 个 Rust 线程 | 是（N×4） | ❌ 完全不影响 |
| **后端 I/O** | N 路 frame drain + WS 序列化（每路 0.2s/帧） | 是 | ✅ 若只对冠军开 frame 流可缓解 |
| **前端浏览器** | N 个 NestSVG 卡片 + 全局 10fps rAF 重绘 | 是 | ✅ 直接消除 |

决定 seed 上限的是第一域（求解 CPU），它跟前端渲染几个 seed **毫无关系**。只渲染一个能省的是前端浏览器开销 + 后端 I/O，**触碰不到真正的天花板**。

### 2.2 真正的杠杆：num_workers 动态化

并发约束本质 = **`N × num_workers ≤ 物理核数 × 安全余量`**。当前 `num_workers=4` 写死，所以 `N ≈ 32 / 4 × 0.75 = 6`。要提高 N，正解是动乘积的另一项：

- **降 num_workers**：若每 seed 给 `num_workers=2`，则 32/2×0.75 = 12 个 seed 也只占 24 线程，公平性余量充足。**代价**：单 seed 碰撞检测线程减半，求解变慢。
- **CPU 吞吐近似守恒**：CPU 时间片总量固定，"少 seed × 快求解"与"多 seed × 慢求解"基本等价交换——买的是采样广度，付的是单 seed 深度。

### 2.3 产品形态的隐藏代价

多 seed 对比的核心价值是**实时看 N 条收敛曲线横向对比**。只渲染一个，用户求解中无法判断优劣，除非把形态从"实时多曲线对比"降级为"后台静默跑 N 个、只渲染冠军 / 出排名表"。这是产品形态变更，非纯工程优化。

---

## 三、按 CPU 配置动态设置 seed 上限（分析 · 未实现）

### 3.1 公式

```
N_max = floor(物理核数 × 安全余量 / num_workers)
```

- 当前 `num_workers=4`、余量 0.75 → `floor(32 × 0.75 / 4) = 6`，正好对上硬编码 6。说明这个 6 本质是"32 核 / 4 / 0.75"的具象，换成动态计算顺理成章。
- 服务器 16 核 → 3；64 核 → 12。

### 3.2 四个陷阱（服务器部署致命）

| 陷阱 | 说明 |
|---|---|
| **`os.cpu_count()` 在容器里撒谎** | 返回宿主机核数，无视 cgroup 限额。宿主 64 核、容器 `--cpus=8` → 仍返回 64 → 算出 N=12 → 实际 8 核严重超载。需读 cgroup（v1 `cpu.cfs_quota_us/period`、v2 `cpu.max`） |
| **物理核 vs 逻辑核** | 碰撞检测计算密集，超线程收益约 1.3x 非 2x。分母应取物理核，否则高比例超线程服务器仍轻微超载 |
| **共享服务器邻居噪声** | "64 核"实际可用余量取决于同时刻其他进程。静态公式只能给上限，不是承诺，需更大余量或运行时反压 |
| **spawn vs fork 的内存差异** | Windows 无 fork，每子进程全量 import + deepcopy，内存翻倍；Linux fork 写时复制，N 进程内存开销远低。动态上限若只看 CPU 不看内存，低内存机可能 OOM |

### 3.3 安全下限与落点

```
N_max = clamp( floor(物理核 × 余量 / num_workers),  下限=2,  上限=产品上限 )
```

低配机（4 核）公式算出 0 → clamp 到 2（接受超载换可用性）。架构落点：**后端启动时探测一次真实算力（cgroup + 物理核 + 内存）→ 算出 `max_seeds` → 经 API 暴露给前端 → 前端据此设 input max 与 clamp**，单一真相源在后端，顺便消除 1.1 节"三处魔法数分散漂移"风险。

---

## 四、多用户 / 多母版并发的服务器部署风险（分析 · 当前为单租户）

### 4.1 一句话结论

当前是「**单租户单实例**」架构——整个服务器只有一个"当前母版"概念。多用户或多母版并发会出现**数据正确性事故（排错版）**，不只是性能下降。这是全局单例状态的设计限制，调参解决不了。

### 4.2 "解析"三态安全性矩阵

| 端点 | 碰全局状态 | 写共享文件 | 并发安全性 | 位置 |
|---|---|---|---|---|
| **parse-dxf**（上传预览解析） | ❌ 无状态 | 仅写 `uploads/<uuid>.dxf`（uuid 隔离） | ✅ 安全 | `server.py:249` |
| **commit-to-nesting**（切裁片→落 intermediate） | ✅ 改 `_PIECES_STATE` | ✅ 覆盖**唯一**的 `intermediate.json` | 🔴 危险 | `server.py:417` |
| **ws/solve**（求解） | 读 `_PIECES_STATE` 快照 | 否 | 🟠 受 commit 牵连 | `server.py:707` |

**parse（预览解析）本身安全，真正的雷在 commit**——它写进全局唯一 intermediate 并 reload 全局 state。

### 4.3 P0：数据正确性事故

**P0-1 全局单例 + 单一 intermediate → "最后写赢"，求解串数据。**
`_PIECES_STATE` 是模块级全局 dict（`server.py:56`），intermediate 是全服务器唯一文件（`server.py:368`）。

```
A commit → intermediate=A, state=A
B commit → intermediate=B, state=B   ← 覆盖 A
A 点求解  → ws_solve accept 拿快照 = B 的数据！  ← A 以为排 A 版，实际排 B 版
```

`_state_lock` 只保证"读到的快照完整一致"，不保证"这个快照是我的母版"。多用户下 A 完全无感知被 B 覆盖——排错版到裁床是事故级风险。

**P0-2 commit 非原子写 → 撕裂 intermediate 崩盘。**
`server.py:368` 是裸 `open(intermediate, 'w')` + `json.dump`，**无 tmp + `os.replace` 原子替换**。两人同时 commit → 两 `open('w')` 都截断、两 `json.dump` 交错 → intermediate 变撕裂的无效 JSON → 下次任何人 reload 解析崩 → 所有人求解报"排料数据为空"。

### 4.4 P1：资源争抢与雪崩

**P1-1 parse / commit / solve 共享同一个 6 槽线程池。**
三端点全用 `_executor`（`server.py:249` / `:417` / `:707`）。commit 大母版占槽几十秒 + 同时 6 seed 求解 → 池满排队；1.4 节"6 seed 同等 CPU 竞争保公平"前提直接失效（池里混进 commit 任务，seed 间 CPU 份额不均 → 排名失真）。

**P1-2 多用户 × 多 seed → CPU/内存雪崩。** 2 用户各 6 seed = 12 进程 × 4 = **48 线程抢 32 核**（超载 50%）；Windows spawn 全量 import，12 进程内存翻倍，低内存服务器可能 OOM。

### 4.5 多 worker 部署陷阱

`main()` 用 `uvicorn.run(app, ...)` 默认**单 worker**（`server.py:779`）。若生产用 `--workers 4` 横向扩展：每 worker 独立 `_PIECES_STATE`/`_executor`，但 intermediate 是共享磁盘文件 → worker1 commit 只 reload 自己的 state，worker2~4 仍是旧的 → 同服务器不同 worker 对"当前母版"认知不一致，叠加 P0-2 撕裂，**多 worker 比单 worker 更危险**。

### 4.6 解决方向（按代价从低到高）

| 方案 | 代价 | 解决 |
|---|---|---|
| A. commit 全局互斥锁串行化 | 极低 | 止血 P0-2 撕裂 + 缓解 P0-1（仍 last-write-wins） |
| B. intermediate 原子写（tmp+`os.replace`） | 低 | 消除 P0-2 撕裂，不解决 P0-1 串数据 |
| C. state/intermediate 按 doc_id 隔离 | 中（架构改） | 根治 P0-1：`_PIECES_STATE` → `{doc_id: state}`，ws/solve 带 doc_id |
| D. 资源池按租户配额 + CPU 动态上限 | 中高 | 治 P1，与第三节动态 seed 同一事两面 |

**现实建议**：少数版师轮流用 → A+B 足够（并发退化串行，零架构改）；真要多人同时用 → 必须上 C，否则 P0-1 串数据迟早酿成事故。

---

## 五、Windows exe 本地部署：能否避免多用户并发（分析 · 未实现）

### 5.1 核心结论：能，从根本上消除"跨用户"并发

exe 模式把并发的性质整个改变：

```
服务器模式:  N 个用户 ──→  1 个后端进程(1 份 state/intermediate/池)   ← 冲突根源
exe 模式:    每人 1 个 exe = 1 个独立后端进程 = 各自独立的 state/intermediate/池
```

每个 exe 实例是独立 Python 进程，A/B 的 `_PIECES_STATE` 在各自进程内存物理隔离。第四节 P0/P1 在**跨用户层面全部消失**。对"少数版师本地各自用"的场景判断成立。

### 5.2 残留：单用户内的并发（降级为"自坑"）

| 问题 | 服务器 | exe |
|---|---|---|
| A 排到 B 的版（P0-1） | 🔴 事故 | ✅ 消失 |
| intermediate 撕裂（P0-2） | 🔴 事故 | ✅ 消失 |
| 池挤占/公平性破坏（P1） | 🔴 严重 | ✅ 消失 |
| 同一用户开多浏览器标签 | — | 🟡 残留（两标签共享同一后端 state） |
| 同一用户快速连续 commit | — | 🟡 残留（单进程单例，自己覆盖自己） |

残留场景危害从"生产事故"降级为"单机可重启、自己知情"，对内部工具可接受。

### 5.3 exe 打包引入的四个工程坑（真正的难点，按踩坑概率）

| 坑 | 说明 |
|---|---|
| **① multiprocessing 在 frozen exe 下的 spawn** | 当前 `solver.py:283` 用 `multiprocessing.Process(target=solve_worker)`。PyInstaller 打包后 Windows spawn 子进程会**重新执行 exe 主入口**，若无 `freeze_support()` + `__main__` 保护 → 子进程重跑 uvicorn → 端口冲突/无限弹窗/求解瘫痪。**最可能踩的硬坑** |
| **② 数据目录写权限失效** | `paths.py:13-18` 靠 `__file__` 上溯定位 repo 根，`INTERMEDIATE` 落 `_SERVER/out/`。frozen 后 `__file__` 指向只读 `_MEIPASS`；装到 `C:\Program Files\`（只读）→ intermediate 写盘失败 → commit 崩。须检测 `sys.frozen` 重定向 `OUT_DIR` 到 `%APPDATA%`（`MS_OUT_DIR` 环境变量通道已预留） |
| **③ 端口 8000 单实例** | 后端写死 bind `:8000`（`server.py:779`）。已占/启动第二个 exe → bind 失败（errno 10048）。反构成单实例保护，但须把失败处理成友好提示 |
| **④ 重依赖打包** | spyrrow（Rust .pyd）、shapely（GEOS DLL）、ezdxf、numpy 都是大块头，exe 体积数百 MB、首启慢（解压 `_MEIPASS`）。需 `--collect-all spyrrow` 等 |

**前端承载**：推荐 **pywebview / WebView2 内嵌**（一窗口一会话，顺带堵住多标签残留）；启动系统浏览器会有多标签残留；Electron 太重。

### 5.4 附带利好

- **动态 seed 简化**（第三节）：本地 CPU 固定，启动探测一次即可，无 cgroup 谎言，不必考虑多用户配额。
- **commit 加锁/原子写可省**（第四节方案 A/B）：单机单用户并发压力近乎为零，单人顺序操作几乎不撞。

### 5.5 适用边界

exe 适合：少数版师、本地离线、各自独立排料。要权衡：①**数据孤岛**（母版/结果分散，无集中沉淀）；②**更新分发**（算法迭代变 exe 版本发布，不如 web 即时）。

---

## 六、关键概念：CPU 核心数 vs 内存（澄清）

本机实测配置：

| 指标 | 实际值 | 含义 |
|---|---|---|
| CPU 逻辑线程 | 32 | 24 物理核 + 超线程虚拟出的 32 线程 |
| CPU 物理核 | 24 | 真正的物理核心数 |
| 内存 (RAM) | 31.7 GB | 运行内存 |

> 易混点：这台机器 CPU 逻辑线程与内存恰好都是 32，易把"32 核"误当"32G 内存"。二者是不同资源。

**区别（厨房类比）**：

- **CPU 核心** = 厨房里多少个厨师能同时炒菜（并行计算能力）→ 影响**并发数和速度**。
- **内存** = 案板多大、能同时摆多少食材（临时工作区）→ 影响**会不会因装不下而 OOM 崩溃**。

**精度修正**：严格说"32 核"不准确，是"32 个逻辑线程（24 物理核超线程而来）"。超线程对排料这种计算密集任务约 1.3 倍、非 2 倍，用物理核做分母更保守：

```
floor(24 × 0.75 / 4) = 4.5  →  真正不超载的 seed 数其实更接近 4~5，6 已吃到超线程红利
```

**内存评估**：6 个求解子进程每进程约几百 MB，合计 ~2~3 GB，相对 31.7 GB 完全充裕。**本机内存不是瓶颈，CPU 核心数才是。**

---

## 七、结论与建议汇总

| 议题 | 现状 / 判断 | 建议方向 |
|---|---|---|
| 多 seed 并发上限 | 6（三处硬编码 + 6×4<32） | 抽 `MAX_CONCURRENT_SEEDS` 单一常量消除分散漂移 |
| 提速杠杆 | num_workers=4 写死，单 seed 仅用 12.5% CPU | num_workers 动态化（按 seed_count 分配），是性能正杠杆 |
| 单机多用户 | 跨用户并发事故级 | 上 Windows exe（pywebview），根治跨用户；残留单用户自坑可接受 |
| 服务器多用户 | 单租户架构，P0 串数据事故 | 少数人轮用→commit 加锁+原子写（A+B）；多人同用→按 doc_id 隔离（C）必须 |
| 动态 seed 上限 | 写死 6 | `floor(物理核×0.75/W)`，穿透 cgroup 谎言，后端探测→前端消费 |
| 本机瓶颈 | CPU（24/32），内存（31.7G）充裕 | 优化盯 CPU 核心预算，不盯内存 |

**一句话**：当前 6 seed 合理且公平；性能真瓶颈是 `num_workers=4` 写死导致单 seed 仅用 12.5% CPU；并发安全的真问题是**单租户全局单例**——单机部署走 exe 即可规避，服务器多租户必须按 doc_id 隔离，否则迟早排错版。

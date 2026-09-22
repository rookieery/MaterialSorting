# PRD: 机器任务 .msn 状态文件下载端点（机器对接三期 · MaterialSorting 侧）

> 配套 PRD：YL 侧透传对接见 `tasks/prd-machine-state-file-yl.md`（交付 YL 团队；YL 侧仅按钮 + 字节流透传，可复制至 `D:\code\YLPatternMaking\tasks\` 由其 Ralph 消费，先例 `prd-ms-nesting-integration.md`）。
> 需求定稿：2026-09-22 会话分析 + 五项决策点全部锁定（端点形态 / 运行中允许 / 纯配置档 / provenance 映射 / 文件名）。

## 概述 (Overview)

为机器任务（`/api/machine/*`）新增 `.msn` 状态文件下载端点：把任务的工作台态（doc 五层 + form + quantities + run 最优布局）服务端装配成与浏览器「保存状态文件」完全同构的 gzip JSON 附件。YL 用户拿到文件后在 MS 工作台「状态恢复」上传，即可基于机器求解结果继续人工调整（编辑布局 / 智能微调 / 改数量重解 / 导出 PNG·DXF·PLT）。恢复端全链路现成（状态文件 PRD US-001/002 已验收），MS 前端零改动。

## 目标 (Goals)

- YL 凭 `task_id` 一步换取 `.msn` 附件：`GET /api/machine/solve/{task_id}/state-file`，无请求体，token 闸 / 公共闸与既有五端点同族
- 会话无关：会话被 TTL 逐出、甚至 MS 重启后（内存槽在）仍可下载 —— doc 从 run_dir `pieces_intermediate.json` 直载（export 同先例），form/quantities 从状态槽快照回落 `machine_cfg_<sid>_*.json`
- 生成物与浏览器 `POST /api/state-save` 产物**同构可恢复**：schema v1 零变更、`web/statefile.py` 零改动，序列化/守恒全部复用其导出符号

## 用户故事 (User Stories)

### US-001: state-file 端点（数据链装配 + 守恒 + 序列化 + 错误契约）
- **Description**: As a 机器客户端（YL 后端）, I want 用 task_id 换取该任务的 .msn 状态文件, so that 用户可把机器求解结果带回 MS 工作台继续人工调整。文件：`web/machine.py`（新端点 + doc 契约注释；复用 `_machine_task_ctx`/`_machine_token_error`/`_best_layout`/`strategy_mod._status_common`、`load_pieces`、`statefile.build_state_document`/`serialize_state`/`check_placed_conservation`）、`tests/test_web_machine.py`（增补）。
- **Acceptance Criteria**:
  1. **端点契约**：`GET /api/machine/solve/{task_id}/state-file` → `200 application/gzip` 附件，`Content-Disposition` 中文/ASCII 双写（state_save 同法），文件名 `<doc.source 去 .dxf>_状态_<yyyymmdd-HHMMSS>.msn`（ASCII fallback `nesting_state_...`）；`MS_MACHINE_TOKEN` 设置时缺失/错头 → 401 先行；task_id 非法 → 400 / 未知任务 → 404（`_machine_task_ctx` 公共闸，含 DELETE 后 404）。
  2. **doc 三源链**：① run_dir `pieces_intermediate.json` 直载（`load_pieces` 返回的 doc 即 .msn doc 块，含 5 层）→ ② 会话快照 `registry.peek(task_id).state['doc']` → ③ per-doc intermediate（`doc_id` 经状态槽/marker 反查 `uploads/<doc_id>_pieces/`）。AC：显式使会话 TTL 逐出后下载仍 200 且与存活期产物**逐字节一致**。
  3. **form/quantities 合成**：源 = 状态槽 start 快照（`sizes`/`per_type`/`quantities`/`gate_mm`）→ 槽缺失回落 `machine_cfg_<sid>_*.json`；`form.gate = str(gate_mm/10)`（cm 字符串，恢复端 `_form_gate_mm` ×10 口径）—— AC：生成物走恢复链后 manifest `gate_mm` == 任务 `gate_mm`（1750/1800 双值抽验）；`form` 其余键（time=档位烘焙秒数/seed='0'/multi_seed/seed_count/band_*/prefix_*）给满形态缺省值，恢复后前端表单无 undefined；`quantities` 缺省 None 入档（全 1 旧语义）。
  4. **run 块**：`_best_layout(run_dir)` 与 result/export 同源同序；`placed` = `best.placed_items` 原样（demand>1 N 条绝不按 pid 去重）；`seed` 透传；`final` 按 best 可用键合成（`density`/`density_sparrow`/`width_mm`/`elapsed` 至少在场，缺键省略）；`provenance.kind` 映射 normal→`solve` / advanced→`strategy_race` / extreme→`extreme`（`config:{time_total_s:烘焙预算}` 纯展示可选）。无任何布局帧（error 态/未产帧）→ **纯配置档**：200、文件无 `run` 键。
  5. **守恒闸**：run 在场时 `check_placed_conservation(placed, doc.pieces, sizes, per_type, quantities)` 通过（求解与入档同源配置，理论必过）；防御性失败 → `409` 中文（「布局与数量矩阵不一致，无法生成状态文件」——不让内部不一致文件流出，state_save §五.5 同定案）。
  6. **roundtrip**：生成物 gzip 解开经 `parse_state_document` 校验链全过，`doc`/`form`/`quantities`/`run` 逐块一致；恢复链 `build_pid_meta` 重算 demand 与 result 端点 manifest 逐 pid 相等。防御：序列化后未压缩尺寸 > `STATE_MAX_BYTES`（20MB）→ 409（防生成不可恢复文件）。
  7. `pytest tests/test_web_machine.py` 全绿（新增用例覆盖上述 1~6 + 三档 run_mode 各一条 provenance 断言）+ 全量后端测试零回归；AST 守卫不新增违规（machine→statefile 单向 import，无环）。
- **Priority**: 1

### US-002: 契约文档 + 透传指引 + 冒烟清单
- **Description**: As a YL 对接开发者, I want 机器契约专节覆盖 state-file 端点与透传指引, so that 仅凭该节即可完成 YL 侧下载功能对接。文件：`.docs/technical/agent-api-reference.md`（机器专节）、`README.md`（机器节）。
- **Acceptance Criteria**:
  1. 机器专节新增「GET /api/machine/solve/{task_id}/state-file」小节：请求/响应、错误码（401/400/404/409 触发条件表）、`.msn` 五块服务端来源说明（YL 无感，仅供排障）、纯配置档语义、running 期下载 = best-so-far 快照（export 同语义）、**密度口径警示沿用**（final.density 物理毛版口径不可与历史 erode 混比）。
  2. **YL 透传指引**：.msn 为不透明字节流（YL 不解析、schema 升级零感知）；透传 `Content-Type` 与 `Content-Disposition`（保文件名/扩展）；克隆既有 PLT 导出下载通道模式；用户后续路径一条链（下载 → MS 工作台「状态恢复」上传 → 编辑/微调/重解/导出）。
  3. §8 错误码汇总表补 state-file 行；§10 对接推荐流程加分支「需人工继续调整 → GET state-file（终态后及时取件，同 export 运维注记）」。
  4. README 机器对接节一句话 + 指向契约专节；文档内附 curl 冒烟序列（solve → status 轮询至终态 → state-file 存盘 → MS 工作台恢复验证）。
  5. 全量后端测试零回归。
- **Priority**: 2（依赖 US-001）

## 功能需求 (Functional Requirements)

- FR-1: `GET /api/machine/solve/{task_id}/state-file`：无请求体；token 闸（`_machine_token_error`）与 task_id 公共闸（`_machine_task_ctx`）先行，与五端点家族同口径。
- FR-2: doc 块三源链：run_dir intermediate 直载 → 会话快照 → per-doc intermediate（`doc_id` 反查）；三源同内容（commit 单点写入），任一命中即 200，全空 → `409 {"error":"裁片数据已不可得（run_dir 与上传快照均缺失）"}`。
- FR-3: form 合成：`gate` = 任务实际门幅 cm 字符串（**必须**，恢复 manifest 幅宽单一来源）；`sizes`/`per_type` 原样；`time` = `RUN_MODE_SPECS[run_mode]['time']`；其余 FormState 键满形态缺省。quantities 原样入档（None = 全 1 语义）。
- FR-4: run 块：`_best_layout` 同源；provenance 三档映射；final 合成；无布局 → 纯配置档（无 run 键，仍 200）。
- FR-5: 守恒校验复用 `statefile.check_placed_conservation`；失败 409 中文，不让坏文件流出。
- FR-6: 序列化复用 `statefile.build_state_document` + `serialize_state`（schema v1 / `statefile.py` **零改动**）；`quantities_base`/`pending_strategy_result` 不产（机器无此概念，省键式）。
- FR-7: 响应附件契约同 `state_save`（application/gzip + CD 中文/ASCII 双写）。

## 非目标 (Non-Goals)

- `.msn` schema 任何变更 / `web/statefile.py` 任何改动（纯消费方）
- 机器任务的 `pending_strategy_result` 槽（无「待确认弹窗」语义，run 块直接呈现）
- `placed`/`table` 等覆写参数（.msn 恒服务端权威装配，与 export 的可覆写面刻意不同）
- YL 侧改动（见配套 PRD）
- MS 工作台前端任何改动（恢复管线现成，47 检查冒烟已验收）
- .msn 内容预览 / 在线恢复的机器通道（恢复仍走浏览器「状态恢复」上传）

## 设计考虑 (Design Considerations)

- 用户动线：YL 任务结果页下载 .msn → 交付版师 → MS 工作台「状态恢复」→ 预览 Tab + 数量矩阵 + 超排画布最优布局全量还原 → 编辑/微调/重解/导出。恢复后会话为用户自己的浏览器会话，与机器任务 sid 无任何纠缠。
- provenance 来源小字如实反映档位（normal 显示普通求解 / advanced race / extreme 极限），避免版师误判结果来历。
- 纯配置档是有价值产物而非降级：error 态任务（坏配置/超时）的 .msn 让用户在 MS 工作台改参数自行重解，不必回 YL 重走提交流程。

## 技术考虑 (Technical Considerations)

- 分层：`machine.py` import `statefile`（兄弟 web 模块单向，statefile 不反向 import machine，无环）；禁 import `..cli.*` 不涉（无 spawn）；`server`/`UPLOADS_DIR` 依赖沿用函数内延迟 import + 模块属性调用时取值（tests monkeypatch 生效点不变）。
- `form.gate` 教训（2026-09-11 E2E 备案）：恢复 manifest 幅宽取 form 侧 cm×10；intermediate doc 的 `gate_mm` 是 commit 期默认值（GATE_MM=1750），与任务实际门幅可能不同 —— 由 `_form_gate_mm` 既有语义覆盖，**不需要**改 doc 块。
- running 期下载：`_best_layout` 直读 best_frame 边车，无人轮询推进到 done 也不阻塞（export 同先例）；曲线/不可行帧过滤（2026-09-16 `_frame_allowed`）已保证边车只含可行帧。
- 生命周期约束沿用家族语义：MS 重启后已 done 未取件（marker 已清 + 内存槽丢）→ 404，契约文档「终态后及时取件」警示对 state-file 同样适用；DELETE 后 404；run_dir 7 天机会式清理窗内可下载。
- 生成耗时秒级（intermediate json 直载 + gzip，典型 < 2s）；YL 侧代理超时建议 ≥30s（写进透传指引）。
- 生成物尺寸：上传 ≤20MB DXF → doc JSON 量级相当，超 `STATE_MAX_BYTES` 概率极低，防御性 409 兜底。

## 成功指标 (Success Metrics)

- [ ] 会话 TTL 逐出后下载 200，产物与存活期逐字节一致（同 export M 演练判据）
- [ ] roundtrip：生成 .msn → `parse_state_document` 全过 → 恢复链 manifest demand 逐 pid == result 端口；`manifest.gate_mm` == 任务 gate_mm
- [ ] 三档 run_mode provenance 映射正确；normal 档（无 portfolio incumbent）经 best_frame 回落仍出完整 run 块
- [ ] 纯配置档路径（无帧任务）200 且文件无 run 键；守恒防御路径 409
- [ ] `pytest tests/test_web_machine.py` 全绿 + 全量后端测试零回归

## 待确认问题 (Open Questions)

- 无（五项决策 2026-09-22 锁定：① GET path-param 无请求体；② 运行中允许 = best-so-far；③ 无布局出纯配置档；④ provenance 按档位映射；⑤ 文件名 `<原上传名>_状态_<ts>.msn`）。

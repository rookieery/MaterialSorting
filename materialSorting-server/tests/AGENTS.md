# tests/ — Agent 速查

> `materialSorting-server/tests/` 单测目录（US-025 起新建）。pytest 走 `pyproject.toml` 的 `[tool.pytest.ini_options] testpaths=["tests"]`，根目录 `materialSorting-server/`。

## 运行

```bash
cd materialSorting-server
../.venv/Scripts/python.exe -m pytest tests/ -v            # 全跑
../.venv/Scripts/python.exe -m pytest tests/test_solve_proc.py::test_terminate_returns_within_5s -v
../.venv/Scripts/python.exe -m pytest tests/ -k normal     # 按名筛选
```

## 文件

| 文件 | 覆盖 |
| --- | --- |
| `conftest.py` | sys.path 注入 `src/`（未 `pip install -e .` 也能跑）；`real_or_synthetic_pieces` / `synthetic_pieces` fixture（优先读真实 intermediate，缺失则合成 2 片矩形；US-001 起合成片为 **v2 schema**：`pid='g01_28'`、有 `label` 无 `ptype`/`side`） |
| `test_solve_proc.py` | US-025 `solve_worker` + `solve_with_callback_proc`：①正常求解 + density 双口径 ②terminate 5s 内返回 ③build_instance 抛错 ④外部 kill 不 hang ⑤solve_worker 可 pickle |
| `test_ws_stop.py` | US-026 WS `/ws/solve` stop 协议 + 客户端断开清理：①start→frame→stop→stopped+WS 关闭 ②直接断连→进程数回落 ③不发 stop 正常求解收 final（用 `starlette.testclient.TestClient`） |
| `test_export_plt.py` | US-033 `write_marker_plt` HPGL 文本生成器（封装对齐生产 PLT）：头部 `IN;PS<纸长>;SP1;PW0.08;`、CRLF 行尾、尾部 `PU;PG;`、无 VS/LB、坐标×40 round 取整、闭合不变量（SP1 PU 首点=PD 末点、SP6 门幅框 4 角闭合）、6 个笔号各有数据时全出现、空层跳过、多片 N×SP1、PS 覆盖刺口法线延伸、越界统计 `_plt_frame_stats`、5 层笔号语义端到端、空 pieces 防御边界（合成裁片，不依赖 intermediate） |
| `test_load_pieces_notches.py` | `_apply_layer_transforms` 刺口变换回归：notch **点**随片旋转（旧实现只转法线导致竖直布纹片刺口飞出轮廓 3m+，腰/后袋 600 越界点污染 PLT/PNG/DXF）、法线旋转、rot=0 直通（US-001 起镜像分支已删，镜像用例随删） |
| `test_labeling.py` | US-001 v2 `labeling` 单测：`label_for`/`code_sort_key` 边界、`master_code_from_block_name` 保守识别矩阵（含仓内易误伤 block 名）、`collect_master_codes` all-or-nothing（有效片=全部 size≠None，未录名组同样参与）、`assign_codes` 顺序模式（`sequential_sort_key` group_key 前置 / T4 跨码同号 / AC#5 确定性）与母版复用模式 |
| `test_label_representatives.py` | US-001 v2 `_build_label_representatives`：键=g 码、代表取最小码首个 size≠None 片、5 层字段白名单（由 test_ptype_representatives.py 更名而来） |
| `test_commit_pipeline.py` | US-001 v2 commit 全管线（合成「未录入名称」母版）：0 丢片全片有 g 码、`{label}_{size}.dxf`+`pieces_manifest.json` 落盘、manifest 驱动 `load_nest_pieces`（pid=`{label}_{size}`）、AC#5 parse↔intermediate 逐片 label+面积对齐、idempotent 重跑、旧切片目录/v1 intermediate 明确报错「请重新 commit」 |
| `test_solver_label.py` | US-002 求解/导出层 label 键：`label_color`（16 色循环/同码同色/兜底）+ `label_aci`（`((code-1)%24)+1` 公式与循环）、`build_instance` per_type `(label,sizeKey)` 命中即覆盖（erode/tol 只落命中片；未命中与旧 ptype 键 no-op；全局上限收边）、quantities demand 直译（0 跳过/N 副本/面积×demand）、pid_meta 无 ptype 键且 color=label_color、`constraints.validate` 删成对齐套校验后裸 pid 裁片可用 |

## Windows multiprocessing 测试注意

- **目标函数必须顶层**：`multiprocessing.Process(target=...)` 在 Windows spawn 模式下 pickle target；闭包 / 局部函数不可 pickle。`solve_worker` 是顶层（`materialsorting.web.solve_worker`），不是 `__main__`。
- **不在模块级创建 Process**：pytest import 测试模块时若触发 spawn 会无限递归。所有 Process 创建在 test 函数内。
- **`__main__` 守卫**：`if __name__ == "__main__": pytest.main([__file__, "-v"])` 让脚本直接 `python tests/test_solve_proc.py` 也能跑（不走 spawn 路径）。
- **找子进程**：`multiprocessing.active_children()` 列出当前进程的活子进程；测试用它在 `on_report` 回调里定位 solve worker 并 terminate / kill（模拟 US-026 stop 协议 + 外部 crash）。
- **`exitcode` 语义**：`None`=还在跑、`0`=正常退出、`>0`=异常退出（exit(code)）、`<0`=被信号杀（`-15`=SIGTERM 即 `terminate()`，Windows 实为 TerminateProcess 但 Python 也记负数）。

## fixture 设计

- **`real_or_synthetic_pieces`**：优先读 `paths.INTERMEDIATE`（取码 28 子集加速），失败回退 `_synthetic_pieces()`（2 个简单矩形 400k + 120k mm²）。CI / 全新 checkout 无 intermediate 时也能跑。
- **`synthetic_pieces`**：总是合成数据，用于错误路径测试（避免依赖真实 intermediate 的不确定性）。

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
| `conftest.py` | sys.path 注入 `src/`（未 `pip install -e .` 也能跑）；`real_or_synthetic_pieces` / `synthetic_pieces` fixture（优先读真实 intermediate，缺失则合成 2 片矩形） |
| `test_solve_proc.py` | US-025 `solve_worker` + `solve_with_callback_proc`：①正常求解 + density 双口径 ②terminate 5s 内返回 ③build_instance 抛错 ④外部 kill 不 hang ⑤solve_worker 可 pickle |

## Windows multiprocessing 测试注意

- **目标函数必须顶层**：`multiprocessing.Process(target=...)` 在 Windows spawn 模式下 pickle target；闭包 / 局部函数不可 pickle。`solve_worker` 是顶层（`materialsorting.web.solve_worker`），不是 `__main__`。
- **不在模块级创建 Process**：pytest import 测试模块时若触发 spawn 会无限递归。所有 Process 创建在 test 函数内。
- **`__main__` 守卫**：`if __name__ == "__main__": pytest.main([__file__, "-v"])` 让脚本直接 `python tests/test_solve_proc.py` 也能跑（不走 spawn 路径）。
- **找子进程**：`multiprocessing.active_children()` 列出当前进程的活子进程；测试用它在 `on_report` 回调里定位 solve worker 并 terminate / kill（模拟 US-026 stop 协议 + 外部 crash）。
- **`exitcode` 语义**：`None`=还在跑、`0`=正常退出、`>0`=异常退出（exit(code)）、`<0`=被信号杀（`-15`=SIGTERM 即 `terminate()`，Windows 实为 TerminateProcess 但 Python 也记负数）。

## fixture 设计

- **`real_or_synthetic_pieces`**：优先读 `paths.INTERMEDIATE`（取码 28 子集加速），失败回退 `_synthetic_pieces()`（2 个简单矩形 400k + 120k mm²）。CI / 全新 checkout 无 intermediate 时也能跑。
- **`synthetic_pieces`**：总是合成数据，用于错误路径测试（避免依赖真实 intermediate 的不确定性）。

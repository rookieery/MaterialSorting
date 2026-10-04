"""初始布局 web 侧 warm 载荷装载点 + 热启动能力探测（US-001，prd-initial-layout）。

warm-start 一期把引擎透传链（``solve_with_callback_proc(initial_solution=...)`` +
worker 三闸门）铺在了 **CLI 侧**（``cli/pipeline._load_warm_payload`` 读筛选轮
best_frame 边车装载）；二期把「界面录入初始布局 → WS 热启动」向用户开放，本模块
是 **web 侧的镜像装载点**（一期结论：web 侧此前无此装载点）：把前端保存的
placed 列表（展开视图或 band/prefix 组合宇宙条目）安全转换为 spyrrow
``initial_solution`` 载荷。与 CLI 装载点的差异只在数据源（边车 → 界面载荷），
校验与构造语义逐条镜像：

- ``demand_map`` 双口径（防 worker ``instance_mismatch``）：
  - 缺省 None（plain）→ 经 ``web.solver.build_pid_meta`` 同口径投影
    ``{pid: int(demand)}`` —— 与 worker ``build_instance`` 的实例宇宙同参同源
    （sizes/per_type/quantities/params 逐字段透传，demand=0 片同样出局）；
  - 显式给定（band/prefix 组合宇宙，pid 含 ``WB_``/``PS_``、成员 pid 按扣减后
    demand）→ **直接采用**（生成响应 ``composite.demand_map`` 不透明透传，组合
    片宇宙主进程无法推导，worker 侧 ``payload_universe_error`` 复检兜底）。
- ``strip_width``：``solver._physical_width_mm`` 同款物理毛版包络公式
  （``ceil(maxX − 1e-9)``，与前端 ``computeLayoutStats`` 逐位同式）。组合片条目
  （pid 不在 intermediate pid_meta，无原始轮廓）**不计入包络** —— 组合片轮廓
  存活在 worker 实例内，主进程不可得；量取可测量条目（measurable-only）已覆盖
  排料宽度的主导项（组合片恒居布头低 x 区）。
- 全降级不抛：``warm_start_supported()`` False / placed 形态非法 / 裁片实例构造
  失败 / pid 需求映射外前置复检 / ``warmstart.build_initial_solution`` 校验矩阵
  （完整解硬约束 / mirror / 畸形）任一命中 → ``(None, 中文 reason)``，调用方
  （US-003 WS start）照常起普通求解**不炸轮**（镜像 CLI 装载点回退矩阵语义）。

能力探测 ``warm_capability()``：``{'supported': bool, 'version': str}`` 包装
``warmstart.warm_start_supported()``（版本串经 ``importlib.metadata`` 容错读取，
未安装/异常 → ``'(未安装)'`` 恒为 str，探测恒不抛）；经 ``GET /api/warm-capability``
（routes_views）恒 200 暴露给前端按钮置灰判定 —— 能力是**进程级属性**，无会话
闸门。

US-002 生成编排 ``generate_initial_layout()``：初始布局弹窗「打开/刷新」的数据源
—— ``web.prefix_accept.run_arm`` 同款同步收集形态（回调塞 list 收 manifest/frames/
final）经 ``solve_with_callback_proc(..., record_composite=True)`` 跑短求解
（``time_budget`` 由端点传 ``INITIAL_LAYOUT_GEN_TIME_S``），取**密度最大可行帧**
（可行过滤 ``solve_worker._frame_allowed`` 白名单在发射层已保证）组响应：
``{ok, manifest(WS 前端契约同形), placed(展开视图，永无 WB_/PS_), width_mm,
density, composite?{placed_items, demand_map}, prefix?}`` —— ``composite`` 段仅在
band/prefix 开时随帧在场（worker 展开**前** solver 原始条目 + 组合宇宙 demand_map，
US-006 前端保存 warm 载荷的组合视角数据源）；失败抛 ``InitialLayoutGenError``
（中文 message，端点映射 502）。

分层约束：本模块属 ``web``，仅 import 同包兄弟 ``solver``（build_pid_meta /
_raw_polygon_map / _physical_width_mm / solve_with_callback_proc）/ ``routes_ws``
（``_build_manifest_msg``，函数内延迟）+ ``nesting_engine.warmstart``；
**禁 import server/cli**（AST 守卫在 tests/test_web_initial_layout.py，镜像
tests/test_web_edit_hold.py 套路）。``__main__`` 合成夹具冒烟自检
（``python -m materialsorting.web.initial_layout``）无真实母版 / spyrrow solve
依赖（能力探测在夹具内临时打桩，ms0/PyPI 环境同样全过）。
"""
from __future__ import annotations

import importlib.metadata
import json
import sys

from ..nesting_engine import warmstart
from .solver import _physical_width_mm, _raw_polygon_map, build_pid_meta

# 版本串读取失败的哨兵值（与 warmstart 冒烟回显同口径，前端按 str 透传展示）。
_VERSION_UNKNOWN = '(未安装)'

# 能力探测未过 → 中文 reason（US-003 WS start 降级矩阵消费 + 前端 toast 同源文案）。
_REASON_UNSUPPORTED = ('当前 spyrrow 版本不支持热启动'
                       '（需 0.9.0+ms1 及以上私有 wheel）')


def warm_capability() -> dict:
    """热启动能力探测（进程级，恒不抛）→ ``{'supported': bool, 'version': str}``。

    ``supported`` = ``warmstart.warm_start_supported()``（``+ms>=1`` local tag 判定，
    见其 docstring）；``version`` = ``importlib.metadata.version('spyrrow')`` 容错
    读取（包缺失 / 任何异常 → ``'(未安装)'``）。``GET /api/warm-capability`` 的
    单一数据源（前端「设置初始布局」按钮置灰判定）。
    """
    try:
        version = str(importlib.metadata.version('spyrrow'))
    except Exception:                      # noqa: BLE001 探测恒不抛（PackageNotFoundError 等）
        version = _VERSION_UNKNOWN
    return {'supported': warmstart.warm_start_supported(),
            'version': version}


def build_warm_payload(pieces, placed, *, gate_mm=None, sizes=None,
                       per_type=None, quantities=None, params=None,
                       demand_map=None) -> tuple[dict | None, str | None]:
    """界面 placed 列表 → spyrrow warm 载荷（web 侧装载单一真相源，全降级不抛）。

    Parameters
    ----------
    pieces : list[dict]
        会话 intermediate pieces 快照（``build_pid_meta`` 输入，与 worker
        ``build_instance`` 同源同参）。
    placed : list[dict]
        界面保存的初始布局条目 ``{id, rotation(度), translation:[x,y]}``
        （编辑器同构）；plain = 展开视图全条目，band/prefix 开 = 组合宇宙条目
        （pid 含 ``WB_``/``PS_``）。
    gate_mm : float | None
        门幅（mm）。**当前未消费** —— 载荷契约仅 ``strip_width``/``placed_items``
        两键（见 warmstart docstring 输出契约）；签名保留与求解上下文同形
        （US-003 routes_ws 调用点已解析该值，未来校验/密度回显扩展位）。
    sizes, per_type, quantities, params
        透传 ``build_pid_meta``（与 worker 实例宇宙一致，防 ``instance_mismatch``；
        缺省 None = 不过滤，与 build_pid_meta 同缺省语义）。
    demand_map : dict[str, int] | None
        缺省 None → pid_meta demand 投影（plain 宇宙）；给定（band/prefix 组合
        宇宙）→ 直接采用，不再从 pid_meta 推导。

    Returns
    -------
    (payload, None)
        装载成功：``{"strip_width": float, "placed_items": [{id, rotation,
        translation}]}``（``warmstart.build_initial_solution`` 产物，纯 JSON dict）。
    (None, reason)
        降级（中文 reason，全矩阵不抛，判定序即上列顺序）：unsupported / placed
        空·形态非法 / 无母版 / 裁片实例构造失败 / pid 需求映射外前置复检 /
        无可测量轮廓 / ``build_initial_solution`` 校验矩阵（完整解硬约束 /
        mirror / 畸形条目）。
    """
    if not warmstart.warm_start_supported():
        return None, _REASON_UNSUPPORTED
    if not isinstance(placed, list) or not placed:
        return None, '初始布局为空或形态非法，无法热启动'
    if not pieces:
        return None, '排料数据为空（请先上传母版）'
    try:
        pid_meta, _total_area, _n_eroded = build_pid_meta(
            pieces, sizes=sizes, per_type=per_type,
            quantities=quantities, params=params)
    except Exception as e:                 # noqa: BLE001 装载点契约：脏 pieces 降级不抛
        return None, f'裁片实例构造失败：{e}'
    if demand_map is None:
        demand_map = {pid: int(m['demand']) for pid, m in pid_meta.items()}

    # pid 宇宙前置复检（宽于 build_initial_solution 的逐条检查：任一条目 pid 不在
    # 最终 demand_map → 先行降级，给「母版/数量已变更」的人话 reason，而不是让
    # 宽度量取先炸出含糊文案 —— 保存态与运行态参数漂移是热启动最常见失效形态）。
    for i, it in enumerate(placed):
        if isinstance(it, dict) and it.get('id') not in demand_map:
            return None, (f'初始布局第 {i} 条含当前需求映射外的裁片 id：'
                          f'{it.get("id")!r}（母版或数量/参数已变更？）')

    # strip_width：物理毛版包络（_physical_width_mm 单一权威公式）。组合片条目
    # （WB_/PS_ 不在 pid_meta）无原始轮廓，不计入包络（measurable-only，见模块
    # docstring）；全条目均不可测量 → 降级（pid 已全数在 demand_map 内，即全组合
    # 片条目的退化宇宙 —— 量不出任何原始轮廓）。
    pid_raw = _raw_polygon_map(pid_meta)
    measurable = [it for it in placed
                  if isinstance(it, dict) and it.get('id') in pid_raw]
    width = _physical_width_mm(measurable, pid_raw) if measurable else None
    if width is None:
        return None, '初始布局仅含组合片条目（无可测量裁片轮廓），无法计算用布长度'

    try:
        payload = warmstart.build_initial_solution(placed, demand_map, width)
    except ValueError as e:                # warmstart 校验矩阵（中文消息直接作 reason）
        return None, str(e)
    except Exception as e:                 # noqa: BLE001 防御：装载点绝不抛（理论不可达）
        return None, f'初始布局装载失败：{e}'
    return payload, None


# ------------------------------------------------ US-002 生成编排（短求解）

# 短求解预算（秒）：弹窗打开/刷新一次的生成时长（求解 + 子进程启停开销 ≈ 预算+数
# 秒）。PRD 既定 10，2026-10-04 用户定案收敛 5（弹窗等待感更短）；端点
# （routes_views）经本常量组 solve_params（测试断言 time_budget 数据源）。
INITIAL_LAYOUT_GEN_TIME_S = 5


class InitialLayoutGenError(Exception):
    """初始布局生成失败（求解错误 / 无 manifest / 无可行帧）。

    ``str(e)`` = 中文错误文案，端点（routes_views）捕获后映射 ``502 {error}``。
    与装载点 ``build_warm_payload`` 的 ``(None, reason)`` 降级风格刻意不同：生成本
    身就是用户显式动作（弹窗打开/刷新），失败即结构化报错可重试，无静默降级场景。
    """


def generate_initial_layout(pieces_snapshot, gate_mm, solve_params, *,
                            band=None, prefix=None) -> dict:
    """短求解同步收集 → 完整初始布局响应段（US-002，初始布局弹窗数据源）。

    ``web.prefix_accept.run_arm`` 同款同步收集形态（回调塞 list 收 manifest/frames/
    final）：``solve_with_callback_proc`` 与 ``/ws/solve`` **同一求解管线**（同一
    ``solve_worker`` 子进程内 build_instance + solve + 帧前展开 WB_/PS_），仅预算短
    （端点传 ``time_budget=INITIAL_LAYOUT_GEN_TIME_S``）且 ``record_composite=True``
    （band/prefix 开时帧附展开前组合视角 ``composite`` 段；关闭时 worker 不附，
    响应同样无该键）。**须在工作线程内调用**（端点经 ``run_in_threadpool``，防阻塞
    事件循环）；阻塞秒级 = ``solve_params['time_budget']`` + 子进程启停开销。

    Parameters
    ----------
    pieces_snapshot, gate_mm, solve_params, band, prefix
        与 ``solve_with_callback_proc`` 同名参数同形（pieces_snapshot = 会话 pieces
        纯 dict 拷贝；band/prefix = ``routes_ws._parse_band``/``_parse_prefix`` 校验
        产物 worker 形态）。

    Returns
    -------
    dict
        ``{ok: True, manifest, placed, width_mm, density, composite?, prefix?}``：
        - ``manifest`` = WS 前端契约同形（``routes_ws._build_manifest_msg`` 单一真相
          源，前端 US-006 合成伪 RunRecord 直用）；
        - ``placed``/``width_mm``/``density`` = **密度最大可行帧**（density 已由 proc
          层 ``_apply_density_dual`` 换算原面积口径；可行过滤在 worker 发射层，
          本函数不做二次过滤）；placed 恒为展开视图三键条目（永无 WB_/PS_）；
        - ``composite`` 仅在 band/prefix 开时在场（展开前 solver 原始条目 + 组合
          宇宙 demand_map，US-006 保存 warm 组合载荷的数据源）；
        - ``prefix`` = worker final 统计段（prefix 开时在场）。

    Raises
    ------
    InitialLayoutGenError
        求解错误（含 worker error / 意外退出）/ manifest 缺席 / 无任何可行帧。
    """
    # 调用时 import（monkeypatch materialsorting.web.solver.solve_with_callback_proc
    # 生效 = 测试注入点；pipeline 先例）+ routes_ws 兄弟延迟（模块级无环）。
    from .routes_ws import _build_manifest_msg
    from .solver import solve_with_callback_proc

    manifest = None
    frames: list = []
    final = None

    def on_manifest(m):
        nonlocal manifest
        manifest = m

    def on_report(r):
        frames.append(r)

    _proc, final, _elapsed, err = solve_with_callback_proc(
        [dict(p) for p in pieces_snapshot], float(gate_mm), dict(solve_params),
        on_manifest=on_manifest, on_report=on_report,
        band=band, prefix=prefix, record_composite=True)

    if err is not None:
        raise InitialLayoutGenError(f'求解失败: {err}')
    if manifest is None:
        raise InitialLayoutGenError('求解失败: 未收到裁片清单（manifest）')
    if not frames:
        raise InitialLayoutGenError('求解失败: 未产生任何可行帧')

    # 密度最大可行帧（帧序无关 argmax；等值取先到帧 = max 语义）。
    best = max(frames, key=lambda f: float(f.get('density') or 0.0))
    resp = {
        'ok': True,
        'manifest': _build_manifest_msg(manifest, float(gate_mm)),
        'placed': best.get('placed_items') or [],
        'width_mm': best.get('width_mm'),
        'density': best.get('density'),
    }
    if isinstance(best.get('composite'), dict):
        resp['composite'] = best['composite']
    if final is not None and isinstance(final.get('prefix'), dict):
        resp['prefix'] = final['prefix']
    return resp


# --------------------------------------------------------------- 冒烟自检

def _smoke_pieces() -> list[dict]:
    """合成 2 片矩形裁片（schema v2 子集，build_pid_meta 够用即可）。"""
    return [
        {'pid': 'g01_28', 'label': 'g01', 'size': 28,
         'polygon': [[0.0, 0.0], [500.0, 0.0], [500.0, 800.0], [0.0, 800.0]],
         'bbox': [0.0, 0.0, 500.0, 800.0], 'area_mm2': 400000.0, 'n_verts': 4,
         'allowed_angles': [0, 180], 'net_polygon': [], 'internal_lines': [],
         'notches': [], 'grain_line': None},
        {'pid': 'g02_28', 'label': 'g02', 'size': 28,
         'polygon': [[0.0, 0.0], [300.0, 0.0], [300.0, 400.0], [0.0, 400.0]],
         'bbox': [0.0, 0.0, 300.0, 400.0], 'area_mm2': 120000.0, 'n_verts': 4,
         'allowed_angles': [0, 180], 'net_polygon': [], 'internal_lines': [],
         'notches': [], 'grain_line': None},
    ]


def _smoke_fixtures() -> bool:
    """合成夹具自检（US-001 验收口径，无真实母版/spyrrow solve 依赖）。

    能力探测在夹具内**临时打桩**（保存→替换→finally 还原 ``warmstart`` 模块属性）：
    装载点判定序首查 ``warm_start_supported()``，不打桩则 ms0/PyPI 环境恒降级、
    happy path 不可验 —— 打桩后冒烟与装载态解耦，任何环境同一口径全过。
    """
    ok = True

    def report(passed: bool, name: str, detail: str = '') -> None:
        nonlocal ok
        if not passed:
            ok = False
        line = f'  {"ok" if passed else "FAIL"}  {name}'
        if detail:
            line += f'：{detail}'
        print(line)

    def expect_reason(name, fn, needle):
        """降级断言：(None, reason 含 needle) 且绝不抛。"""
        try:
            payload, reason = fn()
        except Exception as e:             # noqa: BLE001 冒烟只报不炸
            report(False, name, f'不应抛 {type(e).__name__}: {e}')
            return
        report(payload is None and reason is not None and needle in str(reason),
               name, str(reason) or '（未降级）')

    real_supported = warmstart.warm_start_supported
    try:
        # ---- 能力探测（真实态：只验形态与不抛，装载态多态由单测矩阵锁定）
        cap = warm_capability()
        report(isinstance(cap, dict)
               and set(cap) == {'supported', 'version'}
               and isinstance(cap['supported'], bool)
               and isinstance(cap['version'], str),
               'warm_capability() 形态 {supported: bool, version: str}',
               f'当前装载：spyrrow {cap["version"]}')

        warmstart.warm_start_supported = lambda: True   # 装载态打桩（下同）
        pieces = _smoke_pieces()
        quantities = {'g01': {'28': 2}, 'g02': {'28': 1}}
        ctx = dict(gate_mm=1980.0, sizes=None, per_type=None,
                   quantities=quantities, params=None)

        # ---- plain happy path：round-trip + strip_width 与权威公式对拍
        placed = [
            {'id': 'g01_28', 'rotation': 0.0, 'translation': [0.0, 0.0]},
            {'id': 'g01_28', 'rotation': 90.0, 'translation': [1000.0, 500.0]},
            {'id': 'g02_28', 'rotation': 180.0, 'translation': [600.0, 100.0]},
        ]
        payload, reason = build_warm_payload(pieces, placed, **ctx)
        report(payload is not None and reason is None,
               'plain 装载成功', reason or '')
        if payload is not None:
            pid_meta, _a, _n = build_pid_meta(pieces, quantities=quantities)
            expect_width = _physical_width_mm(
                placed, _raw_polygon_map(pid_meta))
            report(payload['strip_width'] == float(expect_width),
                   'strip_width 与 _physical_width_mm 对拍',
                   f'{payload["strip_width"]} vs {expect_width}')
            report(json.loads(json.dumps(payload)) == payload,
                   'JSON 可序列化 round-trip')
            report([it['id'] for it in payload['placed_items']]
                   == ['g01_28', 'g01_28', 'g02_28'],
                   'placed_items 顺序保持（多副本 2 条在案）')

        # ---- 降级矩阵（reason 中文 + 绝不抛）
        # （mirror 条目 @tx=600：镜像后包络 [100,600] 仍有正宽度 —— 若 tx=0 会先
        # 触发 strip_width 非正降级，测不到 mirror 拒绝分支）
        expect_reason('mirror 拒绝',
                      lambda: build_warm_payload(
                          pieces, [{'id': 'g01_28', 'rotation': 0.0,
                                    'translation': [600.0, 0.0],
                                    'mirror': True}] * 2, **ctx),
                      '含镜像片，无法热启动')
        expect_reason('每 pid 条数不等于 demand（g01 demand=2 只 1 条）',
                      lambda: build_warm_payload(
                          pieces, [{'id': 'g01_28', 'rotation': 0.0,
                                    'translation': [0.0, 0.0]},
                                   {'id': 'g02_28', 'rotation': 0.0,
                                    'translation': [0.0, 0.0]}], **ctx),
                      '不是完整解')
        expect_reason('placed 空', lambda: build_warm_payload(
            pieces, [], **ctx), '初始布局为空')
        expect_reason('无母版', lambda: build_warm_payload(
            [], placed, **ctx), '请先上传母版')
        expect_reason('未知 pid（plain 宇宙）', lambda: build_warm_payload(
            pieces, [{'id': 'g99_28', 'rotation': 0.0,
                      'translation': [0.0, 0.0]}], **ctx), '需求映射外')

        # ---- 组合宇宙：demand_map 直用（不从 pid_meta 推导）+ 组合条目不计包络
        comp_demand = {'WB_g01': 1, 'g02_28': 1}
        comp_placed = [
            {'id': 'WB_g01', 'rotation': 0.0, 'translation': [700.0, 0.0]},
            {'id': 'g02_28', 'rotation': 180.0, 'translation': [600.0, 100.0]},
        ]
        payload, reason = build_warm_payload(pieces, comp_placed, **ctx,
                                             demand_map=comp_demand)
        report(payload is not None and reason is None,
               '组合 demand_map 直用装载成功', reason or '')
        if payload is not None:
            ids = [it['id'] for it in payload['placed_items']]
            report(ids == ['WB_g01', 'g02_28'],
                   '组合条目 WB_ 原样进载荷（pid_meta 投影未被采用）', str(ids))
            report(payload['strip_width'] == 600.0,
                   '组合条目不计包络（量取 g02_28 得 600，非 WB 的 tx=700）',
                   str(payload['strip_width']))

        # ---- unsupported 降级（判定序首位：脏输入同样不抛）
        warmstart.warm_start_supported = lambda: False
        expect_reason('unsupported 降级（脏 placed 同样不抛）',
                      lambda: build_warm_payload(pieces, 'garbage', **ctx),
                      '不支持热启动')
        return ok
    finally:
        warmstart.warm_start_supported = real_supported


def main(argv=None) -> int:
    """冒烟入口：``python -m materialsorting.web.initial_layout``。

    合成夹具自检（能力探测形态 / plain round-trip + strip_width 对拍 / 降级
    矩阵（mirror·条数·空·无母版·未知 pid·unsupported）/ 组合 demand_map 直用
    + 组合条目不计包络），全过打印 PASS、exit 0；无真实母版 / spyrrow solve
    依赖（能力探测临时打桩，任何装载态同一口径）。
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print('== web.initial_layout 合成夹具自检（US-001 验收口径）==')
    if not _smoke_fixtures():
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""warm-start 初始解载荷构造模块（US-001，prd-warm-start-phase1）。

sparrow lib 层 ``optimize(..., initial_solution)`` 早已存在（rev 881cdcbd
与 0.2.0 双版本核查），spyrrow-ms 私有 wheel（``0.9.0+ms1`` 起）以 pyo3
暴露 ``instance.solve(config, progress=None, initial_solution=<JSON 字符串>)``
—— 接口契约 = ``.docs/business/sparrow-ms侧需求规格_warm-start暴露_2026-09.md``
§3.2。本模块是 MS 侧**唯一的 warm 载荷构造点**：把全链路统一的 placed
列表（solver 帧 / ``best_frame_s{seed}.json`` 边车 / 编辑器同构）安全转换
为 spyrrow ``initial_solution`` JSON dict，脏数据在 Python 层 fail-fast
``ValueError``（中文消息面向用户），绝不放行进 Rust —— pyo3 把 Rust panic
转 ``PanicException``（BaseException 系），release 构建无 validate，
**Python 层校验前置是主防线**（规格 §3.1/§3.3）。

校验矩阵（全部 fail-fast ``ValueError``）：

- 载荷形态：``placed`` 非列表 / 条目非对象 / 缺 ``id``·``rotation``·
  ``translation`` 键 / 类型错（id 非字符串、rotation/translation 非数值、
  translation 非 2 元）→ 拒；
- pid 全匹配：条目 id 不在 ``demand_map`` → 拒（未知裁片）；
- **完整解硬约束**（规格 F2：sparrow ``SPProblem::restore()`` 只按 placed
  逐条扣减 demand、**不补放新片** —— exploration/compression 只有
  move/shrink 无放置调用 ⇒ 缺的片永远不会被放上）：每 pid 条数 ≠ demand
  → 拒（部分解 / 超量解同拒；demand>1 时 spyrrow 给同一 pid 发 N 条
  placed_items，同 pid N 条（N == demand）合法 —— 与既有不变量对齐）；
- **镜像片拒绝**（sparrow 姿态语言是 proper rigid，``DTransformation``
  无反射，编辑器 ``mirror: true`` 无法表达）→「含镜像片，无法热启动」。

输出契约（§3.2，jagua u64 item_id 映射不外漏，字符串 pid）::

    {"strip_width": float,                        # mm，restore 续跑起点（F3）
     "placed_items": [{"id": pid, "rotation": 度,
                       "translation": [x, y]}, ...]}

数值口径：rotation 度 / translation mm（jagua ``ExtTransformation`` 是
f32，mm 级精度 1e-4，f64→f32 收窄安全）；全部数值须**有限**（NaN/Inf
``json.dumps`` 产非法 JSON，Rust serde 直接拒）；``strip_width`` 须为正。
条目多余键白名单丢弃（输出恒三键；``mirror: False`` 是 omit-when-false
约定的显式形态，等价缺席照常放行）；placed_items **保持输入顺序**（同
warm 输入 ⇒ restore 后轨迹确定，A/B 背靠背判据的前提）。

能力探测 ``warm_start_supported()``：解析已装 ``spyrrow`` 的 PEP 440
版本串 ``+ms<N>`` local tag，**N ≥ 1 才 True** —— 纯重建 wheel
``0.9.0+ms0`` 无 ``initial_solution`` 参数，不算支持（2026-09-19 联调前
实勘：ms0 已装入 .venv，纯 ``'+ms'`` 子串判定会误报 True 致 worker 层
硬 ``TypeError``，此为对原 PRD AC 的修订）；PyPI ``0.9.0`` / 包缺失 /
版本串异常 → False，**任何异常都不抛**。

二期（2026-09-19，band/prefix warm 解禁）新增 ``payload_universe_error``：
worker 在 ``build_instance`` 后把载荷 pid 宇宙与本进程重建实例复检（错位 →
丢弃降级普通重放，防 release 无 validate 下 Rust 侧静默错乱）—— 见其
docstring。

分层约束：本模块属 ``nesting_engine``，仅 import 标准库（无
spyrrow/shapely 运行时依赖，冒烟合成夹具即可跑）；**禁 import web/cli**
（AST 守卫在 tests/test_warmstart.py，对齐 tests/test_polish.py 先例）。
"""
from __future__ import annotations

import importlib.metadata
import json
import math
import re
import sys
from collections import Counter

# spyrrow 私有 wheel local tag（PEP 440 ``+ms<N>``；跨项目契约勿改 ——
# spyrrow-ms 侧规格 §2.3）。要求 N ≥ 1：ms0 是行为全等对拍用的纯重建
# wheel，尚无 initial_solution 参数。
_LOCAL_TAG_RE = re.compile(r'\+ms(\d+)')

# placed 条目必填三键（与 solver 帧 / best_frame 边车 / 编辑器同构）。
_REQUIRED_KEYS = ('id', 'rotation', 'translation')


def _finite_num(value, where: str) -> float:
    """数值守卫：int/float（拒 bool）/ 有限 → 归一 float。

    bool 是 int 子类（``isinstance(True, int)`` 为 True），JSON 里
    rotation/translation 填 true/false 属脏数据，显式拒；NaN/Inf 过不了
    Rust serde 的 JSON 解析，Python 层前置拒并给人话消息。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{where} 应为数值，实得 {type(value).__name__} 类型')
    fv = float(value)
    if not math.isfinite(fv):
        raise ValueError(f'{where} 应为有限数值，实得 {value!r}')
    return fv


def build_initial_solution(placed, demand_map, strip_width_mm) -> dict:
    """placed 列表 → spyrrow ``initial_solution`` JSON dict（契约 §3.2）。

    Parameters
    ----------
    placed : list[dict]
        全链路统一格式条目 ``{id, rotation(度), translation:[x,y]}``
        （solver 帧 / ``best_frame_s{seed}.json`` 边车 / 编辑器同构；
        ``mirror: true`` 条目拒绝 —— sparrow 无反射姿态）。
    demand_map : dict[str, int]
        ``{pid: demand}``（pid_meta 的 demand 投影）；每 pid 条数必须
        **恰好等于** demand（完整解硬约束 F2）。
    strip_width_mm : float
        冠军帧用布长度（mm，restore 续跑起点 F3），须为正有限数。

    Returns
    -------
    dict
        ``{"strip_width": float, "placed_items": [{id, rotation,
        translation}]}`` —— 纯 JSON dict（Windows spawn pickle 安全），
        ``json.dumps`` 由 worker 最终消费点做（FR-7）。

    Raises
    ------
    ValueError
        校验矩阵任一命中（中文消息面向用户，fail-fast 不进 Rust）。
    """
    if not isinstance(placed, list):
        raise ValueError(f'初始布局应为列表，实得 {type(placed).__name__} 类型')
    if not isinstance(demand_map, dict):
        raise ValueError(f'需求映射应为字典，实得 {type(demand_map).__name__} 类型')
    for pid, demand in demand_map.items():
        if isinstance(demand, bool) or not isinstance(demand, int) or demand < 1:
            raise ValueError(f'需求映射非法：{pid!r} 的 demand 应为正整数，'
                             f'实得 {demand!r}')
    width = _finite_num(strip_width_mm, '用布长度 strip_width_mm')
    if width <= 0.0:
        raise ValueError(f'用布长度 strip_width_mm 应为正数，实得 {width!r}')

    counts: Counter[str] = Counter()
    items = []
    for i, entry in enumerate(placed):
        if not isinstance(entry, dict):
            raise ValueError(f'初始布局第 {i} 条应为对象，'
                             f'实得 {type(entry).__name__} 类型')
        missing = [k for k in _REQUIRED_KEYS if k not in entry]
        if missing:
            raise ValueError(f'初始布局第 {i} 条缺少字段：{"、".join(missing)}')
        pid = entry['id']
        if not isinstance(pid, str):
            raise ValueError(f'初始布局第 {i} 条 id 应为字符串，'
                             f'实得 {type(pid).__name__} 类型')
        if pid not in demand_map:
            raise ValueError(f'初始布局第 {i} 条含未知裁片 id：{pid!r}'
                             '（不在需求映射内）')
        rotation = _finite_num(entry['rotation'], f'初始布局第 {i} 条 rotation')
        tr = entry['translation']
        if isinstance(tr, (str, bytes)) or not isinstance(tr, (list, tuple)):
            raise ValueError(f'初始布局第 {i} 条 translation 应为 [x, y] '
                             f'两个数值，实得 {type(tr).__name__} 类型')
        if len(tr) != 2:
            raise ValueError(f'初始布局第 {i} 条 translation 应为 2 元 '
                             f'[x, y]，实得 {len(tr)} 元')
        tx = _finite_num(tr[0], f'初始布局第 {i} 条 translation[0]')
        ty = _finite_num(tr[1], f'初始布局第 {i} 条 translation[1]')
        if entry.get('mirror'):
            raise ValueError(f'初始布局第 {i} 条（{pid!r}）含镜像片，'
                             '无法热启动（sparrow 姿态不含反射，请先取消镜像）')
        counts[pid] += 1
        items.append({'id': pid, 'rotation': rotation,
                      'translation': [tx, ty]})

    for pid, demand in demand_map.items():
        n = counts.get(pid, 0)
        if n != demand:
            raise ValueError(f'初始布局不是完整解：裁片 {pid!r} 条数 {n} ≠ '
                             f'需求 {demand}（sparrow restore 不补放新片，'
                             '热启动必须每片恰好放满）')

    return {'strip_width': width, 'placed_items': items}


def warm_start_supported() -> bool:
    """当前环境 spyrrow 是否支持 ``initial_solution``（探测恒不抛）。

    判据 = ``importlib.metadata.version('spyrrow')`` 解析出 ``+ms<N>``
    local tag 且 N ≥ 1（私有 wheel 语义版本）；包不存在 / 版本串无 tag /
    ``+ms0``（纯重建 wheel，无 initial_solution 参数）/ 任何异常 → False。
    """
    try:
        version = importlib.metadata.version('spyrrow')
    except Exception:
        return False
    m = _LOCAL_TAG_RE.search(str(version))
    return bool(m) and int(m.group(1)) >= 1


def payload_universe_error(payload, demand_map) -> str | None:
    """warm 载荷 pid 宇宙复检（二期 2026-09-19 band/prefix 解禁，worker 侧末道防线）。

    ``solve_worker`` 在 ``build_instance`` 之后调用：载荷的 pid 宇宙须与**本进程
    重建实例**的 ``{item.id: demand}`` 逐 pid 恰好一致（未知 pid / 缺片 / 超量
    皆不匹配）。设计动机：sparrow lib 层 restore 只按 placed 扣减 demand、不
    补放新片，而 ms1 release 构建无 validate（§3.1）—— 载荷与实例错位若不在
    Python 层拦下，Rust 侧静默错乱。band/prefix 场景下主进程装载点用的是**边车
    记录的组合视角 demand_map**（筛选轮实例），延长轮 worker 重建的组合片实例
    理论上逐字节一致（构造无 RNG）；本复检兜住任何漂移（如确定性破坏 / 手改
    边车），不匹配 → 调用方丢弃载荷降级普通重放。

    与 ``build_initial_solution`` 的关系：校验口径同源（完整解硬约束 / 未知
    pid / strip_width 正有限），但不重建载荷、不抛 —— 复检用，返回中文错误
    描述（含定位信息）或 ``None``（一致）。载荷形态非法也返回描述（worker 统一
    降级，绝不因复检炸轮）。
    """
    try:
        width = float(payload['strip_width'])
        placed = payload['placed_items']
    except (KeyError, TypeError):
        return '载荷形态非法（缺 strip_width / placed_items）'
    if not math.isfinite(width) or width <= 0.0:
        return f'载荷 strip_width 非正有限数: {width!r}'
    if not isinstance(placed, list):
        return f'载荷 placed_items 应为列表，实得 {type(placed).__name__} 类型'
    counts: Counter[str] = Counter()
    for i, entry in enumerate(placed):
        try:
            pid = entry['id']
        except (KeyError, TypeError):
            return f'载荷第 {i} 条缺 id 或非对象'
        if not isinstance(pid, str):
            return f'载荷第 {i} 条 id 应为字符串，实得 {type(pid).__name__} 类型'
        counts[pid] += 1
    for pid, demand in demand_map.items():
        n = counts.pop(pid, 0)
        if n != int(demand):
            return (f'载荷与实例不匹配：{pid!r} 条数 {n} ≠ 实例 demand '
                    f'{int(demand)}')
    if counts:
        pids = ', '.join(sorted(counts))
        return f'载荷含实例外裁片 id：{pids}'
    return None


# --------------------------------------------------------------- 冒烟自检

def _smoke_entry(pid, rot=0.0, tr=(0.0, 0.0), mirror=None):
    it = {'id': pid, 'rotation': rot, 'translation': list(tr)}
    if mirror is not None:
        it['mirror'] = mirror
    return it


def _smoke_fixtures() -> bool:
    """合成夹具自检（US-001 验收口径，无 spyrrow/intermediate 依赖）。"""
    ok = True

    def report(passed: bool, name: str, detail: str = '') -> None:
        nonlocal ok
        if not passed:
            ok = False
        line = f'  {"ok" if passed else "FAIL"}  {name}'
        if detail:
            line += f'：{detail}'
        print(line)

    def expect_pass(name, fn):
        try:
            result = fn()
        except Exception as e:             # noqa: BLE001 冒烟只报不炸
            report(False, name, f'不应抛 {type(e).__name__}: {e}')
            return None
        report(True, name)
        return result

    def expect_reject(name, fn, needle=None):
        try:
            fn()
        except ValueError as e:
            msg = str(e)
            report(needle is None or needle in msg, name, msg)
        except Exception as e:             # noqa: BLE001 冒烟只报不炸
            report(False, name, f'异常类型错 {type(e).__name__}: {e}')
        else:
            report(False, name, '未拒绝')

    demand = {'g01_28': 2, 'g02_30': 1}
    placed_ok = [
        {'id': 'g02_30', 'rotation': 180, 'translation': [120.5, 0]},
        {'id': 'g01_28', 'rotation': 0.0, 'translation': [0, 0],
         'mirror': False, 'source': 'editor'},          # 多余键白名单丢弃
        {'id': 'g01_28', 'rotation': 90, 'translation': [10, 300.25]},
    ]
    built = expect_pass('合法构造（多副本 + 乱序 + 多余键丢弃）',
                        lambda: build_initial_solution(
                            placed_ok, demand, 1500))
    if built is not None:
        expect = {
            'strip_width': 1500.0,
            'placed_items': [
                {'id': 'g02_30', 'rotation': 180.0,
                 'translation': [120.5, 0.0]},
                {'id': 'g01_28', 'rotation': 0.0,
                 'translation': [0.0, 0.0]},
                {'id': 'g01_28', 'rotation': 90.0,
                 'translation': [10.0, 300.25]},
            ],
        }
        if built != expect:
            report(False, '结构对拍', json.dumps(built, ensure_ascii=False))
        expect_pass('JSON 可序列化 round-trip',
                    lambda: json.loads(json.dumps(built)) == built)

    expect_pass('空解（demand 空 + placed 空）',
                lambda: build_initial_solution([], {}, 800.0))

    expect_reject('部分解（g01_28 只 1 条 demand=2）',
                  lambda: build_initial_solution(
                      [placed_ok[1]], demand, 1500), '不是完整解')
    expect_reject('超量解（g01_28 3 条 demand=2）',
                  lambda: build_initial_solution(
                      placed_ok + [dict(placed_ok[2])], demand, 1500),
                  '不是完整解')
    expect_reject('未知 pid',
                  lambda: build_initial_solution(
                      [_smoke_entry('g99_28')], {'g01_28': 1}, 1500),
                  '未知裁片')
    expect_reject('mirror 拒绝',
                  lambda: build_initial_solution(
                      [_smoke_entry('g01_28', mirror=True)],
                      {'g01_28': 1}, 1500), '含镜像片，无法热启动')

    expect_reject('placed 非列表', lambda: build_initial_solution(
        {'id': 'g01_28'}, {'g01_28': 1}, 1500))
    expect_reject('条目非对象', lambda: build_initial_solution(
        ['g01_28'], {'g01_28': 1}, 1500))
    expect_reject('缺键', lambda: build_initial_solution(
        [{'id': 'g01_28', 'rotation': 0}], {'g01_28': 1}, 1500), '缺少字段')
    expect_reject('id 非字符串', lambda: build_initial_solution(
        [_smoke_entry(1)], {'g01_28': 1}, 1500))
    expect_reject('rotation 非数值', lambda: build_initial_solution(
        [_smoke_entry('g01_28', rot='0')], {'g01_28': 1}, 1500))
    expect_reject('rotation 布尔', lambda: build_initial_solution(
        [_smoke_entry('g01_28', rot=True)], {'g01_28': 1}, 1500))
    expect_reject('rotation NaN', lambda: build_initial_solution(
        [_smoke_entry('g01_28', rot=float('nan'))], {'g01_28': 1}, 1500))
    expect_reject('translation 非 2 元', lambda: build_initial_solution(
        [_smoke_entry('g01_28', tr=[1, 2, 3])], {'g01_28': 1}, 1500))
    expect_reject('translation 元素非数值', lambda: build_initial_solution(
        [_smoke_entry('g01_28', tr=[1, 'y'])], {'g01_28': 1}, 1500))
    expect_reject('demand_map 非字典', lambda: build_initial_solution(
        [_smoke_entry('g01_28')], ['g01_28'], 1500))
    expect_reject('demand 非正整数', lambda: build_initial_solution(
        [_smoke_entry('g01_28')], {'g01_28': 0}, 1500))
    expect_reject('strip_width 非数值', lambda: build_initial_solution(
        [_smoke_entry('g01_28')], {'g01_28': 1}, '1500'))
    expect_reject('strip_width 非正', lambda: build_initial_solution(
        [_smoke_entry('g01_28')], {'g01_28': 1}, 0))

    # 能力探测：当前态只验证「不抛 + bool」，装载态（PyPI/ms0/ms1）由
    # tests/test_warmstart.py 的 monkeypatch 多态矩阵锁定。
    supported = expect_pass('warm_start_supported() 探测不抛',
                            warm_start_supported)
    try:
        version = importlib.metadata.version('spyrrow')
    except Exception:                      # noqa: BLE001 探测恒不抛同款
        version = '(未安装)'
    print(f'  --  当前装载：spyrrow {version}，warm_start_supported='
          f'{supported}')
    if not isinstance(supported, bool):
        ok = False

    # 二期宇宙复检（worker 侧防御）：一致 → None；错位/畸形 → 中文描述不抛。
    good = {'strip_width': 900.0,
            'placed_items': [_smoke_entry('g01_28'), _smoke_entry('g02_30')]}
    if expect_pass('宇宙一致 → None',
                   lambda: payload_universe_error(good,
                                                  {'g01_28': 1, 'g02_30': 1})
                   ) is not None:
        report(False, '宇宙一致应返回 None')
    desc = payload_universe_error(good, {'WB_g05': 1, 'g02_30': 1})
    report(desc is not None and 'WB_g05' in desc, '宇宙错位 → 描述含缺片 pid',
           desc or '（未检出）')
    desc2 = payload_universe_error({}, {'g01_28': 1})
    report(desc2 is not None, '载荷形态非法 → 描述不抛', desc2 or '（未检出）')
    return ok


def main(argv=None) -> int:
    """冒烟入口：``python -m materialsorting.nesting_engine.warmstart``。

    合成夹具自检（合法 round-trip / 多副本 / 部分与超量解 / 未知 pid /
    mirror 拒绝 / 畸形矩阵 / 能力探测不抛 / 二期宇宙复检三态），全过打印
    PASS、exit 0；无 spyrrow/shapely/intermediate 依赖。
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print('== warmstart 合成夹具自检（US-001 验收口径）==')
    if not _smoke_fixtures():
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

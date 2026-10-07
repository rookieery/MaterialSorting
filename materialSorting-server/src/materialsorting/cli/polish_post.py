"""自动智能微调后处理（2026-10-07）—— ``ms-run-config --polish`` 的实现体。

对 run_dir 最优布局（portfolio.incumbent 优先，旧式 best 的 int 计数回退
``best_frame_s{seed}.json`` 边车 —— 与 ``lns.postprocess_run_dir`` 同款源解析）
跑一遍编辑弹窗同款 ``nesting_engine.polish.polish_layout``
（``max_rounds=POLISH_ROUNDS_MAX`` 迭代至不动点，确定性纯函数）。

**严格更优（物理口径 real_density）才回写**（LNS 同款门槛）：改进 → 调用方把
incumbent 的 density/width_mm/placed_items 三字段就地更新 + result.json 落
``polish`` 段；不优 → result.json 布局逐字节不变（段仍记 ``improved:false``）。
明细恒写 ``result_polish.json``（含改进布局，legacy 无 incumbent 回写路径时不
丢失）。

exclude 口径（band/prefix 刚性组保护）：**label 级保守排除** —— result.json
config 回显的 band label + prefix front/back label。CLI 侧 incumbent 是帧级布局
（展开成员形态，无 final.prefix 成员明细可解析），label 级 over-conservative
安全（与编辑弹窗 exclude「同 label 全部副本」的 v1 口径一致；prefix 异码补片
属异 label 不冻结，微调守卫保证其仍合法贴触）。band/prefix 开启**不跳过**
微调 —— 区别于 LNS 波段重排会拆带形态整段跳过：polish 是贴附级微调 +
exclude 冻结，与编辑弹窗可对带开启布局微调同款。

失败语义（调用方 run_config 裁决）：输入缺失 / 无布局 / 引擎异常抛
``PolishError`` / ``OSError`` / ``json.JSONDecodeError`` / ``ValueError`` ——
后处理失败不否定已完成的求解交付物（warn 跳过，退出码 0，LNS 同模式）。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from ..nesting_engine.polish import POLISH_ROUNDS_MAX, polish_layout


def _layout_source(doc: dict, run_dir: Path | None = None) -> dict:
    """result.json → 最优布局来源记录（``lns._incumbent`` 同款解析，独立轻量
    复制避免跨模块私有依赖）：portfolio.incumbent 优先（placed_items 完整布局），
    旧式 best 的 int 计数回退 ``best_frame_s{seed}.json`` 边车。"""
    inc = (doc.get('portfolio') or {}).get('incumbent') or doc.get('best') or {}
    if isinstance(inc.get('placed_items'), list) and inc['placed_items']:
        return inc
    if run_dir is not None and isinstance(inc.get('seed'), (int, float)):
        side = Path(run_dir) / ('best_frame_s%d.json' % int(inc['seed']))
        if side.is_file():
            try:
                frame = json.loads(side.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                frame = {}
            if isinstance(frame.get('placed_items'), list) and frame['placed_items']:
                return frame
    raise ValueError('result.json 无 incumbent/best placed_items（尚无求解产物）')


def _physical_width(placed: list[dict], pid_raw: dict) -> float | None:
    """物理毛版包络料长 —— ``web.solver._physical_width_mm`` 同式镜像（ceil − 1e-9
    抵浮点噪声；x=0 布头，左侧外凸不计）。任一 pid 缺席 → None（调用方跳过
    密度重算，保守不回写）。"""
    max_x = 0.0
    for it in placed:
        poly = pid_raw.get(it.get('id'))
        if not poly:
            return None
        r = math.radians(float(it.get('rotation', 0.0) or 0.0))
        c, s = math.cos(r), math.sin(r)
        tr = it.get('translation') or (0.0, 0.0)
        tx, ty = float(tr[0]), float(tr[1])
        mirror = it.get('mirror') is True
        for pt in poly:
            x = -pt[0] if mirror else pt[0]
            wx = x * c - pt[1] * s + tx
            if wx > max_x:
                max_x = wx
    return math.ceil(max_x - 1e-9)


def polish_run_result(run_dir, *, echo=None) -> dict:
    """run_dir 最优布局自动微调（读 result.json + intermediate，明细写
    ``result_polish.json``）。

    Returns
    -------
    dict
        ``{'improved', 'before', 'after', 'delta', 'rounds', 'moves',
        'attach_moves', 'excluded_pieces', 'elapsed_sec', 'placed_items',
        'seed'}`` —— ``improved`` = 引擎有 move 且物理口径 real_density 严格
        更优（**回写门槛**）；``placed_items`` 仅 improved 时为新布局（不优 =
        输入布局原对象）。前后密度 = 物理毛版包络口径（分子 Σ(area×副本数)，
        与 result.json best 同 90% 生死线口径）。
    """
    run_dir = Path(run_dir)
    doc = json.loads((run_dir / 'result.json').read_text(encoding='utf-8'))
    inter = json.loads((run_dir / 'pieces_intermediate.json')
                       .read_text(encoding='utf-8'))
    src = _layout_source(doc, run_dir)
    placed_in = src['placed_items']
    pieces = inter['pieces']
    gate_mm = float(inter['gate_mm'])
    pieces_by_id = {p['pid']: p for p in pieces}

    # exclude：label 级保守排除（config 回显单一数据源；band/prefix 关 → 空表
    # = 载荷省略 exclude 键，与引擎 None 语义一致）。
    cfg = doc.get('config') or {}
    labels = []
    band = cfg.get('band') or {}
    if isinstance(band.get('label'), str):
        labels.append(band['label'])
    prefix = cfg.get('prefix') or {}
    for key in ('front', 'back'):
        if isinstance(prefix.get(key), str):
            labels.append(prefix[key])
    exclude = {'labels': labels} if labels else None

    pid_raw = {p['pid']: p.get('polygon') for p in pieces if p.get('polygon')}
    placed_new, report = polish_layout(
        placed_in, pieces_by_id, gate_mm,
        exclude=exclude, max_rounds=POLISH_ROUNDS_MAX)

    def _density(placed: list[dict]) -> float | None:
        w = _physical_width(placed, pid_raw)
        if not w or w <= 0:
            return None
        total_area = 0.0
        for it in placed:
            piece = pieces_by_id[it['id']]
            area = piece.get('area_mm2')
            if not area:
                from shapely.geometry import Polygon
                area = Polygon(piece['polygon']).area
            total_area += float(area)
        return total_area / (w * gate_mm)

    moved = placed_new is not placed_in and bool(report.get('moves'))
    d_before = _density(placed_in)
    d_after = _density(placed_new) if moved else d_before
    improved = bool(moved and d_before is not None and d_after is not None
                    and d_after > d_before)

    def _summary(placed, density):
        w = _physical_width(placed, pid_raw)
        return {'density': round(density, 6) if density is not None else None,
                'width_mm': (round(float(w), 2) if w is not None else None),
                'n_placed': len(placed)}

    out = {
        'improved': improved,
        'before': _summary(placed_in, d_before),
        'after': _summary(placed_new if moved else placed_in, d_after),
        'rounds': report.get('rounds', 1),
        'moves': len(report.get('moves') or []),
        'attach_moves': report.get('attach_moves', 0),
        'excluded_pieces': len(report.get('excluded') or []),
        'elapsed_sec': report.get('elapsed_sec'),
        'source': {'result': 'result.json',
                   'intermediate': 'pieces_intermediate.json',
                   'seed': src.get('seed'),
                   'exclude_labels': labels},
        # placed_items 仅 improved 时携带（回写用；不优省体积 —— 明细文件同口径）。
        **({'placed_items': placed_new} if improved else {}),
    }
    if d_before is not None and d_after is not None:
        out['delta'] = {'density_pt': round((d_after - d_before) * 100.0, 4)}
    with open(run_dir / 'result_polish.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    if echo is not None:
        echo(f"[polish] 微调完成: improved={improved} "
             f"moves={out['moves']} rounds={out['rounds']} "
             f"({out['elapsed_sec']:.2f}s)")
    return out

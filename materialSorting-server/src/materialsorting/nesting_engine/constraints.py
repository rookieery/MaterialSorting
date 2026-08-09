"""阶段 1c-3：v0.3 约束层。

- 重合公差：内部裁片位图按 v0.3 max_overlap 向内腐蚀，排料时允许重合（利用率杠杆，
  非降约束）。外部裁片 max_overlap 0.4-2mm，RES=2 下腐蚀 0-1 像素（≈相切排）。
- 镜像配对校验：成对类 L/R 数量应 1:1。
- 旋转公差/布纹线/门幅：声明 + 校验。旋转公差（外部锁 {0,180}，内部允许多姿态）
  在排料侧由 allowed_angles 体现；多姿态搜索是后续利用率提升点。
"""
from __future__ import annotations

from collections import Counter

import numpy as np

# v0.3 §4 各片最大重合深度（mm，沿接触边法线）
MAX_OVERLAP = {
    '前片': 2.0, '后片': 2.0, '腰': 0.4, '前袋': 0.4, '后袋': 0.4, '机头': 0.4,
    '单排': 10.0, '双排': 10.0, '火机袋': 5.0, '裤耳': 10.0,
}
# v0.3 §3 各片旋转公差（度，基准 {0°,180°} 上的 ±）
ROTATION_TOL = {
    '前片': 1, '后片': 1, '腰': 3, '前袋': 30, '后袋': 1, '机头': 3,
    '单排': 15, '双排': 15, '火机袋': 8, '裤耳': 45,
}
PAIR_TYPES = {'前片', '后片', '腰', '前袋', '后袋', '机头'}   # v0.3 成对类


def erode_bitmap(bm: np.ndarray, d_pix: int) -> np.ndarray:
    """位图向内腐蚀 d_pix 像素（4 邻域迭代形态学腐蚀）。d_pix<=0 原样返回。

    腐蚀后该片排料时可与邻片重叠 d_pix 像素（= d_pix×res mm），即 v0.3 的重合公差。
    """
    if d_pix <= 0:
        return bm
    b = bm.copy()
    for _ in range(d_pix):
        up = np.zeros_like(b); up[:-1, :] = b[1:, :]
        dn = np.zeros_like(b); dn[1:, :] = b[:-1, :]
        lf = np.zeros_like(b); lf[:, :-1] = b[:, 1:]
        rt = np.zeros_like(b); rt[:, 1:] = b[:, :-1]
        b = b & up & dn & lf & rt
    return b


def overlap_dpix(ptype: str, res: float) -> int:
    """该片位图腐蚀像素数 = max_overlap / res。"""
    return int(MAX_OVERLAP.get(ptype, 0.0) / res)


def validate(placed_world, pieces, used, gate, res):
    """排料合法性校验。返回 (ok, issues)。"""
    issues = []
    placed_pieces = [p for p, _ in placed_world]

    # 1. 数量
    if len(placed_world) != len(pieces):
        issues.append(f'片数不符: 排{len(placed_world)} vs 输入{len(pieces)}')

    # 2. 镜像配对：成对类每 (类型,码) 的 L 与 R 应各 1
    pair_cnt = Counter((p.ptype, p.size, p.side) for p in placed_pieces if p.ptype in PAIR_TYPES)
    seen = set()
    for (t, s, side), n in pair_cnt.items():
        if n != 1:
            issues.append(f'镜像异常: {(t, s, side)} 出现 {n} 次')
        seen.add((t, s))
    # 输入里成对类每 (类型,码) 应有 L+R，排料也应有
    in_pairs = Counter((p.ptype, p.size, p.side) for p in pieces if p.ptype in PAIR_TYPES)
    for k, n in in_pairs.items():
        if pair_cnt.get(k, 0) != n:
            issues.append(f'镜像缺失: {k} 输入{n} 排{pair_cnt.get(k,0)}')
            break

    # 3. 门幅：所有片 x ∈ [0, gate]
    for piece, poly in placed_world:
        xs = [x for x, _ in poly]
        if min(xs) < -1.0 or max(xs) > gate + 1.0:
            issues.append(f'{piece.pid} 超门幅 [{min(xs):.0f},{max(xs):.0f}]')
            break

    # 4. 用布长度正向
    if used <= 0:
        issues.append('用布长度非正')

    return (len(issues) == 0), issues

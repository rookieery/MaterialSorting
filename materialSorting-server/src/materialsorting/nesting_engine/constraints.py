"""阶段 1c-3：v0.3 约束层。

- 重合公差：裁片位图按申请 d 向内腐蚀，排料时允许重合（利用率杠杆，非降约束）。
- 旋转公差/布纹线/门幅：声明 + 校验。旋转公差（外部锁 {0,180}，内部允许多姿态）
  在排料侧由 allowed_angles 体现；多姿态搜索是后续利用率提升点。

2026-08-17 起：重合/旋转上限改为**全局**口径（与高级配置弹窗一致），不再按片型钳制 ——
版师确认的每片型工艺上限（外部 0.4~2mm / 前袋旋转 30° 等）保留在
``.docs/business/排料规则_详细版.md`` §3.2/§4 作参考，由用户在 UI 按片型显式填值控制，
默认 0（不重合/锁布纹线）。

2026-08-18（US-002）：删 ``PAIR_TYPES`` 与成对齐套校验（L 数=R 数）—— 该校验服务于
已删除的合成镜像模型（引擎不再按名称集合做任何行为判断，数量一律由 demand 表达），
名称常量随之整体退场。
"""
from __future__ import annotations

import numpy as np

# 全局最大重合深度（mm，沿接触边法线）。UI 高级配置弹窗重合输入 max 同值。
MAX_OVERLAP_MM = 10.0
# 全局最大旋转公差（°，基准 {0°,180°} 上的 ±）。UI 高级配置弹窗旋转输入 max 同值。
MAX_ROTATION_TOL_DEG = 45.0


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


def validate(placed_world, pieces, used, gate, res):
    """排料合法性校验。返回 (ok, issues)。"""
    issues = []

    # 1. 数量
    if len(placed_world) != len(pieces):
        issues.append(f'片数不符: 排{len(placed_world)} vs 输入{len(pieces)}')

    # 2. 门幅：所有片 x ∈ [0, gate]
    for piece, poly in placed_world:
        xs = [x for x, _ in poly]
        if min(xs) < -1.0 or max(xs) > gate + 1.0:
            issues.append(f'{piece.pid} 超门幅 [{min(xs):.0f},{max(xs):.0f}]')
            break

    # 3. 用布长度正向
    if used <= 0:
        issues.append('用布长度非正')

    return (len(issues) == 0), issues

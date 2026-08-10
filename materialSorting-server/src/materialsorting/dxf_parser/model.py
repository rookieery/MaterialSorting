"""裁片几何 IR。

第一阶段为"数据探索"服务：忠实记录每条 layer1 毛版外轮廓 + 结构信息 + 度量，
不做语义类型识别（piece_type 故意不加，留给独立识别程序）。

US-002 起新增三字段承载母版深度解析所需细节（内部线/刀口/净版），均
`field(default_factory=list)` 默认空 list，既有调用方（pieces_export、
sparrow_baseline、explore.collect_pieces）零改动可用；US-003
`collect_pieces_with_details()` 负责填充。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field


@dataclass
class PieceOutline:
    source_file: str                                            # 母版文件名
    block_name_raw: str                                         # block 原始名（未经解码）
    block_name: str                                             # GBK 解码后块名
    size: int | None                                            # 码号（块名末尾数字；提取失败为 None）
    piece_index: int                                            # 该 block 内第几条 layer1（0-based）
    group_key: str                                              # 分组键 = 去码号block名 + "#" + piece_index
    polygon_mm: list[tuple[float, float]]                       # layer1 毛版外轮廓顶点(mm)，原样保留
    is_closed: bool                                             # POLYLINE 闭合标志
    vertex_count: int                                           # 顶点数（应 == len(polygon_mm)）
    perimeter_mm: float                                         # 闭合多边形周长(mm)
    area_mm2: float                                             # 多边形面积(mm²，shoelace 绝对值)
    bbox_mm: tuple[float, float, float, float]                  # (minx, miny, maxx, maxy)
    grain_line: tuple[float, float, float, float] | None        # 配对到的布纹线起止(x1,y1,x2,y2)；无则 None
    grain_angle_deg: float | None                               # 布纹线与水平夹角(度)；无则 None
    grain_orientation: str                                      # 'horizontal' | 'vertical' | 'unknown'，排料统一水平时的旋转依据
    # US-002：深度解析字段（layer8/layer4/layer14），默认空 list 向后兼容
    internal_lines: list = field(default_factory=list)          # layer8 POLYLINE 内部线 [[(x,y),...], ...]，每条一组顶点
    notches: list = field(default_factory=list)                 # layer4 POINT 刀口 [(x,y,nx,ny), ...] = 点 + 单位法向量
    net_polygon: list = field(default_factory=list)             # layer14 POLYLINE 净版轮廓 [(x,y), ...]；无则空

    def to_dict(self) -> dict:
        return asdict(self)

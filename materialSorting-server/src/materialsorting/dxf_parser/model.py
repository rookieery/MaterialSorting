"""裁片几何 IR。

第一阶段为"数据探索"服务：忠实记录每条 layer1 毛版外轮廓 + 结构信息 + 度量，
不做语义类型识别（piece_type 故意不加，留给独立识别程序）。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


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

    def to_dict(self) -> dict:
        return asdict(self)

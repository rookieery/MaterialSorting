"""DXF 底层读取。

扛住三个母版坑：
1. ezdxf.recover.readfile 返回 (doc, errors) 元组，需正确解包；
2. $DWGCODEPAGE 标为 ANSI_1252，块名实际是 GBK；
3. $INSUNITS 不可信（实测标 6），统一按 mm 解释。

只读 R12 POLYLINE（顶点在 .vertices）+ LINE，不依赖 LWPOLYLINE/SPLINE/ARC。
"""
from __future__ import annotations

import re

import ezdxf


def decode_str(s: str) -> str:
    """GBK 解码块名/文字（母版 $DWGCODEPAGE 误标 ANSI_1252，实际 GBK）；失败回退原值。"""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("gbk")
    except Exception:
        return s


def load_doc(path: str):
    """读取 DXF：优先 recover（能救损坏文件），失败回退普通 readfile。正确解包元组。"""
    try:
        result = ezdxf.recover.readfile(path)
        if isinstance(result, tuple):
            return result[0]
        return result
    except Exception:
        return ezdxf.readfile(path)


# 只取末尾的 ".<数字>" 或 "_<数字>" 作为码号，避开 "M1787#28-32小33-38大码" 中的数字段
_SIZE_RE = re.compile(r"[._](\d+)$")


def parse_size(block_name: str) -> int | None:
    """从 block 名末尾提取码号；提取失败返回 None。"""
    m = _SIZE_RE.search(block_name)
    return int(m.group(1)) if m else None


def strip_size(block_name: str) -> str:
    """去掉 block 名末尾码号，用于分组键的"类型"部分。"""
    return _SIZE_RE.sub("", block_name)


def polyline_points(entity) -> list[tuple[float, float]] | None:
    """从 R12 POLYLINE 取顶点 [(x, y), ...]，原样保留（不抽稀、不平滑）。非 POLYLINE 返回 None。"""
    if entity.dxftype() != "POLYLINE":
        return None
    return [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]


def is_polyline_closed(entity) -> bool:
    """POLYLINE 闭合标志。优先用 ezdxf 属性，回退 flags 位。"""
    try:
        if getattr(entity, "is_closed", None) is not None:
            return bool(entity.is_closed)
    except Exception:
        pass
    try:
        return bool(entity.dxf.flags & 1)  # POLYLINE_CLOSED = 1
    except Exception:
        return False


def iter_block_entities(block, layers: set[str] | None = None):
    """按可选 layer 白名单迭代 block 内实体。

    US-002：为母版深度解析（US-003 collect_pieces_with_details）提供
    统一的实体提取入口。`layers` 为 None 时返回全部实体（与原
    `for e in block` 等价）；指定白名单时仅 yield `str(e.dxf.layer)`
    命中的实体。layer 字符串比较与现有 collect_pieces 的
    `str(e.dxf.layer) == "1"` 同口径。

    Args:
        block: ezdxf Block 对象（可迭代 yield 实体）。
        layers: 可选 layer 名白名单（如 {"1", "7", "8", "14"}）。

    Yields:
        block 内命中的实体（POLYLINE/LINE/POINT/...）。
    """
    for e in block:
        if layers is None:
            yield e
            continue
        try:
            layer = str(e.dxf.layer)
        except Exception:
            layer = ""
        if layer in layers:
            yield e

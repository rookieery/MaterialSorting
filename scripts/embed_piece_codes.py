# -*- coding: utf-8 -*-
"""把 g01+ 裁片编号植入母版 DXF，生成带编号的新母版（原文件不动）。

背景：g 码编号的单一真相源是 ``nesting_engine.labeling.assign_codes``（Web parse /
commit 同源），但编号此前只出现在排料产物（PNG / marker DXF 逐片叠印），母版本身
不带编号 —— 版师在 ET2008 打开母版时无法把图面上的片与系统里的 g 码对上。本脚本
补上这一环：对母版每片裁片（每条 layer1 POLYLINE，同 ``collect_pieces_with_details``
口径）在其 block 内写一个 TEXT 实体（独立 layer 'TEXT'，不碰裁切层 1 / 工艺层
14/8/4/7 / 参考点层 2），编号与 Web 上传预览**逐片一致**（同 collect + 同
``assign_codes``）。文本格式同 marker 导出口径：``g03-30``（g 码-码号；size=None
只印 g 码），纯 ASCII 无字库坑。

为什么写进 block 定义而不是 modelspace：解析与编号全部按 block-local 几何走
（身份键 ``(block_name, size, piece_index)``），modelspace 的 INSERT 只是摆放引用；
TEXT 放 block 内随每个 INSERT 副本显示，且不改变 block 内 layer1 计数与枚举序
（piece_index 不受影响 → 重解析同码）。TEXT 层不在 collect 的提取白名单
（layer 1/14/8/4/7）内，对解析管线不可见。

定位：顶点质心（与 PNG / marker DXF 叠印同口径，``labeling.centroid``）；凹片
（L 形前/后片）质心可能落片外，回退到 bbox 中线扫描「最宽内条带中点」（必在
片内，编号不悬空）。

幂等：写前先清掉输出文档里 TEXT 层的既有实体（仅本脚本产物层），重复跑不叠字。

自校验：输出文件重新 collect + assign_codes，与原母版逐片比对 (block, size,
piece_index) → g 码；不一致即报错退出（防 ezdxf 回写副作用），保证带编号母版是
原母版的 drop-in 替换（可直接再上传 Web 走 commit，g 码不变）。

用法（repo 根目录，任意 python ≥3.11 均可，无包安装要求）::

    python scripts/embed_piece_codes.py <母版.dxf> [-o 输出.dxf] [--height 25]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ 在 repo 根，包源码在 materialSorting-server/src —— 引导后 import 包内模块
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "materialSorting-server" / "src"))

from materialsorting.dxf_parser import geometry, reader                     # noqa: E402
from materialsorting.dxf_parser.collect import collect_pieces_with_details  # noqa: E402
from materialsorting.nesting_engine.labeling import (                       # noqa: E402
    assign_codes,
    centroid,
    collect_master_codes,
)

# 编号 TEXT 独立层（与 web/export.write_marker_dxf 的 _DXF_LAYER_TEXT 同名同义）
TEXT_LAYER = "TEXT"
DEFAULT_HEIGHT = 25.0  # 字高 mm（与 marker DXF 逐片 TEXT 同口径）


def _label_anchor(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    """TEXT 定位点：顶点质心；凹片质心落片外时回退 bbox 中线最宽内条带中点。"""
    c = centroid(polygon)
    if geometry.point_in_polygon(c, polygon):
        return c
    ys = [y for _, y in polygon]
    my = (min(ys) + max(ys)) / 2.0
    # 扫描线 y=my 与各边交点（严格跨线才算，顶点擦线不产生假交点）
    xs_hit: list[float] = []
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 - my) * (y2 - my) < 0:
            t = (my - y1) / (y2 - y1)
            xs_hit.append(x1 + t * (x2 - x1))
    if not xs_hit:
        return c  # 退化（扫描线恰好全程贴边）—— 仍用质心兜底
    xs_hit.sort()
    # 交点排序后内/外交替，偶数位配对才是片内条带（U/凹形片最宽的相邻对可能是
    # 凹口外的外部条带）；按宽度降序取首个中点确在片内的条带
    spans = sorted(zip(xs_hit[0::2], xs_hit[1::2]), key=lambda ab: ab[1] - ab[0], reverse=True)
    for lo, hi in spans:
        mid = ((lo + hi) / 2.0, my)
        if geometry.point_in_polygon(mid, polygon):
            return mid
    return c


def _codes_sig(path: Path) -> dict:
    """重解析文件 → ``{(block_name_raw, size, piece_index): g码}`` 全量签名。"""
    pieces = collect_pieces_with_details(path)
    codes = assign_codes(pieces)
    return {
        (p.block_name_raw, p.size, p.piece_index): code
        for members in codes.values()
        for p, code in members
    }


def embed_codes(src: Path, dst: Path, height: float) -> None:
    """主流程：解析赋码 → 写 TEXT 进各 block → 另存 → 自校验。"""
    pieces = collect_pieces_with_details(src)
    if not pieces:
        raise SystemExit(f"[ERROR] 未从母版提取到裁片（无 layer1 POLYLINE）: {src}")
    codes_by_size = assign_codes(pieces)
    mode = "母版编号复用" if collect_master_codes(pieces) else "顺序赋号"

    doc = reader.load_doc(str(src))
    block_by_name = {b.name: b for b in doc.blocks if not b.name.startswith("*")}

    # 幂等：清掉 TEXT 层既有实体（仅本脚本产物层，母版自带的 layer2/4 参考 TEXT 不动）
    removed = 0
    for blk in block_by_name.values():
        for e in [e for e in blk
                  if e.dxftype() == "TEXT" and str(e.dxf.layer) == TEXT_LAYER]:
            blk.delete_entity(e)
            removed += 1

    if TEXT_LAYER not in {layer.dxf.name for layer in doc.layers}:
        doc.layers.add(TEXT_LAYER, color=7)

    n_text = 0
    for size, members in codes_by_size.items():
        for p, code in members:
            blk = block_by_name.get(p.block_name_raw)
            if blk is None:
                print(f"[WARN] block 不存在: {p.block_name_raw!r}，该片跳过", file=sys.stderr)
                continue
            text = f"{code}-{size}" if size is not None else code
            x, y = _label_anchor(p.polygon_mm)
            blk.add_text(text, dxfattribs={
                "height": height, "insert": (round(x, 2), round(y, 2)),
                "layer": TEXT_LAYER, "color": 7})
            n_text += 1

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(dst))

    print(f"读取母版: {src}")
    print(f"赋码模式: {mode}｜植入 TEXT: {n_text} 片（清旧 {removed}）")
    for size in sorted(codes_by_size, key=lambda s: (s is None, s if s is not None else 0)):
        members = codes_by_size[size]
        size_str = str(size) if size is not None else "?"
        print(f"  码号 {size_str}: {len(members):>2} 片  {members[0][1]}..{members[-1][1]}")
    print(f"写出: {dst}")

    # 自校验：输出重解析逐片同码（drop-in 替换保证）
    sig_src, sig_out = _codes_sig(src), _codes_sig(dst)
    if sig_src == sig_out:
        print(f"[OK] 自校验通过：输出重解析 {len(sig_out)} 片，g 码与原母版逐片一致")
    else:
        diff = {k for k in sig_src.keys() | sig_out.keys()
                if sig_src.get(k) != sig_out.get(k)}
        sample = ", ".join(f"{k}->{sig_out.get(k)}" for k in sorted(diff, key=str)[:5])
        raise SystemExit(f"[ERROR] 自校验失败：{len(diff)} 片不一致（如 {sample}），"
                         f"输出文件不可用，勿上传")


def main() -> None:
    # Windows 终端默认 GBK，重定向/管道捕获时强制 UTF-8，避免中文乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="把 g01+ 裁片编号植入母版 DXF（生成新文件，编号与 Web 上传预览一致）")
    ap.add_argument("dxf", help="母版 DXF 路径")
    ap.add_argument("-o", "--out", default=None,
                    help="输出路径（默认：同目录 <名>_coded.dxf）")
    ap.add_argument("--height", type=float, default=DEFAULT_HEIGHT,
                    help=f"TEXT 字高 mm（默认 {DEFAULT_HEIGHT:g}，与 marker 导出同口径）")
    args = ap.parse_args()

    src = Path(args.dxf)
    if not src.exists():
        raise SystemExit(f"[ERROR] 找不到 DXF: {args.dxf}")
    dst = Path(args.out) if args.out else src.with_name(f"{src.stem}_coded.dxf")

    embed_codes(src, dst, args.height)


if __name__ == "__main__":
    main()

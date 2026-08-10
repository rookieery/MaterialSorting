"""通用 DXF 探查: 遍历 ms + 所有命名 BLOCK, 兼容旧母版(BLOCK结构)与新AAMA(平铺)。"""
import sys, math
import ezdxf
import ezdxf.recover
from collections import Counter

OUT = open(sys.argv[2] if len(sys.argv) > 2 else '_probe_out.txt', 'w', encoding='utf-8')
def p(*a):
    print(*a, file=OUT)

path = sys.argv[1]
try:
    result = ezdxf.recover.readfile(path)
    doc = result[0] if isinstance(result, tuple) else result
except Exception as ex:
    p("recover 失败, 回退 readfile:", ex)
    doc = ezdxf.readfile(path)
ms = doc.modelspace()

def iter_entities():
    """yield (space_name, entity) 遍历 ms + 所有命名 block。"""
    for e in ms:
        yield ("MS", e)
    for blk in doc.blocks:
        if blk.name.startswith("*"):
            continue
        for e in blk:
            yield (blk.name, e)

p("="*60, "\nHEADER\n", "="*60)
h = doc.header
p("dxfversion:", doc.dxfversion)
p("$DWGCODEPAGE:", h.get("$DWGCODEPAGE"), " $INSUNITS:", h.get("$INSUNITS"))
p("$EXTMIN:", h.get("$EXTMIN"), " $EXTMAX:", h.get("$EXTMAX"))
p("\nAPPID:", sorted(a.dxf.name for a in doc.appids))
p("\nLAYERS:", [lyr.dxf.name for lyr in doc.layers])

p("\n", "="*60, "\n全文档实体 (space, layer, type) -> count\n", "="*60)
c = Counter()
for sp, e in iter_entities():
    c[(sp[:20], e.dxf.layer, e.dxftype())] += 1
for (sp,ly,ty),n in sorted(c.items()):
    p(f"  {sp:20} layer={ly:10} {ty:12} {n}")

p("\n", "="*60, "\n命名 BLOCK 结构\n", "="*60)
named = [b for b in doc.blocks if not b.name.startswith("*")]
p("命名 BLOCK 数:", len(named))
for blk in named[:25]:
    bc = Counter()
    for e in blk:
        bc[(e.dxf.layer, e.dxftype())] += 1
    summ = ", ".join(f"{ly}/{ty}={n}" for (ly,ty),n in sorted(bc.items()))
    p(f"  {blk.name:42} | {summ}")

p("\n", "="*60, "\nPOINT (刀口候选)\n", "="*60)
pts = []
for sp, e in iter_entities():
    if e.dxftype() == "POINT":
        pts.append((sp[:16], e.dxf.layer, round(float(e.dxf.location.x),1), round(float(e.dxf.location.y),1)))
p("POINT 总数:", len(pts), " 按 layer:", dict(Counter(pt[1] for pt in pts)))
for pt in pts[:25]:
    p("  ", pt)

p("\n", "="*60, "\nLINE (布纹线/刀口刻线)\n", "="*60)
lines = []
for sp, e in iter_entities():
    if e.dxftype() == "LINE":
        lines.append((e.dxf.layer, e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y))
p("LINE 总数:", len(lines), " 按 layer:", dict(Counter(l[0] for l in lines)))
if lines:
    lens = [math.hypot(l[3]-l[1], l[4]-l[2]) for l in lines]
    p(f"长度: min={min(lens):.1f} max={max(lens):.1f} 中位={sorted(lens)[len(lens)//2]:.1f}")
    buckets = Counter()
    for L in lens:
        if L < 5: buckets["<5mm"] += 1
        elif L < 50: buckets["5-50mm"] += 1
        elif L < 200: buckets["50-200mm"] += 1
        else: buckets[">200mm"] += 1
    p("长度桶:", dict(sorted(buckets.items())))
    angc = Counter()
    for l in lines:
        L = math.hypot(l[3]-l[1], l[4]-l[2])
        if L > 100:
            angc[round(math.degrees(math.atan2(l[4]-l[2], l[3]-l[1]))/10)*10] += 1
    p("长线(>100mm)方向:", dict(sorted(angc.items())))

p("\n", "="*60, "\nPOLYLINE (轮廓)\n", "="*60)
vc = Counter(); closed_c = Counter(); plc = Counter()
for sp, e in iter_entities():
    if e.dxftype() == "POLYLINE":
        vc[len(e.vertices)] += 1
        closed_c["closed" if getattr(e,'is_closed',False) else "open"] += 1
        plc[e.dxf.layer] += 1
p("按 layer:", dict(plc), " 闭合:", dict(closed_c))
p("顶点数分布(前15):")
for nv,n in sorted(vc.items())[:15]:
    p(f"  {nv}顶点: {n}条")
if 1 in closed_c and closed_c.get("closed",0)==0:
    p("  >> 警告: 无闭合 POLYLINE")

p("\n", "="*60, "\nTEXT (尺码/片名)\n", "="*60)
texts = []
for sp, e in iter_entities():
    if e.dxftype()=="TEXT": texts.append(e.dxf.text)
    elif e.dxftype()=="MTEXT": texts.append(e.plain_text())
p("TEXT 总数:", len(texts))
sizes = sorted(set(t.split('Size:')[1].strip() for t in texts if 'Size:' in t and len(t.split('Size:'))>1 and t.split('Size:')[1].strip()))
pn = sorted(set(t.split('Piece Name:')[1].strip() for t in texts if 'Piece Name:' in t and len(t.split('Piece Name:'))>1 and t.split('Piece Name:')[1].strip()))
p("Size 值:", sizes)
p("Piece Name 值:", pn)

OUT.close()
print("done")

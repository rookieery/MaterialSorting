// edit-drag-snap US-002 snap 单测（松手吸附引擎纯函数）：
//   1) P0 retreat 基础夹具：布尔交 ≤1e-9 mm² + 分离 ≥1e-9 mm + 回退量与解析值对拍（0.01mm）
//   2) 粗扫隧道穿越夹具：凹形/多障碍使自由区间不连通，朴素二分会跳过首界（→300）
//   3) 谓词不恶化起手基线：恶化位 retreat 回基线（存量重叠不清不增）
//   4) 改善/持平位不动（free，不误清存量重叠）+ 引擎不重钳 raw（调用方已 clamp）
//   5) 多副本同 pid 求和锁：5 副本各自 ≤ 基线、合计 > 基线 → retreat（pid 去重会误判 free）
//   6) attract 6mm（<10）吸到触点−1nm / 15mm（>10）不动
//   7) 零位移质心退化（lastSafeTr===raw 与 null 两变体）取 t 最小邻居
//   8) 平手取 key（数组下标）小者 —— 与 others 数组顺序无关
//   9) 同 pid 多副本 attract 寻址锁（不按 pid 收敛到首遇副本）
//  10) clamp 违反弃用回落 raw（gate 顶 / minX / minY 三变体）+ retreat 候选违 clamp 同回落
//  11) 内部异常 fail-open 返回 raw（getter 抛异常注入）
//  12) 确定性双跑逐位全等（无 RNG）
//  13) 空邻居 / 无锚点防御

import { describe, expect, it } from 'vitest';
import { ATTRACT_MAX_GAP_MM, computeSnapCorrection, type SnapSession } from './snap';
import { computeOverlap, type EditPiece } from './overlap';
import { bboxOf, transformPolygon } from './editGeometry';
import type { Polygon, Pt } from '../types/piece';

/** 100x100 方形 base（dragged 与邻居通用构件）。 */
const SQ: Polygon = [
  [0, 0],
  [100, 0],
  [100, 100],
  [0, 100],
];

/** 轴对齐矩形多边形（世界坐标直出，rot=0/tr=(0,0) 即 base=world）。 */
function rect(x0: number, y0: number, x1: number, y1: number): Polygon {
  return [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
  ];
}

/** EditPiece 直造夹具（worldPolygon/bbox 由 transformPolygon/bboxOf 正规计算）。
 *  dMm 缺省 0（本套夹具全 d=0 —— 吸附引擎不消费压线额度，物理口径=夹具多边形本身）。 */
function mkEp(
  key: number,
  pid: string,
  poly: Polygon,
  rot = 0,
  tr: Pt = [0, 0],
  mirror = false,
): EditPiece {
  const world = transformPolygon(poly, rot, tr, mirror);
  return {
    key,
    pid,
    rot,
    tr: [tr[0], tr[1]],
    mirror,
    basePolygon: poly,
    dMm: 0,
    worldPolygon: world,
    bbox: bboxOf(world),
  };
}

function sess(lastSafeTr: Pt | null, startOverlapMm2: number): SnapSession {
  return { lastSafeTr, startOverlapMm2 };
}

/** 被拖片放到 result.tr 后 vs 全邻居的布尔交总面积（验收口径复用 computeOverlap）。 */
function areaAt(dragged: EditPiece, tr: Pt, others: readonly EditPiece[]): number {
  const world = transformPolygon(dragged.basePolygon, dragged.rot, tr, dragged.mirror);
  const ep: EditPiece = { ...dragged, tr: [tr[0], tr[1]], worldPolygon: world, bbox: bboxOf(world) };
  return computeOverlap(ep, others).areaMm2;
}

describe('computeSnapCorrection — P0 retreat', () => {
  it('基础夹具：回退到墙西沿解析位 tx=30（±0.01），布尔交 ≤1e-9、分离 ≥1e-9，kind/partner 正确', () => {
    // dragged [0,100]^2 从 (0,0) 拖到 (60,0)，墙 [130,230]x[0,100]：首界 tx=30（ maxX=130 贴触）。
    // 粗扫 t=20 自由（[20,120] 距墙 10）→ t=40 碰撞（[40,140] 交 10x100）→ 括出 [20,40] 二分。
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(7, 'w_28', rect(130, 0, 230, 100));
    const r = computeSnapCorrection(dragged, [60, 0], sess([0, 0], 0), [wall], { gate: 1000 });
    expect(r.kind).toBe('retreat');
    expect(r.partnerKey).toBe(7);
    expect(Math.abs(r.tr[0] - 30)).toBeLessThanOrEqual(0.01); // 回退量解析对拍
    expect(r.tr[1]).toBe(0);
    expect(areaAt(dragged, r.tr, [wall])).toBeLessThanOrEqual(1e-9); // 布尔交 ≤1e-9 mm²
    const gap = 30 - r.tr[0]; // 墙西沿 130 − 被拖片东沿 100+tx（代数等价式避免大数相减的 1e-14 级消去噪声）
    // 分离 ≥1e-9 mm（1nm 微退）：容 1e-12 浮点余量 —— ~30mm 量级 double 的 ulp ~3.5e-15，
    // 「大数 − 大数」消去把 1nm 量出来会带 ~1e-14 级噪声（物理不变量 = 严格分离 + ~1nm）。
    expect(gap).toBeGreaterThan(0);
    expect(gap).toBeGreaterThanOrEqual(1e-9 - 1e-12);
    expect(gap).toBeLessThanOrEqual(0.01); // 二分收敛界（14 轮 × ≤20mm 段）
  });

  it('隧道穿越夹具：窄障碍 A=[150,155] 中途 + 远墙 B=[400,500] 终点，粗扫回到首界 50（朴素二分会跳到 300）', () => {
    // 自由区间不连通：[0,50) ∪ (155,300)。落点 (350,0) 撞 B；朴素二分 [0,350] 首个 mid=175
    // 落在自由口袋 → 收敛到 B 的界 300（穿越 A）。粗扫 20mm 步在 t=60 先撞 A → 括出 [40,60]。
    const dragged = mkEp(0, 'd_28', SQ);
    const barA = mkEp(1, 'a_28', rect(150, 0, 155, 100));
    const wallB = mkEp(2, 'b_28', rect(400, 0, 500, 100));
    const r = computeSnapCorrection(dragged, [350, 0], sess([0, 0], 0), [barA, wallB], { gate: 1000 });
    expect(r.kind).toBe('retreat');
    expect(Math.abs(r.tr[0] - 50)).toBeLessThanOrEqual(0.01); // 首界 = A 西沿 150 − maxX 100
    expect(r.tr[0]).toBeLessThan(100); // 远离朴素二分的错误收敛位 300
    expect(areaAt(dragged, r.tr, [barA, wallB])).toBeLessThanOrEqual(1e-9);
    expect(50 - r.tr[0]).toBeGreaterThan(0); // A 西沿 150 − 东沿 100+tx 的等价式（严格分离）
    expect(50 - r.tr[0]).toBeGreaterThanOrEqual(1e-9 - 1e-12); // ~1nm（ulp 消去噪声容差，同上）
    expect(r.partnerKey).toBe(1); // 边界碰撞主导邻居 = 窄障碍 A
  });
});

describe('computeSnapCorrection — 谓词基线（存量重叠不恶化、不误清）', () => {
  it('恶化位（900 > 基线 500）retreat 回到基线等价位：终态重叠 = 基线（不清零）', () => {
    // 起手 [0,100]^2 与墙 [95,195]x[0,100] 交 5x100=500（solver 容差构造的存量重叠）。
    // 落点 (4,0) 交 9x100=900 > 500 → 沿路径任何 tx>0 都 >500 → 回退到锚点 (0,0) 本身。
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(3, 'w_28', rect(95, 0, 195, 100));
    const r = computeSnapCorrection(dragged, [4, 0], sess([0, 0], 500), [wall], { gate: 1000 });
    expect(r.kind).toBe('retreat');
    expect(r.tr).toEqual([0, 0]); // 二分 a 恒 0（任何正 tx 都违谓词）→ tStar=0 精确
    const finalArea = areaAt(dragged, r.tr, [wall]);
    expect(finalArea).toBeLessThanOrEqual(500 + 1e-9); // 不恶化
    expect(finalArea).toBeGreaterThanOrEqual(499); // 不误清（仍保留 ~500 存量重叠）
  });

  it('改善位（300 ≤ 基线 500）不动：free 原样落点、存量重叠保留（引擎不重钳 raw —— 调用方已 clamp）', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(3, 'w_28', rect(95, 0, 195, 100));
    const r = computeSnapCorrection(dragged, [-2, 0], sess([0, 0], 500), [wall], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([-2, 0]);
    expect(areaAt(dragged, r.tr, [wall])).toBeCloseTo(300, 9); // 3x100 保留
  });

  it('持平位（零位移、恰在基线）不动：free、重叠 500 原样（不误清）', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(3, 'w_28', rect(95, 0, 195, 100));
    const r = computeSnapCorrection(dragged, [0, 0], sess([0, 0], 500), [wall], { gate: 1000 });
    expect(r.kind).toBe('free'); // 500 ≤ 500+eps；attract 方向触点在 95mm 外（>10mm 阈）不动
    expect(r.tr).toEqual([0, 0]);
    expect(areaAt(dragged, r.tr, [wall])).toBeCloseTo(500, 9);
  });
});

describe('computeSnapCorrection — 多副本同 pid（仓库红线：绝不 pid 去重）', () => {
  it('retreat 谓词按 key 逐副本求和：5 副本各 50 ≤ 基线 200、合计 250 > 200 → retreat（去重会误判 free）', () => {
    // W=[-8,2]x[0,100] 起手交 2x100=200（基线）；E1..E5=[150,190]x[0,10/20-30/.../80-90]
    // 同 pid z_28 五副本。落点 (55,0)：每条交 5x10=50（单看都 ≤200），合计 250 > 200。
    // 谓词边界：total(tx)=50·(tx−50)（tx∈[50,90]）≤200 ⟺ tx≤54 → 回退到 54。
    const dragged = mkEp(0, 'd_28', SQ);
    const w = mkEp(1, 'z_28', rect(-8, 0, 2, 100));
    const strips = [0, 20, 40, 60, 80].map((y0, i) => mkEp(2 + i, 'z_28', rect(150, y0, 190, y0 + 10)));
    const others = [w, ...strips];
    const r = computeSnapCorrection(dragged, [55, 0], sess([0, 0], 200), others, { gate: 1000 });
    expect(r.kind).toBe('retreat'); // 若按 pid 去重只剩一副本（50 ≤ 200）会误判 free
    expect(Math.abs(r.tr[0] - 54)).toBeLessThanOrEqual(0.01); // 解析对拍
    const finalArea = areaAt(dragged, r.tr, others);
    expect(finalArea).toBeLessThanOrEqual(200 + 1e-9); // 不恶化
    expect(finalArea).toBeGreaterThanOrEqual(150); // 不误清
    expect(r.partnerKey).toBe(2); // 边界位五副本同面积平手 → key 最小（E1）
  });

  it('attract 寻址按 key：同 pid 两副本 t=6/8 取 t 小者（后位副本），与 others 数组顺序无关', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const north = mkEp(2, 'z_28', rect(0, 108, 100, 208)); // 北 8mm
    const east = mkEp(4, 'z_28', rect(106, 0, 206, 100)); // 东 6mm
    const r = computeSnapCorrection(dragged, [0, 0], sess([0, 0], 0), [north, east], { gate: 1000 });
    expect(r.kind).toBe('attract');
    expect(r.partnerKey).toBe(4); // 东副本 t=6 < 北副本 t=8（按 pid 收敛首遇副本会得 2）
    expect(r.tr[0]).toBeCloseTo(6, 8); // 6 − 1nm
    expect(r.tr[1]).toBe(0);
  });
});

describe('computeSnapCorrection — P1 attract', () => {
  it('间隙 6mm（< ATTRACT_MAX_GAP_MM=10）：沿末帧拖动方向吸到触点 −1nm，布尔交 ≤1e-9、分离 ≥1e-9', () => {
    // dragged (0,0)→(4,0)（dragDir=(1,0)），墙 [110,210]x[0,100]：首触 t=6 → tx=4+6−1nm=10−1nm。
    expect(ATTRACT_MAX_GAP_MM).toBe(10); // 2026-09-06 定案阈值锁
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(3, 'w_28', rect(110, 0, 210, 100));
    const r = computeSnapCorrection(dragged, [4, 0], sess([0, 0], 0), [wall], { gate: 1000 });
    expect(r.kind).toBe('attract');
    expect(r.partnerKey).toBe(3);
    expect(r.tr[0]).toBeCloseTo(10, 8); // 10 − 1nm
    expect(r.tr[1]).toBe(0);
    expect(areaAt(dragged, r.tr, [wall])).toBeLessThanOrEqual(1e-9);
    expect(110 - (100 + r.tr[0])).toBeGreaterThanOrEqual(1e-9); // 分离 ≥1e-9
  });

  it('间隙 15mm（> 阈值 10）：不吸，free 原样落点', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(3, 'w_28', rect(120, 0, 220, 100));
    const r = computeSnapCorrection(dragged, [5, 0], sess([0, 0], 0), [wall], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([5, 0]);
  });

  it('零位移帧退化质心连线（lastSafeTr === rawTr）：东 4mm / 北 8mm 取东（t 最小）', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const east = mkEp(5, 'e_28', rect(104, 0, 204, 100));
    const north = mkEp(6, 'n_28', rect(0, 108, 100, 208));
    const r = computeSnapCorrection(dragged, [0, 0], sess([0, 0], 0), [east, north], { gate: 1000 });
    expect(r.kind).toBe('attract');
    expect(r.partnerKey).toBe(5);
    expect(r.tr[0]).toBeCloseTo(4, 8); // 4 − 1nm
    expect(r.tr[1]).toBe(0);
    expect(areaAt(dragged, r.tr, [east, north])).toBeLessThanOrEqual(1e-9);
  });

  it('零位移 null 锚点变体（lastSafeTr === null 且落点合谓词）：同样走质心退化', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const east = mkEp(5, 'e_28', rect(104, 0, 204, 100));
    const r = computeSnapCorrection(dragged, [0, 0], sess(null, 0), [east], { gate: 1000 });
    expect(r.kind).toBe('attract');
    expect(r.partnerKey).toBe(5);
    expect(r.tr[0]).toBeCloseTo(4, 8);
  });

  it('多邻居平手（同 t=6）取 key 小者 —— 与 others 数组顺序无关', () => {
    // 东墙 key=9 在数组首位、北墙 key=2 在次位，两向 t 均 6（整数算术精确相等）→ key=2 胜。
    const dragged = mkEp(0, 'd_28', SQ);
    const eastBig = mkEp(9, 'e_28', rect(106, 0, 206, 100));
    const northSmall = mkEp(2, 'n_28', rect(0, 106, 100, 206));
    const r = computeSnapCorrection(
      dragged,
      [0, 0],
      sess([0, 0], 0),
      [eastBig, northSmall],
      { gate: 1000 },
    );
    expect(r.kind).toBe('attract');
    expect(r.partnerKey).toBe(2); // 平手 → key（placed_items 数组下标）小者
    expect(r.tr).toEqual([0, expect.closeTo(6, 8)]);
    expect(r.tr[0]).toBe(0);
  });

  it('拖动方向背离邻居（首触在身后）：无候选不吸', () => {
    // dragDir=(−1,0) 背离东墙 → firstContactDistance 无前方交点 → free。
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(3, 'w_28', rect(110, 0, 210, 100));
    const r = computeSnapCorrection(dragged, [4, 0], sess([10, 0], 0), [wall], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([4, 0]);
  });
});

describe('computeSnapCorrection — clamp 不变量与 fail-open', () => {
  it('attract 候选越 gate 顶（maxY > gate）：弃用回落 raw', () => {
    // 被拖片贴门幅顶（maxY=1000=gate），北邻在门外 4mm：质心退化方向 (0,1)、t=4，
    // 吸引位 maxY=1004−1nm > gate → 违不变量 → 弃用 → free 原样落点。
    const dragged = mkEp(0, 'd_28', SQ, 0, [0, 900]);
    const north = mkEp(1, 'n_28', rect(0, 1004, 100, 1104));
    const r = computeSnapCorrection(dragged, [0, 900], sess([0, 900], 0), [north], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([0, 900]);
  });

  it('attract 候选 minX < 0：弃用回落 raw', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const west = mkEp(1, 'w_28', rect(-14, 0, -4, 100)); // 西邻（门外），间隙 4mm
    const r = computeSnapCorrection(dragged, [0, 0], sess([0, 0], 0), [west], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([0, 0]);
  });

  it('attract 候选 minY < 0：弃用回落 raw', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const south = mkEp(1, 's_28', rect(0, -14, 100, -4)); // 南邻（布头墙下），间隙 4mm
    const r = computeSnapCorrection(dragged, [0, 0], sess([0, 0], 0), [south], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([0, 0]);
  });

  it('retreat 候选违 clamp（锚点本身未钳制）：同样弃用回落 raw', () => {
    // 锚点 (0,−5)（伪造未钳制位）：落点 (60,−5) 撞墙 → 回退位 minY=−5 违不变量 → raw。
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(7, 'w_28', rect(130, 0, 230, 100));
    const r = computeSnapCorrection(dragged, [60, -5], sess([0, -5], 0), [wall], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([60, -5]);
  });

  it('内部异常 fail-open：返回 raw（kind=free），不抛出', () => {
    // basePolygon 取值时抛异常（pieceAt 重放变换即触发）→ catch → raw。
    const boom = {
      key: 0,
      pid: 'd_28',
      rot: 0,
      tr: [0, 0] as Pt,
      mirror: false,
      get basePolygon(): Polygon {
        throw new Error('boom');
      },
      worldPolygon: SQ,
      bbox: bboxOf(SQ),
    } as EditPiece;
    const wall = mkEp(7, 'w_28', rect(130, 0, 230, 100));
    expect(() =>
      computeSnapCorrection(boom, [60, 0], sess([0, 0], 0), [wall], { gate: 1000 }),
    ).not.toThrow();
    const r = computeSnapCorrection(boom, [60, 0], sess([0, 0], 0), [wall], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([60, 0]);
    expect(r.partnerKey).toBeNull();
  });
});

describe('computeSnapCorrection — 确定性与防御', () => {
  it('确定性双跑逐位全等（隧道穿越夹具，无 RNG）', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const barA = mkEp(1, 'a_28', rect(150, 0, 155, 100));
    const wallB = mkEp(2, 'b_28', rect(400, 0, 500, 100));
    const r1 = computeSnapCorrection(dragged, [350, 0], sess([0, 0], 0), [barA, wallB], { gate: 1000 });
    const r2 = computeSnapCorrection(dragged, [350, 0], sess([0, 0], 0), [barA, wallB], { gate: 1000 });
    expect(JSON.stringify(r1)).toBe(JSON.stringify(r2)); // 数值逐位全等
    expect(r1).toEqual(r2);
  });

  it('空邻居：free 恒等返回（且 tr 为拷贝不别名入参）', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const rawTr: Pt = [123.5, 67.25];
    const r = computeSnapCorrection(dragged, rawTr, sess([0, 0], 0), [], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([123.5, 67.25]);
    expect(r.tr).not.toBe(rawTr);
  });

  it('落点违谓词但无安全锚点（lastSafeTr=null）：fail-open 返回 raw', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const wall = mkEp(7, 'w_28', rect(130, 0, 230, 100));
    const r = computeSnapCorrection(dragged, [60, 0], sess(null, 0), [wall], { gate: 1000 });
    expect(r.kind).toBe('free');
    expect(r.tr).toEqual([60, 0]);
  });

  it('含被拖片自身的 others：按 key 跳过，不产生自交假阳性', () => {
    const dragged = mkEp(0, 'd_28', SQ);
    const self = mkEp(0, 'd_28', SQ, 0, [60, 0]); // 同 key 不同位（防御夹具）
    const wall = mkEp(7, 'w_28', rect(130, 0, 230, 100));
    const r = computeSnapCorrection(dragged, [60, 0], sess([0, 0], 0), [self, wall], { gate: 1000 });
    expect(r.kind).toBe('retreat'); // 自身被跳过，仍按墙 retreat 到 ~30
    expect(Math.abs(r.tr[0] - 30)).toBeLessThanOrEqual(0.01);
  });
});

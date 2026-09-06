// 编辑排料 US-001 editGeometry 单测：
//   1) transformPolygon 与 lib/geometry.ts pointsStr 同公式逐点一致（r2 截断后对拍）
//   2) transformPolygon 全精度 + 不修改入参
//   3) polygonArea 多 ring 求和版（复用 params.ts shoelace 单 ring）
//   4) bboxOf / bboxIntersect（含边界接触）
//   5) pointInPolygon（凸 / 凹）
//   6) penetrationDepth（矩形 / 三角 / 凹形夹具手算锁死 + 已知近似边界如实断言）
//   7) clientToWorld（mock CTM：letterbox 偏移 + scale(1,-1) 翻转的复合矩阵逆变换；
//      CTM 不可得 -> null）
//   8) edit-keyboard US-001 mirror 分支：手算方块 / 与 pointsStr mirror 对拍 / x 预取负
//      等价（全精度）/ mirror=false 显式 = 缺省零回归
//   9) edit-drag-snap US-001 吸附几何算子：contactT 单位解（垂直/斜向精确 t、延长线
//      miss、近平行与零长边 null 不抛异常、负 t 原样返回、端点命中含端）+
//      firstContactDistance（矩形夹具解析精确 t、斜向两向枚举、凹形 L 首触点落凹口
//      内角、近平行弧段密集顶点 null 不抛异常 / 跳过后照常得手算值、无交点 null、
//      镜像+旋转 vs 直接构造同形态同 t 口径无关性锁）

import { describe, expect, it } from 'vitest';
import { pointsStr, r2 } from '../geometry';
import {
  bboxIntersect,
  bboxOf,
  clientToWorld,
  contactT,
  firstContactDistance,
  penetrationDepth,
  pointInPolygon,
  polygonArea,
  transformPolygon,
} from '../editGeometry';
import type { Polygon, Pt } from '../../types/piece';

const SQUARE: Polygon = [
  [0, 0],
  [100, 0],
  [100, 100],
  [0, 100],
];

describe('transformPolygon', () => {
  it('与 pointsStr 同公式逐点一致（r2 截断后对拍；多组含任意角度/平移）', () => {
    const cases: Array<{ poly: number[][]; rot: number; tr: [number, number] }> = [
      { poly: SQUARE, rot: 0, tr: [0, 0] },
      { poly: SQUARE, rot: 0, tr: [1234.5, 987.6] },
      { poly: [[1, 0], [0, 1]], rot: 90, tr: [10, 20] },
      { poly: [[10, 0], [10, 10], [0, 10]], rot: 45, tr: [0, 0] },
      { poly: [[100, 200], [300, 400]], rot: 180, tr: [50, 50] },
      { poly: [[1.23456, 2.34567], [-3.45678, 4.56789]], rot: 33.3, tr: [100.5, 200.5] },
      { poly: [[0, 0], [5, 0], [2.5, 4.33]], rot: 270, tr: [0, 0] },
      {
        poly: Array.from({ length: 12 }, (_, i) => [
          100 * Math.cos((i / 12) * 2 * Math.PI),
          100 * Math.sin((i / 12) * 2 * Math.PI),
        ]),
        rot: 17.5,
        tr: [1234.5, 6789],
      },
    ];
    for (const { poly, rot, tr } of cases) {
      const arr = transformPolygon(poly as Pt[], rot, tr as Pt);
      const fromStr = pointsStr(poly as Polygon, rot, tr as Pt)
        .split(' ')
        .map((p) => p.split(',').map(Number) as [number, number]);
      expect(arr.length).toBe(fromStr.length);
      for (let i = 0; i < arr.length; i++) {
        // +0 归一化：r2 可产 -0，而 String(-0)='0' 回解析为 +0（Object.is 区分 ±0）
        expect(r2(arr[i][0]) + 0).toBe(fromStr[i][0] + 0);
        expect(r2(arr[i][1]) + 0).toBe(fromStr[i][1] + 0);
      }
    }
  });

  it('保留全精度（不 r2 截断）—— 布尔交/bbox 计算口径', () => {
    const out = transformPolygon([[1, 0]], 30, [0, 0]);
    expect(out[0][0]).toBeCloseTo(Math.cos(Math.PI / 6), 12);
  });

  it('返回新数组，不修改入参', () => {
    const src: Polygon = [
      [1, 2],
      [3, 4],
    ];
    const snapshot = src.map((p) => [...p] as Pt);
    transformPolygon(src, 90, [10, 10]);
    expect(src).toEqual(snapshot);
  });

  it('mirror=false 显式传参与缺省不传逐点相同（零回归红线）', () => {
    for (const rot of [0, 33.3, 90, 180, 270]) {
      for (const tr of [[0, 0], [100.5, -200.25]] as Pt[]) {
        expect(transformPolygon(SQUARE, rot, tr, false)).toEqual(transformPolygon(SQUARE, rot, tr));
      }
    }
  });
});

// ============================================================
// edit-keyboard US-001：transformPolygon mirror 分支
// ============================================================

describe('transformPolygon mirror (edit-keyboard US-001)', () => {
  it('手算：SQUARE rot=0 + tr(10,20) + mirror -> x 分量取负（(100,0)->(-90,20) 等）', () => {
    // mirror + rot0：x' = −x + 10；y' = y + 20
    // (0,0)->(10,20)；(100,0)->(−90,20)；(100,100)->(−90,120)；(0,100)->(10,120)
    expect(transformPolygon(SQUARE, 0, [10, 20], true)).toEqual([
      [10, 20],
      [-90, 20],
      [-90, 120],
      [10, 120],
    ]);
  });

  it('mirror 与 pointsStr 同公式逐点一致（r2 截断后对拍；多组含任意角度/平移）', () => {
    const cases: Array<{ poly: number[][]; rot: number; tr: [number, number] }> = [
      { poly: SQUARE, rot: 0, tr: [0, 0] },
      { poly: SQUARE, rot: 0, tr: [1234.5, 987.6] },
      { poly: [[1, 0], [0, 1]], rot: 90, tr: [10, 20] },
      { poly: [[10, 0], [10, 10], [0, 10]], rot: 45, tr: [0, 0] },
      { poly: [[1.23456, 2.34567], [-3.45678, 4.56789]], rot: 33.3, tr: [100.5, 200.5] },
      { poly: [[0, 0], [5, 0], [2.5, 4.33]], rot: 270, tr: [0, 0] },
      {
        poly: Array.from({ length: 12 }, (_, i) => [
          100 * Math.cos((i / 12) * 2 * Math.PI),
          100 * Math.sin((i / 12) * 2 * Math.PI),
        ]),
        rot: 17.5,
        tr: [1234.5, 6789],
      },
    ];
    for (const { poly, rot, tr } of cases) {
      const arr = transformPolygon(poly as Pt[], rot, tr as Pt, true);
      const fromStr = pointsStr(poly as Polygon, rot, tr as Pt, true)
        .split(' ')
        .map((p) => p.split(',').map(Number) as [number, number]);
      expect(arr.length).toBe(fromStr.length);
      for (let i = 0; i < arr.length; i++) {
        // +0 归一化：r2 可产 -0，而 String(-0)='0' 回解析为 +0（Object.is 区分 ±0）
        expect(r2(arr[i][0]) + 0).toBe(fromStr[i][0] + 0);
        expect(r2(arr[i][1]) + 0).toBe(fromStr[i][1] + 0);
      }
    }
  });

  it('mirror=true 与「x 预取负 poly 的无镜像变换」全精度逐点相等（同一算术序）', () => {
    const poly: Polygon = [
      [1.23456, 2.34567],
      [-3.45678, 4.56789],
      [10, -20],
    ];
    const xNeg: Polygon = poly.map((p) => [-p[0], p[1]] as Pt);
    for (const rot of [0, 17.5, 90, 180, 337]) {
      for (const tr of [[0, 0], [-500.25, 1234.5]] as Pt[]) {
        expect(transformPolygon(poly, rot, tr, true)).toEqual(transformPolygon(xNeg, rot, tr));
      }
    }
  });

  it('mirror 保留全精度 + 返回新数组不修改入参', () => {
    const out = transformPolygon([[1, 0]], 30, [0, 0], true);
    // mirror+rot30：x' = −cos30 ≈ −0.8660254（全精度不截断）
    expect(out[0][0]).toBeCloseTo(-Math.cos(Math.PI / 6), 12);
    expect(out[0][1]).toBeCloseTo(-Math.sin(Math.PI / 6), 12);
    const src: Polygon = [
      [1, 2],
      [3, 4],
    ];
    const snapshot = src.map((p) => [...p] as Pt);
    transformPolygon(src, 90, [10, 10], true);
    expect(src).toEqual(snapshot);
  });
});

describe('polygonArea（多 ring 求和版）', () => {
  it('单 ring = shoelace 绝对值（100x100 方 = 10000）', () => {
    expect(polygonArea([SQUARE])).toBe(10000);
  });

  it('多 ring 求和（10000 + 5000 = 15000）', () => {
    const tri: Polygon = [
      [0, 0],
      [100, 0],
      [0, 100],
    ];
    expect(polygonArea([SQUARE, tri])).toBe(15000);
  });

  it('顶点序不影响（顺/逆时针同面积）', () => {
    expect(polygonArea([[...SQUARE].reverse()])).toBe(10000);
  });
});

describe('bboxOf / bboxIntersect', () => {
  it('bboxOf：顶点 min/max（含斜置三角形）', () => {
    expect(bboxOf(SQUARE)).toEqual({ minX: 0, minY: 0, maxX: 100, maxY: 100 });
    const tri: Polygon = [
      [10, 0],
      [0, -5],
      [30, 20],
    ];
    expect(bboxOf(tri)).toEqual({ minX: 0, minY: -5, maxX: 30, maxY: 20 });
  });

  it('bboxOf：空数组防御返回全 0 退化盒', () => {
    expect(bboxOf([])).toEqual({ minX: 0, minY: 0, maxX: 0, maxY: 0 });
  });

  it('bboxIntersect：相交 true / 相离 false / 边界接触 true（预筛宁多勿漏）', () => {
    const a = { minX: 0, minY: 0, maxX: 100, maxY: 100 };
    expect(bboxIntersect(a, { minX: 50, minY: 50, maxX: 150, maxY: 150 })).toBe(true);
    expect(bboxIntersect(a, { minX: 101, minY: 0, maxX: 200, maxY: 100 })).toBe(false);
    expect(bboxIntersect(a, { minX: 100, minY: 0, maxX: 200, maxY: 100 })).toBe(true);
    expect(bboxIntersect(a, { minX: 0, minY: 100, maxX: 50, maxY: 200 })).toBe(true);
  });
});

describe('pointInPolygon', () => {
  it('凸方形：内 true / 外 false', () => {
    expect(pointInPolygon([50, 50], SQUARE)).toBe(true);
    expect(pointInPolygon([150, 50], SQUARE)).toBe(false);
    expect(pointInPolygon([-1, -1], SQUARE)).toBe(false);
  });

  it('凹形：缺口内 false / 实体处 true（L 形）', () => {
    // L 形：全方形挖去右上 50x50 缺口
    const l: Polygon = [
      [0, 0],
      [100, 0],
      [100, 50],
      [50, 50],
      [50, 100],
      [0, 100],
    ];
    expect(pointInPolygon([25, 75], l)).toBe(true); // 左上实体
    expect(pointInPolygon([75, 75], l)).toBe(false); // 右上缺口
    expect(pointInPolygon([75, 25], l)).toBe(true); // 右下实体
    expect(pointInPolygon([150, 50], l)).toBe(false);
  });
});

describe('penetrationDepth', () => {
  it('不相交 -> 0', () => {
    const b: Polygon = [
      [200, 0],
      [300, 0],
      [300, 100],
      [200, 100],
    ];
    expect(penetrationDepth(SQUARE, b)).toBe(0);
  });

  it('矩形 x 矩形：B 左边深入 A 5mm（双方各有顶点落入对方，最近边距 = 5）', () => {
    // A=[0,100]^2，B=[95,195]x[30,130]：B 顶点 (95,30) 落入 A，到 A 边界最近边 x=100 距 5；
    // A 顶点 (100,100) 落入 B，到 B 边界最近边 x=95 距 5 -> 深度 5。
    const b: Polygon = [
      [95, 30],
      [195, 30],
      [195, 130],
      [95, 130],
    ];
    expect(penetrationDepth(SQUARE, b)).toBeCloseTo(5, 10);
  });

  it('三角 x 矩形：三角顶点深入矩形 10mm', () => {
    // 矩形 [0,100]x[0,30]，三角 [(5,5),(15,5),(10,20)]：顶点 (10,20) 落入矩形，
    // 到矩形边界（y=30）距 10；其余顶点在矩形内但更浅（y=5 距底 5）-> 深度 10。
    const rect: Polygon = [
      [0, 0],
      [100, 0],
      [100, 30],
      [0, 30],
    ];
    const tri: Polygon = [
      [5, 5],
      [15, 5],
      [10, 20],
    ];
    expect(penetrationDepth(tri, rect)).toBeCloseTo(10, 10);
  });

  it('凹形：A 顶点落入 B / B 顶点落入 A 双向采样取最大（L 形 x 方块）', () => {
    // A = L 形（右上半边挖缺，缺口区 [50,100]x[50,100]）；B = 方块 [40,70]^2。
    // A 顶点 (50,50) 落入 B，到 B 边界（x=40 / y=40）最近距 10；
    // B 顶点 (40,40) 落入 A 左下实体，到 A 缺口角 (50,50) 距 √200 ≈ 14.142（凹角贡献）；
    // B 顶点 (70,40)/(40,70) 深度 10 -> 双向取最大 = √200。
    const l: Polygon = [
      [0, 0],
      [100, 0],
      [100, 50],
      [50, 50],
      [50, 100],
      [0, 100],
    ];
    const b: Polygon = [
      [40, 40],
      [70, 40],
      [70, 70],
      [40, 70],
    ];
    expect(penetrationDepth(l, b)).toBeCloseTo(Math.sqrt(200), 10);
  });

  it('已知近似边界（如实断言）：十字交叉（边相交但顶点互不落入）-> 0（低估，面积指标互补）', () => {
    // A 横条 [0,100]x[40,60]，B 竖条 [40,60]x[0,100]：交 20x20，但双方顶点均不在对方内部。
    const h: Polygon = [
      [0, 40],
      [100, 40],
      [100, 60],
      [0, 60],
    ];
    const v: Polygon = [
      [40, 0],
      [60, 0],
      [60, 100],
      [40, 100],
    ];
    expect(penetrationDepth(h, v)).toBe(0);
  });
});

// ---- clientToWorld（jsdom 无 getScreenCTM/createSVGPoint —— mock 复合矩阵） ----

/** 2x3 仿射矩阵（DOMMatrix 2D 口径：x' = a*x + c*y + e；y' = b*x + d*y + f）。 */
interface MockMat {
  a: number;
  b: number;
  c: number;
  d: number;
  e: number;
  f: number;
  inverse: () => MockMat;
}

function mockMat(a: number, b: number, c: number, d: number, e: number, f: number): MockMat {
  const inverse = (): MockMat => {
    const det = a * d - b * c;
    const ia = d / det;
    const ib = -b / det;
    const ic = -c / det;
    const id = a / det;
    return mockMat(ia, ib, ic, id, -(ia * e + ic * f), -(ib * e + id * f));
  };
  return { a, b, c, d, e, f, inverse };
}

/**
 * 复合 CTM = viewBox->client（含 xMinYMid meet letterbox）后再经翻转组
 * translate(0,1980) scale(1,-1) 的完整链：world(x,y) -> client(0.2x + 60, 416 - 0.2y)
 * （viewBox 2000x1980 以 scale 0.2 落在 client 400x396 @ 偏移 (60,20)，x 向 letterbox 60px。）
 */
const CTM = mockMat(0.2, 0, 0, -0.2, 60, 416);

function setupSvg(): { svg: SVGSVGElement; g: SVGGElement } {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg') as unknown as SVGSVGElement;
  const g = document.createElementNS(NS, 'g') as unknown as SVGGElement;
  (g as unknown as { getScreenCTM: () => MockMat | null }).getScreenCTM = () => CTM;
  (svg as unknown as { createSVGPoint: () => unknown }).createSVGPoint = () => {
    const pt = {
      x: 0,
      y: 0,
      matrixTransform(m: MockMat) {
        return { x: m.a * pt.x + m.c * pt.y + m.e, y: m.b * pt.x + m.d * pt.y + m.f };
      },
    };
    return pt;
  };
  return { svg, g };
}

describe('clientToWorld', () => {
  it('复合矩阵（letterbox + Y 翻转）下取回精确世界坐标', () => {
    const { svg, g } = setupSvg();
    // world (100, 990) -> client (0.2*100+60, 416-0.2*990) = (80, 218)
    // （mock 逆矩阵有 float 噪声 —— toBeCloseTo 逐分量）
    const w1 = clientToWorld(svg, g, 80, 218);
    expect(w1?.[0]).toBeCloseTo(100, 10);
    expect(w1?.[1]).toBeCloseTo(990, 10);
    // world (0, 0)（左下角，料头底）-> client (60, 416)
    const w2 = clientToWorld(svg, g, 60, 416);
    expect(w2?.[0]).toBeCloseTo(0, 10);
    expect(w2?.[1]).toBeCloseTo(0, 10);
    // world (2000, 1980)（右上角）-> client (460, 20) —— Y 翻转：世界 y 大 -> client y 小
    const w = clientToWorld(svg, g, 460, 20);
    expect(w?.[0]).toBeCloseTo(2000, 10);
    expect(w?.[1]).toBeCloseTo(1980, 10);
  });

  it('CTM 不可得（未渲染 / 旧测试环境）-> null', () => {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg') as unknown as SVGSVGElement;
    const g = document.createElementNS(NS, 'g') as unknown as SVGGElement;
    (g as unknown as { getScreenCTM: () => null }).getScreenCTM = () => null;
    expect(clientToWorld(svg, g, 0, 0)).toBeNull();
  });
});

// ============================================================
// edit-drag-snap US-001：吸附几何算子（contactT + firstContactDistance）
// ============================================================

describe('contactT (edit-drag-snap US-001)', () => {
  it('垂直命中：v(0,0) 沿 +x 到竖边 x=100（y∈[−10,50]）-> 精确 t=100（±1e-9）', () => {
    const t = contactT([0, 0], [1, 0], [100, -10], [100, 50]);
    expect(t).not.toBeNull();
    expect(Math.abs((t as number) - 100)).toBeLessThanOrEqual(1e-9);
  });

  it('斜向命中：v(0,0) 沿 (√2/2,√2/2) 到竖边 x=50 -> 精确 t=50√2（±1e-9）', () => {
    const inv = 1 / Math.SQRT2;
    const t = contactT([0, 0], [inv, inv], [50, 0], [50, 100]);
    expect(t).not.toBeNull();
    expect(Math.abs((t as number) - 50 * Math.SQRT2)).toBeLessThanOrEqual(1e-9);
  });

  it('顶点扫过所在直线但错过线段本体（延长线命中）-> null', () => {
    // 射线 y=0 永远够不到 y∈[10,110] 的竖边
    expect(contactT([0, 0], [1, 0], [100, 10], [100, 110])).toBeNull();
    // 斜向射线 (0.6,0.8) 过直线 x=50 时 y=50/0.6·0.8=66.7 ∉ [70,100] —— foot 在线段外
    expect(contactT([0, 0], [0.6, 0.8], [50, 70], [50, 100])).toBeNull();
  });

  it('近平行（弧片密集顶点实况）：斜率 1e-12 与恰共线 -> null 不抛异常', () => {
    // d=(100,−2e-12)：|cross(dir,d)|=2e-12 ≤ 1e-9·|d|≈1e-7 -> 近平行
    expect(contactT([0, 0], [1, 0], [100, 1e-12], [200, -1e-12])).toBeNull();
    // 恰共线（cross 恰 0，无 eps 会除零产 ±Infinity/NaN）
    expect(contactT([0, 0], [1, 0], [100, 5], [200, 5])).toBeNull();
  });

  it('触点在身后（负 t）原样返回 —— 过滤正 t 是调用方职责', () => {
    // v(0,0) 沿 +x：触点 x=−50 在身后 -> t=−50（命中点在线段 y∈[−10,10] 内）
    expect(contactT([0, 0], [1, 0], [-50, -10], [-50, 10])).toBe(-50);
  });

  it('端点命中含端（s=0/s=1 闭区间）', () => {
    // 命中点恰为线段起点 (100,0)
    expect(contactT([0, 0], [1, 0], [100, 0], [100, 100])).toBe(100);
    // 命中点恰为线段终点 (100,0)
    expect(contactT([0, 0], [1, 0], [100, 100], [100, 0])).toBe(100);
  });

  it('零长退化边 -> null（防御，不抛异常）', () => {
    expect(contactT([0, 0], [1, 0], [100, 0], [100, 0])).toBeNull();
  });
});

describe('firstContactDistance (edit-drag-snap US-001)', () => {
  const BAR: Polygon = [
    [50, 40],
    [150, 40],
    [150, 60],
    [50, 60],
  ];
  const RECT: Polygon = [
    [300, 0],
    [400, 0],
    [400, 100],
    [300, 100],
  ];

  it('矩形夹具：横条 vs 矩形沿 +x -> 解析精确 t=150（±1e-9）', () => {
    const t = firstContactDistance(BAR, RECT, [1, 0]);
    expect(t).not.toBeNull();
    expect(Math.abs((t as number) - 150)).toBeLessThanOrEqual(1e-9);
  });

  it('矩形夹具斜向 (0.6,0.8)：两向枚举同值 -> 精确 t=250/3（±1e-9）', () => {
    // 方块 [0,50]² 沿 3-4-5 方向撞大矩形 [100,300]x[100,200]：
    // ① moved 顶点 (50,50) 撞西墙 x=100：0.6t=50 -> t=250/3、y=50+0.8t=116.7 ∈ [100,200]；
    // ② obstacle 顶点 (100,100) 沿 −dir 撞 moved 东边 x=50：同 t=250/3（y=100−0.8t=33.3 ∈ [0,50]）。
    const sq: Polygon = [
      [0, 0],
      [50, 0],
      [50, 50],
      [0, 50],
    ];
    const big: Polygon = [
      [100, 100],
      [300, 100],
      [300, 200],
      [100, 200],
    ];
    const t = firstContactDistance(sq, big, [0.6, 0.8]);
    expect(t).not.toBeNull();
    expect(Math.abs((t as number) - 250 / 3)).toBeLessThanOrEqual(1e-9);
  });

  it('凹形 L 夹具：首触点恰落凹口内角 (50,50)，t=10 精确', () => {
    // L 形障碍（右上 50x50 缺口，凹口内角 = 反射顶点 (50,50)）；三角 moved 最西顶点
    // (60,50) 沿 −x 贴入：唯一 argmin 对 = (60,50) × 凹口西墙 (50,50)-(50,100) 的端点命中。
    const l: Polygon = [
      [0, 0],
      [100, 0],
      [100, 50],
      [50, 50],
      [50, 100],
      [0, 100],
    ];
    const tri: Polygon = [
      [60, 50],
      [90, 60],
      [65, 70],
    ];
    const t = firstContactDistance(tri, l, [-1, 0]);
    expect(t).toBe(10); // 整数算术全精确
    // 首触点重构：最西顶点 + t·dir = (50,50) —— 凹口内角
    const px = 60 + (t as number) * -1;
    const py = 50 + (t as number) * 0;
    expect(px).toBe(50);
    expect(py).toBe(50);
    // moved 底边与凹口底边 y=50 共线（近平行对）：跳过不抛异常，否则此处早已 ±Infinity 污染
  });

  it('近平行弧段密集顶点（弧片实况）：两向全无良态交点 -> null 不抛异常', () => {
    // 障碍 = 浅弧顶链（弦斜率 1e-10/10，|sinθ|≈1e-11 < 1e-9 全近平行）+ 东西竖壁 + 底边；
    // moved = 同款浅弧链抬高 5mm + 竖壁 —— 所有顶点射线要么撞近平行边（跳过）、要么
    // foot 落在竖壁 y 区间外（miss），两向枚举全 null。
    const arcObs: Polygon = [
      [300, 0],
      [310, 1e-10],
      [320, 2e-10],
      [330, 3e-10],
      [340, 4e-10],
      [350, 5e-10],
      [350, -50],
      [300, -50],
    ];
    const arcMov: Polygon = [
      [180, 5],
      [190, 5 + 1e-10],
      [200, 5 + 2e-10],
      [210, 5 + 3e-10],
      [220, 5 + 4e-10],
      [230, 5 + 5e-10],
      [230, 25],
      [180, 25],
    ];
    expect(firstContactDistance(arcMov, arcObs, [1, 0])).toBeNull();
  });

  it('近平行弧段在场但真触点良态：跳过后照常返回手算值 t=40', () => {
    // 同一弧障碍 vs 西侧方块（y∈[−20,−5]，全部落在障碍西壁 y∈[−50,0] 内）：
    // 近平行弧弦对被跳过（无 eps 时恰共线的水平底边会产 ±Infinity），真触点 =
    // 方块东边 x=260 撞西壁 x=300 -> t=40 精确。
    const arcObs: Polygon = [
      [300, 0],
      [310, 1e-10],
      [320, 2e-10],
      [330, 3e-10],
      [340, 4e-10],
      [350, 5e-10],
      [350, -50],
      [300, -50],
    ];
    const sq: Polygon = [
      [200, -20],
      [260, -20],
      [260, -5],
      [200, -5],
    ];
    expect(firstContactDistance(sq, arcObs, [1, 0])).toBe(40);
  });

  it('前方无交点（障碍在身后 / 射线错过）-> null', () => {
    const far: Polygon = [
      [-300, -100],
      [-100, -100],
      [-100, 100],
      [-300, 100],
    ];
    expect(firstContactDistance(BAR, far, [1, 0])).toBeNull(); // 障碍全在西，+x 远离
    expect(firstContactDistance(BAR, RECT, [0, -1])).toBeNull(); // 竖直向下错过（x 错位）
  });

  it('空多边形防御 -> null 不抛异常', () => {
    expect(firstContactDistance([], RECT, [1, 0])).toBeNull();
    expect(firstContactDistance(BAR, [], [1, 0])).toBeNull();
  });

  it('镜像+旋转 vs 直接构造同物理形态片同 t（口径无关性锁 —— 只读 worldPolygon）', () => {
    // 非对称五边形 base：镜像确实改变形态（fixture 有效性自证）
    const base: Polygon = [
      [0, 0],
      [80, 0],
      [100, 30],
      [40, 90],
      [-10, 40],
    ];
    const wall: Polygon = [
      [800, 300],
      [900, 300],
      [900, 500],
      [800, 500],
    ];
    // w1 = mirror+rot37：最东顶点 = 原 (0,0) -> (600,400)，撞墙 x=800 -> t=200 精确
    const w1 = transformPolygon(base, 37, [600, 400], true);
    const t1 = firstContactDistance(w1, wall, [1, 0]);
    expect(t1).toBe(200);
    // 直接构造同物理形态（x 预取负 + 无镜像 —— 既有恒等式同算术序）-> 逐位同 t
    const baseNeg: Polygon = base.map(([x, y]) => [-x, y] as Pt);
    expect(firstContactDistance(transformPolygon(baseNeg, 37, [600, 400]), wall, [1, 0])).toBe(t1);
    // 顶点序无关（逆序 / 换起点）-> 同 t（min 与枚举序无关）
    expect(firstContactDistance([...w1].reverse() as Polygon, wall, [1, 0])).toBe(t1);
    expect(
      firstContactDistance([...w1.slice(2), ...w1.slice(0, 2)] as Polygon, wall, [1, 0]),
    ).toBe(t1);
    // 无镜像片最东顶点 = (80,0) 变换后 -> t = 200−80·cos37° ≈ 136.11 ≠ 200（形态确实不同）
    const tPlain = firstContactDistance(transformPolygon(base, 37, [600, 400]), wall, [1, 0]);
    expect(tPlain).not.toBe(t1);
    expect(tPlain).toBeCloseTo(200 - 80 * Math.cos((37 * Math.PI) / 180), 9);
  });

  it('确定性：同输入双跑逐位全等（无 RNG）', () => {
    const l: Polygon = [
      [0, 0],
      [100, 0],
      [100, 50],
      [50, 50],
      [50, 100],
      [0, 100],
    ];
    const tri: Polygon = [
      [60, 50],
      [90, 60],
      [65, 70],
    ];
    expect(firstContactDistance(tri, l, [-1, 0])).toBe(firstContactDistance(tri, l, [-1, 0]));
    expect(firstContactDistance(BAR, RECT, [1, 0])).toBe(firstContactDistance(BAR, RECT, [1, 0]));
  });
});

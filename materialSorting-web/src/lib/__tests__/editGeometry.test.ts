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

import { describe, expect, it } from 'vitest';
import { pointsStr, r2 } from '../geometry';
import {
  bboxIntersect,
  bboxOf,
  clientToWorld,
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

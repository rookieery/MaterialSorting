// US-003 pointsStr 单测：
//   1) 与旧 legacy/app.js pointsStr 字节级一致（多组随机输入对比）
//   2) 旋转 0° + 平移 0 = 原多边形（仅做 r2 截断）
//   3) 旋转 90° 后再平移、绕原点旋转的可视化 sanity check
//   4) 单点 / 三点 / 多点 边界

import { describe, expect, it } from 'vitest';
import { pointsStr, r2 } from '../geometry';
import type { Polygon, Pt } from '../../types/piece';

// 旧 app.js pointsStr 副本（参考实现，用于字节级对比）。
function legacyPointsStr(poly: number[][], rot: number, tr: number[]): string {
  const legacyR2 = (x: number) => Math.round(x * 100) / 100;
  const r = (rot * Math.PI) / 180;
  const c = Math.cos(r);
  const s = Math.sin(r);
  const tx = tr[0];
  const ty = tr[1];
  let out = '';
  for (let i = 0; i < poly.length; i++) {
    const x = poly[i][0];
    const y = poly[i][1];
    out += (i ? ' ' : '') + legacyR2(x * c - y * s + tx) + ',' + legacyR2(x * s + y * c + ty);
  }
  return out;
}

describe('r2', () => {
  it('四舍五入到 2 位小数（与旧 app.js 一致）', () => {
    expect(r2(0)).toBe(0);
    expect(r2(1.234)).toBe(1.23);
    expect(r2(1.235)).toBe(1.24); // Math.round(123.5)/100 = 124/100 = 1.24
    expect(r2(1.5)).toBe(1.5);
    expect(r2(-1.234)).toBe(-1.23);
    expect(r2(123.456)).toBe(123.46);
  });
});

describe('pointsStr', () => {
  it('与旧 app.js 字节级一致（多组对比）', () => {
    const cases: Array<{ poly: number[][]; rot: number; tr: [number, number] }> = [
      // 单位正方形，无变换
      { poly: [[0, 0], [10, 0], [10, 10], [0, 10]], rot: 0, tr: [0, 0] },
      // 单位正方形，平移到 (100, 200)
      { poly: [[0, 0], [10, 0], [10, 10], [0, 10]], rot: 0, tr: [100, 200] },
      // 旋转 90° + 平移
      { poly: [[1, 0], [0, 1]], rot: 90, tr: [10, 20] },
      // 旋转 45°
      { poly: [[10, 0], [10, 10], [0, 10]], rot: 45, tr: [0, 0] },
      // 旋转 180°（= 镜像 + 平移）
      { poly: [[100, 200], [300, 400]], rot: 180, tr: [50, 50] },
      // 浮点截断（验 r2）
      { poly: [[1.23456, 2.34567], [-3.45678, 4.56789]], rot: 33.3, tr: [100.5, 200.5] },
      // 三角形大角度
      { poly: [[0, 0], [5, 0], [2.5, 4.33]], rot: 270, tr: [0, 0] },
      // 单点（边界）
      { poly: [[7, 8]], rot: 0, tr: [0, 0] },
      // 多点（裁片级真实规模，10+ 顶点）
      {
        poly: Array.from({ length: 12 }, (_, i) => [
          100 * Math.cos((i / 12) * 2 * Math.PI),
          100 * Math.sin((i / 12) * 2 * Math.PI),
        ]),
        rot: 17.5,
        tr: [1234.5, 6789.0],
      },
    ];

    for (const { poly, rot, tr } of cases) {
      const mine = pointsStr(poly as Polygon, rot, tr as Pt);
      const ref = legacyPointsStr(poly, rot, tr);
      expect(mine).toBe(ref);
    }
  });

  it('旋转 0° + 平移 (10,20)：每点 (x+10, y+20)', () => {
    const poly: Polygon = [
      [0, 0],
      [3, 0],
      [3, 4],
    ];
    expect(pointsStr(poly, 0, [10, 20])).toBe('10,20 13,20 13,24');
  });

  it('旋转 90°：原 (1,0) → (0,1)（绕原点）', () => {
    // c=cos90=0, s=sin90=1
    // (1,0) → (1*0 − 0*1, 1*1 + 0*0) = (0, 1)
    // (0,1) → (0*0 − 1*1, 0*1 + 1*0) = (−1, 0)
    const poly: Polygon = [[1, 0], [0, 1]];
    expect(pointsStr(poly, 90, [0, 0])).toBe('0,1 -1,0');
  });

  it('输出无尾随空格 / 无前导空格', () => {
    const poly: Polygon = [[0, 0], [1, 1], [2, 2]];
    const out = pointsStr(poly, 0, [0, 0]);
    expect(out.startsWith(' ')).toBe(false);
    expect(out.endsWith(' ')).toBe(false);
    // 点间恰好 1 个空格
    expect(out.match(/ /g)?.length).toBe(2);
  });
});

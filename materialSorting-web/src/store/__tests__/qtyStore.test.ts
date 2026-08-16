// qtyStore 单测（US-011 起源；矩阵化重构 US-001 改写：删 global 模式，加 setRowAll /
// baseValue / hydrate 单一入口）。
//
// 验收：
//   - clampQty 处理负数 / 小数 / NaN / 超 99 / 字符串 / 正常值（公式不变）
//   - getPieceDisplay 三分支 + null 码 sizeKey（editable 仅在「该码无此裁片」时 false）
//   - setPiecePerSize 写入值（clampQty）+ 保留 baseValue + 新建 label baseValue 兜底 1
//   - setRowAll 整行写入 + baseValue 置为填充值 + clamp + sizes 外码保留
//   - resetQuantities 清空为 {}
//   - hydrate 按 (label×size) 初始化每片默认 1 且 baseValue=1（全量重建）
//   - store 与 uploadStore 字段不重叠

import { beforeEach, describe, expect, it } from 'vitest';
import { clampQty, getPieceDisplay, useQtyStore } from '../qtyStore';
import { useUploadStore } from '../uploadStore';
import type { PieceQuantityMap } from '../../types/qty';

beforeEach(() => {
  // 重置 qtyStore，避免测试间残留
  useQtyStore.getState().resetQuantities();
});

describe('clampQty (US-011)', () => {
  it('negative to 0', () => {
    expect(clampQty(-5)).toBe(0);
    expect(clampQty(-0.1)).toBe(0);
  });

  it('decimal truncated', () => {
    expect(clampQty(3.7)).toBe(3);
    expect(clampQty(0.99)).toBe(0);
    expect(clampQty(99.9)).toBe(99);
  });

  it('NaN / non-number to 0', () => {
    expect(clampQty(NaN)).toBe(0);
    expect(clampQty(undefined)).toBe(0);
    expect(clampQty(null)).toBe(0);
    expect(clampQty({})).toBe(0);
    expect(clampQty([1, 2, 3])).toBe(0);
  });

  it('over 99 to 99', () => {
    expect(clampQty(100)).toBe(99);
    expect(clampQty(9999)).toBe(99);
  });

  it('string to integer', () => {
    expect(clampQty('5')).toBe(5);
    expect(clampQty('3.9')).toBe(3);
    expect(clampQty('abc')).toBe(0);
    expect(clampQty('')).toBe(0);
  });

  it('normal [0,99] pass through', () => {
    expect(clampQty(0)).toBe(0);
    expect(clampQty(50)).toBe(50);
    expect(clampQty(99)).toBe(99);
  });
});

describe('getPieceDisplay (US-001 简化后)', () => {
  it('label 未配置 -> {qty:0, editable:true}', () => {
    const map: PieceQuantityMap = {};
    const r = getPieceDisplay(map, 'A', 30);
    expect(r).toEqual({ qty: 0, editable: true });
  });

  it('该码有值 -> qty 从 perSize[sizeKey] 读，editable=true', () => {
    const map: PieceQuantityMap = {
      A: { perSize: { '28': 2, '30': 4 }, baseValue: 2 },
    };
    expect(getPieceDisplay(map, 'A', 30)).toEqual({ qty: 4, editable: true });
    expect(getPieceDisplay(map, 'A', 28)).toEqual({ qty: 2, editable: true });
  });

  it('该码无此裁片（perSize 缺 sizeKey）-> {qty:0, editable:false}', () => {
    const map: PieceQuantityMap = {
      A: { perSize: { '28': 2 }, baseValue: 1 },
    };
    // 32 码无 A 片（hydrate 只物化 doc 内存在的 (label,size)）
    expect(getPieceDisplay(map, 'A', 32)).toEqual({ qty: 0, editable: false });
  });

  it('显式 0（该码配置为不排）-> {qty:0, editable:true}', () => {
    const map: PieceQuantityMap = {
      A: { perSize: { '28': 0 }, baseValue: 1 },
    };
    expect(getPieceDisplay(map, 'A', 28)).toEqual({ qty: 0, editable: true });
  });

  it('null 码用 sizeKey null 作 key', () => {
    const map: PieceQuantityMap = {
      A: { perSize: { null: 9 }, baseValue: 1 },
    };
    expect(getPieceDisplay(map, 'A', null)).toEqual({ qty: 9, editable: true });
  });
});

describe('setPiecePerSize (US-011)', () => {
  it('写入值（经 clampQty），新建 label baseValue 兜底 1', () => {
    useQtyStore.getState().setPiecePerSize('A', 30, 5);
    expect(useQtyStore.getState().quantities.A).toEqual({
      perSize: { '30': 5 },
      baseValue: 1,
    });
  });

  it('每码 / 每 label 独立写入互不干扰', () => {
    useQtyStore.getState().setPiecePerSize('A', 28, 2);
    useQtyStore.getState().setPiecePerSize('A', 30, 4);
    useQtyStore.getState().setPiecePerSize('B', 28, 6);
    const map = useQtyStore.getState().quantities;
    expect(map.A.perSize).toEqual({ '28': 2, '30': 4 });
    expect(map.B.perSize).toEqual({ '28': 6 });
  });

  it('值经 clampQty（负数 / 超 99 / 小数）', () => {
    useQtyStore.getState().setPiecePerSize('A', 30, -1);
    expect(useQtyStore.getState().quantities.A.perSize['30']).toBe(0);
    useQtyStore.getState().setPiecePerSize('A', 32, 200);
    expect(useQtyStore.getState().quantities.A.perSize['32']).toBe(99);
    useQtyStore.getState().setPiecePerSize('A', 34, 3.9);
    expect(useQtyStore.getState().quantities.A.perSize['34']).toBe(3);
  });

  it('格内编辑不动 baseValue（特例高亮基准保持）', () => {
    useQtyStore.getState().setRowAll('A', [28, 30], 2);
    useQtyStore.getState().setPiecePerSize('A', 30, 5);
    const q = useQtyStore.getState().quantities.A;
    expect(q.perSize).toEqual({ '28': 2, '30': 5 });
    expect(q.baseValue).toBe(2);
  });
});

describe('setRowAll (US-001 整行填充)', () => {
  it('setRowAll A [28,29,30] 2 -> 三码=2 且 baseValue===2', () => {
    useQtyStore.getState().setRowAll('A', [28, 29, 30], 2);
    const q = useQtyStore.getState().quantities.A;
    expect(q.perSize).toEqual({ '28': 2, '29': 2, '30': 2 });
    expect(q.baseValue).toBe(2);
  });

  it('value 经 clampQty（负数→0，超 99→99）', () => {
    useQtyStore.getState().setRowAll('A', [28, 30], -3);
    expect(useQtyStore.getState().quantities.A).toEqual({
      perSize: { '28': 0, '30': 0 },
      baseValue: 0,
    });
    useQtyStore.getState().setRowAll('A', [28, 30], 150);
    expect(useQtyStore.getState().quantities.A).toEqual({
      perSize: { '28': 99, '30': 99 },
      baseValue: 99,
    });
  });

  it('sizes 外的既有码保留原值（非破坏合并）', () => {
    useQtyStore.getState().setPiecePerSize('A', 32, 7);
    useQtyStore.getState().setRowAll('A', [28, 30], 2);
    expect(useQtyStore.getState().quantities.A.perSize).toEqual({
      '28': 2,
      '30': 2,
      '32': 7,
    });
  });

  it('二次填充覆盖旧值 + baseValue（含 null 码 sizeKey）', () => {
    useQtyStore.getState().setRowAll('A', [28, null], 2);
    useQtyStore.getState().setRowAll('A', [28, null], 3);
    const q = useQtyStore.getState().quantities.A;
    expect(q.perSize).toEqual({ '28': 3, null: 3 });
    expect(q.baseValue).toBe(3);
  });
});

describe('resetQuantities (US-011)', () => {
  it('clears to {}', () => {
    useQtyStore.getState().setPiecePerSize('A', 30, 5);
    useQtyStore.getState().setRowAll('B', [28], 7);
    expect(Object.keys(useQtyStore.getState().quantities).length).toBe(2);
    useQtyStore.getState().resetQuantities();
    expect(useQtyStore.getState().quantities).toEqual({});
  });
});

describe('hydrate (解析后默认数量 + baseValue=1)', () => {
  it('按 (label×size) 初始化每个码下默认 1 且 baseValue=1', () => {
    // 模拟 doc：28 码 A/B，30 码 A（同 label 跨码）
    useQtyStore.getState().hydrate([
      { label: 'A', size: 28 },
      { label: 'B', size: 28 },
      { label: 'A', size: 30 },
    ]);
    const map = useQtyStore.getState().quantities;
    expect(map.A).toEqual({ perSize: { '28': 1, '30': 1 }, baseValue: 1 });
    expect(map.B).toEqual({ perSize: { '28': 1 }, baseValue: 1 });
  });

  it('null 码（通用）用 sizeKey null 作 key', () => {
    useQtyStore.getState().hydrate([{ label: 'A', size: null }]);
    const map = useQtyStore.getState().quantities;
    expect(map.A).toEqual({ perSize: { null: 1 }, baseValue: 1 });
    expect(getPieceDisplay(map, 'A', null).qty).toBe(1);
  });

  it('全量重建：旧数量 / 旧 baseValue 被新 doc 默认覆盖（重传场景）', () => {
    // 先填一些旧数量
    useQtyStore.getState().setPiecePerSize('A', 28, 9);
    useQtyStore.getState().setRowAll('B', [30], 7);
    expect(Object.keys(useQtyStore.getState().quantities).length).toBe(2);
    // 重传：新 doc 只有 28 码 A 片 → hydrate 全量重建，旧 B / 旧值 9 被清
    useQtyStore.getState().hydrate([{ label: 'A', size: 28 }]);
    const map = useQtyStore.getState().quantities;
    expect(Object.keys(map).sort()).toEqual(['A']);
    expect(map.A).toEqual({ perSize: { '28': 1 }, baseValue: 1 });
  });

  it('空 entries → 空 map（后续 serializeQuantities 返 null）', () => {
    useQtyStore.getState().setPiecePerSize('A', 28, 9);
    useQtyStore.getState().hydrate([]);
    expect(useQtyStore.getState().quantities).toEqual({});
  });
});

describe('store independence (US-011)', () => {
  it('qtyStore and uploadStore fields do not overlap', () => {
    // qtyStore only holds quantities + 4 actions（US-001 合并 hydrate 双入口 + setRowAll）
    const qKeys = Object.keys(useQtyStore.getState()).filter((k) => k !== 'quantities');
    expect(qKeys.sort()).toEqual(['hydrate', 'resetQuantities', 'setPiecePerSize', 'setRowAll']);
    // uploadStore does not hold quantities
    expect(useUploadStore.getState()).not.toHaveProperty('quantities');
  });

  it('qtyStore reset does not affect uploadStore and vice versa', () => {
    useQtyStore.getState().setPiecePerSize('A', 30, 5);
    useUploadStore.setState({ status: 'done', activeSize: 30 });
    useQtyStore.getState().resetQuantities();
    // qtyStore cleared, uploadStore preserved
    expect(useQtyStore.getState().quantities).toEqual({});
    expect(useUploadStore.getState().status).toBe('done');
    expect(useUploadStore.getState().activeSize).toBe(30);
    // reverse direction
    useQtyStore.getState().setPiecePerSize('B', 32, 2);
    useUploadStore.getState().reset();
    expect(useQtyStore.getState().quantities.B).toBeDefined();
    expect(useUploadStore.getState().status).toBe('idle');
  });
});

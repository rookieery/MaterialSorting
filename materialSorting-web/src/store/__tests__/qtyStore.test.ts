// US-011 qtyStore 单测：clampQty 6 + getPieceDisplay 9 + setPiecePerSize 4 + setPieceGlobal 2
// + resetQuantities 1 + store 独立性 2 = 24 项。
//
// 验收：
//   - clampQty 处理负数 / 小数 / NaN / 超 99 / 字符串 / 正常值
//   - getPieceDisplay 四分支 + null 码 sizeKey/sizeLabel
//   - setPiecePerSize 写入值 + 从 global 切回时 globalValue 继承到 source 码
//   - setPieceGlobal 切模式后, 非 source 码 editable=false 且 reason 含来源码
//   - resetQuantities 清空为 {}
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

describe('getPieceDisplay (US-011)', () => {
  it('label not configured -> {qty:0, editable:true, reason:null}', () => {
    const map: PieceQuantityMap = {};
    const r = getPieceDisplay(map, 'A', 30);
    expect(r).toEqual({ qty: 0, editable: true, reason: null });
  });

  it('per-size mode -> qty from perSize[sizeKey]', () => {
    const map: PieceQuantityMap = {
      A: { mode: 'per-size', perSize: { '28': 2, '30': 4 }, globalValue: 0, globalSource: null },
    };
    expect(getPieceDisplay(map, 'A', 30).qty).toBe(4);
    expect(getPieceDisplay(map, 'A', 28).qty).toBe(2);
  });

  it('per-size mode size unset -> qty=0', () => {
    const map: PieceQuantityMap = {
      A: { mode: 'per-size', perSize: { '28': 2 }, globalValue: 0, globalSource: null },
    };
    const r = getPieceDisplay(map, 'A', 32);
    expect(r).toEqual({ qty: 0, editable: true, reason: null });
  });

  it('global mode globalSource===size -> editable=true', () => {
    const map: PieceQuantityMap = {
      A: { mode: 'global', perSize: {}, globalValue: 7, globalSource: 30 },
    };
    const r = getPieceDisplay(map, 'A', 30);
    expect(r).toEqual({ qty: 7, editable: true, reason: null });
  });

  it('global mode globalSource!==size -> editable=false + reason has source size', () => {
    const map: PieceQuantityMap = {
      A: { mode: 'global', perSize: {}, globalValue: 7, globalSource: 30 },
    };
    const r = getPieceDisplay(map, 'A', 32);
    expect(r.qty).toBe(7);
    expect(r.editable).toBe(false);
    expect(r.reason).toContain('30');
  });

  it('null size uses sizeKey null (per-size)', () => {
    const map: PieceQuantityMap = {
      A: { mode: 'per-size', perSize: { null: 9 }, globalValue: 0, globalSource: null },
    };
    expect(getPieceDisplay(map, 'A', null).qty).toBe(9);
  });

  it('null size with source=28 -> reason contains source size 28', () => {
    const map: PieceQuantityMap = {
      A: { mode: 'global', perSize: {}, globalValue: 3, globalSource: 28 },
    };
    const r = getPieceDisplay(map, 'A', null);
    expect(r.editable).toBe(false);
    expect(r.reason).toContain('28');
  });

  it('global source=null, access null -> editable=true (source matches)', () => {
    const map: PieceQuantityMap = {
      A: { mode: 'global', perSize: {}, globalValue: 5, globalSource: null },
    };
    expect(getPieceDisplay(map, 'A', null)).toEqual({ qty: 5, editable: true, reason: null });
  });

  it('global source=null, access number -> reason contains liang-yong (universal) label', () => {
    const map: PieceQuantityMap = {
      A: { mode: 'global', perSize: {}, globalValue: 5, globalSource: null },
    };
    const r = getPieceDisplay(map, 'A', 30);
    expect(r.editable).toBe(false);
    // sizeLabel(null) = universal code label
    expect(r.reason).toContain('通用');
  });
});

describe('setPiecePerSize (US-011)', () => {
  it('per-size mode writes value (via clampQty)', () => {
    useQtyStore.getState().setPiecePerSize('A', 30, 5);
    const map = useQtyStore.getState().quantities;
    expect(map.A).toEqual({
      mode: 'per-size',
      perSize: { '30': 5 },
      globalValue: 0,
      globalSource: null,
    });
  });

  it('switching from global inherits globalValue to source size + writes new value', () => {
    // first set global: source=28, value=7
    useQtyStore.getState().setPieceGlobal('A', 28, 7);
    // switch back to per-size at size 30 with value=3
    useQtyStore.getState().setPiecePerSize('A', 30, 3);
    const q = useQtyStore.getState().quantities.A;
    expect(q.mode).toBe('per-size');
    expect(q.globalValue).toBe(0);
    expect(q.globalSource).toBeNull();
    // globalValue 7 inherited to source size 28
    expect(q.perSize['28']).toBe(7);
    // new value 3 written to size 30
    expect(q.perSize['30']).toBe(3);
  });

  it('per-size independent writes per size do not interfere', () => {
    useQtyStore.getState().setPiecePerSize('A', 28, 2);
    useQtyStore.getState().setPiecePerSize('A', 30, 4);
    useQtyStore.getState().setPiecePerSize('B', 28, 6);
    const map = useQtyStore.getState().quantities;
    expect(map.A.perSize).toEqual({ '28': 2, '30': 4 });
    expect(map.B.perSize).toEqual({ '28': 6 });
  });

  it('value via clampQty (negative/over-99/decimal)', () => {
    useQtyStore.getState().setPiecePerSize('A', 30, -1);
    expect(useQtyStore.getState().quantities.A.perSize['30']).toBe(0);
    useQtyStore.getState().setPiecePerSize('A', 32, 200);
    expect(useQtyStore.getState().quantities.A.perSize['32']).toBe(99);
    useQtyStore.getState().setPiecePerSize('A', 34, 3.9);
    expect(useQtyStore.getState().quantities.A.perSize['34']).toBe(3);
  });
});

describe('setPieceGlobal (US-011)', () => {
  it('after setPieceGlobal, non-source size returns editable=false + reason has source size', () => {
    useQtyStore.getState().setPieceGlobal('A', 28, 8);
    const map = useQtyStore.getState().quantities;
    expect(map.A).toEqual({
      mode: 'global',
      perSize: {},
      globalValue: 8,
      globalSource: 28,
    });
    const r = getPieceDisplay(map, 'A', 30);
    expect(r.editable).toBe(false);
    expect(r.reason).toContain('28');
    // source size itself remains editable
    expect(getPieceDisplay(map, 'A', 28).editable).toBe(true);
  });

  it('setPieceGlobal twice to a different source overwrites previous', () => {
    useQtyStore.getState().setPieceGlobal('A', 28, 8);
    useQtyStore.getState().setPieceGlobal('A', 30, 5);
    const q = useQtyStore.getState().quantities.A;
    expect(q.globalSource).toBe(30);
    expect(q.globalValue).toBe(5);
  });
});

describe('resetQuantities (US-011)', () => {
  it('clears to {}', () => {
    useQtyStore.getState().setPiecePerSize('A', 30, 5);
    useQtyStore.getState().setPieceGlobal('B', 28, 7);
    expect(Object.keys(useQtyStore.getState().quantities).length).toBe(2);
    useQtyStore.getState().resetQuantities();
    expect(useQtyStore.getState().quantities).toEqual({});
  });
});

describe('store independence (US-011)', () => {
  it('qtyStore and uploadStore fields do not overlap', () => {
    // qtyStore only holds quantities + 3 actions
    const qKeys = Object.keys(useQtyStore.getState()).filter((k) => k !== 'quantities');
    expect(qKeys.sort()).toEqual(['resetQuantities', 'setPieceGlobal', 'setPiecePerSize']);
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

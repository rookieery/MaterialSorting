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
    const r = getPieceDisplay(map, 'g01', 30);
    expect(r).toEqual({ qty: 0, editable: true });
  });

  it('该码有值 -> qty 从 perSize[sizeKey] 读，editable=true', () => {
    const map: PieceQuantityMap = {
      g01: { perSize: { '28': 2, '30': 4 }, baseValue: 2 },
    };
    expect(getPieceDisplay(map, 'g01', 30)).toEqual({ qty: 4, editable: true });
    expect(getPieceDisplay(map, 'g01', 28)).toEqual({ qty: 2, editable: true });
  });

  it('该码无此裁片（perSize 缺 sizeKey）-> {qty:0, editable:false}', () => {
    const map: PieceQuantityMap = {
      g01: { perSize: { '28': 2 }, baseValue: 1 },
    };
    // 32 码无 A 片（hydrate 只物化 doc 内存在的 (label,size)）
    expect(getPieceDisplay(map, 'g01', 32)).toEqual({ qty: 0, editable: false });
  });

  it('显式 0（该码配置为不排）-> {qty:0, editable:true}', () => {
    const map: PieceQuantityMap = {
      g01: { perSize: { '28': 0 }, baseValue: 1 },
    };
    expect(getPieceDisplay(map, 'g01', 28)).toEqual({ qty: 0, editable: true });
  });

  it('null 码用 sizeKey null 作 key', () => {
    const map: PieceQuantityMap = {
      g01: { perSize: { null: 9 }, baseValue: 1 },
    };
    expect(getPieceDisplay(map, 'g01', null)).toEqual({ qty: 9, editable: true });
  });
});

describe('setPiecePerSize (US-011)', () => {
  it('写入值（经 clampQty），新建 label baseValue 兜底 1', () => {
    useQtyStore.getState().setPiecePerSize('g01', 30, 5);
    expect(useQtyStore.getState().quantities.g01).toEqual({
      perSize: { '30': 5 },
      baseValue: 1,
    });
  });

  it('每码 / 每 label 独立写入互不干扰', () => {
    useQtyStore.getState().setPiecePerSize('g01', 28, 2);
    useQtyStore.getState().setPiecePerSize('g01', 30, 4);
    useQtyStore.getState().setPiecePerSize('g02', 28, 6);
    const map = useQtyStore.getState().quantities;
    expect(map.g01.perSize).toEqual({ '28': 2, '30': 4 });
    expect(map.g02.perSize).toEqual({ '28': 6 });
  });

  it('值经 clampQty（负数 / 超 99 / 小数）', () => {
    useQtyStore.getState().setPiecePerSize('g01', 30, -1);
    expect(useQtyStore.getState().quantities.g01.perSize['30']).toBe(0);
    useQtyStore.getState().setPiecePerSize('g01', 32, 200);
    expect(useQtyStore.getState().quantities.g01.perSize['32']).toBe(99);
    useQtyStore.getState().setPiecePerSize('g01', 34, 3.9);
    expect(useQtyStore.getState().quantities.g01.perSize['34']).toBe(3);
  });

  it('格内编辑不动 baseValue（特例高亮基准保持）', () => {
    useQtyStore.getState().setRowAll('g01', [28, 30], 2);
    useQtyStore.getState().setPiecePerSize('g01', 30, 5);
    const q = useQtyStore.getState().quantities.g01;
    expect(q.perSize).toEqual({ '28': 2, '30': 5 });
    expect(q.baseValue).toBe(2);
  });
});

describe('setRowAll (US-001 整行填充)', () => {
  it('setRowAll A [28,29,30] 2 -> 三码=2 且 baseValue===2', () => {
    useQtyStore.getState().setRowAll('g01', [28, 29, 30], 2);
    const q = useQtyStore.getState().quantities.g01;
    expect(q.perSize).toEqual({ '28': 2, '29': 2, '30': 2 });
    expect(q.baseValue).toBe(2);
  });

  it('value 经 clampQty（负数→0，超 99→99）', () => {
    useQtyStore.getState().setRowAll('g01', [28, 30], -3);
    expect(useQtyStore.getState().quantities.g01).toEqual({
      perSize: { '28': 0, '30': 0 },
      baseValue: 0,
    });
    useQtyStore.getState().setRowAll('g01', [28, 30], 150);
    expect(useQtyStore.getState().quantities.g01).toEqual({
      perSize: { '28': 99, '30': 99 },
      baseValue: 99,
    });
  });

  it('sizes 外的既有码保留原值（非破坏合并）', () => {
    useQtyStore.getState().setPiecePerSize('g01', 32, 7);
    useQtyStore.getState().setRowAll('g01', [28, 30], 2);
    expect(useQtyStore.getState().quantities.g01.perSize).toEqual({
      '28': 2,
      '30': 2,
      '32': 7,
    });
  });

  it('二次填充覆盖旧值 + baseValue（含 null 码 sizeKey）', () => {
    useQtyStore.getState().setRowAll('g01', [28, null], 2);
    useQtyStore.getState().setRowAll('g01', [28, null], 3);
    const q = useQtyStore.getState().quantities.g01;
    expect(q.perSize).toEqual({ '28': 3, null: 3 });
    expect(q.baseValue).toBe(3);
  });
});

describe('resetQuantities (US-011)', () => {
  it('clears to {}', () => {
    useQtyStore.getState().setPiecePerSize('g01', 30, 5);
    useQtyStore.getState().setRowAll('g02', [28], 7);
    expect(Object.keys(useQtyStore.getState().quantities).length).toBe(2);
    useQtyStore.getState().resetQuantities();
    expect(useQtyStore.getState().quantities).toEqual({});
  });
});

describe('hydrate (解析后默认数量 + baseValue=1)', () => {
  it('按 (label×size) 初始化每个码下默认 1 且 baseValue=1', () => {
    // 模拟 doc：28 码 A/B，30 码 A（同 label 跨码）
    useQtyStore.getState().hydrate([
      { label: 'g01', size: 28 },
      { label: 'g02', size: 28 },
      { label: 'g01', size: 30 },
    ]);
    const map = useQtyStore.getState().quantities;
    expect(map.g01).toEqual({ perSize: { '28': 1, '30': 1 }, baseValue: 1 });
    expect(map.g02).toEqual({ perSize: { '28': 1 }, baseValue: 1 });
  });

  it('null 码（通用）用 sizeKey null 作 key', () => {
    useQtyStore.getState().hydrate([{ label: 'g01', size: null }]);
    const map = useQtyStore.getState().quantities;
    expect(map.g01).toEqual({ perSize: { null: 1 }, baseValue: 1 });
    expect(getPieceDisplay(map, 'g01', null).qty).toBe(1);
  });

  it('全量重建：旧数量 / 旧 baseValue 被新 doc 默认覆盖（重传场景）', () => {
    // 先填一些旧数量
    useQtyStore.getState().setPiecePerSize('g01', 28, 9);
    useQtyStore.getState().setRowAll('g02', [30], 7);
    expect(Object.keys(useQtyStore.getState().quantities).length).toBe(2);
    // 重传：新 doc 只有 28 码 A 片 → hydrate 全量重建，旧 B / 旧值 9 被清
    useQtyStore.getState().hydrate([{ label: 'g01', size: 28 }]);
    const map = useQtyStore.getState().quantities;
    expect(Object.keys(map).sort()).toEqual(['g01']);
    expect(map.g01).toEqual({ perSize: { '28': 1 }, baseValue: 1 });
  });

  it('空 entries → 空 map（后续 serializeQuantities 返 null）', () => {
    useQtyStore.getState().setPiecePerSize('g01', 28, 9);
    useQtyStore.getState().hydrate([]);
    expect(useQtyStore.getState().quantities).toEqual({});
  });
});

describe('store independence (US-011)', () => {
  it('qtyStore and uploadStore fields do not overlap', () => {
    // qtyStore only holds quantities + 5 actions（US-001 合并 hydrate 双入口 + setRowAll；
    // US-004 状态文件恢复 hydrateFlat 扁平实值覆盖）
    const qKeys = Object.keys(useQtyStore.getState()).filter((k) => k !== 'quantities');
    expect(qKeys.sort()).toEqual(['hydrate', 'hydrateFlat', 'resetQuantities', 'setPiecePerSize', 'setRowAll']);
    // uploadStore does not hold quantities
    expect(useUploadStore.getState()).not.toHaveProperty('quantities');
  });

  it('qtyStore reset does not affect uploadStore and vice versa', () => {
    useQtyStore.getState().setPiecePerSize('g01', 30, 5);
    useUploadStore.setState({ status: 'done', activeSize: 30 });
    useQtyStore.getState().resetQuantities();
    // qtyStore cleared, uploadStore preserved
    expect(useQtyStore.getState().quantities).toEqual({});
    expect(useUploadStore.getState().status).toBe('done');
    expect(useUploadStore.getState().activeSize).toBe(30);
    // reverse direction
    useQtyStore.getState().setPiecePerSize('g02', 32, 2);
    useUploadStore.getState().reset();
    expect(useQtyStore.getState().quantities.g02).toBeDefined();
    expect(useUploadStore.getState().status).toBe('idle');
  });
});

// ============================================================
// hydrateFlat（状态文件 US-004）：{label:{sizeKey:N}} 扁平实值覆盖 ——
// 恢复编排 applyRestorePayload 在 hydrate（默认 1 物化）之后调用。
// ============================================================
describe('hydrateFlat (US-004 状态文件恢复)', () => {
  it('实值覆盖：hydrate 物化的默认 1 被 flat 实值覆写，flat 缺键保留 1', () => {
    useQtyStore.getState().hydrate([
      { label: 'g01', size: 28 },
      { label: 'g01', size: 30 },
      { label: 'g02', size: 28 },
    ]);
    useQtyStore.getState().hydrateFlat({ g01: { '28': 3, '30': 0 } });
    const map = useQtyStore.getState().quantities;
    // g01: 28 码覆写 3、30 码覆写 0（显式 0 = 排除语义可追溯）；g02 未入 flat → 默认 1。
    expect(map.g01).toEqual({ perSize: { '28': 3, '30': 0 }, baseValue: 1 });
    expect(map.g02).toEqual({ perSize: { '28': 1 }, baseValue: 1 });
  });

  it('null / 空对象 → no-op（纯配置档 = 后端 demand 全 1 口径，默认 1 即终态）', () => {
    useQtyStore.getState().hydrate([{ label: 'g01', size: 28 }]);
    useQtyStore.getState().hydrateFlat(null);
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(1);
    useQtyStore.getState().hydrateFlat({});
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(1);
  });

  it('flat 多出的 sizeKey 并入（手改文件补键无害：QtyMatrix 只渲染 doc 格）', () => {
    useQtyStore.getState().hydrate([{ label: 'g01', size: 28 }]);
    useQtyStore.getState().hydrateFlat({ g01: { '28': 2, '99': 7 } });
    expect(useQtyStore.getState().quantities.g01.perSize).toEqual({ '28': 2, '99': 7 });
  });

  it('flat 多出的 label 不新建行（无 baseValue 锚，避免幽灵行）', () => {
    useQtyStore.getState().hydrate([{ label: 'g01', size: 28 }]);
    useQtyStore.getState().hydrateFlat({ g01: { '28': 2 }, gX: { '28': 5 } });
    const map = useQtyStore.getState().quantities;
    expect(Object.keys(map).sort()).toEqual(['g01']);
  });

  it('数值经 clampQty 归整（线格式契约 0-99 整数：小数截断 / 越界钳制 / 非数归 0）', () => {
    useQtyStore.getState().hydrate([{ label: 'g01', size: 28 }]);
    useQtyStore.getState().hydrateFlat({ g01: { '28': 3.9 } });
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(3);
    useQtyStore.getState().hydrateFlat({ g01: { '28': 150 } });
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(99);
    // 'x' 模拟手改文件的非法值（线格式契约外输入，clampQty 归 0）
    useQtyStore.getState().hydrateFlat({ g01: { '28': 'x' as unknown as number } });
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(0);
  });

  it('baseValue 保留物化值 1（状态文件不含 baseValue —— 特例高亮基准与初始态同锚）', () => {
    useQtyStore.getState().hydrate([{ label: 'g01', size: 28 }]);
    useQtyStore.getState().hydrateFlat({ g01: { '28': 5 } });
    expect(useQtyStore.getState().quantities.g01.baseValue).toBe(1);
  });
});

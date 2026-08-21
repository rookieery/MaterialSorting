// US-019 collectParams 单测（主面板精简后；US-003 起 per_type 键 = 裁片 g 码）：
//   1) params 永远全 0（d_ext/d_int/tol_ext/tol_int 主面板输入已删，全交高级配置弹窗 per_type）。
//   2) per_type 解析逻辑保留不变：仅 trim()!=='' 写入；空 → null；任一档非空 → 创建 entry。
//   3) parseTime / parseSeed / parseSeedCount 与旧 vanilla 实现 `parseInt(...) || fallback` 一致。
// US-012 band 三态（collectBand / collectStartContext.band）+ bandMemberCount 三态。

import { describe, expect, it } from 'vitest';
import {
  bandMemberCount,
  collectBand,
  collectParams,
  collectStartContext,
  DEFAULT_FORM,
  parseGate,
  parseSeed,
  parseSeedCount,
  parseTime,
  serializeQuantities,
  type FormState,
} from '../params';
import type { PerTypeOverrides, SolveParams } from '../../types/v03';
import type { PieceQuantityMap } from '../../types/qty';

function makeForm(overrides: Partial<FormState> = {}): FormState {
  return {
    ...DEFAULT_FORM,
    per_type: { ...DEFAULT_FORM.per_type },
    ...overrides,
  };
}

describe('collectParams (US-019)', () => {
  it('默认表单：params 全 0；per_type = null（全空）', () => {
    const out = collectParams(DEFAULT_FORM);
    expect(out.params).toEqual<SolveParams>({
      d_ext: 0,
      d_int: 0,
      tol_ext: 0,
      tol_int: 0,
    });
    expect(out.per_type).toBeNull();
  });

  it('US-017: DEFAULT_FORM.sizes 默认空数组（强制用户选）', () => {
    expect(DEFAULT_FORM.sizes).toEqual([]);
  });

  it('US-019: FormState 不再含 d_ext/d_int/tol_ext/tol_int 字段（已迁至高级配置弹窗）', () => {
    // 类型层断言：FormState 不应包含已删字段（编译期保护，运行时 noop）。
    const form: FormState = DEFAULT_FORM;
    expect(form).not.toHaveProperty('d_ext');
    expect(form).not.toHaveProperty('d_int');
    expect(form).not.toHaveProperty('tol_ext');
    expect(form).not.toHaveProperty('tol_int');
  });

  it('US-019: params 永远全 0，无论 form 怎样构造（per_type 是唯一 d/tol 入口）', () => {
    // 各种 per_type 填法的 form，params 都应保持全 0
    const forms: FormState[] = [
      makeForm(),
      makeForm({
        per_type: { ...DEFAULT_FORM.per_type, g01: { d: '1', tol: '' } },
      }),
      makeForm({
        per_type: {
          ...DEFAULT_FORM.per_type,
          g01: { d: '2', tol: '1' },
          g02: { d: '', tol: '45' },
        },
      }),
      makeForm({
        per_type: {
          g01: { d: '2', tol: '1' },
          g03: { d: '2', tol: '1' },
          g04: { d: '0.4', tol: '3' },
          g05: { d: '0.4', tol: '30' },
          g06: { d: '0.4', tol: '1' },
          g07: { d: '0.4', tol: '3' },
          g08: { d: '10', tol: '15' },
          g09: { d: '10', tol: '15' },
          g10: { d: '5', tol: '8' },
          g02: { d: '10', tol: '45' },
        },
      }),
    ];
    for (const form of forms) {
      expect(collectParams(form).params).toEqual<SolveParams>({
        d_ext: 0,
        d_int: 0,
        tol_ext: 0,
        tol_int: 0,
      });
    }
  });

  it('per_type 单档非空 → entry 仅写该档；另一档缺省', () => {
    const form = makeForm({
      per_type: { ...DEFAULT_FORM.per_type, g08: { d: '7', tol: '' } },
    });
    const out = collectParams(form);
    expect(out.per_type).toEqual<PerTypeOverrides>({
      g08: { d: 7 },
    });
  });

  it('per_type d 与 tol 都空白 → 不创建 entry（与旧 vanilla 实现 inp.value.trim() 一致）', () => {
    const form = makeForm({
      per_type: { ...DEFAULT_FORM.per_type, g04: { d: '   ', tol: '' } },
    });
    expect(collectParams(form).per_type).toBeNull();
  });

  it('per_type 多片型混合（g01 d+tol，g02 仅 tol）正确聚合', () => {
    const form = makeForm({
      per_type: {
        ...DEFAULT_FORM.per_type,
        g01: { d: '2', tol: '1' },
        g02: { d: '', tol: '45' },
      },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      g01: { d: 2, tol: 1 },
      g02: { tol: 45 },
    });
  });

  it('per_type 含空白（trim 后空 → 不写入；只非空档写）', () => {
    const form = makeForm({
      per_type: { ...DEFAULT_FORM.per_type, g01: { d: '  ', tol: ' 1 ' } },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      g01: { tol: 1 },
    });
  });

  it('per_type 显式 "0" 也写入（区分空 vs "0"，与旧 vanilla 实现一致）', () => {
    const form = makeForm({
      per_type: { ...DEFAULT_FORM.per_type, g07: { d: '0', tol: '0' } },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      g07: { d: 0, tol: 0 },
    });
  });

  it('per_type 全 g 码填满（示例覆盖值，均在全局上限 10/45 内）→ 所有 10 个 entry 写入', () => {
    const form = makeForm({
      per_type: {
        g01: { d: '2', tol: '1' },
        g03: { d: '2', tol: '1' },
        g04: { d: '0.4', tol: '3' },
        g05: { d: '0.4', tol: '30' },
        g06: { d: '0.4', tol: '1' },
        g07: { d: '0.4', tol: '3' },
        g08: { d: '10', tol: '15' },
        g09: { d: '10', tol: '15' },
        g10: { d: '5', tol: '8' },
        g02: { d: '10', tol: '45' },
      },
    });
    const out = collectParams(form);
    expect(Object.keys(out.per_type!)).toHaveLength(10);
    // params 仍然全 0
    expect(out.params).toEqual<SolveParams>({
      d_ext: 0,
      d_int: 0,
      tol_ext: 0,
      tol_int: 0,
    });
  });
});

describe('parseTime / parseSeed (US-004)', () => {
  it('parseTime：默认 120 → 120；空串 → fallback 120；非法 → fallback 120', () => {
    expect(parseTime(DEFAULT_FORM)).toBe(120);
    expect(parseTime(makeForm({ time: '' }))).toBe(120);
    expect(parseTime(makeForm({ time: 'abc' }))).toBe(120);
    expect(parseTime(makeForm({ time: '120' }))).toBe(120);
    expect(parseTime(makeForm({ time: '600' }))).toBe(600);
  });

  it('parseSeed：默认 0 → 0；空串 → fallback 0；非法 → fallback 0', () => {
    expect(parseSeed(DEFAULT_FORM)).toBe(0);
    expect(parseSeed(makeForm({ seed: '' }))).toBe(0);
    expect(parseSeed(makeForm({ seed: 'abc' }))).toBe(0);
    expect(parseSeed(makeForm({ seed: '7' }))).toBe(7);
  });
});

describe('parseSeedCount (US-005)', () => {
  // 旧 vanilla 实现 startSolve 内：multi ? clamp(count||3, 2, 6) : 1
  it('multi_seed=false → 1（无论 seed_count 填什么）', () => {
    expect(parseSeedCount(DEFAULT_FORM)).toBe(1);
    expect(parseSeedCount(makeForm({ multi_seed: false, seed_count: '5' }))).toBe(1);
    expect(parseSeedCount(makeForm({ multi_seed: false, seed_count: '' }))).toBe(1);
  });

  it('multi_seed=true + count=3（默认）→ 3', () => {
    expect(parseSeedCount(makeForm({ multi_seed: true, seed_count: '3' }))).toBe(3);
  });

  it('multi_seed=true + count=2 → 2（下界）', () => {
    expect(parseSeedCount(makeForm({ multi_seed: true, seed_count: '2' }))).toBe(2);
  });

  it('multi_seed=true + count=6 → 6（上界）', () => {
    expect(parseSeedCount(makeForm({ multi_seed: true, seed_count: '6' }))).toBe(6);
  });

  it('multi_seed=true + count=1 → clamp 到 2（下界保护）', () => {
    expect(parseSeedCount(makeForm({ multi_seed: true, seed_count: '1' }))).toBe(2);
  });

  it('multi_seed=true + count=10 → clamp 到 6（上界保护）', () => {
    expect(parseSeedCount(makeForm({ multi_seed: true, seed_count: '10' }))).toBe(6);
  });

  it('multi_seed=true + count 空 / 非法 → fallback 3', () => {
    expect(parseSeedCount(makeForm({ multi_seed: true, seed_count: '' }))).toBe(3);
    expect(parseSeedCount(makeForm({ multi_seed: true, seed_count: 'abc' }))).toBe(3);
  });
});

describe('parseGate', () => {
  // cm 字符串 ×10 → mm；空/非法/非正 → fallback 1980（=198cm，与 nesting_bounds.GATE_MM 一致）。
  it('默认 198cm → 1980mm；正常值 ×10 换算', () => {
    expect(parseGate(DEFAULT_FORM)).toBe(1980);
    expect(parseGate(makeForm({ gate: '150' }))).toBe(1500);
    expect(parseGate(makeForm({ gate: '180' }))).toBe(1800);
  });

  it('空串 / 非法 → fallback 1980', () => {
    expect(parseGate(makeForm({ gate: '' }))).toBe(1980);
    expect(parseGate(makeForm({ gate: 'abc' }))).toBe(1980);
  });

  it('0 / 负数 → fallback 1980（非正保护）', () => {
    expect(parseGate(makeForm({ gate: '0' }))).toBe(1980);
    expect(parseGate(makeForm({ gate: '-5' }))).toBe(1980);
  });
});

describe('serializeQuantities (US-022；US-001 删 global 分支)', () => {
  function makePerSizeMap(
    label: string,
    perSize: Record<string, number>,
  ): PieceQuantityMap {
    return { [label]: { perSize, baseValue: 1 } };
  }

  it('空 quantities → null（后端回退全片 demand=1）', () => {
    expect(serializeQuantities({}, [28, 30])).toBeNull();
  });

  it('perSize 原样透传（含 0，不抹零）', () => {
    const map = makePerSizeMap('g01', { '28': 2, '30': 0 });
    const out = serializeQuantities(map, [28, 30]);
    expect(out).toEqual({ g01: { '28': 2, '30': 0 } });
  });

  it('未选中码被过滤（用户取消勾选 → 不参与排料）', () => {
    const map = makePerSizeMap('g01', { '28': 1, '30': 1, '32': 1 });
    // 只选了 28 / 30，32 被过滤
    const out = serializeQuantities(map, [28, 30]);
    expect(out).toEqual({ g01: { '28': 1, '30': 1 } });
  });

  it("'null' sizeKey（通用码）兜底保留（不在 sizes 内也透传）", () => {
    const map = makePerSizeMap('g01', { null: 2 });
    const out = serializeQuantities(map, [28]);
    expect(out).toEqual({ g01: { null: 2 } });
  });

  it('多 label 独立透传（线格式与旧版 per-size 路径逐字段一致）', () => {
    const map: PieceQuantityMap = {
      g01: { perSize: { '28': 2, '30': 1 }, baseValue: 1 },
      g02: { perSize: { '28': 1, '30': 4 }, baseValue: 4 },
    };
    const out = serializeQuantities(map, [28, 30]);
    expect(out).toEqual({
      g01: { '28': 2, '30': 1 },
      g02: { '28': 1, '30': 4 },
    });
  });

  it('baseValue 不参与序列化（仅 UI 高亮基准）', () => {
    const map = makePerSizeMap('g01', { '28': 2 });
    const out = serializeQuantities(map, [28]);
    expect(out).toEqual({ g01: { '28': 2 } });
    expect(JSON.stringify(out)).not.toContain('baseValue');
  });

  it('label 全部码被过滤（未勾选任何码）→ 该 label 不出现在输出', () => {
    const map: PieceQuantityMap = {
      g01: { perSize: { '32': 1 }, baseValue: 1 },
    };
    const out = serializeQuantities(map, [28]);
    expect(out).toBeNull();
  });

  it('空 sizes → null（无选中码，不发 demand；ControlPanel.handleStart 已前置校验）', () => {
    const map = makePerSizeMap('g01', { '28': 1 });
    const out = serializeQuantities(map, []);
    expect(out).toBeNull();
  });
});

// ============================================================
// US-012 腰头成带：collectBand 三态 + collectStartContext.band + bandMemberCount 三态
// ============================================================
describe('collectBand / collectStartContext.band (US-012 三态)', () => {
  it('DEFAULT_FORM：band_enabled=false / band_label="" / band_ack=false（默认关闭）', () => {
    expect(DEFAULT_FORM.band_enabled).toBe(false);
    expect(DEFAULT_FORM.band_label).toBe('');
    expect(DEFAULT_FORM.band_ack).toBe(false);
    // 默认表单 collectStartContext → band null（旧行为：StartPayload band 键恒 null）
    expect(collectStartContext(DEFAULT_FORM, {}).band).toBeNull();
  });

  it('三态①：band 关（band_enabled=false，即使 band_label 有值）→ null', () => {
    const form = makeForm({ band_enabled: false, band_label: 'g05' });
    expect(collectBand(form)).toBeNull();
    expect(collectStartContext(form, {}).band).toBeNull();
  });

  it('三态②：开但未选编号（空串 / 纯空白）→ null', () => {
    expect(collectBand(makeForm({ band_enabled: true, band_label: '' }))).toBeNull();
    expect(collectBand(makeForm({ band_enabled: true, band_label: '   ' }))).toBeNull();
    expect(
      collectStartContext(makeForm({ band_enabled: true, band_label: '' }), {}).band,
    ).toBeNull();
  });

  it('三态②（延伸）：开但 label 非 g 码模式（^g\\d+$ 镜像后端）→ null 静默降级', () => {
    for (const bad of ['waist', 'g', 'g5x', 'G05', '5', 'g-5', 'g 05']) {
      expect(collectBand(makeForm({ band_enabled: true, band_label: bad }))).toBeNull();
    }
  });

  it('三态③：开且有效 → {enabled:true,label}（首尾空白 trim；不带 ack 键）', () => {
    const out = collectBand(makeForm({ band_enabled: true, band_label: 'g05' }));
    expect(out).toEqual({ enabled: true, label: 'g05' });
    // trim：' g09 ' → 'g09'
    expect(collectBand(makeForm({ band_enabled: true, band_label: ' g09 ' }))).toEqual({
      enabled: true,
      label: 'g09',
    });
    // 序列化形态：JSON.stringify 后恰两键（ack 缺省不随带）
    expect(JSON.parse(JSON.stringify(out))).toEqual({ enabled: true, label: 'g05' });
  });

  it('US-013 ack：band_ack=true 且开且有效 → {enabled,label,ack:true}（硬警告形态放行键）', () => {
    // 弹窗对硬警告形态勾选二次确认后置 true（FR-1：ack 仅显式勾选时随 band 发送）
    const form = makeForm({ band_enabled: true, band_label: 'g05', band_ack: true });
    expect(collectBand(form)).toEqual({ enabled: true, label: 'g05', ack: true });
    expect(collectStartContext(form, {}).band).toEqual({
      enabled: true, label: 'g05', ack: true,
    });
    // band 关（即使 ack 残留 true）→ null（enabled=false 恒 null）
    expect(collectBand(makeForm({ band_enabled: false, band_label: 'g05', band_ack: true }))).toBeNull();
  });

  it('collectStartContext.band 与 collectBand 同源（开且有效透传，其余字段不受 band 影响）', () => {
    const q: PieceQuantityMap = { g05: { perSize: { '28': 2 }, baseValue: 1 } };
    const form = makeForm({ band_enabled: true, band_label: 'g05', sizes: [28] });
    const ctx = collectStartContext(form, q);
    expect(ctx.band).toEqual({ enabled: true, label: 'g05' });
    // 既有字段不受影响（sizes/quantities 正常解析）
    expect(ctx.sizes).toEqual([28]);
    expect(ctx.quantities).toEqual({ g05: { '28': 2 } });
  });
});

describe('bandMemberCount (US-012 三态：missing→1 / 显式 0 / 未选码过滤)', () => {
  /** g05 行 fixture：28 码 2 份、30 码显式 0、32 码 1 份。 */
  const Q: PieceQuantityMap = {
    g05: { perSize: { '28': 2, '30': 0, '32': 1 }, baseValue: 1 },
  };

  it('显式 0 → 0（该码不计入成员）', () => {
    // 28→2、30 显式 0→0、32→1 = 3
    expect(bandMemberCount(makeForm({ sizes: [28, 30, 32] }), Q, 'g05')).toBe(3);
  });

  it('未选码过滤：未勾选码不计（即使有数量）', () => {
    // 只选 28：30（显式 0）/ 32（有 1 份）都未选 → 过滤 → 仅 28 的 2
    expect(bandMemberCount(makeForm({ sizes: [28] }), Q, 'g05')).toBe(2);
    // 只选 30（显式 0）→ 0 —— US-013「选中 g 码数量全 0」闸门触发态
    expect(bandMemberCount(makeForm({ sizes: [30] }), Q, 'g05')).toBe(0);
  });

  it('missing→1：label 行缺 / sizeKey 缺（无记录）→ 按默认 1 计（后端空 quantities 回退口径）', () => {
    // label 行整缺（store 未 hydrate）：每个选中码各计 1 片
    expect(bandMemberCount(makeForm({ sizes: [28, 30] }), {}, 'g05')).toBe(2);
    // 行在但 sizeKey 缺（28 有记录、30 无记录）→ 28→2 + 30→1 = 3
    const partial: PieceQuantityMap = { g05: { perSize: { '28': 2 }, baseValue: 1 } };
    expect(bandMemberCount(makeForm({ sizes: [28, 30] }), partial, 'g05')).toBe(3);
  });

  it("null 通用码不计（后端 sizes 过滤 want=数字集，null 码裁片不进求解）", () => {
    const withNull: PieceQuantityMap = {
      g05: { perSize: { '28': 2, null: 5 }, baseValue: 1 },
    };
    // null 即使在 perSize 且 form.sizes 含 null 也不计（与既有下游 number[] 契约一致）
    expect(bandMemberCount(makeForm({ sizes: [28, null] }), withNull, 'g05')).toBe(2);
  });

  it('选中 g 码数量全 0 → 0（US-013 启动闸门触发态）；空 sizes → 0', () => {
    const allZero: PieceQuantityMap = {
      g05: { perSize: { '28': 0, '30': 0 }, baseValue: 1 },
    };
    expect(bandMemberCount(makeForm({ sizes: [28, 30] }), allZero, 'g05')).toBe(0);
    expect(bandMemberCount(makeForm({ sizes: [] }), Q, 'g05')).toBe(0);
  });

  it('非 band label 不串行（只统计入参 label 的码）', () => {
    const two: PieceQuantityMap = {
      g05: { perSize: { '28': 2 }, baseValue: 1 },
      g09: { perSize: { '28': 9 }, baseValue: 1 },
    };
    expect(bandMemberCount(makeForm({ sizes: [28] }), two, 'g09')).toBe(9);
  });
});

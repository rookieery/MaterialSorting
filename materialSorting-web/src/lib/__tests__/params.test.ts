// US-019 collectParams 单测（主面板精简后；US-004 起 per_type 键 = (g 码, 码号) 两级
// 嵌套 {label:{sizeKey:{d,tol}}}，与高级配置弹窗矩阵一一对应）：
//   1) params 永远全 0（d_ext/d_int/tol_ext/tol_int 主面板输入已删，全交高级配置弹窗 per_type）。
//   2) per_type：仅 trim()!=='' 写入；双侧全空格子/全空 label 剔除；整体空 → null。
//   3) URL 分享格式 perTypeToUrlParam/perTypeFromUrlParam 往返一致；旧 ptype 键忽略不报错。
//   4) parseTime / parseSeed / parseSeedCount 与旧 vanilla 实现 `parseInt(...) || fallback` 一致。

import { describe, expect, it } from 'vitest';
import {
  collectParams,
  DEFAULT_FORM,
  parseGate,
  parseSeed,
  parseSeedCount,
  parseTime,
  perTypeFromUrlParam,
  perTypeToUrlParam,
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

describe('collectParams (US-019 / US-004 两级嵌套)', () => {
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
        per_type: { g01: { '28': { d: '1', tol: '' } } },
      }),
      makeForm({
        per_type: {
          g01: { '28': { d: '2', tol: '1' }, '30': { d: '', tol: '45' } },
          g02: { null: { d: '10', tol: '45' } },
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

  it('US-004: 单格单档非空 → 该 sizeKey entry 仅写该档；另一档缺省', () => {
    const form = makeForm({
      per_type: { g08: { '30': { d: '7', tol: '' } } },
    });
    const out = collectParams(form);
    expect(out.per_type).toEqual<PerTypeOverrides>({
      g08: { '30': { d: 7 } },
    });
  });

  it('US-004: 同 g 码多码号独立 entry（(g 码, 码号) 逐格命中）', () => {
    const form = makeForm({
      per_type: {
        g03: {
          '28': { d: '1.5', tol: '' },
          '30': { d: '', tol: '45' },
          null: { d: '0', tol: '0' },
        },
      },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      g03: {
        '28': { d: 1.5 },
        '30': { tol: 45 },
        null: { d: 0, tol: 0 },
      },
    });
  });

  it('per_type d 与 tol 都空白 → 该格子剔除（与旧 vanilla 实现 inp.value.trim() 一致）', () => {
    const form = makeForm({
      per_type: {
        g04: { '28': { d: '   ', tol: '' }, '30': { d: '1', tol: '' } },
      },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      g04: { '30': { d: 1 } },
    });
  });

  it('label 下全部格子空白 → 该 label 整体剔除；全表空白 → null', () => {
    const bothEmpty = makeForm({
      per_type: { g04: { '28': { d: '', tol: '' } } },
    });
    expect(collectParams(bothEmpty).per_type).toBeNull();
  });

  it('per_type 多片混合（g01 d+tol，g02 仅 tol，null 码键）正确聚合', () => {
    const form = makeForm({
      per_type: {
        g01: { '28': { d: '2', tol: '1' } },
        g02: { null: { d: '', tol: '45' } },
      },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      g01: { '28': { d: 2, tol: 1 } },
      g02: { null: { tol: 45 } },
    });
  });

  it('per_type 含空白（trim 后空 → 不写入；只非空档写）', () => {
    const form = makeForm({
      per_type: { g01: { '28': { d: '  ', tol: ' 1 ' } } },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      g01: { '28': { tol: 1 } },
    });
  });

  it('per_type 显式 "0" 也写入（区分空 vs "0"，与旧 vanilla 实现一致）', () => {
    const form = makeForm({
      per_type: { g07: { '28': { d: '0', tol: '0' } } },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      g07: { '28': { d: 0, tol: 0 } },
    });
  });

  it('US-004 端到端口径：g03@28 d=1.5 → per_type.g03["28"].d === 1.5（WS start payload 形状）', () => {
    const form = makeForm({
      per_type: { g03: { '28': { d: '1.5', tol: '' } } },
    });
    const out = collectParams(form);
    expect(out.per_type!.g03['28'].d).toBe(1.5);
  });
});

describe('per_type URL 分享格式 (US-004)', () => {
  it('空配置 → 空串；解码空串/null → 空对象', () => {
    expect(perTypeToUrlParam(DEFAULT_FORM)).toBe('');
    expect(perTypeFromUrlParam('')).toEqual({});
    expect(perTypeFromUrlParam(null)).toEqual({});
  });

  it('编码：仅非空格子产出；格式 label@sizeKey=d,tol', () => {
    const form = makeForm({
      per_type: {
        g03: { '28': { d: '1.5', tol: '' }, '30': { d: '', tol: '45' } },
        g02: { null: { d: '0', tol: '3' }, '31': { d: '', tol: '' } }, // 31 全空不产出
      },
    });
    expect(perTypeToUrlParam(form)).toBe('g03@28=1.5,;g03@30=,45;g02@null=0,3');
  });

  it('往返一致：编码 → 解码 → 再编码 稳定', () => {
    const form = makeForm({
      per_type: {
        g01: { '28': { d: '2', tol: '1' } },
        g10: { null: { d: '0.4', tol: '30' } },
        g100: { '33': { d: '', tol: '45' } },
      },
    });
    const once = perTypeToUrlParam(form);
    const decoded = perTypeFromUrlParam(once);
    expect(decoded).toEqual(form.per_type);
    expect(perTypeToUrlParam({ ...form, per_type: decoded })).toBe(once);
  });

  it('解码：旧 ptype 键（中文 / 旧 label 单级格式）忽略不报错', () => {
    // 旧 label 单级格式（US-003 时代）：前片@28=1,2 不匹配新语法 → 跳过
    const out1 = perTypeFromUrlParam('前片@28=1,2;g03@30=,45');
    expect(out1).toEqual({ g03: { '30': { d: '', tol: '45' } } });
    // 旧扁平 d/tol 键形态（d=@28 位）也不匹配 → 跳过
    const out2 = perTypeFromUrlParam('g03@d=1,tol;g01@28=2,');
    expect(out2).toEqual({ g01: { '28': { d: '2', tol: '' } } });
    // 乱拼段（缺 = / 缺 ,）静默跳过
    const out3 = perTypeFromUrlParam('garbage;;g02@30=1,2;g02@xx=1,2');
    expect(out3).toEqual({ g02: { '30': { d: '1', tol: '2' } } });
  });

  it('解码：非数值 d/tol 段跳过（防手拼 NaN 注入）', () => {
    expect(perTypeFromUrlParam('g01@28=abc,2')).toEqual({});
    expect(perTypeFromUrlParam('g01@28=1,xyz')).toEqual({});
    expect(perTypeFromUrlParam('g01@28=1,')).toEqual({ g01: { '28': { d: '1', tol: '' } } });
  });

  it('解码结果直接可用作 FormState.per_type（collectParams 输出闭环）', () => {
    const decoded = perTypeFromUrlParam('g03@28=1.5,');
    const out = collectParams({ ...DEFAULT_FORM, per_type: decoded });
    expect(out.per_type).toEqual<PerTypeOverrides>({ g03: { '28': { d: 1.5 } } });
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

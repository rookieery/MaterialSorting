// US-019 collectParams 单测（主面板精简后）：
//   1) params 永远全 0（d_ext/d_int/tol_ext/tol_int 主面板输入已删，全交高级配置弹窗 per_type）。
//   2) per_type 解析逻辑保留不变：仅 trim()!=='' 写入；空 → null；任一档非空 → 创建 entry。
//   3) parseTime / parseSeed / parseSeedCount 与旧 vanilla 实现 `parseInt(...) || fallback` 一致。

import { describe, expect, it } from 'vitest';
import {
  collectParams,
  DEFAULT_FORM,
  parseSeed,
  parseSeedCount,
  parseTime,
  type FormState,
} from '../params';
import type { PerTypeOverrides, SolveParams } from '../../types/v03';

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
        per_type: { ...DEFAULT_FORM.per_type, 前片: { d: '1', tol: '' } },
      }),
      makeForm({
        per_type: {
          ...DEFAULT_FORM.per_type,
          前片: { d: '2', tol: '1' },
          裤耳: { d: '', tol: '45' },
        },
      }),
      makeForm({
        per_type: {
          前片: { d: '2', tol: '1' },
          后片: { d: '2', tol: '1' },
          腰: { d: '0.4', tol: '3' },
          前袋: { d: '0.4', tol: '30' },
          后袋: { d: '0.4', tol: '1' },
          机头: { d: '0.4', tol: '3' },
          单排: { d: '10', tol: '15' },
          双排: { d: '10', tol: '15' },
          火机袋: { d: '5', tol: '8' },
          裤耳: { d: '10', tol: '45' },
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
      per_type: { ...DEFAULT_FORM.per_type, 单排: { d: '7', tol: '' } },
    });
    const out = collectParams(form);
    expect(out.per_type).toEqual<PerTypeOverrides>({
      单排: { d: 7 },
    });
  });

  it('per_type d 与 tol 都空白 → 不创建 entry（与旧 vanilla 实现 inp.value.trim() 一致）', () => {
    const form = makeForm({
      per_type: { ...DEFAULT_FORM.per_type, 腰: { d: '   ', tol: '' } },
    });
    expect(collectParams(form).per_type).toBeNull();
  });

  it('per_type 多片型混合（前片 d+tol，裤耳 仅 tol）正确聚合', () => {
    const form = makeForm({
      per_type: {
        ...DEFAULT_FORM.per_type,
        前片: { d: '2', tol: '1' },
        裤耳: { d: '', tol: '45' },
      },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      前片: { d: 2, tol: 1 },
      裤耳: { tol: 45 },
    });
  });

  it('per_type 含空白（trim 后空 → 不写入；只非空档写）', () => {
    const form = makeForm({
      per_type: { ...DEFAULT_FORM.per_type, 前片: { d: '  ', tol: ' 1 ' } },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      前片: { tol: 1 },
    });
  });

  it('per_type 显式 "0" 也写入（区分空 vs "0"，与旧 vanilla 实现一致）', () => {
    const form = makeForm({
      per_type: { ...DEFAULT_FORM.per_type, 机头: { d: '0', tol: '0' } },
    });
    expect(collectParams(form).per_type).toEqual<PerTypeOverrides>({
      机头: { d: 0, tol: 0 },
    });
  });

  it('全 ptype 全填（V03_TABLE 上限值）→ 所有 10 个 entry 写入', () => {
    const form = makeForm({
      per_type: {
        前片: { d: '2', tol: '1' },
        后片: { d: '2', tol: '1' },
        腰: { d: '0.4', tol: '3' },
        前袋: { d: '0.4', tol: '30' },
        后袋: { d: '0.4', tol: '1' },
        机头: { d: '0.4', tol: '3' },
        单排: { d: '10', tol: '15' },
        双排: { d: '10', tol: '15' },
        火机袋: { d: '5', tol: '8' },
        裤耳: { d: '10', tol: '45' },
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
  it('parseTime：默认 60 → 60；空串 → fallback 120；非法 → fallback 120', () => {
    expect(parseTime(DEFAULT_FORM)).toBe(60);
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

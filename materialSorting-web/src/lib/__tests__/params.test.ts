// US-004 collectParams 单测：
//   1) 默认表单 → d_int=10，其余三档 0；per_type = null（全空）。
//   2) 与旧 vanilla 实现 collectParams 字段级一致（多组对比，含全空 / 部分填 / 全填 / 空白 / 非法字符）。
//   3) per_type 空 → null；任一档非空 → 创建 entry（仅写非空档）。
//   4) parseTime / parseSeed 与旧 vanilla 实现 `parseInt(...) || fallback` 一致。

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

// 旧 vanilla 实现 num(id, def) —— 模拟从 input.value 字符串解析。
function legacyNum(s: string, def: number): number {
  const v = parseFloat(s);
  return Number.isNaN(v) ? def : v;
}

// 旧 vanilla 实现 collectParams 的参考实现（按 FormState 输入重写，行为字节级一致）。
function legacyCollectParams(form: FormState): { params: SolveParams; per_type: PerTypeOverrides | null } {
  const params: SolveParams = {
    d_ext: legacyNum(form.d_ext, 0),
    d_int: legacyNum(form.d_int, 0),
    tol_ext: legacyNum(form.tol_ext, 0),
    tol_int: legacyNum(form.tol_int, 0),
  };
  const per_type: PerTypeOverrides = {};
  // 旧 vanilla 实现 遍历所有 input（10 ptype × 2 key），此处等价展开。
  for (const [pt, vals] of Object.entries(form.per_type)) {
    if (vals.d.trim() !== '') {
      (per_type[pt] = per_type[pt] || {}).d = parseFloat(vals.d);
    }
    if (vals.tol.trim() !== '') {
      (per_type[pt] = per_type[pt] || {}).tol = parseFloat(vals.tol);
    }
  }
  return { params, per_type: Object.keys(per_type).length ? per_type : null };
}

function makeForm(overrides: Partial<FormState> = {}): FormState {
  return {
    ...DEFAULT_FORM,
    per_type: { ...DEFAULT_FORM.per_type },
    ...overrides,
  };
}

describe('collectParams (US-004)', () => {
  it('默认表单：d_int=10，其余三档 0；per_type = null（全空）', () => {
    const out = collectParams(DEFAULT_FORM);
    expect(out.params).toEqual<SolveParams>({
      d_ext: 0,
      d_int: 10,
      tol_ext: 0,
      tol_int: 0,
    });
    expect(out.per_type).toBeNull();
  });

  it('与旧 vanilla 实现 collectParams 字段级一致（多组对比）', () => {
    const cases: FormState[] = [
      // 1. 全空 per_type + 默认档
      makeForm(),
      // 2. 仅 d_ext=2
      makeForm({ d_ext: '2' }),
      // 3. d_int 空串（parseFloat → NaN → 默认 0）
      makeForm({ d_int: '' }),
      // 4. 全档都填
      makeForm({ d_ext: '1.5', d_int: '10', tol_ext: '5', tol_int: '20' }),
      // 5. 含空白串（trim 后空）
      makeForm({ d_ext: '   ', d_int: '10' }),
      // 6. per_type 部分填：前片 d=1
      makeForm({
        per_type: { ...DEFAULT_FORM.per_type, 前片: { d: '1', tol: '' } },
      }),
      // 7. per_type 部分填：单排 tol=15
      makeForm({
        per_type: { ...DEFAULT_FORM.per_type, 单排: { d: '', tol: '15' } },
      }),
      // 8. per_type 部分填：火机袋 d=5 + tol=8
      makeForm({
        per_type: { ...DEFAULT_FORM.per_type, 火机袋: { d: '5', tol: '8' } },
      }),
      // 9. per_type 多片型混合（前片 d+tol，裤耳 仅 tol）
      makeForm({
        per_type: {
          ...DEFAULT_FORM.per_type,
          前片: { d: '2', tol: '1' },
          裤耳: { d: '', tol: '45' },
        },
      }),
      // 10. 全 ptype 全填（V03_TABLE 上限值）
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
      // 11. per_type 含空白（trim 后空 → 不写入）
      makeForm({
        per_type: { ...DEFAULT_FORM.per_type, 前片: { d: '  ', tol: ' 1 ' } },
      }),
    ];

    for (const form of cases) {
      const mine = collectParams(form);
      const ref = legacyCollectParams(form);
      expect(mine).toEqual(ref);
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

  it('所有档显式 "0" → params 全 0；per_type 中 d=0 也写入（区分空 vs "0"）', () => {
    const form = makeForm({
      d_ext: '0',
      d_int: '0',
      tol_ext: '0',
      tol_int: '0',
      per_type: { ...DEFAULT_FORM.per_type, 机头: { d: '0', tol: '0' } },
    });
    const out = collectParams(form);
    expect(out.params).toEqual<SolveParams>({ d_ext: 0, d_int: 0, tol_ext: 0, tol_int: 0 });
    expect(out.per_type).toEqual<PerTypeOverrides>({ 机头: { d: 0, tol: 0 } });
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

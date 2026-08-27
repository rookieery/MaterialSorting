// US-005 session.ts 单测：sid get-or-create（localStorage 键 ms_sid，uuid4 hex）。
//   AC1 空库首取 → 生成 32 位小写 hex 并落盘；同进程重复取值不变。
//   AC2 预置合法值（= 刷新页面场景）→ 原值返回不重生成。
//   AC3 存量损坏（非法形状）→ 静默重生成 + 覆写。
//   AC4 uuid4 定位（version 4 / variant 10xx 位）。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { clearPersistedSessionId, getSessionId, resetSessionIdForTest } from '../session';

const SID_RE = /^[0-9a-f]{32}$/;

beforeEach(() => {
  localStorage.clear();
  resetSessionIdForTest();
});

afterEach(() => {
  localStorage.clear();
  resetSessionIdForTest();
});

describe('session.ts（US-005）', () => {
  it('AC1 空库首取：生成 32 位小写 hex + 写入 localStorage ms_sid', () => {
    const sid = getSessionId();
    expect(sid).toMatch(SID_RE);
    expect(localStorage.getItem('ms_sid')).toBe(sid);
  });

  it('AC1 幂等：同进程重复调用返回同值（模块缓存）', () => {
    expect(getSessionId()).toBe(getSessionId());
  });

  it('AC2 预置合法值（刷新页面场景）：原值返回不重生成', () => {
    const preset = '0123456789abcdef0123456789abcdef';
    localStorage.setItem('ms_sid', preset);
    resetSessionIdForTest(); // 模拟页面重载（模块缓存清空，localStorage 持久）
    expect(getSessionId()).toBe(preset);
    expect(localStorage.getItem('ms_sid')).toBe(preset);
  });

  it('AC3 存量损坏（非 32-hex）→ 重生成 + 覆写', () => {
    localStorage.setItem('ms_sid', 'not-a-valid-sid');
    resetSessionIdForTest();
    const sid = getSessionId();
    expect(sid).toMatch(SID_RE);
    expect(sid).not.toBe('not-a-valid-sid');
    expect(localStorage.getItem('ms_sid')).toBe(sid);
  });

  it('AC4 uuid4 定位：version=4（第 13 位 hex ∈ [4-7]）+ variant 10xx（第 17 位 ∈ [89ab]）', () => {
    // 多取样防巧合（固定位按 RFC 4122 由生成器显式置位，非随机分布）
    for (let i = 0; i < 8; i++) {
      localStorage.clear();
      resetSessionIdForTest();
      const sid = getSessionId();
      expect('4567').toContain(sid[12]);
      expect('89ab').toContain(sid[16]);
    }
  });

  it('AC5 clearPersistedSessionId：清 localStorage + 模块缓存，下次取值换新（过期墓碑出口）', () => {
    const sid = getSessionId();
    expect(localStorage.getItem('ms_sid')).toBe(sid);
    clearPersistedSessionId();
    expect(localStorage.getItem('ms_sid')).toBeNull();
    const sid2 = getSessionId();
    expect(sid2).toMatch(SID_RE);
    expect(sid2).not.toBe(sid); // 新铸造
    expect(localStorage.getItem('ms_sid')).toBe(sid2); // 且已落盘
  });
});

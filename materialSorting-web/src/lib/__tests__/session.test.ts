// US-005 session.ts 单测：sid get-or-create（localStorage 键 ms_sid，uuid4 hex）。
//   AC1 空库首取 → 生成 32 位小写 hex 并落盘；同进程重复取值不变。
//   AC2 预置合法值（= 刷新页面场景）→ 原值返回不重生成。
//   AC3 存量损坏（非法形状）→ 静默重生成 + 覆写。
//   AC4 uuid4 定位（version 4 / variant 10xx 位）。
// 会话过期自动恢复 US-003 补：peekPersistedSessionId 非铸造只读（peek 必须先于
//   clear —— getSessionId 会 lazy-mint 覆盖旧值，启动期恢复的时序红线）。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  clearPersistedSessionId,
  getSessionId,
  peekPersistedSessionId,
  resetSessionIdForTest,
} from '../session';

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

describe('peekPersistedSessionId（US-003 非铸造只读）', () => {
  it('空库 → null 且绝不铸造（localStorage 保持空，模块缓存不落值）', () => {
    expect(peekPersistedSessionId()).toBeNull();
    expect(localStorage.getItem('ms_sid')).toBeNull(); // 没有被 peek 写入
    expect(getSessionId()).toMatch(SID_RE); // 事后 get 才铸造
  });

  it('预置合法值（刷新页面场景）→ 原值返回，不重生成不覆写', () => {
    const preset = '0123456789abcdef0123456789abcdef';
    localStorage.setItem('ms_sid', preset);
    resetSessionIdForTest(); // 模拟页面重载（缓存空，localStorage 持久）
    expect(peekPersistedSessionId()).toBe(preset);
    expect(localStorage.getItem('ms_sid')).toBe(preset);
    expect(getSessionId()).toBe(preset); // peek 没有破坏后续 get-or-create
  });

  it('缓存命中（getSessionId 之后）→ 同值返回', () => {
    const sid = getSessionId();
    expect(peekPersistedSessionId()).toBe(sid);
  });

  it('存量损坏 → null（不抛异常，不触发重铸）', () => {
    localStorage.setItem('ms_sid', 'not-a-valid-sid');
    resetSessionIdForTest();
    expect(peekPersistedSessionId()).toBeNull();
  });

  it('恢复时序红线：peek → clear → get 全链旧值不丢（sessionRecovery 同序）', () => {
    const sid = getSessionId();
    const old = peekPersistedSessionId(); // ① 先 peek 拿旧值
    expect(old).toBe(sid);
    clearPersistedSessionId(); // ② 再清
    const next = getSessionId(); // ③ 后铸新
    expect(next).not.toBe(sid);
    expect(old).toBe(sid); // 旧值已被捕获在手，不因铸新丢失
  });
});

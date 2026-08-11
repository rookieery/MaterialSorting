// US-001 uiStore 单测（原 4 项）：
//   - 默认 activeTab = 'preview'（首页落上传预览）
//   - setTab('preview') / setTab('nesting') 切换并触发订阅
//   - 多次 setTab 同值幂等（无额外通知）
// US-015 新增 4 项（nestingEnabled 解锁闸）：
//   - 默认 nestingEnabled === false
//   - setNestingEnabled(true) 切换 nestingEnabled
//   - 订阅者收到 nestingEnabled 变化
//   - setTab('nesting') 在 nestingEnabled===false 时静默不切（关键不变量）

import { beforeEach, describe, expect, it } from 'vitest';
import { useUiStore } from '../uiStore';

beforeEach(() => {
  // 重置到默认 preview + 锁定超排 Tab，避免前一个测试残留
  useUiStore.getState().setTab('preview');
  useUiStore.getState().setNestingEnabled(false);
});

describe('uiStore', () => {
  it('默认 activeTab = preview', () => {
    expect(useUiStore.getState().activeTab).toBe('preview');
  });

  it('setTab(nesting) 切换 activeTab', () => {
    // US-015：setTab('nesting') 需先解锁，否则静默不切（保留原断言意图）
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('setTab(preview) 从 nesting 切回', () => {
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    useUiStore.getState().setTab('preview');
    expect(useUiStore.getState().activeTab).toBe('preview');
  });

  it('订阅者收到 activeTab 变化', () => {
    useUiStore.getState().setNestingEnabled(true);
    const seen: string[] = [];
    const unsub = useUiStore.subscribe((s) => seen.push(s.activeTab));
    useUiStore.getState().setTab('nesting');
    useUiStore.getState().setTab('preview');
    unsub();
    // zustand 在初始化时不通知；只在 set 后通知
    expect(seen).toEqual(['nesting', 'preview']);
  });
});

describe('uiStore US-015 nestingEnabled', () => {
  it('默认 nestingEnabled === false', () => {
    expect(useUiStore.getState().nestingEnabled).toBe(false);
  });

  it('setNestingEnabled(true) 切换 nestingEnabled', () => {
    useUiStore.getState().setNestingEnabled(true);
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    useUiStore.getState().setNestingEnabled(false);
    expect(useUiStore.getState().nestingEnabled).toBe(false);
  });

  it('订阅者收到 nestingEnabled 变化', () => {
    const seen: boolean[] = [];
    const unsub = useUiStore.subscribe((s) => seen.push(s.nestingEnabled));
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setNestingEnabled(false);
    unsub();
    expect(seen).toEqual([true, false]);
  });

  it('setTab(nesting) 在 nestingEnabled===false 时静默不切（关键不变量）', () => {
    // 未解锁状态下尝试切超排
    useUiStore.getState().setTab('nesting');
    expect(useUiStore.getState().activeTab).toBe('preview');
    // 解锁后再切才生效
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('setTab(preview) 在 nestingEnabled===false 时仍可切（用户随时可回上传预览页）', () => {
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    useUiStore.getState().setNestingEnabled(false);
    // 锁定状态下从 nesting 切回 preview 仍允许（不强制留在 nesting）
    useUiStore.getState().setTab('preview');
    expect(useUiStore.getState().activeTab).toBe('preview');
  });
});

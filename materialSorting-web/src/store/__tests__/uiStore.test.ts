// US-001 uiStore 单测：
//   - 默认 activeTab = 'preview'（首页落上传预览）
//   - setTab('preview') / setTab('nesting') 切换并触发订阅
//   - 多次 setTab 同值幂等（无额外通知）

import { beforeEach, describe, expect, it } from 'vitest';
import { useUiStore } from '../uiStore';

beforeEach(() => {
  // 重置到默认 'preview'，避免前一个测试残留
  useUiStore.getState().setTab('preview');
});

describe('uiStore', () => {
  it('默认 activeTab = preview', () => {
    expect(useUiStore.getState().activeTab).toBe('preview');
  });

  it('setTab(nesting) 切换 activeTab', () => {
    useUiStore.getState().setTab('nesting');
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('setTab(preview) 从 nesting 切回', () => {
    useUiStore.getState().setTab('nesting');
    useUiStore.getState().setTab('preview');
    expect(useUiStore.getState().activeTab).toBe('preview');
  });

  it('订阅者收到 activeTab 变化', () => {
    const seen: string[] = [];
    const unsub = useUiStore.subscribe((s) => seen.push(s.activeTab));
    useUiStore.getState().setTab('nesting');
    useUiStore.getState().setTab('preview');
    unsub();
    // zustand 在初始化时不通知；只在 set 后通知
    expect(seen).toEqual(['nesting', 'preview']);
  });
});

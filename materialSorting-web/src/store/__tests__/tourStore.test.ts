// US-029 tourStore 单测（≥6 项）：
//   - 默认 activeTour=null
//   - start 置 activeTour + stepIndex=0
//   - next 递增 + prev 递减 floor 0（边界 clamp）
//   - close 清 activeTour
//   - markSeen 写 localStorage + hydrate（重新加载后读回）
//   - resetSeen 清 localStorage 全部 seen
//   - TOUR_VERSION 不一致清 seen（强制重看）

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useTourStore } from '../tourStore';
import { TOUR_VERSION } from '../../tour/steps';

beforeEach(() => {
  // 清 localStorage + reset store 状态（避免前一个测试残留）
  localStorage.clear();
  useTourStore.setState({
    activeTour: null,
    stepIndex: 0,
    seen: { preview: false, nesting: false },
  });
});

describe('tourStore US-029 基础', () => {
  it('默认 activeTour=null + stepIndex=0', () => {
    const s = useTourStore.getState();
    expect(s.activeTour).toBeNull();
    expect(s.stepIndex).toBe(0);
  });

  it('start(tabId) 置 activeTour + stepIndex=0', () => {
    useTourStore.getState().start('preview');
    const s = useTourStore.getState();
    expect(s.activeTour).toBe('preview');
    expect(s.stepIndex).toBe(0);

    // 推进几步后再 start 验证 stepIndex 重置
    useTourStore.getState().next();
    useTourStore.getState().next();
    expect(useTourStore.getState().stepIndex).toBe(2);
    useTourStore.getState().start('nesting');
    expect(useTourStore.getState().activeTour).toBe('nesting');
    expect(useTourStore.getState().stepIndex).toBe(0);
  });

  it('next 递增 stepIndex；prev 递减 floor 0（边界 clamp）', () => {
    useTourStore.getState().start('preview');
    expect(useTourStore.getState().stepIndex).toBe(0);

    useTourStore.getState().next();
    expect(useTourStore.getState().stepIndex).toBe(1);

    useTourStore.getState().next();
    expect(useTourStore.getState().stepIndex).toBe(2);

    useTourStore.getState().prev();
    expect(useTourStore.getState().stepIndex).toBe(1);

    // prev floor clamp at 0（连按多次不越界）
    useTourStore.getState().prev();
    useTourStore.getState().prev();
    useTourStore.getState().prev();
    expect(useTourStore.getState().stepIndex).toBe(0);
  });

  it('close 清 activeTour（stepIndex 保留，下次 start 重置）', () => {
    useTourStore.getState().start('preview');
    useTourStore.getState().next();
    expect(useTourStore.getState().stepIndex).toBe(1);

    useTourStore.getState().close();
    expect(useTourStore.getState().activeTour).toBeNull();
    // stepIndex 保留（不重置；下次 start 才重置为 0）
    expect(useTourStore.getState().stepIndex).toBe(1);

    // 重新 start 验证 stepIndex 重置
    useTourStore.getState().start('preview');
    expect(useTourStore.getState().stepIndex).toBe(0);
  });
});

describe('tourStore US-029 seen 持久化', () => {
  it('markSeen 写 localStorage + 重新加载后 hydrate', async () => {
    // markSeen 写内存 + localStorage
    useTourStore.getState().markSeen('preview');
    expect(useTourStore.getState().seen.preview).toBe(true);
    expect(localStorage.getItem('ms.tour.seen.preview')).toBe('1');

    // 模拟重新加载：reset modules + 重新导入 → hydrateSeen 从 localStorage 读
    vi.resetModules();
    const { useTourStore: freshStore } = await import('../tourStore');
    expect(freshStore.getState().seen.preview).toBe(true);
    expect(freshStore.getState().seen.nesting).toBe(false);
  });

  it('resetSeen 清 localStorage 全部 seen', () => {
    useTourStore.getState().markSeen('preview');
    useTourStore.getState().markSeen('nesting');
    expect(localStorage.getItem('ms.tour.seen.preview')).toBe('1');
    expect(localStorage.getItem('ms.tour.seen.nesting')).toBe('1');

    useTourStore.getState().resetSeen();

    expect(useTourStore.getState().seen.preview).toBe(false);
    expect(useTourStore.getState().seen.nesting).toBe(false);
    expect(localStorage.getItem('ms.tour.seen.preview')).toBeNull();
    expect(localStorage.getItem('ms.tour.seen.nesting')).toBeNull();
  });

  it('TOUR_VERSION 不一致清 seen（强制重看）', async () => {
    // 先标记 seen（写正确版本号 + seen）
    useTourStore.getState().markSeen('preview');
    expect(localStorage.getItem('ms.tour.version')).toBe(TOUR_VERSION);

    // 模拟旧版本号：手动覆写 localStorage 为旧版本 + 旧 seen
    localStorage.setItem('ms.tour.version', '0');
    localStorage.setItem('ms.tour.seen.preview', '1');
    localStorage.setItem('ms.tour.seen.nesting', '1');

    // reset modules + 重新导入 → hydrateSeen 检测版本不一致 → 清 seen + 写新版本号
    vi.resetModules();
    const { useTourStore: freshStore } = await import('../tourStore');

    // seen 被清空（强制重看）
    expect(freshStore.getState().seen.preview).toBe(false);
    expect(freshStore.getState().seen.nesting).toBe(false);
    // 旧 seen key 从 localStorage 清除
    expect(localStorage.getItem('ms.tour.seen.preview')).toBeNull();
    expect(localStorage.getItem('ms.tour.seen.nesting')).toBeNull();
    // 新版本号写入
    expect(localStorage.getItem('ms.tour.version')).toBe(TOUR_VERSION);
  });

  it('markSeen 幂等（重复调不重复写 localStorage）', () => {
    useTourStore.getState().markSeen('preview');
    expect(useTourStore.getState().seen.preview).toBe(true);

    // 再次 markSeen：seen 已 true，no-op（不触发 setState）
    const spy = vi.spyOn(Storage.prototype, 'setItem');
    useTourStore.getState().markSeen('preview');
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

// US-018 controlPanelStore 单测：
//   - 默认 modal===null / previewPtype===null
//   - openModal('per_type') / closeModal 切换并通知订阅者
//   - openPreviewPtype('前片') / closePreviewPtype 切换并通知订阅者
//   - 两层 state 独立（closeModal 不影响 previewPtype / closePreviewPtype 不影响 modal）

import { beforeEach, describe, expect, it } from 'vitest';
import { useControlPanelStore } from '../controlPanelStore';

beforeEach(() => {
  // 重置到默认关闭态，避免前一个测试残留
  useControlPanelStore.getState().closeModal();
  useControlPanelStore.getState().closePreviewPtype();
});

describe('controlPanelStore US-018', () => {
  it('默认 modal===null / previewPtype===null', () => {
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(useControlPanelStore.getState().previewPtype).toBeNull();
  });

  it('openModal(per_type) / closeModal 切换 modal', () => {
    useControlPanelStore.getState().openModal('per_type');
    expect(useControlPanelStore.getState().modal).toBe('per_type');
    useControlPanelStore.getState().closeModal();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('openPreviewPtype / closePreviewPtype 切换 previewPtype', () => {
    useControlPanelStore.getState().openPreviewPtype('前片');
    expect(useControlPanelStore.getState().previewPtype).toBe('前片');
    useControlPanelStore.getState().closePreviewPtype();
    expect(useControlPanelStore.getState().previewPtype).toBeNull();
  });

  it('订阅者收到 modal 变化', () => {
    const seen: (string | null)[] = [];
    const unsub = useControlPanelStore.subscribe((s) => seen.push(s.modal));
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().closeModal();
    unsub();
    expect(seen).toEqual(['per_type', null]);
  });

  it('订阅者收到 previewPtype 变化', () => {
    const seen: (string | null)[] = [];
    const unsub = useControlPanelStore.subscribe((s) => seen.push(s.previewPtype));
    useControlPanelStore.getState().openPreviewPtype('腰');
    useControlPanelStore.getState().closePreviewPtype();
    unsub();
    expect(seen).toEqual(['腰', null]);
  });

  it('两层 state 独立：closeModal 不影响 previewPtype', () => {
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewPtype('前片');
    useControlPanelStore.getState().closeModal();
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(useControlPanelStore.getState().previewPtype).toBe('前片');
  });

  it('两层 state 独立：closePreviewPtype 不影响 modal', () => {
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewPtype('前片');
    useControlPanelStore.getState().closePreviewPtype();
    expect(useControlPanelStore.getState().previewPtype).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });
});

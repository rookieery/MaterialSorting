// US-018 controlPanelStore 单测（裁片编号化重构 US-003 起 previewPtype→previewLabel，
// 目标值 = 裁片 g 码）：
//   - 默认 modal===null / previewLabel===null
//   - openModal('per_type') / closeModal 切换并通知订阅者
//   - openPreviewLabel('g03') / closePreviewLabel 切换并通知订阅者
//   - 两层 state 独立（closeModal 不影响 previewLabel / closePreviewLabel 不影响 modal）

import { beforeEach, describe, expect, it } from 'vitest';
import { useControlPanelStore } from '../controlPanelStore';

beforeEach(() => {
  // 重置到默认关闭态，避免前一个测试残留
  useControlPanelStore.getState().closeModal();
  useControlPanelStore.getState().closePreviewLabel();
});

describe('controlPanelStore US-018', () => {
  it('默认 modal===null / previewLabel===null', () => {
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
  });

  it('openModal(per_type) / closeModal 切换 modal', () => {
    useControlPanelStore.getState().openModal('per_type');
    expect(useControlPanelStore.getState().modal).toBe('per_type');
    useControlPanelStore.getState().closeModal();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('openPreviewLabel / closePreviewLabel 切换 previewLabel（g 码）', () => {
    useControlPanelStore.getState().openPreviewLabel('g03');
    expect(useControlPanelStore.getState().previewLabel).toBe('g03');
    useControlPanelStore.getState().closePreviewLabel();
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
  });

  it('订阅者收到 modal 变化', () => {
    const seen: (string | null)[] = [];
    const unsub = useControlPanelStore.subscribe((s) => seen.push(s.modal));
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().closeModal();
    unsub();
    expect(seen).toEqual(['per_type', null]);
  });

  it('订阅者收到 previewLabel 变化', () => {
    const seen: (string | null)[] = [];
    const unsub = useControlPanelStore.subscribe((s) => seen.push(s.previewLabel));
    useControlPanelStore.getState().openPreviewLabel('g05');
    useControlPanelStore.getState().closePreviewLabel();
    unsub();
    expect(seen).toEqual(['g05', null]);
  });

  it('两层 state 独立：closeModal 不影响 previewLabel', () => {
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewLabel('g01');
    useControlPanelStore.getState().closeModal();
    expect(useControlPanelStore.getState().modal).toBeNull();
    expect(useControlPanelStore.getState().previewLabel).toBe('g01');
  });

  it('两层 state 独立：closePreviewLabel 不影响 modal', () => {
    useControlPanelStore.getState().openModal('per_type');
    useControlPanelStore.getState().openPreviewLabel('g01');
    useControlPanelStore.getState().closePreviewLabel();
    expect(useControlPanelStore.getState().previewLabel).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });

  // 编辑排料 US-002：'edit_layout' 入联合类型 —— closeModal 通用关闭（弹窗自身不挂
  // ESC/遮罩路径，但 store 层 openModal/closeModal 语义与其他 id 一致）。
  it('openModal(edit_layout) / closeModal 切换 modal（编辑排料弹窗，US-002）', () => {
    useControlPanelStore.getState().openModal('edit_layout');
    expect(useControlPanelStore.getState().modal).toBe('edit_layout');
    useControlPanelStore.getState().closeModal();
    expect(useControlPanelStore.getState().modal).toBeNull();
  });
});

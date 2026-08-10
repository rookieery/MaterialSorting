// US-005 uploadStore 单测：
//   - 默认 status='idle' / doc=null / activeSize=null / error=null / qtyDialog=null / zoom=null
//   - reset() 清空所有字段（包括从 done 回到 idle，含 qtyDialog / zoom）
//   - setSize(n) / setSize(null) 切 activeSize 并触发订阅
//   - 直接 setState({status, doc, error}) 写入（hook 内部用，UI 不直接调）
//   - openQtyDialog/closeQtyDialog 切 qtyDialog（US-012 新增）
//   - reset() 把 qtyDialog 清回 null（US-012 新增）
//   - openZoom/closeZoom 切 zoom（US-013 新增）
//   - reset() 把 zoom 清回 null（US-013 新增）

import { beforeEach, describe, expect, it } from 'vitest';
import { useUploadStore } from '../uploadStore';
import type { ParsedDoc } from '../../types/parsed';

const sampleDoc: ParsedDoc = {
  doc_id: 'abc123',
  filename: 'M1787.dxf',
  sizes: [
    { size: 28, pieces: [] },
    { size: 30, pieces: [] },
    { size: null, pieces: [] },
  ],
};

beforeEach(() => {
  // 重置到默认 idle，避免前一个测试残留
  useUploadStore.getState().reset();
});

describe('uploadStore (US-005)', () => {
  it('默认 status=idle / doc=null / activeSize=null / error=null', () => {
    const s = useUploadStore.getState();
    expect(s.status).toBe('idle');
    expect(s.doc).toBeNull();
    expect(s.activeSize).toBeNull();
    expect(s.error).toBeNull();
  });

  it('reset() 把 done 态清回 idle（doc/activeSize/error 全清）', () => {
    useUploadStore.setState({
      status: 'done',
      doc: sampleDoc,
      activeSize: 28,
      error: null,
    });
    useUploadStore.getState().reset();
    const s = useUploadStore.getState();
    expect(s.status).toBe('idle');
    expect(s.doc).toBeNull();
    expect(s.activeSize).toBeNull();
    expect(s.error).toBeNull();
  });

  it('reset() 把 error 态清回 idle', () => {
    useUploadStore.setState({ status: 'error', error: '解析失败' });
    useUploadStore.getState().reset();
    const s = useUploadStore.getState();
    expect(s.status).toBe('idle');
    expect(s.error).toBeNull();
  });

  it('setSize(30) 切 activeSize', () => {
    useUploadStore.getState().setSize(30);
    expect(useUploadStore.getState().activeSize).toBe(30);
  });

  it('setSize(null) 切到 null 码组（码号 None）', () => {
    useUploadStore.getState().setSize(28);
    useUploadStore.getState().setSize(null);
    expect(useUploadStore.getState().activeSize).toBeNull();
  });

  it('订阅者收到 activeSize 变化', () => {
    const seen: (number | null)[] = [];
    const unsub = useUploadStore.subscribe((s) => seen.push(s.activeSize));
    useUploadStore.getState().setSize(30);
    useUploadStore.getState().setSize(null);
    unsub();
    expect(seen).toEqual([30, null]);
  });

  it('订阅者收到 status 变化（done 后 reset）', () => {
    const seen: string[] = [];
    const unsub = useUploadStore.subscribe((s) => seen.push(s.status));
    useUploadStore.setState({ status: 'uploading' });
    useUploadStore.setState({ status: 'done', doc: sampleDoc, activeSize: 28 });
    useUploadStore.getState().reset();
    unsub();
    expect(seen).toEqual(['uploading', 'done', 'idle']);
  });
});

describe('uploadStore qtyDialog (US-012)', () => {
  it('默认 qtyDialog=null', () => {
    expect(useUploadStore.getState().qtyDialog).toBeNull();
  });

  it('openQtyDialog(label, size) 写入 {label, size}', () => {
    useUploadStore.getState().openQtyDialog('A', 30);
    expect(useUploadStore.getState().qtyDialog).toEqual({ label: 'A', size: 30 });
  });

  it('openQtyDialog(label, null) 写入 size=null（通用码）', () => {
    useUploadStore.getState().openQtyDialog('B', null);
    expect(useUploadStore.getState().qtyDialog).toEqual({ label: 'B', size: null });
  });

  it('closeQtyDialog() 清回 null', () => {
    useUploadStore.getState().openQtyDialog('A', 30);
    useUploadStore.getState().closeQtyDialog();
    expect(useUploadStore.getState().qtyDialog).toBeNull();
  });

  it('reset() 同时清 qtyDialog=null', () => {
    useUploadStore.getState().openQtyDialog('A', 30);
    useUploadStore.getState().reset();
    expect(useUploadStore.getState().qtyDialog).toBeNull();
  });

  it('订阅者收到 qtyDialog 变化（open + close）', () => {
    const seen: ({ label: string; size: number | null } | null)[] = [];
    const unsub = useUploadStore.subscribe((s) => seen.push(s.qtyDialog));
    useUploadStore.getState().openQtyDialog('A', 28);
    useUploadStore.getState().closeQtyDialog();
    unsub();
    expect(seen).toEqual([{ label: 'A', size: 28 }, null]);
  });
});

describe('uploadStore zoom (US-013)', () => {
  it('默认 zoom=null', () => {
    expect(useUploadStore.getState().zoom).toBeNull();
  });

  it('openZoom(label, size) 写入 {label, size}', () => {
    useUploadStore.getState().openZoom('A', 30);
    expect(useUploadStore.getState().zoom).toEqual({ label: 'A', size: 30 });
  });

  it('openZoom(label, null) 写入 size=null（通用码）', () => {
    useUploadStore.getState().openZoom('B', null);
    expect(useUploadStore.getState().zoom).toEqual({ label: 'B', size: null });
  });

  it('closeZoom() 清回 null', () => {
    useUploadStore.getState().openZoom('A', 30);
    useUploadStore.getState().closeZoom();
    expect(useUploadStore.getState().zoom).toBeNull();
  });

  it('reset() 同时清 zoom=null', () => {
    useUploadStore.getState().openZoom('A', 30);
    useUploadStore.getState().reset();
    expect(useUploadStore.getState().zoom).toBeNull();
  });

  it('订阅者收到 zoom 变化（open + close）', () => {
    const seen: ({ label: string; size: number | null } | null)[] = [];
    const unsub = useUploadStore.subscribe((s) => seen.push(s.zoom));
    useUploadStore.getState().openZoom('A', 28);
    useUploadStore.getState().closeZoom();
    unsub();
    expect(seen).toEqual([{ label: 'A', size: 28 }, null]);
  });

  it('zoom 与 qtyDialog 字段独立（互不干扰）', () => {
    useUploadStore.getState().openQtyDialog('A', 30);
    useUploadStore.getState().openZoom('B', 32);
    expect(useUploadStore.getState().qtyDialog).toEqual({ label: 'A', size: 30 });
    expect(useUploadStore.getState().zoom).toEqual({ label: 'B', size: 32 });
    useUploadStore.getState().closeZoom();
    expect(useUploadStore.getState().qtyDialog).toEqual({ label: 'A', size: 30 });
    expect(useUploadStore.getState().zoom).toBeNull();
  });
});

// US-005 uploadStore 单测：
//   - 默认 status='idle' / doc=null / activeSize=null / error=null
//   - reset() 清空所有字段（包括从 done 回到 idle）
//   - setSize(n) / setSize(null) 切 activeSize 并触发订阅
//   - 直接 setState({status, doc, error}) 写入（hook 内部用，UI 不直接调）

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

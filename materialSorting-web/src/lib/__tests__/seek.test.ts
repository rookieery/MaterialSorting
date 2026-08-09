// US-006 seek.ts 单测：
//   - maxElapsed: 空 / 单 run / 多 run 取 max
//   - frameAtTime: 空 / 边界 / 二分查找 与 旧 app.js 线性参考等价
//
// AC#2: frameAtTime 必须做二分（O(log n)），单测与线性参考逐 t 对比（含 1000 帧 stress）。

import { describe, expect, it } from 'vitest';
import { frameAtTime, maxElapsed, type FrameContainer } from '../seek';
import type { FrameMsg } from '../../types/ws';
import type { RunRecord } from '../../store/runRegistry';

function makeFrame(elapsed: number, density = 0.5): FrameMsg {
  return {
    type: 'frame',
    index: 0,
    elapsed,
    phase: 'exploring',
    density,
    density_sparrow: density,
    width_mm: 800,
    placed_items: [],
  };
}

describe('frameAtTime (US-006 AC#2)', () => {
  it('empty frames -> null', () => {
    const c: FrameContainer = { frames: [] };
    expect(frameAtTime(c, 5)).toBeNull();
  });

  it('single frame, t before -> returns the only frame (ans init=0)', () => {
    const c: FrameContainer = { frames: [makeFrame(1)] };
    expect(frameAtTime(c, 0)).toBe(c.frames[0]);
  });

  it('single frame, t after -> returns the only frame', () => {
    const c: FrameContainer = { frames: [makeFrame(1)] };
    expect(frameAtTime(c, 100)).toBe(c.frames[0]);
  });

  it('three frames, t equals middle -> returns middle', () => {
    const c: FrameContainer = { frames: [makeFrame(1), makeFrame(2), makeFrame(3)] };
    expect(frameAtTime(c, 2)).toBe(c.frames[1]);
  });

  it('three frames, t between frames -> returns the lower (elapsed <= t)', () => {
    const c: FrameContainer = { frames: [makeFrame(1), makeFrame(2), makeFrame(3)] };
    expect(frameAtTime(c, 2.5)).toBe(c.frames[1]);
  });

  it('three frames, t after last -> returns last', () => {
    const c: FrameContainer = { frames: [makeFrame(1), makeFrame(2), makeFrame(3)] };
    expect(frameAtTime(c, 100)).toBe(c.frames[2]);
  });

  it('three frames, t before first -> returns first (ans init=0)', () => {
    const c: FrameContainer = { frames: [makeFrame(1), makeFrame(2), makeFrame(3)] };
    expect(frameAtTime(c, -10)).toBe(c.frames[0]);
  });

  it('binary search matches linear reference (10 frames, sampled t)', () => {
    const frames: FrameMsg[] = [];
    for (let i = 0; i < 10; i++) frames.push(makeFrame(i, i * 0.01));
    const c: FrameContainer = { frames };
    function linear(t: number): FrameMsg {
      let ans = 0;
      for (let i = 0; i < frames.length; i++) if (frames[i].elapsed <= t) ans = i;
      return frames[ans];
    }
    for (const t of [-1, 0, 0.5, 1, 1.5, 5.5, 9, 9.5, 10, 100]) {
      expect(frameAtTime(c, t)).toBe(linear(t));
    }
  });

  it('binary search matches linear reference (1000 frames, stress)', () => {
    // 与旧 app.js 字节级一致 —— 1000 帧（典型 final n_frames 量级），随机 t 验证二分正确性。
    const frames: FrameMsg[] = [];
    for (let i = 0; i < 1000; i++) frames.push(makeFrame(i * 0.05, i * 0.0005));
    const c: FrameContainer = { frames };
    function linear(t: number): FrameMsg {
      let ans = 0;
      for (let i = 0; i < frames.length; i++) if (frames[i].elapsed <= t) ans = i;
      return frames[ans];
    }
    const ts = [-1, 0, 0.001, 1.234, 12.5, 25.3, 49.95, 50, 50.5, 99.95, 100, 1000];
    for (const t of ts) {
      expect(frameAtTime(c, t)).toBe(linear(t));
    }
  });

  it('handles duplicate elapsed values (degenerate monotonic)', () => {
    // solver 偶尔在 fast-report 模式下连推同 elapsed 多帧；二分仍应稳定返回最大索引。
    const c: FrameContainer = {
      frames: [makeFrame(1), makeFrame(2), makeFrame(2), makeFrame(2), makeFrame(3)],
    };
    // t=2：最大的 i 使 elapsed<=2 是 i=3
    expect(frameAtTime(c, 2)).toBe(c.frames[3]);
  });
});

describe('maxElapsed (US-006 AC#1)', () => {
  it('empty array -> 0', () => {
    expect(maxElapsed([])).toBe(0);
  });

  it('all empty frames -> 0', () => {
    const a = { frames: [] } as FrameContainer;
    const b = { frames: [] } as FrameContainer;
    expect(maxElapsed([a, b])).toBe(0);
  });

  it('single run -> its last frame elapsed', () => {
    const a = { frames: [makeFrame(1), makeFrame(5), makeFrame(7)] } as FrameContainer;
    expect(maxElapsed([a])).toBe(7);
  });

  it('multi run -> max of last', () => {
    const a = { frames: [makeFrame(1), makeFrame(5)] } as FrameContainer;
    const b = { frames: [makeFrame(1), makeFrame(9), makeFrame(12)] } as FrameContainer;
    const c = { frames: [makeFrame(2), makeFrame(8)] } as FrameContainer;
    expect(maxElapsed([a, b, c])).toBe(12);
  });

  it('mix of empty and non-empty -> only non-empty contributes', () => {
    const a = { frames: [] } as FrameContainer;
    const b = { frames: [makeFrame(0.5), makeFrame(3)] } as FrameContainer;
    expect(maxElapsed([a, b])).toBe(3);
  });

  it('RunRecord 也能直接传入（结构兼容）', () => {
    // 验证 FrameContainer 接口能容纳 RunRecord（解耦契约）。
    const rec = { frames: [makeFrame(2), makeFrame(4)] } as unknown as RunRecord;
    expect(maxElapsed([rec])).toBe(4);
  });
});

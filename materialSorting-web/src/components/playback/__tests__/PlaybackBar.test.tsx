// US-006 PlaybackBar 集成测试：
//   AC#1 全部 run 完成 → seekbar 启用，max = ceil(maxElapsed)，value 默认到末尾
//   AC#1 求解中 / 未启动 → seekbar disabled，max=0，readout "—"
//   AC#2 拖动 seekbar → setSeekTime(t)，NestSVG 切到 frameAtTime（在 NestSVG.test 验证）
//   AC#3 SeekReadout 显示 `t=X.Xs | sN yy.yy% | sM zz.zz%`

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PlaybackBar } from '../PlaybackBar';
import { Seekbar } from '../Seekbar';
import { SeekReadout } from '../SeekReadout';
import { useAppStore } from '../../../store/appStore';
import { runRegistry, type RunRecord } from '../../../store/runRegistry';
import type { FrameMsg, ManifestMsg } from '../../../types/ws';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  runRegistry.clear();
  useAppStore.setState({ renderTick: 0, seekTime: -1 });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) {
    const r = root;
    act(() => {
      r.unmount();
    });
    root = null;
  }
  container?.remove();
  container = null;
  runRegistry.clear();
});

function renderWith(children: React.ReactNode) {
  act(() => {
    root!.render(<StrictMode>{children}</StrictMode>);
  });
}

function makeManifest(): ManifestMsg {
  return {
    type: 'manifest',
    gate_mm: 1980,
    total_area_mm2: 100000,
    n_eroded: 0,
    pieces: [],
  };
}

/** 推入 N 帧到 rec，elapsed = base + i*step，density = i*0.001。 */
function pushFrames(rec: RunRecord, n: number, base = 0, step = 0.5): void {
  for (let i = 0; i < n; i++) {
    const f: FrameMsg = {
      type: 'frame',
      index: i,
      elapsed: base + i * step,
      phase: 'exploring',
      density: 0.5 + i * 0.001,
      density_sparrow: 0.5 + i * 0.001,
      width_mm: 1000,
      placed_items: [],
    };
    rec.frames.push(f);
    rec.lastFrame = f;
  }
}

describe('PlaybackBar (US-006)', () => {
  it('无 run → .playback 容器 + disabled seekbar (max=0) + readout "—"', () => {
    renderWith(<PlaybackBar />);
    const playback = container!.querySelector('.playback');
    expect(playback).not.toBeNull();
    const seek = container!.querySelector<HTMLInputElement>('#seek')!;
    expect(seek.disabled).toBe(true);
    expect(parseInt(seek.max, 10)).toBe(0);
    expect(container!.querySelector('#seek-readout')!.textContent).toBe('—');
  });

  it('求解中（run 未全部 done）→ seekbar 仍 disabled + readout "—"', () => {
    const rec = runRegistry.create(0);
    rec.manifest = makeManifest();
    pushFrames(rec, 5);
    rec.done = false; // 求解中
    renderWith(<PlaybackBar />);
    expect(container!.querySelector<HTMLInputElement>('#seek')!.disabled).toBe(true);
    expect(container!.querySelector('#seek-readout')!.textContent).toBe('—');
  });

  it('AC#1 全部完成 → seekbar 启用，max = ceil(maxElapsed)，value 默认到末尾', () => {
    const rec = runRegistry.create(0);
    rec.manifest = makeManifest();
    pushFrames(rec, 11, 0, 1); // elapsed: 0,1,2,...,10 → maxElapsed=10
    rec.done = true;
    rec.finalDensity = 0.65;
    // App.onDone 会 setSeekTime(me)；这里手动模拟
    act(() => useAppStore.getState().setSeekTime(10));
    renderWith(<PlaybackBar />);
    const seek = container!.querySelector<HTMLInputElement>('#seek')!;
    expect(seek.disabled).toBe(false);
    expect(parseInt(seek.max, 10)).toBe(10);
    expect(parseInt(seek.value, 10)).toBe(10);
  });

  it('AC#1 ceil(maxElapsed) 非整数 → 取 ceil（如 5.4 → 6）', () => {
    const rec = runRegistry.create(0);
    rec.manifest = makeManifest();
    pushFrames(rec, 6, 0, 0.9); // elapsed: 0, 0.9, 1.8, 2.7, 3.6, 4.5 → max=4.5 → ceil=5
    rec.done = true;
    rec.finalDensity = 0.5;
    act(() => useAppStore.getState().setSeekTime(5));
    renderWith(<PlaybackBar />);
    const seek = container!.querySelector<HTMLInputElement>('#seek')!;
    expect(parseInt(seek.max, 10)).toBe(5);
  });

  it('AC#3 全部完成后 SeekReadout 显示 "t=X.Xs | sN yy.yy%"', () => {
    const r0 = runRegistry.create(0);
    r0.manifest = makeManifest();
    pushFrames(r0, 11, 0, 1); // 0..10s，density 0.500, 0.501, ..., 0.510
    r0.done = true;
    r0.finalDensity = 0.65;
    // 模拟 App.onDone setSeekTime(10)
    act(() => useAppStore.getState().setSeekTime(10));
    renderWith(<SeekReadout />);
    const text = container!.querySelector('#seek-readout')!.textContent;
    // t=10.0s | s0 <max-frame density*100>%
    // frameAtTime(10) → frames[10].density = 0.510 → 51.00%
    expect(text).toBe('t=10.0s | s0 51.00%');
  });

  it('AC#3 多 seed SeekReadout 用 " | " 分隔', () => {
    const r0 = runRegistry.create(0);
    r0.manifest = makeManifest();
    pushFrames(r0, 6, 0, 1); // 0..5s，density 0.500..0.505
    r0.done = true;
    r0.finalDensity = 0.5;

    const r1 = runRegistry.create(1);
    r1.manifest = makeManifest();
    pushFrames(r1, 6, 0, 1);
    r1.frames.forEach((f, i) => (f.density = 0.6 + i * 0.001)); // 0.600..0.605
    r1.lastFrame = r1.frames[r1.frames.length - 1];
    r1.done = true;
    r1.finalDensity = 0.6;

    act(() => useAppStore.getState().setSeekTime(3));
    renderWith(<SeekReadout />);
    const text = container!.querySelector('#seek-readout')!.textContent;
    // t=3.0s | s0 50.30% | s1 60.30%
    expect(text).toBe('t=3.0s | s0 50.30% | s1 60.30%');
  });

  it('AC#2 拖动 seekbar → setSeekTime(t) 写进 store', () => {
    const rec = runRegistry.create(0);
    rec.manifest = makeManifest();
    pushFrames(rec, 11, 0, 1);
    rec.done = true;
    act(() => useAppStore.getState().setSeekTime(10));
    renderWith(<Seekbar max={10} disabled={false} />);
    const seek = container!.querySelector<HTMLInputElement>('#seek')!;
    // 模拟用户拖到 t=4
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(seek, '4');
      seek.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(useAppStore.getState().seekTime).toBe(4);
  });

  it('AC#1 seekTime=-1（live）+ 全完成 → value 默认到末尾（=max）', () => {
    // 全完成时 App 应已 setSeekTime(me)，但若未触发（边界），UI 应回退到 max。
    const rec = runRegistry.create(0);
    rec.manifest = makeManifest();
    pushFrames(rec, 11, 0, 1);
    rec.done = true;
    // 故意不 setSeekTime（保持 -1）
    renderWith(<Seekbar max={10} disabled={false} />);
    const seek = container!.querySelector<HTMLInputElement>('#seek')!;
    expect(parseInt(seek.value, 10)).toBe(10); // 回退到 max
  });

  it('AC#1 disabled seekbar max=0 value=0（与旧 app.js reset 一致）', () => {
    renderWith(<Seekbar max={0} disabled={true} />);
    const seek = container!.querySelector<HTMLInputElement>('#seek')!;
    expect(seek.disabled).toBe(true);
    expect(parseInt(seek.max, 10)).toBe(0);
    expect(parseInt(seek.value, 10)).toBe(0);
  });
});

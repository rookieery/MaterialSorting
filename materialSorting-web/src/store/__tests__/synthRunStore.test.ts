// synthRunStore 单测（状态文件 US-004）—— applySyntheticRun 共享落笔 +
// deepCopyPlaced 深拷贝口径 + provenanceText 文案 + 信号 store。
//
// 覆盖面（设计 §十 前端 vitest）：
//   - 清场：旧 run（含 WS 引用）被清、editStore 编辑态失效、seekTime 回 live；
//   - 合成 RunRecord 字段：frames=[帧] / lastFrame / finalDensity 双口径 /
//     viewBoxMaxW / done/error/stopped / ws=null / origin 设与不设；
//   - placed 深拷贝解耦：合成后 mutate 源数组（模拟 editStore.applyToRun 原地
//     写回）不动 registry 帧；translation 数组拷断；mirror omit-when-false；
//   - 信号：token 递增 + seed/note/origin 透传（NestingPage 消费数据源）。

import { beforeEach, describe, expect, it } from 'vitest';
import {
  applySyntheticRun,
  deepCopyPlaced,
  provenanceText,
  useSynthRunStore,
} from '../synthRunStore';
import { useAppStore } from '../appStore';
import { useEditStore } from '../editStore';
import { runRegistry } from '../runRegistry';
import type { FrameMsg, ManifestMsg } from '../../types/ws';

function makeManifest(): ManifestMsg {
  return { type: 'manifest', gate_mm: 1750, total_area_mm2: 500000, n_eroded: 2, pieces: [] };
}

function makeFrame(): FrameMsg {
  return {
    type: 'frame',
    index: 0,
    elapsed: 88.4,
    phase: 'final',
    density: 0.8435,
    density_sparrow: 0.8212,
    width_mm: 7523,
    placed_items: [
      { id: 'g02_38', rotation: 0, translation: [-1.01, 16.22] },
      { id: 'g03_34', rotation: 90, translation: [260, 40], mirror: true },
    ],
  };
}

beforeEach(() => {
  runRegistry.clear();
  useEditStore.getState().invalidate();
  useAppStore.setState({ seekTime: -1, renderTick: 0 });
  useSynthRunStore.setState({ token: 0, seed: 0, note: '', origin: undefined });
});

describe('applySyntheticRun（合成落笔，US-004）', () => {
  it('清场旧 run + 合成单条 done RunRecord 字段齐全（manifest/帧/密度双口径/viewBox）', () => {
    // 预置一条旧 run（模拟主画布现有对比 run）
    const stale = runRegistry.create(7);
    stale.done = true;

    const rec = applySyntheticRun(makeManifest(), makeFrame(), 3);

    // 恰 1 条（旧 run 被清），字段齐全
    expect(runRegistry.list()).toHaveLength(1);
    expect(runRegistry.list()[0]).toBe(rec);
    expect(rec.seed).toBe(3);
    expect(rec.manifest).toEqual(makeManifest());
    expect(rec.frames).toHaveLength(1);
    expect(rec.lastFrame).toBe(rec.frames[0]);
    expect(rec.frames[0].phase).toBe('final');
    expect(rec.frames[0].density).toBe(0.8435);
    expect(rec.finalDensity).toBe(0.8435);
    expect(rec.finalDensitySparrow).toBe(0.8212);
    expect(rec.viewBoxMaxW).toBe(7523);
    expect(rec.done).toBe(true);
    expect(rec.stopped).toBe(false);
    expect(rec.error).toBeNull();
    expect(rec.ws).toBeNull(); // 合成 run 无 WS
  });

  it('清场副作用：editStore 编辑态失效 + seekTime 回 live（-1）', () => {
    // 预置编辑会话在场 + seek 到中间帧
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const f = makeFrame();
    run.frames.push(f);
    run.lastFrame = f;
    run.finalDensity = 0.8;
    run.done = true;
    expect(useEditStore.getState().open(run)).toBe(true);
    useAppStore.setState({ seekTime: 42 });

    applySyntheticRun(makeManifest(), makeFrame(), 0);

    const st = useEditStore.getState();
    expect(st.run).toBeNull();
    expect(st.baseline).toBeNull();
    expect(st.working).toEqual([]);
    expect(useAppStore.getState().seekTime).toBe(-1);
  });

  it('placed 深拷贝解耦：合成后原地 mutate 源数组不动 registry 帧（editStore.applyToRun 别名修复）', () => {
    const frameLike = makeFrame();
    applySyntheticRun(makeManifest(), frameLike, 0);
    // 模拟 editStore.applyToRun 原地写回（对源数组直接 mutate）
    frameLike.placed_items[0].translation[0] = 99999;
    frameLike.placed_items[1].mirror = false;
    const reg = runRegistry.list()[0].lastFrame!;
    expect(reg.placed_items[0].translation[0]).toBe(-1.01);
    expect(reg.placed_items[1].mirror).toBe(true);
  });

  it('origin 缺省不设（undefined = WS 口径，保存端不写 provenance 键）；在场 → rec.origin 透传', () => {
    const recA = applySyntheticRun(makeManifest(), makeFrame(), 0);
    expect(recA.origin).toBeUndefined();
    const origin = { kind: 'extreme' as const, config: { time_total_s: 600 } };
    const recB = applySyntheticRun(makeManifest(), makeFrame(), 1, origin);
    expect(recB.origin).toEqual(origin);
  });

  it('信号：token 递增 + seed/note/origin 透传（NestingPage effect 消费数据源）', () => {
    expect(useSynthRunStore.getState().token).toBe(0);
    const origin: { kind: 'strategy_race'; config: { minutes: number } } = {
      kind: 'strategy_race',
      config: { minutes: 20 },
    };
    applySyntheticRun(makeManifest(), makeFrame(), 5, origin, '策略 run 已应用：seed 5 · 88.38%');
    const sig = useSynthRunStore.getState();
    expect(sig.token).toBe(1);
    expect(sig.seed).toBe(5);
    expect(sig.note).toBe('策略 run 已应用：seed 5 · 88.38%');
    expect(sig.origin).toEqual(origin);
    // 再次合成 → token 继续递增（每信号必新）
    applySyntheticRun(makeManifest(), makeFrame(), 6);
    expect(useSynthRunStore.getState().token).toBe(2);
  });
});

describe('deepCopyPlaced（共享深拷贝口径，US-004）', () => {
  it('保序 + translation 数组拷断 + mirror omit-when-false（false/undefined 都不带键）', () => {
    const items = [
      { id: 'a_28', rotation: 0, translation: [1, 2] as [number, number] },
      { id: 'b_30', rotation: 180, translation: [3, 4] as [number, number], mirror: false },
      { id: 'c_32', rotation: 90, translation: [5, 6] as [number, number], mirror: true },
    ];
    const copy = deepCopyPlaced(items);
    expect(copy).toHaveLength(3);
    expect(copy.map((it) => it.id)).toEqual(['a_28', 'b_30', 'c_32']);
    expect('mirror' in copy[0]).toBe(false);
    expect('mirror' in copy[1]).toBe(false); // mirror:false 不带键
    expect(copy[2].mirror).toBe(true);
    // 拷断：改副本不动源
    copy[0].translation[0] = 999;
    expect(items[0].translation[0]).toBe(1);
    // 非同一数组引用
    expect(copy).not.toBe(items);
    expect(copy[0]).not.toBe(items[0]);
  });
});

describe('provenanceText（来源小字文案，US-004）', () => {
  it('四值枚举逐一覆盖 + config 已知键渲染括号段', () => {
    expect(provenanceText({ kind: 'solve' }, 0)).toBe('来源：普通求解 · seed 0');
    expect(provenanceText({ kind: 'extreme', config: { time_total_s: 600 } }, 2)).toBe(
      '来源：极限运行(600s) · seed 2',
    );
    expect(provenanceText({ kind: 'strategy_race', config: { minutes: 20 } }, 3)).toBe(
      '来源：策略运行·race(20min) · seed 3',
    );
    expect(provenanceText({ kind: 'strategy_se', config: { minutes: 10 } }, 1)).toBe(
      '来源：策略运行·SE(10min) · seed 1',
    );
  });

  it('config 缺席 / 未知键 / 非数值 → 不渲染括号段（手改文件容错，展示级不承重）', () => {
    expect(provenanceText({ kind: 'extreme' }, 0)).toBe('来源：极限运行 · seed 0');
    expect(provenanceText({ kind: 'extreme', config: { unknown: 'x' } }, 0)).toBe(
      '来源：极限运行 · seed 0',
    );
    expect(provenanceText({ kind: 'strategy_se', config: { minutes: 'x' } }, 0)).toBe(
      '来源：策略运行·SE · seed 0',
    );
  });
});

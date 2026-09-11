// lib/stateFile 单测（状态文件 US-003）—— buildSavePayload 组装口径。
//
// 覆盖面（设计 §十 前端 vitest）：
//   - form ← formStore、quantities ← qtyStore 全量扁平化（不按码选过滤）；
//   - run 仅 done 态 bestRun 入块：无 run / 未 done / 无 lastFrame → 整键缺席
//     （纯配置档）；
//   - placed 深拷贝原序（同 pid 多副本数组多条）+ translation 数组拷断不别名
//     + mirror omit-when-false（editStore.deepCopyItems 同口径）；
//   - origin 缺席（WS 普通求解）→ 不写 provenance 键；在场 → {kind, config?}
//     映射（config 缺席不带键）；
//   - final 摘要取 RunRecord 当前值（n_frames = frames.length、
//     n_eroded = manifest.n_eroded、manifest 缺席兜底 0）。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_FORM } from '../../lib/params';
import { buildSavePayload } from '../stateFile';
import { useFormStore } from '../../store/formStore';
import { useQtyStore } from '../../store/qtyStore';
import { runRegistry, type RunRecord } from '../../store/runRegistry';
import type { FrameMsg, ManifestMsg } from '../../types/ws';

function makeManifest(): ManifestMsg {
  return { type: 'manifest', gate_mm: 1750, total_area_mm2: 500000, n_eroded: 3, pieces: [] };
}

function makeFrame(): FrameMsg {
  return {
    type: 'frame',
    index: 5,
    elapsed: 121.4,
    phase: 'final',
    density: 0.8435,
    density_sparrow: 0.8212,
    width_mm: 7523.0,
    placed_items: [
      { id: 'g02_38', rotation: 0, translation: [-1.01, 16.22] },
      { id: 'g02_38', rotation: 180, translation: [500.5, -8.75] },
      { id: 'g03_34', rotation: 90, translation: [260, 40], mirror: true },
    ],
  };
}

/** done 态 run 夹具（默认无 origin = WS 普通求解）。 */
function makeDoneRun(seed = 0): RunRecord {
  const rec = runRegistry.create(seed);
  rec.manifest = makeManifest();
  const f = makeFrame();
  rec.frames.push(f);
  rec.lastFrame = f;
  rec.finalDensity = 0.8435;
  rec.finalDensitySparrow = 0.8212;
  rec.done = true;
  return rec;
}

beforeEach(() => {
  useFormStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  runRegistry.clear();
});

afterEach(() => {
  useFormStore.getState().reset();
  useQtyStore.getState().resetQuantities();
  runRegistry.clear();
});

describe('buildSavePayload：form / quantities（US-003）', () => {
  it('form ← formStore 当前值原样、quantities ← qtyStore 全量扁平化（不按码选过滤）', () => {
    useFormStore.getState().patch({ sizes: [30, 34], gate: '180.00' });
    useQtyStore.getState().setPiecePerSize('g01', 30, 2);
    useQtyStore.getState().setPiecePerSize('g01', 34, 1);
    useQtyStore.getState().setPiecePerSize('g02', 30, 0); // 显式 0 保留
    const p = buildSavePayload();
    expect(p.form.sizes).toEqual([30, 34]);
    expect(p.form.gate).toBe('180.00');
    // 未勾选码（34）的数量也随文件走 —— 与 serializeQuantities（WS 载荷按码选
    // 过滤）的有意分歧：状态文件要跨机完整还原数量矩阵
    expect(p.quantities).toEqual({ g01: { '30': 2, '34': 1 }, g02: { '30': 0 } });
  });

  it('空数量矩阵 → quantities=null（后端 demand 全 1 口径）', () => {
    expect(buildSavePayload().quantities).toBeNull();
  });
});

describe('buildSavePayload：run 块（US-003）', () => {
  it('无 run → 整键缺席（纯配置档；后端 build_state_document 同语义）', () => {
    const p = buildSavePayload();
    expect('run' in p).toBe(false);
  });

  it('run 未 done（running 中）→ 整键缺席', () => {
    const rec = runRegistry.create(0);
    rec.manifest = makeManifest();
    rec.frames.push(makeFrame());
    rec.lastFrame = rec.frames[0];
    rec.done = false;
    expect('run' in buildSavePayload()).toBe(false);
  });

  it('done 态 → run 块含 seed / final 摘要 / placed 深拷贝原序', () => {
    makeDoneRun(9);
    const p = buildSavePayload();
    expect(p.run).toBeDefined();
    expect(p.run!.seed).toBe(9);
    // WS 普通求解 origin 缺席 → 不写 provenance 键（后端缺省 'solve'，老文件零惩罚）
    expect('provenance' in p.run!).toBe(false);
    expect(p.run!.final).toEqual({
      density: 0.8435,
      density_sparrow: 0.8212,
      width_mm: 7523.0,
      elapsed: 121.4,
      n_frames: 1,
      n_eroded: 3,
    });
    // placed 原序 + 同 pid 多副本数组多条（g02_38 × 2）+ mirror omit-when-false
    expect(p.run!.placed).toHaveLength(3);
    expect(p.run!.placed.map((it) => it.id)).toEqual(['g02_38', 'g02_38', 'g03_34']);
    expect('mirror' in p.run!.placed[0]).toBe(false);
    expect('mirror' in p.run!.placed[1]).toBe(false);
    expect(p.run!.placed[2].mirror).toBe(true);
  });

  it('placed 深拷贝：translation 数组拷断（改 payload 不动 lastFrame）', () => {
    makeDoneRun();
    const p1 = buildSavePayload();
    p1.run!.placed[0].translation[0] = 99999;
    const frame = runRegistry.list()[0].lastFrame!;
    expect(frame.placed_items[0].translation[0]).toBe(-1.01);
    // 再次构建不受污染
    const p2 = buildSavePayload();
    expect(p2.run!.placed[0].translation[0]).toBe(-1.01);
  });

  it('mirror=false 的条目不带键（omit-when-false，键集与 wire 契约一致）', () => {
    const rec = makeDoneRun();
    rec.lastFrame!.placed_items[1] = { id: 'g02_38', rotation: 180, translation: [1, 2], mirror: false };
    const p = buildSavePayload();
    expect('mirror' in p.run!.placed[1]).toBe(false);
  });

  it('manifest 缺席 → final.n_eroded 兜底 0', () => {
    const rec = makeDoneRun();
    rec.manifest = null;
    expect(buildSavePayload().run!.final.n_eroded).toBe(0);
  });

  it('bestRun 取 finalDensity 最高者（多 run 场景与导出同口径）', () => {
    const lo = makeDoneRun(0);
    lo.finalDensity = 0.5;
    const hi = makeDoneRun(1);
    hi.finalDensity = 0.9;
    const p = buildSavePayload();
    expect(p.run!.seed).toBe(1);
    expect(p.run!.final.density).toBe(0.9);
  });
});

describe('buildSavePayload：origin → provenance 映射（US-004 写入方的前置锁）', () => {
  it('origin 在场带 config → provenance = {kind, config}', () => {
    const rec = makeDoneRun();
    rec.origin = { kind: 'extreme', config: { time_total_s: 600 } };
    const p = buildSavePayload();
    expect(p.run!.provenance).toEqual({ kind: 'extreme', config: { time_total_s: 600 } });
  });

  it('origin 在场无 config → provenance 只含 kind（config 键缺席）', () => {
    const rec = makeDoneRun();
    rec.origin = { kind: 'strategy_race' };
    const p = buildSavePayload();
    expect(p.run!.provenance).toEqual({ kind: 'strategy_race' });
    expect('config' in p.run!.provenance!).toBe(false);
  });

  it('origin 缺席（WS 普通求解默认态）→ provenance 键缺席', () => {
    makeDoneRun();
    expect('provenance' in buildSavePayload().run!).toBe(false);
  });
});

describe('buildSavePayload：form 原样（FormState 全量）', () => {
  it('form 与 formStore 当前值逐字段相等（DEFAULT_FORM 基线）', () => {
    expect(buildSavePayload().form).toEqual(DEFAULT_FORM);
  });
});

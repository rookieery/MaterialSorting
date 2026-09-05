// editPolish.ts 纯函数单测（edit-polish US-003，2026-09-05；US-005 补 compact 档）：
//   1) parsePrefixMemberPids：组合片 pid（含 5 片补片形态）→ 成员 pid 集合；
//      extra.pid 直收去重；非 PS_ 前缀 / 畸形段静默跳过（best-effort）。
//   2) buildExclude：band → labels；final.prefix → pids；双开双键；皆无 → undefined。
//   3) buildPolishPayload：placed 逐字段拷贝（translation 拷断引用）+ gate_mm 取
//      manifest + exclude 组装 + compact 档（US-005：缺省 false 省略键 additive）；
//      无 manifest / working 空 → null。
// postEditPolish 的 HTTP 行为在 EditLayoutModal.polish.test 组件级覆盖（apiFetch mock）。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { buildExclude, buildPolishPayload, parsePrefixMemberPids } from '../editPolish';
import { runRegistry } from '../../store/runRegistry';
import type { ManifestMsg } from '../../types/ws';
import type { PlacedItem } from '../../types/piece';

beforeEach(() => {
  runRegistry.clear();
});

afterEach(() => {
  runRegistry.clear();
});

function makeManifest(): ManifestMsg {
  return {
    type: 'manifest',
    gate_mm: 1000,
    total_area_mm2: 500000,
    n_eroded: 0,
    pieces: [],
  };
}

describe('parsePrefixMemberPids', () => {
  it('4 片组合 pid（首段裸 front label，size 取 stats.size）→ 前/后幅成员 pid', () => {
    expect(parsePrefixMemberPids('PS_g02+g03@34', 34, null)).toEqual(['g02_34', 'g03_34']);
    // stats.size 缺席 → front 段无从补全 size，best-effort 只收带 @ 的段
    expect(parsePrefixMemberPids('PS_g02+g03@34', null, null)).toEqual(['g03_34']);
  });

  it('5 片组合 pid（含补片段）→ 三成员；extra.pid 直收去重', () => {
    expect(parsePrefixMemberPids('PS_g02+g03@34+g02@32', 34, null)).toEqual([
      'g02_34',
      'g03_34',
      'g02_32',
    ]);
    expect(parsePrefixMemberPids('PS_g02+g03@34', 34, { pid: 'g05_32' })).toEqual([
      'g02_34',
      'g03_34',
      'g05_32',
    ]);
    // extra.pid 与组合段重复 → 集合语义不重复
    expect(parsePrefixMemberPids('PS_g02+g03@34', 34, { pid: 'g02_34' })).toEqual([
      'g02_34',
      'g03_34',
    ]);
  });

  it('非 PS_ 前缀 / 畸形段 / 空 extra → best-effort 静默（空集或跳过）', () => {
    expect(parsePrefixMemberPids('g01_30', 30, null)).toEqual([]);
    expect(parsePrefixMemberPids('', null, { pid: 'g02_32' })).toEqual(['g02_32']);
    expect(parsePrefixMemberPids('PS_g02+g03@34', 34, undefined)).toEqual(['g02_34', 'g03_34']);
    expect(parsePrefixMemberPids('PS_@34+g03@', 34, null)).toEqual([]);
  });
});

describe('buildExclude（exclude best-effort 组装）', () => {
  it('run 带 band 配置 → {labels:[label]}', () => {
    const run = runRegistry.create(0);
    run.band = { enabled: true, label: 'g05' };
    expect(buildExclude(run)).toEqual({ labels: ['g05'] });
  });

  it('band enabled=false / label 空 → 不计 labels', () => {
    const run = runRegistry.create(0);
    run.band = { enabled: false, label: 'g05' };
    expect(buildExclude(run)).toBeUndefined();
    run.band = { enabled: true, label: '' };
    expect(buildExclude(run)).toBeUndefined();
  });

  it('final 带 prefix 统计段 → {pids:[成员 pid 集合]}', () => {
    const run = runRegistry.create(0);
    run.prefix = {
      size: 34,
      pid: 'PS_g02+g03@34+g02@32',
      extra: { pid: 'g02_32', label: 'g02', size: 32, rotation: 180 },
      residual_mm: 3.2,
      fallback: false,
    };
    expect(buildExclude(run)).toEqual({ pids: ['g02_34', 'g03_34', 'g02_32'] });
  });

  it('band + prefix 双开 → 双键并集', () => {
    const run = runRegistry.create(0);
    run.band = { enabled: true, label: 'g05' };
    run.prefix = { size: 34, pid: 'PS_g02+g03@34', extra: null };
    expect(buildExclude(run)).toEqual({ labels: ['g05'], pids: ['g02_34', 'g03_34'] });
  });

  it('两者皆无（含策略合成 run）→ undefined（载荷省略 exclude 键）', () => {
    expect(buildExclude(runRegistry.create(0))).toBeUndefined();
    expect(buildExclude(null)).toBeUndefined();
  });
});

describe('buildPolishPayload', () => {
  const working: PlacedItem[] = [
    { id: 'a_28', rotation: 0, translation: [0, 0] },
    { id: 'b_30', rotation: 25, translation: [600, 10] },
  ];

  it('placed 逐字段 + gate_mm 取 manifest；无 exclude 记录 → 无 exclude 键', () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    const p = buildPolishPayload(working, run)!;
    expect(p.gate_mm).toBe(1000);
    expect(p.placed).toEqual([
      { id: 'a_28', rotation: 0, translation: [0, 0] },
      { id: 'b_30', rotation: 25, translation: [600, 10] },
    ]);
    expect('exclude' in p).toBe(false);
    // translation 拷断引用（载荷与 working 解耦）
    expect(p.placed[1].translation).not.toBe(working[1].translation);
  });

  it('band 记录在案 → exclude.labels 命中', () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    run.band = { enabled: true, label: 'g05' };
    expect(buildPolishPayload(working, run)!.exclude).toEqual({ labels: ['g05'] });
  });

  it('无 manifest / working 空 → null（不可微调）', () => {
    const run = runRegistry.create(0);
    expect(buildPolishPayload(working, run)).toBeNull();
    run.manifest = makeManifest();
    expect(buildPolishPayload([], run)).toBeNull();
    expect(buildPolishPayload(working, null)).toBeNull();
  });

  // ---- US-005 compact 压缩回收档（additive：false 省略键）----

  it('compact 缺省/false → 载荷省略 compact 键（服务端缺省同值 additive）', () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    expect('compact' in buildPolishPayload(working, run)!).toBe(false);
    expect('compact' in buildPolishPayload(working, run, false)!).toBe(false);
  });

  it('compact=true → compact:true 随载荷发出', () => {
    const run = runRegistry.create(0);
    run.manifest = makeManifest();
    expect(buildPolishPayload(working, run, true)!.compact).toBe(true);
  });
});

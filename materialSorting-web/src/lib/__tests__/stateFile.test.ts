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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

  it('quantities_base ← baseValue 收集（省键式：只收 ≠1 的行，全 1 → 整键缺席）', () => {
    // 全默认（只逐格改 / hydrate 物化）→ 整键缺席（旧文件口径零迁移）
    useQtyStore.getState().setPiecePerSize('g01', 30, 2);   // 逐格改不动 baseValue
    expect('quantities_base' in buildSavePayload()).toBe(false);

    // 整列设值 3（setRowAll 写 baseValue）→ 收集该行；g02 未设 → 省键
    useQtyStore.getState().setRowAll('g01', [30, 34], 3);
    const p = buildSavePayload();
    expect(p.quantities_base).toEqual({ g01: 3 });

    // baseValue 回 1（整列设值 1）→ 再省键
    useQtyStore.getState().setRowAll('g01', [30, 34], 1);
    expect('quantities_base' in buildSavePayload()).toBe(false);
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

// ============================================================
// applyRestorePayload（US-004 恢复编排）—— POST /api/state-restore 成功响应
// → 五 store 落笔 + run 合成 + 切超排 Tab 的单一实现。
// ============================================================

import { applyRestorePayload } from '../stateFile';
import { useEditStore } from '../../store/editStore';
import { usePtypeStore } from '../../store/ptypeStore';
import { useSynthRunStore } from '../../store/synthRunStore';
import { useUiStore } from '../../store/uiStore';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedDoc } from '../../types/parsed';
import type { StateRestoreResponse, StateSaveRun } from '../../types/stateFile';

/** 恢复响应夹具：g01 在 28/30 两码 + g02@30 + run 块（含 final/provenance）。 */
function makeRestore(over: Partial<StateRestoreResponse> = {}): StateRestoreResponse {
  const piece = (label: string) => ({
    label,
    polygon: [],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
  });
  const fin = { density: 0.8435, density_sparrow: 0.8212, width_mm: 7523, elapsed: 121.4, n_frames: 42, n_eroded: 2 };
  const placed = [
    { id: 'g01_28', rotation: 0, translation: [10, 20] as [number, number] },
    { id: 'g01_30', rotation: 180, translation: [30, 40] as [number, number], mirror: true },
  ];
  const parse: ParsedDoc = {
    doc_id: 'restored-abc',
    filename: 'M1787.dxf',
    sizes: [
      { size: 28, pieces: [piece('g01')] },
      { size: 30, pieces: [piece('g01'), piece('g02')] },
    ],
  };
  return {
    doc_id: 'restored-abc',
    filename: 'M1787.dxf',
    parse,
    manifest: { gate_mm: 1750, total_area_mm2: 500000, n_eroded: 2, pieces: [] },
    final: fin,
    placed,
    run: {
      seed: 7,
      provenance: { kind: 'extreme', config: { time_total_s: 600 } },
      final: fin,
      placed,
    },
    form: { ...DEFAULT_FORM, sizes: [28, 30], gate: '180.00', time: '60' },
    quantities: { g01: { '28': 3, '30': 0 }, g02: { '30': 5 } },
    // g01 整列设值 3 后 30 码手改 0（base=3）；g02 未设 → 省键式缺席
    quantities_base: { g01: 3 },
    pending_strategy_result: null,
    ...over,
  };
}

describe('applyRestorePayload（US-004 恢复编排）', () => {
  beforeEach(() => {
    useUploadStore.getState().reset();
    useUiStore.setState({ activeTab: 'preview', nestingEnabled: false });
    usePtypeStore.getState().reset();
    useSynthRunStore.setState({ token: 0, seed: 0, note: '', origin: undefined });
    useEditStore.getState().invalidate();
  });

  it('全量编排（含 run）：五 store 落笔 + run 合成 + 切超排 Tab', () => {
    applyRestorePayload(makeRestore());

    // 1) uploadStore doc 就绪（parse 载荷；activeSize 同 .dxf 口径取最小码；commit 字段回 idle）
    const up = useUploadStore.getState();
    expect(up.status).toBe('done');
    expect(up.doc).not.toBeNull();
    expect(up.doc!.doc_id).toBe('restored-abc');
    expect(up.activeSize).toBe(28);
    expect(up.commitStatus).toBe('idle');
    expect(up.commitSummary).toBeNull();
    expect(up.error).toBeNull();

    // 2) qtyStore：默认物化之上 flat 实值覆盖（g01@28=3 / g01@30=0 / g02@30=5）
    //    + quantities_base 写回行基准（g01=3 命中覆写；g02 省键 → 保持物化 1）
    const qty = useQtyStore.getState().quantities;
    expect(qty.g01.perSize).toEqual({ '28': 3, '30': 0 });
    expect(qty.g02.perSize).toEqual({ '30': 5 });
    expect(qty.g01.baseValue).toBe(3);
    expect(qty.g02.baseValue).toBe(1);

    // 3) formStore 水合 + token = 恢复响应新 doc_id
    const fs = useFormStore.getState();
    expect(fs.form.sizes).toEqual([28, 30]);
    expect(fs.form.gate).toBe('180.00');
    expect(fs.hydratedToken).toBe('restored-abc');

    // 4) run 合成：恰 1 条 done record + provenance 透传 + 信号 + 切超排 Tab
    const runs = runRegistry.list();
    expect(runs).toHaveLength(1);
    const rec = runs[0];
    expect(rec.seed).toBe(7);
    expect(rec.done).toBe(true);
    expect(rec.finalDensity).toBe(0.8435);
    expect(rec.finalDensitySparrow).toBe(0.8212);
    expect(rec.viewBoxMaxW).toBe(7523);
    expect(rec.origin).toEqual({ kind: 'extreme', config: { time_total_s: 600 } });
    expect(rec.manifest!.type).toBe('manifest');
    expect(rec.manifest!.gate_mm).toBe(1750);
    expect(rec.frames).toHaveLength(1);
    expect(rec.lastFrame!.phase).toBe('final');
    expect(rec.lastFrame!.placed_items.map((it) => it.id)).toEqual(['g01_28', 'g01_30']);
    const sig = useSynthRunStore.getState();
    expect(sig.token).toBe(1);
    expect(sig.seed).toBe(7);
    expect(sig.note).toContain('状态文件已恢复');
    expect(sig.note).toContain('84.35%');
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('ptypeStore invalidate：status 回 idle、representatives 保留（无感刷新口径）', () => {
    usePtypeStore.setState({ status: 'ready', representatives: { g01: {} as never } });
    applyRestorePayload(makeRestore());
    const st = usePtypeStore.getState();
    expect(st.status).toBe('idle');
    expect(st.representatives.g01).toBeDefined();
  });

  it('run 块缺席（纯配置档）→ store 落笔但不合成 run、不切 Tab（留预览页核对数量）', () => {
    applyRestorePayload(makeRestore({ run: null, final: null, placed: null }));
    expect(runRegistry.list()).toHaveLength(0);
    expect(useSynthRunStore.getState().token).toBe(0);
    expect(useUiStore.getState().activeTab).toBe('preview');
    expect(useUiStore.getState().nestingEnabled).toBe(false);
    // doc/qty/form 仍落笔（恢复 ≠ 求解）
    expect(useUploadStore.getState().status).toBe('done');
    expect(useQtyStore.getState().quantities.g01.perSize['28']).toBe(3);
    expect(useFormStore.getState().hydratedToken).toBe('restored-abc');
  });

  it('run.provenance 缺省 → origin 兜底 {kind:"solve"}（恢复的普通求解结果也回显来源）', () => {
    const res = makeRestore();
    const runNoProv = { ...res.run! };
    delete runNoProv.provenance;
    applyRestorePayload({ ...res, run: runNoProv });
    expect(runRegistry.list()[0].origin).toEqual({ kind: 'solve' });
    expect(useSynthRunStore.getState().origin).toEqual({ kind: 'solve' });
  });

  it('placed 深拷贝解耦：编排后 mutate res.placed 不动 registry 帧（applyToRun 别名防御）', () => {
    const res = makeRestore();
    applyRestorePayload(res);
    res.placed![0].translation[0] = 99999;
    const frame = runRegistry.list()[0].lastFrame!;
    expect(frame.placed_items[0].translation[0]).toBe(10);
  });

  it('清场语义：旧 run / 编辑态随合成清空（恢复 = 显式覆盖当前工作台）', () => {
    const stale = runRegistry.create(9);
    stale.done = true;
    const editable = runRegistry.create(0);
    editable.manifest = makeManifest();
    const f = makeFrame();
    editable.frames.push(f);
    editable.lastFrame = f;
    editable.finalDensity = 0.5;
    expect(useEditStore.getState().open(editable)).toBe(true);
    useUiStore.setState({ nestingEnabled: true });

    applyRestorePayload(makeRestore());

    expect(runRegistry.list().includes(stale)).toBe(false);
    const st = useEditStore.getState();
    expect(st.run).toBeNull();
    expect(st.baseline).toBeNull();
  });
});

describe('applyRestorePayload：run.final 缺席兜底（US-004 手改文件容错）', () => {
  beforeEach(() => {
    useUploadStore.getState().reset();
    useUiStore.setState({ activeTab: 'preview', nestingEnabled: false });
    usePtypeStore.getState().reset();
    useSynthRunStore.setState({ token: 0, seed: 0, note: '', origin: undefined });
  });

  it('finalizeFromLayout：computeLayoutStats 现算 density/width（物理毛版 raw 包络 + real 口径）', () => {
    // 单片 100×60 矩形 @ (0,0)：包络 maxX=100 → width=ceil(100)；
    // density = total_area/(width×gate) = 50000/(100×1000) = 0.5
    const res = makeRestore();
    // final 键整删（v1 内可省键，手改文件形态）
    const runNoFinal: Partial<StateSaveRun> = { ...res.run! };
    delete runNoFinal.final;
    const manifest: Omit<ManifestMsg, 'type'> = {
      gate_mm: 1000,
      total_area_mm2: 50000,
      n_eroded: 1,
      pieces: [
        {
          id: 'g01_28',
          label: 'g01',
          size: 28,
          color: '#000',
          area_mm2: 6000,
          polygon: [[0, 0], [100, 0], [100, 60], [0, 60]] as [number, number][],
        },
      ],
    };
    const one = [{ id: 'g01_28', rotation: 0, translation: [0, 0] as [number, number] }];
    applyRestorePayload({ ...res, manifest, placed: one, run: { ...runNoFinal, placed: one } as StateSaveRun });
    const rec = runRegistry.list()[0];
    expect(rec.finalDensity).toBe(0.5);
    expect(rec.viewBoxMaxW).toBe(100);
    // density_sparrow/elapsed 客户端不可知 → 0（展示级参考值）
    expect(rec.finalDensitySparrow).toBe(0);
    expect(rec.lastFrame!.elapsed).toBe(0);
  });
});

// ============================================================
// US-002：pending_strategy_result 槽 —— buildSavePayload 组装 + applyRestorePayload
// 第 6 步（mode 路由两族 + openModal 自动开弹窗）
// ============================================================

import { useControlPanelStore } from '../../store/controlPanelStore';
import { useExtremeStore, useStrategyStore } from '../../store/strategyStore';
import type { StrategyResult } from '../../types/strategy';
import type { StatePendingStrategyResult } from '../../types/stateFile';

/** done 结果夹具（placed_items 与 makeFrame 同构 + race summary）。 */
function makeDoneResult(mode: 'se' | 'race' | 'extreme' = 'race'): StrategyResult {
  return {
    state: 'done',
    mode,
    run_dir: 'out/config_runs/web_race_x_1',
    manifest: { gate_mm: 1750, total_area_mm2: 500000, n_eroded: 0, pieces: [] },
    best: {
      seed: 7, frame_index: 42, elapsed: 311.2, density: 0.861,
      density_sparrow: 0.843, width_mm: 7310.5,
      placed_items: [
        { id: 'g01_30', rotation: 0, translation: [-1.01, 16.22] },
        { id: 'g03_30', rotation: 90, translation: [260, 40], mirror: true },
      ],
    },
    summary: {
      per_seed: [], mode: 'race',
      race: { gate_seconds: 90, kept_seeds: [7], gated_seeds: [1, 2] },
    },
  };
}

describe('buildSavePayload：pending_strategy_result 槽（US-002）', () => {
  beforeEach(() => {
    useStrategyStore.getState().reset();
    useExtremeStore.getState().reset();
  });
  afterEach(() => {
    useStrategyStore.getState().reset();
    useExtremeStore.getState().reset();
  });

  it('两族无 result → 整键缺席（旧口径对拍：无 pending 载荷零迁移）', () => {
    expect('pending_strategy_result' in buildSavePayload()).toBe(false);
  });

  it('done 结果在场未应用 → 槽入载荷（mode/best/summary 逐字段；不含 state/run_dir/manifest）', () => {
    useStrategyStore.setState({ phase: 'done', result: makeDoneResult('race'), resultApplied: false });
    const slot = buildSavePayload().pending_strategy_result!;
    expect(slot).toBeDefined();
    expect(slot.mode).toBe('race');
    expect(slot.best).toEqual({
      seed: 7, frame_index: 42, elapsed: 311.2, density: 0.861,
      density_sparrow: 0.843, width_mm: 7310.5,
      placed_items: [
        { id: 'g01_30', rotation: 0, translation: [-1.01, 16.22] },
        { id: 'g03_30', rotation: 90, translation: [260, 40], mirror: true },
      ],
    });
    expect(slot.summary.race).toEqual({ gate_seconds: 90, kept_seeds: [7], gated_seeds: [1, 2] });
    // 槽不带 state/run_dir/manifest（后端契约最小面）
    expect('state' in slot).toBe(false);
    expect('run_dir' in slot).toBe(false);
    expect('manifest' in slot).toBe(false);
  });

  it('极限族（extreme）result 同入槽（mode 路由键透传）', () => {
    useExtremeStore.setState({ phase: 'done', result: makeDoneResult('extreme'), resultApplied: false });
    expect(buildSavePayload().pending_strategy_result!.mode).toBe('extreme');
  });

  it('应用后（resultApplied）→ 整键缺席（已应用结果由 run 块承载，无双份数据）', () => {
    useStrategyStore.setState({ phase: 'done', result: makeDoneResult(), resultApplied: true });
    expect('pending_strategy_result' in buildSavePayload()).toBe(false);
  });

  it('stopped 结果不入槽（槽恒 done —— 后端 US-001 契约）', () => {
    const stopped: StrategyResult = { ...makeDoneResult(), state: 'stopped' };
    useStrategyStore.setState({ phase: 'stopped', result: stopped, resultApplied: false });
    expect('pending_strategy_result' in buildSavePayload()).toBe(false);
  });

  it('placed 深拷贝解耦：mutate 载荷不动 store result', () => {
    useStrategyStore.setState({ phase: 'done', result: makeDoneResult(), resultApplied: false });
    const p = buildSavePayload();
    p.pending_strategy_result!.best.placed_items[0].translation[0] = 99999;
    expect(useStrategyStore.getState().result!.best.placed_items[0].translation[0]).toBe(-1.01);
    // 再次构建不受污染
    expect(buildSavePayload().pending_strategy_result!.best.placed_items[0].translation[0]).toBe(-1.01);
  });

  it('mirror omit-when-false 同口径（deepCopyPlaced 单一实现）', () => {
    const r = makeDoneResult();
    r.best.placed_items[1] = { id: 'g03_30', rotation: 90, translation: [1, 2], mirror: false };
    useStrategyStore.setState({ phase: 'done', result: r, resultApplied: false });
    const placed = buildSavePayload().pending_strategy_result!.best.placed_items;
    expect('mirror' in placed[0]).toBe(false);
    expect('mirror' in placed[1]).toBe(false);
  });
});

describe('applyRestorePayload：pending_strategy_result 第 6 步（US-002）', () => {
  beforeEach(() => {
    useUploadStore.getState().reset();
    useUiStore.setState({ activeTab: 'preview', nestingEnabled: false });
    usePtypeStore.getState().reset();
    useSynthRunStore.setState({ token: 0, seed: 0, note: '', origin: undefined });
    useEditStore.getState().invalidate();
    useStrategyStore.getState().reset();
    useExtremeStore.getState().reset();
    useControlPanelStore.getState().closeModal();
  });
  afterEach(() => {
    useStrategyStore.getState().reset();
    useExtremeStore.getState().reset();
    useControlPanelStore.getState().closeModal();
  });

  /** 槽夹具（与后端 US-001 __main__ 夹具同构）。 */
  function makePending(mode: 'se' | 'race' | 'extreme' = 'race'): StatePendingStrategyResult {
    const r = makeDoneResult(mode);
    return { mode, best: r.best, summary: r.summary };
  }

  it("mode='race' → 策略族写回弹窗结果态逐字段 + openModal('strategy_run')；极限族不动", () => {
    applyRestorePayload(makeRestore({ pending_strategy_result: makePending('race') }));

    const s = useStrategyStore.getState();
    expect(s.phase).toBe('done');
    expect(s.status).toBeNull();
    expect(s.resultApplied).toBe(false);
    expect(s.errorMessage).toBeNull();
    expect(s.lastStart).toBeNull();
    const r = s.result!;
    expect(r.state).toBe('done');
    expect(r.mode).toBe('race');
    expect(r.run_dir).toBeNull();
    // manifest = 恢复端重算值透传（res.manifest 同源单份几何）
    expect(r.manifest).toEqual({ gate_mm: 1750, total_area_mm2: 500000, n_eroded: 2, pieces: [] });
    expect(r.best.seed).toBe(7);
    expect(r.best.placed_items.map((it) => it.id)).toEqual(['g01_30', 'g03_30']);
    expect(r.summary.race!.kept_seeds).toEqual([7]);
    // 弹窗自动打开（结果态 = phase done + result 在场，Modal 直接渲染结果面板）
    expect(useControlPanelStore.getState().modal).toBe('strategy_run');
    // 对方族不受扰（恢复只路由归属族）
    expect(useExtremeStore.getState().phase).toBe('idle');
    expect(useExtremeStore.getState().result).toBeNull();
  });

  it("mode='extreme' → 极限族写回 + openModal('extreme_run')；策略族不动", () => {
    applyRestorePayload(makeRestore({ pending_strategy_result: makePending('extreme') }));
    const s = useExtremeStore.getState();
    expect(s.phase).toBe('done');
    expect(s.result!.mode).toBe('extreme');
    expect(s.result!.manifest.gate_mm).toBe(1750);
    expect(useControlPanelStore.getState().modal).toBe('extreme_run');
    expect(useStrategyStore.getState().phase).toBe('idle');
    expect(useStrategyStore.getState().result).toBeNull();
  });

  it("mode='se' → 策略族（se/race 同族同路由）", () => {
    applyRestorePayload(makeRestore({ pending_strategy_result: makePending('se') }));
    expect(useStrategyStore.getState().result!.mode).toBe('se');
    expect(useControlPanelStore.getState().modal).toBe('strategy_run');
  });

  it('run 块缺席 + 槽在场 → 也切超排 Tab（2026-09-14：弹窗 Portal 到 body 不随 Tab 隐藏，不切页则悬浮在上传预览页上）', () => {
    applyRestorePayload(makeRestore({
      run: null, final: null, placed: null,
      pending_strategy_result: makePending('race'),
    }));
    expect(runRegistry.list()).toHaveLength(0);              // 无 run 合成（画布空置）
    expect(useControlPanelStore.getState().modal).toBe('strategy_run');
    expect(useUiStore.getState().nestingEnabled).toBe(true); // 显式解锁（setTab 前置）
    expect(useUiStore.getState().activeTab).toBe('nesting'); // 弹窗落在超排工作台上
  });

  it('槽缺席 → 两族 store 保持 idle、弹窗不开（旧文件零迁移）', () => {
    applyRestorePayload(makeRestore()); // pending_strategy_result: null
    expect(useStrategyStore.getState().phase).toBe('idle');
    expect(useExtremeStore.getState().phase).toBe('idle');
    expect(useControlPanelStore.getState().modal).toBeNull();
  });

  it('恢复写回态 refresh 不降级（idle 守卫端到端闭环：新 sid 后端槽空）', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify({ state: 'idle' }), { status: 200 })),
    );
    try {
      applyRestorePayload(makeRestore({ pending_strategy_result: makePending('race') }));
      await useStrategyStore.getState().refresh(); // 弹窗打开/挂载即 refresh → idle
      expect(useStrategyStore.getState().phase).toBe('done'); // 守卫生效
      expect(useStrategyStore.getState().result).not.toBeNull();
    } finally {
      spy.mockRestore();
    }
  });
});

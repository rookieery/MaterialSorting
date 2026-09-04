// EditStore —— 编辑排料（排料结果手工微调）的编辑态 store（PRD prd-edit-nesting-layout US-001）。
//
// 职责：open 快照不可变基线 → working 草稿（下标寻址，与 placed_items 保序）→
// save 原地写回 RunRecord.lastFrame（布局 + 料长 + 密度族同真相源重算）/ reset 恢复基线 /
// invalidate 清态（重解 / 策略应用时挂点，US-004）。
//
// 关键口径（PRD FR-8 / 技术考虑）：
//   - **多副本寻址**：working 下标 = placed_items 数组下标（同 pid 第 k 次出现 = 第 k 副本，
//     与 NestSVG「出现序」副本池同语义）；save 原地保序写回 ⇒ 副本映射稳定。
//   - **料长双向伸缩**：width = ceil(全布局包络 maxX)（下限 1mm）—— 拖片右移超界扩长 /
//     左移腾空尾部缩短；density 族同口径重算（real 口径 total_area/(width×gate)），
//     computeLayoutStats 单一真相源（弹窗顶部实时显示与保存同公式）。
//   - **density_sparrow 不动**：solver erode 参考值与编辑无关。
//   - **陈旧 run 防御**：save/reset 校验 run 仍在 runRegistry.list()（重解 clear() 后
//     旧引用拒绝写回）；弹窗打开期间 overlay 阻断主界面，registry 无人写，下标安全。
//   - 编辑态纯前端内存，刷新 / 切会话自然消失（不持久化、不落盘）。

import { create } from 'zustand';
import { transformPolygon } from '../lib/editGeometry';
import type { Pt, PlacedItem } from '../types/piece';
import type { ManifestMsg } from '../types/ws';
import { runRegistry, type RunRecord } from './runRegistry';
import { useAppStore } from './appStore';

/** open 时刻的不可变基线（reset 恢复全套的唯一真相源；深拷贝与 run 解耦）。 */
export interface EditBaseline {
  /** lastFrame.placed_items 深拷贝（算法原始布局）。 */
  placedItems: PlacedItem[];
  /** lastFrame.index（快照帧号，信息记录）。 */
  frameIndex: number;
  /** lastFrame.width_mm（算法原始料长）。 */
  widthMm: number;
  /** lastFrame.density（算法原始密度，real 口径）。 */
  density: number;
  /** run.finalDensity（算法原始终局密度）。 */
  finalDensity: number;
  /** run.viewBoxMaxW（算法原始画布宽锚）。 */
  viewBoxMaxW: number;
}

/** 全布局统计（同一真相源：弹窗顶部实时显示与 save/reset 写回共用）。 */
export interface LayoutStats {
  /** 全布局包络 maxX 向上取整（下限 1mm；双向伸缩）。 */
  widthMm: number;
  /** real 口径利用率 = manifest.total_area_mm2 / (widthMm × gate_mm)。 */
  density: number;
}

/**
 * 全布局统计纯函数（US-002 弹窗状态条 / US-003 实时刷新 / save 写回共用，单一真相源）。
 *
 * width = ceil(全部 placed 片世界多边形 bbox 的 maxX 最大值)，下限 1mm（编辑不删片，
 * 布局恒非空；防御性下限防 0 除）；density = total_area_mm2/(width×gate_mm)（real 口径，
 * 与后端 frame.density 同公式 —— total_area 为常量 Σdemand 原面积）。
 *
 * ceil 前 ε=1e-9 抵 float 噪声：90° 旋转的贴边片 x' = x·cos(π/2)+tx 会产生
 * ~3e-14 级正噪声（sub-nm），裸 ceil 会把整数贴边 maxX 无辜 +1mm（未编辑即扩长）。
 */
export function computeLayoutStats(
  working: readonly PlacedItem[],
  manifest: ManifestMsg,
): LayoutStats {
  const byId = new Map<string, (typeof manifest.pieces)[number]>();
  for (const p of manifest.pieces) byId.set(p.id, p);
  let maxX = 0;
  for (const it of working) {
    const p = byId.get(it.id);
    if (!p) continue;
    const world = transformPolygon(p.polygon, it.rotation, it.translation);
    for (const [x] of world) {
      if (x > maxX) maxX = x;
    }
  }
  const widthMm = Math.max(1, Math.ceil(maxX - 1e-9));
  const density = manifest.total_area_mm2 / (widthMm * manifest.gate_mm);
  return { widthMm, density };
}

/** PlacedItem 深拷贝（translation 是数组引用，必须逐项拷断与 lastFrame/baseline 的耦合）。 */
function deepCopyItems(items: readonly PlacedItem[]): PlacedItem[] {
  return items.map((it) => ({
    id: it.id,
    rotation: it.rotation,
    translation: [it.translation[0], it.translation[1]] as Pt,
  }));
}

/** 把布局 + 统计写入 run.lastFrame / run（save 与 reset 共用的落笔点；原地保序）。 */
function applyToRun(
  run: RunRecord,
  items: readonly PlacedItem[],
  widthMm: number,
  density: number,
  finalDensity: number,
  viewBoxMaxW: number,
): void {
  const f = run.lastFrame;
  if (!f) return;
  // 原地保序写回：数组身份不变（frames[] 内同一 FrameMsg 引用一致），按下标覆写 +
  // length 对齐（防御 working 比原 placed_items 短的病态输入）。
  for (let i = 0; i < items.length; i++) {
    f.placed_items[i] = {
      id: items[i].id,
      rotation: items[i].rotation,
      translation: [items[i].translation[0], items[i].translation[1]] as Pt,
    };
  }
  f.placed_items.length = items.length;
  f.width_mm = widthMm;
  f.density = density;
  run.finalDensity = finalDensity;
  run.viewBoxMaxW = viewBoxMaxW;
}

export interface EditState {
  /** 编辑目标 run（open 时刻引用；save/reset 前校验仍在 registry）。 */
  run: RunRecord | null;
  /** open 快照不可变基线（null = 未打开）。 */
  baseline: EditBaseline | null;
  /** 工作草稿（下标 = placed_items 数组下标；US-003 拖动 / 旋转经 setWorkingItem 更新）。 */
  working: PlacedItem[];
  /** 已保存过编辑（run.lastFrame 相对算法基线已被改写；重置按钮激活口径，US-004）。 */
  savedDirty: boolean;
  /**
   * 打开编辑：快照不可变基线全套 + working 深拷贝草稿。
   * @returns false = run 无 lastFrame（无可编辑布局），态保持清空。
   */
  open: (run: RunRecord) => boolean;
  /** 更新 working 下标项（US-003 拖动 / 旋转消费；越界 / 未打开防御 no-op）。 */
  setWorkingItem: (index: number, patch: { rotation?: number; translation?: Pt }) => void;
  /**
   * 保存：placed_items 原地保序写回 + width_mm / density / finalDensity / viewBoxMaxW
   * 按 computeLayoutStats 重算 + bumpRenderTick + savedDirty=true。
   * @returns false = 未打开 / 陈旧 run（已 clear 出 registry）/ lastFrame 缺失，拒绝写回。
   */
  save: () => boolean;
  /**
   * 重置：恢复基线全套（placed_items + width_mm + density / finalDensity + viewBoxMaxW）
   * + working 回基线 + savedDirty=false + bumpRenderTick。
   * @returns false 同 save 防御口径。
   */
  reset: () => boolean;
  /** 清态（重解 start / 应用策略结果挂点，US-004；幂等）。 */
  invalidate: () => void;
}

export const useEditStore = create<EditState>((set, get) => ({
  run: null,
  baseline: null,
  working: [],
  savedDirty: false,

  open: (run) => {
    const f = run.lastFrame;
    if (!f) {
      set({ run: null, baseline: null, working: [], savedDirty: false });
      return false;
    }
    set({
      run,
      baseline: {
        placedItems: deepCopyItems(f.placed_items),
        frameIndex: f.index,
        widthMm: f.width_mm,
        density: f.density,
        finalDensity: run.finalDensity,
        viewBoxMaxW: run.viewBoxMaxW,
      },
      working: deepCopyItems(f.placed_items),
      savedDirty: false,
    });
    return true;
  },

  setWorkingItem: (index, patch) => {
    const { working } = get();
    if (index < 0 || index >= working.length) return;
    const next = working.slice();
    const cur = next[index];
    next[index] = {
      id: cur.id,
      rotation: patch.rotation !== undefined ? patch.rotation : cur.rotation,
      translation:
        patch.translation !== undefined
          ? [patch.translation[0], patch.translation[1]]
          : [cur.translation[0], cur.translation[1]],
    };
    set({ working: next });
  },

  save: () => {
    const { run, working } = get();
    if (!run || !run.lastFrame || !run.manifest) return false;
    if (!runRegistry.list().includes(run)) return false;
    const stats = computeLayoutStats(working, run.manifest);
    applyToRun(run, working, stats.widthMm, stats.density, stats.density, stats.widthMm);
    set({ savedDirty: true });
    useAppStore.getState().bumpRenderTick();
    return true;
  },

  reset: () => {
    const { run, baseline } = get();
    if (!run || !baseline || !run.lastFrame) return false;
    if (!runRegistry.list().includes(run)) return false;
    applyToRun(
      run,
      baseline.placedItems,
      baseline.widthMm,
      baseline.density,
      baseline.finalDensity,
      baseline.viewBoxMaxW,
    );
    set({ working: deepCopyItems(baseline.placedItems), savedDirty: false });
    useAppStore.getState().bumpRenderTick();
    return true;
  },

  invalidate: () => {
    set({ run: null, baseline: null, working: [], savedDirty: false });
  },
}));

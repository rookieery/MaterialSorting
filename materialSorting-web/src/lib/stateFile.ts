// 状态文件前端侧逻辑（状态文件 US-003）：保存载荷组装。
//
// buildSavePayload = POST /api/state-save 请求体单一实现（useExport.saveState 消费）：
//   - form ← formStore 当前值（FormState 全量原样入文件）；
//   - quantities ← qtyStore **全量扁平化**（不过滤 form.sizes）：{label:{sizeKey:N}}
//     原生形态。与 WS start 载荷（serializeQuantities 按码选过滤）有意分歧 ——
//     状态文件要跨机完整还原数量矩阵（未勾选码的数量也随文件走），后端守恒
//     校验自按 form.sizes 过滤 demand，多带的 sizeKey 无害；
//   - run ← bestRun() 仅 done 态（无 lastFrame / 未结束 → 整键缺席 = 纯配置
//     档；经导出入口保存被 ExportButtons hasLastFrame 门槛天然拦截，端点层仍
//     容忍无 run 为未来「会话存档」入口留契约）。final 摘要取 RunRecord 当前
//     值（编辑保存后 applyToRun 已同口径更新 density/width_mm）；
//     placed = lastFrame.placed_items 深拷贝原序（同 pid 多副本 = 数组多条），
//     mirror 按 omit-when-false 只在 true 时带键（editStore.deepCopyItems 同
//     口径）；origin 缺席（WS 普通求解）→ 不写 provenance 键，在场 → 映射
//     {kind, config?}。
//
// applyRestorePayload（恢复编排）属 US-004 —— 本文件暂只承载保存侧。

import { useFormStore } from '../store/formStore';
import { useQtyStore } from '../store/qtyStore';
import { runRegistry, type RunRecord } from '../store/runRegistry';
import type { PieceQuantityMap } from '../types/qty';
import type { PlacedItem } from '../types/piece';
import type { RunOrigin, RunProvenance, StateSavePayload, StateSaveRun } from '../types/stateFile';

/**
 * qtyStore 数量矩阵 → {label:{sizeKey:N}} 扁平形态（全量，不过滤码选）。
 * 空矩阵 → null（后端「quantities=None → demand 全 1」旧语义口径）。
 * 数量 0 保留（「显式 0 = 排除」语义可追溯，后端 build_pid_meta 见 0 跳过）。
 */
function flattenQuantities(
  map: PieceQuantityMap,
): Record<string, Record<string, number>> | null {
  const out: Record<string, Record<string, number>> = {};
  for (const label of Object.keys(map)) {
    const q = map[label];
    if (!q) continue;
    const flat = { ...q.perSize };
    if (Object.keys(flat).length > 0) out[label] = flat;
  }
  return Object.keys(out).length > 0 ? out : null;
}

/**
 * PlacedItem 深拷贝（translation 是数组引用，必须逐项拷断与 lastFrame 的耦合；
 * 保序 = placed_items 数组原序）。mirror omit-when-false 透传：`mirror === true`
 * 才带键 —— 与 editStore.deepCopyItems 同口径（键集与 wire 契约一致）。
 */
function deepCopyPlaced(items: readonly PlacedItem[]): PlacedItem[] {
  return items.map((it) => ({
    id: it.id,
    rotation: it.rotation,
    translation: [it.translation[0], it.translation[1]] as PlacedItem['translation'],
    ...(it.mirror === true ? { mirror: true } : {}),
  }));
}

/** origin → run.provenance：缺席（WS 普通求解，undefined = 'solve'）→ 不写键。 */
function provenanceOf(origin: RunOrigin | undefined): RunProvenance | undefined {
  if (!origin) return undefined;
  return {
    kind: origin.kind,
    ...(origin.config !== undefined ? { config: origin.config } : {}),
  };
}

/**
 * 组装保存载荷（{form, quantities, run?}）：run 仅 done 态 bestRun 入块。
 * 深拷贝保证：payload 与 stores 当前态解耦（发送期间用户编辑不影响已序列化体）。
 */
export function buildSavePayload(): StateSavePayload {
  const form = useFormStore.getState().form;
  const quantities = flattenQuantities(useQtyStore.getState().quantities);
  const run = buildRunBlock(runRegistry.bestRun());
  return { form, quantities, ...(run ? { run } : {}) };
}

/** bestRun → run 块（无 lastFrame / 未结束 → undefined = 整块缺席）。 */
function buildRunBlock(run: RunRecord | null): StateSaveRun | undefined {
  if (!run || !run.lastFrame || !run.done) return undefined;
  const provenance = provenanceOf(run.origin);
  return {
    seed: run.seed,
    ...(provenance ? { provenance } : {}),
    final: {
      density: run.finalDensity,
      density_sparrow: run.finalDensitySparrow,
      width_mm: run.lastFrame.width_mm,
      elapsed: run.lastFrame.elapsed,
      n_frames: run.frames.length,
      n_eroded: run.manifest?.n_eroded ?? 0,
    },
    placed: deepCopyPlaced(run.lastFrame.placed_items),
  };
}

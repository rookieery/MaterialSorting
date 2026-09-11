// 状态文件前端侧逻辑（状态文件 US-003 保存 / US-004 恢复编排）。
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
//     mirror 按 omit-when-false 只在 true 时带键（deepCopyPlaced 单一实现，
//     synthRunStore 导出共享）；origin 缺席（WS 普通求解）→ 不写 provenance 键，
//     在场 → 映射 {kind, config?}。
//
// applyRestorePayload（US-004）= POST /api/state-restore 成功响应的恢复编排单一
// 实现（useParseDxf .msn 分流成功路径消费）：uploadStore doc 就绪 → qtyStore 实值
// 水合 → formStore 水合（token=新 docId）→ ptypeStore 失效 → 有 run 块时切超排
// Tab + applySyntheticRun 合成（manifest 重算 + 单帧 final + provenance 写回）。
// 顺序细节见函数头注释 —— 两处 store 联动（PreviewPage 订阅 / ControlPanel docId
// effect）都在 setState 同步或 React 提交后触发，与本编排的写序收敛一致。

import { useFormStore } from '../store/formStore';
import { usePtypeStore } from '../store/ptypeStore';
import { useQtyStore } from '../store/qtyStore';
import { runRegistry, type RunRecord } from '../store/runRegistry';
import {
  applySyntheticRun,
  deepCopyPlaced,
} from '../store/synthRunStore';
import { computeLayoutStats } from '../store/editStore';
import { useUiStore } from '../store/uiStore';
import { useUploadStore } from '../store/uploadStore';
import type { PieceQuantityMap } from '../types/qty';
import type { PlacedItem } from '../types/piece';
import type {
  RunOrigin,
  RunProvenance,
  StateRestoreResponse,
  StateRunFinal,
  StateSavePayload,
  StateSaveRun,
} from '../types/stateFile';
import type { FrameMsg, ManifestMsg } from '../types/ws';

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
 * PlacedItem 深拷贝 = synthRunStore.deepCopyPlaced（US-004 起共享单一实现：
 * 保序 + translation 逐项拷断 + mirror omit-when-false，保存/合成/编辑三侧同口径）。
 */
// （deepCopyPlaced 经 import 具名引入，见文件头 import 块。）

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

// ============================================================
// 恢复编排（US-004）—— POST /api/state-restore 成功响应 → 五 store 落笔 + run 合成
// ============================================================

/**
 * 手改文件容错兜底：run.final 缺席（后端校验 final 键可省）时从恢复布局现算摘要
 * —— computeLayoutStats 与 editStore.save 同一真相源（物理毛版 raw 包络 + real
 * 口径密度），density_sparrow/elapsed 客户端不可知 → 0（展示级参考值）。
 */
function finalizeFromLayout(
  placed: readonly PlacedItem[],
  manifest: ManifestMsg,
): StateRunFinal {
  const stats = computeLayoutStats(placed, manifest);
  return {
    density: stats.density,
    density_sparrow: 0,
    width_mm: stats.widthMm,
    elapsed: 0,
    n_frames: 1,
    n_eroded: manifest.n_eroded,
  };
}

/**
 * 恢复编排（单一实现，useParseDxf .msn 分流成功路径消费）：
 *
 *  1. uploadStore doc 就绪 —— parse 载荷即 ParsedDoc（doc_id = 恢复铸新 id，与
 *     顶层 res.doc_id 同源）；activeSize 同 .dxf 口径取最小码；commit 字段回 idle
 *     （恢复无「应用中」相位，旧会话摘要对新 doc 失效）。setState 同步触发
 *     PreviewPage 订阅：qty 默认物化（下步显式重放覆盖）+ nestingEnabled 解锁
 *     + strategyStore.lastStart 清空（旧 start 载荷对新 doc 非法，commit 同口径）。
 *  2. qtyStore —— hydrate（doc 全码全片默认 1 物化，与 PreviewPage 订阅同构：
 *     显式重放使编排不依赖组件挂载时序 / 订阅顺序）→ hydrateFlat（状态文件实值
 *     覆盖，null = 纯配置档保持默认 1）。
 *  3. formStore.hydrate(form, token=res.doc_id) —— ControlPanel useEffect([docId])
 *     在 React 提交后才跑 resetForDoc(新 docId)，届时 token 已匹配 → 水合表单保留
 *     （水合优先于 docId 变更重置；token 单射 + 恢复每次铸新 id 无假匹配面）。
 *  4. ptypeStore.invalidate() —— commit-done 同口径（后端 representatives 唯一
 *     变化点；弹窗开着则订阅 idle 无感刷新）。
 *  5. run 块在场 → 合成：manifest（恢复端 build_pid_meta 确定性重算 + type 判别键）
 *     + 单帧 phase='final'（placed 原序，深拷贝在 applySyntheticRun 内统一）+
 *     origin = run.provenance 透传（缺省 {kind:'solve'} —— 恢复的普通求解结果也
 *     回显来源小字）→ applySyntheticRun 共享落笔（清场/registry/信号）；随后
 *     setNestingEnabled(true) 显式先行（useCommitToNesting D1 闭环同款，不依赖
 *     PreviewPage 订阅时序）+ setTab('nesting') 展示布局。无 run（纯配置档）→
 *     不切 Tab（留在预览页核对数量矩阵，求解入口由用户主动进）。
 */
export function applyRestorePayload(res: StateRestoreResponse): void {
  // 1) uploadStore doc 就绪（status done —— UploadPanel done 态 / PreviewPage QtyMatrix 渲染）。
  const initialSize = res.parse.sizes.length > 0 ? res.parse.sizes[0].size : null;
  useUploadStore.setState({
    status: 'done',
    doc: res.parse,
    activeSize: initialSize,
    error: null,
    zoom: null,
    commitStatus: 'idle',
    commitError: null,
    commitSummary: null,
  });

  // 2) qtyStore：默认物化（幂等）→ 状态文件实值覆盖。
  const entries = res.parse.sizes.flatMap((s) =>
    s.pieces.map((p) => ({ label: p.label, size: s.size })),
  );
  useQtyStore.getState().hydrate(entries);
  useQtyStore.getState().hydrateFlat(res.quantities);

  // 3) formStore 水合（token = 恢复响应新 doc_id）。
  useFormStore.getState().hydrate(res.form, res.doc_id);

  // 4) ptypeStore 失效（commit-done 口径）。
  usePtypeStore.getState().invalidate();

  // 5) run 合成 + 切超排 Tab（有 run 块时）。
  const runBlock = res.run;
  if (runBlock && res.placed) {
    const manifest: ManifestMsg = { type: 'manifest', ...res.manifest };
    const fin = runBlock.final ?? finalizeFromLayout(res.placed, manifest);
    const frame: FrameMsg = {
      type: 'frame',
      index: 0,
      elapsed: fin.elapsed,
      phase: 'final',
      density: fin.density,
      density_sparrow: fin.density_sparrow,
      width_mm: fin.width_mm,
      placed_items: res.placed,
    };
    const origin: RunOrigin = runBlock.provenance ?? { kind: 'solve' };
    applySyntheticRun(
      manifest,
      frame,
      runBlock.seed,
      origin,
      `状态文件已恢复：seed ${runBlock.seed} · ${(fin.density * 100).toFixed(2)}%`,
    );
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
  }
}

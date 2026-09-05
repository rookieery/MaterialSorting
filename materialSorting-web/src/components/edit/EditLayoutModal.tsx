// EditLayoutModal —— 编辑排料大弹窗（US-002：全量渲染 + 缩放平移查看；
// 拖动/旋转在 EditCanvas 内叠加（US-003）；US-004 ✕ dirty 二次确认接线，保存路径
// editStore.save() 自 US-001 落地 —— placed 原地保序写回 + width/density 族同真相源
// 重算 + viewBoxMaxW 跟随 + bumpRenderTick，density_sparrow 恒不动）。
//
// edit-polish US-003（2026-09-05）：「智能微调」state 机在本组件（快照生命周期 =
// modal state）—— 按钮与对比卡渲染在 EditCanvas（工具区/右下卡栈），经 polish
// prop 受控下发（onModeChange 同款模式）。成功 → replaceWorking 写 working（**不
// 调用 save、不自动保存**，✕ 关窗即弃既有语义不变）；失败（网络/4xx）→ 错误文案
// 进卡、working 逐字段不变；一级撤销 = pre-polish working 快照（再次微调覆盖、
// 关闭/重置清空 —— 关窗即 Inner 整树卸载，快照自然清零）。
// edit-polish US-005（2026-09-05）：polishCompact 勾选态（对比卡内 checkbox，默认
// 不勾）→ 勾选后随下次微调请求发出 compact:true（引擎 pass ④ 压缩回收档）。
//
// 声明式受控 Portal（范本 ExportInfoModal）：外层订阅 controlPanelStore.modal ===
// 'edit_layout' 自显隐，Portal 到 document.body，Inner 带 key（关闭→重开重挂载 =
// open() 重新快照基线）。打开入口：主界面「编辑排料」区块（EditLayoutControls）。
//
// **有意偏离全站 ESC/遮罩关闭惯例**（controlPanelStore 注释同款口径）：编辑草稿不可
// 被误触丢弃 —— 不挂 ESC keydown listener、遮罩 mousedown 不调 close。唯一关闭路径：
//   1. 右上 ✕（US-004：dirty = working ≠ 已保存布局（itemsEqual，ε=1e-9 同口径）
//      → 自定义小确认层「放弃未保存的修改？」（EditConfirmLayer，与主面板重置
//      confirm 同组件复用）确认后弃稿关窗；非 dirty（未编辑 / 已保存）直接关）
//   2. 右下「保存当前布局」（editStore.save() 写回 + 关窗 —— 保存后 working 与
//      lastFrame 逐项相等 ⇒ ✕ 不再确认）
// PRD AC：单测 dispatch ESC keydown 与遮罩 mousedown 断言弹窗仍在。
//
// 结构：顶部状态条（料长 mm + 利用率 % + 相对基线 Δpt，computeLayoutStats 单一真相源
// —— 初值 = 基线即主视图利用率/料长，US-003 拖动起实时刷新）+ 右上 ✕ + 中心 EditCanvas
// + 右下仅「保存当前布局」单按钮（取消按钮已废弃）。全屏 overlay 阻断主界面（z-index
// 1250，ptype-preview 1200 与 band-zoom 1300 之间 —— 编辑弹窗盖住预览、让位放大镜）。
// 形态 select（完整版/毛板，即时切换可恢复）2026-09-05 自 footer 移入画布左上工具区
// （EditCanvas 渲染，state 仍在本组件、经 onModeChange 受控 —— ± 放缩按钮同日删除）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { computeLayoutStats, itemsEqual, useEditStore } from '../../store/editStore';
import { runRegistry } from '../../store/runRegistry';
import { EDIT_HOLD_INTERVAL_MS, refreshEditHold } from '../../lib/editHold';
import { buildPolishPayload, postEditPolish, type PolishReport } from '../../lib/editPolish';
import type { PlacedItem } from '../../types/piece';
import { EditCanvas, type EditViewMode } from './EditCanvas';
import { EditConfirmLayer } from './EditConfirmLayer';

export function EditLayoutModal(): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  if (modal !== 'edit_layout') return null;
  return <EditLayoutModalInner key="edit-layout-modal" />;
}

function EditLayoutModalInner(): JSX.Element {
  const closeModal = useControlPanelStore((s) => s.closeModal);
  const open = useEditStore((s) => s.open);
  const save = useEditStore((s) => s.save);
  const invalidate = useEditStore((s) => s.invalidate);
  const run = useEditStore((s) => s.run);
  const working = useEditStore((s) => s.working);
  const baseline = useEditStore((s) => s.baseline);
  const [mode, setMode] = useState<EditViewMode>('full');
  // ✕ dirty 二次确认层显隐（US-004）。
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  // ---- edit-polish US-003（2026-09-05）：智能微调 state 机 ----
  // busy = 请求在飞（按钮 loading 态禁重复点击）；report = 最近一次成功的前后对比
  // （对比卡数据源）；error = 最近一次失败文案（卡内显示）；prePolish = 一级撤销
  // 快照（成功落 working 前拷贝；再次微调覆盖、撤销/关窗清空）。
  // US-005：polishCompact = 压缩回收档勾选态（对比卡内 checkbox，默认不勾、
  // 勾选后随**下次**微调请求发出 compact:true；关窗 Inner 卸载自然回 false）。
  const [polishBusy, setPolishBusy] = useState(false);
  const [polishReport, setPolishReport] = useState<PolishReport | null>(null);
  const [polishError, setPolishError] = useState<string | null>(null);
  const [prePolish, setPrePolish] = useState<PlacedItem[] | null>(null);
  const [polishCompact, setPolishCompact] = useState(false);

  // mount 一次性快照基线（ExportInfoModal 先例：自 bestRun() 取目标 run）。
  // open 内部防御：run 无 lastFrame → 清态返回 false（弹窗显示空态）。
  useEffect(() => {
    const best = runRegistry.bestRun();
    if (!best) {
      invalidate();
      return;
    }
    open(best);
  }, [open, invalidate]);

  // 会话钉住心跳（2026-09-04）：编辑纯前端无任何请求，后端 10min 空闲过期会在
  // 长编辑中逐出会话 → 保存后导出 401 全丢。弹窗打开期间滚动续期 POST
  // /api/edit-hold（后端 2h 钉住 + 关窗后自然宽限，镜像高级运行语义；失败静默
  // 详见 lib/editHold.ts）。
  useEffect(() => {
    void refreshEditHold();
    const id = window.setInterval(() => void refreshEditHold(), EDIT_HOLD_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  // 状态条：computeLayoutStats 单一真相源（与 save/reset 写回同公式 = ceil(包络) 口径，
  // US-003 起料长 = ceil(当前包络 maxX) 实时刷新）。注意 solver 原始 width_mm 可为小数
  // （如 6148.38）—— ceil 口径会比主视图 NestLabel 高 0.01pt 级（保存后主视图同步为
  // ceil 值即一致；这是「料长双向伸缩」设计的固有取整，非 bug）。
  // Δpt 基线 = computeLayoutStats(baseline.placedItems)（同 ceil 口径），不是裸
  // baseline.density —— 否则未编辑时 Δ 就带 −0.01pt 取整伪影；Δ 只度量「编辑的效果」，
  // 初值恒 +0.00（working = 基线深拷贝 ⇒ 同 placements 同 stats）。
  const manifest = run?.manifest ?? null;
  const stats = manifest && working.length > 0 ? computeLayoutStats(working, manifest) : null;
  const baselineStats =
    manifest && baseline && baseline.placedItems.length > 0
      ? computeLayoutStats(baseline.placedItems, manifest)
      : null;
  const deltaPt =
    stats && baselineStats ? (stats.density - baselineStats.density) * 100 : null;
  const deltaText =
    deltaPt === null ? '—' : `${deltaPt >= 0 ? '+' : ''}${deltaPt.toFixed(2)}pt`;

  /** 右下唯一保存路径：写回 run（US-002 布局未动 ⇒ 幂等同值写回）+ 关窗。 */
  function handleSave(): void {
    void save();
    closeModal();
  }

  /**
   * 智能微调（edit-polish US-003）：POST /api/edit-polish → 成功把返回 placed 经
   * replaceWorking 写 working（pid 逐位守恒校验失败 = 形态异常按失败处理，草稿
   * 不动）+ 快照 pre-polish（再次微调覆盖）；不调用 save（✕ 关窗即弃语义不变）。
   * 失败（网络/4xx/形态异常）→ 错误文案进卡、working 逐字段不变（401 session code
   * 由 apiFetch 拦截走既有全局阻断弹窗，正确行为）。
   */
  async function handlePolish(): Promise<void> {
    if (polishBusy || !manifest || working.length === 0) return;
    const run = useEditStore.getState().run;
    const payload = buildPolishPayload(
      useEditStore.getState().working,
      run,
      polishCompact,
    );
    if (!payload) return;
    setPolishBusy(true);
    setPolishError(null);
    try {
      const { placed, report } = await postEditPolish(payload);
      const before = useEditStore.getState().working;
      if (!useEditStore.getState().replaceWorking(placed)) {
        throw new Error('微调失败：结果与当前布局条数/裁片不一致，已忽略');
      }
      // 快照仅在校验通过、working 已替换后落（失败路径不留孤儿快照 —— 撤销按钮
      // 不出现；快照 = 点击微调前的 working，手动拖动后的中间态一并入照）。
      setPrePolish(
        before.map((it) => ({
          id: it.id,
          rotation: it.rotation,
          translation: [it.translation[0], it.translation[1]] as PlacedItem['translation'],
        })),
      );
      setPolishReport(report);
    } catch (e) {
      // postEditPolish 抛的错已带「微调失败」前缀直显；其余（fetch 网络层 TypeError
      // 如 "Failed to fetch" 等浏览器英文文案）统一补前缀，卡内文案可读。
      const raw = e instanceof Error ? e.message : String(e);
      setPolishError(raw.startsWith('微调失败') ? raw : `微调失败：${raw}`);
    } finally {
      setPolishBusy(false);
    }
  }

  /** 一级撤销：恢复 pre-polish 快照 working + 清卡（报告/错误/快照一并清空）。 */
  function handleUndoPolish(): void {
    if (!prePolish) return;
    useEditStore.getState().replaceWorking(prePolish);
    setPrePolish(null);
    setPolishReport(null);
    setPolishError(null);
  }

  // US-004 ✕ 关闭口径：dirty = working ≠ 已保存布局（run.lastFrame.placed_items；
  // save 写回是精确拷贝 ⇒ 保存后必相等，open 快照深拷贝 ⇒ 未编辑恒非 dirty）。
  // dirty → 弹 EditConfirmLayer「放弃未保存的修改？」确认后弃稿关窗（working 草稿
  // 不写回，下次 open 重新快照 lastFrame）；非 dirty 直接关。
  const savedItems = run?.lastFrame?.placed_items ?? null;
  const dirty = !!(run && savedItems && !itemsEqual(working, savedItems));

  function handleClose(): void {
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }
    closeModal();
  }

  return createPortal(
    <div className="edit-layout-overlay" data-testid="edit-layout-overlay">
      <div
        className="edit-layout-modal"
        role="dialog"
        aria-modal="true"
        aria-label="编辑排料布局"
      >
        <div className="edit-layout-head">
          <div className="edit-layout-stats">
            <span className="edit-layout-stat" data-testid="edit-layout-width">
              料长 {stats ? `${stats.widthMm} mm` : '—'}
            </span>
            <span className="edit-layout-stat" data-testid="edit-layout-density">
              利用率 {stats ? `${(stats.density * 100).toFixed(2)}%` : '—'}
            </span>
            <span className="edit-layout-stat" data-testid="edit-layout-delta">
              Δ {deltaText}
            </span>
          </div>
          <button
            type="button"
            className="edit-layout-close"
            aria-label="关闭"
            title="关闭"
            onClick={handleClose}
            data-testid="edit-layout-close"
          >
            ✕
          </button>
        </div>

        {run && manifest ? (
          <div className="edit-layout-body">
            <EditCanvas
              mode={mode}
              onModeChange={setMode}
              polish={{
                busy: polishBusy,
                error: polishError,
                report: polishReport,
                canUndo: prePolish !== null,
                compact: polishCompact,
                onPolish: () => void handlePolish(),
                onUndo: handleUndoPolish,
                onCompactChange: setPolishCompact,
              }}
            />
          </div>
        ) : (
          <div className="edit-layout-body edit-layout-empty" data-testid="edit-layout-empty">
            暂无可编辑的排料结果（请先完成一次求解）
          </div>
        )}

        {/* footer 仅存保存按钮（形态 select 2026-09-05 移入画布左上工具区）。 */}
        <div className="edit-layout-foot">
          <button
            type="button"
            className="edit-layout-save"
            onClick={handleSave}
            data-testid="edit-layout-save"
          >
            保存当前布局
          </button>
        </div>
      </div>
      {/* ✕ dirty 确认层（Portal 到 body，z-index 1350 盖住编辑弹窗自身） */}
      {confirmDiscard && (
        <EditConfirmLayer
          message="放弃未保存的修改？"
          onConfirm={() => {
            setConfirmDiscard(false);
            closeModal();
          }}
          onCancel={() => setConfirmDiscard(false)}
        />
      )}
    </div>,
    document.body,
  );
}

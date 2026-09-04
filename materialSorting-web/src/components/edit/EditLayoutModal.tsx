// EditLayoutModal —— 编辑排料大弹窗（US-002：全量渲染 + 缩放平移查看；
// 拖动/旋转在 EditCanvas 内叠加（US-003）；US-004 ✕ dirty 二次确认接线，保存路径
// editStore.save() 自 US-001 落地 —— placed 原地保序写回 + width/density 族同真相源
// 重算 + viewBoxMaxW 跟随 + bumpRenderTick，density_sparrow 恒不动）。
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
// + 左下形态 select（完整版/毛板，即时切换可恢复）+ 右下仅「保存当前布局」单按钮
// （取消按钮已废弃）。全屏 overlay 阻断主界面（z-index 1250，ptype-preview 1200 与
// band-zoom 1300 之间 —— 编辑弹窗盖住预览、让位放大镜）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { computeLayoutStats, itemsEqual, useEditStore } from '../../store/editStore';
import { runRegistry } from '../../store/runRegistry';
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
            <EditCanvas mode={mode} />
          </div>
        ) : (
          <div className="edit-layout-body edit-layout-empty" data-testid="edit-layout-empty">
            暂无可编辑的排料结果（请先完成一次求解）
          </div>
        )}

        <div className="edit-layout-foot">
          <label className="edit-layout-mode">
            形态
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as EditViewMode)}
              data-testid="edit-layout-mode"
            >
              <option value="full">完整版</option>
              <option value="rough">毛板</option>
            </select>
          </label>
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

// PerTypeOverrides —— 高级「每裁片覆盖」入口（US-018 改造为按钮触发器；裁片编号化重构
// US-003 起覆盖键 = 裁片 g 码；2026-08-18 回退 US-004 矩阵化后维持单级 {g 码: {d, tol}}）。
//
// 更早旧版：`<details>` 折叠面板，内嵌 10 行 d/tol 输入（US-018 已删）。
// US-018：改为 `<button class="per-type-btn">` 触发 → PerTypeOverridesModal 弹窗 table。
//
// 保留 values/onChange 契约（ControlPanel 仍 `<PerTypeOverrides values={form.per_type}
// onChange={(per_type) => patch({ per_type })} />`）；本组件作为入口把 values/onChange
// 透传给 PerTypeOverridesModal（在按钮旁边挂载）。Modal 草稿 + 确定时调 onChange 回写。
//
// US-013：透传扩展 —— band/onBandChange（布局设置分区 form.band_* 草稿/回写）+
// buildStartContext（预演 POST /api/band/preview 的求解上下文构造器）。
//
// 关键不变量（AC#6）：与 ControlPanel 的 values/onChange 契约不变；
// PerTypeOverridesModal 订阅 controlPanelStore.modal 自显隐（声明式受控 Portal）。
//
// 不变量：PtypePreviewModal 叠在 PerTypeOverridesModal 之上（z-index 更高）；
// PerTypeOverridesModal 内部表头缩略图点击触发 openPreviewLabel(label)。

import type { JSX } from 'react';
import { useControlPanelStore } from '../../store/controlPanelStore';
import type { PerTypeFormValue, StartContext } from '../../lib/params';
import { PerTypeOverridesModal, type BandFormValue } from './PerTypeOverridesModal';
import { PtypePreviewModal } from './PtypePreviewModal';

export interface PerTypeOverridesProps {
  /** 每裁片（g 码）的 d/tol 输入字符串（key = 当前母版 g 码并集，动态）。 */
  values: Record<string, PerTypeFormValue>;
  /** Modal 确定时回写（label + 'd' | 'tol' + 新字符串）。 */
  onChange: (next: Record<string, PerTypeFormValue>) => void;
  /** US-013 布局设置初值（form.band_*：enabled/label/ack）。 */
  band: BandFormValue;
  /** US-013 确定时回写 form.band_*。 */
  onBandChange: (next: BandFormValue) => void;
  /** US-013 预演 /api/band/preview 的求解上下文构造器。 */
  buildStartContext: () => StartContext;
  /** US-027 求解中冻结高级配置入口（与 StartButton disabled 同套机制）。 */
  disabled?: boolean;
}

export function PerTypeOverrides({
  values,
  onChange,
  band,
  onBandChange,
  buildStartContext,
  disabled = false,
}: PerTypeOverridesProps): JSX.Element {
  const openModal = useControlPanelStore((s) => s.openModal);

  return (
    <div className="per-type-wrapper">
      <button
        type="button"
        className="per-type-btn"
        disabled={disabled}
        onClick={() => openModal('per_type')}
        data-testid="per-type-btn"
      >
        高级配置：每裁片覆盖
      </button>
      {/* 模态单例：订阅 controlPanelStore 自显隐；Portal 到 document.body */}
      <PerTypeOverridesModal
        values={values}
        onChange={onChange}
        band={band}
        onBandChange={onBandChange}
        buildStartContext={buildStartContext}
      />
      <PtypePreviewModal />
    </div>
  );
}

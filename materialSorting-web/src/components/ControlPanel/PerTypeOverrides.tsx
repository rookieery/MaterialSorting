// PerTypeOverrides —— 高级「每片型覆盖」入口（US-018 改造为按钮触发器）。
//
// 旧版（US-004）：`<details>` 折叠面板，内嵌 10 行 d/tol 输入。
// US-018：改为 `<button class="per-type-btn">` 触发 → PerTypeOverridesModal 弹窗 table。
//
// 保留 values/onChange 契约（ControlPanel 仍 `<PerTypeOverrides values={form.per_type}
// onChange={(per_type) => patch({ per_type })} />`）；本组件作为入口把 values/onChange
// 透传给 PerTypeOverridesModal（在按钮旁边挂载）。Modal 草稿 + 确定时调 onChange 回写。
//
// 关键不变量（AC#6）：与 ControlPanel 的 values/onChange 契约不变，ControlPanel 无需改动；
// PerTypeOverridesModal 订阅 controlPanelStore.modal 自显隐（声明式受控 Portal）。
//
// 不变量：PtypePreviewModal 叠在 PerTypeOverridesModal 之上（z-index 更高）；
// PerTypeOverridesModal 内部表头缩略图点击触发 openPreviewPtype(ptype)。

import type { JSX } from 'react';
import { useControlPanelStore } from '../../store/controlPanelStore';
import type { PerTypeFormValue } from '../../lib/params';
import { PerTypeOverridesModal } from './PerTypeOverridesModal';
import { PtypePreviewModal } from './PtypePreviewModal';

export interface PerTypeOverridesProps {
  /** 每片型的 d/tol 输入字符串（key 全量 = V03_PTYPES）。 */
  values: Record<string, PerTypeFormValue>;
  /** Modal 确定时回写（key + 'd' | 'tol' + 新字符串）。 */
  onChange: (next: Record<string, PerTypeFormValue>) => void;
}

export function PerTypeOverrides({ values, onChange }: PerTypeOverridesProps): JSX.Element {
  const openModal = useControlPanelStore((s) => s.openModal);

  return (
    <div className="per-type-wrapper">
      <button
        type="button"
        className="per-type-btn"
        onClick={() => openModal('per_type')}
        data-testid="per-type-btn"
      >
        高级配置：每片型覆盖
      </button>
      {/* 模态单例：订阅 controlPanelStore 自显隐；Portal 到 document.body */}
      <PerTypeOverridesModal values={values} onChange={onChange} />
      <PtypePreviewModal />
    </div>
  );
}

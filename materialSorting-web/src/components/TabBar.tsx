// TabBar —— 顶部 Tab 切换（US-001 AC#1）+ 超排 Tab 解锁闸（US-015）。
//
// 渲染两个 Tab（上传预览 / 超排），点击切换 uiStore.activeTab；当前激活项加 `.active`
// class 高亮（与 ControlPanel 视觉同色系：暗背景 #26282e + 绿色 #2ea06c 强调，见 style.css）。
//
// 超排 Tab 解锁闸（US-015）：
//   - nestingEnabled===false 时「超排」button 加 `disabled` 属性 + `.disabled` class；
//   - disabled 时 onClick 运行时再判一次（双重防御：native disabled 兜底 a11y / 键盘 tab 序列，
//     运行时判 uiStore.setTab 内的 guard 兜底 JS 旁路调用）；
//   - aria-disabled 同步给屏幕阅读器（与 aria-pressed 同 a11y 口径）。
//   - 上传预览 Tab 永远可点（用户随时可回上传预览页）。
//
// 设计原则（CLAUDE.md / AGENTS.md）：
//   1. 不引入 CSS 框架，沿用 style.css 命令式 className 约定（`.tabbar / .tab / .tab.active / .tab.disabled`）。
//   2. Tab 切换由 uiStore 单字段驱动；App 订阅 activeTab 切 .page.hidden，不卸载组件
//      （AC#4 display:none 保 DOM，求解/WS/seek 全保留）。
//   3. 用原生 <button> 保证可键盘 focus / Enter 触发，符合 a11y 最低要求。

import type { ReactElement } from 'react';
import { useUiStore, type TabId } from '../store/uiStore';

/**
 * Tab 元信息（顺序即渲染顺序：上传预览在前、超排在后）。
 * 注意：默认 activeTab=preview（见 uiStore），首页落「上传预览」——首位即默认入口。
 */
const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: 'preview', label: '上传预览' },
  { id: 'nesting', label: '超排' },
];

export function TabBar(): ReactElement {
  const activeTab = useUiStore((s) => s.activeTab);
  const setTab = useUiStore((s) => s.setTab);
  const nestingEnabled = useUiStore((s) => s.nestingEnabled);

  return (
    <nav className="tabbar" aria-label="页面切换">
      {TABS.map((t) => {
        const isActive = t.id === activeTab;
        // 超排 Tab 在 nestingEnabled===false 时置灰不可点（US-015）；上传预览永远可点。
        const disabled = t.id === 'nesting' && !nestingEnabled;
        return (
          <button
            key={t.id}
            type="button"
            className={`tab${isActive ? ' active' : ''}${disabled ? ' disabled' : ''}`}
            aria-pressed={isActive}
            aria-disabled={disabled}
            disabled={disabled}
            onClick={() => {
              // 双重防御：native disabled 兜底 a11y / 键盘序列；运行时判 disabled 兜底
              // JS 旁路调用（理论上 disabled button 不触发 click，但合成事件 / devtools 可绕过）。
              if (disabled) return;
              setTab(t.id);
            }}
          >
            {t.label}
          </button>
        );
      })}
    </nav>
  );
}

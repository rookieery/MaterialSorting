// TabBar —— 顶部 Tab 切换（US-001 AC#1）。
//
// 渲染两个 Tab（排料 / 上传预览），点击切换 uiStore.activeTab；当前激活项加 `.active`
// class 高亮（与 ControlPanel 视觉同色系：暗背景 #26282e + 绿色 #2ea06c 强调，见 style.css）。
//
// 设计原则（CLAUDE.md / AGENTS.md）：
//   1. 不引入 CSS 框架，沿用 style.css 命令式 className 约定（`.tabbar / .tab / .tab.active`）。
//   2. Tab 切换由 uiStore 单字段驱动；App 订阅 activeTab 切 .page.hidden，不卸载组件
//      （AC#4 display:none 保 DOM，求解/WS/seek 全保留）。
//   3. 用原生 <button> 保证可键盘 focus / Enter 触发，符合 a11y 最低要求。

import type { ReactElement } from 'react';
import { useUiStore, type TabId } from '../store/uiStore';

/** Tab 元信息（顺序即渲染顺序，不可乱改：排料在前是默认入口）。 */
const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: 'nesting', label: '排料' },
  { id: 'preview', label: '上传预览' },
];

export function TabBar(): ReactElement {
  const activeTab = useUiStore((s) => s.activeTab);
  const setTab = useUiStore((s) => s.setTab);

  return (
    <nav className="tabbar" aria-label="页面切换">
      {TABS.map((t) => {
        const isActive = t.id === activeTab;
        return (
          <button
            key={t.id}
            type="button"
            className={`tab${isActive ? ' active' : ''}`}
            aria-pressed={isActive}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        );
      })}
    </nav>
  );
}

// TabBar —— 顶部 Tab 切换（US-001 AC#1）+ 超排 Tab 解锁闸（US-015）+ 右上角操作指引入口（US-029）。
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
// 右上角操作指引入口（US-029）：
//   - margin-left:auto 推到 .tabbar 右侧；native button「操作指引」+ 下拉菜单。
//   - 下拉菜单：US-029 仅「重置全部指引」一项（触发 resetSeen + start('preview') 跑 2 步假 tour）；
//     US-032 补全三项（重看 preview / 重看 nesting / 重置全部）。
//   - 点击外部 / ESC 关闭菜单（document click listener + keydown）。
//   - a11y：aria-haspopup="menu" + aria-expanded；按钮 class 用 .tour-entry（非 .tab，
//     不干扰现有 TabBar.test.tsx 的 button.tab 断言）。
//
// 设计原则（CLAUDE.md / AGENTS.md）：
//   1. 不引入 CSS 框架，沿用 style.css 命令式 className 约定。
//   2. Tab 切换由 uiStore 单字段驱动；App 订阅 activeTab 切 .page.hidden，不卸载组件。
//   3. 用原生 <button> 保证可键盘 focus / Enter 触发，符合 a11y 最低要求。

import { useEffect, useRef, useState } from 'react';
import type { ReactElement } from 'react';
import { useUiStore, type TabId } from '../store/uiStore';
import { useTourStore } from '../store/tourStore';

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
  const resetSeen = useTourStore((s) => s.resetSeen);
  const startTour = useTourStore((s) => s.start);

  const [menuOpen, setMenuOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭菜单（document mousedown listener）
  useEffect(() => {
    if (!menuOpen) return;
    function onDocMouseDown(e: MouseEvent): void {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') setMenuOpen(false);
    }
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  /** 重置全部指引：清 localStorage seen + 启动 preview demo tour（US-029 假 tour 验证链路）。 */
  function handleResetAll(): void {
    resetSeen();
    startTour('preview');
    setMenuOpen(false);
  }

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

      {/* US-029 右上角操作指引入口（margin-left:auto 推到右侧） */}
      <div className="tour-entry-wrapper" ref={wrapperRef}>
        <button
          type="button"
          className="tour-entry"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((o) => !o)}
        >
          操作指引
        </button>
        {menuOpen && (
          <div className="tour-menu" role="menu" data-testid="tour-menu">
            {/* US-029 仅一项；US-032 补全三项（重看 preview / 重看 nesting / 重置全部） */}
            <button
              type="button"
              className="tour-menu-item"
              role="menuitem"
              onClick={handleResetAll}
              data-testid="tour-menu-reset"
            >
              重置全部指引
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}

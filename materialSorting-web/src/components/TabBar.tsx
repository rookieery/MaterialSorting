// TabBar —— 顶部 Tab 切换（US-001 AC#1）+ 超排 Tab 解锁闸（US-015）+ 右上角操作指引入口（US-029 / US-032 两项菜单）。
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
// 右上角操作指引入口（US-029 基础设施 / US-032 补全三项菜单）：
//   - margin-left:auto 推到 .tabbar 右侧；native button「操作指引」+ 下拉菜单。
//   - 下拉菜单两项（US-032；原「重置全部指引」已移除）：
//     ①「查看上传预览指引」→ start('preview')（强制重放，不检查 seen）。
//     ②「查看超排指引」→ start('nesting')（强制重放，不检查 seen）。
//   - 每项仅在对应 Tab 可点：非当前 Tab 时置灰禁用（.disabled + aria-disabled +
//     native disabled 兜底 a11y / 键盘序列；handler 运行时再判一次兜底合成事件/devtools 旁路，
//     与超排 Tab 解锁闸同款双重防御）。
//   - 点击外部 / ESC 关闭菜单（document mousedown listener + keydown）。
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
  const startTour = useTourStore((s) => s.start);

  // 菜单项仅在对应 Tab 可点：非当前 Tab 置灰禁用（与 Tour Tab 同 .disabled 色系）。
  const previewDisabled = activeTab !== 'preview';
  const nestingDisabled = activeTab !== 'nesting';

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

  /** 查看上传预览指引：强制重放 preview tour（不检查 seen）。仅在 preview Tab 可点。US-032。 */
  function handleReplayPreview(): void {
    // 双重防御：native disabled 兜底真实用户点击；运行时再判一次兜底合成事件/devtools 旁路。
    if (previewDisabled) return;
    startTour('preview');
    setMenuOpen(false);
  }

  /** 查看超排指引：强制重放 nesting tour（不检查 seen）。仅在 nesting Tab 可点。US-032。 */
  function handleReplayNesting(): void {
    if (nestingDisabled) return;
    startTour('nesting');
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
            data-tour={t.id === 'nesting' ? 'tab-nesting' : undefined}
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
            {/* US-032 两项菜单：查看 preview / 查看 nesting（原「重置全部指引」已移除）。
                每项仅在对应 Tab 可点，非当前 Tab 置灰禁用。 */}
            <button
              type="button"
              className={`tour-menu-item${previewDisabled ? ' disabled' : ''}`}
              role="menuitem"
              aria-disabled={previewDisabled}
              disabled={previewDisabled}
              onClick={handleReplayPreview}
              data-testid="tour-menu-replay-preview"
            >
              查看上传预览指引
            </button>
            <button
              type="button"
              className={`tour-menu-item${nestingDisabled ? ' disabled' : ''}`}
              role="menuitem"
              aria-disabled={nestingDisabled}
              disabled={nestingDisabled}
              onClick={handleReplayNesting}
              data-testid="tour-menu-replay-nesting"
            >
              查看超排指引
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}

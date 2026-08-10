// SizeTabs —— 母版尺码切换条（US-008）。
//
// 职责：
//   1. 从 uploadStore 读 doc.sizes 拿到全部尺码列表（按后端返回的数值升序、null 殿后顺序），
//      渲染为可点击 chip 行；点击调 setSize(size) 切 activeSize。
//   2. 当前 activeSize 的 chip 加 .active 高亮（与 StartButton / TabBar active 同色 #2ea06c）。
//   3. null 码（母版里极少出现，统计上代表「通用/不分码」）显示为「通用」便于人读。
//
// 设计原则（CLAUDE.md / AGENTS.md US-005 关键约定）：
//   - 单一真相源：activeSize 与 doc 都来自 uploadStore；本组件只读 + 触发 setSize，
//     不持有任何本地状态（保证切 Tab 后状态保留：display:none 不卸载 + store 持久）。
//   - 沿用 style.css，不引入 CSS 框架；与 ControlPanel 的 .chip 视觉同色系（暗背景 + 绿色强调）。
//   - 用原生 <button> 保证键盘 focus / Enter 触发，符合 a11y 最低要求（与 TabBar 一致）。
//
// 空态：doc=null 时整组件不渲染（PreviewPage 负责整体空态提示；SizeTabs 仅在已解析时挂载）。

import type { JSX } from 'react';
import { useUploadStore } from '../../store/uploadStore';
import type { ParsedSize } from '../../types/parsed';

/** null 码（母版中代表通用/不分码）的人读文案。 */
const NULL_SIZE_LABEL = '通用';

/** 把 ParsedSize.size 格式化为 chip 文案（number→String，null→「通用」）。 */
function formatSize(size: number | null): string {
  return size === null ? NULL_SIZE_LABEL : String(size);
}

export function SizeTabs(): JSX.Element {
  const doc = useUploadStore((s) => s.doc);
  const activeSize = useUploadStore((s) => s.activeSize);
  const setSize = useUploadStore((s) => s.setSize);

  // doc=null 时 PreviewPage 走整体空态分支，不渲染 SizeTabs（双重防御）。
  if (!doc) return <></>;

  const sizes: ParsedSize[] = doc.sizes;

  return (
    <div className="size-tabs" role="tablist" aria-label="尺码切换">
      {sizes.map((s) => {
        const isActive = s.size === activeSize;
        const label = formatSize(s.size);
        return (
          <button
            key={label}
            type="button"
            // role=tab + aria-selected 让屏幕阅读器把 SizeTabs 当作一组切换 tab
            // （与 TabBar 的 aria-pressed 区别：TabBar 是页面切换，SizeTabs 是尺码切换；
            //  两者都遵循 a11y 最低要求：原生 button + 显式 aria）
            role="tab"
            aria-selected={isActive}
            className={`size-chip${isActive ? ' active' : ''}`}
            onClick={() => setSize(s.size)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

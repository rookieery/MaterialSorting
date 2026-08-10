// PreviewPage —— DXF 上传预览页容器（US-008 落地）。
//
// 职责：
//   1. 左侧 UploadPanel（US-006）+ 右侧（SizeTabs + ParsedPiecesView）的双栏布局。
//   2. 从 uploadStore 读 status + doc：未上传时右侧显示整体空态提示（与 US-001 占位文案一致风格），
//      已解析时挂载 SizeTabs + ParsedPiecesView。
//   3. 不持有任何本地状态（store 是单一真相源；切 Tab 后状态保留：display:none 不卸载 + store 持久）。
//
// 设计原则（CLAUDE.md / AGENTS.md US-001 关键约定）：
//   - 双页面常驻 DOM，display:none 切换 —— 本组件本身不挂 .hidden（由父 App 控制 .page.hidden）；
//     本组件渲染时已默认在 .page 容器内，故用 <div class="preview-page"> 作为根 flex 容器。
//   - 沿用 style.css，不引入 CSS 框架；视觉与 ControlPanel 同色系（暗背景 #26282e）。
//   - 左 UploadPanel 固定宽（.panel width: 248px），右侧自适应（与 NestingPage ControlPanel+main 同结构）。
//   - 切回 Tab 后状态保留：uploadStore 不被销毁，doc / activeSize 全部保真（AC#5 通过 store 保证）。
//
// 空态分支：
//   - status === 'done' 且 doc 非空 → 挂载 SizeTabs + ParsedPiecesView
//   - 其它（idle / uploading / error / done 但 doc=null 兜底）→ 显示空态提示卡片
//   - 上传中时 UploadPanel 自身会显示加载态，右侧空态保持「等待解析」提示一致体验。

import type { JSX } from 'react';
import { useUploadStore } from '../../store/uploadStore';
import { ParsedPiecesView } from './ParsedPiecesView';
import { SizeTabs } from './SizeTabs';
import { UploadPanel } from './UploadPanel';

export function PreviewPage(): JSX.Element {
  const status = useUploadStore((s) => s.status);
  const doc = useUploadStore((s) => s.doc);

  // 已解析且 doc 非空 → 挂载右侧主体（SizeTabs + ParsedPiecesView）。
  // 双重条件防御：done 状态理论必有 doc，但 TS 类型上 doc 是 nullable。
  const hasParsed = status === 'done' && doc !== null;

  return (
    <div className="preview-page">
      <UploadPanel />

      <section className="preview-main">
        {hasParsed ? (
          <>
            <SizeTabs />
            <ParsedPiecesView />
          </>
        ) : (
          <div className="preview-empty">
            <div className="preview-empty-card">
              <h2>DXF 上传预览</h2>
              <p>
                点击或拖拽母版 DXF 到左侧上传区，解析后按尺码切换查看每码全部裁片
                （毛版 / 净版 / 内部线 / 刀口 / 布纹线 + A/B/C 标注）。
              </p>
              <p className="dim">切到排料 Tab 再切回，本页状态（已选码 / 解析结果）全部保留。</p>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

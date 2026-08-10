// PreviewPage —— DXF 上传预览页容器（US-008 落地；US-014 集成模态 + 重传清零）。
//
// 职责：
//   1. 左侧 UploadPanel（US-006）+ 右侧（SizeTabs + ParsedPiecesView）的双栏布局。
//   2. 从 uploadStore 读 status + doc：未上传时右侧显示整体空态提示（与 US-001 占位文案一致风格），
//      已解析时挂载 SizeTabs + ParsedPiecesView。
//   3. 顶层挂 <PieceQtyDialog/> + <PieceZoomModal/> 单例（订阅 store 自显隐；US-014 集成）。
//   4. uploadStore.doc.doc_id 变化（首次上传 / 重传 / reset）→ 联动 qtyStore.resetQuantities()
//      （US-014 重传清零：避免旧母版数量残留到新母版）。
//   5. 不持有任何本地状态（store 是单一真相源；切 Tab 后状态保留：display:none 不卸载 + store 持久）。
//
// 设计原则（CLAUDE.md / AGENTS.md US-001 关键约定）：
//   - 双页面常驻 DOM，display:none 切换 —— 本组件本身不挂 .hidden（由父 App 控制 .page.hidden）；
//     本组件渲染时已默认在 .page 容器内，故用 <div class="preview-page"> 作为根 flex 容器。
//   - 沿用 style.css，不引入 CSS 框架；视觉与 ControlPanel 同色系（暗背景 #26282e）。
//   - 左 UploadPanel 固定宽（.panel width: 248px），右侧自适应（与 NestingPage ControlPanel+main 同结构）。
//   - 切回 Tab 后状态保留：uploadStore 不被销毁，doc / activeSize 全部保真（AC#5 通过 store 保证）。
//
// 重传清零（US-014 关键约定）：
//   - 用 useUploadStore.subscribe 监听 state 变化，对比 prev/next doc.doc_id；不同则调
//     useQtyStore.getState().resetQuantities()。覆盖三路径：首次上传（no-op）、重传（核心场景）、
//     reset() 清空（doc→null）。subscribe 在 useEffect 内挂载，卸载时 unsub（无残留）。
//   - 不在 uploadStore.reset 内直接调 qtyStore —— 两 store 解耦，由 PreviewPage 作为集成层
//     绑定（与 qtyStore / uploadStore 完全解耦的设计原则一致）。
//   - prevDocId 在 subscribe 闭包内 mutable（不依赖 React state），捕获 mount 时初始 doc_id；
//     subscribe 只对未来 state 变化触发，初始挂载不触发 reset。
//
// 空态分支：
//   - status === 'done' 且 doc 非空 → 挂载 SizeTabs + ParsedPiecesView
//   - 其它（idle / uploading / error / done 但 doc=null 兜底）→ 显示空态提示卡片
//   - 上传中时 UploadPanel 自身会显示加载态，右侧空态保持「等待解析」提示一致体验。
//
// 模态挂载（US-014）：
//   - <PieceQtyDialog/> + <PieceZoomModal/> 在 .preview-page 顶层（与 UploadPanel / .preview-main
//     同级）。两者均 createPortal(..., document.body)，DOM 位置与 React 树位置无关，故结构上
//     放在 PreviewPage 顶层最直观（与 SizeTabs / ParsedPiecesView 同级语义）。
//   - 默认 qtyDialog=null / zoom=null → 模态 return null（不挂 DOM）；store 写入目标时自显隐。

import { useEffect } from 'react';
import type { JSX } from 'react';
import { useUploadStore } from '../../store/uploadStore';
import { useQtyStore } from '../../store/qtyStore';
import { ParsedPiecesView } from './ParsedPiecesView';
import { PieceQtyDialog } from './PieceQtyDialog';
import { PieceZoomModal } from './PieceZoomModal';
import { SizeTabs } from './SizeTabs';
import { UploadPanel } from './UploadPanel';

export function PreviewPage(): JSX.Element {
  const status = useUploadStore((s) => s.status);
  const doc = useUploadStore((s) => s.doc);

  // 重传清零：监听 uploadStore.doc.doc_id 变化 → qtyStore.resetQuantities()
  // subscribe 在 mount 时注册，unmount 时 unsub；prevDocId 闭包内 mutable。
  useEffect(() => {
    let prevDocId: string | undefined = useUploadStore.getState().doc?.doc_id;
    const unsub = useUploadStore.subscribe((state) => {
      const nextDocId = state.doc?.doc_id;
      if (nextDocId !== prevDocId) {
        prevDocId = nextDocId;
        useQtyStore.getState().resetQuantities();
      }
    });
    return unsub;
  }, []);

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

      {/* 模态单例：订阅 store 自显隐；Portal 到 document.body，与 .preview-page 结构无关 */}
      <PieceQtyDialog />
      <PieceZoomModal />
    </div>
  );
}

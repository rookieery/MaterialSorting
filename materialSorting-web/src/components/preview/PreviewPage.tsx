// PreviewPage —— DXF 上传预览页容器（US-008 落地；US-014 集成模态 + 重传清零；
// US-016 联动 uiStore.nestingEnabled 解锁/锁定超排 Tab；矩阵化重构 US-003 集成 QtyMatrix）。
//
// 职责：
//   1. 左侧 UploadPanel（US-006）+ 右侧（QtyMatrix + ParsedPiecesView）的双栏布局。
//   2. 从 uploadStore 读 status + doc：未上传时右侧显示整体空态提示（与 US-001 占位文案一致风格），
//      已解析时挂载 QtyMatrix（数量矩阵）+ ParsedPiecesView（按码图形预览，码切换由矩阵列头驱动）。
//   3. 顶层挂 <PieceZoomModal/> 单例（订阅 store 自显隐；US-014 集成；数量编辑弹窗
//      PieceQtyDialog 已随矩阵化重构 US-003 拆除 —— 数量在 QtyMatrix 格内直接编辑）。
//   4. uploadStore.doc.doc_id 变化（首次上传 / 重传 / reset）→ 联动 qtyStore：
//      有 doc 时 hydrate（每码每片默认 1），doc→null 时 resetQuantities。
//      （US-014 重传清零的演进：旧母版数量不残留，新母版每片默认 1。）
//   5. 联动 uiStore.setNestingEnabled（US-016）：subscribe uploadStore，按
//      `status==='done' && doc!==null` 切 nestingEnabled；mount 时立即对齐初值。
//   6. 不持有任何本地状态（store 是单一真相源；切 Tab 后状态保留：display:none 不卸载 + store 持久）。
//
// 设计原则（CLAUDE.md / AGENTS.md US-001 关键约定）：
//   - 双页面常驻 DOM，display:none 切换 —— 本组件本身不挂 .hidden（由父 App 控制 .page.hidden）；
//     本组件渲染时已默认在 .page 容器内，故用 <div class="preview-page"> 作为根 flex 容器。
//   - 沿用 style.css，不引入 CSS 框架；视觉与 ControlPanel 同色系（暗背景 #26282e）。
//   - 左 UploadPanel 固定宽（.panel width: 248px），右侧自适应（与 NestingPage ControlPanel+main 同结构）。
//   - 切回 Tab 后状态保留：uploadStore 不被销毁，doc / activeSize 全部保真（AC#5 通过 store 保证）。
//
// 数量联动（US-014 关键约定，演进：清零 → 默认 1）：
//   - 用 useUploadStore.subscribe 监听 state 变化，对比 prev/next doc.doc_id；不同则按新 doc
//     初始化数量。覆盖三路径：首次上传（hydrate 默认 1）、重传（核心场景，重新 hydrate 默认 1、
//     旧编辑被新母版默认覆盖）、reset() 清空（doc→null，resetQuantities 回 {}）。subscribe 在
//     useEffect 内挂载，卸载时 unsub（无残留）。
//   - 额外挂载即对齐：mount 时若已有 doc 立即 hydrate（迟到挂载 / 刷新恢复兜底）。
//   - 不在 uploadStore.reset 内直接调 qtyStore —— 两 store 解耦，由 PreviewPage 作为集成层
//     绑定（与 qtyStore / uploadStore 完全解耦的设计原则一致）。
//   - prevDocId 在 subscribe 闭包内 mutable（不依赖 React state），捕获 mount 时初始 doc_id。
//
// Tab 解锁联动（US-016 关键约定）：
//   - subscribe uploadStore，按 `status==='done' && doc!==null` 切 setNestingEnabled；
//     覆盖四路径：idle（默认 false）/ done+doc（true）/ error（false）/ reset（doc→null false）/
//     重传（status 切 uploading 短暂 false，done 后切回 true）。
//   - mount 时立即对齐初值（idle → false），避免迟到挂载 / 刷新恢复时残留旧解锁态。
//   - **关键不变量（AC#3）**：setNestingEnabled 仅控 Tab「能否进入」，不强制切 Tab ——
//     uiStore.setNestingEnabled 实现仅 `set({ nestingEnabled: b })`，不触碰 activeTab；
//     若用户已在 nesting Tab 时 reset，Tab 仍可点回 preview（preview 永远可点）但不强制切回，
//     避免丢失求解状态。
//   - uiStore 与 uploadStore 解耦（与 qtyStore 同设计原则）：uploadStore 不知道 uiStore 存在，
//     PreviewPage 作为集成层用 subscribe 绑定。
//
// 空态分支：
//   - status === 'done' 且 doc 非空 → 挂载 QtyMatrix + ParsedPiecesView
//   - 其它（idle / uploading / error / done 但 doc=null 兜底）→ 显示空态提示卡片
//   - 上传中时 UploadPanel 自身会显示加载态，右侧空态保持「等待解析」提示一致体验。
//
// 模态挂载（US-014；US-003 拆除数量弹窗后仅剩放大预览）：
//   - <PieceZoomModal/> 在 .preview-page 顶层（与 UploadPanel / .preview-main 同级）。
//     createPortal(..., document.body)，DOM 位置与 React 树位置无关，故结构上放在
//     PreviewPage 顶层最直观（与 QtyMatrix / ParsedPiecesView 同级语义）。
//   - 默认 zoom=null → 模态 return null（不挂 DOM）；store 写入目标时自显隐。

import { useEffect } from 'react';
import type { JSX } from 'react';
import { useUploadStore, type UploadStatus } from '../../store/uploadStore';
import { useQtyStore } from '../../store/qtyStore';
import { useUiStore } from '../../store/uiStore';
import type { ParsedDoc } from '../../types/parsed';
import { ParsedPiecesView } from './ParsedPiecesView';
import { PieceZoomModal } from './PieceZoomModal';
import { QtyMatrix } from './QtyMatrix';
import { UploadPanel } from './UploadPanel';

export function PreviewPage(): JSX.Element {
  const status = useUploadStore((s) => s.status);
  const doc = useUploadStore((s) => s.doc);

  // 解析完成 / 重传 / reset 联动 qtyStore：
  //   - 有 doc（doc_id 变化或挂载时已有 doc）→ 按 doc 全码全片初始化默认数量 1 + baseValue 1。
  //     把「每尺码每片默认 1」物化进 store（下游 commit / 排料直接读 map，不靠 selector 兜底）。
  //   - doc→null（reset）→ 清空数量。
  // 集成层职责：qtyStore / uploadStore 完全解耦，由 PreviewPage 把 doc.pieces 翻译成
  // {label,size} 列表喂给 qtyStore.hydrate（store 不依赖 parsed 类型）。
  useEffect(() => {
    const syncQty = (doc: ParsedDoc | null): void => {
      if (doc) {
        const entries = doc.sizes.flatMap((s) =>
          s.pieces.map((p) => ({ label: p.label, size: s.size })),
        );
        useQtyStore.getState().hydrate(entries);
      } else {
        useQtyStore.getState().resetQuantities();
      }
    };

    // 挂载即对齐：迟到挂载 / 刷新恢复时若已有 doc，立即初始化默认数量（生产中 App 常驻、
    // mount 时 doc=null，此处理论 no-op；主要为测试与未来路由恢复场景的健壮性兜底）。
    let prevDocId: string | undefined = useUploadStore.getState().doc?.doc_id;
    syncQty(useUploadStore.getState().doc);

    const unsub = useUploadStore.subscribe((state) => {
      const nextDocId = state.doc?.doc_id;
      if (nextDocId !== prevDocId) {
        prevDocId = nextDocId;
        syncQty(state.doc);
      }
    });
    return unsub;
  }, []);

  // Tab 解锁联动（US-016）：subscribe uploadStore，按 `status==='done' && doc!==null`
  // 切 uiStore.setNestingEnabled；mount 时立即对齐初值（idle → false）。
  //   - 覆盖路径：idle/uploading（false）/ done+doc（true）/ error（false）/
  //     reset（doc→null false）/ 重传（uploading 短暂 false，done 切回 true）。
  //   - 关键不变量（AC#3）：setNestingEnabled 仅控 Tab「能否进入」，不强制切 Tab ——
  //     uiStore.setNestingEnabled 实现不触碰 activeTab，故用户在 nesting Tab 时 reset
  //     不会被强制切回 preview（避免丢失求解状态）。
  //   - 与 qtyStore 联动同模式：subscribe + mount 即对齐 + 卸载时 unsub。
  //   - 调用 setNestingEnabled 前先判 next !== prev（get().nestingEnabled），避免无变化
  //     时无谓 setState 触发订阅者通知（zustand 内部 Object.is 也会兜底，但显式判断
  //     更省一次 set 调度）。
  useEffect(() => {
    const syncTab = (status: UploadStatus, doc: ParsedDoc | null): void => {
      const next = status === 'done' && doc !== null;
      if (useUiStore.getState().nestingEnabled !== next) {
        useUiStore.getState().setNestingEnabled(next);
      }
    };

    // 挂载即对齐：迟到挂载 / 刷新恢复时按当前 status 立即对齐（默认 idle → false）。
    {
      const s = useUploadStore.getState();
      syncTab(s.status, s.doc);
    }

    const unsub = useUploadStore.subscribe((state) => {
      syncTab(state.status, state.doc);
    });
    return unsub;
  }, []);

  // 已解析且 doc 非空 → 挂载右侧主体（QtyMatrix + ParsedPiecesView）。
  // 双重条件防御：done 状态理论必有 doc，但 TS 类型上 doc 是 nullable。
  const hasParsed = status === 'done' && doc !== null;

  return (
    <div className="preview-page">
      <UploadPanel />

      <section className="preview-main">
        {hasParsed ? (
          <>
            <QtyMatrix />
            <ParsedPiecesView />
          </>
        ) : (
          <div className="preview-empty">
            <div className="preview-empty-card">
              <h2>DXF 上传预览</h2>
              <p>
                点击或拖拽母版 DXF 到左侧上传区，解析后在数量矩阵中编辑每码裁片数量
                （毛版 / 净版 / 内部线 / 刀口 / 布纹线 + A/B/C 标注），点击矩阵列头切换图形预览码。
              </p>
              <p className="dim">切到排料 Tab 再切回，本页状态（已选码 / 解析结果）全部保留。</p>
            </div>
          </div>
        )}
      </section>

      {/* 模态单例：订阅 store 自显隐；Portal 到 document.body，与 .preview-page 结构无关 */}
      <PieceZoomModal />
    </div>
  );
}

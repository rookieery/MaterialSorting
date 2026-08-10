// PreviewPage —— DXF 上传预览页容器（US-001 仅占位，US-008 落地 UploadPanel + SizeTabs + ParsedPiecesView）。
//
// US-001 阶段：App 已为预览页预留 `.page preview-page` 容器（display:none 切换），
//   此处仅渲染「待实现」空态提示，保证 Tab 切到预览时不是空白屏，便于 dev 演示。
// US-008 将替换为本体（左 UploadPanel + 右 SizeTabs + ParsedPiecesView）。
//
// 设计原则：沿用 style.css，不引入 CSS 框架；视觉与 ControlPanel 同色系（暗背景 + 提示字）。

export function PreviewPage(): React.JSX.Element {
  return (
    <div className="preview-empty">
      <div className="preview-empty-card">
        <h2>DXF 上传预览</h2>
        <p>该页将在 US-006 ~ US-008 落地：点击 / 拖拽上传母版 → 按码切换 → 单片还原（毛版 / 净版 / 内部线 / 刀口 / 布纹线）。</p>
        <p className="dim">当前 Tab 切换已可用 —— 切回排料 Tab，进行中的求解 / WS / 播放进度均保留。</p>
      </div>
    </div>
  );
}

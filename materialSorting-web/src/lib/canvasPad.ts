// canvasPad —— 画布垂直留白换算（2026-09-16 视觉优化 v2：无条件 ≥留门口径）。
//
// 背景：NestSVG（超排卡）与 EditCanvas（编辑弹窗）都是 viewBox = 布局包围盒
// (W×gate) + preserveAspectRatio="xMinYMid meet" + svg 铺满容器。meet 缩放比
// s = min(容器宽/W, 容器高/gate)。裁片少 → W 小 → 内容放大到撑满整个高度，上下
// 零留白（v0 原始行为，用户第一轮反馈）。
//
// v1 教训（同日二轮，用户实测否决）：v1 用「高度受限才干预」（a > b 才加 pad）当
// 「少片」的代理变量 —— 但纵横比 1.5~2.2 的**中等致密唛架**在宽屏容器里同样高度
// 受限或临界：超排卡（容器纵横 ≈1.87 < 内容 1.94）落宽度受限分支 → 留白没出现
// （预期落差）；编辑弹窗留白生效但内容缩 47% + 灰画布跟着 viewBox 塌陷露出深黑
// 空洞（观感更坏）。「哪个维度受限」与「内容是否致密」无关，判据不可用。
//
// v2 口径（用户定案）：**无条件**保证上下各 ≥px 留白 —— s = min(a, target)，
// target = (H−2px)/vbH：
//   a ≤ target → pad=0（宽度受限且上下余量本已 ≥px，深宽唛架 8m+ 逐字节不变）；
//   a > target → pad = px·vbH/(H−2px) ⇒ meet 下 s = target ⇒ 内容高恰 H−2px。
// 推导：H/(vbH+2pad) = target ⇔ pad = px·vbH/(H−2px)；a = target 处两侧同值，
// 连续无跳变（v1 在 a=b 处有 (H/(H−2px))−1 倍跳变）。
//
// 兜底：容器尺寸不可得（jsdom gBCR=0 / 未布局）→ 0（既有渲染逐字节不变）；
// 小容器（H < 800）px 按 H/4 优雅降级（保证分母 H−2px ≥ H/2 > 0，内容不挤没）。
export const CANVAS_VPAD_PX = 200;

/**
 * 画布垂直留白（世界 mm）。参数：boxW/boxH = svg 元素像素尺寸（getBoundingClientRect），
 * vbW/vbH = viewBox 世界尺寸（W×gate）。返回 padY；a ≤ target（余量已足）时 0。
 */
export function canvasVPadMm(boxW: number, boxH: number, vbW: number, vbH: number): number {
  if (!(boxW > 0) || !(boxH > 0) || !(vbW > 0) || !(vbH > 0)) return 0;
  const px = Math.min(CANVAS_VPAD_PX, Math.floor(boxH / 4));
  const denom = boxH - 2 * px; // ≥ boxH/2 > 0
  const target = denom / vbH; // 留白后的高比上限（px/mm）
  const a = boxW / vbW; // 宽比（px/mm）
  if (a <= target) return 0; // 宽度受限且上下余量 ≥px → 不干预（逐字节不变）
  return (px * vbH) / denom;
}

/**
 * 便捷封装：读 svg 当前像素尺寸算留白（NestSVG 每帧 / EditCanvas vb0 与全览复位用）。
 * 未布局 / jsdom 零尺寸 → 0。
 */
export function canvasVPadOf(svg: SVGSVGElement, vbW: number, vbH: number): number {
  const r = svg.getBoundingClientRect();
  return canvasVPadMm(r.width, r.height, vbW, vbH);
}

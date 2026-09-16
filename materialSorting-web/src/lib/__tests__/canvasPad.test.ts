// canvasPad 单测 —— v2 无条件垂直留白口径（2026-09-16 二轮，用户实测否决 v1 条件口径）：
//   1) 高度受限（裁片少）→ 内容高恰为 H−2px（上下各 ≥200px）；
//   2) v2 无条件：中等致密唛架（宽度受限但上下余量 <px —— v1 盲区）同样钳到 H−2px；
//   3) 深宽唛架（a ≤ target：余量本已 ≥px）→ 0 逐字节不变；a == target 边界 → 0（连续）；
//   4) 零尺寸（jsdom / 未布局）→ 0 兜底；
//   5) 小容器 → px 按 H/4 降级（内容高 ≥ H/2，不挤没）。

import { describe, expect, it } from 'vitest';

import { CANVAS_VPAD_PX, canvasVPadMm } from '../canvasPad';

describe('canvasVPadMm 无条件垂直留白（v2）', () => {
  it('高度受限（裁片少：宽比 > 高比）→ 内容高恰为 H−2px，上下各 ≥200px', () => {
    // 夹具：容器 1560×900px，viewBox 600×1750（窄高条，少片形态）。
    const W = 1560;
    const H = 900;
    const vbW = 600;
    const gate = 1750;
    const pad = canvasVPadMm(W, H, vbW, gate);
    expect(pad).toBeGreaterThan(0);
    // meet 语义复算：s = min(W/vbW, H/(gate+2pad))，内容高 = s·gate。
    const s = Math.min(W / vbW, H / (gate + 2 * pad));
    expect(s).toBeCloseTo(H / (gate + 2 * pad), 10); // 高度仍钳在 target（pad 未越界翻转）
    const contentH = s * gate;
    expect(contentH).toBeCloseTo(H - 2 * CANVAS_VPAD_PX, 6); // = 500px → 上下各 200px
  });

  it('v2 无条件：中等致密唛架（宽度受限 a<b 但余量 <px，v1 盲区）→ 同样钳到 H−2px', () => {
    // 用户实测场景同构：容器 1560×760（纵横 2.05），viewBox 3400×1450（纵横 2.34）。
    // a=0.459 ≤ b=0.524（宽度受限）但 a > target=380/1450=0.262（上下余量不足 190px）→
    // v1 此形态 pad=0（「满宽不干预」判据误判致密形态）—— v2 钳到内容高 380px。
    const W = 1560;
    const H = 760;
    const vbW = 3400;
    const gate = 1450;
    expect(W / vbW).toBeLessThanOrEqual(H / gate); // 前提：宽度受限（v1 会返回 0）
    const pad = canvasVPadMm(W, H, vbW, gate);
    expect(pad).toBeGreaterThan(0); // v2 不再放过
    const s = Math.min(W / vbW, H / (gate + 2 * pad));
    expect(s * gate).toBeCloseTo(H - 2 * Math.min(CANVAS_VPAD_PX, Math.floor(H / 4)), 6); // = 380px
  });

  it('深宽唛架（a ≤ target：余量本已 ≥px）→ 0 逐字节不变；a == target 边界 → 0（连续）', () => {
    // 容器 1560×900，viewBox 8000×1450：a=0.195 ≤ target=500/1450=0.345 → 0。
    expect(canvasVPadMm(1560, 900, 8000, 1450)).toBe(0);
    // 边界 a == target：boxH=800 → px=200 → denom=400；target=400/1000=0.4 == a=1000/2500。
    // 两侧同值（clamp 与 width-fit 给出同一 s）→ pad=0，无跳变。
    expect(canvasVPadMm(1000, 800, 2500, 1000)).toBe(0);
  });

  it('零尺寸 / 非法尺寸（jsdom gBCR=0 / 未布局）→ 0 兜底', () => {
    expect(canvasVPadMm(0, 0, 900, 1980)).toBe(0);
    expect(canvasVPadMm(0, 760, 600, 1750)).toBe(0);
    expect(canvasVPadMm(1560, 0, 600, 1750)).toBe(0);
    expect(canvasVPadMm(1560, 760, 0, 1750)).toBe(0);
    expect(canvasVPadMm(1560, 760, 600, 0)).toBe(0);
  });

  it('小容器优雅降级：px = H/4，内容高 ≥ H/2 不挤没', () => {
    const gate = 1750;
    for (const H of [300, 600, 799]) {
      const pad = canvasVPadMm(1560, H, 600, gate);
      expect(pad).toBeGreaterThan(0);
      const s = Math.min(1560 / 600, H / (gate + 2 * pad));
      expect(s * gate).toBeCloseTo(H - 2 * Math.floor(H / 4), 6); // = H/2（H<800 时 floor 对齐）
    }
    // H ≥ 800 → 足额 200px×2。
    const pad800 = canvasVPadMm(1560, 800, 600, gate);
    const s800 = Math.min(1560 / 600, 800 / (gate + 2 * pad800));
    expect(s800 * gate).toBeCloseTo(400, 6);
  });
});

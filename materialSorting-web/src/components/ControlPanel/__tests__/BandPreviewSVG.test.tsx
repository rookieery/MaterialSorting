// BandPreviewSVG 单测（2026-08-24 成带形态预览）：
//   AC#1 命令式渲染范式（React 仅空骨架；成员/轮廓/标注全部 imperative；StrictMode 双 mount 安全）
//   AC#2 成员尺码着色（fill = size_color、半透明 + 同色实线边）+ data-size 可辨码序
//   AC#3 组合片外轮廓虚线叠加（outline 层）
//   AC#4 翻转组 transform = translate(0 minY+maxY) scale(1 -1)（与 PiecePreviewSVG/NestSVG 一致）
//   AC#5 showLabels：尺码文字在翻转组外（屏幕坐标，不镜像）；compact 默认无标注
//   AC#6 空数据清空不画 + bandBBox 纯函数（members ∪ outline 合并）

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode, type MutableRefObject } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { BandPreviewSVG, bandBBox } from '../BandPreviewSVG';
import type { BandPreviewMember } from '../../../types/band';
import type { Polygon } from '../../../types/piece';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) {
    const r = root;
    act(() => {
      r.unmount();
    });
    root = null;
  }
  container?.remove();
  container = null;
});

/** 两成员带（28 码蓝下半 / 29 码橙上半，0..600 × 0..300）。 */
const MEMBERS: BandPreviewMember[] = [
  {
    pid: 'g01_28',
    size: 28,
    color: '#1f77b4',
    polygon: [
      [0, 0],
      [600, 0],
      [600, 150],
      [0, 150],
    ],
  },
  {
    pid: 'g01_29',
    size: 29,
    color: '#ff7f0e',
    polygon: [
      [0, 150],
      [600, 150],
      [600, 300],
      [0, 300],
    ],
  },
];

const OUTLINE: Polygon = [
  [0, 0],
  [600, 0],
  [600, 300],
  [0, 300],
];

/** StrictMode 双 mount 包装的 Probe（拿到 svg ref）。 */
function mountProbe(
  members: BandPreviewMember[],
  outline?: unknown,
  showLabels = false,
): MutableRefObject<SVGSVGElement | null> {
  const ref: MutableRefObject<SVGSVGElement | null> = { current: null };
  function Probe() {
    return (
      <div
        ref={(el) => {
          ref.current = el?.querySelector('svg') ?? null;
        }}
      >
        <BandPreviewSVG
          members={members}
          outline={(outline as never) ?? null}
          showLabels={showLabels}
        />
      </div>
    );
  }
  act(() => {
    root!.render(
      <StrictMode>
        <Probe />
      </StrictMode>,
    );
  });
  return ref;
}

describe('BandPreviewSVG', () => {
  it('成员尺码着色 + data-size；轮廓虚线叠加；翻转组 transform（AC#2~4）', () => {
    const ref = mountProbe(MEMBERS, OUTLINE);
    const svg = ref.current!;
    expect(svg).not.toBeNull();
    expect(svg.getAttribute('class')).toBe('band-preview-svg');
    const flip = svg.querySelector('[data-role="flip"]')!;
    expect(flip.getAttribute('transform')).toBe('translate(0 300) scale(1 -1)');
    // 两成员 polygon：fill = 尺码色 + fill-opacity；stroke 同色；data-size 辨码序
    const polys = Array.from(svg.querySelectorAll('[data-role="band-member"]'));
    expect(polys).toHaveLength(2);
    expect(polys[0].getAttribute('fill')).toBe('#1f77b4');
    expect(polys[0].getAttribute('fill-opacity')).toBe('0.55');
    expect(polys[0].getAttribute('data-size')).toBe('28');
    expect(polys[1].getAttribute('fill')).toBe('#ff7f0e');
    // 组合片外轮廓虚线（fill none + dasharray）
    const env = svg.querySelector('[data-role="band-outline"]')!;
    expect(env.getAttribute('fill')).toBe('none');
    expect(env.getAttribute('stroke-dasharray')).toBe('6 3');
    // 缩略默认无尺码标注（AC#5）
    expect(svg.querySelector('[data-role="band-size-label"]')).toBeNull();
  });

  it('showLabels：尺码文字在翻转组外（svg 直下、flip 组内无），居中锚点（AC#5）', () => {
    const ref = mountProbe(MEMBERS, OUTLINE, true);
    const svg = ref.current!;
    const labels = Array.from(svg.querySelectorAll('[data-role="band-size-label"]'));
    expect(labels).toHaveLength(2);
    for (const t of labels) {
      expect(t.parentElement).toBe(svg);           // 翻转组外（svg 直下，不镜像）
      expect(t.getAttribute('text-anchor')).toBe('middle');
    }
    // 28 码成员中心 (300,75) → 屏幕 Y = 300 − 75 = 225
    const label28 = labels.find((t) => t.textContent === '28')!;
    expect(label28.getAttribute('x')).toBe('300');
    expect(label28.getAttribute('y')).toBe('225');
  });

  it('空数据清空不画（无 flip 组残留）；数据切换整组重建（AC#6）', () => {
    const ref: MutableRefObject<SVGSVGElement | null> = { current: null };
    // 同一 wrapper 结构重渲（保 probe ref 存活），仅换 members/outline props
    const render = (members: BandPreviewMember[], outline: Polygon | null): void => {
      function Probe() {
        return (
          <div
            ref={(el) => {
              ref.current = el?.querySelector('svg') ?? null;
            }}
          >
            <BandPreviewSVG members={members} outline={outline} />
          </div>
        );
      }
      act(() => {
        root!.render(
          <StrictMode>
            <Probe />
          </StrictMode>,
        );
      });
    };
    render(MEMBERS, OUTLINE);
    expect(ref.current!.querySelector('[data-role="band-member"]')).not.toBeNull();
    // 切空数据 → 清空（不留旧 flip 组/成员残影）
    render([], null);
    expect(ref.current!.querySelector('[data-role="band-member"]')).toBeNull();
    expect(ref.current!.querySelector('[data-role="flip"]')).toBeNull();
  });

  it('bandBBox 纯函数：members ∪ outline 合并；空数据 null（AC#6）', () => {
    const bb = bandBBox(MEMBERS, OUTLINE)!;
    expect(bb).toEqual({ minX: 0, minY: 0, maxX: 600, maxY: 300 });
    // outline 超出成员时并入（组合片轮廓是成员 union 的超集方向）
    const biggerOutline: Polygon = [
      [-5, -5],
      [700, 400],
    ];
    const bigger = bandBBox(MEMBERS, biggerOutline)!;
    expect(bigger).toEqual({ minX: -5, minY: -5, maxX: 700, maxY: 400 });
    expect(bandBBox([], null)).toBeNull();
  });
});

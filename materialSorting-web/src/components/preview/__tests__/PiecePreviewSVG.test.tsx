// PiecePreviewSVG 单测（US-007）：
//   AC#1 命令式渲染范式（React 仅渲染空骨架；子节点全部 imperative；flipRef 幂等在 StrictMode 双 mount 安全）
//   AC#2 渲染分层（毛版蓝实心 / 净版绿虚 / 内部线橙实 / 刀口黄短线 / 布纹线红虚）
//   AC#3 翻转组 transform = translate(0 minY+maxY) scale(1 -1) + g 码文字在翻转组外（不镜像）
//   AC#4 单片 / 多片同框 / 空片容错
//   AC#5 切 piece 整组重建（不残留旧节点）+ pad clamp

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode, type MutableRefObject } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PiecePreviewSVG, piecesBBox, pieceBBox } from '../PiecePreviewSVG';
import type { ParsedPiece } from '../../../types/parsed';

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

/** 构造一片：方框 100x80 在 (10,20)-(110,100)，可选附加 net/internal/notch/grain。 */
function makePiece(overrides: Partial<ParsedPiece> = {}): ParsedPiece {
  return {
    label: 'g01',
    name: '前片-30',
    polygon: [
      [10, 20],
      [110, 20],
      [110, 100],
      [10, 100],
    ],
    internal_lines: [],
    notches: [],
    net_polygon: [],
    grain_line: null,
    ...overrides,
  };
}

/** StrictMode 双 mount 包装的 Probe（拿到 svg ref）。 */
function mountProbe(piece: ParsedPiece | ParsedPiece[], pad?: number): MutableRefObject<SVGSVGElement | null> {
  const ref: MutableRefObject<SVGSVGElement | null> = { current: null };
  function Probe() {
    return (
      <div
        ref={(el) => {
          ref.current = el?.querySelector('svg') ?? null;
        }}
      >
        <PiecePreviewSVG piece={piece} pad={pad} />
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

/** 非 StrictMode 包装（用于测「无 StrictMode 也能建 DOM」基础路径）。 */
function mountSimple(piece: ParsedPiece | ParsedPiece[], pad?: number): SVGSVGElement {
  let svg: SVGSVGElement | null = null;
  act(() => {
    root!.render(
      <div
        ref={(el) => {
          svg = el?.querySelector('svg') ?? null;
        }}
      >
        <PiecePreviewSVG piece={piece} pad={pad} />
      </div>,
    );
  });
  return svg!;
}
describe('PiecePreviewSVG (US-007) — pieceBBox / piecesBBox pure helpers', () => {
  it('pieceBBox 合并所有层顶点', () => {
    const p = makePiece({
      net_polygon: [
        [20, 30],
        [100, 30],
        [100, 90],
      ],
      internal_lines: [
        [
          [5, 50],
          [115, 50],
        ],
      ],
      notches: [[10, 20, 0, -1]],
      grain_line: [0, 0, 200, 0],
    });
    const bb = pieceBBox(p)!;
    // grain 200 扩大 maxX；net/internal/notch 都在 polygon 范围内或边上
    expect(bb.minX).toBe(0);
    expect(bb.minY).toBe(0);
    expect(bb.maxX).toBe(200);
    expect(bb.maxY).toBe(100);
  });

  it('pieceBBox 空片（全无数据）返回 null', () => {
    const p: ParsedPiece = {
      label: 'g01',
      name: '空',
      polygon: [],
      internal_lines: [],
      notches: [],
      net_polygon: [],
      grain_line: null,
    };
    expect(pieceBBox(p)).toBeNull();
  });

  it('pieceBBox 无 grain_line 时跳过；无 net_polygon 时正常算', () => {
    const p = makePiece();
    const bb = pieceBBox(p)!;
    expect(bb).toEqual({ minX: 10, minY: 20, maxX: 110, maxY: 100 });
  });

  it('piecesBBox 合并多片 bbox', () => {
    const a = makePiece(); // (10,20)-(110,100)
    const b = makePiece({
      polygon: [
        [200, 0],
        [300, 0],
        [300, 50],
        [200, 50],
      ],
    }); // (200,0)-(300,50)
    const bb = piecesBBox([a, b])!;
    expect(bb).toEqual({ minX: 10, minY: 0, maxX: 300, maxY: 100 });
  });

  it('piecesBBox 全空片返回 null', () => {
    const empty: ParsedPiece = {
      label: '',
      name: '',
      polygon: [],
      internal_lines: [],
      notches: [],
      net_polygon: [],
      grain_line: null,
    };
    expect(piecesBBox([empty, empty])).toBeNull();
  });
});
describe('PiecePreviewSVG (US-007) AC#1 命令式渲染范式', () => {
  it('React 仅渲染 <svg ref/> 空骨架（mount 时建子节点 imperative）', () => {
    const ref = mountProbe(makePiece());
    const svg = ref.current!;
    expect(svg.tagName).toBe('svg');
    // 子节点 ≥ 1（flipGroup + 至少 1 rough polygon + label text）
    expect(svg.childNodes.length).toBeGreaterThanOrEqual(1);
    // 第一个子节点必为翻转组 <g data-role=flip>
    const flip = svg.childNodes[0] as SVGGElement;
    expect(flip.tagName).toBe('g');
    expect(flip.getAttribute('data-role')).toBe('flip');
  });

  it('StrictMode 双 mount 不残留（清空后重建）', () => {
    const ref = mountProbe(makePiece());
    const svgBefore = ref.current!;
    const flipCountBefore = svgBefore.querySelectorAll('g[data-role="flip"]').length;
    expect(flipCountBefore).toBe(1);

    // 重渲染同一 piece 不应产生第二个 flipGroup
    act(() => {
      root!.render(
        <StrictMode>
          <div
            ref={(el) => {
              ref.current = el?.querySelector('svg') ?? null;
            }}
          >
            <PiecePreviewSVG piece={makePiece()} />
          </div>,
        </StrictMode>,
      );
    });
    const svgAfter = ref.current!;
    expect(svgAfter.querySelectorAll('g[data-role="flip"]').length).toBe(1);
  });
});

describe('PiecePreviewSVG (US-007) AC#2 渲染分层（颜色 / 线型 / 数据）', () => {
  it('layer1 毛版：半透明蓝实心 + 实线边（fill / stroke / stroke-width）', () => {
    const piece = makePiece();
    const svg = mountSimple(piece);
    const rough = svg.querySelector('polygon[data-role="rough"]') as SVGPolygonElement | null;
    expect(rough).not.toBeNull();
    expect(rough!.getAttribute('points')!.length).toBeGreaterThan(0);
    expect(rough!.getAttribute('fill')).toBe('rgba(80, 140, 200, 0.22)');
    expect(rough!.getAttribute('stroke')).toBe('#3f7fbf');
    expect(rough!.getAttribute('stroke-width')).toBe('1.5');
  });

  it('layer1 points 字符串与 r2 + 空格分隔一致', () => {
    const piece = makePiece();
    const svg = mountSimple(piece);
    const rough = svg.querySelector('polygon[data-role="rough"]')!;
    // polygon = (10,20)(110,20)(110,100)(10,100)，r2 后均整数
    expect(rough.getAttribute('points')).toBe('10,20 110,20 110,100 10,100');
  });

  it('layer14 净版：绿虚线 polygon，无填充', () => {
    const piece = makePiece({
      net_polygon: [
        [20, 30],
        [100, 30],
        [100, 90],
        [20, 90],
      ],
    });
    const svg = mountSimple(piece);
    const net = svg.querySelector('polygon[data-role="net"]') as SVGPolygonElement | null;
    expect(net).not.toBeNull();
    expect(net!.getAttribute('fill')).toBe('none');
    expect(net!.getAttribute('stroke')).toBe('#33cc33');
    expect(net!.getAttribute('stroke-dasharray')).toBe('6 3');
  });

  it('layer8 内部线：橙色 polyline，每条独立', () => {
    const piece = makePiece({
      internal_lines: [
        [
          [20, 50],
          [100, 50],
        ],
        [
          [50, 30],
          [50, 90],
        ],
      ],
    });
    const svg = mountSimple(piece);
    const internals = svg.querySelectorAll('polyline[data-role="internal"]');
    expect(internals.length).toBe(2);
    expect(internals[0].getAttribute('stroke')).toBe('#ff8c1a');
    expect(internals[0].getAttribute('fill')).toBe('none');
    expect(internals[1].getAttribute('points')).toBe('50,30 50,90');
  });

  it('layer8 internal line < 2 顶点跳过（不渲染残线）', () => {
    const piece = makePiece({
      internal_lines: [[[50, 50]]], // 单点，跳过
    });
    const svg = mountSimple(piece);
    expect(svg.querySelectorAll('polyline[data-role="internal"]').length).toBe(0);
  });

  it('layer4 刀口：黄色短线段，沿法线 8mm（half=4，P ± 4*normal）', () => {
    // 法线 (1,0)，点 (110, 60)：端点 (106,60)-(114,60)
    const piece = makePiece({
      notches: [[110, 60, 1, 0]],
    });
    const svg = mountSimple(piece);
    const notch = svg.querySelector('line[data-role="notch"]') as SVGLineElement | null;
    expect(notch).not.toBeNull();
    expect(notch!.getAttribute('stroke')).toBe('#ffd700');
    expect(notch!.getAttribute('x1')).toBe('106');
    expect(notch!.getAttribute('y1')).toBe('60');
    expect(notch!.getAttribute('x2')).toBe('114');
    expect(notch!.getAttribute('y2')).toBe('60');
  });

  it('layer4 刀口：法线斜向（0.6, 0.8），端点 P ± 4*normal', () => {
    const piece = makePiece({
      notches: [[10, 20, 0.6, 0.8]],
    });
    const svg = mountSimple(piece);
    const notch = svg.querySelector('line[data-role="notch"]')!;
    // (10 - 4*0.6, 20 - 4*0.8) = (7.6, 16.8)；(10 + 4*0.6, 20 + 4*0.8) = (12.4, 23.2)
    expect(notch.getAttribute('x1')).toBe('7.6');
    expect(notch.getAttribute('y1')).toBe('16.8');
    expect(notch.getAttribute('x2')).toBe('12.4');
    expect(notch.getAttribute('y2')).toBe('23.2');
  });

  it('layer7 布纹线：红色虚线 line（[x1,y1,x2,y2]）', () => {
    const piece = makePiece({
      grain_line: [10, 60, 110, 60],
    });
    const svg = mountSimple(piece);
    const grain = svg.querySelector('line[data-role="grain"]') as SVGLineElement | null;
    expect(grain).not.toBeNull();
    expect(grain!.getAttribute('stroke')).toBe('#e53e3e');
    expect(grain!.getAttribute('stroke-dasharray')).toBe('5 3');
    expect(grain!.getAttribute('x1')).toBe('10');
    expect(grain!.getAttribute('x2')).toBe('110');
  });

  it('layer7 grain_line=null 不渲染布纹线节点', () => {
    const svg = mountSimple(makePiece());
    expect(svg.querySelector('line[data-role="grain"]')).toBeNull();
  });

  it('全 5 层同时存在时，flipGroup 内含 rough + net + 1 internal + 1 notch + 1 grain', () => {
    const piece = makePiece({
      net_polygon: [
        [20, 30],
        [100, 30],
        [100, 90],
        [20, 90],
      ],
      internal_lines: [
        [
          [50, 30],
          [50, 90],
        ],
      ],
      notches: [[110, 60, 1, 0]],
      grain_line: [10, 60, 110, 60],
    });
    const svg = mountSimple(piece);
    const flip = svg.querySelector('g[data-role="flip"]')!;
    expect(flip.querySelectorAll('polygon[data-role="rough"]').length).toBe(1);
    expect(flip.querySelectorAll('polygon[data-role="net"]').length).toBe(1);
    expect(flip.querySelectorAll('polyline[data-role="internal"]').length).toBe(1);
    expect(flip.querySelectorAll('line[data-role="notch"]').length).toBe(1);
    expect(flip.querySelectorAll('line[data-role="grain"]').length).toBe(1);
  });
});
describe('PiecePreviewSVG (US-007) AC#3 坐标系翻转 + g 码文字标注（不镜像）', () => {
  it('翻转组 transform = translate(0 minY+maxY) scale(1 -1)', () => {
    // piece bbox (10,20)-(110,100)：minY+maxY=120
    const svg = mountSimple(makePiece());
    const flip = svg.querySelector('g[data-role="flip"]')!;
    expect(flip.getAttribute('transform')).toBe('translate(0 120) scale(1 -1)');
  });

  it('翻转组 transform 与多片合并 bbox 一致（取并集 minY+maxY）', () => {
    const a = makePiece(); // (10,20)-(110,100)
    const b = makePiece({
      label: 'g02',
      name: 'b',
      polygon: [
        [200, 0],
        [300, 0],
        [300, 50],
        [200, 50],
      ],
    }); // (200,0)-(300,50)
    const svg = mountSimple([a, b]);
    const flip = svg.querySelector('g[data-role="flip"]')!;
    // 合并 bbox: (10,0)-(300,100)；minY+maxY=0+100=100
    expect(flip.getAttribute('transform')).toBe('translate(0 100) scale(1 -1)');
  });

  it('viewBox = bbox + pad（默认 14，整数 r2 截断）', () => {
    const svg = mountSimple(makePiece());
    // bbox (10,20)-(110,100)，w=100+28=128，h=80+28=108
    expect(svg.getAttribute('viewBox')).toBe('-4 6 128 108');
    expect(svg.getAttribute('preserveAspectRatio')).toBe('xMidYMid meet');
  });

  it('pad 自定义：viewBox 按自定义 pad 计算', () => {
    const svg = mountSimple(makePiece(), 5);
    // bbox (10,20)-(110,100)，pad=5：(5,15) 100+10=110, 80+10=90
    expect(svg.getAttribute('viewBox')).toBe('5 15 110 90');
  });

  it('pad 低于 MIN_PAD(4) 被 clamp 到 4', () => {
    const svg = mountSimple(makePiece(), 0);
    // bbox (10,20)-(110,100)，pad=clamp(0,4)=4：(6,16) 100+8=108, 80+8=88
    expect(svg.getAttribute('viewBox')).toBe('6 16 108 88');
  });

  it('g 码文字标注在翻转组外（svg 直接子节点，非 flipGroup 内）', () => {
    const svg = mountSimple(makePiece({ label: 'g03' }));
    const text = svg.querySelector('text[data-role="label"]') as SVGTextElement | null;
    expect(text).not.toBeNull();
    // 直接 child of svg，不在 flipGroup 内
    expect(text!.parentNode).toBe(svg);
    expect(text!.textContent).toBe('g03');
  });

  it('g 码标注用屏幕坐标（minX, minY - LABEL_Y_OFFSET）', () => {
    // piece bbox (10,20)-(110,100)；minX=10, minY=20, offset=3 → baseline y=17
    const svg = mountSimple(makePiece({ label: 'g01' }));
    const text = svg.querySelector('text[data-role="label"]')!;
    expect(text.getAttribute('x')).toBe('10');
    expect(text.getAttribute('y')).toBe('17');
    expect(text.getAttribute('dominant-baseline')).toBe('alphabetic');
    expect(text.getAttribute('text-anchor')).toBe('start');
    expect(text.getAttribute('font-size')).toBe('11');
  });

  it('label 字段为空字符串时不渲染标注', () => {
    const svg = mountSimple(makePiece({ label: '' }));
    expect(svg.querySelector('text[data-role="label"]')).toBeNull();
  });

  it('多片同框：每个 piece 各自的 g 码标注独立渲染（无镜像，各自 bbox 锚点）', () => {
    const a = makePiece({ label: 'g01' }); // bbox (10,20)-(110,100) → 文字在 (10,17)
    const b = makePiece({
      label: 'g02',
      name: 'b',
      polygon: [
        [200, 0],
        [300, 0],
        [300, 50],
        [200, 50],
      ],
    }); // bbox (200,0)-(300,50) → 文字在 (200,-3)
    const svg = mountSimple([a, b]);
    const texts = svg.querySelectorAll('text[data-role="label"]');
    expect(texts.length).toBe(2);
    const labels = Array.from(texts).map((t) => t.textContent);
    expect(labels).toContain('g01');
    expect(labels).toContain('g02');
    // B 的 baseline y = 0 - 3 = -3
    const textB = Array.from(texts).find((t) => t.textContent === 'g02')!;
    expect(textB.getAttribute('x')).toBe('200');
    expect(textB.getAttribute('y')).toBe('-3');
  });
});
describe('PiecePreviewSVG (US-007) AC#4 单片 / 多片 / 空片容错', () => {
  it('单片：flipGroup 含 1 rough + 1 label', () => {
    const svg = mountSimple(makePiece());
    expect(svg.querySelectorAll('polygon[data-role="rough"]').length).toBe(1);
    expect(svg.querySelectorAll('text[data-role="label"]').length).toBe(1);
  });

  it('多片：flipGroup 内 rough 数 = pieces.length；标注数 = pieces.length', () => {
    const pieces: ParsedPiece[] = [
      makePiece({ label: 'g01' }),
      makePiece({
        label: 'g02',
        name: 'b',
        polygon: [
          [200, 0],
          [300, 0],
          [300, 50],
          [200, 50],
        ],
      }),
      makePiece({
        label: 'g03',
        name: 'c',
        polygon: [
          [10, 200],
          [110, 200],
          [110, 280],
          [10, 280],
        ],
      }),
    ];
    const svg = mountSimple(pieces);
    expect(svg.querySelectorAll('polygon[data-role="rough"]').length).toBe(3);
    expect(svg.querySelectorAll('text[data-role="label"]').length).toBe(3);
  });

  it('空片（无 polygon）：svg 清空后啥都不画（无 viewBox / 无 flipGroup）', () => {
    const empty: ParsedPiece = {
      label: 'g01',
      name: '空',
      polygon: [],
      internal_lines: [],
      notches: [],
      net_polygon: [],
      grain_line: null,
    };
    const svg = mountSimple(empty);
    expect(svg.childNodes.length).toBe(0);
    expect(svg.getAttribute('viewBox')).toBeNull();
    expect(svg.querySelector('g[data-role="flip"]')).toBeNull();
  });

  it('polygon < 3 顶点跳过 rough；其他层照常渲染', () => {
    const piece: ParsedPiece = {
      label: 'g01',
      name: '退化',
      polygon: [
        [10, 20],
        [110, 20],
      ],
      internal_lines: [],
      notches: [],
      net_polygon: [],
      grain_line: [0, 0, 100, 0],
    };
    const svg = mountSimple(piece);
    // polygon.length=2 < 3 → 不画 rough；grain_line 照常
    expect(svg.querySelectorAll('polygon[data-role="rough"]').length).toBe(0);
    expect(svg.querySelectorAll('line[data-role="grain"]').length).toBe(1);
  });
});

describe('PiecePreviewSVG (US-007) AC#5 切 piece 整组重建', () => {
  it('切换 piece：旧 flipGroup 子节点清空 + 新 piece 节点写入', () => {
    const ref = mountProbe(makePiece({ label: 'g01' }));
    const svgBefore = ref.current!;
    const roughBefore = svgBefore.querySelector('polygon[data-role="rough"]')!;
    expect(roughBefore.getAttribute('points')).toBe('10,20 110,20 110,100 10,100');

    // 切到完全不同位置的 piece
    act(() => {
      root!.render(
        <StrictMode>
          <div
            ref={(el) => {
              ref.current = el?.querySelector('svg') ?? null;
            }}
          >
            <PiecePreviewSVG
              piece={makePiece({
                label: 'g02',
                name: 'b',
                polygon: [
                  [200, 0],
                  [300, 0],
                  [300, 50],
                  [200, 50],
                ],
              })}
            />
          </div>,
        </StrictMode>,
      );
    });

    const svgAfter = ref.current!;
    // 只有一个 flipGroup（不残留）
    expect(svgAfter.querySelectorAll('g[data-role="flip"]').length).toBe(1);
    const roughAfter = svgAfter.querySelector('polygon[data-role="rough"]')!;
    expect(roughAfter.getAttribute('points')).toBe('200,0 300,0 300,50 200,50');
    // 新 viewBox 反映新 bbox（pad=14）：(200,0)-(300,50) → (186,-14) 128 78
    expect(svgAfter.getAttribute('viewBox')).toBe('186 -14 128 78');
  });

  it('切到空片：旧内容清空，无 viewBox', () => {
    const ref = mountProbe(makePiece());
    expect(ref.current!.childNodes.length).toBeGreaterThan(0);

    const empty: ParsedPiece = {
      label: '',
      name: '',
      polygon: [],
      internal_lines: [],
      notches: [],
      net_polygon: [],
      grain_line: null,
    };
    act(() => {
      root!.render(
        <StrictMode>
          <div
            ref={(el) => {
              ref.current = el?.querySelector('svg') ?? null;
            }}
          >
            <PiecePreviewSVG piece={empty} />
          </div>,
        </StrictMode>,
      );
    });

    const svg = ref.current!;
    expect(svg.childNodes.length).toBe(0);
    expect(svg.getAttribute('viewBox')).toBeNull();
  });

  it('pad 变化触发 viewBox 重算（dep 含 pad）', () => {
    const ref = mountProbe(makePiece(), 10);
    expect(ref.current!.getAttribute('viewBox')).toBe('0 10 120 100');

    act(() => {
      root!.render(
        <StrictMode>
          <div
            ref={(el) => {
              ref.current = el?.querySelector('svg') ?? null;
            }}
          >
            <PiecePreviewSVG piece={makePiece()} pad={20} />
          </div>,
        </StrictMode>,
      );
    });

    expect(ref.current!.getAttribute('viewBox')).toBe('-10 0 140 120');
  });
});

describe('PiecePreviewSVG (US-018) compact 模式', () => {
  it('compact=true：不渲染 g 码 label text（即使 piece.label 非空）', () => {
    let svg: SVGSVGElement | null = null;
    act(() => {
      root!.render(
        <div
          ref={(el) => {
            svg = el?.querySelector('svg') ?? null;
          }}
        >
          <PiecePreviewSVG piece={makePiece({ label: 'g01' })} compact />
        </div>,
      );
    });
    expect(svg).not.toBeNull();
    expect(svg!.querySelector('polygon[data-role="rough"]')).not.toBeNull();
    // 关 g 码标注（即使 label='g01'）
    expect(svg!.querySelector('text[data-role="label"]')).toBeNull();
  });

  it('compact=true：pad 默认 COMPACT_PAD(2)，viewBox 紧贴几何', () => {
    // bbox (10,20)-(110,100)，compact pad=2：viewBox=(8,18) w=104 h=84
    let svg: SVGSVGElement | null = null;
    act(() => {
      root!.render(
        <div
          ref={(el) => {
            svg = el?.querySelector('svg') ?? null;
          }}
        >
          <PiecePreviewSVG piece={makePiece()} compact />
        </div>,
      );
    });
    expect(svg!.getAttribute('viewBox')).toBe('8 18 104 84');
  });

  it('compact=true：layer-aware 渲染不变（数据带 net/internal/notch/grain 仍渲染）', () => {
    const piece = makePiece({
      net_polygon: [
        [20, 30],
        [100, 30],
        [100, 90],
        [20, 90],
      ],
      internal_lines: [
        [
          [50, 30],
          [50, 90],
        ],
      ],
      notches: [[110, 60, 1, 0]],
      grain_line: [10, 60, 110, 60],
    });
    let svg: SVGSVGElement | null = null;
    act(() => {
      root!.render(
        <div
          ref={(el) => {
            svg = el?.querySelector('svg') ?? null;
          }}
        >
          <PiecePreviewSVG piece={piece} compact />
        </div>,
      );
    });
    const flip = svg!.querySelector('g[data-role="flip"]')!;
    expect(flip.querySelectorAll('polygon[data-role="rough"]').length).toBe(1);
    expect(flip.querySelectorAll('polygon[data-role="net"]').length).toBe(1);
    expect(flip.querySelectorAll('polyline[data-role="internal"]').length).toBe(1);
    expect(flip.querySelectorAll('line[data-role="notch"]').length).toBe(1);
    expect(flip.querySelectorAll('line[data-role="grain"]').length).toBe(1);
    // compact 模式仍不渲染 label
    expect(svg!.querySelectorAll('text[data-role="label"]').length).toBe(0);
  });

  it('compact=false（默认）：g 码标注正常渲染（向后兼容）', () => {
    let svg: SVGSVGElement | null = null;
    act(() => {
      root!.render(
        <div
          ref={(el) => {
            svg = el?.querySelector('svg') ?? null;
          }}
        >
          <PiecePreviewSVG piece={makePiece({ label: 'g01' })} />
        </div>,
      );
    });
    expect(svg!.querySelector('text[data-role="label"]')).not.toBeNull();
    expect(svg!.querySelector('text[data-role="label"]')!.textContent).toBe('g01');
  });

  it('compact=true + 显式 pad：使用显式 pad（COMPACT_PAD 仅作未指定时默认）', () => {
    // 显式 pad=5 优先于 compact COMPACT_PAD(2)
    let svg: SVGSVGElement | null = null;
    act(() => {
      root!.render(
        <div
          ref={(el) => {
            svg = el?.querySelector('svg') ?? null;
          }}
        >
          <PiecePreviewSVG piece={makePiece()} compact pad={5} />
        </div>,
      );
    });
    // bbox (10,20)-(110,100)，pad=5：viewBox=(5,15) w=110 h=90
    expect(svg!.getAttribute('viewBox')).toBe('5 15 110 90');
  });
});

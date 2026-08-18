// 矩阵化重构 US-005 previewTour 单测（2026-08-16 转置回归）：
//   1. 5 步 id 序列稳定（upload/parsed/set-qty/committed/goto-nesting）+ tabId
//   2. parsed/set-qty 锚点迁矩阵（qty-matrix / qty-rowhead），无旧 size-tabs/piece-card-head 残留
//   3. TOUR_VERSION bump（步骤内容重大变更 → 老用户 seen 被 tourStore init 清空重看）
//   4. parsed/set-qty 文案描述矩阵操作（行头切码 / 格内编辑 / 整列设值 / 特例高亮 /
//      配对 ×2 口径；×2 徽章已随 2026-08 行头简化拆除，文案不再指引）
//   5. 锚点在已渲染的 QtyMatrix 上 querySelector 命中（行头切码 / 格内编辑指引可定位）
//
// 设计：测 1~4 直接读 previewTour/TOUR_VERSION 模块常量（纯断言，无需 DOM）；
//      测 5 挂 QtyMatrix（useUploadStore.setState 注入 doc，与 QtyMatrix.test.tsx 同 fixture 模式）。

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { previewTour } from '../previewTour';
import { TOUR_VERSION } from '../index';
import { QtyMatrix } from '../../../components/preview/QtyMatrix';
import { useUploadStore } from '../../../store/uploadStore';
import type { ParsedDoc, ParsedPiece } from '../../../types/parsed';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  useUploadStore.getState().reset();
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
  useUploadStore.getState().reset();
});

/** 构造一片：方框 100x80（与 QtyMatrix.test.tsx makePiece 同模式）。 */
function makePiece(overrides: Partial<ParsedPiece> = {}): ParsedPiece {
  return {
    label: 'g01',
    name: '前片',
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

/** 两码 doc：28(A+B) + null(C)，覆盖 null 码「通用」行（转置后码在行）。 */
function makeDoc(): ParsedDoc {
  return {
    doc_id: 'deadbeef',
    filename: 'M1787.dxf',
    sizes: [
      { size: 28, pieces: [makePiece({ label: 'g01' }), makePiece({ label: 'g02', name: '后片' })] },
      { size: null, pieces: [makePiece({ label: 'g03', name: '腰通用' })] },
    ],
  };
}

describe('previewTour 步骤结构（矩阵化重构 US-005）', () => {
  it('1. 共 5 步且 id 序列符合定义（upload/parsed/set-qty/committed/goto-nesting）', () => {
    expect(previewTour.tabId).toBe('preview');
    expect(previewTour.steps).toHaveLength(5);
    expect(previewTour.steps.map((s) => s.id)).toEqual([
      'upload',
      'parsed',
      'set-qty',
      'committed',
      'goto-nesting',
    ]);
  });

  it('2. parsed/set-qty 锚点迁矩阵，旧 size-tabs/piece-card-head 选择器零残留', () => {
    const parsed = previewTour.steps.find((s) => s.id === 'parsed')!;
    const setQty = previewTour.steps.find((s) => s.id === 'set-qty')!;
    expect(parsed.selector).toBe('[data-tour="qty-matrix"]');
    expect(setQty.selector).toBe('[data-tour="qty-rowhead"]');
    // 旧锚点（SizeTabs / ParsedPiecesView 卡片头）零残留
    const allSelectors = previewTour.steps.map((s) => s.selector).join(' ');
    expect(allSelectors).not.toContain('size-tabs');
    expect(allSelectors).not.toContain('piece-card-head');
    // 其余三步锚点不动（upload/committed/goto-nesting）
    expect(previewTour.steps[0].selector).toBe('[data-tour="drop-zone"]');
    expect(previewTour.steps[3].selector).toBe('[data-testid="commit-status"]');
    expect(previewTour.steps[4].selector).toBe('[data-tour="tab-nesting"]');
  });

  it('3. TOUR_VERSION bump 为 6（步骤内容重大变更强制老用户重看）', () => {
    // '1'（US-030 首次落地）→ '2'（矩阵化重构 US-005 锚点迁移）
    // → '3'（图形预览区拆除：parsed 步旧文案指引的「下方图形预览」已不存在）
    // → '4'（矩阵行头简化：set-qty 步旧文案指引的「行头填充 / ×2 徽章」已拆除）
    // → '5'（行级整行设值回归 + 整表重置拆除：set-qty 步重新指引行级批量设值）
    // → '6'（数量矩阵行列转置：整行设值 → 整列设值，列头/行头方位互换）
    expect(TOUR_VERSION).toBe('6');
    // 版本号策略不变量：与旧版本不一致时 tourStore init 清 seen（行为级断言见 tourStore.test.ts）
  });

  it('4. parsed/set-qty 文案描述矩阵操作（转置后：列=裁片，行=尺码）', () => {
    const parsed = previewTour.steps.find((s) => s.id === 'parsed')!;
    const setQty = previewTour.steps.find((s) => s.id === 'set-qty')!;
    // parsed：矩阵浏览 + 列头缩略图放大（图形预览区已拆除，不再指引「下方图形预览」）
    expect(parsed.body).toContain('矩阵');
    expect(parsed.body).toContain('列头');
    expect(parsed.body).toContain('缩略图');
    expect(parsed.body).not.toContain('图形预览');
    // set-qty：格内直接编辑 / 整列设值（2026-08-16 转置）/ 特例高亮 / 配对 ×2 口径；
    // ×2 徽章已拆（2026-08 行头简化），文案零残留
    expect(setQty.body).toContain('格子');
    expect(setQty.body).toContain('整列设值');
    expect(setQty.body).not.toContain('整行设值');
    expect(setQty.body).toContain('高亮');
    expect(setQty.body).toContain('×2');
    expect(setQty.body).not.toContain('徽章');
  });
});

describe('previewTour 锚点渲染命中（矩阵化重构 US-005）', () => {
  it('5. qty-matrix / qty-rowhead 锚点在已渲染的 QtyMatrix 上 querySelector 命中', () => {
    act(() => {
      useUploadStore.setState({
        status: 'done',
        doc: makeDoc(),
        activeSize: 28,
      });
    });
    act(() => {
      root!.render(
        <StrictMode>
          <QtyMatrix />
        </StrictMode>,
      );
    });

    // 矩阵根容器（parsed 步锚点）
    expect(container!.querySelector('[data-tour="qty-matrix"]')).not.toBeNull();
    // 首个行头（set-qty 步锚点；querySelector 命中首行）
    const rowhead = container!.querySelector('[data-tour="qty-rowhead"]');
    expect(rowhead).not.toBeNull();
    expect(rowhead!.classList.contains('qty-rowhead')).toBe(true);
  });
});

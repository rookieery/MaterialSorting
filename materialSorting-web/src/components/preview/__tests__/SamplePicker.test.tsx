// SamplePicker integration tests（2026-09-16 样例区块）。
//
// AC 覆盖：
// 1. mount GET /api/samples → select 填充全部样例，默认选中第一个；
// 2. 切换选择 → 点「应用」→ GET /api/samples/file?name=<encodeURIComponent> →
//    取回字节包 File（名 = 样例名）喂 useParseDxf.upload（复用上传链路，不另起炉灶）；
// 3. 取文件 404 → 红字「应用失败：<后端 error>」，upload 不被调；
// 4. 清单加载失败 → 红字「样例列表加载失败：…」+ select 空占位 + 应用禁用；
// 5. 上传中（store status='uploading'）→ select / 应用禁用（与面板按钮同防护口径）。
//
// Mirrors UploadPanel.test.tsx pattern: render into container, dispatch DOM events.
// useParseDxf mock 掉（样例组件契约止于「把 File 交给 upload」；parse/commit 链路
// 在 useParseDxf.test / UploadPanel.test 各自覆盖）。

// 注意 mock 路径相对**测试文件**（__tests__/ 下）解析：../../../hooks 才是 src/hooks。
const { uploadMock } = vi.hoisted(() => ({ uploadMock: vi.fn() }));
vi.mock('../../../hooks/useParseDxf', () => ({
  useParseDxf: () => ({ upload: uploadMock }),
}));

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { SamplePicker } from '../SamplePicker';
import { markSessionProbedForTest } from '../../../lib/api';
import { useUploadStore } from '../../../store/uploadStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

/** 样例清单（两个：ASCII + 保留字符名，验证 encodeURIComponent 往返）。 */
const SAMPLES = [
  { name: 'a.dxf', size_bytes: 3 },
  { name: 'b#中文（1）.dxf', size_bytes: 5 },
];
const FILE_BYTES = new Uint8Array([1, 2, 3, 4, 5]).buffer;

beforeEach(() => {
  markSessionProbedForTest();
  useUploadStore.getState().reset();
  uploadMock.mockReset().mockResolvedValue(undefined);
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
  vi.restoreAllMocks();
});

function renderPicker(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <SamplePicker />
      </StrictMode>,
    );
  });
  return container!;
}

function makeJsonResponse(json: unknown, ok = true, status = 200, statusText = 'OK'): Response {
  return {
    ok,
    status,
    statusText,
    json: vi.fn(async () => json),
  } as unknown as Response;
}

/** 文件端点 Response：样例组件读 res.blob()（列表端点读 res.json()）。 */
function makeFileResponse(buf: ArrayBuffer): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    blob: vi.fn(async () => new Blob([buf], { type: 'application/dxf' })),
  } as unknown as Response;
}

/** 统一 fetch stub：/api/samples → 清单 JSON；/api/samples/file → 文件字节。 */
function stubFetch(overrides?: {
  list?: Response | Error;
  file?: Response | Error;
}): ReturnType<typeof vi.spyOn> {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url.startsWith('/api/samples/file')) {
      if (overrides?.file instanceof Error) throw overrides.file;
      return overrides?.file ?? makeFileResponse(FILE_BYTES);
    }
    if (url === '/api/samples') {
      if (overrides?.list instanceof Error) throw overrides.list;
      return overrides?.list ?? makeJsonResponse({ samples: SAMPLES });
    }
    return makeJsonResponse({});
  }) as unknown as ReturnType<typeof vi.spyOn>;
}

/** flush 异步 effect（mount 拉清单 / 应用链）后重渲染。 */
async function flush(): Promise<void> {
  await act(async () => {});
}

describe('SamplePicker', () => {
  it('mount 拉清单并默认选中第一个样例', async () => {
    const fetchSpy = stubFetch();
    renderPicker();
    await flush();
    const select = container!.querySelector('select.sample-select') as HTMLSelectElement;
    expect(select).not.toBeNull();
    expect(select.value).toBe('a.dxf');
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toEqual(['a.dxf', 'b#中文（1）.dxf']);
    // 仅清单请求（StrictMode 双挂载是同一 URL 的幂等 GET，此处不锁次数）
    expect(fetchSpy.mock.calls.every((c) => String(c[0]).startsWith('/api/samples'))).toBe(true);
    expect(container!.querySelector('[data-testid="sample-error"]')).toBeNull();
  });

  it('应用 = 取文件字节包 File 喂 upload（选择名透传 + encodeURIComponent）', async () => {
    const fetchSpy = stubFetch();
    renderPicker();
    await flush();
    // 切到第二个样例（保留字符名走编码）
    const select = container!.querySelector('select.sample-select') as HTMLSelectElement;
    await act(async () => {
      select.value = 'b#中文（1）.dxf';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const btn = container!.querySelector('[data-testid="sample-apply"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    await flush();
    const fileUrl = fetchSpy.mock.calls.map((c) => String(c[0])).find((u) => u.startsWith('/api/samples/file'));
    expect(fileUrl).toBe(`/api/samples/file?name=${encodeURIComponent('b#中文（1）.dxf')}`);
    expect(uploadMock).toHaveBeenCalledTimes(1);
    const file = uploadMock.mock.calls[0][0] as File;
    expect(file.name).toBe('b#中文（1）.dxf');
    expect(file.size).toBe(5);
    expect(container!.querySelector('[data-testid="sample-error"]')).toBeNull();
  });

  it('取文件 404 → 红字「应用失败」，upload 不被调', async () => {
    stubFetch({ file: makeJsonResponse({ error: '样例文件不存在：x' }, false, 404, 'Not Found') });
    renderPicker();
    await flush();
    const btn = container!.querySelector('[data-testid="sample-apply"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    await flush();
    expect(uploadMock).not.toHaveBeenCalled();
    const err = container!.querySelector('[data-testid="sample-error"]');
    expect(err?.textContent).toContain('应用失败');
    expect(err?.textContent).toContain('样例文件不存在：x');
  });

  it('清单加载失败 → 红字提示 + 空占位 + 应用禁用', async () => {
    stubFetch({ list: new Error('backend down') });
    renderPicker();
    await flush();
    const err = container!.querySelector('[data-testid="sample-error"]');
    expect(err?.textContent).toContain('样例列表加载失败');
    const select = container!.querySelector('select.sample-select') as HTMLSelectElement;
    expect(select.value).toBe('');
    const btn = container!.querySelector('[data-testid="sample-apply"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(uploadMock).not.toHaveBeenCalled();
  });

  it('上传中（store status=uploading）禁用 select 与应用按钮', async () => {
    stubFetch();
    renderPicker();
    await flush();
    act(() => {
      useUploadStore.setState({ status: 'uploading' });
    });
    const select = container!.querySelector('select.sample-select') as HTMLSelectElement;
    const btn = container!.querySelector('[data-testid="sample-apply"]') as HTMLButtonElement;
    expect(select.disabled).toBe(true);
    expect(btn.disabled).toBe(true);
  });
});

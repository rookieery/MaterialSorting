// US-006 UploadPanel integration tests.
//
// AC#1 click button / drop-zone triggers hidden <input type=file accept=".dxf"> click
// AC#1 panel-wide DnD: dragenter/dragover/dragleave/drop on root <aside>
// AC#2 client-side validation rejects non-.dxf / multi-file / oversize WITHOUT fetch
// AC#2 single .dxf passes validation -> upload() called -> fetch fires
// AC#3 status=uploading shows loading + disables button
// AC#3 status=done shows filename + summary
// AC#3 status=error shows red error from uploadStore.error
// AC#3 localError (client reject) takes priority over store.error
//
// Mirrors ControlPanel.test.tsx pattern: render into container, dispatch DOM events.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { UploadPanel } from '../UploadPanel';
import { useUploadStore } from '../../../store/uploadStore';
import { useUiStore } from '../../../store/uiStore';
import type { ParsedDoc } from '../../../types/parsed';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  useUploadStore.getState().reset();
  // US-021：commit 副作用会写 uiStore（setNestingEnabled+setTab），reset 防跨测试污染。
  useUiStore.getState().setNestingEnabled(false);
  useUiStore.getState().setTab('preview');
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
  // US-021：commit 异步 resolve 可能在此触发 setTab，reset 防下一个测试污染。
  useUiStore.getState().setNestingEnabled(false);
  useUiStore.getState().setTab('preview');
  vi.restoreAllMocks();
});

function renderPanel(): HTMLElement {
  act(() => {
    root!.render(
      <StrictMode>
        <UploadPanel />
      </StrictMode>,
    );
  });
  return container!;
}

function stubInputClick(): ReturnType<typeof vi.spyOn> {
  return vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {});
}

function makeFile(name: string, size = 100): File {
  const buf = new Uint8Array(size);
  return new File([buf], name, { type: 'application/octet-stream' });
}

// jsdom lacks DragEvent / DataTransfer — polyfill minimal stubs for DnD tests.
// Stub matches the surface our component actually reads: event.dataTransfer.files / .items.add.
interface DataTransferStub {
  files: File[];
  items: { add: (file: File) => void };
  dropEffect: string;
}
function makeDataTransfer(files: File[] = []): DataTransferStub {
  return {
    files,
    items: { add: (f: File) => files.push(f) },
    dropEffect: 'none',
  };
}

/** Construct a DragEvent — jsdom lacks the ctor, so build a native Event and attach dataTransfer. */
function makeDropEvent(type: string, files: File[]): DragEvent {
  const ev = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
  Object.defineProperty(ev, 'dataTransfer', {
    value: makeDataTransfer(files),
    configurable: true,
  });
  // preventDefault is invoked by the component — native Event has it, but be defensive
  return ev;
}

function makeDragEvent(type: string): DragEvent {
  const ev = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
  // dragenter/over/leave handlers read dataTransfer?.dropEffect only; null is OK
  Object.defineProperty(ev, 'dataTransfer', {
    value: makeDataTransfer(),
    configurable: true,
  });
  return ev;
}

function makeResponse(json: unknown, ok = true, status = 200, statusText = 'OK'): Response {
  return {
    ok,
    status,
    statusText,
    json: vi.fn(async () => json),
  } as unknown as Response;
}

function makeDoc(sizes: { size: number | null; pieces: unknown[] }[] = [
  { size: 28, pieces: [{}, {}] },
  { size: 30, pieces: [{}] },
]): ParsedDoc {
  return {
    doc_id: 'deadbeef',
    filename: 'M1787.dxf',
    sizes: sizes as ParsedDoc['sizes'],
  };
}

describe('UploadPanel (US-006) structure and AC#1 interactions', () => {
  it('renders .panel.upload-panel + h2 + drop-zone + hidden input + upload-btn', () => {
    const el = renderPanel();
    expect(el.querySelector('aside.panel.upload-panel')).not.toBeNull();
    expect(el.querySelector('h2')).not.toBeNull();
    expect(el.querySelector('.drop-zone')).not.toBeNull();
    const input = el.querySelector<HTMLInputElement>('input[type=file].upload-input-hidden');
    expect(input).not.toBeNull();
    expect(input!.getAttribute('accept')).toBe('.dxf');
    expect(el.querySelector('button.upload-btn')).not.toBeNull();
  });

  it('AC#1 click on drop-zone triggers input.click()', () => {
    const spy = stubInputClick();
    const el = renderPanel();
    act(() => {
      el.querySelector<HTMLElement>('.drop-zone')!.click();
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('AC#1 click on upload-btn triggers input.click()', () => {
    const spy = stubInputClick();
    const el = renderPanel();
    act(() => {
      el.querySelector<HTMLButtonElement>('button.upload-btn')!.click();
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('AC#1 drop-zone keyboard Enter triggers input.click() (a11y)', () => {
    const spy = stubInputClick();
    const el = renderPanel();
    const dz = el.querySelector<HTMLElement>('.drop-zone')!;
    act(() => {
      dz.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('AC#1 drop-zone keyboard Space triggers input.click() (a11y)', () => {
    const spy = stubInputClick();
    const el = renderPanel();
    const dz = el.querySelector<HTMLElement>('.drop-zone')!;
    act(() => {
      dz.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('uploading state: click on drop-zone does NOT trigger input.click()', () => {
    const spy = stubInputClick();
    useUploadStore.setState({ status: 'uploading' });
    const el = renderPanel();
    act(() => {
      el.querySelector<HTMLElement>('.drop-zone')!.click();
    });
    expect(spy).not.toHaveBeenCalled();
  });
});

describe('UploadPanel (US-006) AC#2 client-side validation', () => {
  it('AC#2 non-.dxf suffix -> red error msg, no fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeResponse(makeDoc()));
    const el = renderPanel();
    const input = el.querySelector<HTMLInputElement>('input[type=file]')!;
    const files = [makeFile('notes.txt', 50)];
    Object.defineProperty(input, 'files', { value: files, configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    const errBox = el.querySelector('.upload-status.error');
    expect(errBox).not.toBeNull();
    expect(errBox!.textContent).toContain('.dxf');
  });

  it('AC#2 .DXF uppercase suffix passes (MIME tolerant)', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeResponse(makeDoc()));
    const el = renderPanel();
    const input = el.querySelector<HTMLInputElement>('input[type=file]')!;
    const files = [makeFile('M1787.DXF', 50)];
    Object.defineProperty(input, 'files', { value: files, configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // US-021：解析成功后自动 commit 触发第二次 fetch（POST /api/commit-to-nesting）。
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it('AC#2 drop multiple files -> reject msg, no fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeResponse(makeDoc()));
    const el = renderPanel();
    await act(async () => {
      el.querySelector<HTMLElement>('.upload-panel')!.dispatchEvent(
        makeDropEvent('drop', [makeFile('a.dxf', 50), makeFile('b.dxf', 60)]),
      );
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    const errBox = el.querySelector('.upload-status.error');
    expect(errBox).not.toBeNull();
    expect(errBox!.textContent!.length).toBeGreaterThan(0);
  });

  it('AC#2 file > 20MB -> reject msg, no fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeResponse(makeDoc()));
    const el = renderPanel();
    const oversized = makeFile('big.dxf', 20 * 1024 * 1024 + 1);
    await act(async () => {
      el.querySelector<HTMLElement>('.upload-panel')!.dispatchEvent(
        makeDropEvent('drop', [oversized]),
      );
    });
    expect(fetchSpy).not.toHaveBeenCalled();
    const errBox = el.querySelector('.upload-status.error');
    expect(errBox).not.toBeNull();
    expect(errBox!.textContent).toContain('20MB');
  });

  it('AC#2 single valid .dxf -> triggers fetch POST /api/parse-dxf', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeResponse(makeDoc()));
    const el = renderPanel();
    await act(async () => {
      el.querySelector<HTMLElement>('.upload-panel')!.dispatchEvent(
        makeDropEvent('drop', [makeFile('M1787.dxf', 100)]),
      );
    });
    // US-021：解析成功后自动 commit 触发第二次 fetch（POST /api/commit-to-nesting）。
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/parse-dxf');
  });

  it('AC#2 valid pick clears stale localError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeResponse(makeDoc()));
    const el = renderPanel();
    const input = el.querySelector<HTMLInputElement>('input[type=file]')!;
    Object.defineProperty(input, 'files', { value: [makeFile('bad.txt', 10)], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(el.querySelector('.upload-status.error')).not.toBeNull();
    Object.defineProperty(input, 'files', { value: [makeFile('M1787.dxf', 100)], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(el.querySelector('.upload-status.done')).not.toBeNull();
    expect(el.querySelector('.upload-status.error')).toBeNull();
  });

  it('AC#2 input value reset after change (same file re-pickable)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeResponse(makeDoc()));
    const el = renderPanel();
    const input = el.querySelector<HTMLInputElement>('input[type=file]')!;
    Object.defineProperty(input, 'files', { value: [makeFile('M1787.dxf', 100)], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(input.value).toBe('');
  });
});

describe('UploadPanel (US-006) AC#1 DnD visual feedback', () => {
  it('dragenter adds .dragover class to drop-zone', () => {
    const el = renderPanel();
    const panel = el.querySelector<HTMLElement>('.upload-panel')!;
    act(() => {
      panel.dispatchEvent(makeDragEvent('dragenter'));
    });
    expect(el.querySelector('.drop-zone')!.classList.contains('dragover')).toBe(true);
  });

  it('dragenter x2 then dragleave x1 -> still dragover (counter>0)', () => {
    const el = renderPanel();
    const panel = el.querySelector<HTMLElement>('.upload-panel')!;
    act(() => {
      panel.dispatchEvent(makeDragEvent('dragenter'));
      panel.dispatchEvent(makeDragEvent('dragenter'));
      panel.dispatchEvent(makeDragEvent('dragleave'));
    });
    expect(el.querySelector('.drop-zone')!.classList.contains('dragover')).toBe(true);
  });

  it('dragleave counter=0 removes .dragover', () => {
    const el = renderPanel();
    const panel = el.querySelector<HTMLElement>('.upload-panel')!;
    act(() => {
      panel.dispatchEvent(makeDragEvent('dragenter'));
      panel.dispatchEvent(makeDragEvent('dragleave'));
    });
    expect(el.querySelector('.drop-zone')!.classList.contains('dragover')).toBe(false);
  });

  it('drop removes .dragover class', async () => {
    const el = renderPanel();
    const panel = el.querySelector<HTMLElement>('.upload-panel')!;
    act(() => {
      panel.dispatchEvent(makeDragEvent('dragenter'));
    });
    expect(el.querySelector('.drop-zone')!.classList.contains('dragover')).toBe(true);
    await act(async () => {
      panel.dispatchEvent(makeDropEvent('drop', [makeFile('M1787.dxf', 100)]));
    });
    expect(el.querySelector('.drop-zone')!.classList.contains('dragover')).toBe(false);
  });

  it('drop-zone text switches to release hint on dragOver', () => {
    const el = renderPanel();
    const panel = el.querySelector<HTMLElement>('.upload-panel')!;
    const initial = el.querySelector('.drop-zone-text')!.textContent;
    act(() => {
      panel.dispatchEvent(makeDragEvent('dragenter'));
    });
    const after = el.querySelector('.drop-zone-text')!.textContent;
    expect(after).not.toBe(initial);
  });
});

describe('UploadPanel (US-006) AC#3 status-driven UI', () => {
  it('AC#3 status=uploading shows loading + upload-btn disabled', () => {
    useUploadStore.setState({ status: 'uploading' });
    const el = renderPanel();
    const status = el.querySelector('.upload-status.loading');
    expect(status).not.toBeNull();
    const btn = el.querySelector<HTMLButtonElement>('button.upload-btn');
    expect(btn!.disabled).toBe(true);
  });

  it('AC#3 status=done shows filename + summary', () => {
    const doc = makeDoc([
      { size: 28, pieces: [{}, {}, {}] },
      { size: 30, pieces: [{}] },
      { size: null, pieces: [{}, {}] },
    ]);
    useUploadStore.setState({ status: 'done', doc, activeSize: 28 });
    const el = renderPanel();
    const done = el.querySelector('.upload-status.done');
    expect(done).not.toBeNull();
    expect(done!.querySelector('.upload-filename')!.textContent).toBe('M1787.dxf');
    const summary = done!.querySelector('.upload-summary')!.textContent || '';
    expect(summary).toContain('3');
    expect(summary).toContain('6');
  });

  it('AC#3 status=error shows store.error red text', () => {
    useUploadStore.setState({ status: 'error', error: 'backend boom' });
    const el = renderPanel();
    const errBox = el.querySelector('.upload-status.error');
    expect(errBox).not.toBeNull();
    expect(errBox!.textContent).toContain('backend boom');
  });

  it('AC#3 idle renders no status block', () => {
    const el = renderPanel();
    expect(el.querySelector('.upload-status')).toBeNull();
  });

  it('AC#3 localError takes priority over store.error', () => {
    useUploadStore.setState({ status: 'error', error: 'backend err' });
    const el = renderPanel();
    const input = el.querySelector<HTMLInputElement>('input[type=file]')!;
    Object.defineProperty(input, 'files', { value: [makeFile('bad.txt', 10)], configurable: true });
    act(() => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const errBox = el.querySelector('.upload-status.error');
    expect(errBox!.textContent).toContain('.dxf');
    expect(errBox!.textContent).not.toContain('backend err');
  });

  it('AC#3 upload success -> state transitions to done (e2e)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(makeResponse(makeDoc()));
    const el = renderPanel();
    const input = el.querySelector<HTMLInputElement>('input[type=file]')!;
    Object.defineProperty(input, 'files', { value: [makeFile('M1787.dxf', 100)], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const done = el.querySelector('.upload-status.done');
    expect(done).not.toBeNull();
    expect(done!.querySelector('.upload-filename')!.textContent).toBe('M1787.dxf');
  });

  it('AC#3 upload failure (HTTP 400) -> state transitions to error with backend msg', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      makeResponse({ error: 'only .dxf supported' }, false, 400, 'Bad Request'),
    );
    const el = renderPanel();
    const input = el.querySelector<HTMLInputElement>('input[type=file]')!;
    Object.defineProperty(input, 'files', { value: [makeFile('M1787.dxf', 100)], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const errBox = el.querySelector('.upload-status.error');
    expect(errBox).not.toBeNull();
    expect(errBox!.textContent).toContain('only .dxf supported');
  });
});

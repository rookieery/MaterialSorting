// US-007 download.ts 单测：
//   AC#4 Content-Disposition 解析：
//     - filename*=UTF-8''xxx（RFC 5987）→ decodeURIComponent（中文正确解出）
//     - filename="xxx" / filename=xxx（ASCII fallback）
//     - 兜底 nesting.<fmt>
//     - malformed URI sequence → 落 fallback
//   AC#5 downloadBlob：<a download> + revokeObjectURL 触发

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { downloadBlob, parseContentDisposition } from '../download';

// jsdom 提供 document.createElement('a') + click；URL.createObjectURL / revokeObjectURL 需 stub。
let urlCounter = 0;

beforeEach(() => {
  urlCounter = 0;
  vi.stubGlobal('URL', {
    createObjectURL: vi.fn(() => {
      const url = `blob:fake://${++urlCounter}`;
      return url;
    }),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parseContentDisposition (US-007 AC#4)', () => {
  it('RFC 5987 filename*=UTF-8\'\'xxx → decodeURIComponent（中文，AC#5）', () => {
    // 服务端 server.py: `fname_cn = 排料_码28-30-32_88.42pct_seed0.png`
    // 经 urllib.parse.quote → %E6%8E%92%E6%96%99_%E7%A0%8128-30-32_88.42pct_seed0.png
    const cd =
      'attachment; filename="nesting_28-30-32_88.42pct_seed0.png"; filename*=UTF-8\'\'%E6%8E%92%E6%96%99_%E7%A0%8128-30-32_88.42pct_seed0.png';
    expect(parseContentDisposition(cd, 'png')).toBe('排料_码28-30-32_88.42pct_seed0.png');
  });

  it('RFC 5987 ASCII 字符串 → 原样返回', () => {
    const cd = "attachment; filename*=UTF-8''nesting_28-30-32_88.42pct_seed0.png";
    expect(parseContentDisposition(cd, 'png')).toBe('nesting_28-30-32_88.42pct_seed0.png');
  });

  it('filename="xxx" 引号 → 返回 xxx（ASCII fallback）', () => {
    const cd = 'attachment; filename="nesting_28-30-32_88.42pct_seed0.png"';
    expect(parseContentDisposition(cd, 'png')).toBe('nesting_28-30-32_88.42pct_seed0.png');
  });

  it('filename=xxx 无引号 → 返回 xxx', () => {
    const cd = 'attachment; filename=nesting_28-30-32_88.42pct_seed0.png';
    expect(parseContentDisposition(cd, 'png')).toBe('nesting_28-30-32_88.42pct_seed0.png');
  });

  it('空 Content-Disposition → nesting.<fmt> 兜底', () => {
    expect(parseContentDisposition('', 'png')).toBe('nesting.png');
    expect(parseContentDisposition('', 'dxf')).toBe('nesting.dxf');
    // US-034：PLT 兜底（与 png/dxf 同语义，喂 WT V8.8 / LIKE 绘图仪）
    expect(parseContentDisposition('', 'plt')).toBe('nesting.plt');
    // 2026-08-31 毛版：变体后缀去掉还原 .plt 扩展名（仅 CD 头缺失的极端兜底路径）
    expect(parseContentDisposition('', 'plt-clean')).toBe('nesting.plt');
    // 状态文件 US-003：'state' 扩展名映射 .msn（走独立 /api/state-save 的唯一例外格式）
    expect(parseContentDisposition('', 'state')).toBe('nesting.msn');
  });

  it('无 filename 字段 → nesting.<fmt> 兜底', () => {
    const cd = 'attachment; size=12345';
    expect(parseContentDisposition(cd, 'png')).toBe('nesting.png');
  });

  it('malformed URI sequence（filename* 含非法百分号）→ 落 filename= fallback', () => {
    // %E6%8 单字节不完整 → decodeURIComponent 抛 URIError
    const cd = "attachment; filename=\"fallback.png\"; filename*=UTF-8''%E6%8";
    expect(parseContentDisposition(cd, 'png')).toBe('fallback.png');
  });

  it('filename* 后无内容 → 落 filename= / nesting.<fmt>', () => {
    const cd = "attachment; filename*=UTF-8''";
    expect(parseContentDisposition(cd, 'png')).toBe('nesting.png');
  });

  it('filename* 优先于 filename（同时存在时取 filename*）', () => {
    const cd = "attachment; filename=\"ascii.png\"; filename*=UTF-8''%E6%8E%92%E6%96%99.png";
    expect(parseContentDisposition(cd, 'png')).toBe('排料.png');
  });

  it('正则大小写不敏感（FILENAME*= 也匹配）', () => {
    const cd = "attachment; FILENAME*=UTF-8''ascii.png";
    expect(parseContentDisposition(cd, 'png')).toBe('ascii.png');
  });
});

// 状态文件：2026-09-11 US-003 曾把 state 追加进 EXPORT_FORMATS（排 PNG 后）；
// 2026-09-12 入口改判移出下拉（保存入口独立为 SaveStateControls），ExportFmt
// 联合类型保留 'state' —— RFC5987 中文文件名解析复用（后端 /api/state-save
// 命名 <母版名去 .dxf>_状态_<ts>.msn）。
describe('EXPORT_FORMATS / DEFAULT_EXPORT_FMT（状态文件）', () => {
  it('EXPORT_FORMATS 不含 state（2026-09-12 移出下拉；纯生产交付格式族 4 项）', async () => {
    const { EXPORT_FORMATS } = await import('../download');
    expect(EXPORT_FORMATS.map((f) => f.value)).toEqual(['dxf', 'plt', 'plt-clean', 'png']);
    expect(EXPORT_FORMATS.some((f) => f.value === 'state')).toBe(false);
  });

  it('DEFAULT_EXPORT_FMT 仍为 plt-clean（默认选中不动）', async () => {
    const { DEFAULT_EXPORT_FMT } = await import('../download');
    expect(DEFAULT_EXPORT_FMT).toBe('plt-clean');
  });

  it('状态文件 RFC5987 中文文件名解析（_状态_ 命名 round-trip）', () => {
    const fname = '5336订单_状态_20260911-103000.msn';
    const cd = `attachment; filename="nesting_state_20260911-103000.msn"; filename*=UTF-8''${
      // encodeURIComponent 与后端 urllib.parse.quote 中文同编码口径
      encodeURIComponent(fname).replace(/[!'()*]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase())
    }`;
    expect(parseContentDisposition(cd, 'state')).toBe(fname);
  });
});

// 2026-09-12 文件名弹窗：默认名合成式镜像（**名称主体，无扩展名** —— 后端 save_as
// 清洗时按格式自动补后缀；确认后实际名以 save_as 回传为准，见 hooks/useExport）。
describe('defaultExportFilename / defaultStateFilename（2026-09-12 弹窗预填）', () => {
  it('镜像 /export 合成式（去后缀）：{stem}_码{码号-连}_{pct}pct_seed{N}', async () => {
    const { defaultExportFilename } = await import('../download');
    expect(defaultExportFilename('M1787.dxf', 'png', [28, 30, 32], 0.8842, 0))
      .toBe('M1787_码28-30-32_88.42pct_seed0');
  });

  it('码号空 → all 兜底；乱序入参 → 升序排', async () => {
    const { defaultExportFilename } = await import('../download');
    expect(defaultExportFilename('5336.dxf', 'dxf', [], 0.5, 3))
      .toBe('5336_码all_50.00pct_seed3');
    expect(defaultExportFilename('M.dxf', 'png', [32, 28, 30], 0.5, 0))
      .toBe('M_码28-30-32_50.00pct_seed0');
  });

  it("plt-clean → _毛版 后缀（格式差异只在后端补后缀时体现）", async () => {
    const { defaultExportFilename } = await import('../download');
    expect(defaultExportFilename('M1787.dxf', 'plt-clean', [30], 0.8838, 1))
      .toBe('M1787_码30_88.38pct_seed1_毛版');
    expect(defaultExportFilename('M1787.dxf', 'plt', [30], 0.8838, 1))
      .toBe('M1787_码30_88.38pct_seed1');
  });

  it('母版名缺失 → 排料 兜底 stem；无 .dxf 扩展名原样用', async () => {
    const { defaultExportFilename } = await import('../download');
    expect(defaultExportFilename(undefined, 'png', [], 0.5, 0)).toBe('排料_码all_50.00pct_seed0');
    expect(defaultExportFilename(null, 'png', [], 0.5, 0)).toBe('排料_码all_50.00pct_seed0');
    expect(defaultExportFilename('5336', 'png', [28], 0.5, 0)).toBe('5336_码28_50.00pct_seed0');
  });

  it('defaultStateFilename：{stem}_状态_{yyyymmdd-HHMMSS}（无扩展名）；缺省 stem 兜底 排料', async () => {
    const { defaultStateFilename } = await import('../download');
    expect(defaultStateFilename('M1787.dxf')).toMatch(/^M1787_状态_\d{8}-\d{6}$/);
    expect(defaultStateFilename(undefined)).toMatch(/^排料_状态_\d{8}-\d{6}$/);
  });
});

describe('downloadBlob (US-007 AC#5)', () => {
  // jsdom `<a>.click()` 会触发 navigation 报「Not implemented」—— 我们只关心副作用（download 属性、
  // href、appendChild、remove、revokeObjectURL），不模拟真实下载。stub click 到 no-op。
  let clickSpy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });
  afterEach(() => {
    clickSpy.mockRestore();
  });

  it('创建 <a> + click + remove + revokeObjectURL（10s 后）', () => {
    const blob = new Blob(['data'], { type: 'image/png' });
    const removeSpy = vi.spyOn(Element.prototype, 'remove');

    vi.useFakeTimers();
    downloadBlob(blob, '排料.png');
    // 同步：appendChild + click + remove 已发生；body 内 <a> 已清
    expect(document.body.querySelectorAll('a').length).toBe(0);
    expect(removeSpy).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    // revokeObjectURL 在 10s 后才调
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(10000);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
    removeSpy.mockRestore();
  });

  it('download 属性 = filename（触发附件下载行为）', () => {
    const blob = new Blob(['x'], { type: 'image/png' });
    const createdAnchors: HTMLAnchorElement[] = [];
    const origCreate = document.createElement.bind(document);
    const spy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag);
      if (tag.toLowerCase() === 'a') createdAnchors.push(el as HTMLAnchorElement);
      return el;
    });
    vi.useFakeTimers();
    downloadBlob(blob, '中文文件名.png');
    expect(createdAnchors.length).toBe(1);
    expect(createdAnchors[0].download).toBe('中文文件名.png');
    vi.advanceTimersByTime(10000);
    vi.useRealTimers();
    spy.mockRestore();
  });

  it('href = ObjectURL（点击前已设置）', () => {
    const blob = new Blob(['x'], { type: 'image/png' });
    const createdAnchors: HTMLAnchorElement[] = [];
    const origCreate = document.createElement.bind(document);
    const spy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag);
      if (tag.toLowerCase() === 'a') createdAnchors.push(el as HTMLAnchorElement);
      return el;
    });
    vi.useFakeTimers();
    downloadBlob(blob, 'x.png');
    expect(createdAnchors[0].href).toBe('blob:fake://1');
    vi.advanceTimersByTime(10000);
    vi.useRealTimers();
    spy.mockRestore();
  });
});

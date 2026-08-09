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

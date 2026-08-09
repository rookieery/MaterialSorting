// 下载与文件名解析工具（US-007 AC#4..#5）。
//
// 与旧 legacy/app.js exportAs 内的 Content-Disposition 解析 + <a download> 字节级一致：
//   1. /filename\*=UTF-8''([^;]+)/i → decodeURIComponent（中文文件名 RFC 5987 正确解出）
//   2. fallback：filename="xxx" / filename=xxx
//   3. 兜底：nesting.<fmt>
//   4. <a download> + URL.createObjectURL + 10s revoke（与旧 app.js setTimeout 10000 一致）

/** 导出格式（与后端 server.py export 路由的 fmt 字段对齐）。 */
export type ExportFmt = 'png' | 'dxf';

/**
 * 从 Content-Disposition 头解析下载文件名（RFC 5987）。
 *
 * 优先级（与旧 app.js exportAs 内 `m = /filename\*=UTF-8''([^;]+)/i.exec(cd)` 一致）：
 *   1. filename*=UTF-8''xxx → decodeURIComponent（处理 %E6%8E%92%E6%96%99 中文百分号编码）
 *   2. filename="xxx" 或 filename=xxx（ASCII fallback）
 *   3. nesting.<fmt>（最终兜底；与旧 app.js `nesting.${fmt}` 字面量一致）
 *
 * 异常处理：decodeURIComponent 抛 URIError（malformed URI sequence）→ 落到 fallback。
 */
export function parseContentDisposition(cd: string, fmt: ExportFmt): string {
  // 1) RFC 5987 filename*=UTF-8''xxx（中文文件名主路径）
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star && star[1]) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      // malformed URI sequence —— 落到 filename= / filename*= 之外的 fallback
    }
  }
  // 2) filename="xxx" 或 filename=xxx（ASCII fallback；与旧 app.js 同兜底语义）
  const quoted = /filename="?([^";]+)"?/i.exec(cd);
  if (quoted && quoted[1]) return quoted[1];
  // 3) 兜底
  return `nesting.${fmt}`;
}

/**
 * 触发浏览器下载（<a download> + URL.createObjectURL + 10s revoke）。
 *
 * 与旧 app.js exportAs 内：
 *   const a = document.createElement('a');
 *   a.href = URL.createObjectURL(blob); a.download = name;
 *   document.body.appendChild(a); a.click(); a.remove();
 *   setTimeout(() => URL.revokeObjectURL(a.href), 10000);
 *
 * 不变量：
 *   - 调用前后 a 节点必须 detach（避免泄漏 DOM；appendChild + remove 与旧版一致）。
 *   - revoke 延迟 10s（与旧版字面量一致）—— 给浏览器足够时间发起下载请求。
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const a = document.createElement('a');
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

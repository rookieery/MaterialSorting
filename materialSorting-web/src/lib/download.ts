// 下载与文件名解析工具（US-007 AC#4..#5）。
//
// 与旧 vanilla 前身 exportAs 内的 Content-Disposition 解析 + <a download> 字节级一致：
//   1. /filename\*=UTF-8''([^;]+)/i → decodeURIComponent（中文文件名 RFC 5987 正确解出）
//   2. fallback：filename="xxx" / filename=xxx
//   3. 兜底：nesting.<fmt>
//   4. <a download> + URL.createObjectURL + 10s revoke（与旧 vanilla 实现 setTimeout 10000 一致）

/** 导出格式（与后端 server.py export 路由的 fmt 字段对齐）。
 * 'plt-clean' = PLT 毛版变体（2026-08-31：裁片只画最外层毛版轮廓 + 尺码*数量标注，
 * 唛架左右两端各一份同内容信息表格；后端 /export clean=True 分支。命名与裁片
 * layer1「毛版轮廓」同口径，当日由「净版」更名；协议值 'plt-clean' 不随更名变）。 */
export type ExportFmt = 'png' | 'dxf' | 'plt' | 'plt-clean';

/**
 * 导出格式下拉框选项（与 ExportFmt 同源）。
 * 新增格式只需：往此数组加一项 + 扩 ExportFmt 联合类型 + 后端 /export 路由加分支。
 *
 * 顺序约定：DXF 永远第一项（版师 / ET2008 生产交付主格式）；US-034 新增 PLT（WT V8.8 /
 * LIKE 绘图仪原生链路），插在 DXF 与 PNG 之间——生产交付格式族（DXF/PLT）相邻，PNG 作为
 * 可视化预览格式排末位。下拉顺序与默认选中解耦：2026-08-24 起 DEFAULT_EXPORT_FMT='plt'
 * （用户要求，现场以绘图仪切绘为主用交付），2026-08-31 起 'plt-clean'（毛版，用户要求
 * 毛版为现场主交付）；首项仍为 DXF。
 */
export const EXPORT_FORMATS: { value: ExportFmt; label: string }[] = [
  { value: 'dxf', label: 'DXF' },
  { value: 'plt', label: 'PLT' },
  { value: 'plt-clean', label: 'PLT（毛版）' },
  { value: 'png', label: 'PNG' },
];

/** 默认导出格式：2026-08-31 起 PLT 毛版（用户要求，现场以毛版切绘为主用交付；
 * 此前 2026-08-24~08-30 为 'plt' 全量）；DXF 仍为下拉首项。 */
export const DEFAULT_EXPORT_FMT: ExportFmt = 'plt-clean';

/**
 * 从 Content-Disposition 头解析下载文件名（RFC 5987）。
 *
 * 优先级（与旧 vanilla 实现 exportAs 内 `m = /filename\*=UTF-8''([^;]+)/i.exec(cd)` 一致）：
 *   1. filename*=UTF-8''xxx → decodeURIComponent（处理 %E6%8E%92%E6%96%99 中文百分号编码）
 *   2. filename="xxx" 或 filename=xxx（ASCII fallback）
 *   3. nesting.<fmt>（最终兜底；与旧 vanilla 实现 `nesting.${fmt}` 字面量一致）
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
  // 2) filename="xxx" 或 filename=xxx（ASCII fallback；与旧 vanilla 实现 同兜底语义）
  const quoted = /filename="?([^";]+)"?/i.exec(cd);
  if (quoted && quoted[1]) return quoted[1];
  // 3) 兜底（'plt-clean' 去变体后缀还原 .plt 扩展名 —— 仅 CD 头缺失的极端路径会走到）
  return `nesting.${fmt.replace(/-clean$/, '')}`;
}

/**
 * 触发浏览器下载（<a download> + URL.createObjectURL + 10s revoke）。
 *
 * 与旧 vanilla 实现 exportAs 内：
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

// useExport —— 导出最优排料 PNG / DXF 的生命周期 hook（US-007）。
//
// 与旧 vanilla 前身 exportAs(fmt) 字节级等价：
//   1. bestRun = lastFrame 存在且 finalDensity 最高的 run（runRegistry.bestRun() 已封装；
//      AC#1）。
//   2. ExportPayload = { fmt, sizes: selectedSizes(), seed: run.seed, gate_mm,
//      width_mm: lastFrame.width_mm, density: run.finalDensity, placed: lastFrame.placed_items,
//      filename: doc.filename }（AC#2 字段 + filename 透传作导出文件名前缀）。
//   3. fetch /export（相对 URL；dev 由 Vite proxy 转 :8000，prod 同源），响应 blob（AC#3）。
//   4. Content-Disposition filename*=UTF-8''xxx → decodeURIComponent；fallback filename=xxx
//      / nesting.<fmt>（AC#4，由 lib/download.ts parseContentDisposition 处理）。
//   5. <a download> 触发文件下载，中文文件名前缀取上传母版名（去 .dxf 扩展名），形如
//      M1787_码28-30-32_88.42%_seed0.png（AC#5，由后端 server.py 拼 filename* + 前端 decode）。
//   6. 求解未完成或无 lastFrame → 按钮 disabled（由 ExportButtons 自身根据 registry 状态判断）；
//      导出中 exporting=true（按钮 disabled + StatusLine 显示 正在生成 PNG/DXF…）。
//
// 解耦：
//   - useExport 只负责 HTTP 调用 + 下载触发，sizes 由调用方（ControlPanel form）透传。
//   - 按钮的 disabled（求解中 / 无 lastFrame）由 ExportButtons 直接读 runRegistry + props.solving。
//   - onStatus 透传到 ControlPanel props.onStatus（最终写入 App.setStatus → StatusLine）。
//
// 防连击：exportingRef 与 exporting state 同步，导出中再次触发 → 静默忽略（旧版用 disabled 间接防，
// 这里双重防护）。
//
// 状态文件 US-003：新增 saveState() —— fmt='state' 分支（独立 /api/state-save，
// 不进 /export 路由族）；body = lib/stateFile.buildSavePayload()，下载文件名由
// 后端 Content-Disposition 给出（<母版名去 .dxf>_状态_<时间戳>.msn）；与
// exportAs 共用 exporting 单一防连击旗（PNG/DXF/PLT/状态文件互斥）。

import { useCallback, useRef, useState } from 'react';
import { apiFetch } from '../lib/api';
import type { ExportFmt } from '../lib/download';
import { downloadBlob, parseContentDisposition } from '../lib/download';
import type { ExportTableFields } from '../lib/exportTable';
import { toExportTablePayload } from '../lib/exportTable';
import { buildSavePayload } from '../lib/stateFile';
import { runRegistry } from '../store/runRegistry';

/** 父级回调：导出开始 / 完成 / 失败时把状态文案透传给 StatusLine（AC#6）。 */
export interface UseExportCallbacks {
  onStatus?: (text: string) => void;
}

export interface UseExportResult {
  /** 触发导出（取 bestRun → POST /export → blob 下载）。sizes = ControlPanel form.sizes；
   *  filename = 上传母版名（透传作导出文件名前缀，与界面「当前文件」同源）；
   *  table = PLT 唛架信息表格手输字段（2026-08-30，仅 fmt='plt'/'plt-clean' 消费 ——
   *  后端转 14 字段表格附在唛架外围（毛版左右各一份）；undefined 时 payload 不带 table 键）；
   *  saveAs = 文件名弹窗确认的名称主体（2026-09-12，**无扩展名** —— 后端清洗时
   *  按 fmt 自动补正确后缀后整名覆盖合成名；undefined 时 payload 不带 save_as 键
   *  = 合成名旧行为）。 */
  exportAs: (fmt: ExportFmt, sizes: number[], filename?: string,
             table?: ExportTableFields, saveAs?: string) => Promise<void>;
  /**
   * 保存状态文件（状态文件 US-003，fmt='state' 分支）：POST /api/state-save
   * （body = buildSavePayload(saveAs)）→ blob → parseContentDisposition → downloadBlob。
   * 与 PNG/DXF/PLT 共用 exporting state/ref 单一防连击旗（互斥）；saveAs（2026-09-12
   * 弹窗）= 确认的名称主体（无扩展名，后端补 .msn；缺省 → 后端从会话 doc.source
   * 生成 <母版名去 .dxf>_状态_<时间戳>.msn）。StatusLine 三态走同一 onStatus。
   */
  saveState: (saveAs?: string) => Promise<void>;
  /** 是否正在导出（按钮 disabled + 状态行 正在生成…）。 */
  exporting: boolean;
}

/**
 * useExport —— 单实例 hook，挂在 ControlPanel 内（与 form.sizes 同处）。
 *
 * 调用方约定：
 *   const { exportAs, exporting } = useExport({ onStatus });
 *   <ExportButtons solving={solving} exporting={exporting} onExport={(fmt) => exportAs(fmt, form.sizes)} />
 */
export function useExport(cb: UseExportCallbacks = {}): UseExportResult {
  // 用 ref 持有最新回调，避免 onStatus 闭包陈旧（与 useSolveRun cbRef 同套路）。
  const cbRef = useRef(cb);
  cbRef.current = cb;

  const [exporting, setExporting] = useState(false);
  // ref 同步 state，async 流程内读到最新值（防连击：state 异步生效，ref 立即生效）。
  const exportingRef = useRef(false);

  const exportAs = useCallback(async (fmt: ExportFmt, sizes: number[], filename?: string,
                                       table?: ExportTableFields,
                                       saveAs?: string): Promise<void> => {
    // 1) bestRun（AC#1）：lastFrame 存在且 finalDensity 最高的 run
    const run = runRegistry.bestRun();
    if (!run || !run.lastFrame) {
      cbRef.current.onStatus?.('无可导出的方案（请先求解）');
      return;
    }
    // 防连击：导出中再次触发 → 忽略
    if (exportingRef.current) return;

    // 2) ExportPayload（AC#2，逐字段与旧 vanilla 实现 一致）
    //    gate_mm 来自 manifest（与旧 vanilla 实现 `gateH = m.gate_mm` 同源；所有 run 共享）。
    //    table（2026-08-30）：PLT 唛架信息表格手输字段；save_as（2026-09-12 弹窗）：
    //    确认的名称主体，无扩展名（JSON.stringify 自动剔除 undefined —— PNG/DXF/PLT
    //    载荷与旧版逐字节一致，带 save_as 时后端清洗 + 按 fmt 补后缀后整名覆盖合成名）。
    const gate_mm = run.manifest?.gate_mm ?? 0;
    const payload = {
      fmt,
      sizes,
      seed: run.seed,
      gate_mm,
      width_mm: run.lastFrame.width_mm,
      density: run.finalDensity,
      placed: run.lastFrame.placed_items,
      filename,
      table: table ? toExportTablePayload(table) : undefined,
      save_as: (saveAs || '').trim() || undefined,
    };

    // 3) 状态行：正在生成 PNG/DXF/PLT…（AC#6；毛版显示中文变体名）
    cbRef.current.onStatus?.(
      `正在生成 ${fmt === 'plt-clean' ? 'PLT（毛版）' : fmt.toUpperCase()} …`);
    setExporting(true);
    exportingRef.current = true;
    try {
      // AC#3：POST /export（相对 URL；dev 走 Vite proxy，prod 同源），响应 blob
      //（US-005 起经 apiFetch 注入 X-Session-Id —— 会话过期时 export 也是 401 JSON）。
      const res = await apiFetch('/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        // 后端返回 JSON {error: ...}（server.py export 路由），降级用 statusText
        let msg = res.statusText;
        try {
          const err = (await res.json()) as { error?: string };
          msg = err.error || msg;
        } catch {
          // 非 JSON 响应 —— 用 statusText 兜底
        }
        cbRef.current.onStatus?.(`导出失败：${msg}`);
        return;
      }
      const blob = await res.blob();
      // AC#4：Content-Disposition filename*=UTF-8''xxx → decodeURIComponent
      const cd = res.headers.get('Content-Disposition') || '';
      const name = parseContentDisposition(cd, fmt);
      // AC#5：<a download> 触发文件下载（中文文件名）
      downloadBlob(blob, name);
      cbRef.current.onStatus?.(`已导出 ${name}`);
    } catch (e) {
      // 网络错 / blob 读错 / 其他 —— 显式 message，与旧 vanilla 实现 `导出失败：${e}` 一致
      const msg = e instanceof Error ? e.message : String(e);
      cbRef.current.onStatus?.(`导出失败：${msg}`);
    } finally {
      setExporting(false);
      exportingRef.current = false;
    }
  }, []);

  // 状态文件 US-003：保存工作台状态（.msn）。防连击与 exportAs 共用同一
  // exportingRef（互斥：保存中点 PNG/DXF/PLT 或反向均静默忽略）。
  // saveAs（2026-09-12 弹窗）= 确认的名称主体，无扩展名（trim 后为空同缺省）。
  const saveState = useCallback(async (saveAs?: string): Promise<void> => {
    if (exportingRef.current) return;
    cbRef.current.onStatus?.('正在生成 状态文件 …');
    setExporting(true);
    exportingRef.current = true;
    try {
      const res = await apiFetch('/api/state-save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildSavePayload(saveAs)),
      });
      if (!res.ok) {
        // 后端结构化 JSON {error}（保存期守恒 fail-fast 指路文案 / 会话 401/422 等）
        let msg = res.statusText;
        try {
          const err = (await res.json()) as { error?: string };
          msg = err.error || msg;
        } catch {
          // 非 JSON 响应 —— 用 statusText 兜底
        }
        cbRef.current.onStatus?.(`导出失败：${msg}`);
        return;
      }
      const blob = await res.blob();
      // Content-Disposition 中文/ASCII 双写（/export 同法），RFC5987 解析复用；
      // fallback 扩展名 'state' → nesting.msn（仅 CD 头缺失的极端路径）。
      const cd = res.headers.get('Content-Disposition') || '';
      const name = parseContentDisposition(cd, 'state');
      downloadBlob(blob, name);
      cbRef.current.onStatus?.(`已导出 ${name}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      cbRef.current.onStatus?.(`导出失败：${msg}`);
    } finally {
      setExporting(false);
      exportingRef.current = false;
    }
  }, []);

  return { exportAs, saveState, exporting };
}

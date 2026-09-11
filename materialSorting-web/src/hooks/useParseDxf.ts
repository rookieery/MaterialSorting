// useParseDxf —— 上传 DXF → POST /api/parse-dxf → 写入 uploadStore（US-005）。
//
// 设计要点（参考 useExport 的防连击 + 错误处理模式）：
//   1. 请求走相对路径 '/api/parse-dxf'（dev 由 Vite proxy 转 :8000，prod 同源；与 useExport
//      内 '/export' 同口径，dev/prod 前端代码完全一致；US-005 起统一经 lib/api.apiFetch
//      注入 X-Session-Id）。
//   2. multipart/form-data：FormData 仅一个 file 字段（单文件）。Content-Type 由 fetch
//      自动设 multipart/form-data + boundary，**不能手设**（否则 boundary 丢失导致后端
//      python-multipart 解析失败）。
//   3. 防连击：uploadingRef（立即生效）+ status==='uploading'（store 状态）双重防护，
//      上传中重复触发 → 静默 return（不抛错、不重置状态、不覆盖正在进行的 fetch）。
//      ref 是必需的：setState 异步生效，第二次连击会在 setState 调度前进 hook body。
//   4. 状态机：uploading → done | error；error 时存中文消息（后端 JSONResponse.error /
//      网络错 message）。
//   5. 成功后默认 activeSize = doc.sizes[0]?.size ?? null（后端按数值升序、null 殿后；
//      sizes[0] 是最小码；空 sizes 兜底 null，UI 自然显示空态）。
//   6. US-021 D1：解析成功后自动触发 commit（后台副作用，不阻塞预览渲染）。
//      doc/status 先进 store（UI 立即渲染预览），commit 再后台跑（commitStatus 独立字段）。
//      commit 失败不影响 parse done（预览已可用）；commit 成功仅解锁超排 Tab（不自动切入）。
//   7. 解析成功且 doc.sizes 含 null 码（块名末尾带不出码号的裁片）→ toast 提示
//      （2026-08-31）：超排页码号区已不渲染该组 chip（通用片不参与求解），toast 引导
//      用户检查母版命名；具体是哪些片看预览页 QtyMatrix「通用」行。
//   8. 状态文件 US-003 上传分流 + US-004 恢复编排接线：扩展名 .msn → POST
//      /api/state-restore（multipart，不经 parse-dxf/commit）：uploading 反馈期间走
//      独立校验链，成功 → applyRestorePayload(res)（lib/stateFile：五 store 落笔 +
//      run 合成 + 切超排 Tab）+ toast「状态文件已恢复」；失败 toast 后端结构化错误
//      信息；.dxf 原路径零变化（分支在 parse 请求之前）。
//
// 调用方约定：
//   const { upload } = useParseDxf();
//   <UploadPanel onPick={(file) => upload(file)} />
//   上传前应做客户端预校验（.dxf 后缀、单文件、大小上限），不通过则不发请求（US-006 落地）。
//
// 解耦：
//   - hook 只负责 HTTP + store 写入；UI 文案 / loading 显示由 UploadPanel 读 uploadStore 渲染。
//   - hook 不抛错（错误统一进 uploadStore.error，UI 自取）；返回 Promise<void> 仅为调用方
//     可选 await（如「上传完成后再切 Tab」类用法）。

import { useCallback, useRef } from 'react';
import { apiFetch } from '../lib/api';
import { applyRestorePayload } from '../lib/stateFile';
import { useToastStore } from '../store/toastStore';
import { useUploadStore } from '../store/uploadStore';
import { useCommitToNesting } from './useCommitToNesting';
import type { ParsedDoc } from '../types/parsed';
import type { StateRestoreResponse } from '../types/stateFile';

/** 解析端点（dev 由 Vite proxy 转 :8000；prod 同源）。 */
const PARSE_DXF_URL = '/api/parse-dxf';

/** 状态文件恢复端点（US-003 上传分流；multipart，与 parse-dxf 同走 apiFetch 注 sid）。 */
const STATE_RESTORE_URL = '/api/state-restore';

/** 状态文件扩展名（与后端 STATE_EXTENSION 同源；accept/分流判定用，小写比较）。 */
const STATE_FILE_EXT = '.msn';

export interface UseParseDxfResult {
  /** 触发上传（防连击：uploading 中重复触发静默忽略）。客户端预校验应由调用方完成。 */
  upload: (file: File) => Promise<void>;
}

export function useParseDxf(): UseParseDxfResult {
  // 防连击：ref 立即生效（setState 异步，第二次连击会在 setState 调度前进 hook body）。
  const uploadingRef = useRef(false);
  // US-021 D1：解析成功后自动 commit（后台副作用）。useCommitToNesting 内部同样有
  // committingRef + commitStatus 双重防连击，此处仅持引用供 upload 回调内调用。
  const { commit } = useCommitToNesting();

  const upload = useCallback(async (file: File): Promise<void> => {
    // 双重防护：ref + store status（任一为 uploading 即忽略，防止意外覆盖正在进行的请求）
    if (uploadingRef.current) return;
    if (useUploadStore.getState().status === 'uploading') return;

    uploadingRef.current = true;
    try {
      // 状态文件 US-003：按扩展名分流（分支在 parse 请求之前，.dxf 流程逐行为旧代码）。
      // .msn → 恢复端点（不经 parse-dxf / commit）；大小写容错（仅看后缀，MIME 同理不判）。
      if (file.name.toLowerCase().endsWith(STATE_FILE_EXT)) {
        await restoreStateFile(file);
        return;
      }
      await uploadDxf(file, commit);
    } finally {
      uploadingRef.current = false;
    }
  }, [commit]);

  return { upload };
}

/**
 * .msn 状态文件恢复分流（US-003 分流 + US-004 编排接线）：POST /api/state-restore
 * （multipart）→ 成功 applyRestorePayload(res)（doc/qty/form/ptype 落笔 + run 合成
 * + 有 run 时切超排 Tab；status 置 done）+ toast「状态文件已恢复」；失败 toast
 * 后端结构化错误信息。错误不进 uploadStore.error：toast 是状态文件路径的统一
 * 提示通道（不与 .dxf 路径的红字互斥展示语义耦合）；失败/网络错回 idle（无半
 * 恢复态 —— 旧 doc 展示随会话覆盖语义失效，用户重传即重新开始）。
 */
async function restoreStateFile(file: File): Promise<void> {
  useUploadStore.setState({
    status: 'uploading',
    error: null,
    commitStatus: 'idle',
    commitError: null,
    commitSummary: null,
  });
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await apiFetch(STATE_RESTORE_URL, {
      method: 'POST',
      body: fd,
    });
    if (!res.ok) {
      // 校验链错误（400/413）/ 会话错误（401/429）全走 JSONResponse { error }（中文消息）
      let msg = res.statusText;
      try {
        const err = (await res.json()) as { error?: string };
        msg = err.error || msg;
      } catch {
        // 非 JSON 响应 —— 用 statusText 兜底
      }
      useToastStore.getState().pushToast(`状态文件恢复失败：${msg}`);
      return;
    }
    // 恢复编排（US-004）：五 store 落笔 + run 合成 + provenance 写回 + 切超排 Tab。
    const payload = (await res.json()) as StateRestoreResponse;
    applyRestorePayload(payload);
    useToastStore.getState().pushToast(
      `状态文件已恢复：${payload.filename}${payload.run ? '（含排料结果）' : ''}`,
    );
  } catch (e) {
    // 网络错 / SessionBlockedError —— toast 统一提示（不抛、不 rethrow）
    const msg = e instanceof Error ? e.message : String(e);
    useToastStore.getState().pushToast(`状态文件恢复失败：${msg}`);
  } finally {
    // 成功路径 applyRestorePayload 已置 status='done'（doc 就绪）；失败/网络错回 idle。
    if (useUploadStore.getState().status === 'uploading') {
      useUploadStore.setState({ status: 'idle' });
    }
  }
}

/** .dxf 母版解析路径（US-005 原实现，US-003 分流后独立成函数 —— 行为零变化）。 */
async function uploadDxf(
  file: File,
  commit: (docId: string, filename?: string) => Promise<unknown>,
): Promise<void> {
  // 进入 uploading 时清掉旧的 error（避免 UI 残留上次失败的红字），doc/activeSize 保留。
  // 同步清 commit 字段（US-021）：重传时旧 commit 摘要 / 错误不再适用，避免 UI 误导。
  useUploadStore.setState({
    status: 'uploading',
    error: null,
    commitStatus: 'idle',
    commitError: null,
    commitSummary: null,
  });

  try {
    const fd = new FormData();
    fd.append('file', file);

      const res = await apiFetch(PARSE_DXF_URL, {
        method: 'POST',
        body: fd,
      });

      if (!res.ok) {
        // 后端 400/413/422 全部走 JSONResponse { error: ... }（中文消息）
        let msg = res.statusText;
        try {
          const err = (await res.json()) as { error?: string };
          msg = err.error || msg;
        } catch {
          // 非 JSON 响应 —— 用 statusText 兜底
        }
        useUploadStore.setState({ status: 'error', error: msg });
        return;
      }

      const doc = (await res.json()) as ParsedDoc;
      // 默认选中第一个码（后端按数值升序、null 殿后；sizes[0] 是最小码；空 sizes 兜底 null）
      const initialSize = doc.sizes.length > 0 ? doc.sizes[0].size : null;
      useUploadStore.setState({
        status: 'done',
        doc,
        activeSize: initialSize,
        error: null,
      });

      // 解析成功且含 null 通用码（块名末尾带不出码号的裁片）→ toast 提示检查母版命名。
      // 超排页码号区不渲染该组（通用片不参与求解，WS 载荷过滤 null），预览页 QtyMatrix
      // 「通用」行是唯一排查入口 —— 文案里点名去向。
      if (doc.sizes.some((s) => s.size === null)) {
        useToastStore
          .getState()
          .pushToast(
            '当前 DXF 文件存在一批块名末尾带不出码号的裁片，已归入上传预览页「通用」分组（不参与排料），请检查母版命名',
          );
      }

      // US-021 D1：解析成功 → 自动触发 commit（后台副作用，不阻塞预览）。
      //   - doc/status 已进 store（上一行 setState 同步生效），UI 立即渲染预览；
      //   - commit 用 void 不 await：parse 预览先上屏，commit 后台跑更新 commitStatus；
      //   - commit done 时 useCommitToNesting 内部 setNestingEnabled(true)（不自动切 Tab，由用户主动点击进入）；
      //   - commit fail 时 commitStatus='error' 显示，不切 Tab（D5：Tab 仍解锁，可重试或用旧数据）。
      void commit(doc.doc_id, doc.filename);
    } catch (e) {
      // 网络错 / JSON 解析错 —— 统一进 error 状态（不抛、不 rethrow）
      const msg = e instanceof Error ? e.message : String(e);
      useUploadStore.setState({ status: 'error', error: msg });
    }
}

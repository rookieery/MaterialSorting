// useCommitToNesting —— 解析成功后自动 commit 母版到超排（US-021 D1 副作用）。
//
// 设计要点（参考 useParseDxf 防连击 + 错误进 store 模式）：
//   1. fetch POST /api/commit-to-nesting JSON body {doc_id, filename}（与 useParseDxf
//      FormData 上传不同 —— commit 是已落盘文件的引用，无文件数据传输）。
//      Content-Type 必须手设 application/json（与 useParseDxf 不手设 multipart 边界不同）。
//   2. 防连击：committingRef（立即生效）+ commitStatus==='committing'（store 状态）
//      双重防护，连击仅触发一次 fetch（与 useParseDxf uploadingRef 同模式）。
//   3. 状态机：idle → committing → done | error；commitStatus 与 parse status 分离
//      （独立字段），互不干扰 —— parse done 触发 commit，commit 后台跑不阻塞预览。
//   4. 错误不抛、不 rethrow（统一进 uploadStore.commitError，UI 自取）；返回
//      Promise<CommitResult> 仅为调用方可选 await（如测试断言）。
//   5. commit done → setNestingEnabled(true)（US-015/016 已在 PreviewPage subscribe
//      parse done 时设过，这里重复设是显式 D1 闭环，幂等无副作用） +
//      setTab('nesting') 自动切入超排页（uiStore guard：nestingEnabled=false 时静默不切，
//      故必须先 setNestingEnabled(true) 再 setTab）。
//   6. commit fail → commitStatus='error' + commitError 显示；**不切 Tab**（D5），
//      让用户看到错误；Tab 解锁状态由 PreviewPage subscribe parse done 控制（已 true），
//      用户可重试 commit 或用旧数据进入超排。
//
// 调用方约定：
//   const { commit } = useCommitToNesting();
//   void commit(doc.doc_id, doc.filename);  // 不 await，后台跑
//   hook 不抛错（错误统一进 uploadStore.commitError，UI 自取）；返回 Promise<CommitResult>
//   仅为调用方可选 await（如测试断言 / 「commit 完成后再做 X」类用法）。
//
// 解耦：
//   - hook 只负责 HTTP + store 写入 + D1 闭环（setNestingEnabled + setTab）；
//     UI 文案 / loading 显示由 UploadPanel 读 uploadStore.commitStatus 渲染。
//   - hook 不读 uploadStore.doc（doc_id/filename 由调用方传入，hook 本身不依赖 doc 形状）。

import { useCallback, useRef } from 'react';
import { useUploadStore, type CommitSummary } from '../store/uploadStore';
import { useUiStore } from '../store/uiStore';

/** commit 端点（dev 由 Vite proxy 转 :8000；prod 同源）。 */
const COMMIT_TO_NESTING_URL = '/api/commit-to-nesting';

/** commit 成功返回结构（后端 _commit_to_nesting_sync 返回 dict 的子集）。 */
interface CommitResponseData {
  doc_id?: unknown;
  source?: unknown;
  sizes?: unknown;
  n_pieces?: unknown;
  total_area_mm2?: unknown;
  reloaded?: unknown;
}

/** hook 返回结构：commit 完成（ok=true + summary）或失败（ok=false + error）。 */
export interface CommitResult {
  ok: boolean;
  summary?: CommitSummary;
  error?: string;
}

export interface UseCommitToNestingResult {
  /** 触发 commit（防连击：committing 中重复触发静默忽略）。 */
  commit: (doc_id: string, filename?: string) => Promise<CommitResult>;
}

export function useCommitToNesting(): UseCommitToNestingResult {
  // 防连击：ref 立即生效（setState 异步，第二次连击会在 setState 调度前进 hook body）。
  const committingRef = useRef(false);

  const commit = useCallback(
    async (doc_id: string, filename?: string): Promise<CommitResult> => {
      // 双重防护：ref + store commitStatus（任一为 committing 即忽略，防止意外覆盖正在进行的请求）
      if (committingRef.current) {
        return { ok: false, error: 'commit already in progress' };
      }
      if (useUploadStore.getState().commitStatus === 'committing') {
        return { ok: false, error: 'commit already in progress' };
      }

      committingRef.current = true;
      // 进入 committing 时清掉旧的 error / summary（避免 UI 残留上次失败的红字或旧摘要）
      useUploadStore.setState({
        commitStatus: 'committing',
        commitError: null,
        commitSummary: null,
      });

      try {
        const res = await fetch(COMMIT_TO_NESTING_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ doc_id, filename }),
        });

        if (!res.ok) {
          // 后端 400/404/422 全部走 JSONResponse { error: ... }（中文消息）
          let msg = res.statusText;
          try {
            const err = (await res.json()) as { error?: string };
            msg = err.error || msg;
          } catch {
            // 非 JSON 响应 —— 用 statusText 兜底
          }
          useUploadStore.setState({ commitStatus: 'error', commitError: msg });
          return { ok: false, error: msg };
        }

        const data = (await res.json()) as CommitResponseData;
        // 防御性构造 summary：字段缺失用空数组 / 0 兜底（不阻塞 commit done 状态切换）
        const summary: CommitSummary = {
          sizes: Array.isArray(data.sizes) ? (data.sizes as number[]) : [],
          n_pieces: typeof data.n_pieces === 'number' ? data.n_pieces : 0,
          total_area_mm2:
            typeof data.total_area_mm2 === 'number' ? data.total_area_mm2 : 0,
        };

        useUploadStore.setState({
          commitStatus: 'done',
          commitError: null,
          commitSummary: summary,
        });

        // D1 闭环（US-021 AC#4）：commit done → 解锁超排 Tab + 自动切入。
        //   - setNestingEnabled(true) 与 PreviewPage subscribe parse done 重复（幂等），
        //     显式调保证 commit 链路自闭环（不依赖 PreviewPage effect 时序）。
        //   - setTab('nesting') 必须在 setNestingEnabled(true) 之后：uiStore guard
        //     `nestingEnabled===false 时 setTab('nesting') 静默不切`。
        useUiStore.getState().setNestingEnabled(true);
        useUiStore.getState().setTab('nesting');

        return { ok: true, summary };
      } catch (e) {
        // 网络错 / JSON 解析错 —— 统一进 commitError（不抛、不 rethrow）
        const msg = e instanceof Error ? e.message : String(e);
        useUploadStore.setState({ commitStatus: 'error', commitError: msg });
        return { ok: false, error: msg };
      } finally {
        committingRef.current = false;
      }
    },
    [],
  );

  return { commit };
}

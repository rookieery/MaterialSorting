// UploadPanel —— DXF 上传预览页左侧面板（US-006）。
//
// 职责：
//   1. 点击按钮 / 拖拽落区 → 触发隐藏 `<input type=file accept=".dxf">` → 调 useParseDxf.upload。
//   2. 客户端预校验：.dxf 后缀（MIME 容错，仅看后缀）+ 单文件 + 20MB 上限。
//      失败 → 红字提示，**不发请求**（AC#2）。
//   3. 从 uploadStore 读 status/error：uploading 显示加载态、done 显示文件名 + 码数概览、
//      error 显示后端返回的红字消息（AC#3）；客户端校验失败显示本地红字（与 store.error 互斥展示）。
//   4. US-021：从 uploadStore 读 commitStatus/commitError/commitSummary —— 解析成功后
//      自动 commit（D1 副作用），commit 中显示「应用中…」、done 显示「已应用至超排：N 裁片，M 码」、
//      error 显示红字。commit 状态独立于 parse status，两行互不干扰（parse done 行 + commit 行）。
//
// 设计原则（CLAUDE.md / AGENTS.md US-005 关键约定）：
//   - 沿用 style.css，与 ControlPanel 视觉同色系（暗背景 #26282e + 绿色 #2ea06c 强调）；
//     不引入 CSS 框架。左侧固定宽度（沿用 `.panel` width: 248px）。
//   - **整个 aside 是拖拽落区**（dragenter/dragover/dragleave/drop 挂在根元素），点击触发限定在
//     drop-zone / button 上（避免点状态文本误触文件选择）。
//   - dragCounter 防子元素 dragleave 抖动：浏览器在子元素间移动会反复触发 dragenter/dragleave，
//     用计数器保证只在真正离开 panel 时清 .dragover（与原生 HTML5 DnD 标准模式一致）。
//   - 文件大小上限 20MB 与后端 `server.py UPLOAD_MAX_BYTES` 一致（双校验：客户端先拦，后端兜底）。
//   - `e.target.value = ''` 重置 input value：否则同一文件再次选择不触发 change（input.value 去重机制）。
//
// 状态来源拆分：
//   - HTTP 流程状态（uploading / done / error + doc）→ uploadStore（US-005 单一真相源）。
//   - US-021 commit 状态（committing / done / error + summary）→ uploadStore（独立字段，
//     与 parse status 分离）。commit 由 useParseDxf 在 parse done 后自动触发（D1 副作用），
//     UploadPanel 只读不触发。
//   - 客户端校验失败消息（localError）→ 本组件 useState：不污染 store 状态机（hook 仅在 HTTP 流程内
//     切 status），同时让用户重试时清掉旧 reject 提示。

import { useRef, useState } from 'react';
import type { JSX } from 'react';
import { useParseDxf } from '../../hooks/useParseDxf';
import { useUploadStore } from '../../store/uploadStore';

/** 单文件大小上限（与后端 server.py UPLOAD_MAX_BYTES 一致，20MB）。 */
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** 客户端预校验结果：file 通过 / error 中文消息。 */
interface ValidateResult {
  file?: File;
  error?: string;
}

/** 校验 .dxf 后缀（MIME 容错）+ 单文件 + 大小上限。 */
function validateFiles(files: File[]): ValidateResult {
  if (files.length === 0) return { error: '未选择文件' };
  if (files.length > 1) return { error: '一次只能上传一个 DXF 文件' };
  const f = files[0];
  // MIME 容错：file.type 可能是 ''、'application/dxf'、'application/octet-stream' 等，
  // 仅按后缀判定（生产环境 Windows 下文件 MIME 经常缺失或五花八门）。
  if (!f.name.toLowerCase().endsWith('.dxf')) {
    return { error: '仅支持 .dxf 文件' };
  }
  if (f.size > MAX_UPLOAD_BYTES) {
    return { error: `文件大小超过上限 ${MAX_UPLOAD_BYTES / 1024 / 1024}MB` };
  }
  return { file: f };
}

/** 计算已解析裁片总数（doc.sizes 各码 pieces 数之和）。done 态展示用。 */
function countTotalPieces(doc: { sizes: { pieces: unknown[] }[] }): number {
  return doc.sizes.reduce((sum, s) => sum + s.pieces.length, 0);
}

export function UploadPanel(): JSX.Element {
  // 订阅 uploadStore（US-005 单一真相源）：status 驱动 UI 分支、doc 用于 done 态展示、
  // error 用于 HTTP 流程失败态展示（与 localError 互斥：localError 优先）。
  const status = useUploadStore((s) => s.status);
  const doc = useUploadStore((s) => s.doc);
  const storeError = useUploadStore((s) => s.error);
  // US-021：commit 状态独立订阅（与 parse status 分离），驱动 commit 行渲染。
  const commitStatus = useUploadStore((s) => s.commitStatus);
  const commitError = useUploadStore((s) => s.commitError);
  const commitSummary = useUploadStore((s) => s.commitSummary);

  const { upload } = useParseDxf();

  const inputRef = useRef<HTMLInputElement | null>(null);
  /** 拖拽悬停 flag：dragCounter 计数防子元素 dragleave 抖动。 */
  const dragCounter = useRef(0);
  const [dragOver, setDragOver] = useState(false);
  /** 客户端校验失败消息（与 store.error 互斥：本地优先；新 pick/drop 清零）。 */
  const [localError, setLocalError] = useState<string | null>(null);

  /** 处理 input change / drop 的统一入口。 */
  function handleFiles(files: File[]): void {
    const { file, error } = validateFiles(files);
    if (error || !file) {
      setLocalError(error ?? '未知错误');
      return;
    }
    // 校验通过：清旧 localError，触发 HTTP 流程（hook 内部切 uploading → done | error）
    setLocalError(null);
    void upload(file);
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>): void {
    const list = e.target.files;
    if (list && list.length > 0) handleFiles(Array.from(list));
    // 重置 value 让同一文件可重复选（否则选同一文件不触发 change）
    e.target.value = '';
  }

  function handlePickClick(): void {
    // 上传中禁用（防覆盖正在进行的请求；hook 内部也有 ref + status 双重防护）
    if (status === 'uploading') return;
    inputRef.current?.click();
  }

  function handleDragEnter(e: React.DragEvent): void {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    if (dragCounter.current === 1) setDragOver(true);
  }

  function handleDragOver(e: React.DragEvent): void {
    e.preventDefault(); // 必须 preventDefault 才能触发 drop
    e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
  }

  function handleDragLeave(e: React.DragEvent): void {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = Math.max(0, dragCounter.current - 1);
    if (dragCounter.current === 0) setDragOver(false);
  }

  function handleDrop(e: React.DragEvent): void {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setDragOver(false);
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) handleFiles(Array.from(files));
  }

  /** 当前展示的错误消息：本地校验失败优先，否则 status=error 时用 store.error（HTTP 错）。 */
  const displayError = localError ?? (status === 'error' ? storeError : null);
  /** 已解析裁片总数（done 态展示）。 */
  const totalPieces = doc ? countTotalPieces(doc) : 0;

  return (
    <aside
      className="panel upload-panel"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <h2>DXF 上传预览</h2>

      {/* 状态反馈区：uploading / done / error 三态互斥（idle 不渲染） */}
      {status === 'uploading' && (
        <div className="upload-status loading" data-testid="upload-status">
          上传中…
        </div>
      )}
      {status === 'done' && doc && (
        <div className="upload-status done" data-testid="upload-status">
          <div className="upload-filename">{doc.filename}</div>
          <div className="upload-summary">
            已解析 {doc.sizes.length} 码 / {totalPieces} 裁片
          </div>
        </div>
      )}
      {displayError && (
        <div className="upload-status error" data-testid="upload-status">
          {displayError}
        </div>
      )}

      {/* US-021 commit 状态行：独立于 parse status，只在 commitStatus!==idle 时渲染。
          commit 由 useParseDxf 在 parse done 后自动触发（D1 副作用），此区域只读不触发。
          - committing → 「应用中…」loading（复用 .upload-status.loading 暗绿底）。
          - done + commitSummary → 「已应用至超排：N 裁片，M 码」暗绿底（复用 .upload-status.done）。
          - error + commitError → 红字「应用失败：<msg>」（复用 .upload-status.error）。 */}
      {commitStatus === 'committing' && (
        <div className="upload-status loading" data-testid="commit-status">
          应用中…
        </div>
      )}
      {commitStatus === 'done' && commitSummary && (
        <div className="upload-status done" data-testid="commit-status">
          已应用至超排：{commitSummary.n_pieces} 裁片，{commitSummary.sizes.length} 码
        </div>
      )}
      {commitStatus === 'error' && commitError && (
        <div className="upload-status error" data-testid="commit-status">
          应用失败：{commitError}
        </div>
      )}

      {/* 拖拽落区（也响应 click + 键盘 Enter/Space 触发文件选择，符合 a11y） */}
      <div
        className={`drop-zone${dragOver ? ' dragover' : ''}`}
        data-tour="drop-zone"
        onClick={handlePickClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handlePickClick();
          }
        }}
      >
        <div className="drop-zone-text">{dragOver ? '松开以上传' : '拖拽 DXF 到此'}</div>
        <div className="drop-zone-hint">或点击下方按钮选择文件</div>
      </div>

      {/* 隐藏 input + 显式按钮（AC#1 点击上传按钮，与 drop-zone 双入口） */}
      <input
        ref={inputRef}
        type="file"
        accept=".dxf"
        className="upload-input-hidden"
        onChange={handleInputChange}
      />
      <button
        type="button"
        className="upload-btn"
        onClick={handlePickClick}
        disabled={status === 'uploading'}
      >
        {status === 'done' ? '重新上传' : '选择 DXF 文件'}
      </button>

      <div className="hint">
        仅支持 .dxf 母版文件；单文件，最大 {MAX_UPLOAD_BYTES / 1024 / 1024}MB。
      </div>
    </aside>
  );
}

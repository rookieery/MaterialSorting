// SamplePicker —— 上传预览左侧「样例」区块（2026-09-16）。
//
// 职责：
//   1. mount 时 GET /api/samples 拉 data/ 顶层 .dxf 清单 → 填充 select，
//      默认选中第一个（用户需求：默认选择第一个文件）。
//   2. 「应用」= GET /api/samples/file?name=<选中名>（encodeURIComponent ——
//      样例名含中文/#/（）等 URI 保留字符，走 query 参数）取回字节包成
//      File → 复用 useParseDxf.upload —— 与本地上传逐字节同路：
//      parse → 预览 → 自动 commit 至超排（上传状态行 / 数量矩阵 / Tab 解锁
//      全部既有链路，本组件零新数据路径）。
//   3. 失败态红字（复用 .upload-status.error）：列表加载失败 / 取文件失败 /
//      应用失败共用一行，消息带场景前缀；成功路径无本组件级提示（面板上方
//      的 upload-status 已展示「已解析/已应用至超排」）。
//
// 设计原则（与 UploadPanel 同款约定）：
//   - HTTP 一律走 lib/api.apiFetch（注入 X-Session-Id + 会话先行门）。
//   - 防连击：applyingRef（立即生效）+ store status==='uploading' 双重防护
//     （与 useParseDxf.upload 内部防护同构 —— upload 自身也会静默忽略，此处
//     提前禁用按钮让 UI 状态先行）。
//   - effect 卸载 cancelled flag：StrictMode 双挂载 / 组件卸载后异步落定不写
//     state（React 18 警告防护，与项目内异步 effect 同模式）。
//   - 列表是叶子便利功能：本地 useState（不进 store）——面板常驻 DOM（切 Tab
//     display:none 不卸载），选择状态跨 Tab 保真。
//   - 沿用 style.css（.sample-* 前缀，.panel h2 同级标题），不引入 CSS 框架。

import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import { apiFetch } from '../../lib/api';
import { useParseDxf } from '../../hooks/useParseDxf';
import { useUploadStore } from '../../store/uploadStore';

/** 样例清单端点（dev 由 Vite proxy 转 :8010；prod 同源）。 */
const SAMPLES_URL = '/api/samples';

/** 样例取文件端点（?name= query，encodeURIComponent 编码）。 */
const SAMPLE_FILE_URL = '/api/samples/file';

/** 后端 GET /api/samples 响应条目。 */
interface SampleEntry {
  name: string;
  size_bytes: number;
}

export function SamplePicker(): JSX.Element | null {
  /** 样例清单（mount 一次拉取；空 = 无可用样例或加载失败）。 */
  const [samples, setSamples] = useState<SampleEntry[]>([]);
  /** 当前选中文件名（默认第一个；空串 = 无选择）。 */
  const [selected, setSelected] = useState('');
  /** 本组件级错误消息（列表/取文件/应用失败共用一行红字；null 不渲染）。 */
  const [error, setError] = useState<string | null>(null);
  /** 应用中 flag（驱动按钮禁用 + 文案「应用中…」）。 */
  const [applying, setApplying] = useState(false);
  /** 防连击 ref（setState 异步生效，第二次连击在调度前进 handler）。 */
  const applyingRef = useRef(false);

  // 订阅 uploadStore.status：上传中（含本组件触发的应用）禁用交互 —— 与
  // UploadPanel 选择文件按钮同款防护口径。
  const status = useUploadStore((s) => s.status);

  const { upload } = useParseDxf();

  // mount 拉样例清单：默认选第一个。失败 → 红字（区块保留，select 置空提示）。
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await apiFetch(SAMPLES_URL);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { samples?: SampleEntry[] };
        if (!Array.isArray(data.samples)) throw new Error('响应格式异常');
        if (cancelled) return;
        setSamples(data.samples);
        setSelected(data.samples[0]?.name ?? '');
      } catch (e) {
        if (cancelled) return;
        setError(`样例列表加载失败：${e instanceof Error ? e.message : String(e)}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** 应用选中样例：取字节 → 包 File → 走既有 upload（parse + 自动 commit）。 */
  async function handleApply(): Promise<void> {
    if (!selected || applyingRef.current) return;
    applyingRef.current = true;
    setApplying(true);
    setError(null);
    try {
      const res = await apiFetch(
        `${SAMPLE_FILE_URL}?name=${encodeURIComponent(selected)}`,
      );
      if (!res.ok) {
        // 后端 404/4xx 走 JSONResponse { error }（中文消息）
        let msg = res.statusText;
        try {
          msg = ((await res.json()) as { error?: string }).error || msg;
        } catch {
          // 非 JSON 响应 —— statusText 兜底
        }
        throw new Error(msg);
      }
      const blob = await res.blob();
      // 与本地上传同路：File 名 = 样例文件名（parse 响应 filename / 导出前缀同源）
      await upload(new File([blob], selected, { type: 'application/dxf' }));
    } catch (e) {
      setError(`应用失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      applyingRef.current = false;
      setApplying(false);
    }
  }

  const busy = applying || status === 'uploading';

  return (
    <div className="sample-section" data-testid="sample-section">
      <h2>样例</h2>
      <div className="sample-row">
        <select
          className="sample-select"
          data-testid="sample-select"
          value={selected}
          title={selected || undefined}
          disabled={busy || samples.length === 0}
          onChange={(e) => setSelected(e.target.value)}
        >
          {samples.length === 0 && <option value="">（无可用样例）</option>}
          {samples.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="sample-apply-btn"
          data-testid="sample-apply"
          disabled={busy || !selected}
          onClick={() => {
            void handleApply();
          }}
        >
          {applying ? '应用中…' : '应用'}
        </button>
      </div>
      {error && (
        <div className="upload-status error" data-testid="sample-error">
          {error}
        </div>
      )}
    </div>
  );
}

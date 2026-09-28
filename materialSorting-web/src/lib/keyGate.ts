// keyGate.ts —— 三入口运行前 key 预检（prd-key-authorization-system US-007）。
//
// 数据源 = 后端 POST /api/key/precheck（US-005 routes_key.py）：keygate.
// ensure_run_allowed(doc_source, deduct=False) —— 与真跑闸门（WS /ws/solve、
// /api/strategy|extreme/start）**同一判定序**，唯一差异是不扣次不动账。三个
// 前端入口（普通运行 ControlPanel.handleStart / 高级·极限 strategyStore.start）
// 在发起真正请求前共用本函数，key 失效时得到即时中文反馈而非跑一半失败：
//
//   - 拦截口径「宽容放行」：**仅显式 ``ok === false`` 拦截**。后端契约恒带 ok
//     键（200 {ok:true[,reason]} | {ok:false,message}）；半截响应 / 无 ok 键的
//     200（mock fetch 兜底分支等）一律放行 —— 前端预检是 UX 前置，权威闸门在
//     后端 US-005（fail-closed），预检漏拦最多晚一拍由后端拦下，绝不误拦。
//   - 失败文案 = 后端 message 原样透传（含断网文案「无法连接授权服务器，请检
//     查网络后重试」—— keyserver 不可达由**后端 precheck 映射**，前端不自行
//     判断网络）；仅 MS 后端自身 fetch 抛错时用本地兜底文案（此时 WS / /start
//     同样连不上，拦截语义自洽）。三入口共用本函数 → 文案天然一致。
//   - 失败经 toastStore 弹中文错误（非阻断轻提示；调用方各自另有展示位：
//     ControlPanel onStatus → StatusLine，strategyStore errorMessage → 弹窗
//     既有渲染位）。
//   - ``doc_source`` = uploadStore 当前 doc 的 filename —— 与后端闸门口径对齐：
//     WS 闸门取 state['doc']['source'] 的 basename 判样例豁免，而 commit 时
//     source = 前端上传的原文件名（样例应用 = File 名即样例名），basename 同值
//     → 样例母版在 precheck 同样豁免，不误拦（US-010 三入口样例免闸 E2E 依赖）。
//
// 分层：lib 层引用 store 有先例（sessionRecovery/sessionCheckpoint 均引 store）；
// 本模块只读 uploadStore.doc（现取快照）+ toastStore.pushToast。

import { apiFetch } from './api';
import { useToastStore } from '../store/toastStore';
import { useUploadStore } from '../store/uploadStore';

/** 预检结果：ok=true 放行（reason = 豁免原因 'off'/'sample'，debug 可观测）；
 * ok=false 拦截（message = 可直接上屏的中文文案）。 */
export type RunGateResult = { ok: true; reason?: string } | { ok: false; message: string };

/** MS 后端自身不可达时的兜底文案（keyserver 侧断网文案由后端透传，非此处）。 */
const MSG_NET = '无法连接服务器，请检查网络后重试';

/** 错误响应体读中文 {error}（缺失/非 JSON → HTTP 状态兜底文案；keyStore 同款）。 */
async function readErrorMessage(res: Response, fallbackPrefix: string): Promise<string> {
  let msg = `${fallbackPrefix}（HTTP ${res.status}）`;
  try {
    const data = (await res.json()) as { error?: unknown } | null;
    if (data && typeof data.error === 'string' && data.error !== '') msg = data.error;
  } catch {
    /* 非 JSON 错误体 → 保留兜底文案 */
  }
  return msg;
}

/** 统一失败出口：Toast 弹中文错误 + 返回 {ok:false, message}（调用方另有展示位）。 */
function gateFail(message: string): RunGateResult {
  useToastStore.getState().pushToast(message);
  return { ok: false, message };
}

/**
 * 运行前 key 预检（三入口共用）：POST /api/key/precheck（doc_source 随当前 doc）。
 *
 * 契约见文件头。永不抛错（网络异常也返回 {ok:false}）—— 调用方无需 try/catch。
 */
export async function ensureRunAllowed(): Promise<RunGateResult> {
  const docSource = useUploadStore.getState().doc?.filename ?? null;
  try {
    const r = await apiFetch('/api/key/precheck', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_source: docSource }),
    });
    // 契约上 precheck 恒 200（结果自描述）；非 2xx（旧后端 404 等）→ 拦下并透
    // 传 error 文案（无 {error} 用 HTTP 兜底）。
    if (!r.ok) return gateFail(await readErrorMessage(r, '运行前校验失败'));
    let data: unknown = null;
    try {
      data = await r.json();
    } catch {
      /* 半截响应体 → 无 ok 键，宽容放行（权威闸门在后端） */
    }
    const d =
      data !== null && typeof data === 'object'
        ? (data as { ok?: unknown; message?: unknown; reason?: unknown })
        : null;
    if (d !== null && d.ok === false) {
      const message =
        typeof d.message === 'string' && d.message !== ''
          ? d.message
          : '授权校验未通过，请检查 key 状态';
      return gateFail(message);
    }
    return { ok: true, ...(typeof d?.reason === 'string' ? { reason: d.reason } : {}) };
  } catch {
    // MS 后端不可达（fetch 抛错 / 会话阻断拦截）—— 本地兜底文案，三入口一致。
    return gateFail(MSG_NET);
  }
}

// FormState store —— ControlPanel 表单状态的唯一归宿（状态文件 US-003）。
//
// 背景：form 原是 ControlPanel 本地 useState（2026-08-27 重传联动 effect 挂在
// 组件内）。状态文件保存要读 form（buildSavePayload）、恢复要写 form
// （US-004 applyRestorePayload 注表单）—— 本地 state 无法跨模块读写，故上提
// store；ControlPanel 行为（含 docId 变更重置 DEFAULT_FORM）与重构前完全一致
// 是硬红线（既有 vitest 全绿 = 回归门）。
//
// 水合与重置的博弈（设计 §六.1，前端唯一中风险点）：
//   - hydrate(form, token)：恢复编排把状态文件的 form 块按 token（= 恢复响应
//     新 doc_id）写回 —— 立即生效并记 token；
//   - resetForDoc(docId)：ControlPanel useEffect([docId]) 唯一调用方 ——
//     token 匹配 → 保留水合表单（水合优先于 docId 重置）；否则回 DEFAULT_FORM
//     并清 token。两条写回顺序（先 hydrate 后换 doc / 先换 doc 后 hydrate）
//     终态一致：token 单射 + 恢复每次铸新 doc_id，无假匹配面；
//   - 幂等：resetForDoc(同 docId) 多次调用（StrictMode 双 effect）不重置已
//     水合表单 —— 匹配即保留、不消费 token。
//
// 不变量：DEFAULT_FORM 是模块常量且 patch/hydrate 恒建新对象不原地改，共享
// 引用安全（与旧本地 state 时代同约定）。

import { create } from 'zustand';
import { DEFAULT_FORM, type FormState } from '../lib/params';

export interface FormStateStore {
  /** ControlPanel 表单当前值（字段按 input.value 字符串持有，lib/params 同构）。 */
  form: FormState;
  /** 当前水合载荷所属 doc_id（null = 无水合；见文件头「水合与重置的博弈」）。 */
  hydratedToken: string | null;
  /** 局部字段更新（ControlPanel patch 同语义：浅合并建新对象）。 */
  patch: (p: Partial<FormState>) => void;
  /**
   * 水合（US-004 恢复编排接线）：form 块缺键时按 DEFAULT_FORM 兜底合并（手改
   * 文件容错）；token = 本载荷所属 doc_id。
   */
  hydrate: (form: FormState, token: string) => void;
  /**
   * docId 变化重置（ControlPanel useEffect([docId]) 挂点）：无本 docId 的水合
   * 载荷 → DEFAULT_FORM；有 → 保留（水合优先）。
   */
  resetForDoc: (docId: string | undefined) => void;
  /** 全量重置（测试隔离用）。 */
  reset: () => void;
}

export const useFormStore = create<FormStateStore>((set) => ({
  form: DEFAULT_FORM,
  hydratedToken: null,
  patch: (p) => set((s) => ({ form: { ...s.form, ...p } })),
  hydrate: (form, token) => set({ form: { ...DEFAULT_FORM, ...form }, hydratedToken: token }),
  resetForDoc: (docId) =>
    set((s) =>
      docId !== undefined && s.hydratedToken === docId
        ? { hydratedToken: s.hydratedToken }
        : { form: DEFAULT_FORM, hydratedToken: null },
    ),
  reset: () => set({ form: DEFAULT_FORM, hydratedToken: null }),
}));

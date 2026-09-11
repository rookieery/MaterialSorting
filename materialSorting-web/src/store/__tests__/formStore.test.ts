// formStore 单测（状态文件 US-003）。
//
// 覆盖面（设计 §六.1 —— 「前端唯一中风险点」）：
//   - patch 浅合并建新对象（DEFAULT_FORM 不被原地改）；
//   - resetForDoc：无水合载荷 → DEFAULT_FORM（docId 变更重置语义与旧本地 state
//     时代完全一致 = 硬红线）；
//   - hydrate(form, token)：立即生效 + 记 token；缺键按 DEFAULT_FORM 兜底合并；
//   - 水合优先于 docId 重置：hydrate 后 resetForDoc(同 token) 保留表单
//     （含 StrictMode 双 effect 幂等 —— 同 token 多次 resetForDoc 不重置）；
//   - resetForDoc(不同 docId / undefined) → DEFAULT_FORM 且清 token（假匹配无面：
//     恢复每次铸新 doc_id，token 单射）；
//   - 两种写回顺序（先 hydrate 后换 doc / 先换 doc 后 hydrate）终态一致。

import { beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_FORM, type FormState } from '../../lib/params';
import { useFormStore } from '../formStore';

/** 编辑过的表单夹具（与 DEFAULT_FORM 逐字段可区分）。 */
function editedForm(): FormState {
  return {
    sizes: [30, 34],
    gate: '180.50',
    time: '60',
    seed: '7',
    multi_seed: true,
    seed_count: '4',
    per_type: { g02: { d: '2', tol: '1' } },
    band_enabled: true,
    band_label: 'g05',
    prefix_enabled: true,
    prefix_front: 'g02',
    prefix_back: 'g03',
  };
}

beforeEach(() => {
  useFormStore.getState().reset();
});

describe('formStore patch（US-003）', () => {
  it('patch 浅合并部分字段，其余保留', () => {
    useFormStore.getState().patch({ gate: '160.00' });
    const f = useFormStore.getState().form;
    expect(f.gate).toBe('160.00');
    expect(f.time).toBe(DEFAULT_FORM.time);
    expect(f.sizes).toEqual([]);
  });

  it('patch 恒建新对象 —— DEFAULT_FORM 模块常量不被原地改', () => {
    useFormStore.getState().patch({ sizes: [30] });
    expect(DEFAULT_FORM.sizes).toEqual([]);
    expect(useFormStore.getState().form.sizes).toEqual([30]);
  });
});

describe('formStore resetForDoc：docId 变更重置（行为等价硬红线）', () => {
  it('无水合载荷 → DEFAULT_FORM（含幅宽 175.00 / 时长 120 / band·prefix 关）', () => {
    useFormStore.getState().patch({ gate: '199.00', band_enabled: true, band_label: 'g05' });
    useFormStore.getState().resetForDoc('master-b');
    expect(useFormStore.getState().form).toBe(DEFAULT_FORM);
    expect(useFormStore.getState().hydratedToken).toBeNull();
  });

  it('docId=undefined（mount 时 doc=null）→ 同样回默认', () => {
    useFormStore.getState().patch({ time: '60' });
    useFormStore.getState().resetForDoc(undefined);
    expect(useFormStore.getState().form).toBe(DEFAULT_FORM);
  });

  it('docId 不变化的直接重复调用幂等（DEFAULT_FORM 再 reset 仍默认）', () => {
    useFormStore.getState().resetForDoc('master-a');
    useFormStore.getState().resetForDoc('master-a');
    expect(useFormStore.getState().form).toBe(DEFAULT_FORM);
  });
});

describe('formStore hydrate：水合优先于 docId 重置（US-004 恢复编排地基）', () => {
  it('hydrate 立即生效并记 token', () => {
    const payload = editedForm();
    useFormStore.getState().hydrate(payload, 'restored-1');
    expect(useFormStore.getState().form).toEqual(payload);
    expect(useFormStore.getState().hydratedToken).toBe('restored-1');
  });

  it('缺键按 DEFAULT_FORM 兜底合并（手改文件容错）', () => {
    useFormStore.getState().hydrate({ gate: '180.00' } as Partial<FormState> as FormState, 't');
    const f = useFormStore.getState().form;
    expect(f.gate).toBe('180.00');
    expect(f.time).toBe(DEFAULT_FORM.time);
    expect(f.sizes).toEqual([]);
  });

  it('hydrate 后 resetForDoc(同 token) → 保留水合表单（水合优先于重置）', () => {
    const payload = editedForm();
    useFormStore.getState().hydrate(payload, 'restored-1');
    useFormStore.getState().resetForDoc('restored-1');
    expect(useFormStore.getState().form).toEqual(payload);
  });

  it('同 token 多次 resetForDoc 不重置（StrictMode 双 effect 幂等）', () => {
    useFormStore.getState().hydrate(editedForm(), 'restored-1');
    useFormStore.getState().resetForDoc('restored-1');
    useFormStore.getState().resetForDoc('restored-1');
    expect(useFormStore.getState().form).toEqual(editedForm());
  });

  it('水合后换新母版（不同 docId）→ DEFAULT_FORM 且清 token', () => {
    useFormStore.getState().hydrate(editedForm(), 'restored-1');
    useFormStore.getState().resetForDoc('master-b');
    expect(useFormStore.getState().form).toBe(DEFAULT_FORM);
    expect(useFormStore.getState().hydratedToken).toBeNull();
  });

  it('两种写回顺序终态一致：先换 doc 后 hydrate（effect 先跑，hydrate 补写）', () => {
    useFormStore.getState().patch({ gate: '190.00' });
    // 模拟 US-004 编排 B 顺序：uploadStore doc 就绪（effect 触发 reset）→ hydrate
    useFormStore.getState().resetForDoc('restored-2');
    const payload = editedForm();
    useFormStore.getState().hydrate(payload, 'restored-2');
    expect(useFormStore.getState().form).toEqual(payload);
    // 之后的 StrictMode 二次 effect（同 docId）不再重置
    useFormStore.getState().resetForDoc('restored-2');
    expect(useFormStore.getState().form).toEqual(payload);
  });
});

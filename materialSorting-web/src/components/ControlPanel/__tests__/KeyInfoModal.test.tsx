// key 授权 US-006 KeyInfoModal 组件测试（US-011 ② 区块表格化改版）：
//   1. 未绑定态：空输入 + 引导文案（placeholder / 属性区空态提示 / 表格空态）
//   2. localStorage ms_key 即时预填（不等网络）→ GET /api/key/state 对账以后端
//      为准（输入框随 store.key 更新，用户未编辑不被覆盖）
//   3. 属性展示：次数型 总数/已用/剩余 + 徽标；时长型 生效/截止/剩余天数 +
//      失效徽标（已过期红）；绑定系统/备注不渲染（后台管理端内容，响应仍下发）；
//      key 已删除自动解绑（key:null + error）→ 未绑定态 + 解释红字
//   4. ① 保存：POST /api/key/save 失败 400 {error} 中文红字透传 + 输入框回退
//      实际绑定 key（与属性区恒同 key）；成功后属性更新
//   5. ② 系统可使用的key 表格（US-011）：GET /api/key/list 渲染四列（名称=明文/
//      类型/剩余天|次/操作图标）；正在启用行置顶高亮 + 启用置灰；合并按钮可见
//      性矩阵（仅时长型非启用行 / 无正在使用 key 全隐藏）；点启用 = save(行key)
//      + 输入框对齐；点合并 = merge 单 source + 一行明细；失败红字；list error
//      红字降级
//   6. ESC / 遮罩 / ✕ 只关弹窗（ExportInfoModal 同款骨架）
//   7. 单例互斥：openModal 覆写后本弹窗卸载（controlPanelStore 单字段）
//
// 套路同 ExportInfoModal 既有用例：createRoot + act + data-testid；
// markSessionProbedForTest 跳过会话先行探测；keyStore 每测 __resetKeyStoreForTest
// （store.key 重读 localStorage 镜像 —— 预填口径的隔离锚点）。

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { KeyInfoModal } from '../KeyInfoModal';
import { markSessionProbedForTest, resetSessionForTest } from '../../../lib/api';
import { useControlPanelStore } from '../../../store/controlPanelStore';
import {
  KEY_MIRROR_STORAGE,
  __resetKeyStoreForTest,
} from '../../../store/keyStore';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;
let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;

let statePayload: unknown = { key: null, info: null, error: null };
let listPayload: unknown = { keys: [], error: null };
let saveStatus = 200;
let savePayload: unknown = { saved: true, key: 'MS-SAVE', info: null };
let saveErrorText = 'key 不存在：请检查输入是否正确';
let mergeStatus = 200;
let mergePayload: unknown = null;
let mergeErrorText = '未绑定授权 key：请在「系统key」中输入并保存';
let saveBodies: unknown[] = [];
let mergeBodies: unknown[] = [];

const COUNT_INFO = {
  type: 'count',
  status: '正在使用',
  bound_system_name: 'PC-FACTORY',
  remark: '车间一',
  total_uses: 30,
  used_uses: 12,
  remaining_uses: 18,
};

const DURATION_INFO = {
  type: 'duration',
  status: '已过期',
  bound_system_name: 'PC-FACTORY',
  remark: null,
  activated_at: '2026-08-28 10:00:00',
  expires_at: '2026-09-27 10:00:00',
  remaining_days: 0,
};

const MERGE_OK = {
  target: {
    type: 'duration', status: '正在使用', bound_system_name: 'PC-FACTORY',
    remark: null, activated_at: '2026-09-28 10:00:00',
    expires_at: '2026-11-02 10:00:00', remaining_days: 35,
  },
  sources: [
    { key: 'MS-A', transferred_days: 10.5 },
  ],
  total_transferred_days: 10.5,
};

/** ② 表格夹具（backend 新→旧序）：正在启用的 MS-TARGET 在末位 → 渲染时应置顶。 */
const LIST_ROWS = {
  keys: [
    { key: 'MS-COUNT-2', type: 'count', status: '正在使用', bound_system_name: 'PC',
      remark: null, total_uses: 30, used_uses: 12, remaining_uses: 18 },
    { key: 'MS-DUR-NEW', type: 'duration', status: '正在使用', bound_system_name: 'PC',
      remark: null, activated_at: '2026-09-28 10:00:00',
      expires_at: '2026-10-28 10:00:00', remaining_days: 29 },
    { key: 'MS-TARGET', type: 'duration', status: '正在使用', bound_system_name: 'PC',
      remark: null, activated_at: '2026-09-01 10:00:00',
      expires_at: '2026-10-01 10:00:00', remaining_days: 2 },
  ],
  error: null,
};

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

beforeEach(() => {
  localStorage.clear();
  __resetKeyStoreForTest();
  markSessionProbedForTest();
  useControlPanelStore.getState().closeModal();
  statePayload = { key: null, info: null, error: null };
  listPayload = { keys: [], error: null };
  saveStatus = 200;
  savePayload = { saved: true, key: 'MS-SAVE', info: null };
  saveErrorText = 'key 不存在：请检查输入是否正确';
  mergeStatus = 200;
  mergePayload = null;
  mergeErrorText = '未绑定授权 key：请在「系统key」中输入并保存';
  saveBodies = [];
  mergeBodies = [];
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/key/state')) {
      return Promise.resolve(json(statePayload));
    }
    if (url.includes('/api/key/list')) {
      return Promise.resolve(json(listPayload));
    }
    if (url.includes('/api/key/save')) {
      saveBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      if (saveStatus !== 200) return Promise.resolve(json({ error: saveErrorText }, saveStatus));
      return Promise.resolve(json(savePayload));
    }
    if (url.includes('/api/key/merge')) {
      mergeBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      if (mergeStatus !== 200) return Promise.resolve(json({ error: mergeErrorText }, mergeStatus));
      return Promise.resolve(json(mergePayload ?? MERGE_OK));
    }
    return Promise.resolve(json({}));
  }) as (...args: unknown[]) => Promise<Response>);
});

afterEach(() => {
  if (root) {
    const r = root;
    act(() => {
      r.unmount();
    });
    root = null;
  }
  container?.remove();
  container = null;
  fetchSpy?.mockRestore();
  resetSessionForTest();
  localStorage.clear();
  useControlPanelStore.getState().closeModal();
});

function renderModal(): void {
  act(() => {
    root!.render(<KeyInfoModal />);
  });
}

function openModal(): void {
  act(() => {
    useControlPanelStore.getState().openModal('key_info');
  });
}

async function flush(times = 3): Promise<void> {
  for (let i = 0; i < times; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

/** 模拟用户输入（React 受控 input/textarea：原生 value setter + input 事件）。 */
function setInputValue(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const proto = el instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

function modal(): HTMLElement {
  return document.querySelector('.strategy-modal')!;
}

function keyInput(): HTMLInputElement {
  return modal().querySelector<HTMLInputElement>('[data-testid="key-info-key-input"]')!;
}

function attrText(testid: string): string {
  return modal().querySelector(`[data-testid="${testid}"]`)!.textContent ?? '';
}

describe('KeyInfoModal 未绑定态（默认）', () => {
  it('空输入 + 引导 placeholder + 属性区空态引导文案（三区块齐备）', async () => {
    renderModal();
    openModal();
    await flush();
    expect(keyInput().value).toBe('');
    expect(keyInput().placeholder).toContain('输入授权 key');
    expect(modal().querySelector('[data-testid="key-info-empty-hint"]')!.textContent)
      .toContain('尚未绑定授权 key');
    // 三区块齐备：正在使用的key / 系统可使用的key 表格 / 属性
    expect(modal().querySelector('[data-testid="key-info-current"]')).not.toBeNull();
    expect(modal().querySelector('[data-testid="key-info-list"]')).not.toBeNull();
    expect(modal().querySelector('[data-testid="key-info-attrs"]')).not.toBeNull();
  });

  it('保存按钮空 key 置灰；表格空态引导（本机无可用 key）', async () => {
    renderModal();
    openModal();
    await flush();
    expect(modal().querySelector<HTMLButtonElement>('[data-testid="key-info-save"]')!.disabled)
      .toBe(true);
    expect(modal().querySelector('[data-testid="key-info-list-empty"]')!.textContent)
      .toContain('暂无绑定到本机的可用 key');
  });
});

describe('KeyInfoModal localStorage 即时预填 + 后端对账', () => {
  it('打开瞬间输入框即显镜像值（未 flush 网络未落定）', () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-LOCAL');
    __resetKeyStoreForTest(); // store.key 重读镜像
    renderModal();
    openModal();
    // 不 flush —— fetchState 尚未落定，输入框已是本地值
    expect(keyInput().value).toBe('MS-LOCAL');
  });

  it('对账以后端为准：state 返回另一 key → 输入框/镜像随之更新', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-LOCAL');
    __resetKeyStoreForTest();
    statePayload = { key: 'MS-SERVER', info: COUNT_INFO, error: null };
    renderModal();
    openModal();
    await flush();
    expect(keyInput().value).toBe('MS-SERVER');
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBe('MS-SERVER');
  });

  it('清缓存/换浏览器（无镜像）→ 后端 key_state.json 权威补回', async () => {
    statePayload = { key: 'MS-SERVER', info: COUNT_INFO, error: null };
    renderModal();
    openModal();
    expect(keyInput().value).toBe(''); // 打开瞬间无镜像 → 空
    await flush();
    expect(keyInput().value).toBe('MS-SERVER');
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBe('MS-SERVER');
  });

  it('用户编辑中的草稿不被对账回写覆盖（dirty 标记）', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-LOCAL');
    __resetKeyStoreForTest();
    statePayload = { key: 'MS-SERVER', info: null, error: null };
    renderModal();
    openModal();
    setInputValue(keyInput(), 'MS-TYPING');
    await flush();
    expect(keyInput().value).toBe('MS-TYPING');
  });
});

describe('KeyInfoModal ③ 属性展示 + 状态徽标', () => {
  it('次数型：总数/已用/剩余 + 正在使用绿徽标 + 绑定系统/备注不渲染', async () => {
    statePayload = { key: 'MS-K', info: COUNT_INFO, error: null };
    renderModal();
    openModal();
    await flush();
    expect(attrText('key-attr-total')).toContain('总次数');
    expect(attrText('key-attr-total')).toContain('30');
    expect(attrText('key-attr-used')).toContain('12');
    expect(attrText('key-attr-remaining')).toContain('18');
    // 绑定系统/备注 = 后台管理端内容，弹窗不展示（夹具仍带这两字段验证不渲染）
    expect(modal().querySelector('[data-testid="key-attr-system"]')).toBeNull();
    expect(modal().querySelector('[data-testid="key-attr-remark"]')).toBeNull();
    const badge = modal().querySelector('[data-testid="key-attr-status"] .key-status-badge')!;
    expect(badge.textContent).toBe('正在使用');
    expect(badge.classList.contains('ok')).toBe(true);
  });

  it('时长型：生效/截止/剩余天数 + 已过期红徽标', async () => {
    statePayload = { key: 'MS-K', info: DURATION_INFO, error: null };
    renderModal();
    openModal();
    await flush();
    expect(attrText('key-attr-activated')).toContain('2026-08-28 10:00:00');
    expect(attrText('key-attr-expires')).toContain('2026-09-27 10:00:00');
    expect(attrText('key-attr-days')).toContain('0');
    const badge = modal().querySelector('[data-testid="key-attr-status"] .key-status-badge')!;
    expect(badge.textContent).toBe('已过期');
    expect(badge.classList.contains('bad')).toBe(true);
  });

  it('keyserver 查询失败（error 字段）→ 属性区红字展示，本地 key 仍展示', async () => {
    statePayload = {
      key: 'MS-LOCAL',
      info: null,
      error: '无法连接授权服务器，请检查网络后重试',
    };
    renderModal();
    openModal();
    await flush();
    expect(modal().querySelector('[data-testid="key-info-attr-error"]')!.textContent)
      .toContain('无法连接授权服务器');
    expect(keyInput().value).toBe('MS-LOCAL');
  });

  it('key 已删除自动解绑（key:null + error）→ 未绑定态 + 解释红字 + 输入框空', async () => {
    statePayload = {
      key: null,
      info: null,
      error: '本地 key 已失效（key 不存在，可能已被删除），已自动解除绑定；请输入新 key 并保存',
    };
    renderModal();
    openModal();
    await flush();
    expect(modal().querySelector('[data-testid="key-info-unbound-reason"]')!.textContent)
      .toContain('已自动解除绑定');
    expect(modal().querySelector('[data-testid="key-info-empty-hint"]')).toBeNull();
    expect(keyInput().value).toBe('');            // 无用 key 不再上屏
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBeNull(); // 镜像同步清
  });
});

describe('KeyInfoModal ① 保存（POST /api/key/save）', () => {
  it('失败 400 {error} → 中文红字透传，输入框回退实际绑定 key（与属性区同 key）', async () => {
    statePayload = { key: 'MS-OLD', info: DURATION_INFO, error: null };
    saveStatus = 400;
    renderModal();
    openModal();
    await flush();
    setInputValue(keyInput(), 'MS-BAD');
    await act(async () => {
      modal().querySelector<HTMLButtonElement>('[data-testid="key-info-save"]')!.click();
      await Promise.resolve();
    });
    await flush();
    expect(modal().querySelector('[data-testid="key-info-save-error"]')!.textContent)
      .toBe('key 不存在：请检查输入是否正确');
    expect(keyInput().value).toBe('MS-OLD'); // 回退实际生效 key，不残留失败草稿
    expect(attrText('key-attr-days')).toContain('0'); // 属性区照旧 = 实际绑定 key
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBe('MS-OLD'); // 失败不改镜像
  });

  it('成功 → 属性区即刻展示新 info + localStorage 双写', async () => {
    statePayload = { key: null, info: null, error: null };
    savePayload = { saved: true, key: 'MS-NEW', info: COUNT_INFO };
    renderModal();
    openModal();
    await flush();
    setInputValue(keyInput(), '  MS-NEW  ');
    await act(async () => {
      modal().querySelector<HTMLButtonElement>('[data-testid="key-info-save"]')!.click();
      await Promise.resolve();
    });
    await flush();
    expect(saveBodies).toEqual([{ key: 'MS-NEW' }]); // trim 上送
    expect(attrText('key-attr-remaining')).toContain('18');
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBe('MS-NEW');
  });
});

describe('KeyInfoModal ② 系统可使用的key 表格（US-011）', () => {
  it('四列渲染 + 正在启用行置顶高亮置灰 + 合并按钮可见性矩阵', async () => {
    statePayload = { key: 'MS-TARGET', info: DURATION_INFO, error: null };
    listPayload = LIST_ROWS;
    renderModal();
    openModal();
    await flush();
    const rows = modal().querySelectorAll('[data-testid="key-info-row"]');
    expect(rows).toHaveLength(3);
    // 正在启用行置顶（fixture 末位 → 渲染首位）+ 高亮 + 启用置灰 + 无合并按钮
    expect(rows[0].getAttribute('data-key')).toBe('MS-TARGET');
    expect(rows[0].getAttribute('data-active')).toBe('true');
    expect(rows[0].className).toContain('active');
    expect(rows[0].querySelector<HTMLButtonElement>('[data-testid="key-info-enable"]')!.disabled)
      .toBe(true);
    expect(rows[0].querySelector('[data-testid="key-info-merge-one"]')).toBeNull();
    // 次数型非启用行：名称/类型/剩余 + 启用可点 + 无合并按钮（仅时长型）
    const countCells = rows[1].querySelectorAll('td');
    expect(rows[1].getAttribute('data-key')).toBe('MS-COUNT-2');
    expect(countCells[0].textContent).toBe('MS-COUNT-2');
    expect(countCells[1].textContent).toBe('次数型');
    expect(countCells[2].textContent).toBe('18 次');
    expect(rows[1].querySelector<HTMLButtonElement>('[data-testid="key-info-enable"]')!.disabled)
      .toBe(false);
    expect(rows[1].querySelector('[data-testid="key-info-merge-one"]')).toBeNull();
    // 时长型非启用行：剩余天数 + 合并按钮在
    expect(rows[2].getAttribute('data-key')).toBe('MS-DUR-NEW');
    expect(rows[2].querySelectorAll('td')[2].textContent).toBe('29 天');
    expect(rows[2].querySelector('[data-testid="key-info-merge-one"]')).not.toBeNull();
  });

  it('点启用 → save(行key)（bind 幂等切换）+ 输入框对齐新 key', async () => {
    statePayload = { key: 'MS-TARGET', info: DURATION_INFO, error: null };
    listPayload = LIST_ROWS;
    savePayload = { saved: true, key: 'MS-DUR-NEW', info: null };
    renderModal();
    openModal();
    await flush();
    await act(async () => {
      modal().querySelectorAll<HTMLButtonElement>('[data-testid="key-info-enable"]')[2].click();
      await Promise.resolve();
    });
    await flush();
    expect(saveBodies).toEqual([{ key: 'MS-DUR-NEW' }]);
    expect(keyInput().value).toBe('MS-DUR-NEW'); // 与 ① 手输保存同一落定口径
  });

  it('点合并 → merge 单 source → 一行明细（无合计行）；target 新 info 上屏', async () => {
    statePayload = { key: 'MS-TARGET', info: DURATION_INFO, error: null };
    listPayload = LIST_ROWS;
    renderModal();
    openModal();
    await flush();
    await act(async () => {
      modal().querySelector<HTMLButtonElement>('[data-testid="key-info-merge-one"]')!.click();
      await Promise.resolve();
    });
    await flush();
    expect(mergeBodies).toEqual([{ source_keys: ['MS-DUR-NEW'] }]);
    const detailRows = modal().querySelectorAll('[data-testid="key-info-merge-row"]');
    expect(detailRows).toHaveLength(1);
    expect(detailRows[0].textContent).toBe('MS-A 已合并：+10.5 天');
    expect(modal().querySelector('[data-testid="key-info-merge-total"]')).toBeNull();
    // target 新 info 即刻上屏（新截止 2026-11-02）
    expect(attrText('key-attr-expires')).toContain('2026-11-02 10:00:00');
  });

  it('合并整体失败（无 key 指路文案）→ 红字，无明细', async () => {
    statePayload = { key: 'MS-TARGET', info: DURATION_INFO, error: null };
    listPayload = LIST_ROWS;
    mergeStatus = 400;
    renderModal();
    openModal();
    await flush();
    await act(async () => {
      modal().querySelector<HTMLButtonElement>('[data-testid="key-info-merge-one"]')!.click();
      await Promise.resolve();
    });
    await flush();
    expect(modal().querySelector('[data-testid="key-info-merge-error"]')!.textContent)
      .toBe('未绑定授权 key：请在「系统key」中输入并保存');
    expect(modal().querySelector('[data-testid="key-info-merge-result"]')).toBeNull();
  });

  it('本机无正在使用 key（本地未绑定）→ 全行无合并按钮（无 target），启用可用', async () => {
    statePayload = { key: null, info: null, error: null };
    listPayload = LIST_ROWS;
    renderModal();
    openModal();
    await flush();
    expect(modal().querySelectorAll('[data-testid="key-info-row"]')).toHaveLength(3);
    expect(modal().querySelectorAll('[data-testid="key-info-merge-one"]')).toHaveLength(0);
    expect(modal().querySelectorAll<HTMLButtonElement>('[data-testid="key-info-enable"]')[0].disabled)
      .toBe(false);
  });

  it('list 查询失败（keyserver 断网）→ 表格区红字降级', async () => {
    listPayload = { keys: [], error: '无法连接授权服务器，请检查网络后重试' };
    renderModal();
    openModal();
    await flush();
    expect(modal().querySelector('[data-testid="key-info-list-error"]')!.textContent)
      .toContain('无法连接授权服务器');
    expect(modal().querySelector('[data-testid="key-info-table"]')).toBeNull();
  });
});

describe('KeyInfoModal 关闭行为（ExportInfoModal 同款）', () => {
  it('ESC / 遮罩 / ✕ 只关弹窗', async () => {
    statePayload = { key: 'MS-K', info: COUNT_INFO, error: null };
    renderModal();
    openModal();
    await flush();
    expect(document.querySelector('[data-testid="key-info-overlay"]')).not.toBeNull();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(document.querySelector('[data-testid="key-info-overlay"]')).toBeNull();
    // 重开 → 遮罩点击关闭（mousedown 落在遮罩自身）
    openModal();
    await flush();
    act(() => {
      const overlay = document.querySelector<HTMLElement>('[data-testid="key-info-overlay"]')!;
      overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    });
    expect(document.querySelector('[data-testid="key-info-overlay"]')).toBeNull();
    // 重开 → ✕ 关闭
    openModal();
    await flush();
    await act(async () => {
      modal().querySelector<HTMLButtonElement>('[data-testid="key-info-close"]')!.click();
      await Promise.resolve();
    });
    expect(document.querySelector('[data-testid="key-info-overlay"]')).toBeNull();
  });

  it('单例互斥：openModal 覆写其他弹窗 → 本弹窗卸载', async () => {
    statePayload = { key: null, info: null, error: null };
    renderModal();
    openModal();
    await flush();
    expect(document.querySelector('[data-testid="key-info-overlay"]')).not.toBeNull();
    act(() => {
      useControlPanelStore.getState().openModal('per_type');
    });
    expect(document.querySelector('[data-testid="key-info-overlay"]')).toBeNull();
    expect(useControlPanelStore.getState().modal).toBe('per_type');
  });
});

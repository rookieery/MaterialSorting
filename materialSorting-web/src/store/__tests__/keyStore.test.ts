// key 授权 US-006 keyStore 单测：四端点 fetch 契约 + localStorage ms_key 镜像口径。
//   - 初值：模块求值即读镜像（localStorage 预填 → store.key，不等网络）
//   - fetchState：对账以后端为准（后端 key 覆写本地 / null → removeItem 镜像）；
//     error 字段进 state（keyserver 失败也 200）
//   - fetchKeyList（US-011）：GET /api/key/list → keyList 落定（明文行 + 畸形行
//     滤出）；error 字段 → listError 红字降级；save/merge 成功链式刷新表格
//   - saveKey：POST /api/key/save {key}；成功双写（state + localStorage）+
//     keyInfo 落定；400 {error} 中文透传进 saveError 且不动旧 key / 镜像
//   - mergeKeys：POST /api/key/merge {source_keys}（strip + 过滤空行在 store 内
//     再兜一层）；成功 mergeResult 明细 + keyInfo = target；400 透传 mergeError
//   - 代际号：save 成功后迟到的 state 响应被丢弃（不覆盖新 key）

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import {
  KEY_MIRROR_STORAGE,
  __resetKeyStoreForTest,
  useKeyStore,
} from '../keyStore';
import { markSessionProbedForTest, resetSessionForTest } from '../../lib/api';

let fetchSpy: MockInstance<(...args: unknown[]) => Promise<Response>> | null = null;
/** 各端点当前回包 / 状态（每测可覆写）。 */
let statePayload: unknown = { key: null, info: null, error: null };
let stateStatus = 200;
let listPayload: unknown = { keys: [], error: null };
let saveStatus = 200;
let savePayload: unknown = { saved: true, key: 'MS-SAVE', info: null };
let saveErrorText = 'key 不存在：请检查输入是否正确';
let mergeStatus = 200;
let mergePayload: unknown = null;
let mergeErrorText = '未绑定授权 key：请在「系统key」中输入并保存';
let saveBodies: unknown[] = [];
let mergeBodies: unknown[] = [];
let listCalls = 0;

const COUNT_INFO = {
  type: 'count',
  status: '正在使用',
  bound_system_name: 'PC-FACTORY',
  remark: 'PC-FACTORY',
  total_uses: 30,
  used_uses: 12,
  remaining_uses: 18,
};

const LIST_OK = {
  keys: [
    { key: 'MS-DUR-NEW', type: 'duration', status: '正在使用',
      bound_system_name: 'PC-FACTORY', remark: null,
      activated_at: '2026-09-28 10:00:00', expires_at: '2026-10-28 10:00:00',
      remaining_days: 29 },
    { key: 'MS-COUNT-2', type: 'count', status: '正在使用',
      bound_system_name: 'PC-FACTORY', remark: null,
      total_uses: 30, used_uses: 12, remaining_uses: 18 },
    { key: '', type: 'count' },        // 畸形行：空明文 → 滤出
    { nope: true },                    // 畸形行：无 type/key → 滤出
  ],
  error: null,
};

const MERGE_OK = {
  target: {
    type: 'duration', status: '正在使用', bound_system_name: 'PC-FACTORY',
    remark: 'PC-FACTORY', activated_at: '2026-09-28 10:00:00',
    expires_at: '2026-11-02 10:00:00', remaining_days: 35,
  },
  sources: [
    { key: 'MS-A', transferred_days: 10.5 },
    { key: 'MS-B', transferred_days: 4.5 },
  ],
  total_transferred_days: 15,
};

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status });
}

beforeEach(() => {
  localStorage.clear();
  __resetKeyStoreForTest();
  markSessionProbedForTest();
  statePayload = { key: null, info: null, error: null };
  stateStatus = 200;
  listPayload = { keys: [], error: null };
  saveStatus = 200;
  savePayload = { saved: true, key: 'MS-SAVE', info: null };
  saveErrorText = 'key 不存在：请检查输入是否正确';
  mergeStatus = 200;
  mergePayload = null;
  mergeErrorText = '未绑定授权 key：请在「系统key」中输入并保存';
  saveBodies = [];
  mergeBodies = [];
  listCalls = 0;
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((input: unknown, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/api/key/state')) {
      return Promise.resolve(json(statePayload, stateStatus));
    }
    if (url.includes('/api/key/list')) {
      listCalls += 1;
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
  fetchSpy?.mockRestore();
  fetchSpy = null;
  resetSessionForTest();
  localStorage.clear();
});

async function flush(times = 3): Promise<void> {
  for (let i = 0; i < times; i++) await Promise.resolve();
}

/** 链式（未 await 的）fetchKeyList 落定等待：Response.json() 的 body stream 读取
 *  跨 macrotask，microtask flush 推不动 —— 先真定时器转一圈事件循环再 flush。 */
async function flushMacro(): Promise<void> {
  await new Promise<void>((r) => setTimeout(r, 0));
  await flush();
}

describe('keyStore 初值：localStorage 镜像即时预填', () => {
  it('模块求值时 localStorage 有 ms_key → store.key 即为该值（不等网络）', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-LOCAL');
    vi.resetModules();
    const mod = await import('../keyStore');
    expect(mod.useKeyStore.getState().key).toBe('MS-LOCAL');
    expect(fetchSpy).not.toHaveBeenCalled(); // 纯本地读，零请求
  });

  it('镜像缺失/为空白 → 初值 null', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, '   ');
    vi.resetModules();
    const mod = await import('../keyStore');
    expect(mod.useKeyStore.getState().key).toBeNull();
  });
});

describe('keyStore.fetchState 对账（以后端为准）', () => {
  it('后端返回 key+info → 覆写 state + 镜像同步', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-STALE');
    __resetKeyStoreForTest();
    statePayload = { key: 'MS-SERVER', info: COUNT_INFO, error: null };
    await useKeyStore.getState().fetchState();
    await flush();
    const s = useKeyStore.getState();
    expect(s.key).toBe('MS-SERVER');
    expect(s.keyInfo).toEqual(COUNT_INFO);
    expect(s.error).toBeNull();
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBe('MS-SERVER');
  });

  it('后端 key=null（未绑定）→ 清镜像（后端文件权威）', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-STALE');
    __resetKeyStoreForTest();
    statePayload = { key: null, info: null, error: null };
    await useKeyStore.getState().fetchState();
    await flush();
    expect(useKeyStore.getState().key).toBeNull();
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBeNull();
  });

  it('keyserver 查询失败（error 字段，HTTP 仍 200）→ error 进 state，本地 key 保留', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-LOCAL');
    __resetKeyStoreForTest();
    statePayload = {
      key: 'MS-LOCAL',
      info: null,
      error: '无法连接授权服务器，请检查网络后重试',
    };
    await useKeyStore.getState().fetchState();
    await flush();
    const s = useKeyStore.getState();
    expect(s.key).toBe('MS-LOCAL');
    expect(s.keyInfo).toBeNull();
    expect(s.error).toBe('无法连接授权服务器，请检查网络后重试');
  });

  it('网络错（fetch reject）→ error 兜底文案，key 保留镜像值', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-LOCAL');
    __resetKeyStoreForTest();
    fetchSpy!.mockImplementation(() => Promise.reject(new Error('boom')));
    await useKeyStore.getState().fetchState();
    await flush();
    const s = useKeyStore.getState();
    expect(s.key).toBe('MS-LOCAL');
    expect(s.error).toBe('无法连接服务器，请检查网络后重试');
  });
});

describe('keyStore.fetchKeyList（US-011 表格数据源）', () => {
  it('成功 → keyList 落定（畸形行滤出），listError null', async () => {
    listPayload = LIST_OK;
    await useKeyStore.getState().fetchKeyList();
    await flush();
    const s = useKeyStore.getState();
    expect(s.keyList).toHaveLength(2);
    expect(s.keyList![0].key).toBe('MS-DUR-NEW');
    expect(s.keyList![0].remaining_days).toBe(29);
    expect(s.keyList![1].type).toBe('count');
    expect(s.listError).toBeNull();
  });

  it('keyserver 失败（error 字段，HTTP 仍 200）→ keys 置空 + listError 红字', async () => {
    listPayload = { keys: [], error: '无法连接授权服务器，请检查网络后重试' };
    await useKeyStore.getState().fetchKeyList();
    await flush();
    const s = useKeyStore.getState();
    expect(s.keyList).toEqual([]);
    expect(s.listError).toBe('无法连接授权服务器，请检查网络后重试');
  });

  it('非 2xx（旧后端等）→ listError HTTP 兜底文案', async () => {
    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes('/api/key/list')) return Promise.resolve(json({}, 502));
      return Promise.resolve(json({}));
    }) as (...args: unknown[]) => Promise<Response>);
    await useKeyStore.getState().fetchKeyList();
    await flush();
    expect(useKeyStore.getState().listError).toBe('获取可用 key 列表失败（HTTP 502）');
  });

  it('网络错 → listError 兜底文案', async () => {
    fetchSpy!.mockImplementation(() => Promise.reject(new Error('boom')));
    await useKeyStore.getState().fetchKeyList();
    await flush();
    expect(useKeyStore.getState().listError).toBe('无法连接服务器，请检查网络后重试');
  });

  it('saveKey 成功 → 链式刷新表格（启用/保存换了 key，高亮行随动）', async () => {
    savePayload = { saved: true, key: 'MS-NEW', info: COUNT_INFO };
    listPayload = LIST_OK;
    await useKeyStore.getState().saveKey('MS-NEW');
    await flushMacro(); // save 落定后链式 fetchKeyList 落定
    expect(listCalls).toBe(1); // save 成功尾部自动 fetchKeyList
    expect(useKeyStore.getState().keyList).toHaveLength(2);
  });

  it('mergeKeys 成功 → 链式刷新表格（被合并行已失效出表）', async () => {
    useKeyStore.setState({ key: 'MS-TARGET', keyInfo: null });
    listPayload = LIST_OK;
    await useKeyStore.getState().mergeKeys(['MS-A']);
    await flushMacro(); // merge 落定后链式 fetchKeyList 落定
    expect(listCalls).toBe(1);
    expect(useKeyStore.getState().keyList).toHaveLength(2);
  });

  it('saveKey 失败 → 不触发列表刷新', async () => {
    saveStatus = 400;
    await useKeyStore.getState().saveKey('MS-BAD');
    await flush();
    expect(listCalls).toBe(0);
  });
});

describe('keyStore.saveKey', () => {
  it('成功 → POST {key} + 双写（state key/keyInfo + localStorage）', async () => {
    savePayload = { saved: true, key: 'MS-NEW', info: COUNT_INFO };
    const ok = await useKeyStore.getState().saveKey('  MS-NEW  ');
    await flush();
    expect(ok).toBe(true);
    expect(saveBodies).toEqual([{ key: 'MS-NEW' }]); // trim 后上送
    const s = useKeyStore.getState();
    expect(s.key).toBe('MS-NEW');
    expect(s.keyInfo).toEqual(COUNT_INFO);
    expect(s.saving).toBe(false);
    expect(s.saveError).toBeNull();
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBe('MS-NEW');
  });

  it('400 {error} 中文透传 → saveError；旧 key 与镜像原样保留（bind 失败不落盘）', async () => {
    localStorage.setItem(KEY_MIRROR_STORAGE, 'MS-OLD');
    __resetKeyStoreForTest();
    saveStatus = 400;
    const ok = await useKeyStore.getState().saveKey('MS-BAD');
    await flush();
    expect(ok).toBe(false);
    const s = useKeyStore.getState();
    expect(s.key).toBe('MS-OLD');
    expect(s.saveError).toBe('key 不存在：请检查输入是否正确');
    expect(localStorage.getItem(KEY_MIRROR_STORAGE)).toBe('MS-OLD');
  });

  it('空 key（按钮置灰兜底）→ 不发请求直接 false', async () => {
    const ok = await useKeyStore.getState().saveKey('   ');
    expect(ok).toBe(false);
    expect(saveBodies).toHaveLength(0);
  });

  it('网络错 → saveError 兜底文案', async () => {
    fetchSpy!.mockImplementation(() => Promise.reject(new Error('boom')));
    const ok = await useKeyStore.getState().saveKey('MS-X');
    await flush();
    expect(ok).toBe(false);
    expect(useKeyStore.getState().saveError).toBe('无法连接服务器，请检查网络后重试');
  });

  it('save 成功后迟到的 state 响应被丢弃（代际号，不被旧快照覆盖）', async () => {
    // state 挂起；save 先落定 → 迟到 state（旧 key）不得覆盖 MS-NEW
    let lateState: ((r: Response) => void) | null = null;
    fetchSpy!.mockImplementation(((input: unknown) => {
      const url = String(input);
      if (url.includes('/api/key/state')) {
        return new Promise<Response>((resolve) => {
          lateState = resolve;
        });
      }
      if (url.includes('/api/key/save')) {
        return Promise.resolve(json({ saved: true, key: 'MS-NEW', info: COUNT_INFO }));
      }
      return Promise.resolve(json({}));
    }) as (...args: unknown[]) => Promise<Response>);
    const p = useKeyStore.getState().fetchState();
    await useKeyStore.getState().saveKey('MS-NEW');
    await flush();
    expect(useKeyStore.getState().key).toBe('MS-NEW');
    await lateState!(json({ key: 'MS-OLD', info: null, error: null }));
    await p;
    await flush();
    expect(useKeyStore.getState().key).toBe('MS-NEW'); // 迟到快照已丢弃
  });
});

describe('keyStore.mergeKeys', () => {
  it('成功 → POST source_keys + mergeResult 明细 + keyInfo = target（新截止即刻上屏）', async () => {
    useKeyStore.setState({ key: 'MS-TARGET', keyInfo: null });
    const ok = await useKeyStore.getState().mergeKeys([' MS-A ', '', 'MS-B']);
    await flush();
    expect(ok).toBe(true);
    expect(mergeBodies).toEqual([{ source_keys: ['MS-A', 'MS-B'] }]); // strip + 空行过滤
    const s = useKeyStore.getState();
    expect(s.mergeResult).toEqual(MERGE_OK);
    expect(s.keyInfo).toEqual(MERGE_OK.target);
    expect(s.merging).toBe(false);
    expect(s.mergeError).toBeNull();
  });

  it('400 {error} 透传 → mergeError（整体失败无部分合并）', async () => {
    useKeyStore.setState({ key: null });
    mergeStatus = 400;
    const ok = await useKeyStore.getState().mergeKeys(['MS-A']);
    await flush();
    expect(ok).toBe(false);
    expect(useKeyStore.getState().mergeError)
      .toBe('未绑定授权 key：请在「系统key」中输入并保存');
    expect(useKeyStore.getState().mergeResult).toBeNull();
  });

  it('全部空行（按钮置灰兜底）→ 不发请求直接 false', async () => {
    const ok = await useKeyStore.getState().mergeKeys(['  ', '']);
    expect(ok).toBe(false);
    expect(mergeBodies).toHaveLength(0);
  });

  it('畸形响应（无 target）→ mergeError 兜底，state 不动', async () => {
    useKeyStore.setState({ key: 'MS-TARGET' });
    mergePayload = { sources: [] };
    const ok = await useKeyStore.getState().mergeKeys(['MS-A']);
    await flush();
    expect(ok).toBe(false);
    expect(useKeyStore.getState().mergeError).toBe('合并响应异常，请刷新后重试');
    expect(useKeyStore.getState().keyInfo).toBeNull();
  });
});

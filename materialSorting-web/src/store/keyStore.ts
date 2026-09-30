// KeyStore —— key 授权自助管理（prd-key-authorization-system US-006）状态中心。
//
// 数据源 = 后端四端点（materialsorting/web/routes_key.py）：
//   - GET  /api/key/state {key, info, error}   本地 key + keyserver info 只读现查
//     （keyserver 查询失败也 200，失败文案进 error —— 本地 key 仍可展示）；
//   - GET  /api/key/list {keys, error}         本机可用 key 列表（US-011「系统
//     可使用的key」表格：仅「正在使用」态 + 明文/类型/剩余；keyserver 失败也
//     200，keys 置空 + error 文案红字降级）；
//   - POST /api/key/save {key}                 bind 成功才落 key_state.json（后端
//     文件权威），失败 400 中文 {error} 透传（不覆盖旧 key）；
//   - POST /api/key/merge {source_keys}        target = 本地当前 key，keyserver
//     原子合并，成功 {target, sources, total_transferred_days}（sources = 每个
//     key 转移天数明细，任一 source 违反前置整体失败无部分合并）。
//
// **localStorage ms_key 镜像**（弹窗打开先用本地即时预填，不等网络往返）：
//   - 读：模块求值时读一次作 store.key 初值（清缓存/换浏览器时 null → 由
//     fetchState 对账从后端补回 —— 后端 key_state.json 权威，本地只是加速）；
//   - 写：fetchState 成功 / saveKey 成功后同步镜像（以后端为准：后端 null →
//     removeItem，后端有值 → setItem）。合并发生在后端（merge 不改 key 本身），
//     镜像无需动作。
//
// 请求代际号：fetchState 在飞时用户保存/合并成功会改写后端状态 —— 迟到的
// state 响应携带旧快照会覆盖新结果；saveKey/mergeKeys 成功路径 bump gen 丢弃
// 在飞 state（对账以最新动作为准）。全部请求走 apiFetch（X-Session-Id 体系，
// key 绑定的是 MachineGuid 机器身份 —— 会话头只是全站统一出口惯例，非闸门）。

import { create } from 'zustand';
import { apiFetch } from '../lib/api';

/** localStorage 镜像键名（后端 key_state.json 权威，本地仅预填加速）。 */
export const KEY_MIRROR_STORAGE = 'ms_key';

/** keyserver info 载荷（/api/key/state.info / save.info / merge.target 同构，
 * keyserver service._info_payload 契约；status = 六态中文标签）。 */
export interface KeyInfo {
  type: 'count' | 'duration';
  /** 六态中文标签：正在使用/已过期/已用完/未绑定/未激活/已合并。 */
  status: string;
  bound_system_name: string | null;
  remark: string | null;
  /** count 型专属：总次数 / 已用次数 / 剩余次数。 */
  total_uses?: number;
  used_uses?: number;
  remaining_uses?: number;
  /** duration 型专属：生效/截止时刻（未激活两者 null，此时 remaining_days =
   * 完整 duration_days 整数）/ 剩余天数（keyserver 四舍五入 1 位小数如 9.6，
   * 2026-09-30 起口径，此前 ceil 整天会夸大造成使用错觉）。 */
  activated_at?: string | null;
  expires_at?: string | null;
  remaining_days?: number;
}

/** merge 成功响应的明细行（每个 source key 转移的天数）。 */
export interface MergeSourceRow {
  key: string;
  transferred_days: number;
}

/** POST /api/key/merge 成功响应（keyserver 原样透传；target = 合并后新 info）。 */
export interface MergeResult {
  target: KeyInfo;
  sources: MergeSourceRow[];
  total_transferred_days: number;
}

/** 「系统可使用的key」表格行（US-011）：info 契约 + key 明文（名称列）。 */
export type KeyTableRow = { key: string } & KeyInfo;

/** info 形状守卫（半截/畸形响应 → null，弹窗按「属性不可用」降级）。 */
function isKeyInfo(v: unknown): v is KeyInfo {
  if (typeof v !== 'object' || v === null) return false;
  const t = (v as Record<string, unknown>).type;
  return t === 'count' || t === 'duration';
}

/** 表格行形状守卫（畸形行静默滤出，不炸整表）。 */
function isKeyTableRow(v: unknown): v is KeyTableRow {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof (v as Record<string, unknown>).key === 'string' &&
    (v as Record<string, unknown>).key !== '' &&
    isKeyInfo(v)
  );
}

/** 读 localStorage 镜像（损坏/不可用 → null 静默）。 */
export function readKeyMirror(): string | null {
  try {
    const raw = localStorage.getItem(KEY_MIRROR_STORAGE);
    return raw !== null && raw.trim() !== '' ? raw.trim() : null;
  } catch {
    return null; // 隐私模式等 —— 镜像失败静默（后端权威）
  }
}

/** 写 localStorage 镜像（null = 未绑定 → removeItem；失败静默）。 */
function writeKeyMirror(key: string | null): void {
  try {
    if (key === null) localStorage.removeItem(KEY_MIRROR_STORAGE);
    else localStorage.setItem(KEY_MIRROR_STORAGE, key);
  } catch {
    /* 镜像写失败不阻断主流程 */
  }
}

/** 错误响应体读中文 {error}（缺失/非 JSON → HTTP 状态兜底文案）。 */
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

/** MS 后端不可达时的兜底文案（keyserver 侧断网文案由后端 error 透传，非此处）。 */
const MSG_NET = '无法连接服务器，请检查网络后重试';

export interface KeyState {
  /** 本地当前 key（store 初值 = localStorage 镜像即时预填；fetchState 后以后端为准）。 */
  key: string | null;
  /** keyserver 属性（null = 未绑定或不可用）。 */
  keyInfo: KeyInfo | null;
  /** GET /api/key/state 的 error 字段（keyserver 查询失败文案；本地 key 仍展示）。 */
  error: string | null;
  /** save 进行中（保存按钮互斥防连击）。 */
  saving: boolean;
  /** save 失败中文文案（弹窗红字直显；成功清空）。 */
  saveError: string | null;
  /** merge 进行中（合并按钮互斥防连击）。 */
  merging: boolean;
  /** merge 失败中文文案（弹窗红字直显；含无 key 指路文案）。 */
  mergeError: string | null;
  /** merge 成功明细（每 key 天数 + 总转移；下一次 merge 覆写）。 */
  mergeResult: MergeResult | null;
  /** 「系统可使用的key」表格行（US-011；null = 未查询过/加载中）。 */
  keyList: KeyTableRow[] | null;
  /** GET /api/key/list 失败文案（keyserver 断网等；表格区红字降级）。 */
  listError: string | null;
  /** GET /api/key/state 对账（弹窗打开时调用；成功同步镜像）。 */
  fetchState: () => Promise<void>;
  /** GET /api/key/list（弹窗打开时与 save/merge 成功后调用；启停/合并表格随动）。 */
  fetchKeyList: () => Promise<void>;
  /** POST /api/key/save：成功 true（双写镜像 + keyInfo 更新）；失败 false（saveError）。 */
  saveKey: (rawKey: string) => Promise<boolean>;
  /** POST /api/key/merge（每行一个 key 由弹窗拆行后传入）：成功 true（明细 +
   * target 新 info）；失败 false（mergeError）。 */
  mergeKeys: (sourceKeys: string[]) => Promise<boolean>;
}

/** 请求代际号（fetchState 在飞时保存/合并已改后端状态 → 迟到响应丢弃）。 */
let gen = 0;

export const useKeyStore = create<KeyState>((set, get) => ({
  // 模块求值即读镜像 —— 弹窗打开瞬间 store.key 已是本地值（不等网络往返）。
  key: readKeyMirror(),
  keyInfo: null,
  error: null,
  saving: false,
  saveError: null,
  merging: false,
  mergeError: null,
  mergeResult: null,
  keyList: null,
  listError: null,

  fetchState: async () => {
    const g = gen;
    try {
      const r = await apiFetch('/api/key/state');
      if (g !== gen) return; // 在飞期间保存/合并已接管 → 丢弃过期快照
      if (!r.ok) {
        // 契约上 state 恒 200；非 2xx（旧后端等）→ 保留本地镜像，置 error 提示
        set({ error: `获取 key 状态失败（HTTP ${r.status}）`, keyInfo: null });
        return;
      }
      const data = (await r.json()) as { key?: unknown; info?: unknown; error?: unknown };
      if (g !== gen) return;
      const key = typeof data.key === 'string' && data.key.trim() !== '' ? data.key.trim() : null;
      const keyInfo = isKeyInfo(data.info) ? data.info : null;
      const error = typeof data.error === 'string' && data.error !== '' ? data.error : null;
      // 后端为准：绑定/合并都发生在后端（另一浏览器保存的新 key / 后端已清空
      // 都以本响应落定），镜像随之同步（null → removeItem）。
      set({ key, keyInfo, error });
      writeKeyMirror(key);
    } catch {
      if (g === gen) set({ error: MSG_NET, keyInfo: null });
    }
  },

  fetchKeyList: async () => {
    const g = gen;
    try {
      const r = await apiFetch('/api/key/list');
      if (g !== gen) return; // 在飞期间保存/合并已接管 → 丢弃过期快照
      if (!r.ok) {
        // 契约上 list 恒 200；非 2xx（旧后端等）→ 表格红字降级
        set({ listError: `获取可用 key 列表失败（HTTP ${r.status}）` });
        return;
      }
      const data = (await r.json()) as { keys?: unknown; error?: unknown };
      if (g !== gen) return;
      const rawList = Array.isArray(data.keys) ? data.keys : [];
      const error =
        typeof data.error === 'string' && data.error !== '' ? data.error : null;
      set({ keyList: rawList.filter(isKeyTableRow), listError: error });
    } catch {
      if (g === gen) set({ listError: MSG_NET });
    }
  },

  saveKey: async (rawKey) => {
    const key = rawKey.trim();
    if (key === '' || get().saving) return false; // 按钮已置灰，兜底
    set({ saving: true, saveError: null });
    try {
      const r = await apiFetch('/api/key/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      });
      if (!r.ok) {
        // bind 业务失败中文透传（如「key 不存在：请检查输入是否正确」），
        // 后端不落盘 —— 本地旧 key 与镜像原样保留。
        const msg = await readErrorMessage(r, '保存失败');
        set({ saving: false, saveError: msg });
        return false;
      }
      const data = (await r.json()) as { key?: unknown; info?: unknown };
      gen += 1; // 丢弃在飞 state（本响应即最新状态）
      const saved = typeof data.key === 'string' && data.key.trim() !== '' ? data.key.trim() : key;
      // 双写：后端 key_state.json（路由已落）+ localStorage 镜像。
      writeKeyMirror(saved);
      set({
        key: saved,
        keyInfo: isKeyInfo(data.info) ? data.info : null,
        error: null,
        saving: false,
        saveError: null,
        mergeResult: null, // key 已换，上一 key 的合并明细不再相关
      });
      void get().fetchKeyList(); // 启用/保存换了 key → 表格高亮行随动刷新
      return true;
    } catch {
      set({ saving: false, saveError: MSG_NET });
      return false;
    }
  },

  mergeKeys: async (sourceKeys) => {
    const sources = sourceKeys.map((k) => k.trim()).filter((k) => k !== '');
    if (sources.length === 0 || get().merging) return false; // 按钮已置灰，兜底
    set({ merging: true, mergeError: null, mergeResult: null });
    try {
      const r = await apiFetch('/api/key/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_keys: sources }),
      });
      if (!r.ok) {
        // 整体失败文案（无 key 指路 / 非 duration / 已合并 / key 不存在…）。
        const msg = await readErrorMessage(r, '合并失败');
        set({ merging: false, mergeError: msg });
        return false;
      }
      const data = (await r.json()) as unknown;
      if (typeof data !== 'object' || data === null || !isKeyInfo((data as MergeResult).target)) {
        set({ merging: false, mergeError: '合并响应异常，请刷新后重试' });
        return false;
      }
      gen += 1; // 丢弃在飞 state（merge 响应携带最新 target info）
      const result = data as MergeResult;
      set({
        merging: false,
        mergeError: null,
        mergeResult: result,
        keyInfo: result.target, // target = 合并后新 info（新截止时刻即刻上屏）
      });
      void get().fetchKeyList(); // 被合并行已失效 → 表格刷新（US-011）
      return true;
    } catch {
      set({ merging: false, mergeError: MSG_NET });
      return false;
    }
  },
}));

/** 测试隔离：回初始态（key 重读 localStorage）+ 复位代际号（beforeEach 用；生产勿调）。 */
export function __resetKeyStoreForTest(): void {
  gen = 0;
  useKeyStore.setState({
    key: readKeyMirror(),
    keyInfo: null,
    error: null,
    saving: false,
    saveError: null,
    merging: false,
    mergeError: null,
    mergeResult: null,
    keyList: null,
    listError: null,
  });
}

// InitialLayoutStore —— 初始布局（warm 热启动，prd-initial-layout US-004）状态中心。
//
// 三块状态 + 轻量动作（生成/保存编排属 US-006 弹窗，本 store 只持态）：
//   - supported：热启动能力（GET /api/warm-capability 探测）。null = 未探测 /
//     探测失败（未知 = 入口按钮**不**置灰不拦截）；false = 当前 spyrrow 版本
//     不支持（入口按钮置灰 + title 提示）。App 启动拉一次（probeCapability
//     幂等短路：已落定不再发；失败保持 null，下次调用可重试）。
//   - saved：已保存的初始布局（US-006 保存闸产物；US-007 普通运行附 initial
//     的数据源 + SolveControls chip 三态依据）。displayPlaced = 展开视图全条目
//     （续编/展示），warmPlaced = 组合宇宙条目（warm 载荷 placed 用；plain 时
//     = working 全条目三键形态），demandMap = 组合宇宙需求映射（plain 时 null
//     —— 后端 build_pid_meta 投影才是宇宙，载荷 demand_map 被忽略）。
//   - generating / genSeed / error：US-006 弹窗生成态（busy 画布禁交互）、刷新
//     代际号（确认刷新后 +1 重生成，seed 换代防同帧复现）、生成失败中文文案。
//
// fingerprint（stale 判定核心，run_stats class_key 组件法前端镜像）：
//   稳定序列化 {sizes, per_type, quantities, params, gate_mm, band, prefix} ——
//   后端热启动实例宇宙 = 这七组件完全决定（sizes 过滤 / demand / 公差 / 门幅 /
//   band·prefix 组合形态），任一漂移即 instance_mismatch 降级，故前端先判
//   stale 不带失效载荷。口径与 cli/portfolio.run_stats_class_key 同款：
//   **None 与空同判**（per_type/quantities null ≡ {}；band/prefix 关闭 ≡ null，
//   enabled falsy 同判关）、**键序无关**（对象键升序规范化后序列化）、sizes
//   排序后序列化（勾选序无关 —— 后端 build_pid_meta 按集合成员过滤）。
//   保存侧（US-006 setSaved 存 collectStartContext 指纹）与比较侧（US-007
//   handleStart 现算指纹 isStale）共用 initialLayoutFingerprint 单一实现。
//
// 与 uploadStore.doc 同为模块级 zustand 单例；不 localStorage 持久化（初始布局
// 是会话内工作态，页面刷新丢弃 —— 状态文件恢复不含本 store，US-007 收官口径）。

import { create } from 'zustand';
import { fetchWarmCapability, type CompositePlacedItem } from '../lib/initialLayout';
import type { PlacedItem } from '../types/piece';
import type { PerTypeOverrides, SolveParams } from '../types/v03';
import type { BandConfig, PrefixConfig } from '../types/ws';

/** 已保存的初始布局（US-006「保存当前布局」产物）。 */
export interface SavedInitialLayout {
  /** 展开视图全条目（永无 WB_/PS_；编辑弹窗 working 最终态，续编载入用）。 */
  displayPlaced: PlacedItem[];
  /** 组合宇宙条目（band/prefix 开 = 生成响应 composite.placed_items + 组位移
   * 记账；plain = working 全条目三键形态）—— WS initial.placed 数据源。 */
  warmPlaced: CompositePlacedItem[];
  /** 组合宇宙需求映射（band/prefix 开 = composite.demand_map；plain = null
   * —— 后端 pid_meta 投影才是宇宙，载荷 demand_map 被忽略）。 */
  demandMap: Record<string, number> | null;
  /** 保存时求解上下文指纹（initialLayoutFingerprint 产物）。 */
  fingerprint: string;
  /** 保存时物理包络料长 mm（US-007 冒烟 warm 生效签名断言基准）。 */
  widthMm: number;
  /** 保存时 band 是否开启（chip / 伪卡片回显）。 */
  bandUsed: boolean;
  /** 保存时 prefix 是否开启。 */
  prefixUsed: boolean;
}

/** 指纹输入（collectStartContext 同源 —— StartContext 结构子集；seed/time
 * 不参与指纹：换 seed 重跑不改变实例宇宙，热启动仍合法）。 */
export interface InitialLayoutFingerprintInput {
  sizes: number[];
  per_type: PerTypeOverrides | null;
  quantities: Record<string, Record<string, number>> | null;
  params: SolveParams;
  gate_mm: number;
  band: BandConfig | null;
  prefix: PrefixConfig | null;
}

/** 递归规范化：对象键升序（键序无关）+ undefined 剔除（与 JSON.stringify
 * 丢 undefined 同语义；per_type {d:1} ≡ {d:1,tol:undefined}）。 */
function canonicalize(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(canonicalize);
  if (v !== null && typeof v === 'object') {
    const src = v as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(src).sort()) {
      if (src[k] === undefined) continue;
      out[k] = canonicalize(src[k]);
    }
    return out;
  }
  return v;
}

/** dict 组件 None 与空同判（class_key 组件口径）：null/undefined/空对象 → null。 */
function normDict(v: unknown): unknown {
  if (v === null || v === undefined) return null;
  if (typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length === 0) {
    return null;
  }
  return canonicalize(v);
}

/** band 组件规范化：关闭（null / enabled falsy）→ null 不加组件（class_key
 * 「None 不加组件」同款 —— band off 与历史口径可比）；开启 → {label}。 */
function normBand(band: BandConfig | null): unknown {
  return band && band.enabled ? { label: band.label } : null;
}

/** prefix 组件规范化：同 normBand（关闭 → null；开启 → {front, back}）。 */
function normPrefix(prefix: PrefixConfig | null): unknown {
  return prefix && prefix.enabled ? { front: prefix.front, back: prefix.back } : null;
}

/**
 * 初始布局指纹：稳定序列化 {sizes, per_type, quantities, params, gate_mm,
 * band, prefix}（组件口径 = run_stats class_key 组件法：None 与空同判、键序
 * 无关；sizes 排序后序列化）。同逻辑上下文必同串 —— isStale 比较的单一真相源。
 */
export function initialLayoutFingerprint(input: InitialLayoutFingerprintInput): string {
  const comp = {
    sizes: [...input.sizes].sort((a, b) => a - b),
    per_type: normDict(input.per_type),
    quantities: normDict(input.quantities),
    params: canonicalize(input.params),
    gate_mm: input.gate_mm,
    band: normBand(input.band),
    prefix: normPrefix(input.prefix),
  };
  // 顶层键序 = 字面量固定序（确定性）；内层经 canonicalize 键升序。
  return JSON.stringify(comp);
}

export interface InitialLayoutState {
  /** 热启动能力（null = 未探测/探测失败 —— 不置灰；false = 不支持，入口置灰）。 */
  supported: boolean | null;
  /** 已保存初始布局（null = 未设置 —— US-007 不附带 initial）。 */
  saved: SavedInitialLayout | null;
  /** 生成中（US-006 弹窗 busy 态：画布禁交互 + 进度提示）。 */
  generating: boolean;
  /** 生成代际号（「布局刷新」确认后 +1 换 seed 重生成；从 0 起）。 */
  genSeed: number;
  /** 生成失败中文文案（US-006 弹窗红字直显；成功/保存清空）。 */
  error: string | null;
  /** 能力探测（App 启动拉一次；已落定短路，失败保持 null 可重试）。 */
  probeCapability: () => Promise<void>;
  /** 保存初始布局（US-006 保存闸终态写入；顺带清空 error）。 */
  setSaved: (saved: SavedInitialLayout) => void;
  /** 清除已保存布局（US-007 chip「×清除」；仅动 saved，genSeed 保留续增）。 */
  clear: () => void;
  /** 生成态写入（US-006 编排）。 */
  setGenerating: (generating: boolean) => void;
  /** 刷新代际号 +1（US-006「布局刷新」确认路径），返回新值作生成 seed。 */
  bumpGenSeed: () => number;
  /** error 写入（null = 清空）。 */
  setError: (error: string | null) => void;
  /** 保存态相对当前上下文指纹是否失效（saved 缺席 = true —— 无可新鲜态；
   * US-007 消费：saved && !isStale(现算指纹) 才附 initial）。 */
  isStale: (currentFingerprint: string) => boolean;
}

export const useInitialLayoutStore = create<InitialLayoutState>((set, get) => ({
  supported: null,
  saved: null,
  generating: false,
  genSeed: 0,
  error: null,

  probeCapability: async () => {
    // 一次生命周期只探一次（成功落定后短路；StrictMode 双 mount / 多处调用
    // 并发共享 —— GET 幂等，重复无害）。失败静默保持 null（未知 = 不置灰）。
    if (get().supported !== null) return;
    try {
      const cap = await fetchWarmCapability();
      set({ supported: cap.supported });
    } catch {
      /* 后端未起 / 旧后端无端点 / 形态异常 —— 保持 null，下次调用可重试 */
    }
  },

  setSaved: (saved) => set({ saved, error: null }),
  clear: () => set({ saved: null }),
  setGenerating: (generating) => set({ generating }),
  bumpGenSeed: () => {
    const next = get().genSeed + 1;
    set({ genSeed: next });
    return next;
  },
  setError: (error) => set({ error }),

  isStale: (currentFingerprint) => {
    const saved = get().saved;
    return saved === null || saved.fingerprint !== currentFingerprint;
  },
}));

/** 测试隔离：回初始态（生产勿调）。 */
export function __resetInitialLayoutStoreForTest(): void {
  useInitialLayoutStore.setState({
    supported: null,
    saved: null,
    generating: false,
    genSeed: 0,
    error: null,
  });
}

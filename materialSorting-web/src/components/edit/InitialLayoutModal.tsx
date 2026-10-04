// InitialLayoutModal —— 「高级配置：设置初始布局」弹窗（prd-initial-layout US-006，
// 2026-10-03）。界面与 EditLayoutModal（编辑排料结果弹窗）一致、去掉微调相关功能
// （polish 不传 → 微调按钮/对比卡不渲染；状态条只留料长 + 当前利用率，无 Δ 行 ——
// 初始布局无「相对基线」语义），新增「布局刷新」与保存闸两块编排。外层仿
// EditLayoutModal：订阅 controlPanelStore modal === 'initial_layout' 自显隐
// （声明式受控 Portal → body，Inner 带 key 重挂载 = 打开即重新走「续编 or 生成」
// 编排）；单例挂在 ControlPanel（EditLayoutModal 旁）。不挂 ESC / 遮罩关闭
//（编辑草稿不可误触丢弃，编辑弹窗同哲学）。
//
// ---- 打开编排（mount 一次性，bootRef 防 StrictMode 双 mount 双请求）----
//   collectStartContext 同源上下文（form + qtyStore 快照）→ initialLayoutFingerprint：
//     - saved 在场且指纹未失效 → **载入续编**：saved.manifest + saved.displayPlaced
//       合成伪 RunRecord（不进 runRegistry —— 仅 editStore.open 的渲染/基线载体）
//       → working = displayPlaced 深拷贝；组合基线 = saved.warmPlaced（上次会话组
//       delta 已烘焙在值内，本次编辑的组 delta 在其上继续记账）；
//     - 无 saved / 指纹已失效（stale 布局对当前 pid 宇宙不可用，续编保存只会产出
//       必然降级的热载荷）→ **自动生成**：generateInitialLayout(ctx 同源八键 + seed
//       = store.genSeed 单调值) → manifest + placed 合成伪 run → editStore.open。
//   生成在飞（store.generating）= busy 态：画布禁交互 + 「生成中」浮层 + ✕/刷新/
//   保存全禁（生成期无任何关闭路径 —— async 续作不会落在已卸载弹窗上）。
//   edit_hold 会话钉住心跳复用（编辑弹窗同款 4min 节奏，详见 lib/editHold.ts）。
//
// ---- EditCanvas props（US-005 成品消费）----
//   allowMirror={false}（空格两态掉头、O/I 禁）/ allowFineRotate={false}（L/K 禁）
//   —— sparrow proper-rigid 拒镜像与非法角，编辑产物恒为热启动合法载荷；
//   pieceGroup = band/prefix 开时按 label 前缀 / prefixMemberPids（parsePrefixMemberPids
//   产物，含异码补片）映射组成员（整组刚性平移 + 组内单片不可编辑）；plain 不传
//   （单片语义）。onIllegalOverlapCountChange = 保存闸数据源（红色重叠片数，琥珀
//   压线不计 —— 与画布指标面板同口径；2026-10-04 判红口径修订：红 = 碰撞轮廓
//   （erode）相交，solver 贴触解「穿透微超额度」不再假阳性锁闸 —— 高级配置设
//   重合 d 后生成即无法保存的报障形态，见 EditCanvas 头注/overlap.ts 头注）。
//
// ---- 布局刷新 ----
//   working 相对基线（editStore.baseline = open 快照）有编辑 → EditConfirmLayer
//   「将丢弃当前编辑」确认；确认后 bumpGenSeed() 换 seed 重新生成替换 working
//   （editStore.open 新伪 run → delta 记账基线同步重置为新生成布局）。无编辑直刷。
//
// ---- 保存当前布局（保存闸）----
//   红色重叠计数 > 0 → 保存按钮 disabled + 数量提示（琥珀压线不限）。通过后组装：
//     displayPlaced = 当前 working；warmPlaced = band/prefix 开且有组合基线时
//     assembleWarmPlaced（WB_/PS_ 组条目 += 组位移 delta —— 组 delta = 组内任一
//     成员当前位移相对生成基线；非成员取当前 working 最新值；composite 畸形缺席
//     → plain 降级），plain = working 全条目三键形态；demandMap 同口径；
//     widthMm = computeLayoutStats 当前宽 → initialLayoutStore.setSaved →
//     runRegistry 挂「初始布局（未求解）」伪卡片（INITIAL_LAYOUT_SEED 哨兵，
//     finalDensity 恒 0 + bestRun() 哨兵跳过 —— 导出/编辑排料选源不受污染；
//     重复保存 removeInitialLayoutCard 去重恒至多一张）→ 关闭弹窗。伪卡片经
//     NestingPage 订阅 saved 挂进 seeds 并排回显（下次求解 clear 自然收走）。
//
// ---- 关闭 ✕ ----
//   有未保存编辑（working ≠ 伪 run lastFrame，itemsEqual ε 同编辑弹窗）→ dirty
//   确认层「放弃未保存的修改？」（EditConfirmLayer 同款复用）；否则直接关。

import { useEffect, useMemo, useRef, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { computeLayoutStats, itemsEqual, useEditStore } from '../../store/editStore';
import { INITIAL_LAYOUT_SEED, runRegistry, type RunRecord } from '../../store/runRegistry';
import {
  initialLayoutFingerprint,
  useInitialLayoutStore,
  type SavedInitialLayout,
} from '../../store/initialLayoutStore';
import { useAppStore } from '../../store/appStore';
import { useFormStore } from '../../store/formStore';
import { useQtyStore } from '../../store/qtyStore';
import { deepCopyPlaced } from '../../store/synthRunStore';
import { EDIT_HOLD_INTERVAL_MS, refreshEditHold } from '../../lib/editHold';
import { parsePrefixMemberPids } from '../../lib/editPolish';
import { collectStartContext, type StartContext } from '../../lib/params';
import {
  assembleWarmPlaced,
  generateInitialLayout,
  plainWarmPlaced,
  type CompositePlacedItem,
} from '../../lib/initialLayout';
import type { PlacedItem } from '../../types/piece';
import type { FrameMsg, ManifestMsg } from '../../types/ws';
import { EditCanvas, type EditViewMode } from './EditCanvas';
import { EditConfirmLayer } from './EditConfirmLayer';

/** 编辑会话上下文（打开编排一次性落定；刷新重新生成只换 composite 三段）。 */
interface InitialLayoutSession {
  /** collectStartContext 同源快照（生成载荷 / 组判定 / 指纹数据源）。 */
  ctx: StartContext;
  /** 打开时刻指纹（保存随存 —— 弹窗遮罩阻断主界面，开/存之间上下文不可能漂移）。 */
  fingerprint: string;
  /** 组合宇宙基线（band/prefix 开且有 composite：生成响应 placed_items / 续编
   * saved.warmPlaced；plain 或畸形缺席 = null → 保存 plain 降级）。 */
  composite: CompositePlacedItem[] | null;
  /** 组合宇宙需求映射（同上口径；null = plain 投影）。 */
  demandMap: Record<string, number> | null;
  /** prefix 组成员 pid 集（prefix 关 = []；pieceGroup + 组位移记账共用）。 */
  prefixMemberPids: string[];
}

export function InitialLayoutModal(): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  if (modal !== 'initial_layout') return null;
  return <InitialLayoutModalInner key="initial-layout-modal" />;
}

function InitialLayoutModalInner(): JSX.Element {
  const closeModal = useControlPanelStore((s) => s.closeModal);
  const run = useEditStore((s) => s.run);
  const working = useEditStore((s) => s.working);
  const baseline = useEditStore((s) => s.baseline);
  const generating = useInitialLayoutStore((s) => s.generating);
  const genError = useInitialLayoutStore((s) => s.error);
  const [mode, setMode] = useState<EditViewMode>('full');
  const [session, setSession] = useState<InitialLayoutSession | null>(null);
  /** ✕ dirty 确认层 / 刷新丢弃确认层显隐（互斥单确认层）。 */
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [confirmRefresh, setConfirmRefresh] = useState(false);
  /** 红色（非法）重叠片数（EditCanvas onIllegalOverlapCountChange 数据源，US-005
   * 同指标面板口径 —— 琥珀压线不计）。保存闸消费。 */
  const [illegalCount, setIllegalCount] = useState(0);
  /** 打开编排一次性守卫（StrictMode 双 mount 防双生成请求）。 */
  const bootRef = useRef(false);

  // ---- 打开编排（见组件头注：续编 or 自动生成）----
  useEffect(() => {
    if (bootRef.current) return;
    bootRef.current = true;
    const ctx = collectStartContext(
      useFormStore.getState().form,
      useQtyStore.getState().quantities,
    );
    const fingerprint = initialLayoutFingerprint({
      sizes: ctx.sizes,
      per_type: ctx.per_type,
      quantities: ctx.quantities,
      params: ctx.params,
      gate_mm: ctx.gate_mm,
      band: ctx.band,
      prefix: ctx.prefix,
    });
    const saved = useInitialLayoutStore.getState().saved;
    if (saved !== null && saved.fingerprint === fingerprint) {
      // 载入续编：saved 三段合成伪 run；组合基线 = saved.warmPlaced（band/prefix
      // 开才有组语义 —— 指纹已匹配，bandUsed/prefixUsed 与当前 ctx 同判）。
      useEditStore.getState().open(buildPseudoRun(saved.manifest, saved.displayPlaced));
      const grouped = ctx.band != null || ctx.prefix != null;
      setSession({
        ctx,
        fingerprint,
        composite: grouped ? saved.warmPlaced : null,
        demandMap: grouped ? saved.demandMap : null,
        prefixMemberPids: saved.prefixMemberPids,
      });
      return;
    }
    // 无 saved / 已失效 → 自动生成（stale 布局的 pid 宇宙已漂移，续编只会产出
    // 必然降级的热载荷 —— 重生成是唯一有意义的动作；saved 保留待新保存覆盖）。
    setSession({ ctx, fingerprint, composite: null, demandMap: null, prefixMemberPids: [] });
    void runGenerate(ctx, fingerprint, useInitialLayoutStore.getState().genSeed);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount 一次性编排
  }, []);

  // 会话钉住心跳（编辑弹窗同款：弹窗打开期间滚动 POST /api/edit-hold 续期，
  // 后端 2h 钉住 + 关窗自然宽限；失败静默详见 lib/editHold.ts）。
  useEffect(() => {
    void refreshEditHold();
    const id = window.setInterval(() => void refreshEditHold(), EDIT_HOLD_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  /**
   * 生成（打开自动 / 刷新共用）：POST /api/initial-layout/generate（ctx 同源八键
   * + seed）→ manifest + placed 合成伪 run → editStore.open（delta 记账基线随
   * open 快照重置）；组合段（composite/demand_map/prefix 成员）随响应落 session。
   * 失败 → store.error 中文文案（footer 红字直显；「布局刷新」即重试入口）。
   */
  async function runGenerate(ctx: StartContext, fingerprint: string, seed: number): Promise<void> {
    useInitialLayoutStore.getState().setGenerating(true);
    useInitialLayoutStore.getState().setError(null);
    try {
      const r = await generateInitialLayout({
        sizes: ctx.sizes,
        per_type: ctx.per_type,
        quantities: ctx.quantities,
        params: ctx.params,
        gate_mm: ctx.gate_mm,
        band: ctx.band,
        prefix: ctx.prefix,
        seed,
      });
      useEditStore.getState().open(buildPseudoRun(r.manifest, r.placed));
      const grouped = ctx.band != null || ctx.prefix != null;
      setSession({
        ctx,
        fingerprint,
        composite: grouped ? (r.composite?.placed_items ?? null) : null,
        demandMap: grouped ? (r.composite?.demand_map ?? null) : null,
        prefixMemberPids: r.prefix
          ? parsePrefixMemberPids(r.prefix.pid, r.prefix.size, r.prefix.extra)
          : [],
      });
    } catch (e) {
      useInitialLayoutStore.getState().setError(e instanceof Error ? e.message : String(e));
    } finally {
      useInitialLayoutStore.getState().setGenerating(false);
    }
  }

  /** 组成员映射（US-005 pieceGroup 消费）：band 组 = label 前缀全部副本、prefix
   * 组 = 成员 pid 集（含异码补片）；plain（两者皆关）不传 = 单片语义。 */
  const pieceGroup = useMemo(() => {
    if (!session) return undefined;
    const bandLabel = session.ctx.band != null ? session.ctx.band.label : null;
    const prefixPids = session.prefixMemberPids;
    if (bandLabel == null && prefixPids.length === 0) return undefined;
    return (pid: string): string | null => {
      if (bandLabel != null && pid.startsWith(`${bandLabel}_`)) return 'band';
      if (prefixPids.includes(pid)) return 'prefix';
      return null;
    };
  }, [session]);

  // 状态条：computeLayoutStats 单一真相源（与保存 widthMm 同公式；无 Δ 行 ——
  // 初始布局无「相对基线」语义，PRD 口径只留料长 + 当前利用率）。
  const manifest = run?.manifest ?? null;
  const stats = manifest && working.length > 0 ? computeLayoutStats(working, manifest) : null;

  // ✕ dirty 口径同编辑弹窗：working ≠ 伪 run lastFrame（open 快照深拷贝 ⇒ 未编辑
  // 恒非 dirty；编辑后未保存 → 确认层）。
  const savedItems = run?.lastFrame?.placed_items ?? null;
  const dirty = !!(run && savedItems && !itemsEqual(working, savedItems));

  function handleClose(): void {
    if (generating) return; // busy 态无关闭路径（见组件头注）
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }
    closeModal();
  }

  /** 布局刷新：有编辑 → 确认层「将丢弃当前编辑」；确认/无编辑 → bumpGenSeed 换
   * seed 重生成（editStore.open 新伪 run = working 替换 + delta 基线同步重置）。 */
  function handleRefresh(): void {
    if (generating || !session) return;
    const edited =
      baseline != null &&
      !itemsEqual(useEditStore.getState().working, baseline.placedItems);
    if (edited) {
      setConfirmRefresh(true);
      return;
    }
    void runGenerate(
      session.ctx,
      session.fingerprint,
      useInitialLayoutStore.getState().bumpGenSeed(),
    );
  }

  /** 保存闸 + 组装 + 挂伪卡片 + 关窗（编排见组件头注「保存当前布局」段）。 */
  function handleSave(): void {
    if (generating || illegalCount > 0) return;
    const { run: curRun, working: curWorking, baseline: curBaseline } = useEditStore.getState();
    const curManifest = curRun?.manifest ?? null;
    if (!curRun || !curManifest || curWorking.length === 0 || !session) return;
    const curStats = computeLayoutStats(curWorking, curManifest);
    const grouped = session.ctx.band != null || session.ctx.prefix != null;
    const warmPlaced =
      grouped && session.composite
        ? assembleWarmPlaced(curWorking, curBaseline?.placedItems ?? curWorking, session.composite, {
            bandLabel: session.ctx.band != null ? session.ctx.band.label : null,
            prefixPids: session.prefixMemberPids,
          })
        : plainWarmPlaced(curWorking);
    const saved: SavedInitialLayout = {
      displayPlaced: deepCopyPlaced(curWorking),
      warmPlaced,
      demandMap: grouped ? session.demandMap : null,
      fingerprint: session.fingerprint,
      widthMm: curStats.widthMm,
      bandUsed: session.ctx.band != null,
      prefixUsed: session.ctx.prefix != null,
      manifest: curManifest,
      prefixMemberPids: [...session.prefixMemberPids],
    };
    useInitialLayoutStore.getState().setSaved(saved);
    mountInitialLayoutCard(curManifest, curWorking, curStats);
    useAppStore.getState().bumpRenderTick();
    closeModal();
  }

  const saveBlocked = generating || illegalCount > 0 || working.length === 0;

  return createPortal(
    <div className="edit-layout-overlay" data-testid="initial-layout-overlay">
      <div
        className="edit-layout-modal"
        role="dialog"
        aria-modal="true"
        aria-label="设置初始布局"
      >
        <div className="edit-layout-head">
          <div className="edit-layout-stats">
            <span className="edit-layout-stat" data-testid="initial-layout-width">
              料长 {stats ? `${stats.widthMm} mm` : '—'}
            </span>
            <span className="edit-layout-stat" data-testid="initial-layout-density">
              利用率 {stats ? `${(stats.density * 100).toFixed(2)}%` : '—'}
            </span>
          </div>
          <button
            type="button"
            className="edit-layout-close"
            aria-label="关闭"
            title="关闭"
            onClick={handleClose}
            disabled={generating}
            data-testid="initial-layout-close"
          >
            ✕
          </button>
        </div>

        <div className="edit-layout-body">
          {run && manifest ? (
            <EditCanvas
              mode={mode}
              interactionEnabled={!generating && !confirmDiscard && !confirmRefresh}
              onModeChange={setMode}
              allowMirror={false}
              allowFineRotate={false}
              pieceGroup={pieceGroup}
              onIllegalOverlapCountChange={setIllegalCount}
            />
          ) : !generating ? (
            <div
              className="edit-layout-canvas-wrap edit-layout-empty"
              data-testid="initial-layout-empty"
            >
              {genError ?? '暂无初始布局'}
            </div>
          ) : null}
          {generating && (
            <div className="edit-layout-busy" data-testid="initial-layout-generating">
              初始布局生成中（约 5 秒）…
            </div>
          )}
        </div>

        {/* footer：左侧提示区（生成失败红字 / 保存闸数量提示）+ 右侧「布局刷新」
            与「保存当前布局」两按钮（保存 = 编辑弹窗主色按钮；刷新 = 画布工具区
            次级按钮同款）。 */}
        <div className="edit-layout-foot">
          <div className="edit-layout-foot-note">
            {!generating && genError != null && (
              <span className="edit-layout-error" data-testid="initial-layout-error">
                {genError}
              </span>
            )}
            {illegalCount > 0 && (
              <span className="edit-layout-save-hint" data-testid="initial-layout-save-hint">
                存在 {illegalCount} 片非法（红色）重叠，处理后才能保存
              </span>
            )}
          </div>
          <button
            type="button"
            className="edit-layout-tool edit-layout-refresh"
            onClick={handleRefresh}
            disabled={generating || !session}
            title="重新生成初始布局（有编辑时需确认丢弃）"
            data-testid="initial-layout-refresh"
          >
            布局刷新
          </button>
          <button
            type="button"
            className="edit-layout-save"
            onClick={handleSave}
            disabled={saveBlocked}
            title={
              illegalCount > 0
                ? `存在 ${illegalCount} 片非法（红色）重叠，处理后才能保存`
                : '保存初始布局（普通运行将基于它热启动）'
            }
            data-testid="initial-layout-save"
          >
            保存当前布局
          </button>
        </div>
      </div>
      {/* ✕ dirty 确认层（EditConfirmLayer 同款复用，z-index 1350 盖住弹窗自身） */}
      {confirmDiscard && (
        <EditConfirmLayer
          message="放弃未保存的修改？"
          onConfirm={() => {
            setConfirmDiscard(false);
            closeModal();
          }}
          onCancel={() => setConfirmDiscard(false)}
        />
      )}
      {/* 布局刷新丢弃确认层（文案区分 ✕ 确认层）。 */}
      {confirmRefresh && (
        <EditConfirmLayer
          message="布局刷新将丢弃当前编辑，确认重新生成？"
          confirmText="重新生成"
          onConfirm={() => {
            setConfirmRefresh(false);
            if (!session) return;
            void runGenerate(
              session.ctx,
              session.fingerprint,
              useInitialLayoutStore.getState().bumpGenSeed(),
            );
          }}
          onCancel={() => setConfirmRefresh(false)}
        />
      )}
    </div>,
    document.body,
  );
}

/**
 * 伪 RunRecord 合成（编辑载体，**不进 runRegistry** —— 挂卡是保存动作的产物
 * mountInitialLayoutCard；editStore.save 的 registry 校验因此天然拒绝 —— 本弹窗
 * 保存走自家组装，不走 editStore.save）。帧数值 = computeLayoutStats 单一真相源
 * （与状态条/保存同公式）；density_sparrow 无求解参考值恒 0。
 */
function buildPseudoRun(manifest: ManifestMsg, placed: readonly PlacedItem[]): RunRecord {
  const stats = computeLayoutStats(placed, manifest);
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 0,
    phase: 'final',
    density: stats.density,
    density_sparrow: 0,
    width_mm: stats.widthMm,
    placed_items: deepCopyPlaced(placed),
  };
  return {
    seed: INITIAL_LAYOUT_SEED,
    ws: null,
    manifest,
    stage: null,
    band: null,
    prefix: null,
    warmState: null,
    frames: [frame],
    lastFrame: frame,
    finalDensity: 0,
    finalDensitySparrow: 0,
    done: false,
    error: null,
    viewBoxMaxW: stats.widthMm,
    stopped: false,
    startedAt: performance.now(),
    endedAt: 0,
    finalElapsed: null,
  };
}

/**
 * 保存时挂「初始布局（未求解）」伪卡片（runRegistry 单卡片，重复保存去重）。
 * finalDensity 双口径恒 0 + bestRun() 哨兵跳过 —— 未求解布局不进导出/编辑排料
 * 选源；done 直置不经 markRunDone（不触发 checkpoint —— 未求解布局非「求解完成」
 * 价值时刻）。NestingPage 订阅 saved 变化把哨兵 seed 挂进 seeds。
 */
function mountInitialLayoutCard(
  manifest: ManifestMsg,
  working: readonly PlacedItem[],
  stats: { widthMm: number; density: number },
): void {
  runRegistry.removeInitialLayoutCard();
  const rec = runRegistry.create(INITIAL_LAYOUT_SEED);
  const frame: FrameMsg = {
    type: 'frame',
    index: 0,
    elapsed: 0,
    phase: 'final',
    density: stats.density,
    density_sparrow: 0,
    width_mm: stats.widthMm,
    placed_items: deepCopyPlaced(working),
  };
  rec.manifest = manifest;
  rec.frames.push(frame);
  rec.lastFrame = frame;
  rec.viewBoxMaxW = stats.widthMm;
  rec.done = true;
}

// US-001 uiStore 单测（原 4 项）：
//   - 默认 activeTab = 'preview'（首页落上传预览）
//   - setTab('preview') / setTab('nesting') 切换并触发订阅
//   - 多次 setTab 同值幂等（无额外通知）
// US-015 新增 4 项（nestingEnabled 解锁闸）：
//   - 默认 nestingEnabled === false
//   - setNestingEnabled(true) 切换 nestingEnabled
//   - 订阅者收到 nestingEnabled 变化
//   - setTab('nesting') 在 nestingEnabled===false 时静默不切（关键不变量）

import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  PANEL_W_DEFAULT,
  PANEL_W_MAX,
  PANEL_W_MIN,
  clampPanelWidth,
  useUiStore,
} from '../uiStore';

beforeEach(() => {
  // 重置到默认 preview + 锁定超排 Tab + 面板宽回默认，避免前一个测试残留
  useUiStore.getState().setTab('preview');
  useUiStore.getState().setNestingEnabled(false);
  useUiStore.setState({ panelWidth: PANEL_W_DEFAULT });
  localStorage.removeItem('ms_panel_w');
});

describe('uiStore', () => {
  it('默认 activeTab = preview', () => {
    expect(useUiStore.getState().activeTab).toBe('preview');
  });

  it('setTab(nesting) 切换 activeTab', () => {
    // US-015：setTab('nesting') 需先解锁，否则静默不切（保留原断言意图）
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('setTab(preview) 从 nesting 切回', () => {
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    useUiStore.getState().setTab('preview');
    expect(useUiStore.getState().activeTab).toBe('preview');
  });

  it('订阅者收到 activeTab 变化', () => {
    useUiStore.getState().setNestingEnabled(true);
    const seen: string[] = [];
    const unsub = useUiStore.subscribe((s) => seen.push(s.activeTab));
    useUiStore.getState().setTab('nesting');
    useUiStore.getState().setTab('preview');
    unsub();
    // zustand 在初始化时不通知；只在 set 后通知
    expect(seen).toEqual(['nesting', 'preview']);
  });
});

describe('uiStore US-015 nestingEnabled', () => {
  it('默认 nestingEnabled === false', () => {
    expect(useUiStore.getState().nestingEnabled).toBe(false);
  });

  it('setNestingEnabled(true) 切换 nestingEnabled', () => {
    useUiStore.getState().setNestingEnabled(true);
    expect(useUiStore.getState().nestingEnabled).toBe(true);
    useUiStore.getState().setNestingEnabled(false);
    expect(useUiStore.getState().nestingEnabled).toBe(false);
  });

  it('订阅者收到 nestingEnabled 变化', () => {
    const seen: boolean[] = [];
    const unsub = useUiStore.subscribe((s) => seen.push(s.nestingEnabled));
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setNestingEnabled(false);
    unsub();
    expect(seen).toEqual([true, false]);
  });

  it('setTab(nesting) 在 nestingEnabled===false 时静默不切（关键不变量）', () => {
    // 未解锁状态下尝试切超排
    useUiStore.getState().setTab('nesting');
    expect(useUiStore.getState().activeTab).toBe('preview');
    // 解锁后再切才生效
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    expect(useUiStore.getState().activeTab).toBe('nesting');
  });

  it('setTab(preview) 在 nestingEnabled===false 时仍可切（用户随时可回上传预览页）', () => {
    useUiStore.getState().setNestingEnabled(true);
    useUiStore.getState().setTab('nesting');
    useUiStore.getState().setNestingEnabled(false);
    // 锁定状态下从 nesting 切回 preview 仍允许（不强制留在 nesting）
    useUiStore.getState().setTab('preview');
    expect(useUiStore.getState().activeTab).toBe('preview');
  });
});

describe('uiStore US-003 sessionRecovering（启动期恢复轻加载态）', () => {
  it('默认 sessionRecovering === false', () => {
    expect(useUiStore.getState().sessionRecovering).toBe(false);
  });

  it('setSessionRecovering 起止置位/复位', () => {
    useUiStore.getState().setSessionRecovering(true);
    expect(useUiStore.getState().sessionRecovering).toBe(true);
    useUiStore.getState().setSessionRecovering(false);
    expect(useUiStore.getState().sessionRecovering).toBe(false);
  });
});

describe('uiStore panelWidth（2026-10-05 面板伸缩分隔条）', () => {
  it('clampPanelWidth：范围内取整、越界钳到 200/300、非有限数回默认', () => {
    expect(clampPanelWidth(248)).toBe(248);
    expect(clampPanelWidth(210.4)).toBe(210); // 拖拽 delta 小数取整
    expect(clampPanelWidth(100)).toBe(PANEL_W_MIN);
    expect(clampPanelWidth(9999)).toBe(PANEL_W_MAX);
    expect(clampPanelWidth(Number.NaN)).toBe(PANEL_W_DEFAULT);
    expect(clampPanelWidth(Number.POSITIVE_INFINITY)).toBe(PANEL_W_DEFAULT);
  });

  it('默认 panelWidth = 248（无 localStorage 记忆时）', () => {
    expect(useUiStore.getState().panelWidth).toBe(PANEL_W_DEFAULT);
  });

  it('setPanelWidth 钳制在 [200, 300]', () => {
    useUiStore.getState().setPanelWidth(260);
    expect(useUiStore.getState().panelWidth).toBe(260);
    useUiStore.getState().setPanelWidth(150);
    expect(useUiStore.getState().panelWidth).toBe(PANEL_W_MIN);
    useUiStore.getState().setPanelWidth(400);
    expect(useUiStore.getState().panelWidth).toBe(PANEL_W_MAX);
  });

  it('setPanelWidth 高频路径不写 localStorage，persistPanelWidth 才落盘', () => {
    useUiStore.getState().setPanelWidth(280);
    expect(localStorage.getItem('ms_panel_w')).toBeNull(); // 拖拽中不碰 IO
    useUiStore.getState().persistPanelWidth();
    expect(localStorage.getItem('ms_panel_w')).toBe('280');
  });

  it('resetPanelWidth 回默认 248 并落盘（双击分隔条）', () => {
    useUiStore.getState().setPanelWidth(300);
    useUiStore.getState().resetPanelWidth();
    expect(useUiStore.getState().panelWidth).toBe(PANEL_W_DEFAULT);
    expect(localStorage.getItem('ms_panel_w')).toBe('248');
  });

  it('启动期 loadPanelWidth：读 localStorage（越界脏值被钳制、垃圾值回默认）', () => {
    // store 单例已初始化，loadPanelWidth 的行为经「重置模块 + 预置 localStorage」
    // 复验：vi.resetModules 后重新 import，模块初始化会重新读 localStorage。
    localStorage.setItem('ms_panel_w', '272');
    vi.resetModules();
    return import('../uiStore').then((m) => {
      expect(m.useUiStore.getState().panelWidth).toBe(272);
      // 越界脏值 → 钳到边界；垃圾字符串 → Number(...) NaN → 回默认
      localStorage.setItem('ms_panel_w', '5000');
      vi.resetModules();
      return import('../uiStore').then((m2) => {
        expect(m2.useUiStore.getState().panelWidth).toBe(PANEL_W_MAX);
        localStorage.setItem('ms_panel_w', 'garbage');
        vi.resetModules();
        return import('../uiStore').then((m3) => {
          expect(m3.useUiStore.getState().panelWidth).toBe(PANEL_W_DEFAULT);
        });
      });
    });
  });
});

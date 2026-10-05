// NormalRunModal —— 「普通运行」确认弹窗（2026-10-05 超排交互优化需求 2）。
//
// 点「普通运行」先经本弹窗确认时长（秒）—— 输入框自面板 ParamForm 移入（id="time"
// 选择器保留，冒烟脚本按 #time 填值零改动）；预填 formStore.form.time（面板时代
// 的上次值），确认时由 ControlPanel patch 回写后启动（取消不改值）。其余排料参数
// （码号/幅宽/满核/数量/band/prefix/per_type）不在此复述 —— hint 一行「排料参数
// 取当前面板」（用户定案：最小弹窗，不加参数摘要回显）。
//
// 2026-10-05 交互优化（同日二批）：时长范围限制 10–1200s —— 输入框 min/max 同界
// + 失焦/确认 normalizeTime 钳制（normalizeGate [50,400] 同款先例，越界钳边界、
// 空/非法回退 120，不做报错拦截）。
//
// 骨板对齐 FileNameModal 的纯取消型惯例：ESC / 遮罩 / ✕ / 取消 = 只关不跑；
// Enter = 确认（单输入框弹窗的键盘期望）。确认置灰 = solving（求解中）||
// startDisabled（面板闸门：码号空 / band·prefix 无效 —— 与 #start 同源，双保险）。

import { useEffect, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';

import { normalizeTime } from '../../lib/params';

export interface NormalRunModalProps {
  /** 预填时长（秒）字符串（formStore.form.time，打开时刻快照）。 */
  defaultTime: string;
  /** 求解中（phase==='running'；确认按钮置灰 —— #start 同款冻结）。 */
  solving: boolean;
  /** 面板启动闸门（码号空 / band·prefix 无效 → 置灰；与 #start disabled 同源）。 */
  startDisabled: boolean;
  /** 确认（time = normalizeTime 归一后字符串：钳制 [10,1200]、空/非法回退 120；
   *  解析交 parseTime —— Enter 直提不经 blur，提交点统一归一兜底）。 */
  onConfirm: (time: string) => void;
  /** 取消（含 ESC / 遮罩 / ✕ —— 只关弹窗，form.time 不变）。 */
  onCancel: () => void;
}

export function NormalRunModal({
  defaultTime,
  solving,
  startDisabled,
  onConfirm,
  onCancel,
}: NormalRunModalProps): JSX.Element {
  // 草稿 local state：mount 初始化自 defaultTime（ControlPanel 条件渲染 →
  // 每次打开都是新 mount，重开弹窗重新预填；编辑中不因父级重渲染被覆盖）。
  const [time, setTime] = useState(defaultTime);

  const confirmDisabled = solving || startDisabled;

  // ESC 关闭（仅关弹窗，不启动；FileNameModal 同款）。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      onCancel();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  /** 唯一提交路径（按钮点击 / 输入框 Enter 共用；置灰态静默不触发）。time 经
   *  normalizeTime 钳制 [10,1200]（2026-10-05 范围限制 —— Enter 直提不经 blur，
   *  提交点统一归一；onBlur 同款归一给视觉反馈）。 */
  function handleConfirm(): void {
    if (confirmDisabled) return;
    onConfirm(normalizeTime(time));
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    if (e.target === e.currentTarget) onCancel();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    e.stopPropagation();
  }

  return createPortal(
    <div
      className="strategy-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="normal-run-overlay"
    >
      <div
        className="strategy-modal"
        role="dialog"
        aria-modal="true"
        aria-label="普通运行"
        onMouseDown={handleModalMouseDown}
      >
        <div className="strategy-head">
          <span className="strategy-title">普通运行</span>
          <button
            type="button"
            className="strategy-close"
            aria-label="关闭"
            onClick={onCancel}
            data-testid="normal-run-close"
          >
            ✕
          </button>
        </div>

        <div className="strategy-field">
          <label htmlFor="time">时长（秒）</label>
          <input
            id="time"
            type="number"
            className="strategy-text-input"
            data-testid="normal-run-time"
            value={time}
            min={10}
            max={1200}
            autoFocus
            onChange={(e) => setTime(e.target.value)}
            onBlur={(e) => setTime(normalizeTime(e.target.value))}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleConfirm();
              }
            }}
          />
        </div>
        <div className="strategy-hint">排料参数取当前面板。时长范围 10–1200 秒，越界自动钳制。</div>

        <div className="strategy-actions">
          <button
            type="button"
            className="strategy-btn-again"
            onClick={onCancel}
            data-testid="normal-run-cancel"
          >
            取消
          </button>
          <button
            type="button"
            className="strategy-btn-exec"
            disabled={confirmDisabled}
            onClick={handleConfirm}
            data-testid="normal-run-confirm"
          >
            开始运行
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// MultiSeedControls —— 多 seed 对比开关 + 数量输入（旧 index.html `#multi_seed` / `#seed_count`）。
//
// 与旧 index.html `<div class="field row">` 等价：
//   - checkbox `#multi_seed` 受控；勾选 → 启用多 seed 对比
//   - number `#seed_count`（min=2 max=6，默认 3），由 parseSeedCount 解析 + clamp
//
// DOM 沿用旧 style.css `.field.row label.cb` / `.seed-count`（US-008 前 CSS 不动）。
// seed_count 始终可编辑（即使 multi_seed=false）；解析时 multi_seed=false 直接返回 1。

export interface MultiSeedControlsProps {
  /** 多 seed 对比开关。 */
  multi_seed: boolean;
  /** seed 数量字符串（input.value 口径）。 */
  seed_count: string;
  /** multi_seed checkbox 切换回调。 */
  onMulti: (v: boolean) => void;
  /** seed_count 输入变化回调（传入 input.value 字符串）。 */
  onCount: (v: string) => void;
}

export function MultiSeedControls({ multi_seed, seed_count, onMulti, onCount }: MultiSeedControlsProps) {
  return (
    <div className="field row">
      <label className="cb">
        <input
          id="multi_seed"
          type="checkbox"
          checked={multi_seed}
          onChange={(e) => onMulti(e.target.checked)}
        />
        多 seed 对比
      </label>
      <label className="cb seed-count">
        数量
        <input
          id="seed_count"
          type="number"
          value={seed_count}
          min={2}
          max={6}
          onChange={(e) => onCount(e.target.value)}
        />
      </label>
    </div>
  );
}

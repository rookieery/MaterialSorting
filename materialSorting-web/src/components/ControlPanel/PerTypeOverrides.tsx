// PerTypeOverrides —— 高级「每片型覆盖」面板（与旧 index.html `<details><div id="per_type">` 等价）。
//
// 与旧 vanilla 实现 renderPerType 一致：
//   1. 渲染 V03_PTYPES 10 行，每行：片型名（内片标 `<i>内</i>` 徽章）+ d 输入 + tol 输入。
//   2. placeholder 提示 d≤ / t≤ 上限（取自 V03_TABLE）。
//   3. 内部片（internal=true）用 d_int/tol_int 档，标 `<i>内</i>`；外部片用 d_ext/tol_ext 档。
//
// 字段按字符串持有（空 = 继承两档；非空 = 覆盖），collectParams 做解析（空 → 不写入 per_type）。

import { V03_PTYPES, V03_TABLE } from '../../constants/v03';
import type { PerTypeFormValue } from '../../lib/params';

export interface PerTypeOverridesProps {
  /** 每片型的 d/tol 输入字符串（key 全量 = V03_PTYPES）。 */
  values: Record<string, PerTypeFormValue>;
  /** 任一 input 变化时回写（key + 'd' | 'tol' + 新字符串）。 */
  onChange: (next: Record<string, PerTypeFormValue>) => void;
}

export function PerTypeOverrides({ values, onChange }: PerTypeOverridesProps) {
  function update(pt: string, key: 'd' | 'tol', v: string) {
    const prev = values[pt] ?? { d: '', tol: '' };
    onChange({ ...values, [pt]: { ...prev, [key]: v } });
  }

  return (
    <details className="advanced">
      <summary>高级：每片型覆盖</summary>
      <div className="per_type">
        {V03_PTYPES.map((pt) => {
          const entry = V03_TABLE[pt];
          const v = values[pt] ?? { d: '', tol: '' };
          return (
            <div className="pt-row" key={pt}>
              <span className="pt-name">
                {pt}
                {entry.internal && <i>内</i>}
              </span>
              <input
                type="number"
                min={0}
                step={0.5}
                placeholder={`d≤${entry.d}`}
                value={v.d}
                onChange={(e) => update(pt, 'd', e.target.value)}
              />
              <input
                type="number"
                min={0}
                step={1}
                placeholder={`t≤${entry.tol}`}
                value={v.tol}
                onChange={(e) => update(pt, 'tol', e.target.value)}
              />
            </div>
          );
        })}
      </div>
      <div className="dim small">空 = 继承两档；填值 = 覆盖该维度。受 v0.3 单片上限约束。</div>
    </details>
  );
}

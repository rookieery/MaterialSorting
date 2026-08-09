// 时间轴回放辅助纯函数（US-006 AC#2）。
//
// 与旧 legacy/app.js `maxElapsed` + `frameAtTime` 二分查找 字节级一致。
// 单 run 帧数可达数千，必须用二分（O(log n)）否则拖动 seekbar 会卡顿。
//
// 不变量：frames[].elapsed 单调非减（solver 按时间顺序 push，索引即顺序）。
// 解耦：本模块只接受 `{ frames }` 最小接口，不依赖 RunRecord 全字段。

import type { FrameMsg } from '../types/ws';

/** 本模块的最小输入接口（RunRecord / 测试 stub 都可传入）。 */
export interface FrameContainer {
  frames: readonly FrameMsg[];
}

/**
 * 所有 run 中最大 elapsed（s）。
 * 单 run 取 frames[last].elapsed；多 run 取 max。
 * 0 个 run 或所有 run 无帧 → 0。
 *
 * 与旧 app.js `maxElapsed()` 字节级一致：
 *   let m = 0;
 *   for (const r of runs) if (r.frames.length) m = Math.max(m, r.frames[r.frames.length-1].elapsed);
 *   return m;
 */
export function maxElapsed(runs: readonly FrameContainer[]): number {
  let m = 0;
  for (const r of runs) {
    if (r.frames.length > 0) {
      const last = r.frames[r.frames.length - 1].elapsed;
      if (last > m) m = last;
    }
  }
  return m;
}

/**
 * 二分查找：返回 frames 中 elapsed <= t 的最大索引对应的帧；空数组 → null。
 *
 * 与旧 app.js `frameAtTime(run, t)` 字节级一致（含 ans=0 兜底）：
 *   let lo = 0, hi = fr.length - 1, ans = 0;
 *   while (lo <= hi) {
 *     const mid = (lo + hi) >> 1;
 *     if (fr[mid].elapsed <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
 *   }
 *   return fr[ans];
 *
 * 边界：
 *   - 空 frames → null
 *   - t < fr[0].elapsed → 返回 fr[0]（ans 初始 0，循环不增）
 *   - t >= fr[last].elapsed → 返回 fr[last]
 *   - t == fr[i].elapsed → 返回 fr[i]
 */
export function frameAtTime(container: FrameContainer, t: number): FrameMsg | null {
  const fr = container.frames;
  if (fr.length === 0) return null;
  let lo = 0;
  let hi = fr.length - 1;
  let ans = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (fr[mid].elapsed <= t) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return fr[ans];
}

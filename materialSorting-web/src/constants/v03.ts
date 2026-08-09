// v0.3 工艺约束常量（与后端 constraints.py MAX_OVERLAP / ROTATION_TOL 一致；旧 vanilla 实现 V03）。
//
// 字段说明：
//   d         —— 该片型允许的最大重合深度 mm（erode 上限，对应 MAX_OVERLAP[ptype]）。
//   tol       —— 该片型允许的最大旋转公差 °（布纹线 ±，对应 ROTATION_TOL[ptype]）。
//   internal  —— true 表示「内部片」（单排/双排/火机袋/裤耳），用 d_int/tol_int 档；
//                false 表示「外部片」（前片/后片/腰/前袋/后袋/机头），用 d_ext/tol_ext 档。
//
// PerTypeOverrides 面板按此表渲染 10 行（V03_PTYPES 顺序固定），placeholder 提示 d≤ / t≤ 上限。

/** v0.3 每片型工艺上限条目（与 constraints.py MAX_OVERLAP / ROTATION_TOL 对齐）。 */
export interface V03Entry {
  /** 最大重合深度 mm（constraints.MAX_OVERLAP[ptype]）。 */
  d: number;
  /** 最大旋转公差 °（constraints.ROTATION_TOL[ptype]）。 */
  tol: number;
  /** 内部片 = 单排/双排/火机袋/裤耳，应用 d_int/tol_int 档；外部片应用 d_ext/tol_ext 档。 */
  internal: boolean;
}

/** v0.3 全部 10 片型的工艺上限（顺序固定，旧 vanilla 实现 V03 字面量 1:1）。 */
export const V03_TABLE: Record<string, V03Entry> = {
  前片: { d: 2, tol: 1, internal: false },
  后片: { d: 2, tol: 1, internal: false },
  腰: { d: 0.4, tol: 3, internal: false },
  前袋: { d: 0.4, tol: 30, internal: false },
  后袋: { d: 0.4, tol: 1, internal: false },
  机头: { d: 0.4, tol: 3, internal: false },
  单排: { d: 10, tol: 15, internal: true },
  双排: { d: 10, tol: 15, internal: true },
  火机袋: { d: 5, tol: 8, internal: true },
  裤耳: { d: 10, tol: 45, internal: true },
};

/** v0.3 全部 10 片型名（V03_TABLE key 顺序；PerTypeOverrides 行序与此一致）。 */
export const V03_PTYPES = Object.keys(V03_TABLE);

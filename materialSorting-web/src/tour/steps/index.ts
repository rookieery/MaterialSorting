// Tour 步骤注册表 + 版本号（US-029 基础设施 / US-030 previewTour / US-031 nestingTour）。
//
// 导出：
//   TOUR_VERSION — tour 内容版本号。tourStore init 比对 localStorage 中 ms.tour.version；
//                  不一致则清空全部 seen（强制重看）。仅步骤内容重大变更时 bump（小改不改版本）。
//   TOURS        — Partial<Record<TabId, TourDef>>，按 TabId 注册该 Tab 的指引序列。
//                  useTour.getActiveTour 读 TOURS[activeTour]，auto-trigger 读 TOURS[tab]
//                  判断该 Tab 是否有指引（无则跳过自动触发）。
//
// 版本号 bump 触发条件（写注释提醒未来维护者）：
//   - 仅步骤内容重大变更（增删步骤、改 ready 语义、改锚点导致旧 seen 语义失效）时 bump；
//   - 文案小改、微调 placement 不 bump（老用户无需重看）。
//   bump 后 tourStore init 自动清 seen（US-029 已实现），用户下次进 Tab 自动触发新版。
//
// 版本历史：
//   '1' → '2'（矩阵化重构 US-005）：previewTour parsed/set-qty 两步锚点从旧 SizeTabs/
//         piece-card-head 迁到 QtyMatrix 矩阵（qty-matrix / qty-rowhead）+ 文案改矩阵
//         操作描述 —— 锚点重大变更，老用户 seen 强制清空重看。
//   '2' → '3'（图形预览区拆除）：ParsedPiecesView 按码图形预览区删除（卡片点击放大与
//         矩阵行头缩略图弹同一 PieceZoomModal，交互冗余）；parsed 步文案改矩阵 + 缩略图
//         放大描述。锚点未变，但旧文案指引的「下方图形预览」已不存在 —— 步骤内容重大
//         变更，bump 强制老用户重看。
//   '3' → '4'（矩阵行头简化）：行头只留序号徽章 + 64×64 缩略图，裁片名 / ×2 徽章 /
//         「填充」按钮（整行填默认值弹层）拆除；set-qty 步文案不再指引行头填充与 ×2 徽章
//         —— 被指引的交互已不存在，bump 强制老用户重看。
//   '4' → '5'（行级整行设值回归 + 整表重置拆除）：工具条「重置为默认 1」拆除；行头
//         缩略图右侧新增常驻「≡」整行设值 icon（title 悬浮提示，点击开居中弹层批量设
//         整行统一值，特例 = 应用后单格改）；set-qty 步文案重新指引行级批量设值 ——
//         被指引的交互变化，bump 强制老用户重看。
//   '5' → '6'（数量矩阵行列转置）：行 = 尺码（行头码按钮切 activeSize）、列 = 裁片
//         （列头缩略图 + ≡ 整列设值），对齐 PerTypeOverridesModal 高级配置弹窗「裁片
//         作列」风格；parsed/set-qty 步文案改转置后方位（整行设值 → 整列设值）——
//         被指引的布局重大变更，bump 强制老用户重看。
//   '6' → '7'（裁片编号化重构 US-003）：总片数口径从「配对 ×2」改为「Σ 数量（每份
//         对应母版一个轮廓，不合成镜像）」，set-qty 步文案同口径改写；committed 步
//         「按片型」改「按裁片 g 码」—— 被指引的数量语义重大变更，bump 强制老用户重看。
//   '7' → '8'（2026-09-12 编辑排料 / 保存当前方案补位）：nestingTour 从 5 步扩为
//         7 步，result 与 export 之间插入 edit（编辑排料，edit-controls 锚点）与
//         save（保存当前方案，save-state-group 锚点）—— 两功能为 2026-09 新增且关键
//         交互不可自我发现（右键拖动吸附 / .msn 上传即恢复），锚点虽已随组件预埋但
//         此前无步骤引用；export 步文案同步对齐现行四格式下拉（原仅提 DXF/PNG）。
//         增删步骤属重大变更，bump 强制老用户重看（preview 指引随之重放一次，既有惯例）。
//
// Partial 而非完整 Record<TabId, TourDef>：保留未来新增 Tab 时不必同步补 tour 的灵活性；
// auto-trigger 对无指引的 Tab（TOURS[tab]===undefined）直接跳过，不报错。

import type { TabId } from '../../store/uiStore';
import type { TourDef } from '../types';
import { nestingTour } from './nestingTour';
import { previewTour } from './previewTour';

/** Tour 内容版本号。bump 触发条件：仅步骤内容重大变更时 bump（强制老用户重看）。版本历史见文件头注释。 */
export const TOUR_VERSION = '8';

/**
 * 按 TabId 注册的指引序列。
 * preview：5 步上传预览指引（US-030）。
 * nesting：7 步超排指引（US-031；2026-09-12 扩 edit/save 两步，result/edit/save/export
 *          四步用 runRegistry 帧快照联动推进）。
 */
export const TOURS: Partial<Record<TabId, TourDef>> = {
  preview: previewTour,
  nesting: nestingTour,
};

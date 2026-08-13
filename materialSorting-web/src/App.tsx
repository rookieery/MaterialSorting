// App —— 顶层骨架（US-001：Tab 框架 + NestingPage 外提）。
//
// 职责：
//   1. 渲染 <TabBar/>（顶部 Tab 切换，uiStore.activeTab 驱动）。
//   2. 双页面共存 —— NestingPage 与 PreviewPage 都常驻 DOM，由 `.hidden`（display:none）
//      切换显隐（AC#4 不卸载）。切回排料页时进行中的求解 / WS / 播放 seek 全部保留
//      （NestingPage 内 useState/useRef/runRegistry 不被销毁）。
//   3. 顶层挂一个 <Tooltip/>（Portal 到 body，整 App 生命周期单例；多挂会 clobber）。
//
// 关键不变量（与 US-006 关键约定 #3 一致）：Tooltip 是模块级单例，App 内只挂一个。
// US-001 把排料状态机（seeds/solving/status/useSolveRun/useRafThrottle/handleStart）
// 全部下移到 NestingPage；App 仅保留 Tab + 页面容器 + Tooltip。
//
// 数据流：
//   TabBar setTab → uiStore.activeTab → App 重渲染切 .hidden → NestingPage/PreviewPage 不卸载

import { Tooltip } from './components/Tooltip';
import { NestingPage } from './components/NestingPage';
import { PreviewPage } from './components/preview/PreviewPage';
import { TabBar } from './components/TabBar';
import { TourOverlay } from './tour/TourOverlay';
import { useUiStore } from './store/uiStore';

export function App(): React.JSX.Element {
  const activeTab = useUiStore((s) => s.activeTab);

  return (
    <div className="app">
      <TabBar />

      <div className="tab-content">
        {/* 排料页：US-005 多 seed / US-006 seek / US-007 导出 全部内聚于此 */}
        <div className={`page${activeTab === 'nesting' ? '' : ' hidden'}`}>
          <NestingPage />
        </div>

        {/* 上传预览页：US-001 占位，US-008 落地 UploadPanel + SizeTabs + ParsedPiecesView */}
        <div className={`page${activeTab === 'preview' ? '' : ' hidden'}`}>
          <PreviewPage />
        </div>
      </div>

      {/* US-006 AC#5：Tooltip 用 React Portal 到 body，fixed 定位；app 生命周期内单例。 */}
      <Tooltip />
      {/* US-029：TourOverlay 单例（Portal 到 body，z-index 2000），订阅 tourStore 自显隐。 */}
      <TourOverlay />
    </div>
  );
}

import { useState } from 'react';

// US-001 占位：脚手架联通优先，详细控制面板/排料图/曲线/回放在 US-002..007 实现。
export function App() {
  const [tick, setTick] = useState(0);
  return (
    <div className="app">
      <aside className="panel">
        <h2>求解控制</h2>
        <div className="hint">
          React + TypeScript + Vite 脚手架已就绪（US-001）。
          <br />
          WS/导出已在 vite.config.ts 配置代理 → :8000。
        </div>
        <button id="start" type="button" onClick={() => setTick((t) => t + 1)}>
          点击验证交互（{tick}）
        </button>
        <div className="status" id="status">
          就绪
        </div>
      </aside>
      <main className="main">
        <div className="nest-wrap">
          <div id="nests" className="nests" />
        </div>
        <div className="bottom">
          <div className="curve-wrap">
            <svg id="curve" xmlns="http://www.w3.org/2000/svg" />
          </div>
          <div className="playback">
            <div className="field-label">回放</div>
            <input id="seek" type="range" min={0} max={0} value={0} disabled />
            <div id="seek-readout">—</div>
          </div>
        </div>
      </main>
    </div>
  );
}

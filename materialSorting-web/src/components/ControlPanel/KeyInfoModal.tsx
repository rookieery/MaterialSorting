// KeyInfoModal ——「系统key」弹窗（prd-key-authorization-system US-006 + US-011）。
//
// 三区块（数据源 = keyStore → 后端 /api/key/state|list|save|merge，见 routes_key.py）：
//   ① 正在使用的key 输入/替换 + 保存 —— POST /api/key/save（bind 成功才落盘），
//     失败中文红字透传（如「key 不存在：请检查输入是否正确」）；保存落定后
//     输入框对齐实际生效 key（失败回退旧 key）—— 输入框与属性区恒同 key；
//   ② 系统可使用的key 表格（US-011，替代旧 textarea 批量粘贴）—— GET
//     /api/key/list 本机绑定且「正在使用」态的 key：名称=明文 / 类型 / 剩余
//     （天数或次数）/ 操作列两枚图标按钮：
//       · 启用（电源图标）= saveKey(行key)（已绑本机 → bind 幂等即切换）；
//         正在启用的行高亮 + 按钮置灰不可点；
//       · 合并（并入箭头图标，仅时长型且非正在启用的行显示）= mergeKeys([行key])
//         并入正在使用的key（本机无正在使用 key 时不显示 —— 无 target）；
//     合并成功 = 表格随动刷新（store 链式 fetchKeyList）+ 一行明细；整体失败
//     红字（无 key 指路等）；
//   ③ 属性展示 —— 状态徽标（六态中文标签）+ 次数型 总数/已用/剩余 或
//     时长型 生效/截止/剩余天数（keyserver _info_payload 契约，前端零公式）。
//
// **localStorage ms_key 镜像口径**：弹窗打开**先用 localStorage 即时预填** key
// 输入框（store 模块求值已读镜像，不等网络往返）→ mount 即 fetchState 对账
// **以后端为准**（清缓存/换浏览器不丢 key —— 后端 key_state.json 权威）；保
// 存成功双写（后端文件 + localStorage，见 keyStore.saveKey）。对账回写不覆盖
// 用户编辑中的草稿（dirty 标记）。
//
// 骨架镜像 ExportInfoModal：声明式受控 Portal（订阅 controlPanelStore.modal ===
// 'key_info' 自显隐，单例互斥由 store 单字段保证）+ ESC / 遮罩 / ✕ 只关不提交；
// 每次打开重新 mount（条件渲染）→ 对账/草稿状态不跨开残留。打开入口 =
// ControlPanel「导出最优方案」区块正下方的「系统key」按钮。

import { useEffect, useRef, useState } from 'react';
import type { JSX } from 'react';
import { createPortal } from 'react-dom';
import { useControlPanelStore } from '../../store/controlPanelStore';
import { useKeyStore, type KeyInfo } from '../../store/keyStore';

export function KeyInfoModal(): JSX.Element | null {
  const modal = useControlPanelStore((s) => s.modal);
  if (modal !== 'key_info') return null;
  return <KeyInfoModalInner key="key-info-modal" />;
}

/** 属性只读行（label 左 / 值右，.export-ro-row 同款紧凑单行视觉）。 */
function attrRow(label: string, value: string, testid: string): JSX.Element {
  return (
    <div className="key-attr-row" data-testid={testid} key={testid}>
      <span className="export-ro-label">{label}</span>
      <span className="key-attr-value">{value}</span>
    </div>
  );
}

/** 状态徽标色阶：正在使用=绿（主题色）；已过期/已用完/已合并=红；其余（未绑定/
 * 未激活）=灰。六态标签集见 keyserver models.STATUS_LABELS。 */
function badgeClass(status: string): string {
  if (status === '正在使用') return 'key-status-badge ok';
  if (status === '已过期' || status === '已用完' || status === '已合并') {
    return 'key-status-badge bad';
  }
  return 'key-status-badge idle';
}

/** 启用图标（电源符号，操作列用）—— 内联 SVG，项目无图标库依赖。 */
function IconPower(): JSX.Element {
  return (
    <svg className="key-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M8 1.8v5.4" />
      <path d="M4.4 4.1a5.4 5.4 0 1 0 7.2 0" />
    </svg>
  );
}

/** 合并图标（箭头并入竖条 = 并入正在使用的key，操作列用）。 */
function IconMerge(): JSX.Element {
  return (
    <svg className="key-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M1.5 8h7" />
      <path d="M5.5 4.5 9 8l-3.5 3.5" />
      <path d="M12.5 3v10" />
    </svg>
  );
}

/** ③ 属性展示区块（keyInfo 非空时）：徽标 + 型别专属行。绑定系统/备注是
 * 后台管理端才能看到的内容，不在此弹窗展示（info 里仍会随契约下发）。 */
function AttrSection({ info }: { info: KeyInfo }): JSX.Element {
  const rows: JSX.Element[] = [];
  if (info.type === 'count') {
    rows.push(attrRow('总次数', String(info.total_uses ?? '—'), 'key-attr-total'));
    rows.push(attrRow('已用次数', String(info.used_uses ?? '—'), 'key-attr-used'));
    rows.push(attrRow('剩余次数', String(info.remaining_uses ?? '—'), 'key-attr-remaining'));
  } else {
    rows.push(attrRow('生效时间', info.activated_at ?? '未激活', 'key-attr-activated'));
    rows.push(attrRow('截止时间', info.expires_at ?? '—', 'key-attr-expires'));
    rows.push(attrRow('剩余天数', String(info.remaining_days ?? '—'), 'key-attr-days'));
  }
  return (
    <>
      <div className="key-attr-row" data-testid="key-attr-status">
        <span className="export-ro-label">状态</span>
        <span className={badgeClass(info.status)}>{info.status}</span>
      </div>
      {rows}
    </>
  );
}

function KeyInfoModalInner(): JSX.Element {
  const closeModal = useControlPanelStore((s) => s.closeModal);

  const key = useKeyStore((s) => s.key);
  const keyInfo = useKeyStore((s) => s.keyInfo);
  const error = useKeyStore((s) => s.error);
  const saving = useKeyStore((s) => s.saving);
  const saveError = useKeyStore((s) => s.saveError);
  const merging = useKeyStore((s) => s.merging);
  const mergeError = useKeyStore((s) => s.mergeError);
  const mergeResult = useKeyStore((s) => s.mergeResult);
  const keyList = useKeyStore((s) => s.keyList);
  const listError = useKeyStore((s) => s.listError);

  // ① key 草稿：mount 即 store.key（= localStorage 镜像即时预填，不等网络）。
  // 对账回写（fetchState 落定）仅在用户未编辑时同步 —— 脏草稿不被后端覆盖。
  const [draft, setDraft] = useState(() => useKeyStore.getState().key ?? '');
  const dirtyRef = useRef(false);
  useEffect(() => {
    if (!dirtyRef.current) setDraft(useKeyStore.getState().key ?? '');
  }, [key]);

  // mount 一次性对账：state 以后端为准 + 拉取「系统可使用的key」表格（每次
  // 打开重新 mount）。保存/合并成功后的随动刷新在 store 内链式完成。
  useEffect(() => {
    void useKeyStore.getState().fetchState();
    void useKeyStore.getState().fetchKeyList();
  }, []);

  // ESC 关闭（仅关弹窗，镜像 ExportInfoModal）。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      closeModal();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [closeModal]);

  // 保存/启用共用落定路径（成败都）后输入框对齐实际生效 key：成功 → 新 key
  // （dirty 复位，后续对账可跟随）；失败 → 回退旧 key（「正在使用的key」框与
  // 属性区恒显示同一把实际绑定的 key，不残留未保存成功的草稿造成「输入框 A /
  // 属性 B」的不一致，失败原因见红字）。表格行「启用」= 同一 save 链路（已绑
  // 本机 → bind 幂等即切换正在使用的key，US-011）。
  function applySave(rawKey: string): void {
    if (saving || rawKey.trim() === '') return; // 按钮已置灰，兜底
    void useKeyStore.getState().saveKey(rawKey).then(() => {
      dirtyRef.current = false;
      setDraft(useKeyStore.getState().key ?? '');
    });
  }

  // 表格行「合并」：行 key 并入正在使用的 key（单 source，与旧 textarea 批量
  // 合并同链路 POST /api/key/merge）。
  function handleMergeRow(rowKey: string): void {
    if (merging) return; // 按钮已置灰，兜底
    void useKeyStore.getState().mergeKeys([rowKey]);
  }

  function handleOverlayMouseDown(e: React.MouseEvent): void {
    if (e.target === e.currentTarget) closeModal();
  }

  function handleModalMouseDown(e: React.MouseEvent): void {
    e.stopPropagation();
  }

  return createPortal(
    <div
      className="strategy-overlay"
      onMouseDown={handleOverlayMouseDown}
      data-testid="key-info-overlay"
    >
      <div
        className="strategy-modal key-modal"
        role="dialog"
        aria-modal="true"
        aria-label="系统key"
        onMouseDown={handleModalMouseDown}
      >
        <div className="strategy-head">
          <span className="strategy-title">系统key</span>
          <button
            type="button"
            className="strategy-close"
            aria-label="关闭"
            onClick={closeModal}
            data-testid="key-info-close"
          >
            ✕
          </button>
        </div>

        {/* ① 正在使用的key 输入/替换 + 保存 */}
        <div className="key-section" data-testid="key-info-current">
          <span className="key-section-title">正在使用的key</span>
          <div className="key-save-row">
            <input
              id="key-current"
              type="text"
              className="strategy-text-input"
              data-testid="key-info-key-input"
              value={draft}
              placeholder={key === null ? '输入授权 key（例如 MS-XXXXX）' : '替换正在使用的key'}
              spellCheck={false}
              onChange={(e) => {
                dirtyRef.current = true;
                setDraft(e.target.value);
              }}
            />
            <button
              type="button"
              className="key-save-btn"
              disabled={saving || draft.trim() === ''}
              onClick={() => applySave(draft)}
              data-testid="key-info-save"
            >
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
          {saveError !== null && (
            <div className="key-error" data-testid="key-info-save-error">
              {saveError}
            </div>
          )}
          <div className="strategy-hint">
            保存将把 key 绑定到本机（绑定后其他系统无法使用同一 key）；时长型 key
            绑定即开始计时。
          </div>
        </div>

        {/* ② 系统可使用的key 表格（US-011，替代旧 textarea 批量粘贴）：本机绑定
            且有效的 key；启用 = 切换正在使用的key（当前行高亮 + 按钮置灰）；
            合并（仅时长型非启用行）= 并入正在使用的key。 */}
        <div className="key-section" data-testid="key-info-list">
          <span className="key-section-title">系统可使用的key</span>
          {listError !== null ? (
            <div className="key-error" data-testid="key-info-list-error">
              {listError}
            </div>
          ) : keyList === null ? (
            <div className="strategy-hint" data-testid="key-info-list-loading">
              正在查询本机可用 key…
            </div>
          ) : keyList.length === 0 ? (
            <div className="strategy-hint" data-testid="key-info-list-empty">
              暂无绑定到本机的可用 key：在上方输入 key 并保存后即可在此管理。
            </div>
          ) : (
            <table className="key-table" data-testid="key-info-table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>类型</th>
                  <th>剩余</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {[...keyList]
                  .sort((a, b) => Number(b.key === key) - Number(a.key === key))
                  .map((row) => {
                    const active = row.key === key;
                    const canMerge =
                      row.type === 'duration' && !active && key !== null;
                    return (
                      <tr
                        key={row.key}
                        className={active ? 'key-table-row active' : 'key-table-row'}
                        data-testid="key-info-row"
                        data-key={row.key}
                        data-active={active ? 'true' : 'false'}
                      >
                        <td className="key-table-name" data-testid="key-info-row-key">
                          {row.key}
                        </td>
                        <td>{row.type === 'count' ? '次数型' : '时长型'}</td>
                        <td>
                          {row.type === 'count'
                            ? `${row.remaining_uses ?? '—'} 次`
                            : `${row.remaining_days ?? '—'} 天`}
                        </td>
                        <td className="key-table-actions">
                          <button
                            type="button"
                            className="key-icon-btn"
                            disabled={active || saving}
                            onClick={() => applySave(row.key)}
                            title={active ? '正在使用' : '启用此key'}
                            aria-label={active ? '正在使用' : '启用此key'}
                            data-testid="key-info-enable"
                          >
                            <IconPower />
                          </button>
                          {canMerge && (
                            <button
                              type="button"
                              className="key-icon-btn"
                              disabled={merging}
                              onClick={() => handleMergeRow(row.key)}
                              title="合并到正在使用的key"
                              aria-label="合并到正在使用的key"
                              data-testid="key-info-merge-one"
                            >
                              <IconMerge />
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          )}
          {mergeError !== null && (
            <div className="key-error" data-testid="key-info-merge-error">
              {mergeError}
            </div>
          )}
          {mergeResult !== null && (
            <div className="key-merge-result" data-testid="key-info-merge-result">
              {mergeResult.sources.map((s) => (
                <div className="key-merge-row" data-testid="key-info-merge-row" key={s.key}>
                  {s.key} 已合并：+{s.transferred_days} 天
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ③ 属性展示 + 状态徽标（未绑定 → 引导文案 / 未绑定 + error = 服务端
            自动解绑解释；有 key 无 info → 对账中/失败） */}
        <div className="key-section" data-testid="key-info-attrs">
          <span className="key-section-title">属性</span>
          {keyInfo !== null ? (
            <AttrSection info={keyInfo} />
          ) : key !== null ? (
            error !== null ? (
              <div className="key-error" data-testid="key-info-attr-error">
                {error}
              </div>
            ) : (
              <div className="strategy-hint" data-testid="key-info-loading">
                正在查询 key 属性…
              </div>
            )
          ) : error !== null ? (
            // 未绑定 + error：/api/key/state 发现本地 key 已在 keyserver 侧删除
            // 自动解绑后的解释（key=null → 引导输入在 placeholder，此处告知原因）
            <div className="key-error" data-testid="key-info-unbound-reason">
              {error}
            </div>
          ) : (
            <div className="strategy-hint" data-testid="key-info-empty-hint">
              尚未绑定授权 key：在上方输入 key 并保存后即可运行排料。
            </div>
          )}
        </div>

        <div className="strategy-actions">
          <button
            type="button"
            className="strategy-btn-again"
            onClick={closeModal}
            data-testid="key-info-done"
          >
            关闭
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

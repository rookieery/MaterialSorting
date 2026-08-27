"""uploads 磁盘 TTL 清理（PRD web 多会话 US-006）。

背景：多会话放开后 ``out/uploads/`` 只进不出 —— 每次上传落 ``<doc_id>.dxf``（~3MB）、
commit 建 ``<doc_id>_pieces/``（110 个单裁片 dxf + manifest + intermediate），策略
start 再落 ``strategy_cfg_*.json``；会话过期后这些文件无人引用也无人删，多会话
场景下磁盘占用无界。本模块按 TTL（``MS_UPLOAD_TTL_DAYS`` 缺省 14 天，按 mtime）
扫描清理，**绝不误删在用文档**：

- **删除对象**（只认 ``out/uploads/`` 内三类 web 自有产物，其余命名一律不动）：
  1. 超龄 ``<doc_id>.dxf`` + ``<doc_id>_pieces/`` **成对**目录 —— 同一 doc 任一侧
     （dxf / pieces 目录）未超龄则**整对保留**（commit 会重写 pieces 目录但不刷新
     dxf 的 mtime，按单侧独立判龄会误删仍可被同 doc commit 引用的母版）；
  2. 孤儿单边（只有 dxf 或只有 ``_pieces`` 目录）—— 按同 TTL 单独判龄清理；
  3. 超龄 ``strategy_cfg_*.json``（策略 start 的 config 快照；进行中 run 的 cfg 至多
     60 分钟龄，14 天 TTL 下天然不命中，无需额外保护）。
- **保护集**：SessionRegistry 活跃会话 doc_id（``active_doc_ids``：``st.doc_id`` ∪
  会话快照 ``state['doc']['doc_id']``）∪ ``out/config_runs/.web_strategy_active*.json``
  marker 内 doc_id（进行中策略 run spawn 时引用的 master_dxf —— 会话 B 已过期但
  run 仍在跑时不误删）∪ mtime 未超龄者。
- **触发时机**：进程启动（``server.main`` → ``start_startup_cleaner``，daemon 线程
  不阻塞启动；**只在真正 server 进程触发**，TestClient 导入 app 不起线程不碰真实
  ``out/``）+ 每次 commit 成功后（路由尾 ``trigger_cleanup(uploads_dir=UPLOADS_DIR)``
  —— 显式传 server 模块级常量，测试 monkeypatch ``server_mod.UPLOADS_DIR`` 后清理
  范围自动跟随 tmp）。``trigger_cleanup`` 吞掉一切异常仅 warn；单条目删除失败
  （目录被占用等）同样 warn 跳过继续，绝不阻塞主流程。

分层：模块级仅标准库 + ``..paths``；对 ``.sessions`` / ``.strategy`` 的依赖走函数内
延迟 import（marker 文件名前缀单一真相源在 strategy，不复制字符串；sessions 的
注册表单例同理）。**禁 import ``.server`` / ``..cli.*``**（AST 守卫见
tests/test_web_diskclean.py）。

冒烟：``python -m materialsorting.web.diskclean`` —— 临时目录模拟场景自检（超龄对
删除 / 未超龄与保护集保留 / 孤儿清理 / dry-run）+ 对真实 ``out/`` **dry-run** 打印
将删清单（不动真实文件）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from .. import paths

__all__ = ['UPLOAD_TTL_DAYS', 'scan_uploads', 'trigger_cleanup',
           'start_startup_cleaner']


def _env_days(name: str, default: float) -> float:
    """解析环境变量天数（float，>0）；缺失/非法/非正 → warn 回退缺省。"""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        val = float(str(raw).strip())
        if val <= 0:
            raise ValueError('须为正数')
        return val
    except ValueError:
        print(f'[diskclean] 环境变量 {name}={raw!r} 非法，回退缺省 {default:g}',
              file=sys.stderr)
        return default


# uploads TTL（天）：上传母版 / 切片目录 / 策略 cfg 的保留期，按 mtime 判龄。
UPLOAD_TTL_DAYS: float = _env_days('MS_UPLOAD_TTL_DAYS', 14.0)

_DAY_SEC = 86400.0


def _uploads_dir() -> Path:
    """``out/uploads/``（调用时取 ``paths.OUT_DIR`` 属性 —— monkeypatch 生效）。"""
    return Path(paths.OUT_DIR) / 'uploads'


def _config_runs_dir() -> Path:
    """``out/config_runs/``（marker 落点；调用时取属性，同上）。"""
    return Path(paths.CONFIG_RUNS_DIR)


# ---------------------------------------------------------------- 保护集

def _session_doc_ids(registry=None) -> set[str]:
    """活跃会话 doc_id 集（缺省单例 ``sessions.registry``；测试可注入私有注册表）。

    读取失败 → warn 后按空集继续：活跃会话的产物 mtime 都新（刚上传/commit，TTL
    判龄天然保住），注册表保护集真正的价值在「老 mtime 仍被会话持有」场景，罕见
    失败不构成误删风险。
    """
    if registry is None:
        from .sessions import registry as _singleton
        registry = _singleton
    try:
        return registry.active_doc_ids()
    except Exception as e:
        print(f'[diskclean] 活跃会话 doc_id 读取失败（按空集继续）：{e}',
              file=sys.stderr)
        return set()


def _marker_doc_ids(config_runs: Path) -> set[str]:
    """全部策略 marker（default 旧名 ``.web_strategy_active.json`` + sid 会话分文件
    ``.web_strategy_active_<sid>.json``）内的 doc_id 集。

    marker = 进行中策略 run 的快照（``{pid, run_dir, doc_id, mode, started_at}``），
    其 ``doc_id`` 即该 run spawn 时引用的母版 —— **会话已过期但 run 仍在跑时这是
    唯一保护来源**（注册表逐出不通知磁盘）。坏 JSON / 缺键 → 跳过（run 已死或写入
    竞态，无从保护）。文件名前缀单一真相源在 strategy（延迟 import，不复制字符串）。
    """
    from .strategy import _MARKER_SID_PREFIX
    stem = _MARKER_SID_PREFIX.rstrip('_')          # '.web_strategy_active'
    ids: set[str] = set()
    try:
        markers = list(config_runs.glob(stem + '*.json'))
    except OSError:
        return ids
    for mk in markers:
        try:
            raw = json.loads(mk.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict):
            doc_id = raw.get('doc_id')
            if isinstance(doc_id, str) and doc_id:
                ids.add(doc_id)
    return ids


def _mtime(path: Path) -> float:
    """mtime；读不到（权限/竞态消失）返回 +inf —— 按「未超龄」保护处理（宁漏删不误删）。"""
    try:
        return path.stat().st_mtime
    except OSError:
        return float('inf')


# ---------------------------------------------------------------- 扫描 / 清理

def _delete_entry(path: Path) -> None:
    """删除单条目（文件 unlink / 目录 rmtree）；失败抛 OSError 由调用方 warn 跳过。"""
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def scan_uploads(*, dry_run: bool = False,
                 uploads_dir: Path | str | None = None,
                 config_runs_dir: Path | str | None = None,
                 ttl_days: float | None = None,
                 now: float | None = None,
                 registry=None) -> list[str]:
    """扫描 ``out/uploads/`` 清超龄产物。

    返回本轮删除的条目名列表（``dry_run=True`` 时为「将删」清单且不动任何文件）。
    全参数可注入（目录 / TTL / 时钟 / 注册表）—— 测试与 ``__main__`` 冒烟不依赖
    真实墙钟与真实 ``out/``。单条目删除失败 warn 跳过继续（best-effort）。
    """
    uploads = Path(uploads_dir) if uploads_dir is not None else _uploads_dir()
    cfg_root = (Path(config_runs_dir) if config_runs_dir is not None
                else _config_runs_dir())
    ttl = UPLOAD_TTL_DAYS if ttl_days is None else float(ttl_days)
    if ttl <= 0:                       # 非正 TTL = 关闭清理（防御，env 侧已挡）
        return []
    now = time.time() if now is None else now
    cutoff = now - ttl * _DAY_SEC

    protected = _session_doc_ids(registry) | _marker_doc_ids(cfg_root)

    try:
        entries = sorted(uploads.iterdir())
    except OSError:
        return []                      # 目录不存在（从未上传）/ 不可读 → 无事可做

    # 归类：doc_id → {侧: path}（成对/孤儿单边统一表达）+ 独立的 strategy_cfg 文件。
    # 文件名不识别模式（非 <SID_RE>.dxf / 非 *_pieces / 非 strategy_cfg_*.json）
    # 一律不动 —— 只管理 web 自己的产物。
    from .sessions import SID_RE
    docs: dict[str, dict[str, Path]] = {}
    cfg_files: list[Path] = []
    for entry in entries:
        name = entry.name
        try:
            is_file, is_dir = entry.is_file(), entry.is_dir()
        except OSError:
            continue
        if is_file and name.startswith('strategy_cfg_') and name.endswith('.json'):
            cfg_files.append(entry)
        elif is_file and name.endswith('.dxf'):
            doc_id = name[:-len('.dxf')]
            if SID_RE.match(doc_id):
                docs.setdefault(doc_id, {})['dxf'] = entry
        elif is_dir and name.endswith('_pieces'):
            doc_id = name[:-len('_pieces')]
            if SID_RE.match(doc_id):
                docs.setdefault(doc_id, {})['pieces'] = entry

    victims: list[Path] = []
    for doc_id, sides in docs.items():
        if doc_id in protected:
            continue                   # 活跃会话 / marker 引用 → 整对不动
        if any(_mtime(p) > cutoff for p in sides.values()):
            continue                   # 任一侧未超龄 → 整对保留（防误删可 commit 母版）
        victims.extend(sides.values())
    victims.extend(p for p in cfg_files if _mtime(p) <= cutoff)

    removed: list[str] = []
    for p in victims:
        if dry_run:
            removed.append(p.name)
            continue
        try:
            _delete_entry(p)
            removed.append(p.name)
        except OSError as e:
            print(f'[diskclean] 删除失败（跳过继续）：{p}：{e}', file=sys.stderr)
    return removed


def trigger_cleanup(uploads_dir: Path | str | None = None, **kwargs) -> list[str]:
    """best-effort 清理入口（commit 成功后 / 启动线程调用）：吞掉一切异常仅 warn。

    ``uploads_dir`` 提为显式首位参数 —— commit 路由经 ``run_in_executor`` 只能传
    位置参数（显式传 server 模块级 ``UPLOADS_DIR``，测试 monkeypatch 后清理范围
    自动跟随 tmp）。``scan_uploads`` 自身已对单条目删除失败容错；本函数再兜一层
    「扫描阶段」的意外异常（保护集读取 / iterdir 等）—— **绝不向调用方抛**，
    返回已删条目（失败时 []）。
    """
    try:
        if uploads_dir is not None:
            return scan_uploads(uploads_dir=uploads_dir, **kwargs)
        return scan_uploads(**kwargs)
    except Exception as e:
        print(f'[diskclean] uploads 清理异常（忽略继续）：{e}', file=sys.stderr)
        return []


def start_startup_cleaner() -> threading.Thread:
    """进程启动清理（``server.main`` 调用一次）：daemon 线程跑一轮 ``trigger_cleanup``。

    后台执行不阻塞启动（长期未清理的机器首启可能积压大量超龄目录，rmtree 数百文件
    秒级）；daemon=True 进程退出不等待。无状态可重复调用（每调用排一轮）。
    """
    t = threading.Thread(target=trigger_cleanup, name='ms-diskclean', daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------- 冒烟入口

def _smoke() -> int:
    """``python -m materialsorting.web.diskclean``：临时目录场景自检 + 真实 dry-run。

    场景自检在 ``tempfile`` 私有目录（显式 ``now`` 时钟，零真实墙钟等待、不触碰
    真实 ``out/``）；随后对真实 ``out/uploads/`` **dry-run** 打印将删清单（只读）。
    """
    from .sessions import SessionRegistry, _FakeClock

    print(f'[diskclean] 配置 MS_UPLOAD_TTL_DAYS={UPLOAD_TTL_DAYS:g} '
          f'uploads={_uploads_dir()} config_runs={_config_runs_dir()}')

    now = 2_000_000.0
    day = _DAY_SEC
    results: list[tuple[str, bool]] = []

    def check(name: str, cond: bool) -> None:
        results.append((name, bool(cond)))

    with tempfile.TemporaryDirectory(prefix='ms_diskclean_smoke_') as td:
        uploads = Path(td) / 'out' / 'uploads'
        cfg_runs = Path(td) / 'out' / 'config_runs'
        uploads.mkdir(parents=True)
        cfg_runs.mkdir(parents=True)

        def mk_dxf(doc_id: str, age_days: float) -> Path:
            p = uploads / f'{doc_id}.dxf'
            p.write_bytes(b'x')
            os.utime(p, (now - age_days * day, now - age_days * day))
            return p

        def mk_pieces(doc_id: str, age_days: float) -> Path:
            p = uploads / f'{doc_id}_pieces'
            p.mkdir()
            (p / 'pieces_intermediate.json').write_text('{}', encoding='utf-8')
            os.utime(p, (now - age_days * day, now - age_days * day))
            return p

        old_dxf, old_pieces = mk_dxf('olddoc0001', 20.0), mk_pieces('olddoc0001', 20.0)
        new_dxf, new_pieces = mk_dxf('newdoc0002', 1.0), mk_pieces('newdoc0002', 1.0)
        sess_dxf, sess_pieces = mk_dxf('sessdoc0003', 20.0), mk_pieces('sessdoc0003', 20.0)
        mark_dxf = mk_dxf('markdoc0004', 20.0)           # 仅 dxf：marker 保护（run 在跑）
        orphan_dxf = mk_dxf('orphdoc0005', 20.0)         # 孤儿 dxf（无 pieces）
        orphan_pieces = mk_pieces('orphdoc0006', 20.0)   # 孤儿 pieces（无 dxf）
        fresh_orphan = mk_dxf('freshdo0007', 1.0)        # 未超龄孤儿
        mix_dxf, mix_pieces = mk_dxf('mixdoc0008', 20.0), mk_pieces('mixdoc0008', 1.0)
        old_cfg = uploads / 'strategy_cfg_20260101-000000.json'
        old_cfg.write_text('{}', encoding='utf-8')
        os.utime(old_cfg, (now - 20 * day, now - 20 * day))
        new_cfg = uploads / 'strategy_cfg_20260202-000000.json'
        new_cfg.write_text('{}', encoding='utf-8')
        stray = uploads / 'not_web_file.txt'
        stray.write_text('keep', encoding='utf-8')

        # marker：sid 会话分文件（B 过期但 run 在跑）+ default 旧名，各护一个 doc。
        (cfg_runs / '.web_strategy_active_bbbbbbbb1111.json').write_text(
            json.dumps({'pid': 1, 'run_dir': None, 'doc_id': 'markdoc0004',
                        'mode': 'se', 'started_at': 'x'}), encoding='utf-8')
        (cfg_runs / '.web_strategy_active.json').write_text(
            json.dumps({'doc_id': 'newdoc0002'}), encoding='utf-8')

        # 私有注册表：会话 A 活跃（doc 老龄仍被引用）。
        reg = SessionRegistry(clock=_FakeClock(now))
        reg.resolve('aaaaaaaa1111', create=True).doc_id = 'sessdoc0003'

        removed = scan_uploads(uploads_dir=uploads, config_runs_dir=cfg_runs,
                               ttl_days=14.0, now=now, registry=reg)
        check('超龄成对目录被删（dxf + pieces）',
              not old_dxf.exists() and not old_pieces.exists())
        check('未超龄成对保留', new_dxf.exists() and new_pieces.exists())
        check('活跃会话 doc 不删（老龄仍被引用）',
              sess_dxf.exists() and sess_pieces.exists())
        check('marker 引用 doc 不删（会话过期但 run 在跑）', mark_dxf.exists())
        check('孤儿单边 dxf 清理', not orphan_dxf.exists())
        check('孤儿单边 pieces 目录清理', not orphan_pieces.exists())
        check('未超龄孤儿保留', fresh_orphan.exists())
        check('混龄对整对保留（dxf 超龄 / pieces 新）',
              mix_dxf.exists() and mix_pieces.exists())
        check('超龄 strategy_cfg 清理 / 新 cfg 保留',
              not old_cfg.exists() and new_cfg.exists())
        check('非 web 命名文件不动', stray.exists())
        check('default 旧名 marker 与 sid 分文件 marker 都进保护集',
              _marker_doc_ids(cfg_runs) == {'markdoc0004', 'newdoc0002'})
        check('返回清单只含实删条目',
              sorted(removed) == ['olddoc0001.dxf', 'olddoc0001_pieces',
                                  'orphdoc0005.dxf', 'orphdoc0006_pieces',
                                  'strategy_cfg_20260101-000000.json'])

        # dry-run：只列清单不动文件。
        orphan2 = mk_dxf('orphdoc0009', 20.0)
        planned = scan_uploads(uploads_dir=uploads, config_runs_dir=cfg_runs,
                               ttl_days=14.0, now=now, registry=reg, dry_run=True)
        check('dry-run 只列不删', orphan2.exists() and planned == ['orphdoc0009.dxf'])

    # 真实 out/ dry-run（只读，不动真实文件）。
    real_plan = trigger_cleanup(dry_run=True)
    if real_plan:
        print(f'[diskclean] dry-run：真实 uploads 将删除 {len(real_plan)} 项：')
        for name in real_plan:
            print(f'  - {name}')
    else:
        print('[diskclean] dry-run：真实 uploads 无需清理（或目录不存在）')

    n_pass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f'[diskclean] {"PASS" if ok else "FAIL"}  {name}')
    print(f'[diskclean] 冒烟 {n_pass}/{len(results)} PASS')
    return 0 if n_pass == len(results) else 1


if __name__ == '__main__':
    sys.exit(_smoke())

"""四表读写数据层（keys / key_daily_usage / key_op_log / bound_systems）。

只做表访问与行级原子操作，**不含业务规则**（绑定/合并/扣次规则在 US-003
service.py；管理端续期规则在 US-002 routes_admin）。业务层一律经本模块读写，
不得手写裸 SQL 散落路由。

写操作自带 commit（请求级短连接，一操作一事务）；扣次走单条原子 UPDATE
（``atomic_deduct_once``，US-003）—— SQL 自身即原子，rowcount 即判据，并发零超扣。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from . import keygen
from .models import format_ts, now as now_fn, ymd_of

# keys 表可经 update_key 修改的列白名单（key_plaintext/key_type/created_at 不可改）
UPDATABLE_COLUMNS = (
    'total_uses', 'used_uses', 'duration_days', 'activated_at', 'expires_at',
    'bound_machine_guid', 'bound_system_name', 'remark', 'merged_into_id',
)

_CREATE_RETRY_MAX = 20   # UNIQUE 冲突重试上限（32^15 键空间，实际永不触顶）


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------

def create_key(
    conn: sqlite3.Connection,
    key_type: str,
    *,
    total_uses: int | None = None,
    duration_days: int | None = None,
    remark: str | None = None,
    now_dt: datetime | None = None,
) -> dict[str, Any]:
    """插入一条新 key（明文此刻生成，UNIQUE 冲突自动重试，FR-2）。

    返回插入后的完整行（dict）。调用方负责 key_type 与数值合法性校验（管理端
    400 中文错误属路由层职责）。
    """
    dt = now_dt or now_fn()
    ts = format_ts(dt)
    last_error: Exception | None = None
    for _ in range(_CREATE_RETRY_MAX):
        plaintext = keygen.new_key_plaintext()
        try:
            cur = conn.execute(
                'INSERT INTO keys (key_plaintext, key_type, total_uses, used_uses,'
                '                  duration_days, remark, created_at, updated_at)'
                ' VALUES (?, ?, ?, 0, ?, ?, ?, ?)',
                (plaintext, key_type, total_uses, duration_days, remark, ts, ts),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:   # UNIQUE 撞键（理论概率 ~2^-75）
            last_error = exc
            continue
        return get_key(conn, cur.lastrowid)
    raise RuntimeError(f'key 明文生成冲突重试 {_CREATE_RETRY_MAX} 次仍失败') from last_error


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def get_key(conn: sqlite3.Connection, key_id: int) -> dict[str, Any] | None:
    """按 id 取 key 行（dict；不存在 → None）。"""
    cur = conn.execute('SELECT * FROM keys WHERE id = ?', (key_id,))
    return _row_to_dict(cur.fetchone())


def get_key_by_plaintext(conn: sqlite3.Connection, key_plaintext: str) -> dict[str, Any] | None:
    """按明文取 key 行（消费端 bind/info/validate 入口查询）。"""
    cur = conn.execute('SELECT * FROM keys WHERE key_plaintext = ?', (key_plaintext,))
    return _row_to_dict(cur.fetchone())


def list_keys(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """全量 key 行（新→旧；管理台表格序）。"""
    cur = conn.execute('SELECT * FROM keys ORDER BY id DESC')
    return [dict(r) for r in cur.fetchall()]


def list_keys_by_machine(
    conn: sqlite3.Connection, machine_guid: str,
) -> list[dict[str, Any]]:
    """按绑定机器取 key 行（新→旧；US-011 消费端「系统可使用的key」表格数据源）。

    只按 ``bound_machine_guid`` 过滤，**不含状态判定**（六态过滤在
    ``service.list_for_machine`` 经 ``derive_status`` 单一真相源做）。
    """
    cur = conn.execute(
        'SELECT * FROM keys WHERE bound_machine_guid = ? ORDER BY id DESC',
        (machine_guid,))
    return [dict(r) for r in cur.fetchall()]


def update_key(
    conn: sqlite3.Connection, key_id: int, now_dt: datetime | None = None, **fields: Any
) -> dict[str, Any] | None:
    """按白名单列更新 key 行（自动刷 updated_at）；未知列名 → ValueError。

    返回更新后的完整行；key 不存在 → None（不写库不动账）。
    """
    unknown = set(fields) - set(UPDATABLE_COLUMNS)
    if unknown:
        raise ValueError(f'不可修改的列: {sorted(unknown)}')
    if not fields:
        return get_key(conn, key_id)
    sets = ', '.join(f'{col} = ?' for col in fields)
    params = [*fields.values(), format_ts(now_dt or now_fn()), key_id]
    cur = conn.execute(
        f'UPDATE keys SET {sets}, updated_at = ? WHERE id = ?', params)
    if cur.rowcount == 0:
        conn.commit()
        return None
    conn.commit()
    return get_key(conn, key_id)


def delete_key(conn: sqlite3.Connection, key_id: int) -> bool:
    """物理删除 key 行（含其使用记账与操作日志，管理台删除用）。

    注意与「合并标记保留」（FR-4）区分：合并**不**走本函数。返回是否实际删除。
    """
    conn.execute('DELETE FROM key_daily_usage WHERE key_id = ?', (key_id,))
    conn.execute('DELETE FROM key_op_log WHERE key_id = ?', (key_id,))
    cur = conn.execute('DELETE FROM keys WHERE id = ?', (key_id,))
    conn.commit()
    return cur.rowcount > 0


def atomic_deduct_once(conn: sqlite3.Connection, key_id: int) -> bool:
    """并发零超扣的原子扣次（US-003，FR-12）：count 型 used_uses+1 当且仅当仍有余额。

    单条 UPDATE 自带条件（used_uses < total_uses），SQLite 写串行化下 20 线程并发
    也恰有 total_uses 个线程 rowcount=1；返回 False = 败者（余额被抢扣完 / 非
    count 型），由调用方按「次数已用完」语义拒绝。
    """
    cur = conn.execute(
        "UPDATE keys SET used_uses = used_uses + 1, updated_at = ?"
        " WHERE id = ? AND key_type = 'count' AND used_uses < total_uses",
        (format_ts(now_fn()), key_id),
    )
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# key_daily_usage
# ---------------------------------------------------------------------------

def bump_daily_usage(
    conn: sqlite3.Connection, key_id: int, ymd: str | None = None, *, delta: int = 1
) -> int:
    """当日使用记账 +delta（原子 upsert），返回当日累计次数。

    ``ymd`` 缺省取服务器时钟自然日（消费端时钟不可信，FR-5）。
    """
    day = ymd or ymd_of(now_fn())
    conn.execute(
        'INSERT INTO key_daily_usage (key_id, ymd, count) VALUES (?, ?, ?)'
        ' ON CONFLICT(key_id, ymd) DO UPDATE SET count = count + excluded.count',
        (key_id, day, delta),
    )
    conn.commit()
    cur = conn.execute(
        'SELECT count FROM key_daily_usage WHERE key_id = ? AND ymd = ?', (key_id, day))
    return int(cur.fetchone()['count'])


def list_daily_usage(conn: sqlite3.Connection, key_id: int) -> list[dict[str, Any]]:
    """某 key 的逐日使用记录（ymd 升序；管理台统计 / 验收断言用）。"""
    cur = conn.execute(
        'SELECT ymd, count FROM key_daily_usage WHERE key_id = ? ORDER BY ymd', (key_id,))
    return [dict(r) for r in cur.fetchall()]


def _stats_from_daily(rows: list[dict[str, Any]], today_ymd: str | None) -> dict[str, Any] | None:
    """逐日使用记录 → 统计三指标（FR-14 公式单一真相源，单 key / 系统聚合共用）。

    平均每日 = 总次数 ÷ 开通以来自然日数（自首次使用起至今天数，含首日；
    新 key 当天分母 = 1；保留 1 位小数）。无任何使用记录 → None（管理台显示 —）。
    """
    if not rows:
        return None
    total = sum(int(r['count']) for r in rows)
    first_used = rows[0]['ymd']
    today = today_ymd or ymd_of(now_fn())
    days = (datetime.strptime(today, '%Y-%m-%d')
            - datetime.strptime(first_used, '%Y-%m-%d')).days + 1
    avg_daily = round(total / max(days, 1), 1)
    return {
        'total': total,
        'max_daily': max(int(r['count']) for r in rows),
        'avg_daily': avg_daily,
        'first_used': first_used,
    }


def usage_stats(
    conn: sqlite3.Connection, key_id: int, today_ymd: str | None = None
) -> dict[str, Any] | None:
    """单 key 使用统计三指标（FR-14）：{total, max_daily, avg_daily, first_used}。"""
    return _stats_from_daily(list_daily_usage(conn, key_id), today_ymd)


# ---------------------------------------------------------------------------
# key_op_log
# ---------------------------------------------------------------------------

def log_op(
    conn: sqlite3.Connection,
    key_id: int | None,
    op: str,
    detail: Any = None,
    now_dt: datetime | None = None,
) -> None:
    """操作审计（FR-16）：op ∈ create/bind/merge_source/merge_target/
    validate_deduct/renew/edit/delete；detail 任意可 JSON 化对象。"""
    conn.execute(
        'INSERT INTO key_op_log (key_id, op, detail, ts) VALUES (?, ?, ?, ?)',
        (key_id, op,
         json.dumps(detail, ensure_ascii=False) if detail is not None else None,
         format_ts(now_dt or now_fn())),
    )
    conn.commit()


def list_ops(conn: sqlite3.Connection, key_id: int | None = None) -> list[dict[str, Any]]:
    """操作日志（key_id 缺省全量；新→旧）。detail 原样返回 JSON 文本。"""
    if key_id is None:
        cur = conn.execute('SELECT * FROM key_op_log ORDER BY id DESC')
    else:
        cur = conn.execute(
            'SELECT * FROM key_op_log WHERE key_id = ? ORDER BY id DESC', (key_id,))
    return [dict(r) for r in cur.fetchall()]


def last_used_at(conn: sqlite3.Connection, key_id: int) -> str | None:
    """key 最近一次使用时刻（管理台「最新使用时间」列）。

    口径 = 该 key 最近一条 ``validate_deduct`` 日志的 ts（count/duration 型
    真实使用即扣次/记账时都写该 op，service.validate 是唯一写入口）；ts 为
    TS_FORMAT 文本，字典序即时序，MAX 即最近。从未使用 → None（管理台显 —）。
    """
    cur = conn.execute(
        "SELECT MAX(ts) FROM key_op_log WHERE key_id = ? AND op = 'validate_deduct'",
        (key_id,))
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# bound_systems（绑定系统名列表：行由 keys 派生，本表只挂靠系统级备注）
# ---------------------------------------------------------------------------

def system_has_keys(conn: sqlite3.Connection, system_name: str) -> bool:
    """系统名是否仍有在册 key（行存在性判据 / PUT 备注 404 兜底共用）。"""
    cur = conn.execute(
        'SELECT 1 FROM keys WHERE bound_system_name = ? LIMIT 1', (system_name,))
    return cur.fetchone() is not None


def list_bound_systems(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """派生系统行（该系统最新 key id 倒序）+ LEFT JOIN 系统级备注。

    行完全由 keys 按 ``bound_system_name`` 分组派生（已合并/已过期/已用完但
    未删除的 key 均算成员；未绑定 key 无系统名不参与）；bound_systems 只贡献
    remark（缺行 = 未填备注）。不同机器同名系统合并为一行（按名分组）。
    """
    cur = conn.execute(
        'SELECT k.bound_system_name AS system_name, COUNT(*) AS key_count,'
        '       MAX(k.id) AS latest_key_id, s.remark AS remark'
        ' FROM keys k LEFT JOIN bound_systems s ON s.system_name = k.bound_system_name'
        ' WHERE k.bound_system_name IS NOT NULL'
        ' GROUP BY k.bound_system_name ORDER BY latest_key_id DESC')
    return [dict(r) for r in cur.fetchall()]


def list_system_daily_usage(
    conn: sqlite3.Connection, system_name: str,
) -> list[dict[str, Any]]:
    """系统名下全部 key 的逐日使用**合并日序列**（ymd 升序，同日相加）。"""
    cur = conn.execute(
        'SELECT u.ymd AS ymd, SUM(u.count) AS count'
        ' FROM key_daily_usage u JOIN keys k ON k.id = u.key_id'
        ' WHERE k.bound_system_name = ?'
        ' GROUP BY u.ymd ORDER BY u.ymd',
        (system_name,))
    return [dict(r) for r in cur.fetchall()]


def system_usage_stats(
    conn: sqlite3.Connection, system_name: str, today_ymd: str | None = None
) -> dict[str, Any] | None:
    """系统级使用统计三指标：合并日序列 → FR-14 公式（与单 key 同一真相源）。"""
    return _stats_from_daily(list_system_daily_usage(conn, system_name), today_ymd)


def upsert_system_remark(
    conn: sqlite3.Connection, system_name: str, remark: str,
    now_dt: datetime | None = None,
) -> None:
    """写入/更新系统级备注（空串 = 清除 → 存 NULL）。"""
    conn.execute(
        'INSERT INTO bound_systems (system_name, remark, updated_at) VALUES (?, ?, ?)'
        ' ON CONFLICT(system_name) DO UPDATE SET'
        '   remark = excluded.remark, updated_at = excluded.updated_at',
        (system_name, remark if remark else None, format_ts(now_dt or now_fn())),
    )
    conn.commit()


def delete_system_if_orphaned(conn: sqlite3.Connection, system_name: str | None) -> bool:
    """该系统名下已无任何 key → 连带清理 bound_systems 行（含备注，级联口径）。

    返回是否实际删除（无挂靠行 / 系统仍有 key → False）。幂等可重入。
    """
    if system_name is None or system_has_keys(conn, system_name):
        return False
    cur = conn.execute('DELETE FROM bound_systems WHERE system_name = ?', (system_name,))
    conn.commit()
    return cur.rowcount > 0

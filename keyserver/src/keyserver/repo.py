"""三表读写数据层（keys / key_daily_usage / key_op_log）。

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


def usage_stats(
    conn: sqlite3.Connection, key_id: int, today_ymd: str | None = None
) -> dict[str, Any] | None:
    """使用统计三指标（FR-14）：{total, max_daily, avg_daily, first_used}。

    平均每日 = 总次数 ÷ 开通以来自然日数（自首次使用起至今天数，含首日；
    新 key 当天分母 = 1；保留 1 位小数）。无任何使用记录 → None（管理台显示 —）。
    """
    rows = list_daily_usage(conn, key_id)
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

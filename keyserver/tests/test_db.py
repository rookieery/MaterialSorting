"""db.py 单测（US-001 AC1/AC5）：schema 四表 + WAL + busy_timeout + MS_KEY_DB 重定位。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import keyserver.db as db


def _tables(conn):
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r['name'] for r in cur.fetchall()]


def test_ensure_schema_creates_four_tables(db_env):
    assert not db_env.exists()
    conn = db.ensure_schema(db.connect())
    tables = _tables(conn)
    for t in ('keys', 'key_daily_usage', 'key_op_log', 'bound_systems'):
        assert t in tables
    conn.close()


def test_ensure_schema_idempotent(db_env):
    conn = db.connect()
    db.ensure_schema(conn)
    db.ensure_schema(conn)   # 重复执行零副作用
    assert len(_tables(conn)) == len(set(_tables(conn)))
    conn.close()


def test_wal_and_busy_timeout(db_env):
    conn = db.connect()
    assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert conn.execute('PRAGMA busy_timeout').fetchone()[0] == db.BUSY_TIMEOUT_MS
    conn.close()


def test_ms_key_db_relocates_database_file(db_env):
    conn = db.ensure_schema(db.connect())
    conn.execute(
        "INSERT INTO keys (key_plaintext, key_type, total_uses, created_at, updated_at)"
        " VALUES ('MS-AAAAA-BBBBB-CCCCC', 'count', 5, '2026-09-28 00:00:00',"
        " '2026-09-28 00:00:00')")
    conn.commit()
    conn.close()
    assert db_env.exists()                       # DB 文件落在 MS_KEY_DB 指定处
    assert db.db_path() == db_env                # 解析链命中 env
    # 重开可见（持久化而非内存库）
    again = db.connect()
    row = again.execute('SELECT key_plaintext FROM keys').fetchone()
    assert row['key_plaintext'] == 'MS-AAAAA-BBBBB-CCCCC'
    again.close()


def test_default_db_path_anchors_to_deploy_dir(monkeypatch, tmp_path):
    monkeypatch.delenv('MS_KEY_DB', raising=False)
    # 缺省 = <部署目录>/data/keys.db，部署目录 = 本包上溯两级（keyserver/ 源码根）
    expected = db.DEPLOY_DIR.joinpath(*db.DEFAULT_DB_RELPATH)
    assert db.db_path() == expected
    # 未设 env 时绝不落临时目录（锚定源码根，与 materialsorting/paths.py 同口径）
    assert tmp_path not in db.db_path().parents
    # 锚点显式钉死 = keyserver/ 源码根（US-008 修正 parents 错位后回归锁：
    # 原实现 DEPLOY_DIR 落 repo 根，缺省库会写进 materialsorting 的 data/ 撞目录）
    assert db.DEPLOY_DIR == Path(db.__file__).resolve().parents[2]
    assert db.DEPLOY_DIR.name == 'keyserver'


def test_connect_creates_parent_dirs(tmp_path):
    target = tmp_path / 'nested' / 'deep' / 'keys.db'
    conn = db.connect(target)
    conn.execute('SELECT 1')
    conn.close()
    assert target.exists()


def test_row_factory_is_dict_like(db_env):
    conn = db.ensure_schema(db.connect())
    conn.execute(
        "INSERT INTO keys (key_plaintext, key_type, total_uses, created_at, updated_at)"
        " VALUES ('MS-DDDDD-EEEEE-FFFFF', 'count', 3, '2026-09-28 00:00:00',"
        " '2026-09-28 00:00:00')")
    row = conn.execute('SELECT * FROM keys').fetchone()
    assert isinstance(row, sqlite3.Row)
    assert dict(row)['key_type'] == 'count'
    conn.close()

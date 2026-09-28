"""SQLite 连接工厂 + schema 管理。

约定（FR 决策台账：FastAPI + SQLite 同仓 keyserver/，SQLite 单机足够）：
  - 连接逐次开（请求级短连接；uvicorn 单 worker 下 WAL 足以支撑客户机规模）；
  - ``journal_mode=WAL``（读写并发）+ ``busy_timeout=5000``（写冲突 5s 内重试）；
  - ``ensure_schema`` 幂等（CREATE TABLE IF NOT EXISTS，启动即自动迁移建表）；
  - DB 路径 env ``MS_KEY_DB`` 可重定位；缺省 ``<部署目录>/data/keys.db``
    （部署目录 = 本包上溯两级 = keyserver/ 源码根；editable 安装 / 源码部署
    即锚定仓库内 keyserver/，**非 editable 装进 site-packages 的形态请显式设
    MS_KEY_DB**）。

路径锚点镜像 materialsorting/paths.py 先例（默认相对本包位置上溯，不硬编码
绝对路径；可覆盖环境变量优先）。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_RELPATH = ('data', 'keys.db')   # 相对部署目录
BUSY_TIMEOUT_MS = 5000

# 部署目录 = src/keyserver/db.py 上溯两级 → keyserver/（源码根）
# parents 索引勿错位（US-008 实勘修正：原 parents[1] 起算使 DEPLOY_DIR 落到
# repo 根 data/ —— 与 materialsorting 的 DATA_DIR 撞目录，见 test_db 锚定断言）
_PKG = Path(__file__).resolve().parents[0]        # .../src/keyserver
_SRC = _PKG.parent                                # .../src
DEPLOY_DIR = _SRC.parent                          # .../keyserver（部署目录）


def db_path() -> Path:
    """DB 文件路径（env MS_KEY_DB 优先，缺省 <部署目录>/data/keys.db）。"""
    env = os.environ.get('MS_KEY_DB')
    if env:
        return Path(env)
    return DEPLOY_DIR.joinpath(*DEFAULT_DB_RELPATH)


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    """开一个请求级连接（自动建父目录 + WAL + busy_timeout + Row 工厂）。

    不自动建表（建表是 ``ensure_schema`` 的职责，connect 保持纯连接语义，
    便于测试/工具直连任意空库）。
    """
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute(f'PRAGMA busy_timeout={BUSY_TIMEOUT_MS}')
    return conn


SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS keys (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    key_plaintext       TEXT    NOT NULL UNIQUE,
    key_type            TEXT    NOT NULL CHECK (key_type IN ('count', 'duration')),
    total_uses          INTEGER,
    used_uses           INTEGER NOT NULL DEFAULT 0,
    duration_days       INTEGER,
    activated_at        TEXT,
    expires_at          TEXT,
    bound_machine_guid  TEXT,
    bound_system_name   TEXT,
    remark              TEXT,
    merged_into_id      INTEGER REFERENCES keys(id),
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS key_daily_usage (
    key_id  INTEGER NOT NULL REFERENCES keys(id),
    ymd     TEXT    NOT NULL,                 -- 自然日 'YYYY-MM-DD'（models.YMD_FORMAT）
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, ymd)
);

CREATE TABLE IF NOT EXISTS key_op_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id  INTEGER,                          -- 可空：与 key 无关的系统级操作
    op      TEXT    NOT NULL,                 -- create/bind/merge_*/validate_deduct/renew/edit/delete（FR-16）
    detail  TEXT,                             -- JSON 文本
    ts      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_keys_bound_machine ON keys(bound_machine_guid);
CREATE INDEX IF NOT EXISTS idx_op_log_key ON key_op_log(key_id);
'''


def ensure_schema(conn: sqlite3.Connection) -> sqlite3.Connection:
    """幂等建表（三表 + 索引）。启动时与 health 探测共用，重复执行零副作用。"""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn

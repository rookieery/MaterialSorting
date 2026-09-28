"""keyserver pytest 共享 fixture。

镜像 materialSorting-server/tests/conftest.py 先例：把 ``src/`` 加 sys.path，
未 ``pip install -e .`` 也能跑；每用例把 ``MS_KEY_DB`` 指到临时目录，绝不碰
部署目录真实 keys.db。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]     # keyserver/
_SRC = _ROOT / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    """MS_KEY_DB 指到临时路径，返回该路径（调用 connect/ensure_schema 即用）。"""
    target = tmp_path / 'keys.db'
    monkeypatch.setenv('MS_KEY_DB', str(target))
    return target


@pytest.fixture
def conn(db_env):
    """已建表的请求级连接（用例内直接用；用例结束关闭）。"""
    from keyserver import db

    c = db.ensure_schema(db.connect())
    yield c
    c.close()

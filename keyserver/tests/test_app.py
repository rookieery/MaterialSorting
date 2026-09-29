"""app.py 单测（US-001 AC1）：health 端点 + 模块入口冒烟 + 依赖方向。"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / 'src'


@pytest.fixture
def client(db_env):
    pytest.importorskip('fastapi.testclient')
    from fastapi.testclient import TestClient

    from keyserver import app as app_mod

    with TestClient(app_mod.app) as c:
        yield c


def test_health_returns_ok_and_reports_db(client, db_env):
    resp = client.get('/api/key/health')
    assert resp.status_code == 200
    body = resp.json()
    assert body['ok'] is True
    assert body['service'] == 'keyserver'
    assert body['db'] == str(db_env)


def test_root_returns_200_for_health_probes(client):
    """根路由 200（frp healthCheck 探 `/` 过检，2026-09-29 公网部署修复锁）。"""
    resp = client.get('/')
    assert resp.status_code == 200
    body = resp.json()
    assert body['ok'] is True
    assert body['service'] == 'keyserver'


def test_health_creates_schema_on_first_probe(db_env):
    assert not db_env.exists()
    pytest.importorskip('fastapi.testclient')
    from fastapi.testclient import TestClient

    from keyserver import app as app_mod

    with TestClient(app_mod.app) as c:
        assert c.get('/api/key/health').status_code == 200
    assert db_env.exists()        # 幂等建表已落 MS_KEY_DB 指定文件


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _server_env(port: int, db_path: Path) -> dict:
    env = dict(os.environ)
    env.update({
        'MS_KEY_PORT': str(port),
        'MS_KEY_HOST': '127.0.0.1',
        'MS_KEY_DB': str(db_path),
        'PYTHONPATH': str(SRC_DIR) + os.pathsep + env.get('PYTHONPATH', ''),
        'PYTHONIOENCODING': 'utf-8',
    })
    return env


def _poll_health(port: int, proc: subprocess.Popen, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        if proc.poll() is not None:   # 进程早退 = 启动失败
            out = proc.stdout.read().decode('utf-8', 'replace')
            pytest.fail(f'keyserver 进程早退: {out}')
        try:
            with urllib.request.urlopen(
                    f'http://127.0.0.1:{port}/api/key/health', timeout=2) as r:
                assert r.status == 200
                return json.loads(r.read().decode('utf-8'))
        except Exception as exc:   # noqa: BLE001 - 轮询至就绪
            last_error = exc
            time.sleep(0.3)
    pytest.fail(f'health 探测超时: {last_error}')
    raise AssertionError('unreachable')


def test_python_m_entrypoint_serves_health(tmp_path):
    """``python -m keyserver.app`` 启动 → GET /api/key/health 200 + DB 落 MS_KEY_DB。"""
    port = _free_port()
    db_file = tmp_path / 'relocated' / 'keys.db'
    proc = subprocess.Popen(
        [sys.executable, '-m', 'keyserver.app'],
        cwd=str(SRC_DIR.parent), env=_server_env(port, db_file),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        body = _poll_health(port, proc)
        assert body['ok'] is True
        assert db_file.exists()      # AC：MS_KEY_DB 可重定位数据库文件
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_module_import_does_not_pull_materialsorting():
    """依赖方向红线（行为面）：import keyserver.app 后进程内零 materialsorting 模块。"""
    code = (
        'import sys; import keyserver.app; '
        'bad = [m for m in sys.modules if m.startswith("materialsorting")]; '
        'sys.exit(1 if bad else 0)'
    )
    env = dict(os.environ)
    env['PYTHONPATH'] = str(SRC_DIR) + os.pathsep + env.get('PYTHONPATH', '')
    result = subprocess.run(
        [sys.executable, '-c', code], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert result.returncode == 0, result.stdout.decode('utf-8', 'replace')


def test_default_port_constant():
    from keyserver import app as app_mod

    assert app_mod.DEFAULT_PORT == 8110
    assert app_mod.DEFAULT_HOST == '127.0.0.1'

"""GET /api/samples + /api/samples/file 样例端点测试（2026-09-16）。

覆盖：
1. 列表：data/ 顶层 *.dxf 全列（含大写 .DXF）按名排序 / .plt 与子目录内 .dxf
   不列 / 目录缺失 → 空列表 200；
2. 取文件：白名单内 → 200 字节一致 + application/dxf；
3. 白名单外（不存在名 / ../ 穿越 / 子目录相对路径 / 分隔符注入）→ 404；
4. 隔离：monkeypatch ``paths.DATA_DIR`` → tmp_path 合成文件（_sample_dxf_names
   请求时读 ``paths.DATA_DIR``，非模块级快照）。
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from materialsorting import paths
from materialsorting.web.server import app


@pytest.fixture
def samples_client(tmp_path, monkeypatch):
    """合成 data/ 目录（2 个 .dxf + 大写 .DXF + 干扰项）+ TestClient。"""
    (tmp_path / 'a.dxf').write_bytes(b'AAA-dxf')
    (tmp_path / 'b#中文（1）.dxf').write_bytes(b'BBB-dxf')
    (tmp_path / 'C.DXF').write_bytes(b'CCC-dxf')          # 大写后缀也列（lower 判定）
    (tmp_path / 'note.txt').write_text('x')               # 非 dxf 不列
    (tmp_path / 'ref.plt').write_text('x')                # plt 不列
    sub = tmp_path / 'configs'                            # 子目录内 dxf 不列（非递归）
    sub.mkdir()
    (sub / 'inner.dxf').write_bytes(b'inner')
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        yield client


def test_list_samples_sorted_dxf_only(samples_client):
    resp = samples_client.get('/api/samples')
    assert resp.status_code == 200
    names = [s['name'] for s in resp.json()['samples']]
    # sorted() 朴素排序：大写 C.DXF 在小写前；.txt/.plt/configs/inner.dxf 均不列
    assert names == ['C.DXF', 'a.dxf', 'b#中文（1）.dxf']
    # size_bytes 与磁盘一致
    by_name = {s['name']: s['size_bytes'] for s in resp.json()['samples']}
    assert by_name['a.dxf'] == len(b'AAA-dxf')


def test_list_samples_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path / 'no_such_dir'))
    with TestClient(app) as client:
        resp = client.get('/api/samples')
    assert resp.status_code == 200
    assert resp.json() == {'samples': []}


def test_sample_file_ok_bytes(samples_client):
    resp = samples_client.get('/api/samples/file', params={'name': 'a.dxf'})
    assert resp.status_code == 200
    assert resp.content == b'AAA-dxf'
    assert resp.headers['content-type'].startswith('application/dxf')


def test_sample_file_ok_special_chars(samples_client):
    # 中文 + # + （）保留字符走 query 参数往返无损
    resp = samples_client.get('/api/samples/file',
                              params={'name': 'b#中文（1）.dxf'})
    assert resp.status_code == 200
    assert resp.content == b'BBB-dxf'


@pytest.mark.parametrize('bad', [
    'no_such.dxf',        # 白名单外（不存在）
    '../a.dxf',           # 父目录穿越
    'configs/inner.dxf',  # 子目录相对路径（真实存在也不放行 —— 非递归口径）
    '..\\a.dxf',          # 反斜杠注入（Windows 分隔符）
    'a.dxf/../../../x.dxf',
    '',
])
def test_sample_file_rejected(samples_client, bad):
    resp = samples_client.get('/api/samples/file', params={'name': bad})
    assert resp.status_code == 404
    assert '样例文件不存在' in resp.json()['error']

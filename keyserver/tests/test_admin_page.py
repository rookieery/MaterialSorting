"""GET /admin 可视化单页（US-008）：路由挂载 + 页面骨架标记 + 公开壳姿态。

页面是**公开壳**（token 由登录框输入存 sessionStorage，数据一律走
/api/admin/* 鉴权接口），因此未配置 token 的部署也要 200 —— 配置指引由
页面在首查 403「未配置」时自行渲染（浏览器验证脚本覆盖该相位）。
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip('fastapi.testclient')
from fastapi.testclient import TestClient  # noqa: E402

from keyserver import app as app_mod  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    """裸姿态：不设 token、不设 DEV —— /admin 壳必须照样可打开。"""
    monkeypatch.delenv('MS_KEY_ADMIN_TOKEN', raising=False)
    monkeypatch.delenv('MS_KEY_DEV', raising=False)
    with TestClient(app_mod.app) as c:
        yield c


def test_admin_page_served_as_html(client):
    resp = client.get('/admin')
    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('text/html')
    assert '<!DOCTYPE html>' in resp.text


def test_admin_page_public_shell_without_token(client):
    """未配置 token 且无 DEV：/admin 壳仍 200（数据接口 403，页面渲染指引）。"""
    resp = client.get('/admin')
    assert resp.status_code == 200
    assert client.get('/api/admin/keys').status_code == 403   # 壳公开、数据关闸


def test_admin_page_table_columns(client):
    """key 表六列 + 绑定系统名列表五列（需求列序；备注名/使用统计已迁移为系统级）。"""
    html = client.get('/admin').text
    cols = re.findall(r'<th>([^<]*)</th>', html)
    assert cols == [
        '名称', '绑定系统名', '类型', '详细信息', '属性', '操作',          # key 列表
        '绑定系统名', '备注名', 'key 数', '使用统计', '操作',             # 绑定系统名列表
    ]


def test_admin_page_api_surface_markers(client):
    """页面骨架锚点：token 存储/请求头、接口路径、未配置指引文案。"""
    html = client.get('/admin').text
    assert 'ms_admin_token' in html            # sessionStorage 键
    assert 'X-Admin-Token' in html             # 请求头
    assert '/api/admin/keys' in html           # 列表/新建/续期/删除同前缀
    assert '/api/admin/systems' in html        # 绑定系统名列表两接口
    assert '?force=true' in html               # 正在使用 → 二段确认 force
    assert 'MS_KEY_ADMIN_TOKEN' in html        # 未配置部署的配置指引
    assert 'MS_KEY_CLIENT_TOKEN' in html       # frp 双 token 指引
    for state in ('正在使用', '已过期', '已用完', '未绑定', '未激活', '已合并'):
        assert state in html                   # 六态徽标配色映射

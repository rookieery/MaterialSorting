"""下载文件名清洗（2026-09-12 导出文件名弹窗）。

``POST /export`` 与 ``POST /api/state-save`` 共享的 ``save_as``（前端弹窗确认的
**名称主体，无扩展名** —— 2026-09-12 用户定案：格式已知、后缀不经手用户，弹窗
预填/输入均不带后缀；预填默认值是前端镜像后端合成式去后缀，lib/download.ts
defaultExportFilename / defaultStateFilename）清洗器：用户可任意编辑 —— 服务端
必须防路径分隔符 / Windows 非法字符 / CD 头注入（控制字符、引号）并保证扩展名
正确（本函数按 ext 统一补全，用户永不需要关心后缀）。

仅标准库；routes_views 与 statefile 双向共用（statefile → routes_views 单向
依赖，共享函数放本中立模块避免环）。
"""
from __future__ import annotations

import re

__all__ = ['sanitize_download_name']

# 路径分隔符 + Windows 非法字符 + 控制字符（含 CR/LF，防 Content-Disposition 头注入）。
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WS_RE = re.compile(r'\s+')

# 名字主体长度上限（不含扩展名；超长截断保 CD 头与文件系统双安全）。
_MAX_NAME_LEN = 120


def sanitize_download_name(raw: str, ext: str) -> str:
    """清洗用户确认的下载文件名；非法者返回 ``''``（调用方回退默认合成名）。

    - 非法字符（``\\/:*?"<>|`` 与控制字符）逐字符替换为 ``_``（不静默删除，
      用户可见的位置感保留）；
    - 空白折叠为单空格、去首尾空白与尾部点/空格（Windows 不允许尾部点/空格）；
    - 主体超 ``_MAX_NAME_LEN`` 截断（按码点，切完再去尾部点/空格）；
    - 清洗后为空 → ``''``；
    - 不以 ``.{ext}`` 结尾（大小写不敏感）→ 自动补 ``.{ext}`` —— 扩展名是
      格式事实（fmt 决定渲染器），不交由用户输入决定。
    """
    name = _ILLEGAL_RE.sub('_', (raw or '').strip())
    name = _WS_RE.sub(' ', name).strip().rstrip('. ')
    if len(name) > _MAX_NAME_LEN:
        name = name[:_MAX_NAME_LEN].rstrip('. ')
    if not name:
        return ''
    if not name.lower().endswith(f'.{ext.lower()}'):
        name = f'{name}.{ext}'
    return name

"""download_name.sanitize_download_name 单元测试（2026-09-12 导出文件名弹窗）。

/export 与 /api/state-save 的 save_as 整名覆盖共用清洗器：非法字符替换、空白
折叠、尾部点/空格剥离、长度截断、空回退、扩展名自动补（大小写不敏感时保留
用户原写）。
"""
from __future__ import annotations

from materialsorting.web.download_name import sanitize_download_name


def test_plain_name_appends_extension():
    """普通名（无扩展名）→ 自动补 .{ext}。"""
    assert sanitize_download_name('my-plan', 'png') == 'my-plan.png'
    assert sanitize_download_name('快照', 'msn') == '快照.msn'


def test_correct_extension_kept_as_is():
    """已带正确扩展名（含大小写不一）→ 原样保留，不重复追加。"""
    assert sanitize_download_name('方案A.plt', 'plt') == '方案A.plt'
    assert sanitize_download_name('photo.PNG', 'png') == 'photo.PNG'


def test_wrong_extension_appends_correct_one():
    """带错扩展名 → 追加正确扩展名（扩展名是格式事实，不交用户输入决定）。"""
    assert sanitize_download_name('x.txt', 'png') == 'x.txt.png'


def test_illegal_chars_replaced_with_underscore():
    """路径分隔符 / Windows 非法字符 / 控制字符 → 逐字符 '_'（位置感保留）。"""
    assert sanitize_download_name('a/b\\c:d*e?f"g<h>i|j', 'png') == 'a_b_c_d_e_f_g_h_i_j.png'
    assert sanitize_download_name('CR\r\nLF', 'plt') == 'CR__LF.plt'


def test_whitespace_collapsed_and_stripped():
    """空白折叠单空格 + 首尾剥离；Windows 尾部点/空格非法 → 剥离后再补扩展名。"""
    assert sanitize_download_name('  我的   方案  ', 'png') == '我的 方案.png'
    assert sanitize_download_name('trailing dots... ', 'png') == 'trailing dots.png'


def test_empty_after_sanitize_returns_empty():
    """清洗后为空（空串/纯空白/None）→ ''（调用方回退默认合成名）；纯非法字符
    替换后非空 → '_' 序列照常补扩展名（不静默清空用户的显式输入）。"""
    assert sanitize_download_name('', 'png') == ''
    assert sanitize_download_name('   ', 'png') == ''
    assert sanitize_download_name(None, 'png') == ''          # None 容错（防御）
    assert sanitize_download_name('???', 'png') == '___.png'


def test_length_cap_preserves_extension():
    """主体超 120 截断（按码点），截断后再补扩展名。"""
    long_stem = 'x' * 200
    out = sanitize_download_name(long_stem, 'png')
    assert out == 'x' * 120 + '.png'


def test_all_ascii_name_only_replacement_no_change():
    """合法 ASCII 名清洗前后不变（除补扩展名）——最常见路径零惊扰。"""
    assert sanitize_download_name('M1787_28-30_88.42pct.png', 'png') \
        == 'M1787_28-30_88.42pct.png'

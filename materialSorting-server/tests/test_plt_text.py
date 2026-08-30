"""PLT 矢量文本引擎单测（plt_text，2026-08-30 唛架信息表格的文字来源）。

覆盖：
  - 捆绑字体加载（upm=1000）+ 缺失文件 fail-fast（PLTFontError 带获取文案）
  - glyph 展平：ASCII / 数字 / CJK 轮廓非退化；空格无轮廓有 advance
  - 豆腐框：cmap 未命中 → missing=True + 单矩形轮廓 + warning（可见占位不静默）
  - text_width：线性随字高、空串 0、CJK 宽于单字累加
  - (u,w) 手性：左手系 raise（export_plt 2026-08-24 镜像 bug 同款防御）
  - text_strokes：基变换几何（字顶朝 w、阅读沿 u）、shrink-to-fit（只缩不放 +
    下限截断）、渲染产物过 _plt_polyline 行口径（≤10 点/≤110B）

字体未就位（如过渡期 checkout 缺文件）→ skipif 整组跳过（不入 CI 红灯）。
"""
from __future__ import annotations

import math
import os

import pytest

from materialsorting import paths
from materialsorting.web import plt_text
from materialsorting.web.plt_text import (
    PLTFontError, glyph, load_font, text_strokes, text_width)

_HAS_FONT = os.path.exists(paths.PLT_FONT_PATH)

pytestmark = pytest.mark.skipif(not _HAS_FONT, reason='捆绑字体未就位（resources/fonts）')


# --------------------------------------------- 字体加载

def test_load_bundled_font_upm_1000():
    """捆绑 Noto Sans SC 可加载，upm=1000（SubsetOTF 口径，shrink 换算基准）。"""
    font = load_font()
    assert font['head'].unitsPerEm == 1000


def test_missing_font_raises_with_hint(tmp_path, monkeypatch):
    """字体缺失 → PLTFontError 带获取步骤文案（fail-fast 不静默降级成无表格）。"""
    monkeypatch.setattr(paths, 'PLT_FONT_PATH', str(tmp_path / 'nope.otf'))
    plt_text.load_font.cache_clear()
    try:
        with pytest.raises(PLTFontError, match='NotoSansSC'):
            load_font()
    finally:
        plt_text.load_font.cache_clear()


# --------------------------------------------- glyph 展平

@pytest.mark.parametrize('ch', ['A', '0', '床', '％'])
def test_glyph_contours_non_degenerate(ch):
    """常用字符各产出 ≥1 条 ≥3 点轮廓，坐标全有限浮点。"""
    g = glyph(ch)
    assert not g.missing
    assert len(g.contours) >= 1
    assert all(len(c) >= 3 for c in g.contours)
    assert all(math.isfinite(v) for c in g.contours for p in c for v in p)


def test_glyph_digit_closed_and_bounded():
    """'0'：≥2 轮廓（外圈 + 内圈）、点全部落在 em 框内（0..1em 量级）。
    （隐含 on-curve 顺序坑在 BasePen 路径内建处理，此为端到端锁：
    轮廓若错乱会出现越界/退化点列。）"""
    g = glyph('0')
    assert len(g.contours) >= 2
    for c in g.contours:
        xs = [p[0] for p in c]
        ys = [p[1] for p in c]
        assert -50 <= min(xs) and max(xs) <= 1050     # em 框 ±5% 容差
        assert -50 <= min(ys) and max(ys) <= 1050
        assert max(xs) - min(xs) > 50                  # 非退化（有实际墨迹）


def test_glyph_space_no_contours_but_advance():
    """空格：无轮廓（纯词间距）、advance > 0（撑开词距）。"""
    g = glyph(' ')
    assert g.contours == ()
    assert g.advance > 0


def test_glyph_missing_char_tofu_box_and_warning(caplog):
    """cmap 未命中（PUA）→ 豆腐框单矩形 + missing=True + warning。"""
    with caplog.at_level('WARNING'):
        g = glyph('')
    assert g.missing
    assert len(g.contours) == 1
    c = g.contours[0]
    assert len(c) == 4                                   # 空心矩形 4 角
    xs = [p[0] for p in c]
    ys = [p[1] for p in c]
    assert 50 < xs[1] - xs[0] < 950                      # 0.1em..0.9em
    assert 300 < max(ys) < 900                           # 顶 0.8em
    assert any('U+E00A' in r.message for r in caplog.records)


# --------------------------------------------- text_width

def test_text_width_linear_and_monotonic():
    """宽度 = advance 累加 ×字高/upm：线性随字高、空串 0、'床床' = 2×'床'。"""
    w1 = text_width('床', 18.0)
    assert text_width('', 18.0) == 0.0
    assert text_width('床床', 18.0) == pytest.approx(2 * w1)
    assert text_width('床', 9.0) == pytest.approx(w1 / 2)


# --------------------------------------------- 手性防御

def test_left_handed_basis_raises():
    """(u,w) 左手系（det<0）→ raise：静默容忍 = 渲染镜像文字（历史 bug 复发）。"""
    with pytest.raises(ValueError, match='右手系'):
        text_strokes('床', origin=(0.0, 0.0), u=(0, 1), w=(1, 0), char_h_mm=18.0)


def test_degenerate_basis_raises():
    with pytest.raises(ValueError):
        text_strokes('床', origin=(0.0, 0.0), u=(0, 0), w=(-1, 0), char_h_mm=18.0)


# --------------------------------------------- text_strokes 几何

def test_text_strokes_geometry_up_right_handed():
    """u=(0,1)/w=(-1,0)（表格口径）：阅读沿 +y、字顶朝 −x、墨迹 x≤origin.x。"""
    ox, oy = 100.0, 10.0
    strokes = text_strokes('床155', origin=(ox, oy), u=(0, 1), w=(-1, 0),
                           char_h_mm=18.0)
    assert strokes, '应有笔画'
    xs = [p[0] for st in strokes for p in st]
    ys = [p[1] for st in strokes for p in st]
    # 基线在 origin、字顶（墨迹）向 −x；CJK 表意字设计上略低于拉丁基线
    # （'床' y∈[-80,845]/1000），容差放到 +2mm
    assert max(xs) <= ox + 2.0
    assert min(xs) >= ox - 18.0 - 0.01     # 墨迹不超一个 em
    assert min(ys) >= oy - 0.01            # 阅读沿 +y，文字整体在 origin 之后
    assert max(ys) - min(ys) > 30.0        # '床'+3 数字有实际长度


def test_text_strokes_empty_text():
    assert text_strokes('', origin=(0, 0), u=(0, 1), w=(-1, 0), char_h_mm=18) == []


def test_shrink_to_fit_only_shrinks():
    """10 个 CJK @18mm=180mm 宽、fit=126 → 有效字高 ≈ 12.6mm（只缩不放；
    到下限才截断）。以墨迹厚度断言（CJK 墨迹 ~92% em，容差放宽到 ±1.5mm）。"""
    strokes = text_strokes('床' * 10, origin=(0, 0), u=(0, 1), w=(-1, 0),
                           char_h_mm=18.0, fit_width_mm=126.0)
    xs = [p[0] for st in strokes for p in st]
    thickness = max(xs) - min(xs)
    assert 11.0 <= thickness <= 13.0
    # 宽度确实压进 fit（沿 y 量总长 ≤ 126 + 单字余量）
    ys = [p[1] for st in strokes for p in st]
    assert max(ys) - min(ys) <= 126.0 + 1.0


def test_shrink_truncates_at_min_char_height():
    """30 字 @18mm=540mm、fit=126 → 压到下限 9mm 仍超 → 尾部截断（可见截断）。"""
    strokes = text_strokes('床' * 30, origin=(0, 0), u=(0, 1), w=(-1, 0),
                           char_h_mm=18.0, fit_width_mm=126.0)
    ys = [p[1] for st in strokes for p in st]
    assert max(ys) - min(ys) <= 126.0 + 1.0     # 截断后整体仍在 fit 内
    # 30 字若未截断总长 540mm —— 断言显著短于全量（确实截了）
    assert max(ys) - min(ys) < 200.0


# --------------------------------------------- PLT 行口径兼容

def test_strokes_feed_plt_polyline_within_limits():
    """渲染笔画过 export_plt._plt_polyline 后：PD 行 ≤10 点/≤110B（设备口径）。"""
    from materialsorting.web.export_plt import _PLT_PD_MAX_PTS, _plt_polyline
    strokes = text_strokes('面料利用率 84.86%', origin=(0, 0), u=(0, 1), w=(-1, 0),
                           char_h_mm=18.0)
    lines = []
    for st in strokes:
        lines.extend(_plt_polyline(closed=True, points=st))
    pd_lines = [ln for ln in lines if ln.startswith('PD')]
    assert pd_lines
    for ln in pd_lines:
        assert len(ln) <= 110
        assert ln.count(',') + 1 <= 2 * _PLT_PD_MAX_PTS + 2   # ≤10 点（闭合+1）

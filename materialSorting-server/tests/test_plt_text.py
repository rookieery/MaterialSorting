"""PLT 矢量文本引擎单测（plt_text，2026-08-30 v5 单线矢量字默认路径）。

覆盖：
  - 捆绑 Noto 轮廓字体加载（upm=1000）+ 缺失文件 fail-fast（PLTFontError）
  - glyph 展平（Noto 轮廓原语，仍是回退路径）：ASCII / 数字 / CJK 轮廓非退化；
    空格无轮廓有 advance；豆腐框 cmap 未命中 → missing=True + warning
  - 单线字库（v5 默认）：hanzi_medians ≥9000 字 + hershey_rowmans ≥90 字符；
    14 字段标签用字全覆盖；单线笔画**开放**（closed=False）
  - normalize_text：NFKC 全角→半角 + 残留符号映射（—·。、→ASCII）
  - text_width：线性随字高、空串 0、CJK 全宽 advance=1em、全角归一后与半角同宽
  - (u,w) 手性：左手系 raise（export_plt 2026-08-24 镜像 bug 同款防御）
  - text_strokes：基变换几何（字顶朝 w、阅读沿 u）、汉字归一化排印盒
    [0.06,0.94]em、Hershey H 三笔开放、未覆盖字符 Noto 轮廓回退 closed=True
    + warning、shrink-to-fit（只缩不放 + 下限截断）、渲染产物过 _plt_polyline
    行口径（≤10 点/≤110B）

字体未就位（如过渡期 checkout 缺文件）→ skipif 整组跳过（不入 CI 红灯）。
"""
from __future__ import annotations

import math
import os

import pytest

from materialsorting import paths
from materialsorting.web import plt_text
from materialsorting.web.plt_text import (
    PLTFontError, glyph, load_font, load_stroke_font, normalize_text,
    text_strokes, text_width)

_HAS_FONT = os.path.exists(paths.PLT_FONT_PATH)
_HAS_STROKE = (os.path.exists(os.path.join(paths.FONT_DIR, 'hanzi_medians.txt'))
               and os.path.exists(os.path.join(paths.FONT_DIR,
                                               'hershey_rowmans.txt')))

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


# --------------------------------------------- glyph 展平（Noto 轮廓原语）

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
    """cmap 未命中（PUA U+E00A）→ 豆腐框单矩形 + missing=True + warning。"""
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


# --------------------------------------------- 单线字库（v5 默认渲染路径）

@pytest.mark.skipif(not _HAS_STROKE, reason='单线字资源未就位（hanzi_medians/hershey）')
def test_load_stroke_font_tables():
    """两库加载：汉字 ≥9000（hanzi-writer-data 全量）、ASCII ≥90（rowmans 92 字符）。"""
    hanzi, ascii_ = load_stroke_font()
    assert len(hanzi) >= 9000
    assert len(ascii_) >= 90


@pytest.mark.skipif(not _HAS_STROKE, reason='单线字资源未就位（hanzi_medians/hershey）')
def test_table_label_chars_all_in_stroke_lib():
    """14 字段标签 + 典型 value 用字在单线两库全覆盖（不触发 Noto 轮廓混排）。"""
    hanzi, ascii_ = load_stroke_font()
    text = ('方案名称床次经纱缩水纬利用率幅宽料长本包含套数每用片排师绘图时间样板号'
            '备注料套' + '()=*+.%/m-:0123456789A ')
    missing = [ch for ch in text if ch not in hanzi and ch not in ascii_]
    assert not missing, f'单线字库缺字：{missing!r}'


@pytest.mark.skipif(not _HAS_STROKE, reason='单线字资源未就位（hanzi_medians/hershey）')
def test_stroke_paths_open_not_closed():
    """单线笔画开放（closed=False，一笔中线非闭合轮廓）；空格无笔画有 advance。"""
    strokes = text_strokes('床A0', origin=(0, 0), u=(1, 0), w=(0, 1), char_h_mm=18.0)
    assert strokes
    for closed, pts in strokes:
        assert closed is False                       # 单线 = 开放笔画
        assert len(pts) >= 2


@pytest.mark.skipif(not _HAS_STROKE, reason='单线字资源未就位（hanzi_medians/hershey）')
def test_hershey_H_three_open_strokes():
    """Hershey 解码回归锁：'H' = 左竖+右竖+横 三笔开放 2 点折线（JHF 绝对坐标
    口径若错会出乱线/子路径粘连）。"""
    strokes = text_strokes('H', origin=(0, 0), u=(1, 0), w=(0, 1), char_h_mm=18.0)
    assert [(c, len(p)) for c, p in strokes] == [(False, 2), (False, 2), (False, 2)]


@pytest.mark.skipif(not _HAS_STROKE, reason='单线字资源未就位（hanzi_medians/hershey）')
def test_hanzi_normalized_to_typographic_box():
    """汉字 medians 仿射归一到标准排印盒：u/w 单位基下 py ∈ [0.06,0.94]em 内
    （床 实测 [0.087,0.899]em，混排时汉字与 ASCII 基线关系正常）。"""
    strokes = text_strokes('床', origin=(0, 0), u=(1, 0), w=(0, 1), char_h_mm=18.0)
    ys = [p[1] for _c, pts in strokes for p in pts]
    assert 0.5 <= min(ys) <= max(ys) <= 17.5          # 0.06em=1.08 .. 0.94em=16.92


@pytest.mark.skipif(not _HAS_STROKE, reason='单线字资源未就位（hanzi_medians/hershey）')
def test_hanzi_orientation_semantic_probes():
    """汉字方向回归锁（2026-08-30 v5 用户报告汉字颠倒）：MMaH medians 文件保留
    源 y 向下坐标，引擎加载期在身体范围 [139,1120] 内镜像翻成 y 向上 —— 不翻则
    逐字上下镜像。用类型无关语义判据锁：「上」最宽笔（长横底画）必须在盒下半、
    「下」最宽笔（顶横）必须在盒上半（已与 Noto 轮廓同探针对拍同侧）。"""
    hanzi, _ascii = load_stroke_font()
    em_mid = 0.5 * plt_text._STROKE_EM
    for ch, half in (('上', 'bottom'), ('下', 'top')):
        g = hanzi[ch]
        widest = max(g.strokes, key=lambda sp: max(p[0] for p in sp) - min(p[0] for p in sp))
        y_mid = sum(p[1] for p in widest) / len(widest)
        assert max(p[0] for p in widest) - min(p[0] for p in widest) > 0.7 * plt_text._STROKE_EM  # 探针自证：确是长横
        assert (y_mid < em_mid) if half == 'bottom' else (y_mid > em_mid), \
            f'{ch!r} 长横 y 中心 {y_mid:.0f} 应在盒{"下" if half == "bottom" else "上"}半'


@pytest.mark.skipif(not _HAS_STROKE, reason='单线字资源未就位（hanzi_medians/hershey）')
def test_noto_fallback_closed_outline_and_warning(caplog):
    """两库未覆盖字符（希腊 Ω）→ Noto 轮廓回退 closed=True + warning（每字符一次）。"""
    with caplog.at_level('WARNING'):
        strokes = text_strokes('Ω', origin=(0, 0), u=(1, 0), w=(0, 1), char_h_mm=18.0)
    assert strokes
    assert all(closed is True for closed, _pts in strokes)   # 轮廓 = 闭合
    assert any('单线字库' in r.message for r in caplog.records)


# --------------------------------------------- normalize_text

def test_normalize_fullwidth_to_ascii():
    """全角字母数字/括号 NFKC → 半角（手输法切全角也能进单线字库）。"""
    assert normalize_text('ＡＢ１２（）') == 'AB12()'


def test_normalize_residual_symbol_map():
    """NFKC 不转的表意/异形符号显式映射（—·。、→ASCII，Hershey 可画）。"""
    assert normalize_text('—‐−') == '---'
    assert normalize_text('·・。、') == '...,'


def test_normalize_applies_to_width_and_strokes():
    """归一在 text_width / text_strokes 入口统一：全角与半角同宽（测量=渲染）。"""
    assert text_width('Ａ１', 18.0) == pytest.approx(text_width('A1', 18.0))


# --------------------------------------------- text_width

def test_text_width_linear_and_monotonic():
    """宽度 = advance 累加 ×字高/em：线性随字高、空串 0、CJK 全宽 1em、'床床'=2×。"""
    w1 = text_width('床', 18.0)
    assert w1 == pytest.approx(18.0)                 # 汉字 advance = 1em 全宽
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
    """u=(0,1)/w=(-1,0)（表格口径）：阅读沿 +y、字顶朝 −x、墨迹 x≤origin.x。
    单线口径下 ASCII 基线 py=0 → x 上确界 = origin.x；汉字盒 0.06..0.94em。"""
    ox, oy = 100.0, 10.0
    strokes = text_strokes('床155', origin=(ox, oy), u=(0, 1), w=(-1, 0),
                           char_h_mm=18.0)
    assert strokes, '应有笔画'
    xs = [p[0] for _c, st in strokes for p in st]
    ys = [p[1] for _c, st in strokes for p in st]
    assert max(xs) <= ox + 2.0
    assert min(xs) >= ox - 18.0 - 0.01     # 墨迹不超一个 em（汉字盒 0.94em 顶）
    assert min(ys) >= oy - 0.01            # 阅读沿 +y，文字整体在 origin 之后
    assert max(ys) - min(ys) > 30.0        # '床'+3 数字有实际长度


def test_text_strokes_empty_text():
    assert text_strokes('', origin=(0, 0), u=(0, 1), w=(-1, 0), char_h_mm=18) == []


def test_shrink_to_fit_only_shrinks():
    """10 个 CJK @18mm=180mm 宽、fit=126 → 有效字高 12.6mm（只缩不放；到下限才
    截断）。以墨迹厚度断言（床 归一盒 [0.087,0.899]em → 0.81em×12.6≈10.2mm，
    容差 ±1.3mm）。"""
    strokes = text_strokes('床' * 10, origin=(0, 0), u=(0, 1), w=(-1, 0),
                           char_h_mm=18.0, fit_width_mm=126.0)
    xs = [p[0] for _c, st in strokes for p in st]
    thickness = max(xs) - min(xs)
    assert 9.0 <= thickness <= 12.5
    # 宽度确实压进 fit（沿 y 量总长 ≤ 126 + 单字余量）
    ys = [p[1] for _c, st in strokes for p in st]
    assert max(ys) - min(ys) <= 126.0 + 1.0


def test_shrink_truncates_at_min_char_height():
    """30 字 @18mm=540mm、fit=126 → 压到下限 9mm 仍超 → 尾部截断（可见截断）。"""
    strokes = text_strokes('床' * 30, origin=(0, 0), u=(0, 1), w=(-1, 0),
                           char_h_mm=18.0, fit_width_mm=126.0)
    ys = [p[1] for _c, st in strokes for p in st]
    assert max(ys) - min(ys) <= 126.0 + 1.0     # 截断后整体仍在 fit 内
    # 30 字若未截断总长 540mm —— 断言显著短于全量（确实截了）
    assert max(ys) - min(ys) < 200.0


# --------------------------------------------- PLT 行口径兼容

def test_strokes_feed_plt_polyline_within_limits():
    """渲染笔画（单线开放 / 回退闭合各按 closed 旗标）过 export_plt._plt_polyline
    后：PD 行 ≤10 点/≤110B（设备口径）。"""
    from materialsorting.web.export_plt import _PLT_PD_MAX_PTS, _plt_polyline
    strokes = text_strokes('面料利用率 84.86%', origin=(0, 0), u=(0, 1), w=(-1, 0),
                           char_h_mm=18.0)
    lines = []
    for closed, st in strokes:
        lines.extend(_plt_polyline(closed=closed, points=st))
    pd_lines = [ln for ln in lines if ln.startswith('PD')]
    assert pd_lines
    for ln in pd_lines:
        assert len(ln) <= 110
        assert ln.count(',') + 1 <= 2 * _PLT_PD_MAX_PTS + 2   # ≤10 点（闭合+1）

"""PLT 矢量文本引擎：单线矢量字（默认）+ 捆绑 OFL 中文轮廓字回退（2026-08-30）。

唛架信息表格（plt_table.py）的中文/ASCII 文字来源。PLT 全程无 LB 文字指令
（设备兼容口径，export_plt.py 同款），文字 = PU/PD 笔画 —— 与 2026-08-24 起
「尺码*数量」标注的矢量笔画同思路，但字库不再手写 11 个字形，而是捆绑完整
字库（用户手输的排料师/备注可为任意字符）。

**单线矢量字（v5 2026-08-30，对拍生产件观感）**：生产 PLT（ET2008 等）文字为
一笔单线字（非轮廓空心）。为「字体尽可能与生产文件一致」，表格文字默认走
单线渲染：

- **汉字**：`hanzi_medians.txt`（9575 字，Make Me a Hanzi / hanzi-writer-data
  2.0.1 的笔画中线 medians，em=1024 网格、Arphic 公共许可证随包分发）。
  原始中线含笔画粗度外溢（全库 y∈[139,1120]），加载时仿射归一到 0.06..0.94em
  标准排印盒（混排时汉字与 ASCII 基线关系正常）。
- **ASCII**：`hershey_rowmans.txt`（Hershey Roman Simplex 92 字符，生产 PLT
  ASCII 同款经典刻字体，Usenet Hershey 许可随数据附致谢文件）。构建时已把
  y 平移到基线=0、em=cap/0.70（大写字高 0.7em 排印惯例）。
- 文本先 NFKC 归一（全角字母数字/标点 → 半角，CJK 兼容汉字 → 典型形），残余
  个别全角符号（—·等）显式映射；两库都未覆盖的字符（生僻符号）回退 Noto
  轮廓并 warning（每字符每进程一条，不刷屏）。

**Noto Sans SC Regular 轮廓回退**（SubsetOTF/SC，~8.3MB，OFL 1.1 随包分发）：
单线字资源缺失（安装不全）或字符未覆盖时的兜底，任何汉字 100% 可渲染、
本机/服务器行为一致。路径经 paths.PLT_FONT_PATH（环境变量 MS_FONT_DIR
可覆盖）。fontTools 为 ezdxf 既有依赖，显式声明于 pyproject。

轮廓展平：继承 fontTools BasePen（**不要** RecordingPen 手排 —— 预研踩坑：
'0' 等 TrueType 字形首点是隐含 on-curve、closePath 早于 moveTo 的顺序问题，
BasePen 内建处理隐含起点 / qCurveTo(...,None) 哨兵 / 多控制点二次段分解）。
CFF 三次（curveTo）与 TrueType 二次（qCurveTo）双路支持：De Casteljau 中点
递归细分，控制点离弦距离 ≤ 容差即停（_FLATTEN_TOL_UNITS=2 字体单位 ≈
0.036mm @18mm 字高，upm=1000）。

任意方向文字 = (u, w) 二维基变换（复用 export_plt._grain_annotation_strokes
已验证机制，2026-08-24 手性 bug 后定稿口径）：u = 书写方向单位向量、
w = 字顶方向，**(u, w) 必须右手系**（det(u,w) > 0，否则字形镜像 —— text_strokes
直接 raise 防御，勿改成静默容忍）。字形点 (px, py)（em 单位、基线 y=0、
字顶 y>0）→ world = origin + (gx + px·s)·u + (py·s)·w（gx = 已累积 advance、
s = 字高/EM）。text_strokes 返回 ``[(closed, points)]``：单线笔画开放
（closed=False），轮廓回退闭合（closed=True）。

缺字处理（宁可见勿静默）：cmap 未命中（生僻字/emoji）→ 画空心豆腐框占位
（0.1em..0.9em × 0..0.8em）+ logging.warning —— 裁剪车间里错漏信息比缺字
更危险，可见占位一眼可辨。
"""
from __future__ import annotations

import logging
import math
import os
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

from .. import paths


class PLTFontError(RuntimeError):
    """捆绑字体不可用（文件缺失/损坏）。带获取步骤文案，fail-fast 不静默降级。"""


# 展平容差（字体单位，upm=1000 → 2 单位 = 0.036mm @18mm 字高；设备笔宽 0.08mm
# 量级，再细无意义徒增字节数）
_FLATTEN_TOL_UNITS = 2.0
_FLATTEN_MAX_DEPTH = 8   # 中点递归深度上限（2^8 = 256 段，圆字号足够）

_TOFU_X0_EM = 0.1   # 豆腐框左沿（em 比例）
_TOFU_X1_EM = 0.9   # 豆腐框右沿
_TOFU_Y1_EM = 0.8   # 豆腐框顶（底为基线 0）
_TOFU_ADV_EM = 0.5  # 豆腐框 advance


@lru_cache(maxsize=4)
def load_font(path: str | None = None) -> TTFont:
    """加载矢量文字字体（缺省 paths.PLT_FONT_PATH），按 path 进程级缓存。

    文件缺失 → PLTFontError（带获取步骤；服务器漏拷字体时一眼定位，绝不静默
    降级成无表格导出）。
    """
    p = path or paths.PLT_FONT_PATH
    if not os.path.exists(p):
        raise PLTFontError(
            f'PLT 信息表格字体缺失：{p}。捆绑字体 NotoSansSC-Regular.otf（OFL）'
            '应随包分发在 resources/fonts/；也可用环境变量 MS_FONT_DIR 指向已有'
            '字体目录。若仓库缺文件，从 cdn.jsdelivr.net/gh/notofonts/noto-cjk@'
            'main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf 重新获取。')
    try:
        return TTFont(p, lazy=True)
    except Exception as e:   # 损坏/非字体文件：统一转 PLTFontError（fail-fast）
        raise PLTFontError(f'PLT 信息表格字体无法解析：{p}（{e}）') from e


@dataclass(frozen=True)
class GlyphGeom:
    """单字符几何（字体单位，upm 归一前）。"""

    contours: tuple[tuple[tuple[float, float], ...], ...]   # 展平轮廓（末点不重复首点）
    advance: float                                          # advance width（字体单位）
    missing: bool                                           # True = cmap 未命中，豆腐框占位


class _FlattenPen(BasePen):
    """字形轮廓 → 折线点列（字体单位）。曲线按控制点离弦距离容差中点递归细分。"""

    def __init__(self, glyph_set):
        super().__init__(glyph_set)
        self._cur: list[tuple[float, float]] | None = None
        self.contours: list[list[tuple[float, float]]] = []

    # ---- 轮廓生命周期 ----
    def _moveTo(self, p0):
        self._flush()
        self._cur = [(float(p0[0]), float(p0[1]))]

    def _closePath(self):
        self._flush()

    def _endPath(self):    # 开放轮廓（黑体正文字形基本不出现，防御性保留）
        self._flush()

    def _flush(self):
        if self._cur and len(self._cur) >= 2:
            self.contours.append(self._cur)
        self._cur = None

    # ---- 直线 ----
    def _lineTo(self, p1):
        self._append((float(p1[0]), float(p1[1])))

    # ---- 曲线：De Casteljau 中点递归（判据 = 控制点离弦距离 ≤ 容差）----
    def _curveToOne(self, p1, p2, p3):
        p0 = self._cur[-1]
        self._subdiv_cubic(p0, (float(p1[0]), float(p1[1])),
                           (float(p2[0]), float(p2[1])), (float(p3[0]), float(p3[1])), 0)

    def _qCurveToOne(self, p1, p2):
        p0 = self._cur[-1]
        self._subdiv_quad(p0, (float(p1[0]), float(p1[1])),
                          (float(p2[0]), float(p2[1])), 0)

    def _subdiv_quad(self, p0, p1, p2, depth):
        if depth >= _FLATTEN_MAX_DEPTH or _line_dist(p1, p0, p2) <= _FLATTEN_TOL_UNITS:
            self._append(p2)
            return
        p01 = _mid(p0, p1)
        p12 = _mid(p1, p2)
        pm = _mid(p01, p12)
        self._subdiv_quad(p0, p01, pm, depth + 1)
        self._subdiv_quad(pm, p12, p2, depth + 1)

    def _subdiv_cubic(self, p0, p1, p2, p3, depth):
        if (depth >= _FLATTEN_MAX_DEPTH
                or max(_line_dist(p1, p0, p3), _line_dist(p2, p0, p3))
                <= _FLATTEN_TOL_UNITS):
            self._append(p3)
            return
        p01 = _mid(p0, p1)
        p12 = _mid(p1, p2)
        p23 = _mid(p2, p3)
        p012 = _mid(p01, p12)
        p123 = _mid(p12, p23)
        pm = _mid(p012, p123)
        self._subdiv_cubic(p0, p01, p012, pm, depth + 1)
        self._subdiv_cubic(pm, p123, p23, p3, depth + 1)

    def _append(self, p):
        """去重追加（重复点 = 零长笔画，白耗 PLT 字节）。"""
        cur = self._cur
        if not (cur and cur[-1] == p):
            cur.append(p)


def _mid(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def _line_dist(p, a, b):
    """点 p 到直线 ab 的距离（共线退化 → 0）。"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n < 1e-12:
        return 0.0
    return abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / n


def _tofu(upm: int) -> tuple[tuple[tuple[float, float], ...], float]:
    """缺字豆腐框：空心矩形轮廓 + advance（字体单位）。"""
    x0, x1 = _TOFU_X0_EM * upm, _TOFU_X1_EM * upm
    y1 = _TOFU_Y1_EM * upm
    rect = ((x0, 0.0), (x1, 0.0), (x1, y1), (x0, y1))
    return rect, _TOFU_ADV_EM * upm


@lru_cache(maxsize=4096)
def glyph(ch: str, path: str | None = None) -> GlyphGeom:
    """单字符 → 展平轮廓 + advance（字体单位）。按 (path, ch) 进程级缓存。

    cmap 未命中 → 豆腐框 + missing=True + warning（可见占位，不静默丢字）。
    空格等无轮廓字符 contours 为空、advance 正常（词间距由 advance 决定）。
    """
    font = load_font(path)
    upm = font['head'].unitsPerEm
    cmap = font.getBestCmap()
    gname = cmap.get(ord(ch)) if len(ch) == 1 else None
    if gname is None:
        logging.warning('PLT 信息表格：字符 %r (U+%04X) 不在字体 cmap 中，'
                        '以豆腐框占位渲染', ch, ord(ch) if ch else 0)
        rect, adv = _tofu(upm)
        return GlyphGeom(contours=(rect,), advance=adv, missing=True)
    glyph_set = font.getGlyphSet()
    pen = _FlattenPen(glyph_set)
    glyph_set[gname].draw(pen)
    pen._flush()
    contours = []
    for c in pen.contours:
        # BasePen closePath 已保证回到起点：剥掉与首点重复的末点
        #（PLT 闭合折线由 _plt_polyline(closed=True) 追加首点，双写会画出零长段）
        if len(c) >= 2 and c[0] == c[-1]:
            c = c[:-1]
        if len(c) >= 2:
            contours.append(tuple(c))
    return GlyphGeom(contours=tuple(contours),
                     advance=float(getattr(glyph_set[gname], 'width', upm)),
                     missing=False)


def _upm(path: str | None) -> int:
    return load_font(path)['head'].unitsPerEm


# ===================== 单线矢量字（v5 2026-08-30，默认渲染路径）=====================
# 统一 em 网格：汉字 medians 原生 1024，Hershey 原始单位按头行 em 缩放到同网格
_STROKE_EM = 1024.0

# MMaH medians 全库笔画中心线 y（翻转向上后）范围 —— 含笔画粗度外溢，超出
# 名义 em；仿射归一到标准 CJK 排印盒 [0.06, 0.94]em（汉字与 ASCII 混排时基线
# 关系正常，对齐常见中文字体的版面位置）
_HZ_BODY_LO, _HZ_BODY_HI = 139.0, 1120.0
_HZ_BOX_LO_EM, _HZ_BOX_HI_EM = 0.06, 0.94

# NFKC 后仍残留的全角/异形符号 → Hershey 可画的 ASCII（数据侧实测残留集；
# '，：；！？' 等 fullwidth form NFKC 自会转换，'。、' 是表意标点不转 → 显式映射）
_SYMBOL_MAP = {'—': '-', '‐': '-', '−': '-', '·': '.', '・': '.',
               '。': '.', '、': ','}


@dataclass(frozen=True)
class StrokeGlyph:
    """单线字形：开放笔画折线（em 单位、基线 y=0、字顶 y>0）+ advance（em）。"""

    strokes: tuple[tuple[tuple[float, float], ...], ...]
    advance: float


def _parse_hanzi_line(a: float, b: float, body: str) -> StrokeGlyph:
    strokes = []
    for sp in body.split(';'):
        pts = []
        for pt in sp.split(' '):
            x, y = pt.split(',')
            pts.append((float(x), a * float(y) + b))
        strokes.append(tuple(pts))
    return StrokeGlyph(strokes=tuple(strokes), advance=_STROKE_EM)


@lru_cache(maxsize=1)
def load_stroke_font() -> tuple[dict, dict]:
    """→ ``(hanzi, ascii)`` 两张 char→StrokeGlyph 表（em=_STROKE_EM 统一网格）。

    资源缺失（安装不全）→ 空表 + warning，调用方回退 Noto 轮廓 —— 单线字是
    风格增强而非功能底线，缺文件不该硬炸导出（与捆绑 otf 的 fail-fast 口径
    不同，otf 缺失时轮廓路径也不可用）。
    """
    hanzi: dict[str, StrokeGlyph] = {}
    ascii_: dict[str, StrokeGlyph] = {}
    hz_path = os.path.join(paths.FONT_DIR, 'hanzi_medians.txt')
    if os.path.exists(hz_path):
        span = _HZ_BODY_HI - _HZ_BODY_LO
        a = (_HZ_BOX_HI_EM - _HZ_BOX_LO_EM) * _STROKE_EM / span
        b = _HZ_BOX_LO_EM * _STROKE_EM - _HZ_BODY_LO * a
        with open(hz_path, encoding='utf-8') as f:
            for ln in f:
                if ln.startswith('#') or '\t' not in ln:
                    continue
                ch, body = ln.rstrip('\n').split('\t', 1)
                hanzi[ch] = _parse_hanzi_line(a, b, body)
    asc_path = os.path.join(paths.FONT_DIR, 'hershey_rowmans.txt')
    if os.path.exists(asc_path):
        em_units = 1.0
        with open(asc_path, encoding='utf-8') as f:
            for ln in f:
                ln = ln.rstrip('\n')
                if ln.startswith('#EM'):
                    em_units = float(ln.split()[1])
                    k = _STROKE_EM / em_units
                    continue
                if not ln or '\t' not in ln:
                    continue
                ch, adv, body = ln.split('\t', 2)
                # 空格等无笔画字符 body 为空；双空格/尾随空格防御性滤掉空 token
                strokes = tuple(
                    tuple((float(x) * k, float(y) * k)
                          for x, y in (tok.split(',') for tok in sp.split(' ') if tok))
                    for sp in body.split(';') if sp)
                ascii_[ch] = StrokeGlyph(strokes=strokes, advance=float(adv) * k)
        # JHF 的 y 自字顶向下增长（y=0 = cap 顶，'H' 竖笔底端 = 基线），统一翻成
        # 基线=0、y 向上 —— 否则 ASCII 逐字垂直镜像（'L' 横画跑到字顶、'7' 横画
        # 在底下），与汉字/表格 w=字顶朝向约定相反。基线取 'H' 竖笔最深 y。
        if ascii_:
            h_glyph = ascii_.get('H')
            base = (max(y for sp in h_glyph.strokes for _x, y in sp)
                    if h_glyph else 0.64 * _STROKE_EM)
            ascii_ = {
                ch: StrokeGlyph(
                    strokes=tuple(tuple((x, base - y) for x, y in sp)
                                  for sp in sg.strokes),
                    advance=sg.advance)
                for ch, sg in ascii_.items()
            }
    if not hanzi or not ascii_:
        logging.warning('PLT 单线字资源缺失（resources/fonts/ 的 hanzi_medians.'
                        'txt / hershey_rowmans.txt）—— 表格文字回退 Noto 轮廓字体')
    return hanzi, ascii_


def normalize_text(text: str) -> str:
    """NFKC 归一 + 残留符号映射（全角→半角、CJK 兼容形→典型形、—·→ASCII）。

    单线字两库只收典型形与 ASCII；归一在 text_width / text_strokes 入口统一做，
    保证测量与渲染看到同一字符串。
    """
    text = unicodedata.normalize('NFKC', text)
    return ''.join(_SYMBOL_MAP.get(ch, ch) for ch in text)


_outline_fallback_warned: set[str] = set()


def _advance_em(ch: str, path: str | None) -> float:
    """单字符 advance（em=_STROKE_EM 网格）：单线两库优先，Noto 换算兜底。"""
    hanzi, ascii_ = load_stroke_font()
    sg = hanzi.get(ch) or ascii_.get(ch)
    if sg is not None:
        return sg.advance
    return glyph(ch, path).advance / _upm(path) * _STROKE_EM


def text_width(text: str, char_h_mm: float, path: str | None = None) -> float:
    """文本宽度（mm）= advance 累加 ×（字高/em）。advance 线性随字高缩放，
    shrink-to-fit 单遍测量即可（无需迭代）。单线字优先（汉字 1em、Hershey 按
    字符比例宽），Noto 轮廓换算兜底。"""
    if not text:
        return 0.0
    text = normalize_text(text)
    total_em = math.fsum(_advance_em(ch, path) for ch in text)
    return total_em / _STROKE_EM * char_h_mm


def text_strokes(text: str, *, origin: tuple[float, float],
                 u: tuple[float, float], w: tuple[float, float],
                 char_h_mm: float, fit_width_mm: float | None = None,
                 min_char_h_mm: float = 9.0,
                 path: str | None = None) -> list[tuple[bool, list[tuple[float, float]]]]:
    """文本 → 世界 mm 折线 ``[(closed, points)]``：单线字笔画开放
    （closed=False，一笔中线）、Noto 轮廓回退闭合（closed=True，由调用方交
    _plt_polyline(closed=True) 物理闭合）。

    origin: 基线起点（世界 mm）；u: 书写方向单位向量；w: 字顶方向单位向量
    （(u,w) 必须右手系 det(u,w)>0，左手系 = 镜像字形，直接 raise）。
    char_h_mm: em 字高；fit_width_mm 给定时 shrink-to-fit：实测宽超限 →
    char_h_eff = max(min_char_h_mm, char_h×fit/实测宽)（只缩不放）；到下限仍
    超宽按 advance 从尾部截断字符（可见截断，绝不静默换行/丢中段）。
    """
    text = normalize_text(text)
    if not text:
        return []
    ul = math.hypot(*u)
    wl = math.hypot(*w)
    if ul < 1e-9 or wl < 1e-9:
        raise ValueError(f'退化基向量 u={u} w={w}')
    ux, uy = u[0] / ul, u[1] / ul
    wx, wy = w[0] / wl, w[1] / wl
    if ux * wy - uy * wx <= 0:
        raise ValueError(f'(u,w) 必须右手系（det>0），got u={u} w={w} —— '
                         '左手系会渲染镜像文字（export_plt 2026-08-24 手性 bug 同款）')

    char_h_eff = char_h_mm
    body = text
    if fit_width_mm is not None and fit_width_mm > 0:
        w_full = text_width(text, char_h_mm, path)
        if w_full > fit_width_mm:
            char_h_eff = max(min_char_h_mm, char_h_mm * fit_width_mm / w_full)
            if text_width(text, char_h_eff, path) > fit_width_mm:
                # 下限字高仍超宽：尾部截断（每删一字符重测，O(n) 缓存下开销可忽略）
                while (len(body) > 1
                       and text_width(body, char_h_eff, path) > fit_width_mm):
                    body = body[:-1]

    hanzi, ascii_ = load_stroke_font()
    s = char_h_eff / _STROKE_EM
    s_noto = char_h_eff / _upm(path)      # Noto 字体单位 → mm
    strokes: list[tuple[bool, list[tuple[float, float]]]] = []
    gx = 0.0
    for ch in body:
        sg = hanzi.get(ch) or ascii_.get(ch)
        if sg is not None:
            for poly in sg.strokes:
                strokes.append((False, [
                    (origin[0] + (gx + px * s) * ux + (py * s) * wx,
                     origin[1] + (gx + px * s) * uy + (py * s) * wy)
                    for px, py in poly]))
            gx += sg.advance * s
            continue
        # 单线两库未覆盖（生僻符号/未收录字）→ Noto 轮廓兜底 + 每字符一次 warning
        if ch not in _outline_fallback_warned:
            _outline_fallback_warned.add(ch)
            logging.warning('PLT 信息表格：字符 %r (U+%04X) 不在单线字库中，'
                            '以 Noto 轮廓渲染（与单线风格混排）', ch, ord(ch))
        g = glyph(ch, path)
        for contour in g.contours:
            strokes.append((True, [
                (origin[0] + (gx + px * s_noto) * ux + (py * s_noto) * wx,
                 origin[1] + (gx + px * s_noto) * uy + (py * s_noto) * wy)
                for px, py in contour]))
        gx += g.advance * s_noto
    return strokes

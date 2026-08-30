"""PLT 矢量文本引擎：捆绑 OFL 中文字体 → 轮廓展平 → 世界 mm 折线（2026-08-30）。

唛架信息表格（plt_table.py）的中文/ASCII 文字来源。PLT 全程无 LB 文字指令
（设备兼容口径，export_plt.py 同款），文字 = 字形轮廓的 PU/PD 闭合折线 ——
与 2026-08-24 起「尺码*数量」标注的矢量笔画同思路，但字库不再手写 11 个字形，
而是从捆绑字体提取任意字符轮廓（用户手输的排料师/备注可为任意汉字）。

字体（2026-08-30 定案：仓库捆绑完整 OFL 字体）：Noto Sans SC Regular
（SubsetOTF/SC，~8.3MB，OFL 1.1 许可随包分发，resources/fonts/）。此前评估过
「子集 + 运行时系统字体回退」与「纯运行时发现链」均否决 —— Ubuntu 服务器是否
装中文字体不可控（PNG 导出依赖系统 YaHei 的教训），捆绑保证任何汉字 100% 可
渲染、本机/服务器行为一致。路径经 paths.PLT_FONT_PATH（环境变量 MS_FONT_DIR
可覆盖）。fontTools 为 ezdxf 既有依赖，本次起 pyproject 显式声明。

轮廓展平：继承 fontTools BasePen（**不要** RecordingPen 手排 —— 预研踩坑：
'0' 等 TrueType 字形首点是隐含 on-curve、closePath 早于 moveTo 的顺序问题，
BasePen 内建处理隐含起点 / qCurveTo(...,None) 哨兵 / 多控制点二次段分解）。
CFF 三次（curveTo）与 TrueType 二次（qCurveTo）双路支持：De Casteljau 中点
递归细分，控制点离弦距离 ≤ 容差即停（_FLATTEN_TOL_UNITS=2 字体单位 ≈
0.036mm @18mm 字高，upm=1000）。

任意方向文字 = (u, w) 二维基变换（复用 export_plt._grain_annotation_strokes
已验证机制，2026-08-24 手性 bug 后定稿口径）：u = 书写方向单位向量、
w = 字顶方向，**(u, w) 必须右手系**（det(u,w) > 0，否则字形镜像 —— text_strokes
直接 raise 防御，勿改成静默容忍）。字形点 (px, py)（字体单位，基线 y=0、
字顶 y>0）→ world = origin + (gx + px·s)·u + (py·s)·w（gx = 已累积 advance mm、
s = 字高/upm）。

缺字处理（宁可见勿静默）：cmap 未命中（生僻字/emoji）→ 画空心豆腐框占位
（0.1em..0.9em × 0..0.8em）+ logging.warning —— 裁剪车间里错漏信息比缺字
更危险，可见占位一眼可辨。
"""
from __future__ import annotations

import logging
import math
import os
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


def text_width(text: str, char_h_mm: float, path: str | None = None) -> float:
    """文本宽度（mm）= advance 累加 ×（字高/upm）。advance 线性随字高缩放，
    shrink-to-fit 单遍测量即可（无需迭代）。"""
    if not text:
        return 0.0
    upm = _upm(path)
    adv_units = sum(glyph(ch, path).advance for ch in text)
    return adv_units / upm * char_h_mm


def text_strokes(text: str, *, origin: tuple[float, float],
                 u: tuple[float, float], w: tuple[float, float],
                 char_h_mm: float, fit_width_mm: float | None = None,
                 min_char_h_mm: float = 9.0,
                 path: str | None = None) -> list[list[tuple[float, float]]]:
    """文本 → 世界 mm 折线列表（每条 = 一条闭合字形轮廓，末点不重复首点，
    由调用方以 closed=True 交 _plt_polyline 物理闭合）。

    origin: 基线起点（世界 mm）；u: 书写方向单位向量；w: 字顶方向单位向量
    （(u,w) 必须右手系 det(u,w)>0，左手系 = 镜像字形，直接 raise）。
    char_h_mm: em 字高；fit_width_mm 给定时 shrink-to-fit：实测宽超限 →
    char_h_eff = max(min_char_h_mm, char_h×fit/实测宽)（只缩不放）；到下限仍
    超宽按 advance 从尾部截断字符（可见截断，绝不静默换行/丢中段）。
    """
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

    upm = _upm(path)
    s = char_h_eff / upm
    strokes: list[list[tuple[float, float]]] = []
    gx = 0.0
    for ch in body:
        g = glyph(ch, path)
        for contour in g.contours:
            strokes.append([(origin[0] + (gx + px * s) * ux + (py * s) * wx,
                             origin[1] + (gx + px * s) * uy + (py * s) * wy)
                            for px, py in contour])
        gx += g.advance * s
    return strokes

# -*- coding: utf-8 -*-
"""VB超排 应用图标生成器（候选稿）。

用法：
    .venv/Scripts/python.exe scripts/make_app_icon.py              # 生成全部候选到 out/icon_candidates/
    .venv/Scripts/python.exe scripts/make_app_icon.py --index 3    # 只重出 3 号
    .venv/Scripts/python.exe scripts/make_app_icon.py --index 3 \
        --ico materialSorting-server/assets/app.ico               # 定稿后导出多尺寸 ico（exe/Inno 用）

设计约束（用户 2026-09-27 定案）：
- 软件名「VB超排」；图标 = 圆角正方形（半径 ≈ 22% 边长，参考微信观感）+ 浅色系；
- 题材围绕「排料」：嵌套裁片条带 / 牛仔前后幅互扣 / 单片剪影，配 VB / 超排 字标。

仅依赖 Pillow + Windows 系统字体，纯本地渲染（超采样 1024 → 输出 512）。
"""
from __future__ import annotations

import argparse
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Windows 控制台默认 GBK（scripts/AGENTS.md 惯例）
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

S = 1024                       # 画布（2x 超采样）
OUT = 512                      # 输出边长
RADIUS = int(S * 0.22)         # 圆角半径 ≈ 22% 边长
FONT_LAT = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
FONT_CN = ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"]

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _font(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise FileNotFoundError(paths)


def rgb(h: str):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(h: str, a: int = 255):
    return rgb(h) + (a,)


def base(c_top: str, c_bottom: str | None = None) -> Image.Image:
    """圆角正方形底图，可带纵向浅渐变。"""
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if c_bottom is None:
        d.rectangle([0, 0, S, S], fill=rgba(c_top))
    else:
        a, b = rgb(c_top), rgb(c_bottom)
        for y in range(S):
            t = y / S
            fill = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)
            d.line([(0, y), (S, y)], fill=fill)
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=RADIUS, fill=255)
    img.putalpha(mask)
    return img


def soft_shadow(img: Image.Image, box, radius: int, blur=16, alpha=34, dy=10) -> Image.Image:
    """给条带/色块垫一层柔和落影（画在独立层再合成）。"""
    lay = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle(
        [box[0], box[1] + dy, box[2], box[3] + dy], radius=radius, fill=(30, 40, 60, alpha))
    lay = lay.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(img, lay)


def shrink(poly, k=0.9):
    """多边形向质心收缩（模拟裁片之间的缝隙）。"""
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    return [(cx + (x - cx) * k, cy + (y - cy) * k) for x, y in poly]


def fit_font(paths: list[str], text: str, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    """字号自适应：文字宽度不超过 max_w，防字标溢出画布。"""
    probe = ImageDraw.Draw(Image.new('RGBA', (8, 8)))
    while size > 40:
        f = _font(paths, size)
        b = probe.textbbox((0, 0), text, font=f)
        if b[2] - b[0] <= max_w:
            return f
        size -= 12
    return _font(paths, 40)


def text_center(d: ImageDraw.ImageDraw, cx, cy, text, font, fill):
    b = d.textbbox((0, 0), text, font=font)
    d.text((cx - (b[2] - b[0]) / 2 - b[0], cy - (b[3] - b[1]) / 2 - b[1]),
           text, font=font, fill=fill)


def dashed(d: ImageDraw.ImageDraw, p0, p1, fill, width=10, dash=22, gap=15):
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    if L <= 0:
        return
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    s = 0.0
    while s < L:
        e = min(s + dash, L)
        d.line([(x0 + ux * s, y0 + uy * s), (x0 + ux * e, y0 + uy * e)], fill=fill, width=width)
        s += dash + gap

# ---------------------------------------------------------------------------
# 排料题材元件
# ---------------------------------------------------------------------------

def strip_partition(box):
    """把条带内框切成 3 块互贴的『裁片』（精确铺满，再各自收缩出缝）。"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0

    def p(fx, fy):
        return (x0 + w * fx, y0 + h * fy)

    p1 = [p(0, 0), p(.32, 0), p(.40, .38), p(.24, 1), p(0, 1)]
    p2 = [p(.32, 0), p(1, 0), p(1, .42), p(.40, .38)]
    p3 = [p(.40, .38), p(1, .42), p(1, 1), p(.24, 1)]
    return [p1, p2, p3]


def draw_marker(d: ImageDraw.ImageDraw, box, shades: list[str], dots: str | None = None):
    """唛架条带：白底圆角条 + 3 块嵌套裁片，可加点状铆钉细节。"""
    d.rounded_rectangle(box, radius=int((box[2] - box[0]) * 0.07), fill=(255, 255, 255, 255))
    for poly, c in zip(strip_partition(box), shades):
        d.polygon(shrink(poly, 0.9), fill=rgba(c))
    if dots:
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        r = int(h * 0.028)
        for fx, fy in ((.13, .26), (.13, .46), (.13, .66)):
            d.ellipse([x0 + w * fx - r, y0 + h * fy - r, x0 + w * fx + r, y0 + h * fy + r],
                      fill=rgba(dots))


# 牛仔后幅剪影（腰口在上、裆点 (150,120)、两裤腿朝下），局部坐标 300x330
PANTS = [(40, 0), (260, 0), (300, 330), (185, 330), (150, 120), (115, 330), (0, 330)]


def pants_pts(scale, dx, dy, rot180=False):
    pts = [(300 - x, 330 - y) for x, y in PANTS] if rot180 else PANTS
    return [(x * scale + dx, y * scale + dy) for x, y in pts]

# ---------------------------------------------------------------------------
# 12 个候选
# ---------------------------------------------------------------------------

def c01() -> Image.Image:
    img = base('#E7F4EC', '#DCEFE3')
    box = (152, 312, 872, 712)
    img = soft_shadow(img, box, radius=28)
    d = ImageDraw.Draw(img)
    draw_marker(d, box, ['#3E9B74', '#66B692', '#9BD3B8'], dots='#DCEFE3')
    return img


def c02() -> Image.Image:
    img = base('#E9F1FB', '#DDE9F7')
    box = (152, 312, 872, 712)
    img = soft_shadow(img, box, radius=28)
    d = ImageDraw.Draw(img)
    draw_marker(d, box, ['#3E7BC0', '#6FA0D0', '#A5C6E7'], dots='#DDE9F7')
    return img


def c03() -> Image.Image:
    img = base('#FBF2E3', '#F7EBD5')
    box = (152, 312, 872, 712)
    img = soft_shadow(img, box, radius=28)
    d = ImageDraw.Draw(img)
    draw_marker(d, box, ['#D98E4A', '#E5AF77', '#F0D2AC'], dots='#F7EBD5')
    return img


def _vb(c_top, c_bottom, text_color, bar_colors, cy=400, bar_y=770, bar_h=54):
    img = base(c_top, c_bottom)
    d = ImageDraw.Draw(img)
    text_center(d, S / 2, cy, 'VB', fit_font(FONT_LAT, 'VB', 430, 620), rgba(text_color))
    # 三段『裁片段』胶囊条（宽度不等 = 排料观感）
    widths = (.26, .50, .24)
    gap = 14
    total = 560
    x = S / 2 - total / 2
    for frac, c in zip(widths, bar_colors):
        w = total * frac - gap
        d.rounded_rectangle([x, bar_y, x + w, bar_y + bar_h], radius=bar_h // 2, fill=rgba(c))
        x += total * frac
    return img


def c04() -> Image.Image:
    return _vb('#EDEBF8', '#E4E1F4', '#57489C', ['#8B7EC9', '#57489C', '#B9B0E4'])


def c05() -> Image.Image:
    """利用率仪表盘：270° 圆弧走到 90%（行业生死线），指针圆点 + 中心大字。"""
    img = base('#E8F1FB', '#DEECF9')
    d = ImageDraw.Draw(img)
    cx, cy, r, w = S / 2, 540, 300, 56
    span = 270                       # 量程角
    a0 = 135                         # 起始角（PIL 屏幕系，顺时针，3 点方向为 0°）
    frac = 0.90
    bbox = [cx - r, cy - r, cx + r, cy + r]
    d.arc(bbox, start=a0, end=a0 + span, fill=rgba('#C9DCF0'), width=w)
    d.arc(bbox, start=a0, end=a0 + span * frac, fill=rgba('#3E7BC0'), width=w)
    end = math.radians(a0 + span * frac)
    ex, ey = cx + r * math.cos(end), cy + r * math.sin(end)
    d.ellipse([ex - 46, ey - 46, ex + 46, ey + 46], fill=rgba('#2C4A70'))
    d.ellipse([cx - 26, cy - 26, cx + 26, cy + 26], fill=rgba('#2C4A70'))
    text_center(d, cx, cy - 96, '90%', fit_font(FONT_LAT, '90%', 210, 380), rgba('#2C4A70'))
    return img


def c06() -> Image.Image:
    img = base('#E6F2F4', '#DDEEF0')
    d = ImageDraw.Draw(img)
    text_center(d, S / 2, 470, '超排', fit_font(FONT_CN, '超排', 300, 680), rgba('#1F5F6B'))
    gap, total, h, y = 12, 340, 36, 780
    x = S / 2 - total / 2
    for frac, c in zip((.62, .38), ('#33808C', '#79B4BD')):
        w = total * frac - gap
        d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=rgba(c))
        x += total * frac
    return img


def c07() -> Image.Image:
    img = base('#F6F4ED', '#F1EEE3')
    d = ImageDraw.Draw(img)
    text_center(d, S / 2, 430, '超', fit_font(FONT_CN, '超', 620, 640), rgba('#33415F'))
    box = (312, 770, 712, 862)
    img = soft_shadow(img, box, radius=18, blur=12, alpha=28, dy=6)
    d = ImageDraw.Draw(img)
    draw_marker(d, box, ['#6C82A3', '#93A7C4', '#C0CCDD'])
    return img


def c08() -> Image.Image:
    """前后幅互扣：A 正立（深丹宁），B 旋转 180°（浅丹宁），外缘平行留缝。"""
    img = base('#E2EDF9', '#D8E7F6')
    d = ImageDraw.Draw(img)
    sc = 1.22
    dx, dy = 152, 286
    d.polygon(pants_pts(sc, dx, dy), fill=rgba('#5F8DC0'))
    d.polygon(pants_pts(sc, dx + 289 * sc, dy + 40 * sc, rot180=True), fill=rgba('#A9C6E4'))
    return img


def c09() -> Image.Image:
    """单片剪影：白底裁片 + 轮廓线 + 中缝虚线 + 两颗铆钉。"""
    img = base('#EDF2F8', '#E7EDF5')
    d = ImageDraw.Draw(img)
    sc = 1.9
    dx, dy = (S - 300 * sc) / 2, (S - 330 * sc) / 2
    d.polygon(pants_pts(sc, dx, dy), fill=(255, 255, 255, 255), outline=rgba('#7796BC'),
              width=int(14 * sc / 1.9 * 1.3))
    line = rgba('#7796BC')
    dashed(d, (dx + 150 * sc, dy + 14 * sc), (dx + 150 * sc, dy + 112 * sc), line,
           width=int(9 * sc / 1.9 * 1.2), dash=int(24 * sc / 1.9), gap=int(16 * sc / 1.9))
    r = 20
    for fx in (80, 220):
        cx, cy = dx + fx * sc, dy + 50 * sc
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgba('#AFC4DE'))
    return img


def c10() -> Image.Image:
    """几何四宫拼合：两圆角方 + 两圆，四种蓝灰。"""
    img = base('#F0F2F5', '#EAEDF2')
    d = ImageDraw.Draw(img)
    r = 64
    d.rounded_rectangle([168, 168, 500, 500], radius=r, fill=rgba('#7C93B8'))
    d.ellipse([524, 168, 856, 500], fill=rgba('#A9BAD4'))
    d.ellipse([168, 524, 500, 856], fill=rgba('#C7D2E3'))
    d.rounded_rectangle([524, 524, 856, 856], radius=r, fill=rgba('#5B7399'))
    return img


def c11() -> Image.Image:
    """拼图互扣：左件带凸榫、右件留凹槽（浅粉）。底色必须纯色，凹槽靠底色圆实现。"""
    img = base('#FBEEF2')
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([170, 300, 556, 724], radius=52, fill=rgba('#E29BB8'))
    d.ellipse([556 - 60, 512 - 60, 556 + 60, 512 + 60], fill=rgba('#E29BB8'))   # 凸榫
    d.rounded_rectangle([612, 300, 872, 724], radius=52, fill=(255, 255, 255, 255))
    d.ellipse([612 - 74, 512 - 74, 612 + 74, 512 + 74], fill=rgba('#FBEEF2'))  # 凹槽
    return img


def c12() -> Image.Image:
    img = base('#C9DFF5', '#E8F3FC')
    d = ImageDraw.Draw(img)
    text_center(d, S / 2, 400, 'VB', fit_font(FONT_LAT, 'VB', 430, 620), rgba('#24466E'))
    box = (282, 690, 742, 862)
    img = soft_shadow(img, box, radius=24, blur=14, alpha=30)
    d = ImageDraw.Draw(img)
    draw_marker(d, box, ['#3E6B96', '#6FA0D0', '#A5C6E7'])
    return img


CANDIDATES = [
    ('c01', '嵌套裁片·薄荷', c01),
    ('c02', '嵌套裁片·冰蓝', c02),
    ('c03', '嵌套裁片·奶油', c03),
    ('c04', 'VB·雾紫', c04),
    ('c05', '利用率仪表盘·浅蓝', c05),
    ('c06', '超排·浅青', c06),
    ('c07', '超·宣纸+唛架', c07),
    ('c08', '前后幅互扣·天蓝', c08),
    ('c09', '单片剪影·雾灰蓝', c09),
    ('c10', '几何拼合·雾灰', c10),
    ('c11', '拼图互扣·淡粉', c11),
    ('c12', 'VB+唛架·渐变蓝', c12),
]

# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def render(idx: int) -> Image.Image:
    _, _, fn = CANDIDATES[idx - 1]
    return fn().resize((OUT, OUT), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser(description='VB超排 图标生成')
    ap.add_argument('--index', type=int, help='只渲染第 N 号候选（1 起）')
    ap.add_argument('--ico', type=str, help='把指定候选导出为多尺寸 .ico（需 --index）')
    ap.add_argument('--outdir', default='out/icon_candidates')
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    if args.ico:
        assert args.index, '--ico 需要与 --index 同给'
        img = render(args.index)
        img.save(args.ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                  (256, 256)])
        print(f'[OK] {args.ico}')
        return

    paths = []
    for i, (key, title, _) in enumerate(CANDIDATES, 1):
        if args.index and i != args.index:
            continue
        p = os.path.join(args.outdir, f'{i:02d}_{key}.png')
        render(i).save(p)
        paths.append((i, title, p))
        print(f'[OK] {i:02d} {title} -> {p}')

    if args.index:
        return

    # 总览拼图（4x3，alpha 合成让圆角在底色上可见）
    cols, cell, pad, label_h = 4, 300, 28, 46
    rows = math.ceil(len(paths) / cols)
    W = cols * cell + (cols + 1) * pad
    H = rows * (cell + label_h) + (rows + 1) * pad
    sheet = Image.new('RGBA', (W, H), (233, 237, 242, 255))
    for n, (i, title, p) in enumerate(paths):
        r, c = divmod(n, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + label_h + pad)
        sheet.alpha_composite(Image.open(p).resize((cell, cell), Image.LANCZOS), (x, y))
    d = ImageDraw.Draw(sheet)
    f = _font(FONT_CN, 24)
    for n, (i, title, p) in enumerate(paths):
        r, c = divmod(n, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + label_h + pad)
        d.text((x + 4, y + cell + 8), f'{i:02d} {title}', font=f, fill=(90, 98, 112))
    sheet.save(os.path.join(args.outdir, 'overview.png'))
    print(f'[OK] overview -> {args.outdir}/overview.png')

    # preview.html（浏览器里放大挑选）
    items = '\n'.join(
        f'<figure><img src="{os.path.basename(p)}"><figcaption>{i:02d} {title}</figcaption></figure>'
        for i, title, p in paths)
    html = (f'<!doctype html><meta charset="utf-8"><title>VB超排 图标候选</title>'
            f'<style>body{{background:#f4f6f8;font-family:"Microsoft YaHei",sans-serif;'
            f'display:flex;flex-wrap:wrap;gap:32px;padding:40px;justify-content:center}}'
            f'figure{{margin:0;text-align:center}}img{{width:220px;height:220px;'
            f'border-radius:48px;box-shadow:0 8px 24px rgba(30,40,60,.12)}}'
            f'figcaption{{margin-top:12px;color:#5a6270;font-size:14px}}</style>'
            f'<h1 style="width:100%;text-align:center;color:#33415f">VB超排 · 图标候选（{len(paths)}）</h1>'
            f'{items}')
    with open(os.path.join(args.outdir, 'preview.html'), 'w', encoding='utf-8') as fh:
        fh.write(html)
    print(f'[OK] preview -> {args.outdir}/preview.html')


if __name__ == '__main__':
    main()

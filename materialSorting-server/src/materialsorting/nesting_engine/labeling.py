"""裁片 g01+ 编号单一真相源（v2：label 先行、名称无关）。

供 ``web/server.py`` 的 parse-dxf 响应与 commit-to-nesting intermediate 共用，保证两条
管线对同一母版产出的 label 集合一致 —— parse 与 commit 各自对同一母版跑 ``assign_codes``
（同 collect、同排序键、同母版码规则），同一 ``(block_name, size, piece_index)`` 必得
同码（AC#5 对齐不变量），不再经 (size, ptype) 中转。

编号体系（2026-08-18 起统一为 g 码，取代旧 A/B/C 字母序号与片型中文名标定）：
  - 裁片码 = ``g`` + 两位零填充数字（g01/g02/...，>99 片自然升 g100）；
  - 「有效片」= 全部 ``size != None`` 片（不要求任何名称映射；未录入名称的组不再丢片）；
  - 默认顺序赋号：每码内独立从 g01 起，排序键前置 ``group_key``（block 名派生的身份
    串，与名称识别无关）保证跨码同号 —— 同一 block 模板在各码得到同一 g 码；
  - 母版编号复用：母版 block 名带显式编号尾缀（如 ``前片g03.30`` → g03）时整体复用，
    all-or-nothing（见 ``collect_master_codes``），否则回退顺序赋号。

依赖方向合规：本模块仅 import 标准库，不依赖任何兄弟包（PieceOutline 是 duck-typed，
只读 ``polygon_mm / area_mm2 / block_name / piece_index / group_key / size`` 属性）。
上层 ``web`` 与同层 ``nesting_engine`` 均可 import。
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable


def label_for(idx: int) -> str:
    """0→g01, 1→g02, ..., 98→g99, 99→g100（g + 两位零填充；每码裁片数实测 ≤10）。

    零填充保证字典序 = 数值序（前端 ``compareByLabel`` 的「先长度再字典序」比较器
    与零填充天然兼容，勿去零填充）；g 码即裁片标识，全链路（parse / intermediate /
    WS / 前端 / 导出）同值。
    """
    return f'g{idx + 1:02d}'


# g 码解析（code_sort_key 用）
_CODE_RE = re.compile(r'^g(\d+)$')
# 母版编号尾缀：显式前缀 g/G/# + 1~3 位数字（前片g03 / 腰G3 / 袋#7）。
_MASTER_CODE_RE = re.compile(r'(?:g|G|#)(\d{1,3})$')
# 码号尾缀（与 ``dxf_parser.reader._SIZE_RE`` 同口径）。labeling 保持仅标准库、
# 不 import 兄弟包，故复制常量 —— 两处正则须同步改。
_SIZE_SUFFIX_RE = re.compile(r'[-._](\d+)$')


def code_sort_key(code: str) -> int:
    """g 码 → 数值序键（'g02'→2, 'g10'→10）；非 g 码兜底 0（稳定性靠排序并列）。"""
    m = _CODE_RE.fullmatch(code)
    return int(m.group(1)) if m else 0


def master_code_from_block_name(block_name: str) -> str | None:
    """从母版 block 名提取版师编号 → 规范化 ``gNN``；无显式编号返回 None。

    规则（保守 v1，识别载体仅 block 名；图面 TEXT 实体编号待真实样本校准后再议）：
      1. 先剥码号尾缀（同 ``reader._SIZE_RE`` 口径）：``前片g03.30`` → ``前片g03``；
      2. 再要求剩余部分以显式前缀编号结尾：``(?:g|G|#)(\d{1,3})$`` → 规范化零填充
         （``G3`` / ``#7`` → ``g03`` / ``g07``），与顺序赋号同值域，下游零改动。

    纯数字尾缀（``前片3``）**不识别** —— 与码号 / 款号数字混淆
    （``noname.M1787#28-32С33-38`` 这类块名会被纯数字规则误伤）；
    ``noname.双排.28`` 剥码号后无编号尾缀亦返回 None（走默认顺序赋号）。
    """
    stripped = _SIZE_SUFFIX_RE.sub('', block_name)
    m = _MASTER_CODE_RE.search(stripped)
    if not m:
        return None
    return f'g{int(m.group(1)):02d}'


def centroid(poly: list[tuple[float, float]]) -> tuple[float, float]:
    """顶点算术质心（用于稳定排序键）。空 polygon 兜底 (0,0)。"""
    if not poly:
        return (0.0, 0.0)
    sx = sum(x for x, _ in poly)
    sy = sum(y for _, y in poly)
    return (sx / len(poly), sy / len(poly))


def size_sort_key(size: int | None) -> tuple[int, int]:
    """码号排序键：None 殿后，其余按数值升序。"""
    return (1, 0) if size is None else (0, size)


def parse_member_sort_key(p):
    """码内成员稳定排序键（parse 响应赋号 / label 对齐 / 代表裁片共用）。

    ``(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)`` —— 上方 / 左 /
    大片优先。消费方（``web/server.py._build_parse_payload``、本模块 ``assign_codes``、
    ``web/server.py._build_label_representatives``）必须同键：g 码编号、intermediate
    label 与高级配置代表裁片的对应关系才能跨端点一致（改任何一处须同步，故收敛为
    单一真相源）。
    """
    return (
        -centroid(p.polygon_mm)[1],
        centroid(p.polygon_mm)[0],
        -p.area_mm2,
        p.block_name,
        p.piece_index,
    )


def sequential_sort_key(p):
    """顺序赋码排序键（T4）：``group_key`` 前置 + 码内成员稳定排序键。

    ``group_key``（block 名派生的身份串 ``去码号block名#序号``）与名称识别无关 ——
    前置后同一 block 模板在各码内相对位置一致，顺序赋号天然跨码同号（前片-28 与
    前片-30 同 g 码），demand 键 ``(label, sizeKey)`` 的对应关系才稳定。组间顺序按
    group_key 字典序（确定性排序，非语义排序）；组内仍按上方 / 左 / 大片优先。
    """
    return (p.group_key,) + parse_member_sort_key(p)


def _piece_key(p):
    """裁片身份键 ``(block_name, size, piece_index)``（全文档唯一）。

    与 ``collect_pieces_with_details`` 内部的 ``(block_name_raw, piece_index)`` 唯一键
    同构（block_name 是 block_name_raw 的确定性解码）—— parse / commit 两次请求各自
    重新 collect 同一母版，同键可复现，是 parse↔intermediate label 对齐不变量
    （AC#5）的前提。
    """
    return (p.block_name, p.size, p.piece_index)


def collect_master_codes(pieces: Iterable) -> dict | None:
    """母版编号收集（all-or-nothing）。

    「有效片」= 全部 ``size != None`` 片（名称无关：不再要求任何 GROUP_NAMES 映射，
    未录入名称的组同样参与校验）。有效片**全部**带显式编号、且**每码内编号唯一** →
    返回 ``{_piece_key: code}``；任一片无编号或码内冲突 → 返回 None（整体回退顺序
    赋号，绝不混编 —— 半复用会让「同码不同片」的 UI 对应关系错乱）。

    唯一性按**码内**校验（非全档）：同一片型各码同号（前片-28 / 前片-30 都 g03）
    与全档逐片唯一两种版师习惯都放行 —— demand 键是 (label, sizeKey) 二元组，跨码
    同号天然合法。无有效片（空母版 / 全部 size=None）同样返回 None。
    """
    codes: dict = {}
    seen: dict[int, set] = defaultdict(set)
    for p in pieces:
        if p.size is None:
            continue
        code = master_code_from_block_name(p.block_name)
        if code is None:
            return None
        if code in seen[p.size]:
            return None
        seen[p.size].add(code)
        codes[_piece_key(p)] = code
    return codes or None


def assign_codes(pieces: Iterable) -> dict:
    """每码排序 + 裁片码分配（单一真相源：排序与编号决策只在此处）。

    返回 ``{size: [(piece, code), ...]}``（每码列表有序 = 展示顺序），消费方
    （``web/server.py._build_parse_payload`` / ``web/server.py._build_label_representatives``
    / ``_commit_to_nesting_sync``）迭代同一结构，跨端点同序同码：

    - 顺序模式（默认，``collect_master_codes`` 判 None）：码内 ``sequential_sort_key``
      排序（group_key 前置保证跨码同号，组内上方 / 左 / 大片优先），位置赋码 g01 起；
    - 母版复用模式（全部有效片带编号）：按母版码数值序输出（UI 列序 = 码序）；
      码内无编号片（仅 size=None 组，母版码不覆盖）续在最大母版码之后顺序补号，
      不与母版码冲突。
    """
    master = collect_master_codes(pieces)
    by_size: dict[int | None, list] = defaultdict(list)
    for p in pieces:
        by_size[p.size].append(p)

    out: dict[int | None, list] = {}
    for size, members in by_size.items():
        if master is None:
            ordered = sorted(members, key=sequential_sort_key)
            out[size] = [(p, label_for(i)) for i, p in enumerate(ordered)]
        else:
            coded: list = []    # [(piece, 母版码), ...]
            uncoded: list = []  # [piece, ...]（size=None 片，母版码未覆盖）
            for p in members:
                code = master.get(_piece_key(p))
                if code is not None:
                    coded.append((p, code))
                else:
                    uncoded.append(p)
            coded.sort(key=lambda pc: (code_sort_key(pc[1]), parse_member_sort_key(pc[0])))
            uncoded.sort(key=parse_member_sort_key)
            # 无编号片续在最大母版码之后顺序补号（label_for(next_num-1) = g{next_num}）
            next_num = max((code_sort_key(c) for _, c in coded), default=0) + 1
            out[size] = coded + [(p, label_for(next_num - 1 + i)) for i, p in enumerate(uncoded)]
    return out

"""US-022 共享：裁片 g01+ 编号标注 + (size, ptype) → label 映射。

供 ``web/server.py`` 的 parse-dxf 响应与 commit-to-nesting intermediate 共用，保证两条
管线对同一母版产出的 label 集合一致 —— 前端 ``qtyStore`` 以 label 为 key，后端
intermediate 的 label 必须与 parse 响应的 label 按 (size, ptype) 严格对齐，否则 demand
数量配错片型。

编号体系（2026-08-18 起统一为 g 码，取代旧 A/B/C 字母序号与片型中文名标定）：
  - 裁片码 = ``g`` + 两位零填充数字（g01/g02/...，>99 片自然升 g100）；
  - 默认顺序赋号：每码内独立从 g01 起（L/R 镜像副本共享同码，pid 的 ``_L/_R`` 后缀
    区分物理副本）；
  - 母版编号复用：母版 block 名带显式编号尾缀（如 ``前片g03.30`` → g03）时整体复用，
    all-or-nothing（见 ``collect_master_codes``），否则回退顺序赋号。

命名空间消歧：本模块的裁片码 g01.. 与 ``dxf_parser.export_dxf.GROUP_NAMES`` 的片型
组号键 g00..g09（g01=前片组）是**两个独立命名空间**（前者对外裁片标识、后者内部
gmap 键不上屏），代码中零比较点，仅人读 / grep 时注意区分。

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
      2. 再要求剩余部分以显式前缀编号结尾：``(?:g|G|#)(\\d{1,3})$`` → 规范化零填充
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
    """码内成员稳定排序键（parse 响应赋号 / label 对齐 / ptype 代表裁片共用）。

    ``(-centroid_y, centroid_x, -area_mm2, block_name, piece_index)`` —— 上方 / 左 /
    大片优先。三处消费方（``web/server.py._build_parse_payload``、本模块
    ``assign_codes``、``web/server.py._build_ptype_representatives``）必须同键：
    g 码编号、intermediate label 与高级配置代表裁片的对应关系才能跨端点一致
    （改任何一处须三处同步，故收敛为单一真相源）。
    """
    return (
        -centroid(p.polygon_mm)[1],
        centroid(p.polygon_mm)[0],
        -p.area_mm2,
        p.block_name,
        p.piece_index,
    )


def _piece_key(p):
    """裁片身份键 ``(block_name, size, piece_index)``（全文档唯一）。

    与 ``collect_pieces_with_details`` 内部的 ``(block_name_raw, piece_index)``
    唯一键同构（block_name 是 block_name_raw 的确定性解码）—— parse / commit
    两次请求各自重新 collect 同一母版，同键可复现，是 parse↔intermediate label
    对齐不变量（AC#5）的前提。
    """
    return (p.block_name, p.size, p.piece_index)


def collect_master_codes(pieces: Iterable, gmap: dict[str, str],
                         group_names: dict[str, str]) -> dict | None:
    """母版编号收集（all-or-nothing）。

    「有效片」（size 非 None 且 ptype 有 GROUP_NAMES 映射，即最终进入数量矩阵 /
    排料的片）**全部**带显式编号、且**每码内编号唯一** → 返回
    ``{_piece_key: code}``；任一片无编号或码内冲突 → 返回 None（整体回退顺序
    赋号，绝不混编 —— 半复用会让「同码不同片」的 UI 对应关系错乱）。

    唯一性按**码内**校验（非全档）：同一片型各码同号（前片-28 / 前片-30 都 g03）
    与全档逐片唯一两种版师习惯都放行 —— demand 键是 (label, sizeKey) 二元组，
    跨码同号天然合法。无有效片（空母版）同样返回 None。
    """
    codes: dict = {}
    seen: dict[int, set] = defaultdict(set)
    for p in pieces:
        if p.size is None:
            continue
        if group_names.get(gmap.get(p.group_key)) is None:
            continue
        code = master_code_from_block_name(p.block_name)
        if code is None:
            return None
        if code in seen[p.size]:
            return None
        seen[p.size].add(code)
        codes[_piece_key(p)] = code
    return codes or None


def assign_codes(pieces: Iterable, gmap: dict[str, str],
                 group_names: dict[str, str]) -> dict:
    """每码排序 + 裁片码分配（单一真相源：排序与编号决策只在此处）。

    返回 ``{size: [(piece, code), ...]}``（每码列表有序 = 展示顺序），三处消费方
    （``web/server.py._build_parse_payload`` / 本模块 ``compute_size_ptype_labels`` /
    ``web/server.py._build_ptype_representatives``）迭代同一结构，跨端点同序同码：

    - 顺序模式（默认，``collect_master_codes`` 判 None）：码内
      ``parse_member_sort_key`` 排序（上方 / 左 / 大片优先），位置赋码 g01 起；
    - 母版复用模式（全部有效片带编号）：按母版码数值序输出（UI 列序 = 码序）；
      码内无编号片（ptype 无映射等旁路片）续在最大母版码之后顺序补号，不与
      母版码冲突。size 为 None 的码组全部是旁路片，恒走顺序补号。

    同一 (size, ptype) 多 piece 时（M1787 实测 1:1，防御兜底）各自有码，
    ``compute_size_ptype_labels`` 取首片。
    """
    master = collect_master_codes(pieces, gmap, group_names)
    by_size: dict[int | None, list] = defaultdict(list)
    for p in pieces:
        by_size[p.size].append(p)

    out: dict[int | None, list] = {}
    for size, members in by_size.items():
        if master is None:
            ordered = sorted(members, key=parse_member_sort_key)
            out[size] = [(p, label_for(i)) for i, p in enumerate(ordered)]
        else:
            coded: list = []    # [(piece, 母版码), ...]
            uncoded: list = []  # [piece, ...]（旁路片：ptype 无映射等，母版码未覆盖）
            for p in members:
                code = master.get(_piece_key(p))
                if code is not None:
                    coded.append((p, code))
                else:
                    uncoded.append(p)
            coded.sort(key=lambda pc: (code_sort_key(pc[1]), parse_member_sort_key(pc[0])))
            uncoded.sort(key=parse_member_sort_key)
            # 旁路片续在最大母版码之后顺序补号（label_for(next_num-1) = g{next_num}）
            next_num = max((code_sort_key(c) for _, c in coded), default=0) + 1
            out[size] = coded + [(p, label_for(next_num - 1 + i)) for i, p in enumerate(uncoded)]
    return out


def compute_size_ptype_labels(
    pieces: Iterable,
    gmap: dict[str, str],
    group_names: dict[str, str],
) -> dict[tuple[int | None, str], str]:
    """对 ``explore.collect_pieces`` 返回的 PieceOutline 列表计算 (size, ptype) → label。

    内部走 ``assign_codes``（排序 + 编号单一真相源）→ parse 响应赋号、intermediate
    label、ptype 代表裁片三处同序同码。gmap / group_names 与
    ``dxf_parser.export_dxf.assign_group_no`` / ``GROUP_NAMES`` 同源 —— 同一
    (group_key → gno → ptype) 链路。

    返回 ``{(size, ptype): label}``；ptype 为 None（gno 无 GROUP_NAMES 映射）的 piece
    不入字典（与 commit 路径 skip 语义一致）。同一 (size, ptype) 多 piece 时取首片
    的 label（M1787 实测 1:1，此处兜底防御）。
    """
    out: dict[tuple[int | None, str], str] = {}
    for size, pairs in assign_codes(pieces, gmap, group_names).items():
        for p, code in pairs:
            ptype = group_names.get(gmap.get(p.group_key))
            if ptype is None:
                continue
            key = (size, ptype)
            if key not in out:  # 同 (size, ptype) 多 piece 时取首片 label
                out[key] = code
    return out

"""配置文件驱动的排料求解 · 配置加载与校验（CLI 第一道闸）。

``load_config(path)`` 读取 8 键 JSON 配置（示例 ``data/configs/5336_coded_sizes32-38.json``），
拼写 / 类型 / 路径 / 数值错误在管线启动前就地拦下（中文 ``ConfigError``，消息含字段名）。

8 键 schema（FR-1；除 seeds 外字段名与 WS StartPayload 契约 1:1）：

    master_dxf  str    必填。母版 DXF 路径：绝对直用；相对先按 CWD 再按仓库根
                       （paths.REPO_DIR）解析，均失败报错并列出两个候选绝对路径。
    sizes       list   可选。码号过滤（JSON 整数列表，非空）；缺省 = 不过滤（全部码号）。
    gate_mm     num    必填。门幅（mm，JSON 数字 >0）；intermediate 与密度分母口径。
    time        int    可选。单轮求解时长（秒，正整数），缺省 300。
    seeds       list   可选。串行种子列表：非负整数、不重复、非空，缺省 [0]。
                       **取代**旧 seed / multi_seed / seed_count 三字段 —— 无模式开关、
                       无 clamp [2,6] 语义，支持非连续种子（旧键按未知键报错）。
    per_type    dict   可选。{g码: {d?, tol?}} 逐 g 码覆盖：d=重合（mm）、tol=旋转公差
                       （°），值 JSON 数字 ≥0；超全局上限（MAX_OVERLAP_MM=10 /
                       MAX_ROTATION_TOL_DEG=45）不报错、warn 提示将被钳制。
    quantities  dict   可选。{g码: {码号: 数量}} per-size demand（语义与 web 一致：
                       label 命中但码号缺 → 0 跳过；label 不在 → 1）。码号键必须为
                       数字字符串或 'null'（求解按 str(size) 查 demand，JSON 数字键
                       查不到）；数量为 JSON 数字 ≥0 的整数（字符串 "1" 报错）。
    band        dict   可选。腰头成带 ``{'enabled': bool, 'label': g码}``（与 WS
                       StartPayload.band 1:1，web 策略入口前端直传）。enabled=false
                       或键缺省 = 关闭（BandConfig 字段恒 None）；enabled=true 时
                       label 须匹配 ``^g\\d+$``（routes_ws._BAND_LABEL_RE 同口径）。
                       label 是否存在于母版 / 该 g 码 quantities>0 不在本层校验
                       （config 加载期无 pieces 事实源）—— 求解期由
                       ``solve_worker._build_band`` fail-fast（「成带失败」error）。

本模块保持「纯校验」定位：模块级 import 仅标准库（无兄弟包 import、导入无副作用，
``python -m materialsorting.cli.config`` 直接运行零输出零副作用）；对 paths /
constraints 的依赖走函数内延迟 import，保持单一真相源不复制常量。
"""
from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

__all__ = ['ConfigError', 'NestRunConfig', 'load_config']

# 8 键 schema（FR-1）。旧 seed / multi_seed / seed_count 不在其中 → 按未知键报错。
TOP_LEVEL_KEYS = ('master_dxf', 'sizes', 'gate_mm', 'time', 'seeds', 'per_type',
                  'quantities', 'band')
# 必填键：CLI 无 web 的 intermediate 兜底（intermediate 本身由本配置生成）。
_REQUIRED_KEYS = ('master_dxf', 'gate_mm')
# 已退役的旧种子字段：未知键报错时附迁移提示（→ seeds 列表）。
_RETIRED_SEED_KEYS = ('seed', 'multi_seed', 'seed_count')
# g 码键形（与 labeling.assign_codes 产出一致：g01 / g10 / g100 …）。
_G_CODE_RE = re.compile(r'^g\d{1,3}$')
# quantities 码号键：数字字符串（如 "30"）或 'null'（size=None 片，与 solver 同口径）。
_SIZE_KEY_RE = re.compile(r'^[0-9]+$')
_NULL_SIZE_KEY = 'null'
# per_type 值对象仅接受的键（d=重合 mm / tol=旋转公差 °）。
_PER_TYPE_KEYS = ('d', 'tol')
# band.label 形（与 routes_ws._BAND_LABEL_RE 同口径：g + 任意位数字，如 g05/g105）。
_BAND_LABEL_RE = re.compile(r'^g\d+$')
# band 值对象仅接受的键（与 WS StartPayload.band / 前端 BandConfig 1:1）。
_BAND_KEYS = ('enabled', 'label')

_DEFAULT_TIME = 300          # 缺省单轮求解时长（秒）
_DEFAULT_SEEDS = (0,)        # 缺省种子列表


class ConfigError(ValueError):
    """配置校验失败（消息以「字段名: 中文说明」开头，含出错字段路径）。"""


def _fail(name: str, detail: str) -> NoReturn:
    raise ConfigError(f'{name}: {detail}')


def _repo_root() -> Path:
    """仓库根目录（= paths.REPO_DIR 单一真相源）。

    延迟 import 保持模块级仅标准库；paths 本身只算常量、无副作用。
    """
    from .. import paths
    return Path(paths.REPO_DIR)


def _global_caps() -> tuple[float, float]:
    """(MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG) 全局上限（constraints 单一真相源）。"""
    from ..nesting_engine.constraints import MAX_OVERLAP_MM, MAX_ROTATION_TOL_DEG
    return float(MAX_OVERLAP_MM), float(MAX_ROTATION_TOL_DEG)


def _resolve_master_dxf(name: str, raw: Any) -> Path:
    """master_dxf → 已存在的绝对路径（FR-2）。

    绝对路径直用；相对路径先试 CWD 再试仓库根（paths.REPO_DIR），均失败报错
    并列出两个候选绝对路径。
    """
    if not isinstance(raw, str) or not raw.strip():
        _fail(name, f'须为非空字符串路径，当前为 {raw!r}')
    p = Path(raw)
    if p.is_absolute():
        if p.is_file():
            return p.resolve()
        _fail(name, f'文件不存在: {p}')
    cwd_cand = (Path.cwd() / p).resolve()
    repo_cand = (_repo_root() / p).resolve()
    if cwd_cand.is_file():
        return cwd_cand
    if repo_cand.is_file():
        return repo_cand
    _fail(name, f'路径不存在（相对路径已尝试两个候选）① {cwd_cand} ② {repo_cand}')


def _check_sizes(name: str, raw: Any) -> list[int]:
    """sizes → 码号整数列表。空列表报错（build_instance 把 [] 视为不过滤，静默歧义）。"""
    if not isinstance(raw, list):
        _fail(name, f'须为码号 JSON 整数列表，当前为 {type(raw).__name__}: {raw!r}')
    if not raw:
        _fail(name, '不能为空列表（不需要码号过滤请删除该键 = 全部码号）')
    out = []
    for i, v in enumerate(raw):
        if isinstance(v, bool) or not isinstance(v, int):
            _fail(name, f'第 {i} 项 {v!r} 须为 JSON 整数（码号），不能是字符串/小数/布尔')
        out.append(int(v))
    return out


def _check_gate_mm(name: str, raw: Any) -> float:
    """gate_mm → 正数（mm）。"""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        _fail(name, f'须为 JSON 数字（mm），当前为 {raw!r}')
    v = float(raw)
    if v <= 0:
        _fail(name, f'须为正数（mm），当前为 {v}')
    return v


def _check_time(name: str, raw: Any) -> int:
    """time → 正整数（秒）。"""
    if isinstance(raw, bool) or not isinstance(raw, int):
        _fail(name, f'须为正整数（秒），当前为 {raw!r}')
    if raw <= 0:
        _fail(name, f'须为正整数（秒），当前为 {raw}')
    return int(raw)


def _check_seeds(name: str, raw: Any) -> list[int]:
    """seeds → 非负、不重复、非空的整数列表（缺省 [0]，旧三键已退役）。"""
    if not isinstance(raw, list):
        _fail(name, f'须为非负整数列表，当前为 {type(raw).__name__}: {raw!r}')
    if not raw:
        _fail(name, '不能为空列表（缺省 [0]；至少提供一个种子）')
    seen: set[int] = set()
    for i, v in enumerate(raw):
        if isinstance(v, bool) or not isinstance(v, int):
            _fail(name, f'第 {i} 项 {v!r} 须为非负整数（JSON 整数）')
        if v < 0:
            _fail(name, f'第 {i} 项 {v} 为负数，种子须为非负整数')
        if v in seen:
            _fail(name, f'含重复种子 {v}（同一随机种子重复求解无意义，请去重）')
        seen.add(v)
    return list(raw)


def _check_per_type(name: str, raw: Any) -> dict[str, dict[str, float]]:
    """per_type → {g码: {d?, tol?}}（值 JSON 数字 ≥0；超全局上限 warn 不报错）。"""
    if not isinstance(raw, dict):
        _fail(name, f'须为对象 {{g码: {{d?, tol?}}}}，当前为 {type(raw).__name__}: {raw!r}')
    max_d, max_tol = _global_caps()
    out: dict[str, dict[str, float]] = {}
    for key, over in raw.items():
        if not isinstance(key, str) or not _G_CODE_RE.match(key):
            _fail(name, f'键 {key!r} 不是合法 g 码（须匹配 g+1~3 位数字，如 g01/g10）')
        where = f'{name}.{key}'
        if not isinstance(over, dict):
            _fail(where, f'值须为对象 {{d?, tol?}}，当前为 {over!r}')
        unknown = [k for k in over if k not in _PER_TYPE_KEYS]
        if unknown:
            _fail(where, f'含未知键 {unknown[0]!r}（仅支持 d=重合 mm / tol=旋转公差 °）')
        vals: dict[str, float] = {}
        for k, v in over.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                _fail(where, f'{k} 须为 JSON 数字 ≥0，当前为 {v!r}')
            if v < 0:
                _fail(where, f'{k} 须为 ≥0，当前为 {v}')
            vals[k] = float(v)
        d = vals.get('d', 0.0)
        tol = vals.get('tol', 0.0)
        if d > max_d:
            warnings.warn(
                f'{where}.d = {d:g} 超过全局上限 MAX_OVERLAP_MM = {max_d:g}（mm），'
                f'求解时将被全局上限钳制到 {max_d:g}', stacklevel=3)
        if tol > max_tol:
            warnings.warn(
                f'{where}.tol = {tol:g} 超过全局上限 MAX_ROTATION_TOL_DEG = {max_tol:g}（°），'
                f'求解时将被全局上限钳制到 {max_tol:g}', stacklevel=3)
        out[key] = vals
    return out


def _check_quantities(name: str, raw: Any) -> dict[str, dict[str, int]]:
    """quantities → {g码: {码号: 数量}}（FR-3：码号键数字字符串或 'null'，数量 JSON 数字 ≥0）。"""
    if not isinstance(raw, dict):
        _fail(name, f'须为对象 {{g码: {{码号: 数量}}}}，当前为 {type(raw).__name__}: {raw!r}')
    out: dict[str, dict[str, int]] = {}
    for label, size_map in raw.items():
        if not isinstance(label, str) or not _G_CODE_RE.match(label):
            _fail(name, f'键 {label!r} 不是合法 g 码（须匹配 g+1~3 位数字，如 g01/g10）')
        where = f'{name}.{label}'
        if not isinstance(size_map, dict):
            _fail(where, f'值须为对象 {{码号: 数量}}，当前为 {size_map!r}')
        sizes: dict[str, int] = {}
        for sk, n in size_map.items():
            if not (isinstance(sk, str) and (_SIZE_KEY_RE.match(sk) or sk == _NULL_SIZE_KEY)):
                _fail(where, f'码号键 {sk!r} 须为数字字符串（如 "30"）或 "null"（求解按 '
                             f'str(size) 查 demand，非字符串键查不到）')
            if isinstance(n, bool) or not isinstance(n, (int, float)):
                _fail(where, f'码号 {sk!r} 的数量须为 JSON 数字 —— 应写 1 而非 "1"，当前为 {n!r}')
            if n < 0:
                _fail(where, f'码号 {sk!r} 的数量须为 ≥0，当前为 {n}')
            if isinstance(n, float) and not n.is_integer():
                _fail(where, f'码号 {sk!r} 的数量须为整数（份数），当前为 {n}')
            sizes[sk] = int(n)
        out[label] = sizes
    return out


def _check_band(name: str, raw: Any) -> dict | None:
    """band → ``{'enabled': True, 'label': g码}`` | None（显式关闭与缺省同线）。

    与 WS StartPayload.band 契约 1:1：``enabled=false`` → None（关闭，等价键缺省）；
    ``enabled=true`` 时 label 须为匹配 ``^g\\d+$`` 的字符串。label 存在性 /
    quantities>0 不在此层（config 加载期无 pieces 事实源）—— 求解期
    ``solve_worker._build_band`` fail-fast 兜底。
    """
    if not isinstance(raw, dict):
        _fail(name, f'须为对象 {{enabled, label}}，当前为 {type(raw).__name__}: {raw!r}')
    unknown = [k for k in raw if k not in _BAND_KEYS]
    if unknown:
        _fail(name, f'含未知键 {unknown[0]!r}（仅支持 enabled / label）')
    enabled = raw.get('enabled')
    if not isinstance(enabled, bool):
        _fail(f'{name}.enabled', f'须为 JSON 布尔，当前为 {enabled!r}')
    if not enabled:
        return None
    label = raw.get('label')
    if not isinstance(label, str) or not _BAND_LABEL_RE.match(label):
        _fail(f'{name}.label', f'须为 g 码字符串（如 "g05"，匹配 ^g\\d+$），当前为 {label!r}')
    return {'enabled': True, 'label': label}


@dataclass(frozen=True)
class NestRunConfig:
    """校验通过的排料运行配置（load_config 的产物，字段与 8 键 schema 一一对应）。"""

    master_dxf: Path                                        # 已解析为存在的绝对路径
    gate_mm: float                                          # 门幅 mm（>0）
    sizes: list[int] | None = None                          # None = 不过滤（全部码号）
    time: int = _DEFAULT_TIME                               # 单轮求解时长（秒）
    seeds: list[int] = field(default_factory=lambda: list(_DEFAULT_SEEDS))
    per_type: dict[str, dict[str, float]] = field(default_factory=dict)
    quantities: dict[str, dict[str, int]] | None = None     # None = 全片 demand=1
    band: dict | None = None        # None = 关闭；开启 = {'enabled': True, 'label': g码}


def load_config(path: str | Path) -> NestRunConfig:
    """读取并严格校验配置文件，返回 NestRunConfig；任何配置问题抛 ConfigError。"""
    cfg_path = Path(path)
    if not cfg_path.is_file():
        raise ConfigError(f'配置文件不存在: {cfg_path.resolve()}')
    try:
        raw = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError as e:
        raise ConfigError(
            f'配置文件不是合法 JSON（{cfg_path}）: 第 {e.lineno} 行第 {e.colno} 列 {e.msg}') from e
    if not isinstance(raw, dict):
        raise ConfigError(f'配置顶层须为 JSON 对象 {{...}}，当前为 {type(raw).__name__}')

    unknown = [k for k in raw if k not in TOP_LEVEL_KEYS]
    if unknown:
        retired = [k for k in unknown if k in _RETIRED_SEED_KEYS]
        hint = f'（旧字段 {"/".join(retired)} 已由 seeds 非负整数列表取代）' if retired else ''
        raise ConfigError(
            f'配置含未知顶层键: {", ".join(map(str, unknown))}{hint}；'
            f'合法键: {", ".join(TOP_LEVEL_KEYS)}')
    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        raise ConfigError(
            f'缺少必填键 {", ".join(missing)}（合法键: {", ".join(TOP_LEVEL_KEYS)}）')

    return NestRunConfig(
        master_dxf=_resolve_master_dxf('master_dxf', raw['master_dxf']),
        gate_mm=_check_gate_mm('gate_mm', raw['gate_mm']),
        sizes=_check_sizes('sizes', raw['sizes']) if 'sizes' in raw else None,
        time=_check_time('time', raw['time']) if 'time' in raw else _DEFAULT_TIME,
        seeds=_check_seeds('seeds', raw['seeds']) if 'seeds' in raw else list(_DEFAULT_SEEDS),
        per_type=_check_per_type('per_type', raw['per_type']) if 'per_type' in raw else {},
        quantities=(_check_quantities('quantities', raw['quantities'])
                    if 'quantities' in raw else None),
        band=_check_band('band', raw['band']) if 'band' in raw else None,
    )

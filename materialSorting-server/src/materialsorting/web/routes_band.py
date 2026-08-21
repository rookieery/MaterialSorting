r"""US-013 腰头成带预求解路由：``POST /api/band/preview``（FR-7）。

高级配置弹窗「布局设置」分区选定腰头 g 码后的预演回显 —— executor 线程跑
``waist_band.build_band_plan``（5s 预算），把实测 ``{fill_pct, bbox}`` 交前端对照
break-even 参考线（62.4~63.6%，实测口径出自 US-010 闸门报告：混带 72.5% 过线、
纯腰 54.8~60.9% 不过线）。

body 同 WS StartPayload 的 band 求解上下文子集::

    {"band": {"enabled": true, "label": "g05", "ack"?: true, "fillers"?: [...]},
     "sizes"?: [...], "seed"?: int, "per_type"?: {...}, "quantities"?: {...}}

US-015 起 ``band.fillers``（任意 g 码多选）随预演同口径混带（fill_pct 分子 =
腰 + 填料面积和）。

- 服务端校验复用 ``routes_ws._parse_band``（单一真相源：label ``^g\d+$`` / 存在于
  母版 / quantities>0 / 硬警告形态需 ack / US-015 fillers 全护栏）；
  ``time_budget`` 内部旋钮可缩短预算（测试用）；
- 不落 ``band_runs`` 工件（预演不是求解，US-014 回放对拍只收真实求解工件）；
- 响应口径：
  - 200 ``{ok:true, fill_pct, bbox, elapsed, break_even}`` —— 成带预演成功；
  - 200 ``{ok:false, error}`` —— **几何失败也是结果数据**（该 g 码不适合成带的量化
    证据，如 fill<45% / 总副本 1 / 解散落），前端降级提示不阻塞确认（FR-7）；
  - 400 / 409 / 422 ``{error}`` —— 结构错误（body 非 JSON / band 非法 / 数据为空 /
    其它校验失败）；硬警告形态的 422 附 ``hard_warning:true``（前端据此渲染二次
    确认勾选框，勾选后带 ``ack:true`` 重试）。

分层：本模块属 web 层，import ``.solver``（build_pid_meta / _resolve_d_tol —— 与
solve_worker._build_band 同口径）+ ``nesting_engine.waist_band``；不 import cli。
"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..nesting_bounds.load_pieces import PLOT_SAFE_MAX_Y_MM
from .runtime import _executor, _get_pieces_state
from .routes_ws import BandAckRequired, _parse_band

router = APIRouter()

# 预演预算（秒）：5s 够带内小实例（~14 片）fill 饱和（US-010 fill-预算曲线 5s 已近饱和）；
# 经 body band.time_budget 内部旋钮可覆盖（测试缩短用，非前端契约键）。
BAND_PREVIEW_TIME_BUDGET_S = 5
# break-even 参考线（%，实际占用 bbox 口径）：US-010 闸门实测混带/纯腰的分界。
BAND_BREAK_EVEN_PCT = (62.4, 63.6)


def _band_preview_sync(pieces_snapshot, gate_mm, solve_params, band_cfg):
    """executor 线程同步体：build_pid_meta + build_band_plan（与 _build_band 同口径）。

    d_g/tol_g 经 ``_resolve_d_tol`` 与主解同源裁定（FR-3 带内 per_type 沿用该 g 码
    d/tol；US-015 填料各 label 同法逐个裁定喂 ``filler_ds``）；带内约束带 =
    min(gate_mm, PLOT_SAFE_MAX_Y_MM)（与主解同口径）。几何失败（BandError 家族 /
    ValueError）向上抛 —— 路由层转 ``{ok:false, error}``（200）。
    """
    from ..nesting_engine.waist_band import build_band_plan
    from .solver import _resolve_d_tol, build_pid_meta

    label = str(band_cfg['label'])
    fillers = [str(f) for f in (band_cfg.get('fillers') or [])]
    t0 = time.time()
    pdef = {'d_ext': 0.0, 'd_int': 0.0, 'tol_ext': 0.0, 'tol_int': 0.0}
    pdef.update(solve_params.get('params') or {})
    d_g, tol_g = _resolve_d_tol(label, pdef, solve_params.get('per_type'))
    filler_ds = {}
    for f in fillers:
        filler_ds[f], _tol_f = _resolve_d_tol(f, pdef, solve_params.get('per_type'))
    pid_meta, _area, _n = build_pid_meta(
        pieces_snapshot,
        sizes=solve_params.get('sizes'),
        per_type=solve_params.get('per_type'),
        quantities=solve_params.get('quantities'),
        params=solve_params.get('params'))
    chunk = build_band_plan(
        pid_meta, {p['pid']: p for p in pieces_snapshot},
        label=label,
        seed=int(solve_params.get('seed', 0)),
        gate_nest=min(float(gate_mm), PLOT_SAFE_MAX_Y_MM),
        d_g=d_g, tol_g=tol_g,
        fillers=fillers, filler_ds=filler_ds,
        time_budget=int(band_cfg.get('time_budget') or BAND_PREVIEW_TIME_BUDGET_S))
    return {
        'ok': True,
        'fill_pct': round(float(chunk.fill_pct), 2),
        'bbox': {'width_mm': float(chunk.bbox['width_mm']),
                 'height_mm': float(chunk.bbox['height_mm'])},
        'elapsed': round(time.time() - t0, 2),
        'break_even': list(BAND_BREAK_EVEN_PCT),
    }


@router.post('/api/band/preview')
async def band_preview(req: Request):
    """腰头成带预演（US-013 AC#2）：5s 预算 build_band_plan → fill/bbox 回显。"""
    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({'error': '请求体须为 JSON'}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({'error': '请求体须为 JSON 对象'}, status_code=400)

    raw_band = payload.get('band')
    if not isinstance(raw_band, dict) or not raw_band.get('enabled'):
        return JSONResponse({'error': 'band 须为 {enabled:true, label, ack?}'}, status_code=400)

    state = _get_pieces_state()
    pieces = state.get('pieces') or []
    gate_mm = state.get('gate_mm') or 0.0
    if not pieces or gate_mm <= 0:
        return JSONResponse(
            {'error': '排料数据为空（请先上传解析母版并 commit）'}, status_code=409)

    quantities = payload.get('quantities')
    if not isinstance(quantities, dict):
        quantities = None
    try:
        band_cfg = _parse_band(raw_band, pieces, quantities)
    except BandAckRequired as e:
        # 硬警告形态：结构化标记 → 前端弹窗渲染二次确认勾选框后带 ack:true 重试
        # （FR-1「ack 仅 US-013 确认弹窗显式置 true」的落地点）。
        return JSONResponse({'error': str(e), 'hard_warning': True}, status_code=422)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=422)

    solve_params = {
        'sizes': payload.get('sizes') or [],
        'seed': payload.get('seed') or 0,
        'per_type': payload.get('per_type') or None,
        'quantities': quantities,
        'params': payload.get('params') or None,
    }
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _executor, _band_preview_sync,
            [dict(p) for p in pieces], float(gate_mm), solve_params, band_cfg)
    except Exception as e:            # noqa: BLE001 几何失败 = 结果数据（ok:false 降级，不阻塞确认）
        return {'ok': False, 'error': f'预演失败: {e}'}
    return result

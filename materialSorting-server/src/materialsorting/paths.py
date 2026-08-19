"""集中路径常量。

优先读环境变量，默认相对本包位置上溯定位 repo 根。层级：
    src/materialsorting/  →  src/  →  materialSorting-server/  →  MaterialSorting/(repo 根)

可覆盖的环境变量：
    MS_DATA_DIR    原始数据目录（母版 DXF）
    MS_OUT_DIR     运行产物目录（intermediate / SVG / PNG / 曲线）
    MS_STATIC_DIR  前端静态文件目录（FastAPI mount 用）

子目录约定：
    sparrow_baseline/  web 事实源（pieces_intermediate.json，web commit 独占写）
    uploads/           web 上传母版 + 切片目录（web 独占写）
    config_runs/      CLI（ms-run-config）专属产物根 —— cli 子包唯一可写目录，
                       **禁止**写 INTERMEDIATE / uploads（web 事实源物理隔离）
    portfolio_calibration/  PC-004 标定管线产物根（cli.calibration batch/variants/
                       analyze 的曲线与参数；gitignore 区，与 config_runs 平级）
"""
import os

_PKG = os.path.dirname(os.path.abspath(__file__))                 # .../src/materialsorting
_SERVER = os.path.dirname(os.path.dirname(_PKG))                  # .../materialSorting-server
REPO_DIR = os.path.dirname(_SERVER)                               # .../MaterialSorting

DATA_DIR = os.environ.get('MS_DATA_DIR', os.path.join(REPO_DIR, 'data'))
OUT_DIR = os.environ.get('MS_OUT_DIR', os.path.join(_SERVER, 'out'))
SPARROW_DIR = os.path.join(OUT_DIR, 'sparrow_baseline')           # 与原 _output/sparrow_baseline/ 子目录约定一致
INTERMEDIATE = os.path.join(SPARROW_DIR, 'pieces_intermediate.json')   # 全流程事实源（文件全路径）
CONFIG_RUNS_DIR = os.path.join(OUT_DIR, 'config_runs')     # CLI（ms-run-config）专属产物根：只此可写，禁写 INTERMEDIATE/uploads
CALIBRATION_DIR = os.path.join(OUT_DIR, 'portfolio_calibration')   # PC-004 标定管线产物根（batch/variants/analyze，gitignore 区）
MASTER_DXF_GLOB = os.path.join(DATA_DIR, 'M1787*(2).dxf')         # 母版 DXF glob（命中的是 2.9MB 的 (1)(2)）
STATIC_DIR = os.environ.get('MS_STATIC_DIR',
                            os.path.join(REPO_DIR, 'materialSorting-web', 'static'))

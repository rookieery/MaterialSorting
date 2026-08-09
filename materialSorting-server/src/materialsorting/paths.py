"""集中路径常量。

优先读环境变量，默认相对本包位置上溯定位 repo 根。层级：
    src/materialsorting/  →  src/  →  materialSorting-server/  →  MaterialSorting/(repo 根)

可覆盖的环境变量：
    MS_DATA_DIR    原始数据目录（母版 DXF + 单裁片）
    MS_OUT_DIR     运行产物目录（intermediate / SVG / PNG / 曲线）
    MS_STATIC_DIR  前端静态文件目录（FastAPI mount 用）
"""
import os

_PKG = os.path.dirname(os.path.abspath(__file__))                 # .../src/materialsorting
_SERVER = os.path.dirname(os.path.dirname(_PKG))                  # .../materialSorting-server
REPO_DIR = os.path.dirname(_SERVER)                               # .../MaterialSorting

DATA_DIR = os.environ.get('MS_DATA_DIR', os.path.join(REPO_DIR, 'data'))
OUT_DIR = os.environ.get('MS_OUT_DIR', os.path.join(_SERVER, 'out'))
SPARROW_DIR = os.path.join(OUT_DIR, 'sparrow_baseline')           # 与原 _output/sparrow_baseline/ 子目录约定一致
PIECES_DIR = os.path.join(DATA_DIR, 'm1787_直筒')                 # 110 个单裁片 DXF
INTERMEDIATE = os.path.join(SPARROW_DIR, 'pieces_intermediate.json')   # 全流程事实源（文件全路径）
MASTER_DXF_GLOB = os.path.join(DATA_DIR, 'M1787*(2).dxf')         # 母版 DXF glob（命中的是 2.9MB 的 (1)(2)）
STATIC_DIR = os.environ.get('MS_STATIC_DIR',
                            os.path.join(REPO_DIR, 'materialSorting-web', 'static'))

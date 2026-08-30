# 单线矢量字资源（PLT 唛架信息表格，2026-08-30）

生产 PLT（ET2008 等）的文字为**单线矢量字**（一笔单线、非轮廓空心），为对拍
生产观感，表格文字改用单线字渲染，缺字回退 Noto Sans SC 轮廓。

| 文件 | 内容 | 许可 |
|---|---|---|
| `hanzi_medians.txt` | 汉字笔画中线（9575 字，em=1024、y 向上） | Arphic Public License（`ARPHICPL.txt`）|
| `hershey_rowmans.txt` | Hershey Roman Simplex ASCII 单线体（92 字符，生产 PLT ASCII 同款风格）。**文件保留 JHF 原始坐标口径：y 自字顶向下增长（y=0 = cap 顶、'H' 竖笔底 = 基线），引擎加载期整体翻 y 到基线=0**（不翻则 ASCII 逐字垂直镜像） | Usenet Hershey 许可（`HERSHEY-LICENSE.txt`，任意用途可用、须随数据附致谢） |
| `NotoSansSC-Regular.otf` | 轮廓回退字体 | SIL OFL 1.1（`OFL.txt`） |

出处：
- hanzi_medians.txt 由 `hanzi-writer-data@2.0.1`（Make Me a Hanzi per-char 分发）
  的 `medians` 字段生成（构建脚本 `out/plt_analysis/build_stroke_fonts.py`）。
- hershey_rowmans.txt 由 npm `hershey@2.1.7` 捆绑的 `rowmans.jhf` 生成。

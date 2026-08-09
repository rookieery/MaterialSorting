"""排料专属 DXF 解析包。

独立于项目内打板模块（tools/、front_piece/、back_piece/），不 import 任何外部解析代码。
第一阶段：从全码母版 DXF 忠实提取所有裁片(layer1 毛版闭合多边形)，按 group_key 分组输出。
"""

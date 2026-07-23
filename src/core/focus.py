"""AF 对焦点解析器。

该模块已弃用。ORF 等 RAW 格式通常不写入完整 AF 点坐标，且对焦点评分
无法稳定跨相机品牌工作。画质评分已改为不依赖 EXIF 的 4 维指标。
保留此文件和空类，避免已有代码因 import 失败而报错。
"""

from typing import List, Tuple


class FocusParser:
    """历史占位类，不再实际解析对焦点。"""

    def __init__(self, exiftool_path: str = "exiftool"):
        self.exiftool_path = exiftool_path

    def parse_af_points(self, image_path: str) -> List[Tuple[int, int]]:
        """返回空列表，表示不解析 AF 对焦点。"""
        return []

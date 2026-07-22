import logging
import json
import re
import subprocess
from pathlib import Path
from typing import List, Tuple


class FocusParser:
    """解析相机 EXIF 中的自动对焦点信息。

    优先使用 ExifTool 读取 Olympus/OM System 专用 AF 标签(适用于 ORF 文件),
    其次回退到通用厂商标签(Canon/Nikon 等)。当没有 AF 信息时返回空列表,
    不再进行画面中心兜底。

    Olympus AF 标签说明:
    - ``AFPointSelected``: 选中对焦点,百分比坐标 "x y"(0-100)
    - ``AFSelectedArea``: 选中对焦区域,像素坐标 "x y w h"
    - ``AFFocusArea``: 对焦区域,像素坐标
    - ``AFFrameSize``: AF 框尺寸 "w h",用于百分比换算
    - ``SubjectDetectArea``: 主体检测区域(较新机型),像素或百分比坐标
    """

    def __init__(self, exiftool_path: str = "exiftool"):
        self.exiftool_path = exiftool_path

    def parse_af_points(self, image_path: str) -> List[Tuple[int, int]]:
        """从图像 EXIF 读取 AF 对焦点,返回 [(x, y), ...] 的像素坐标列表。

        无 AF 信息时返回空列表,不进行兜底。
        """
        path = Path(image_path)
        if not path.exists():
            return []

        metadata = self._read_metadata(path)
        if not metadata:
            return []

        img_w, img_h = self._read_image_dimensions(metadata)

        points = self._parse_olympus_pixel_tags(metadata)
        if not points:
            points = self._parse_olympus_percent_tags(metadata, img_w, img_h)
        if not points:
            points = self._parse_generic_af_tags(metadata)

        return points

    def _read_metadata(self, path: Path) -> dict:
        """调用 ExifTool 读取 AF 与图像尺寸相关标签。"""
        try:
            result = subprocess.run(
                [
                    self.exiftool_path,
                    "-j",
                    "-G1",
                    "-Olympus:AFPointSelected",
                    "-Olympus:AFSelectedArea",
                    "-Olympus:AFFocusArea",
                    "-Olympus:AFFrameSize",
                    "-Olympus:SubjectDetectArea",
                    "-Olympus:AFPoint",
                    "-AFPoint",
                    "-AFPointsInFocus",
                    "-AFAreaMode",
                    "-ExifImageWidth",
                    "-ExifImageHeight",
                    "-ImageWidth",
                    "-ImageHeight",
                    "-ExifImageSize",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logging.warning(f"ExifTool failed for {path}: {e}")
            return {}

        if result.returncode != 0:
            return {}

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}

        if not data:
            return {}

        return data[0]

    def _read_image_dimensions(self, metadata: dict) -> Tuple[int, int]:
        """从 EXIF 读取图像宽高,用于百分比坐标换算。"""
        for key in ("ExifImageWidth", "ImageWidth"):
            w = metadata.get(key)
            if isinstance(w, (int, float)) and w > 0:
                break
            w = None
        for key in ("ExifImageHeight", "ImageHeight"):
            h = metadata.get(key)
            if isinstance(h, (int, float)) and h > 0:
                break
            h = None

        # ExifImageSize 形如 "4000x3000"
        size = metadata.get("ExifImageSize")
        if isinstance(size, str) and "x" in size:
            parts = size.lower().split("x")
            if len(parts) == 2:
                try:
                    return int(parts[0]), int(parts[1])
                except ValueError:
                    pass

        if w and h:
            return int(w), int(h)
        return 0, 0

    @staticmethod
    def _extract_numbers(value: str) -> List[int]:
        """从字符串中提取所有整数。"""
        return [int(n) for n in re.findall(r"-?\d+", value)]

    def _parse_olympus_pixel_tags(self, metadata: dict) -> List[Tuple[int, int]]:
        """解析 Olympus 像素坐标 AF 标签(AFSelectedArea / AFFocusArea)。"""
        points: List[Tuple[int, int]] = []
        for key in ("Olympus:AFSelectedArea", "Olympus:AFFocusArea", "Olympus:AFPoint"):
            value = metadata.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            nums = self._extract_numbers(value)
            # "x y w h" 或 "x y"
            if len(nums) >= 2:
                points.append((nums[0], nums[1]))
        return points

    def _parse_olympus_percent_tags(
        self, metadata: dict, img_w: int, img_h: int
    ) -> List[Tuple[int, int]]:
        """解析 Olympus 百分比 AF 标签(AFPointSelected / SubjectDetectArea)。

        百分比坐标需要图像尺寸换算为像素;无尺寸信息时跳过。
        """
        if img_w <= 0 or img_h <= 0:
            return []

        points: List[Tuple[int, int]] = []
        for key in ("Olympus:AFPointSelected", "Olympus:SubjectDetectArea"):
            value = metadata.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            nums = self._extract_numbers(value)
            if len(nums) >= 2:
                # 百分比 0-100 → 像素
                px = int(round(nums[0] / 100.0 * img_w))
                py = int(round(nums[1] / 100.0 * img_h))
                points.append((px, py))
        return points

    def _parse_generic_af_tags(self, metadata: dict) -> List[Tuple[int, int]]:
        """解析通用厂商 AF 标签(AFPointsInFocus / AFPoint)。

        适用于 Canon/Nikon 等,格式常见为 "(900, 600)" 或 "Center"。
        """
        points: List[Tuple[int, int]] = []

        af_points_in_focus = metadata.get("AFPointsInFocus", "")
        if isinstance(af_points_in_focus, str) and af_points_in_focus.strip():
            pts = self._parse_coord_string(af_points_in_focus)
            points.extend(pts)

        if not points:
            af_point = metadata.get("AFPoint", "")
            if isinstance(af_point, str) and af_point.strip():
                points.extend(self._parse_coord_string(af_point))

        return points

    @classmethod
    def _parse_coord_string(cls, value: str) -> List[Tuple[int, int]]:
        """从形如 '(900, 600)' 或 '900 600' 的字符串解析坐标点。"""
        nums = cls._extract_numbers(value)
        if len(nums) >= 2:
            return [(nums[0], nums[1])]
        return []

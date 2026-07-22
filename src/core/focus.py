from typing import List, Tuple
from pathlib import Path
import json
import subprocess


class FocusParser:
    """解析相机 EXIF 中的自动对焦点信息，并支持回退到画面中心点。

    当前实现优先使用 ExifTool 读取常见厂商的 AFPoint 信息；如果读取失败或
    没有相关信息，则回退到画面中心作为默认对焦点。
    """

    def __init__(self, exiftool_path: str = "exiftool"):
        self.exiftool_path = exiftool_path

    def parse_af_points(self, image_path: str) -> List[Tuple[int, int]]:
        """从图像 EXIF 读取 AF 对焦点，返回 [(x, y), ...] 的像素坐标列表。"""
        path = Path(image_path)
        if not path.exists():
            return []

        try:
            result = subprocess.run(
                [self.exiftool_path, "-j", "-AFPoint", "-AFPointsInFocus", "-AFAreaMode", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []

            data = json.loads(result.stdout)
            if not data:
                return []

            metadata = data[0]
            points = []

            # 优先尝试读取 AFPointsInFocus
            af_points_in_focus = metadata.get("AFPointsInFocus", "")
            if isinstance(af_points_in_focus, str) and af_points_in_focus.strip():
                # 常见格式："(900, 600)" 或 "Center" 等
                parts = af_points_in_focus.split(",")
                if len(parts) >= 2:
                    try:
                        x = int("".join(c for c in parts[0] if c.isdigit() or c == "-"))
                        y = int("".join(c for c in parts[1] if c.isdigit() or c == "-"))
                        points.append((x, y))
                    except ValueError:
                        pass

            # 其次尝试读取 AFPoint
            af_point = metadata.get("AFPoint", "")
            if isinstance(af_point, str) and af_point.strip() and not points:
                parts = af_point.split(",")
                if len(parts) >= 2:
                    try:
                        x = int("".join(c for c in parts[0] if c.isdigit() or c == "-"))
                        y = int("".join(c for c in parts[1] if c.isdigit() or c == "-"))
                        points.append((x, y))
                    except ValueError:
                        pass

            return points
        except Exception:
            return []

    @staticmethod
    def get_fallback_points(image_width: int, image_height: int) -> List[Tuple[int, int]]:
        """当 EXIF 没有 AF 点时，回退到画面中心。"""
        return [(image_width // 2, image_height // 2)]

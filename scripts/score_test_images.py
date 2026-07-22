"""对测试文件夹中的 ORF 照片进行 7 维画质评分（使用真实检测框）。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import rawpy
import numpy as np

from src.core.detector import BirdDetector
from src.core.quality import QualityScorer
from src.core.pose import PoseDetector
from src.core.focus import FocusParser
from src.core.processor import ImageProcessor
from src.utils.config_loader import load_config

TEST_DIR = Path(r"D:\照片\2026\testdata")
YOLO_MODEL = PROJECT_ROOT / "data" / "models" / "yolo26n.pt"


def decode_orf(path: Path) -> np.ndarray:
    """解码 ORF 为 RGB numpy 数组。"""
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            output_bps=8,
            use_camera_wb=True,
            half_size=True,
        )
    return rgb


def main():
    config = load_config("config/settings.yaml")
    scorer = QualityScorer(
        weights=config.get("quality", {}).get("weights"),
        pose_upgrade_threshold=config.get("quality", {}).get("pose_upgrade_threshold"),
    )
    pose = PoseDetector()
    focus = FocusParser()

    detector = BirdDetector(str(YOLO_MODEL), confidence=0.3, device="auto")

    orf_files = sorted(set(TEST_DIR.glob("*.ORF")) | set(TEST_DIR.glob("*.orf")))
    if not orf_files:
        print(f"未找到 ORF 文件: {TEST_DIR}")
        return

    print(f"测试照片: {len(orf_files)} 张\n")
    print(f"{'文件名':<20} {'总分':<6} {'clarity':<8} {'contrast':<8} {'position':<8} {'exposure':<8} {'pose':<6} {'bif':<6} {'focus':<6}")
    print("-" * 90)

    for orf_path in orf_files:
        img = decode_orf(orf_path)
        h, w = img.shape[:2]

        # 临时 JPG 供检测器使用
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_jpg = tmp.name

        from PIL import Image
        Image.fromarray(img).save(tmp_jpg, quality=95)

        boxes = detector.detect(tmp_jpg)
        os.unlink(tmp_jpg)

        if not boxes:
            print(f"{orf_path.name:<20} {'N/A':<6} 未检测到鸟")
            continue

        best_box, best_conf = max(boxes, key=lambda b: b[1])
        x, y, x2, y2 = map(int, best_box)
        bw, bh = x2 - x, y2 - y
        bbox = (x, y, bw, bh)

        visibility = pose.detect_visibility(img, bbox)
        flight_prob = pose.is_flying(img, bbox)
        focus_points = focus.parse_af_points(str(orf_path))
        if not focus_points:
            focus_points = FocusParser.get_fallback_points(w, h)

        result = scorer.calculate_quality_score(img, bbox, visibility, focus_points, flight_prob)
        score = result["score"]
        d = result["details"]

        print(
            f"{orf_path.name:<20} {score:<6} "
            f"{d['clarity']:<8.3f} {d['contrast']:<8.3f} {d['position']:<8.3f} "
            f"{d['exposure']:<8.3f} {d['pose']:<6.3f} {d['bif']:<6.3f} {d['focus']:<6.3f}"
        )


if __name__ == "__main__":
    main()

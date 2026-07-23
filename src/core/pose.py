from typing import Dict
import numpy as np


class PoseDetector:
    """基于鸟框计算主体在画面中的占比。

    该模块不再尝试推断头/眼/身/尾/翼等姿态可见性，而是返回一个
    ``subject_size`` 分数，表示鸟类 bbox 占整幅画面的比例。占比越大
    说明鸟在画面中越近、越突出，有利于后期识别和选片。
    """

    def detect_visibility(self, image: np.ndarray, bird_bbox: tuple) -> Dict[str, float]:
        """返回主体占比分数。

        为了与旧接口兼容，仍返回 dict，但只含 ``subject_size`` 一个键。
        分数 = bbox 面积 / 图像面积，限制在 [0, 1]。
        """
        img_h, img_w = image.shape[:2]
        x, y, bw, bh = bird_bbox

        if img_w <= 0 or img_h <= 0 or bw <= 0 or bh <= 0:
            return {"subject_size": 0.0}

        bbox_area = bw * bh
        image_area = img_w * img_h
        ratio = min(bbox_area / max(image_area, 1), 1.0)
        return {"subject_size": ratio}

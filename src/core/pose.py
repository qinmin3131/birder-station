from typing import Dict
import numpy as np


class PoseDetector:
    """基于鸟框几何特征推断姿态可见度和飞版概率。

    当前实现不使用深度学习模型，而是根据鸟框的宽高比、位置、图像上半部
    亮度占比等启发式规则推断：
    - 正方形/接近正方的框 -> 正面/侧面，头眼可见度更高
    - 水平细长框 -> 飞版概率高，翅膀可见度高
    - 框越靠图像上半部 -> 飞版概率越高
    """

    def detect_visibility(self, image: np.ndarray, bird_bbox: tuple) -> Dict[str, float]:
        x, y, bw, bh = bird_bbox
        img_h, img_w = image.shape[:2]
        if bw <= 0 or bh <= 0 or img_w <= 0 or img_h <= 0:
            return {
                "head": 1.0,
                "eye": 1.0,
                "body": 1.0,
                "tail": 1.0,
                "wing": 1.0,
            }

        aspect_ratio = bw / max(bh, 1)
        box_area = bw * bh
        image_area = img_w * img_h
        fill_ratio = min(box_area / max(image_area, 1), 1.0)

        # 默认全身可见
        body = 0.8 + 0.2 * fill_ratio
        head = 1.0
        eye = 1.0
        tail = 1.0
        wing = 0.7

        if aspect_ratio > 1.5:
            # 水平伸展，可能是飞版，翅膀、尾羽可见，但头部可能较小
            wing = 0.9 + 0.1 * fill_ratio
            tail = 0.85 + 0.15 * fill_ratio
            head = 0.8
            eye = 0.75
        elif aspect_ratio < 0.6:
            # 垂直站立，头/眼/身清楚，翅膀收拢
            wing = 0.5
            tail = 0.8
            head = 1.0
            eye = 1.0
        else:
            # 正面或侧面，头眼清楚，翅膀部分可见
            wing = 0.6 + 0.2 * fill_ratio

        return {
            "head": min(1.0, head),
            "eye": min(1.0, eye),
            "body": min(1.0, body),
            "tail": min(1.0, tail),
            "wing": min(1.0, wing),
        }

    def is_flying(self, image: np.ndarray, bird_bbox: tuple) -> float:
        x, y, bw, bh = bird_bbox
        img_h, img_w = image.shape[:2]
        if bw <= 0 or bh <= 0 or img_w <= 0 or img_h <= 0:
            return 0.0

        aspect_ratio = bw / max(bh, 1)
        box_center_y = y + bh / 2.0
        upper_ratio = (img_h - box_center_y) / max(img_h, 1)

        # 水平长条 + 位于画面上半部 = 更可能是飞版
        flight_prob = 0.0
        if aspect_ratio > 1.3:
            flight_prob += 0.35
        if aspect_ratio > 2.0:
            flight_prob += 0.25
        if upper_ratio > 0.6:
            flight_prob += 0.25

        return min(1.0, flight_prob)

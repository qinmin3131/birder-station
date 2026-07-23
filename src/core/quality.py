import cv2
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple


class QualityChecker:
    """Legacy blur-only quality checker.

    保留用于向后兼容旧的 pipeline_runner 与已有测试。新代码应使用
    ``QualityScorer`` 获取多维加权评分。
    """

    @staticmethod
    def calculate_blur_score(image_path: str) -> float:
        """
        Calculate the sharpness score using the Variance of Laplacian method.
        Higher score means sharper image.
        """
        try:
            image = cv2.imread(image_path)
            if image is None:
                logging.error(f"Could not read image for quality check: {image_path}")
                return 0.0

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            score = cv2.Laplacian(gray, cv2.CV_64F).var()
            return score
        except Exception as e:
            logging.error(f"Error calculating blur score: {e}")
            return 0.0

    @staticmethod
    def is_sharp(image_path: str, threshold: float = 80.0) -> bool:
        """Check if the image is sharp enough based on a threshold."""
        score = QualityChecker.calculate_blur_score(image_path)
        return score >= threshold


class QualityScorer:
    """6 维加权画质评分器。

    维度权重按 spec.md §3.2 定义,可通过构造函数注入来自 ``config/settings.yaml``
    的 ``quality.weights`` 自定义。各维度返回 0-1 的归一化分数,综合分数为 0-100
    的整数。

    注: 原飞版加分 (bif) 维度已移除,其权重重新分配至 clarity 与 focus。
    """

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "clarity": 0.30,
        "contrast": 0.10,
        "position": 0.10,
        "exposure": 0.10,
        "subject_size": 0.20,
        "focus": 0.20,
    }

    DEFAULT_EMPTY_FOCUS_SCORE = 0.5
    _CLARITY_NORMALIZER = 500.0
    _CONTRAST_NORMALIZER = 80.0

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        subject_size_upgrade_threshold: Optional[Dict] = None,
    ):
        self.weights = dict(self.DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)

    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray:
        if image.ndim == 3:
            return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        return image

    def calculate_clarity(self, image: np.ndarray) -> float:
        """Laplacian 方差归一化到 0-1,越高越清晰。"""
        gray = self._to_gray(image)
        variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        return min(variance / self._CLARITY_NORMALIZER, 1.0)

    def calculate_contrast(self, image: np.ndarray) -> float:
        """灰度标准差归一化到 0-1,越高对比越强。"""
        gray = self._to_gray(image)
        std = float(gray.std())
        return min(std / self._CONTRAST_NORMALIZER, 1.0)

    def calculate_position(
        self,
        image_shape: Tuple[int, ...],
        bird_bbox: Tuple[int, int, int, int],
    ) -> float:
        """主体中心越靠近画面中心得分越高,归一化到 0-1。"""
        h, w = image_shape[:2]
        if w == 0 or h == 0:
            return 0.0
        x, y, bw, bh = bird_bbox
        cx, cy = x + bw / 2.0, y + bh / 2.0
        center_dist = ((cx - w / 2.0) ** 2 + (cy - h / 2.0) ** 2) ** 0.5
        max_dist = ((w ** 2 + h ** 2) ** 0.5) / 2.0
        if max_dist == 0:
            return 0.0
        return max(0.0, 1.0 - center_dist / max_dist)

    def calculate_subject_size_score(self, image_shape: Tuple[int, ...], bird_bbox: Tuple[int, int, int, int]) -> float:
        """鸟占画面的比例，越大说明鸟越近/越突出，归一化到 0-1。"""
        h, w = image_shape[:2]
        if w <= 0 or h <= 0:
            return 0.0
        x, y, bw, bh = bird_bbox
        if bw <= 0 or bh <= 0:
            return 0.0
        image_area = w * h
        if image_area == 0:
            return 0.0
        return min((bw * bh) / image_area, 1.0)

    def calculate_exposure(self, image: np.ndarray) -> float:
        """直方图相对中间灰度的偏离度,越居中得分越高,归一化到 0-1。"""
        gray = self._to_gray(image)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        total = float(hist.sum())
        if total == 0:
            return 0.0
        normalized = hist / total
        deviation = float(
            np.sum(normalized * np.abs(np.arange(256) - 127) / 127.0)
        )
        return max(0.0, 1.0 - deviation)

    def calculate_pose_score(self, visibility: Dict[str, float]) -> float:
        """头/眼/身/尾/翼可见度均值,归一化到 0-1。"""
        if not visibility:
            return 0.0
        values = [float(v) for v in visibility.values()]
        return sum(values) / len(values)

    def calculate_focus_score(
        self,
        focus_points: List[Tuple[int, int]],
        bird_bbox: Tuple[int, int, int, int],
    ) -> float:
        """AF 对焦点落在鸟框内的比例。无对焦点时返回默认中性分。"""
        if not focus_points:
            return self.DEFAULT_EMPTY_FOCUS_SCORE
        x, y, bw, bh = bird_bbox
        inside = sum(
            1 for px, py in focus_points
            if x <= px <= x + bw and y <= py <= y + bh
        )
        return inside / len(focus_points)

    def calculate_quality_score(
        self,
        image: np.ndarray,
        bird_bbox: Tuple[int, int, int, int],
        visibility: Dict[str, float],
        focus_points: List[Tuple[int, int]],
    ) -> Dict:
        """计算 6 维加权综合画质评分。

        Returns:
            ``{"score": int 0-100, "details": {dim: float 0-1, ...}}``
        """
        details = {
            "clarity": self.calculate_clarity(image),
            "contrast": self.calculate_contrast(image),
            "position": self.calculate_position(image.shape, bird_bbox),
            "exposure": self.calculate_exposure(image),
            "subject_size": self.calculate_subject_size_score(image.shape, bird_bbox),
            "focus": self.calculate_focus_score(focus_points, bird_bbox),
        }
        weighted = sum(details[dim] * self.weights[dim] for dim in self.weights)
        return {"score": int(round(weighted * 100)), "details": details}

    def score_from_path(self, image_path: str, bird_bbox: Tuple[int, int, int, int]) -> Dict:
        """从图像路径和鸟框计算 6 维画质评分。

        自动调用 FocusParser 获取焦点信息,主体占比由鸟框与画面面积比计算。
        无 AF 对焦点时不进行中心兜底,focus 维度返回中性分。
        """
        from .focus import FocusParser

        image = cv2.imread(image_path)
        if image is None:
            logging.error(f"Could not read image for quality scoring: {image_path}")
            return {"score": 0, "details": {dim: 0.0 for dim in self.DEFAULT_WEIGHTS}}

        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        focus_parser = FocusParser()

        visibility = {"subject_size": self.calculate_subject_size_score(image.shape, bird_bbox)}
        focus_points = focus_parser.parse_af_points(image_path)

        return self.calculate_quality_score(image, bird_bbox, visibility, focus_points)

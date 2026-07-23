import cv2
import logging
import numpy as np
from typing import Dict, Optional, Tuple


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
    """5 维加权画质评分器。

    维度：清晰度、对比度、曝光、主体占比、ISO/噪点。所有分数均基于
    图像统计、鸟框几何或 EXIF 元数据。
    """

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "clarity": 0.30,
        "contrast": 0.20,
        "exposure": 0.20,
        "subject_size": 0.20,
        "iso": 0.10,
    }

    _CLARITY_NORMALIZER = 500.0
    _CONTRAST_NORMALIZER = 80.0

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = dict(self.DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)

    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray:
        if image.ndim == 3:
            return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        return image

    @staticmethod
    def calculate_iso_score(iso: Optional[int]) -> float:
        """根据 ISO 分段线性计算噪点惩罚得分,越高越好。

        分段:
        - ≤ 200: 100
        - 200–800: 线性降到 85
        - 800–3200: 线性降到 60
        - 3200–12800: 线性降到 30
        - ≥ 12800: 0
        """
        if iso is None or iso <= 0:
            return 1.0
        if iso <= 200:
            return 1.0
        if iso <= 800:
            return 1.0 - (iso - 200) / 600 * 0.15
        if iso <= 3200:
            return 0.85 - (iso - 800) / 2400 * 0.25
        if iso <= 12800:
            return 0.60 - (iso - 3200) / 9600 * 0.30
        return 0.0

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

    def calculate_subject_size_score(
        self,
        image_shape: Tuple[int, ...],
        bird_bbox: Tuple[int, int, int, int],
    ) -> float:
        """鸟占画面的比例,越大说明鸟越近/越突出,归一化到 0-1。"""
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

    def calculate_quality_score(
        self,
        image: np.ndarray,
        bird_bbox: Tuple[int, int, int, int],
        iso: Optional[int] = None,
    ) -> Dict:
        """计算 5 维加权综合画质评分。

        Returns:
            ``{"score": int 0-100, "details": {dim: float 0-1, ...}}``
        """
        details = {
            "clarity": self.calculate_clarity(image),
            "contrast": self.calculate_contrast(image),
            "exposure": self.calculate_exposure(image),
            "subject_size": self.calculate_subject_size_score(image.shape, bird_bbox),
            "iso": self.calculate_iso_score(iso),
        }
        weighted = sum(details[dim] * self.weights[dim] for dim in self.weights)
        return {"score": int(round(weighted * 100)), "details": details}

    def score_from_path(
        self,
        image_path: str,
        bird_bbox: Tuple[int, int, int, int],
        iso: Optional[int] = None,
    ) -> Dict:
        """从图像路径和鸟框计算 5 维画质评分。"""
        image = cv2.imread(image_path)
        if image is None:
            logging.error(f"Could not read image for quality scoring: {image_path}")
            return {"score": 0, "details": {dim: 0.0 for dim in self.DEFAULT_WEIGHTS}}

        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return self.calculate_quality_score(image, bird_bbox, iso=iso)

import pytest
from unittest.mock import MagicMock
from src.core.quality import QualityScorer
import numpy as np


class TestQualityScorer:
    @pytest.fixture
    def scorer(self):
        return QualityScorer()

    @pytest.fixture
    def sample_image(self):
        return np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)

    def test_clarity_calculation(self, scorer, sample_image):
        clarity = scorer.calculate_clarity(sample_image)
        assert 0 <= clarity <= 1

    def test_contrast_calculation(self, scorer, sample_image):
        contrast = scorer.calculate_contrast(sample_image)
        assert 0 <= contrast <= 1

    def test_exposure_calculation(self, scorer, sample_image):
        exposure = scorer.calculate_exposure(sample_image)
        assert 0 <= exposure <= 1

    def test_subject_size_calculation(self, scorer, sample_image):
        # image shape (100, 200), bbox (50, 25, 100, 50) -> area 5000 / 20000 = 0.25
        subject_size = scorer.calculate_subject_size_score(sample_image.shape, (50, 25, 100, 50))
        assert subject_size == pytest.approx(0.25, abs=1e-6)
        assert 0 <= subject_size <= 1

    def test_iso_score_boundary(self, scorer):
        assert scorer.calculate_iso_score(200) == 1.0
        assert scorer.calculate_iso_score(800) == pytest.approx(0.85, abs=1e-6)
        assert scorer.calculate_iso_score(3200) == pytest.approx(0.60, abs=1e-6)
        assert scorer.calculate_iso_score(12800) == pytest.approx(0.30, abs=1e-6)
        assert scorer.calculate_iso_score(25600) == 0.0
        assert scorer.calculate_iso_score(None) == 1.0

    def test_iso_score_linear_interpolation(self, scorer):
        assert scorer.calculate_iso_score(500) == pytest.approx(0.925, abs=1e-6)
        assert scorer.calculate_iso_score(2000) == pytest.approx(0.725, abs=1e-6)
        assert scorer.calculate_iso_score(8000) == pytest.approx(0.45, abs=1e-6)

    def test_subject_size_returns_zero_for_invalid_bbox(self, scorer, sample_image):
        assert scorer.calculate_subject_size_score(sample_image.shape, (0, 0, 0, 0)) == 0.0
        assert scorer.calculate_subject_size_score(sample_image.shape, (0, 0, -1, 10)) == 0.0

    def test_clarity_uses_bird_crop(self, scorer):
        """清晰度应基于鸟框裁切区域计算，而非整幅图像。"""
        # 左半边：随机纹理（清晰）；右半边：纯色（模糊）
        sharp = np.random.randint(0, 255, (100, 50, 3), dtype=np.uint8)
        smooth = np.full((100, 50, 3), 128, dtype=np.uint8)
        image = np.hstack([sharp, smooth])

        # bbox 在左半边清晰区域 [x1, y1, x2, y2]
        result_sharp = scorer.calculate_quality_score(image, (0, 0, 50, 100))
        # bbox 在右半边模糊区域
        result_smooth = scorer.calculate_quality_score(image, (50, 0, 100, 100))

        assert result_sharp["details"]["clarity"] > result_smooth["details"]["clarity"]
        assert 0 <= result_smooth["details"]["clarity"] <= 1
        assert 0 <= result_sharp["details"]["clarity"] <= 1

    def test_clarity_normalizer_is_larger_than_legacy(self):
        """归一化值应大于旧的 500，避免高像素锐利照片轻易顶到 1.0。"""
        assert QualityScorer._CLARITY_NORMALIZER > 500.0

    def test_calculate_quality_score(self, scorer, sample_image):
        result = scorer.calculate_quality_score(sample_image, (50, 25, 100, 50))
        assert "score" in result
        assert "details" in result
        assert set(result["details"].keys()) == {
            "clarity", "contrast", "exposure", "subject_size", "iso"
        }
        assert 0 <= result["score"] <= 100
        assert result["details"]["subject_size"] == pytest.approx(0.25, abs=1e-6)
        assert result["details"]["iso"] == 1.0

    def test_calculate_quality_score_with_high_iso(self, scorer, sample_image):
        result = scorer.calculate_quality_score(sample_image, (50, 25, 100, 50), iso=3200)
        assert result["details"]["iso"] == pytest.approx(0.60, abs=1e-6)

    def test_calculate_quality_score_with_weights(self, scorer, sample_image):
        weights = {
            "clarity": 0.4, "contrast": 0.0, "exposure": 0.0,
            "subject_size": 0.5, "iso": 0.1
        }
        scorer = QualityScorer(weights=weights)
        result = scorer.calculate_quality_score(sample_image, (50, 25, 100, 50))
        assert 0 <= result["score"] <= 100

    def test_score_from_path(self, scorer, tmp_path):
        import cv2
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((200, 400, 3), dtype=np.uint8) * 128)
        result = scorer.score_from_path(str(img_path), (100, 50, 200, 100))
        assert set(result["details"].keys()) == {
            "clarity", "contrast", "exposure", "subject_size", "iso"
        }
        assert result["details"]["subject_size"] == pytest.approx(0.25, abs=1e-6)
        assert result["details"]["iso"] == 1.0

    def test_score_from_path_with_iso(self, scorer, tmp_path):
        import cv2
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((200, 400, 3), dtype=np.uint8) * 128)
        result = scorer.score_from_path(str(img_path), (100, 50, 200, 100), iso=800)
        assert result["details"]["iso"] == pytest.approx(0.85, abs=1e-6)

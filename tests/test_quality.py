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

    def test_subject_size_returns_zero_for_invalid_bbox(self, scorer, sample_image):
        assert scorer.calculate_subject_size_score(sample_image.shape, (0, 0, 0, 0)) == 0.0
        assert scorer.calculate_subject_size_score(sample_image.shape, (0, 0, -1, 10)) == 0.0

    def test_calculate_quality_score(self, scorer, sample_image):
        result = scorer.calculate_quality_score(sample_image, (50, 25, 100, 50))
        assert "score" in result
        assert "details" in result
        assert set(result["details"].keys()) == {
            "clarity", "contrast", "exposure", "subject_size"
        }
        assert 0 <= result["score"] <= 100
        assert result["details"]["subject_size"] == pytest.approx(0.25, abs=1e-6)

    def test_calculate_quality_score_with_weights(self, scorer, sample_image):
        weights = {"clarity": 0.4, "contrast": 0.0, "exposure": 0.0, "subject_size": 0.6}
        scorer = QualityScorer(weights=weights)
        result = scorer.calculate_quality_score(sample_image, (50, 25, 100, 50))
        assert 0 <= result["score"] <= 100

    def test_score_from_path(self, scorer, tmp_path):
        import cv2
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((200, 400, 3), dtype=np.uint8) * 128)
        result = scorer.score_from_path(str(img_path), (100, 50, 200, 100))
        assert set(result["details"].keys()) == {"clarity", "contrast", "exposure", "subject_size"}
        assert result["details"]["subject_size"] == pytest.approx(0.25, abs=1e-6)

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

    def test_position_calculation(self, scorer, sample_image):
        position = scorer.calculate_position(sample_image.shape, (80, 30, 40, 40))
        assert 0 <= position <= 1

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

    def test_focus_score_with_empty_points(self, scorer):
        focus = scorer.calculate_focus_score([], (0, 0, 100, 100))
        assert focus == 0.5

    def test_focus_score_with_focus_point_inside_bbox(self, scorer):
        focus = scorer.calculate_focus_score([(50, 50)], (40, 40, 20, 20))
        assert focus > 0.5

    def test_calculate_quality_score(self, scorer, sample_image):
        visibility = {"subject_size": 0.5}
        result = scorer.calculate_quality_score(
            sample_image, (50, 25, 100, 50), visibility, []
        )
        assert "score" in result
        assert "details" in result
        assert set(result["details"].keys()) == {
            "clarity", "contrast", "position", "exposure", "subject_size", "focus"
        }
        assert 0 <= result["score"] <= 100
        # details 使用 scorer 自身计算的主体占比，而不是传入的 visibility
        assert result["details"]["subject_size"] == pytest.approx(0.25, abs=1e-6)

    def test_calculate_quality_score_with_weights(self, scorer, sample_image):
        weights = {"clarity": 0.4, "contrast": 0.0, "position": 0.0, "exposure": 0.0, "subject_size": 0.0, "focus": 0.6}
        scorer = QualityScorer(weights=weights)
        visibility = {"subject_size": 0.5}
        result = scorer.calculate_quality_score(
            sample_image, (50, 25, 100, 50), visibility, []
        )
        assert 0 <= result["score"] <= 100

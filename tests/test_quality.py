"""
Unit tests for QualityChecker module.

Tests cover:
- Blur score calculation
- Sharpness threshold detection
- Error handling
"""

import pytest
import tempfile
import os
from pathlib import Path
from PIL import Image
import numpy as np
import cv2

from src.core.quality import QualityChecker


class TestQualityCheckerBlurScore:
    """Test blur score calculation."""

    @pytest.fixture
    def sharp_image(self):
        """Create a sharp test image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            # Create an image with clear edges (high contrast)
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            img[:50, :] = 0  # Black top half
            img[50:, :] = 255  # White bottom half - sharp edge
            cv2.imwrite(f.name, img)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    @pytest.fixture
    def blurry_image(self):
        """Create a blurry test image using Gaussian blur."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            # Create an image and apply Gaussian blur
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            img[:50, :] = 0
            img[50:, :] = 255
            # Apply heavy blur
            blurred = cv2.GaussianBlur(img, (21, 21), 0)
            cv2.imwrite(f.name, blurred)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    def test_calculate_blur_score_returns_float(self, sharp_image):
        """Test that blur score returns a float."""
        score = QualityChecker.calculate_blur_score(sharp_image)
        assert isinstance(score, float)

    def test_calculate_blur_score_sharp_image(self, sharp_image):
        """Test that sharp images have high blur scores."""
        score = QualityChecker.calculate_blur_score(sharp_image)
        assert score > 100  # Sharp images should have high variance

    def test_calculate_blur_score_blurry_image(self, blurry_image):
        """Test that blurry images have low blur scores."""
        score = QualityChecker.calculate_blur_score(blurry_image)
        assert score < 50  # Blurry images should have low variance

    def test_calculate_blur_score_nonexistent_file(self):
        """Test handling of non-existent file."""
        score = QualityChecker.calculate_blur_score("/nonexistent/image.jpg")
        assert score == 0.0

    def test_is_sharp_true(self, sharp_image):
        """Test is_sharp returns True for sharp image."""
        result = QualityChecker.is_sharp(sharp_image, threshold=80.0)
        assert result == True

    def test_is_sharp_false(self, blurry_image):
        """Test is_sharp returns False for blurry image."""
        result = QualityChecker.is_sharp(blurry_image, threshold=80.0)
        assert result == False

    def test_is_sharp_custom_threshold(self, sharp_image):
        """Test is_sharp with custom threshold."""
        # Very high threshold should fail even for sharp image
        result = QualityChecker.is_sharp(sharp_image, threshold=10000.0)
        assert result == False


class TestQualityCheckerEdgeCases:
    """Test edge cases."""

    def test_calculate_blur_score_grayscale_image(self):
        """Test with grayscale image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = np.zeros((100, 100), dtype=np.uint8)
            img[:50, :] = 0
            img[50:, :] = 255
            cv2.imwrite(f.name, img)
            score = QualityChecker.calculate_blur_score(f.name)
            assert isinstance(score, float)
            assert score > 0
        if os.path.exists(f.name):
            os.remove(f.name)

    def test_calculate_blur_score_small_image(self):
        """Test with very small image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            cv2.imwrite(f.name, img)
            score = QualityChecker.calculate_blur_score(f.name)
            assert isinstance(score, float)
        if os.path.exists(f.name):
            os.remove(f.name)


class TestQualityScorerDimensions:
    """Test individual dimension calculators of QualityScorer."""

    @pytest.fixture
    def scorer(self):
        from src.core.quality import QualityScorer
        return QualityScorer()

    @pytest.fixture
    def sharp_image(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:50, :] = 0
        img[50:, :] = 255
        return img

    @pytest.fixture
    def blurry_image(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:50, :] = 0
        img[50:, :] = 255
        return cv2.GaussianBlur(img, (21, 21), 0)

    def test_calculate_clarity_sharp_high_blurry_low(self, scorer, sharp_image, blurry_image):
        sharp = scorer.calculate_clarity(sharp_image)
        blurry = scorer.calculate_clarity(blurry_image)
        assert 0.0 <= sharp <= 1.0
        assert 0.0 <= blurry <= 1.0
        assert sharp > blurry

    def test_calculate_contrast_high_vs_low(self, scorer, sharp_image):
        high = scorer.calculate_contrast(sharp_image)
        flat = np.full((100, 100, 3), 128, dtype=np.uint8)
        low = scorer.calculate_contrast(flat)
        assert 0.0 <= high <= 1.0
        assert 0.0 <= low <= 1.0
        assert high > low

    def test_calculate_position_center_high(self, scorer):
        # bird_bbox 居中
        score = scorer.calculate_position((100, 100, 3), (40, 40, 20, 20))
        assert 0.0 <= score <= 1.0
        assert score > 0.8

    def test_calculate_position_corner_low(self, scorer):
        # bird_bbox 在角落
        score = scorer.calculate_position((100, 100, 3), (0, 0, 20, 20))
        assert 0.0 <= score <= 1.0
        assert score < 0.5

    def test_calculate_exposure_mid_high(self, scorer):
        mid = np.full((100, 100, 3), 128, dtype=np.uint8)
        score_mid = scorer.calculate_exposure(mid)
        assert 0.0 <= score_mid <= 1.0
        # 全黑或全白曝光应该比中间灰度低
        black = np.zeros((100, 100, 3), dtype=np.uint8)
        score_black = scorer.calculate_exposure(black)
        assert score_mid > score_black

    def test_calculate_pose_score_full_visibility(self, scorer):
        visibility = {"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0}
        assert scorer.calculate_pose_score(visibility) == 1.0

    def test_calculate_pose_score_empty_returns_zero(self, scorer):
        assert scorer.calculate_pose_score({}) == 0.0

    def test_calculate_pose_score_partial(self, scorer):
        visibility = {"head": 1.0, "eye": 0.5, "body": 0.0, "tail": 1.0, "wing": 1.0}
        score = scorer.calculate_pose_score(visibility)
        assert 0.0 < score < 1.0
        assert abs(score - 0.7) < 1e-6

    def test_calculate_bif_score_flight_upgrade(self, scorer):
        # 用 partial visibility 避免 pose=1.0 时 bonus 被上限截断
        visibility = {"head": 0.5, "eye": 0.5, "body": 0.5, "tail": 0.5, "wing": 0.5}
        no_flight = scorer.calculate_bif_score(visibility, flight_prob=0.0)
        with_flight = scorer.calculate_bif_score(visibility, flight_prob=0.5)
        assert with_flight > no_flight

    def test_calculate_bif_score_capped_at_one(self, scorer):
        # pose=1.0 + bonus 应被截断到 1.0
        visibility = {"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0}
        score = scorer.calculate_bif_score(visibility, flight_prob=0.5)
        assert score == 1.0

    def test_calculate_bif_score_no_flight(self, scorer):
        visibility = {"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0}
        score = scorer.calculate_bif_score(visibility, flight_prob=0.0)
        assert 0.0 <= score <= 1.0

    def test_calculate_focus_score_inside_bbox(self, scorer):
        # 对焦点全部在 bbox 内
        score = scorer.calculate_focus_score([(50, 50), (55, 55)], (40, 40, 20, 20))
        assert score == 1.0

    def test_calculate_focus_score_outside_bbox(self, scorer):
        # 对焦点全部在 bbox 外
        score = scorer.calculate_focus_score([(0, 0), (5, 5)], (40, 40, 20, 20))
        assert score == 0.0

    def test_calculate_focus_score_empty_returns_default(self, scorer):
        score = scorer.calculate_focus_score([], (40, 40, 20, 20))
        assert 0.0 <= score <= 1.0


class TestQualityScorerOverall:
    """Test the overall calculate_quality_score aggregation."""

    @pytest.fixture
    def scorer(self):
        from src.core.quality import QualityScorer
        return QualityScorer()

    @pytest.fixture
    def sample_image(self):
        return np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)

    def test_returns_dict_with_score_and_details(self, scorer, sample_image):
        result = scorer.calculate_quality_score(
            sample_image,
            bird_bbox=(25, 25, 50, 50),
            visibility={"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0},
            focus_points=[(50, 50)],
        )
        assert isinstance(result, dict)
        assert "score" in result
        assert "details" in result
        assert isinstance(result["score"], int)
        assert isinstance(result["details"], dict)

    def test_score_in_range_0_to_100(self, scorer, sample_image):
        result = scorer.calculate_quality_score(
            sample_image,
            bird_bbox=(25, 25, 50, 50),
            visibility={"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0},
            focus_points=[(50, 50)],
        )
        assert 0 <= result["score"] <= 100

    def test_quality_score_details_has_all_seven_dimensions(self, scorer, sample_image):
        result = scorer.calculate_quality_score(
            sample_image,
            bird_bbox=(25, 25, 50, 50),
            visibility={"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0},
            focus_points=[(50, 50)],
        )
        expected = {"clarity", "contrast", "position", "exposure", "pose", "bif", "focus"}
        assert expected.issubset(result["details"].keys())

    def test_accepts_custom_weights(self, sample_image):
        from src.core.quality import QualityScorer
        custom = {
            "clarity": 0.5, "contrast": 0.0, "position": 0.0,
            "exposure": 0.0, "pose": 0.0, "bif": 0.0, "focus": 0.5,
        }
        scorer = QualityScorer(weights=custom)
        result = scorer.calculate_quality_score(
            sample_image,
            bird_bbox=(25, 25, 50, 50),
            visibility={"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0},
            focus_points=[(50, 50)],
        )
        # 自定义权重总和 1.0,分数仍在 0-100
        assert 0 <= result["score"] <= 100

    def test_higher_visibility_yields_higher_score(self, scorer, sample_image):
        full = scorer.calculate_quality_score(
            sample_image,
            bird_bbox=(25, 25, 50, 50),
            visibility={"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0},
            focus_points=[(50, 50)],
        )
        low = scorer.calculate_quality_score(
            sample_image,
            bird_bbox=(25, 25, 50, 50),
            visibility={"head": 0.0, "eye": 0.0, "body": 0.0, "tail": 0.0, "wing": 0.0},
            focus_points=[(50, 50)],
        )
        assert full["score"] > low["score"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

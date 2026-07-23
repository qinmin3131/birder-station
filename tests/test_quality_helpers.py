"""Tests for quality helpers used by QualityScorer."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.quality import QualityScorer


class TestQualityScorerScoreFromPath:
    def test_score_from_path_returns_five_dimensions(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((200, 400, 3), dtype=np.uint8) * 128)

        scorer = QualityScorer()
        result = scorer.score_from_path(str(img_path), (100, 50, 200, 100))
        assert "score" in result
        assert "details" in result
        assert set(result["details"].keys()) == {
            "clarity", "contrast", "exposure", "subject_size", "iso"
        }
        assert 0 <= result["score"] <= 100
        assert result["details"]["subject_size"] == pytest.approx(0.25, abs=1e-6)
        assert result["details"]["iso"] == 1.0

    def test_score_from_path_with_iso(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((200, 400, 3), dtype=np.uint8) * 128)
        scorer = QualityScorer()
        result = scorer.score_from_path(str(img_path), (100, 50, 200, 100), iso=3200)
        assert result["details"]["iso"] == pytest.approx(0.60, abs=1e-6)

    def test_score_from_path_returns_reasonable_scores_for_uniform_image(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((100, 100, 3), dtype=np.uint8) * 128)
        scorer = QualityScorer()
        result = scorer.score_from_path(str(img_path), (25, 25, 50, 50))
        # Uniform image has low clarity and low contrast
        assert result["details"]["clarity"] < 0.2
        assert result["details"]["contrast"] < 0.2
        # centered 50% bbox -> subject_size = 0.25
        assert result["details"]["subject_size"] == pytest.approx(0.25, abs=1e-6)
        assert result["details"]["iso"] == 1.0

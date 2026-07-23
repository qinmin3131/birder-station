"""Tests for real pose and focus helpers used by QualityScorer."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.focus import FocusParser
from core.quality import QualityScorer


class TestFocusParser:
    def test_returns_empty_list_for_invalid_path(self):
        parser = FocusParser()
        points = parser.parse_af_points("/does/not/exist.jpg")
        assert points == []

    def test_no_fallback_when_exiftool_unavailable(self, tmp_path):
        # ExifTool 未安装或无 AF 信息时返回空列表，不进行中心兜底
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((100, 100, 3), dtype=np.uint8) * 128)
        parser = FocusParser(exiftool_path="nonexistent-exiftool")
        points = parser.parse_af_points(str(img_path))
        assert points == []


class TestQualityScorerScoreFromPath:
    def test_score_from_path_uses_subject_size_and_focus(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((200, 400, 3), dtype=np.uint8) * 128)

        scorer = QualityScorer()
        result = scorer.score_from_path(str(img_path), (100, 50, 200, 100))
        assert "score" in result
        assert "details" in result
        assert set(result["details"].keys()) == {
            "clarity", "contrast", "position", "exposure", "subject_size", "focus"
        }
        assert 0 <= result["score"] <= 100
        # bbox 占画面 1/4，subject_size 应为 0.25
        assert result["details"]["subject_size"] == pytest.approx(0.25, abs=1e-6)

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

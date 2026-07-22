"""Tests for real pose and focus helpers used by QualityScorer."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.pose import PoseDetector
from core.focus import FocusParser
from core.quality import QualityScorer


class TestPoseDetector:
    def test_returns_five_visibility_keys(self):
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        detector = PoseDetector()
        vis = detector.detect_visibility(img, (50, 25, 100, 50))
        assert set(vis.keys()) == {"head", "eye", "body", "tail", "wing"}
        for v in vis.values():
            assert 0.0 <= v <= 1.0

    def test_front_view_returns_higher_head_and_eye_visibility(self):
        detector = PoseDetector()
        # Square-ish bbox suggests front view
        vis = detector.detect_visibility(np.zeros((100, 100, 3), dtype=np.uint8), (25, 25, 50, 50))
        assert vis["head"] >= vis["tail"]
        assert vis["eye"] >= 0.5

    def test_horizontal_bbox_suggests_flight(self):
        detector = PoseDetector()
        # Wide, short bbox like a flying bird
        prob = detector.is_flying(np.zeros((100, 300, 3), dtype=np.uint8), (50, 40, 200, 30))
        assert prob >= 0.5

    def test_vertical_bbox_suggests_not_flying(self):
        detector = PoseDetector()
        prob = detector.is_flying(np.zeros((300, 100, 3), dtype=np.uint8), (25, 50, 50, 200))
        assert prob < 0.5


class TestFocusParser:
    def test_returns_empty_list_for_invalid_path(self):
        parser = FocusParser()
        points = parser.parse_af_points("/does/not/exist.jpg")
        assert points == []

    def test_fallback_returns_center_points(self):
        parser = FocusParser()
        points = parser.get_fallback_points(200, 100)
        assert len(points) == 1
        assert points[0] == (100, 50)


class TestQualityScorerScoreFromPath:
    def test_score_from_path_uses_pose_and_focus(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((200, 400, 3), dtype=np.uint8) * 128)

        scorer = QualityScorer()
        result = scorer.score_from_path(str(img_path), (100, 50, 200, 100))
        assert "score" in result
        assert "details" in result
        assert set(result["details"].keys()) == {
            "clarity", "contrast", "position", "exposure", "pose", "bif", "focus"
        }
        assert 0 <= result["score"] <= 100

    def test_score_from_path_returns_reasonable_scores_for_uniform_image(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        cv2.imwrite(str(img_path), np.ones((100, 100, 3), dtype=np.uint8) * 128)
        scorer = QualityScorer()
        result = scorer.score_from_path(str(img_path), (25, 25, 50, 50))
        # Uniform image has low clarity and low contrast
        assert result["details"]["clarity"] < 0.2
        assert result["details"]["contrast"] < 0.2

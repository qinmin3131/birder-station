import numpy as np
import pytest

from src.core.pose import PoseDetector


@pytest.fixture
def detector():
    return PoseDetector()


def test_subject_size_returns_ratio(detector):
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    bbox = (50, 25, 100, 50)  # area = 5000, image area = 20000
    vis = detector.detect_visibility(image, bbox)
    assert set(vis.keys()) == {"subject_size"}
    assert vis["subject_size"] == pytest.approx(0.25, abs=1e-6)


def test_subject_size_capped_at_one(detector):
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    bbox = (0, 0, 200, 200)  # larger than image
    vis = detector.detect_visibility(image, bbox)
    assert vis["subject_size"] == 1.0


def test_subject_size_zero_for_invalid_bbox(detector):
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    assert detector.detect_visibility(image, (0, 0, 0, 0))["subject_size"] == 0.0
    assert detector.detect_visibility(image, (0, 0, -10, 10))["subject_size"] == 0.0


def test_subject_size_zero_for_invalid_image(detector):
    image = np.zeros((0, 100, 3), dtype=np.uint8)
    assert detector.detect_visibility(image, (0, 0, 10, 10))["subject_size"] == 0.0

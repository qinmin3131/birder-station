import numpy as np
import pytest

from src.core.pose import PoseDetector


@pytest.fixture
def detector():
    return PoseDetector()


def test_detect_visibility_returns_full_visibility(detector):
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    bbox = (25, 25, 50, 50)
    vis = detector.detect_visibility(image, bbox)
    assert set(vis.keys()) == {"head", "eye", "body", "tail", "wing"}
    # 无边缘截断的完整框：头、眼、尾应完全可见，身体/翅膀有基础默认值
    assert vis["head"] == 1.0
    assert vis["eye"] == 1.0
    assert vis["tail"] == 1.0
    assert vis["body"] >= 0.8
    assert vis["wing"] >= 0.6
    assert all(v >= 0.6 for v in vis.values())

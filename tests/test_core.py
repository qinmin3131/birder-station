import sys
import os
import numpy as np
from PIL import Image
import cv2

# Add src to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.detector import BirdDetector
from src.core.quality import QualityChecker
from src.core.processor import ImageProcessor

def test_core_processing():
    print("--- Testing Core Processing ---")
    
    # Create a dummy image
    test_img_path = "tests/test_bird.jpg"
    img = Image.new('RGB', (1000, 1000), color=(73, 109, 137))
    img.save(test_img_path)
    
    print("Testing QualityChecker...")
    score = QualityChecker.calculate_blur_score(test_img_path)
    print(f"Blur Score: {score}")
    assert isinstance(score, float)
    
    print("Testing BirdDetector (Initialization only)...")
    # We won't run full detection because it downloads weights
    detector = BirdDetector("yolo26n.pt")
    assert detector is not None
    
    print("Testing ImageProcessor...")
    output_path = "tests/test_cropped.jpg"
    box = [100, 100, 500, 500]
    success = ImageProcessor.crop_and_resize(test_img_path, box, output_path, target_size=640)
    assert success is True
    assert os.path.exists(output_path)
    with Image.open(output_path) as cropped:
        assert cropped.size == (640, 640)
    
    # Cleanup
    if os.path.exists(test_img_path): os.remove(test_img_path)
    if os.path.exists(output_path): os.remove(output_path)
    
    print("--- Core Processing Test Passed (Logic Check) ---")


def test_crop_and_resize_preserves_aspect_ratio():
    """非正方形裁切区域生成归档图时应保持宽高比，不能强制 1:1。"""
    print("--- Testing Aspect Ratio Preservation ---")
    
    test_img_path = "tests/test_bird_wide.jpg"
    output_path = "tests/test_cropped_preserve.jpg"
    
    img = Image.new('RGB', (1000, 500), color=(73, 109, 137))
    img.save(test_img_path)
    
    # Crop region is 400x200 (non-square)
    box = [100, 100, 500, 300]
    success = ImageProcessor.crop_and_resize(
        test_img_path, box, output_path,
        target_size=640, padding=0, preserve_aspect=True
    )
    assert success is True
    assert os.path.exists(output_path)
    
    with Image.open(output_path) as cropped:
        # 400x200 scaled to fit within 640x640 while preserving aspect ratio -> 640x320
        assert cropped.size == (640, 320)
    
    # Cleanup
    if os.path.exists(test_img_path): os.remove(test_img_path)
    if os.path.exists(output_path): os.remove(output_path)
    
    print("--- Aspect Ratio Preservation Test Passed ---")

if __name__ == "__main__":
    test_core_processing()

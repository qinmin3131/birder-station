"""Debug a single ORF processing step to find the bottleneck."""
import sys
import logging
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from src.core.processor import ImageProcessor
from src.core.detector import BirdDetector
from src.metadata.exif_writer import ExifWriter, read_iso
from src.core.quality import QualityScorer

IMAGE = "D:/照片/2026/testdata/P2080593.ORF"


def main():
    t0 = time.time()
    logging.info(f"Starting debug for {IMAGE}")

    t = time.time()
    size = Path(IMAGE).stat().st_size
    logging.info(f"stat: {time.time()-t:.2f}s size={size}")

    t = time.time()
    ew = ExifWriter()
    logging.info(f"ExifWriter init: {time.time()-t:.2f}s")

    t = time.time()
    iso = read_iso(ew, IMAGE)
    logging.info(f"read_iso: {time.time()-t:.2f}s iso={iso}")

    t = time.time()
    decoded = ImageProcessor.decode_raw_to_temp_jpg(IMAGE)
    logging.info(f"decode_raw_to_temp_jpg: {time.time()-t:.2f}s decoded={decoded}")

    t = time.time()
    det = BirdDetector("data/models/yolo26n.pt", device="cuda")
    dets = det.detect(decoded)
    logging.info(f"detect: {time.time()-t:.2f}s dets={dets}")

    if dets:
        box = dets[0][0]
        t = time.time()
        score = QualityScorer().score_from_path(decoded, box, iso=iso)
        logging.info(f"quality score: {time.time()-t:.2f}s score={score}")

    logging.info(f"Total: {time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()

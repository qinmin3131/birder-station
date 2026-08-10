"""Debug a single ORF processing step including recognition."""
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
from src.recognition.inference_local import LocalBirdRecognizer
from src.metadata.ioc_manager import IOCManager

IMAGE = "D:/照片/2026/testdata/P2080593.ORF"


def main():
    t0 = time.time()
    logging.info(f"Starting debug for {IMAGE}")

    t = time.time()
    ew = ExifWriter()
    iso = read_iso(ew, IMAGE)
    logging.info(f"read_iso: {time.time()-t:.2f}s iso={iso}")

    t = time.time()
    decoded = ImageProcessor.decode_raw_to_temp_jpg(IMAGE)
    logging.info(f"decode_raw_to_temp_jpg: {time.time()-t:.2f}s decoded={decoded}")

    t = time.time()
    det = BirdDetector("data/models/yolo26n.pt", device="cuda")
    dets = det.detect(decoded)
    logging.info(f"detect: {time.time()-t:.2f}s dets={dets}")

    t = time.time()
    db = IOCManager("data/birder.db")
    all_labels = [row["label"] for row in db.conn.execute("SELECT label FROM taxonomy")]
    logging.info(f"loaded {len(all_labels)} labels: {time.time()-t:.2f}s")

    t = time.time()
    rec = LocalBirdRecognizer(device="cuda", all_labels=all_labels)
    logging.info(f"LocalBirdRecognizer init: {time.time()-t:.2f}s")

    if dets:
        box = dets[0][0]
        t = time.time()
        score = QualityScorer().score_from_path(decoded, box, iso=iso)
        logging.info(f"quality score: {time.time()-t:.2f}s score={score}")

        t = time.time()
        crop = Path(decoded).parent / f"debug_crop.jpg"
        ImageProcessor.crop_and_resize(decoded, box, str(crop), target_size=224, padding=50)
        logging.info(f"crop: {time.time()-t:.2f}s")

        t = time.time()
        result = rec.predict(str(crop))
        logging.info(f"recognize: {time.time()-t:.2f}s result={result}")

    logging.info(f"Total: {time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()

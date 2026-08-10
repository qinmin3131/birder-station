"""Debug single image recognition timing."""
import sys
import logging
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from src.recognition.inference_local import LocalBirdRecognizer
from src.metadata.ioc_manager import IOCManager
from src.core.processor import ImageProcessor
from src.metadata.exif_writer import ExifWriter, write_metadata_for_photo
from types import SimpleNamespace

IMAGE = "D:/照片/2026/testdata/P2080593.ORF"


def main():
    t0 = time.time()
    db = IOCManager("data/birder.db")
    labels = [row[0] for row in db.conn.execute("SELECT scientific_name FROM taxonomy")]
    logging.info(f"loaded {len(labels)} labels in {time.time()-t0:.2f}s")

    rec = LocalBirdRecognizer(device="cuda", all_labels=labels)
    logging.info(f"recognizer init total {time.time()-t0:.2f}s")

    decoded = ImageProcessor.decode_raw_to_temp_jpg(IMAGE)

    t = time.time()
    result = rec.predict(decoded, labels, top_k=5)
    logging.info(f"first predict: {time.time()-t:.2f}s result={result}")

    t = time.time()
    result2 = rec.predict(decoded, labels, top_k=5)
    logging.info(f"second predict: {time.time()-t:.2f}s result={result2}")

    ew = ExifWriter()
    meta = SimpleNamespace(
        original_path=IMAGE,
        file_path=IMAGE,
        primary_bird_cn="Test",
        scientific_name=result[0]["scientific_name"],
        location_tag="Unknown",
        captured_date="20260723",
        quality_score=50,
        is_selected=False,
    )
    t = time.time()
    write_metadata_for_photo(meta, ew, write_mode="xmp_sidecar")
    logging.info(f"write xmp sidecar: {time.time()-t:.2f}s")

    logging.info(f"total {time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()

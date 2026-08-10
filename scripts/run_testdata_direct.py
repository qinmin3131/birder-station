"""Run pipeline on the 8 test ORF images in index-only mode with warm cache."""
import sys
import logging
import time
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from src.pipeline_runner import WingScribePipeline
from src.core.io.local import LocalProvider

TEST_FOLDER = Path("D:/照片/2026/testdata")
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def main():
    runner = WingScribePipeline(str(CONFIG_PATH))
    provider = LocalProvider(base_dir=None)

    # Index-only: do not move/write sidecars for this quick test run.
    runner.output_root = ""
    runner.path_generator = None
    runner.write_back_raw = False

    # Pre-load models.
    logging.info("Pre-loading detector...")
    _ = runner.detector.model
    logging.info("Detector loaded.")

    logging.info("Pre-loading recognizer...")
    runner._init_recognizer()
    logging.info("Recognizer loaded.")

    # Warm text-feature cache so the first image is not penalized.
    candidate_labels = runner._select_candidate_labels("Unknown")
    logging.info(f"Warming text features for {len(candidate_labels)} candidate labels...")
    t = time.time()
    _ = runner.recognizer._get_text_features(candidate_labels)
    logging.info(f"Text features cached in {time.time()-t:.2f}s.")

    supported = runner.config.get("paths", {}).get("supported_formats", [".jpg", ".jpeg"])
    suffixes = tuple(s.lower() for s in supported)
    files = sorted([p for p in TEST_FOLDER.iterdir() if p.is_file() and p.suffix.lower() in suffixes])
    logging.info(f"Found {len(files)} test files: {[f.name for f in files]}")

    for idx, p in enumerate(files, 1):
        logging.info(f"[{idx}/{len(files)}] Processing {p.name} ...")
        entry = SimpleNamespace(path=str(p), name=p.name, is_dir=False, size=p.stat().st_size)
        meta = {"location_tag": "Unknown"}
        try:
            runner.process_image(provider, entry, meta)
        except Exception as e:
            logging.exception(f"Failed to process {p.name}: {e}")
        logging.info(f"[{idx}/{len(files)}] Done {p.name}")

    logging.info("All test files processed.")


if __name__ == "__main__":
    main()

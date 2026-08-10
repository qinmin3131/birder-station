import sqlite3, json, time, logging, sys
from pathlib import Path
from types import SimpleNamespace

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline_runner import WingScribePipeline
from src.core.io.local import LocalProvider

TEST_FOLDER = Path("D:/照片/2026/testdata")
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def main():
    conn = sqlite3.connect("data/birder.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM photos WHERE original_path LIKE '%testdata%'")
    conn.commit()
    logging.info(f"Deleted {cur.rowcount} old testdata records.")
    conn.close()

    runner = WingScribePipeline(str(CONFIG_PATH))
    provider = LocalProvider(base_dir=None)
    runner.output_root = ""
    runner.path_generator = None
    runner.write_back_raw = False

    _ = runner.detector.model
    runner._init_recognizer()
    candidate_labels = runner._select_candidate_labels("Unknown")
    _ = runner.recognizer._get_text_features(candidate_labels)

    supported = runner.config.get("paths", {}).get("supported_formats", [".jpg", ".jpeg"])
    suffixes = tuple(s.lower() for s in supported)
    files = sorted([p for p in TEST_FOLDER.iterdir() if p.is_file() and p.suffix.lower() in suffixes])

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

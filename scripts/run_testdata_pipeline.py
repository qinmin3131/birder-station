"""Run pipeline on the testdata folder only."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.pipeline_runner import WingScribePipeline


def main():
    runner = WingScribePipeline(str(PROJECT_ROOT / "config" / "settings.yaml"))
    runner.run_by_folders(["D:/照片/2026/testdata"], recursive=False)


if __name__ == "__main__":
    main()

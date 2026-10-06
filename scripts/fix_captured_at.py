"""Fix captured_at for photos that have null captured_at but valid EXIF data."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.metadata.exif_writer import ExifWriter, read_capture_datetime
from src.core.io.path_parser import PathParser
from src.db.models import Photo, init_database
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def main():
    db_path = str(Path(__file__).parent.parent / "data" / "birder.db")
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return

    engine = create_engine(f"sqlite:///{db_path}")
    init_database(engine)
    session = sessionmaker(bind=engine)()

    # Find photos with null captured_at or incorrect captured_date
    photos = session.query(Photo).filter(
        (Photo.captured_at.is_(None)) | (Photo.captured_date == "20260830")
    ).all()
    print(f"Found {len(photos)} photos to fix")

    if not photos:
        print("Nothing to fix.")
        session.close()
        return

    exif_writer = ExifWriter()
    fixed = 0
    skipped = 0

    for photo in photos:
        # Determine source file for EXIF reading
        source = photo.original_path or photo.file_path
        if not source or not os.path.exists(source):
            print(f"  [SKIP] id={photo.id} file not found: {source}")
            skipped += 1
            continue

        # Read EXIF datetime
        captured_at = read_capture_datetime(exif_writer, source)
        if captured_at:
            photo.captured_at = captured_at
            # Fix captured_date to use EXIF date instead of default today
            exif_date_str = captured_at.strftime("%Y%m%d")
            if not photo.captured_date or photo.captured_date == "20260830":
                photo.captured_date = exif_date_str
            fixed += 1
            print(f"  [FIX] id={photo.id} captured_at={captured_at} date={photo.captured_date} file={photo.filename}")
        else:
            print(f"  [NO EXIF] id={photo.id} file={photo.filename}")
            skipped += 1

        # Fix captured_date from folder path if null
        if not photo.captured_date and photo.file_path:
            source_root = str(Path(photo.file_path).parent)
            parser = PathParser(source_root, None)
            meta = parser.parse(photo.file_path)
            if meta.get("captured_date"):
                photo.captured_date = meta["captured_date"]
                print(f"  [FIX DATE] id={photo.id} captured_date={meta['captured_date']}")

    session.commit()
    print(f"\nDone: {fixed} fixed, {skipped} skipped")
    session.close()


if __name__ == "__main__":
    main()

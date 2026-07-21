"""Image processing utilities for detection, cropping, and RAW handling."""
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image


class ImageProcessor:
    """Shared image processing helpers."""

    SUPPORTED_RAW_EXTENSIONS = {
        ".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2", ".pef", ".raf"
    }

    @staticmethod
    def is_raw(image_path: str) -> bool:
        """Return True if the image file is a camera RAW format."""
        return Path(image_path).suffix.lower() in ImageProcessor.SUPPORTED_RAW_EXTENSIONS

    @staticmethod
    def decode_raw_to_temp_jpg(image_path: str, temp_dir: Optional[str] = None) -> str:
        """Decode a RAW file to a temporary JPEG and return the JPEG path.

        The caller is responsible for cleaning up the temporary file.
        """
        import rawpy

        with rawpy.imread(image_path) as raw:
            rgb = raw.postprocess(
                output_bps=8,
                use_camera_wb=True,
                half_size=True,
            )
        img = Image.fromarray(rgb)
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg", dir=temp_dir)
        try:
            img.save(tmp_path, quality=95)
        finally:
            os.close(fd)
        return tmp_path

    @staticmethod
    def crop_and_resize(
        source_path: str,
        box: Tuple[float, float, float, float],
        dest_path: str,
        target_size: int = 224,
        padding: int = 50,
    ) -> bool:
        """Crop the detected region from *source_path* and resize to *target_size*.

        Args:
            source_path: Path to a decoded image (JPEG or PNG).
            box: (x1, y1, x2, y2) detection box.
            dest_path: Where to write the cropped JPEG.
            target_size: Final square size for the recognizer.
            padding: Extra pixels around the box before cropping.
        """
        x1, y1, x2, y2 = map(int, box)
        x1 -= padding
        y1 -= padding
        x2 += padding
        y2 += padding

        with Image.open(source_path) as img:
            width, height = img.size
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(width, x2)
            y2 = min(height, y2)

            cropped = img.crop((x1, y1, x2, y2))
            cropped = cropped.resize((target_size, target_size), Image.LANCZOS)

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            cropped.save(dest_path, "JPEG", quality=95)

        return True

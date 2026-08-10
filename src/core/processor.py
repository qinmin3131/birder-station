"""Image processing utilities for detection, cropping, and RAW handling."""
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageCms


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
    def decode_raw_to_temp_jpg(
        image_path: str,
        temp_dir: Optional[str] = None,
        half_size: bool = True,
    ) -> str:
        """Decode a RAW file to a temporary JPEG and return the JPEG path.

        Strategy to avoid color shifts (especially for ORF):
        1. Try to extract the embedded JPEG preview/thumbnail first.  This uses
           the camera's own rendering and usually matches the in-camera JPEG.
        2. Fall back to rawpy postprocess with explicit sRGB output color space
           and a standard gamma curve, then embed an sRGB ICC profile so browsers
           interpret the JPEG consistently.

        The caller is responsible for cleaning up the temporary file.
        """
        import rawpy

        with rawpy.imread(image_path) as raw:
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    fd, tmp_path = tempfile.mkstemp(suffix=".jpg", dir=temp_dir)
                    try:
                        with os.fdopen(fd, "wb") as f:
                            f.write(thumb.data)
                    except Exception:
                        os.close(fd)
                        raise
                    return tmp_path
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                pass

            rgb = raw.postprocess(
                output_bps=8,
                use_camera_wb=True,
                half_size=half_size,
                output_color=rawpy.ColorSpace.sRGB,
                gamma=(2.222, 4.5),
                no_auto_bright=True,
                brightness=1.0,
            )

        img = Image.fromarray(rgb)
        img = ImageProcessor._embed_srgb_icc(img)

        fd, tmp_path = tempfile.mkstemp(suffix=".jpg", dir=temp_dir)
        try:
            img.save(tmp_path, quality=95, icc_profile=img.info.get("icc_profile"))
        finally:
            os.close(fd)
        return tmp_path

    @staticmethod
    def _embed_srgb_icc(img: Image.Image) -> Image.Image:
        """Ensure the image carries an sRGB ICC profile.

        If the image already has an ICC profile, return it unchanged. Otherwise
        create a standard sRGB profile and attach it to the image info dict.
        """
        if img.info.get("icc_profile"):
            return img
        srgb_profile = ImageCms.createProfile("sRGB")
        img.info["icc_profile"] = ImageCms.ImageCmsProfile(srgb_profile).tobytes()
        return img

    @staticmethod
    def crop_and_resize(
        source_path: str,
        box: Tuple[float, float, float, float],
        dest_path: str,
        target_size: int = 224,
        padding: int = 50,
        preserve_aspect: bool = False,
    ) -> bool:
        """Crop the detected region from *source_path* and resize to *target_size*.

        Args:
            source_path: Path to a decoded image (JPEG or PNG).
            box: (x1, y1, x2, y2) detection box.
            dest_path: Where to write the cropped JPEG.
            target_size: Final square size for the recognizer, or max edge size
                when *preserve_aspect* is True.
            padding: Extra pixels around the box before cropping.
            preserve_aspect: If False, resize to a square (target_size, target_size)
                for model input. If True, resize so the longest edge equals
                target_size while preserving the original crop aspect ratio.
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
            if preserve_aspect:
                ratio = min(target_size / cropped.width, target_size / cropped.height)
                new_width = max(1, int(round(cropped.width * ratio)))
                new_height = max(1, int(round(cropped.height * ratio)))
                cropped = cropped.resize((new_width, new_height), Image.LANCZOS)
            else:
                cropped = cropped.resize((target_size, target_size), Image.LANCZOS)

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            cropped.save(dest_path, "JPEG", quality=95)

        return True

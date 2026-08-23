"""
Unit tests for ExifWriter module.

Tests cover:
- Metadata writing
- Tag handling
- Error handling
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
import tempfile
import os
import json
from PIL import Image

from src.metadata.exif_writer import (
    ExifWriter,
    quality_score_to_rating,
    build_exif_tags_from_photo,
    write_metadata_for_photo,
    read_iso,
    read_capture_datetime,
    read_exif_summary,
)


class TestExifWriter:
    """Test ExifWriter class."""

    @pytest.fixture
    def test_image(self):
        """Create a temporary test image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    def test_init(self):
        """Test initialization."""
        writer = ExifWriter("exiftool")
        assert writer.exiftool_path == "exiftool"

    def test_init_default_path(self):
        """Test default exiftool path."""
        writer = ExifWriter()
        assert writer.exiftool_path == "exiftool"

    @patch('subprocess.run')
    def test_write_metadata_success(self, mock_run, test_image):
        """Test successful metadata write."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "Test Title",
            "XPKeywords": ["bird", "nature"]
        }
        result = writer.write_metadata(test_image, tags)
        assert result is True
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_write_metadata_with_list_tags(self, mock_run, test_image):
        """Test writing metadata with list tags."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPKeywords": ["bird", "nature", "wildlife"]
        }
        result = writer.write_metadata(test_image, tags)
        assert result is True

        # Check that subprocess was called
        assert mock_run.called

    @patch('subprocess.run')
    def test_write_metadata_with_none_values(self, mock_run, test_image):
        """Test writing metadata ignores None values."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "Test",
            "XPKeywords": None
        }
        result = writer.write_metadata(test_image, tags)
        assert result is True

    @patch('subprocess.run')
    def test_write_metadata_with_empty_string(self, mock_run, test_image):
        """Test writing metadata handles empty strings."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "",
            "XPKeywords": "test"
        }
        result = writer.write_metadata(test_image, tags)
        # Empty string should still be processed (not filtered out)
        assert result is True


class TestExifWriterExiftoolNotFound:
    """Test exiftool not found scenario."""

    @patch('shutil.which')
    def test_write_metadata_exiftool_not_found(self, mock_which):
        """Test handling when exiftool is not found."""
        mock_which.return_value = None

        writer = ExifWriter("exiftool")
        result = writer.write_metadata("/tmp/test.jpg", {"XPTitle": "Test"})
        assert result is False


class TestExifWriterErrorHandling:
    """Test error handling."""

    @patch('subprocess.run')
    def test_write_metadata_subprocess_error(self, mock_run):
        """Test handling subprocess errors."""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "exiftool")

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)

            writer = ExifWriter("exiftool")
            result = writer.write_metadata(f.name, {"XPTitle": "Test"})
            assert result is False

        if os.path.exists(f.name):
            os.remove(f.name)

    @patch('subprocess.run')
    def test_write_metadata_general_error(self, mock_run):
        """Test handling general errors."""
        mock_run.side_effect = Exception("Unknown error")

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)

            writer = ExifWriter("exiftool")
            result = writer.write_metadata(f.name, {"XPTitle": "Test"})
            assert result is False

        if os.path.exists(f.name):
            os.remove(f.name)


class TestExifWriterEncoding:
    """Test encoding handling."""

    @pytest.fixture
    def test_image_encoding(self):
        """Create a temporary test image."""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)
            yield f.name
        if os.path.exists(f.name):
            os.remove(f.name)

    @patch('subprocess.run')
    def test_write_metadata_chinese_chars(self, mock_run, test_image_encoding):
        """Test writing metadata with Chinese characters."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "测试标题",
            "XPKeywords": ["鸟类", "自然"]
        }
        result = writer.write_metadata(test_image_encoding, tags)
        assert result is True

    @patch('subprocess.run')
    def test_write_metadata_newlines_escaped(self, mock_run, test_image_encoding):
        """Test that newlines are properly escaped."""
        mock_run.return_value = MagicMock(returncode=0)

        writer = ExifWriter("exiftool")
        tags = {
            "XPTitle": "Line1\nLine2"
        }
        result = writer.write_metadata(test_image_encoding, tags)
        # Should not raise exception
        assert result is True


class TestExifWriterXmpSidecar:
    """Test XMP sidecar writing for RAW files."""

    def test_write_xmp_sidecar_creates_file(self):
        with tempfile.NamedTemporaryFile(suffix='.ORF', delete=False) as f:
            raw_path = f.name
        try:
            writer = ExifWriter("exiftool")
            tags = {
                "Title": "Cyanopica cyanus",
                "Keywords": ["bird", "Cyanopica cyanus"],
                "Rights": "Test",
                "CustomBird": "灰喜鹊",
            }
            result = writer.write_metadata(raw_path, tags, write_mode="xmp_sidecar")
            assert result is True
            xmp_path = Path(raw_path).with_suffix(".ORF.xmp")
            assert xmp_path.exists()
            content = xmp_path.read_text(encoding="utf-8")
            assert "Cyanopica cyanus" in content
            assert "灰喜鹊" in content
            assert "bird" in content
        finally:
            if os.path.exists(raw_path):
                os.remove(raw_path)
            xmp_path = Path(raw_path).with_suffix(".ORF.xmp")
            if xmp_path.exists():
                os.remove(xmp_path)

    def test_jpeg_ignores_xmp_sidecar_mode(self):
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color=(255, 0, 0))
            img.save(f.name)
            jpg_path = f.name
        try:
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                writer = ExifWriter("exiftool")
                result = writer.write_metadata(jpg_path, {"XPTitle": "Test"}, write_mode="xmp_sidecar")
                assert result is True
                # JPEG should still use exiftool, not create sidecar
                xmp_path = Path(jpg_path).with_suffix(".jpg.xmp")
                assert not xmp_path.exists()
                mock_run.assert_called_once()
        finally:
            if os.path.exists(jpg_path):
                os.remove(jpg_path)


class TestPhotoMetadataHelpers:
    """Test helpers that build tags from Photo records."""

    def test_quality_score_to_rating(self):
        assert quality_score_to_rating(None) == 0
        assert quality_score_to_rating(0) == 0
        assert quality_score_to_rating(29) == 0
        assert quality_score_to_rating(30) == 1
        assert quality_score_to_rating(60) == 2
        assert quality_score_to_rating(75) == 3
        assert quality_score_to_rating(85) == 4
        assert quality_score_to_rating(95) == 5
        assert quality_score_to_rating(150) == 5

    def test_build_exif_tags_from_photo(self):
        photo = SimpleNamespace(
            primary_bird_cn="麻雀",
            scientific_name="Passer montanus",
            location_tag="奥林匹克森林公园",
            captured_date="2026-07-20",
            quality_score=85,
            is_selected=True,
        )
        tags = build_exif_tags_from_photo(photo)
        assert tags["ImageDescription"] == "麻雀 | Passer montanus | 奥林匹克森林公园 | 2026-07-20"
        assert tags["XMP:Title"] == "麻雀 | Passer montanus"
        assert tags["IPTC:Keywords"] == ["麻雀", "Passer montanus", "奥林匹克森林公园"]
        assert tags["XMP:Subject"] == ["麻雀", "Passer montanus", "奥林匹克森林公园"]
        assert tags["XMP:Pick"] == "1"
        assert tags["XMP:Rating"] == 4

    def test_build_exif_tags_from_photo_defaults(self):
        photo = SimpleNamespace(
            primary_bird_cn=None,
            scientific_name=None,
            location_tag=None,
            captured_date=None,
            quality_score=None,
            is_selected=False,
        )
        tags = build_exif_tags_from_photo(photo)
        assert tags["XMP:Title"] == "WingScribe Photo"
        assert tags["XMP:Rating"] == 0
        assert tags["XMP:Pick"] == "0"

    @patch("os.path.exists")
    @patch("subprocess.run")
    def test_write_metadata_for_photo_jpeg(self, mock_run, mock_exists):
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img = Image.new("RGB", (100, 100), color=(255, 0, 0))
            img.save(f.name)
            jpg_path = f.name

        try:
            photo = SimpleNamespace(
                original_path=jpg_path,
                file_path=jpg_path,
                primary_bird_cn="灰喜鹊",
                scientific_name="Cyanopica cyanus",
                location_tag="北京植物园",
                captured_date="2026-07-21",
                quality_score=92,
                is_selected=True,
            )
            writer = ExifWriter("exiftool")
            result = write_metadata_for_photo(photo, writer, write_mode="exif")
            assert result is True
            mock_run.assert_called_once()
        finally:
            if os.path.exists(jpg_path):
                os.remove(jpg_path)

    def test_write_metadata_for_photo_raw_sidecar(self):
        with tempfile.NamedTemporaryFile(suffix=".ORF", delete=False) as f:
            raw_path = f.name
        try:
            photo = SimpleNamespace(
                original_path=raw_path,
                file_path=raw_path,
                primary_bird_cn="灰喜鹊",
                scientific_name="Cyanopica cyanus",
                location_tag="北京植物园",
                captured_date="2026-07-21",
                quality_score=92,
                is_selected=True,
            )
            writer = ExifWriter("exiftool")
            result = write_metadata_for_photo(photo, writer, write_mode="xmp_sidecar")
            assert result is True
            xmp_path = Path(raw_path).with_suffix(".ORF.xmp")
            assert xmp_path.exists()
            content = xmp_path.read_text(encoding="utf-8")
            assert "灰喜鹊" in content
            assert "Cyanopica cyanus" in content
        finally:
            if os.path.exists(raw_path):
                os.remove(raw_path)
            xmp_path = Path(raw_path).with_suffix(".ORF.xmp")
            if xmp_path.exists():
                os.remove(xmp_path)


class TestReadIso:
    """Tests for ISO extraction helper."""

    def test_read_iso_from_exiftool(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img = Image.new("RGB", (100, 100), color=(255, 0, 0))
            img.save(f.name)
            jpg_path = f.name
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="400\n", stderr=""
                )
                writer = ExifWriter("exiftool")
                assert read_iso(writer, jpg_path) == 400
        finally:
            if os.path.exists(jpg_path):
                os.remove(jpg_path)

    def test_read_iso_from_exiftool_with_colon(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img = Image.new("RGB", (100, 100), color=(255, 0, 0))
            img.save(f.name)
            jpg_path = f.name
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="ISO : 800\n", stderr=""
                )
                writer = ExifWriter("exiftool")
                assert read_iso(writer, jpg_path) == 800
        finally:
            if os.path.exists(jpg_path):
                os.remove(jpg_path)

    def test_read_iso_missing_returns_none(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img = Image.new("RGB", (100, 100), color=(255, 0, 0))
            img.save(f.name)
            jpg_path = f.name
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="\n", stderr="")
                writer = ExifWriter("exiftool")
                assert read_iso(writer, jpg_path) is None
        finally:
            if os.path.exists(jpg_path):
                os.remove(jpg_path)

    def test_read_iso_exiftool_not_found(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img = Image.new("RGB", (100, 100), color=(255, 0, 0))
            img.save(f.name)
            jpg_path = f.name
        try:
            with patch.object(ExifWriter, "_resolve_exiftool", return_value=None):
                writer = ExifWriter("exiftool")
                assert read_iso(writer, jpg_path) is None
        finally:
            if os.path.exists(jpg_path):
                os.remove(jpg_path)


class TestReadExifSummary:
    """Tests for read_exif_summary helper."""

    def test_read_exif_summary_parses_flat_tags(self):
        """ExifTool output without group prefix should populate summary fields."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img = Image.new("RGB", (100, 100), color=(255, 0, 0))
            img.save(f.name)
            jpg_path = f.name
        try:
            fake_json = [
                {
                    "SourceFile": jpg_path,
                    "Make": "OM Digital Solutions",
                    "Model": "OM-3",
                    "LensModel": "OM 75-300mm F4.8-6.7 II",
                    "Aperture": 6.7,
                    "ShutterSpeed": "1/800",
                    "ISO": 3200,
                    "FocalLength": "300.0 mm",
                    "DateTimeOriginal": "2026:01:01 13:42:27",
                    "ImageSize": "5220x3912",
                }
            ]
            with patch("src.metadata.exif_writer.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=json.dumps(fake_json), stderr=""
                )
                writer = ExifWriter("exiftool")
                summary = read_exif_summary(writer, jpg_path)
            assert summary["camera_make"] == "OM Digital Solutions"
            assert summary["camera_model"] == "OM-3"
            assert summary["lens_model"] == "OM 75-300mm F4.8-6.7 II"
            assert summary["aperture"] == 6.7
            assert summary["shutter_speed"] == "1/800"
            assert summary["iso"] == 3200
            assert summary["focal_length"] == "300.0 mm"
            assert summary["date_time_original"] == "2026:01:01 13:42:27"
            assert summary["image_size"] == "5220x3912"
            assert summary["file_size"] == os.stat(jpg_path).st_size
        finally:
            if os.path.exists(jpg_path):
                os.remove(jpg_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

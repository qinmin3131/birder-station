import logging
import subprocess
import tempfile
import shutil
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional

RAW_EXTS = {".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"}


class ExifWriter:
    def __init__(self, exiftool_path: str = "exiftool"):
        """
        exiftool_path: Path to the exiftool executable.
        Ensure it is in PATH or provide absolute path.
        """
        self.exiftool_path = exiftool_path

    def _resolve_exiftool(self) -> str | None:
        """
        Resolve exiftool executable path.
        Priority:
        1) explicit EXIFTOOL_PATH env var
        2) configured exiftool_path (absolute path or command in PATH)
        3) bundled tools/exiftool.exe under app root
        """
        env_path = os.getenv("EXIFTOOL_PATH", "").strip()
        if env_path:
            p = Path(env_path)
            if p.exists():
                return str(p)
            which_env = shutil.which(env_path)
            if which_env:
                return which_env

        # User-provided path or command name
        cfg_path = self.exiftool_path
        p = Path(cfg_path)
        if p.exists():
            return str(p)
        which_cfg = shutil.which(cfg_path)
        if which_cfg:
            return which_cfg

        # Bundled path in installer layout: {app_root}/tools/exiftool.exe
        app_root = Path(__file__).resolve().parents[2]
        bundled = app_root / "tools" / "exiftool.exe"
        if bundled.exists():
            return str(bundled)

        return None

    def write_metadata(self, image_path: str, tags: Dict[str, Any], write_mode: str = "exif"):
        """
        Write tags to the image or to a sidecar, depending on the file format.

        For RAW files, when write_mode is "xmp_sidecar", write a .xmp sidecar
        file next to the image. For JPEG/PNG or write_mode "exif", use ExifTool.
        """
        path = Path(image_path)
        if write_mode == "xmp_sidecar" and path.suffix.lower() in RAW_EXTS:
            return self._write_xmp_sidecar(path, tags)
        return self._write_exif(image_path, tags)

    def _write_xmp_sidecar(self, path: Path, tags: Dict[str, Any]) -> bool:
        """Write a minimal XMP sidecar file next to the RAW image."""
        xmp_path = path.with_suffix(path.suffix + ".xmp")
        try:
            xmp_ns = "adobe:ns:meta/"
            rdf_ns = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            dc_ns = "http://purl.org/dc/elements/1.1/"

            root = ET.Element("xmpmeta", {"xmlns": xmp_ns, "xmp": xmp_ns})
            rdf = ET.SubElement(root, "RDF", {"xmlns": rdf_ns})
            desc = ET.SubElement(rdf, "Description", {"xmlns": dc_ns})

            # Title / Description
            title = tags.get("Title") or tags.get("Description")
            if title:
                title_el = ET.SubElement(desc, "title")
                rdf_bag = ET.SubElement(title_el, "Bag", {"xmlns": rdf_ns})
                li = ET.SubElement(rdf_bag, "li")
                li.text = str(title)

            # Subject / Keywords
            keywords = tags.get("Keywords") or tags.get("Subject")
            if keywords:
                subject_el = ET.SubElement(desc, "subject")
                rdf_bag = ET.SubElement(subject_el, "Bag", {"xmlns": rdf_ns})
                if isinstance(keywords, list):
                    for kw in keywords:
                        if kw is not None:
                            li = ET.SubElement(rdf_bag, "li")
                            li.text = str(kw)
                else:
                    li = ET.SubElement(rdf_bag, "li")
                    li.text = str(keywords)

            # Rights / Copyright
            rights = tags.get("Rights") or tags.get("Copyright")
            if rights:
                rights_el = ET.SubElement(desc, "rights")
                rdf_bag = ET.SubElement(rights_el, "Bag", {"xmlns": rdf_ns})
                li = ET.SubElement(rdf_bag, "li")
                li.text = str(rights)

            # Custom bird metadata as non-DC tags (simplified XML elements)
            for key, value in tags.items():
                if key in ("Title", "Description", "Keywords", "Subject", "Rights", "Copyright"):
                    continue
                if value is not None:
                    el = ET.SubElement(desc, key.replace(":", "_"))
                    el.text = str(value)

            ET.indent(root, space="  ")
            tree = ET.ElementTree(root)
            tree.write(xmp_path, encoding="utf-8", xml_declaration=True)
            logging.debug(f"XMP sidecar written to {xmp_path}")
            return True
        except Exception as e:
            logging.error(f"Failed to write XMP sidecar: {e}")
            return False

    def _write_exif(self, image_path: str, tags: Dict[str, Any]) -> bool:
        """
        Write tags to the image using an argfile to handle character encoding correctly.
        """
        exiftool_cmd = self._resolve_exiftool()
        if not exiftool_cmd:
            logging.warning(
                f"ExifTool not found (configured: '{self.exiftool_path}'). Skipping metadata writing."
            )
            return False

        # Prepare arguments for argfile
        # -charset utf8 is passed to CLI, argfile should be UTF-8.
        # Use -E to allow HTML entities for newlines and special chars
        lines = [
            "-m",
            "-overwrite_original",
            "-charset", "iptc=UTF8",
            "-codedcharacterset=utf8",
            "-E"
        ]

        for tag, value in tags.items():
            if isinstance(value, list):
                # For multi-value tags like Keywords
                for v in value:
                    if v is not None: # Changed from 'if v:' to allow empty strings
                        lines.append(f"-{tag}={v}")
            else:
                if value is not None: # Changed from 'if value:' to allow empty strings
                    # Sanitize: Replace newlines with HTML entity &#xa;
                    # ExifTool with -E will decode this back to a newline
                    safe_value = str(value).replace('\n', '&#xa;')
                    lines.append(f"-{tag}={safe_value}")

        # Add the image path to the argfile to avoid CLI encoding issues on Windows
        lines.append(str(image_path))

        # Write to temporary argfile (UTF-8)
        # delete=False is required on Windows to allow closing before subprocess reads it
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as tf:
                tf.write('\n'.join(lines))
                arg_file = tf.name
        except Exception as e:
            logging.error(f"Failed to create temporary argfile: {e}")
            return False

        try:
            cmd = [
                exiftool_cmd,
                "-charset", "utf8", # Interpret argfile and CLI args as UTF-8
                "-@", arg_file
                # image_path is now IN the argfile
            ]

            # Run ExifTool
            # capture_output=True to suppress stdout unless error
            # Use text=False (binary mode) to avoid UnicodeDecodeError in background reader thread
            # if output is not valid UTF-8 (e.g. system locale warning)
            subprocess.run(cmd, check=True, capture_output=True, text=False)
            logging.debug(f"Metadata written to {image_path}")
            return True

        except subprocess.CalledProcessError as e:
            # Decode stderr safely
            try:
                err_msg = e.stderr.decode('utf-8') if e.stderr else "No stderr"
            except (UnicodeDecodeError, AttributeError):
                # Fallback to system encoding or ignore
                err_msg = e.stderr.decode('mbcs', errors='replace') if e.stderr and os.name == 'nt' else "Failed to decode stderr"

            logging.error(f"Failed to write metadata: {err_msg}")
            return False
        except Exception as e:
            logging.error(f"ExifTool execution error: {e}")
            return False
        finally:
            # Cleanup temp file
            if os.path.exists(arg_file):
                try:
                    os.remove(arg_file)
                except:
                    pass


def quality_score_to_rating(score: Optional[int]) -> int:
    """Map a 0-100 quality score to Lightroom 0-5 star rating."""
    if score is None:
        return 0
    score = max(0, min(100, int(score)))
    if score >= 90:
        return 5
    if score >= 80:
        return 4
    if score >= 70:
        return 3
    if score >= 50:
        return 2
    if score >= 30:
        return 1
    return 0


def build_exif_tags_from_photo(photo: Any) -> Dict[str, Any]:
    """Build ExifTool tag dictionary from a Photo record.

    Fields follow the spec: ImageDescription, XMP:Title, XMP:Description,
    IPTC:Keywords, XMP:Subject, XMP:Pick, XMP:Rating.
    """
    cn = photo.primary_bird_cn or ""
    sci = photo.scientific_name or ""
    location = photo.location_tag or ""
    captured = photo.captured_date or ""

    keywords = [k for k in (cn, sci, location) if k]

    title = " | ".join([p for p in (cn, sci) if p]) or "WingScribe Photo"
    description = " | ".join([p for p in (cn, sci, location, captured) if p]) or "WingScribe Photo"

    pick = "1" if getattr(photo, "is_selected", False) else "0"
    rating = quality_score_to_rating(getattr(photo, "quality_score", None))

    return {
        "ImageDescription": description,
        "XMP:Title": title,
        "XMP:Description": description,
        "IPTC:Keywords": keywords,
        "XMP:Subject": keywords,
        "XMP:Pick": pick,
        "XMP:Rating": rating,
    }


def write_metadata_for_photo(photo: Any, exif_writer: ExifWriter, write_mode: str = "exif") -> bool:
    """Write metadata for a Photo record to its original file.

    For RAW files, write_mode='xmp_sidecar' generates a sidecar file next to
    the original RAW. For JPEG or write_mode='exif', tags are embedded directly.
    """
    image_path = photo.original_path or photo.file_path
    if not image_path or not os.path.exists(image_path):
        logging.warning(f"Cannot write metadata, original file missing: {image_path}")
        return False

    tags = build_exif_tags_from_photo(photo)
    return exif_writer.write_metadata(image_path, tags, write_mode=write_mode)

import os
import sys
import yaml
import logging
import hashlib
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

# Add project root to sys.path to allow running as script
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

from src.metadata.ioc_manager import IOCManager
from src.core.detector import BirdDetector
from src.core.quality import QualityChecker, QualityScorer
from src.core.processor import ImageProcessor
from src.recognition.inference_local import LocalBirdRecognizer
from src.recognition.inference_dongniao import DongniaoRecognizer
from src.recognition.inference_api import APIBirdRecognizer
from src.metadata.exif_writer import (
    ExifWriter,
    write_metadata_for_photo,
    read_capture_datetime,
    read_iso,
)
from src.utils.config_loader import load_config, validate_paths_config
from src.utils.env_check import check_system_dependencies

from src.core.io.local import LocalProvider # Import to access IGNORED_DIRS
from src.core.io.temp_manager import TempFileManager
from src.core.io.path_generator import PathGenerator
from src.core.io.path_parser import PathParser

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _get_process_rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        pass

    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        return -1.0

class SmartScanner:
    def __init__(self, root_path: Path, start_date: str = None, end_date: str = None, exclude_dirs: list = None):
        self.root_path = root_path
        self.start_date = int(start_date) if start_date else 0
        self.end_date = int(end_date) if end_date else 99999999
        # Normalize exclude dirs to absolute paths
        self.exclude_dirs = []
        if exclude_dirs:
            for d in exclude_dirs:
                try:
                    self.exclude_dirs.append(Path(d).resolve())
                except:
                    pass

    def _is_in_range(self, d_start, d_end):
        if not d_start: return True # No date info, assume safe to explore
        
        # d_start is always present if d_end is present
        start_int = int(d_start)
        end_int = int(d_end) if d_end else start_int
        
        # Check intersection
        # Folder range: [start_int, end_int]
        # Query range: [self.start_date, self.end_date]
        return not (end_int < self.start_date or start_int > self.end_date)

    def scan(self, current_path: Path):
        try:
            # First, process files in current dir
            for entry in os.scandir(current_path):
                # Ignore system/recycle directories
                if entry.name in LocalProvider.IGNORED_DIRS:
                    continue

                if entry.is_file():
                    yield entry
                elif entry.is_dir():
                    # Check if this directory should be excluded (output dir)
                    # 不使用 resolve()，避免 UNC 路径问题
                    entry_path = Path(entry.path)
                    if self.exclude_dirs:
                        if any(str(entry_path).startswith(str(ex)) for ex in self.exclude_dirs):
                            logging.debug(f"Excluding output dir: {entry.name}")
                            continue

                    # Check pruning
                    d_start, d_end, _ = PathParser.parse_folder_name(entry.name)

                    if self._is_in_range(d_start, d_end):
                         # Recurse
                         yield from self.scan(Path(entry.path))
                    else:
                        logging.debug(f"Pruning skipped: {entry.name}")
        except PermissionError:
            pass

class WingScribePipeline:
    def __init__(self, config_path: str = "config/settings.yaml", init_timeout: int = 120):
        """
        Initialize the pipeline.

        Args:
            config_path: Path to config file
            init_timeout: Maximum seconds to wait for model loading (default 120s)
        """
        # Use centralized config loader
        self.config = load_config(config_path)

        # Validate paths configuration
        is_valid, errors = validate_paths_config(self.config)
        if not is_valid:
            logging.error(f"Configuration validation failed: {errors}")
            for err in errors:
                logging.error(f"  - {err}")
            raise ValueError(f"Invalid paths configuration: {errors}")

        # Get source directory (photo base directory)
        sources = self.config.get('paths', {}).get('sources', [])
        source_dir = ''
        if sources and len(sources) > 0:
            source_dir = sources[0].get('path', '')

        # Resolve db_path - relative to cwd if not set
        db_path_config = self.config['paths'].get('db_path')
        if db_path_config is None:
            # Default: relative to current working directory
            db_path = Path('data/db/wingscribe.db')
        elif Path(db_path_config).is_absolute():
            db_path = Path(db_path_config)
        else:
            db_path = Path(db_path_config)

        # Path Generator - output.root_dir is optional in new spec (index-only mode)
        paths_conf = self.config['paths']
        out_conf = paths_conf.get('output', {})
        output_root = out_conf.get('root_dir', '')
        if output_root and not Path(output_root).is_absolute():
            raise ValueError("output.root_dir must be absolute path if provided")

        self.db = IOCManager(
            str(db_path),
            source_base_dir=source_dir,
            processed_base_dir=output_root
        )
        self.device = self.config['processing'].get('device', 'cpu')

        # 日志等级配置
        self.log_level = self.config.get('web', {}).get('log_level', 'info').lower()
        self.memory_profile_enabled = os.getenv("WINGSCRIBE_PROFILE_MEMORY") == "1"
        # 进度跟踪
        self.total_files = 0
        self.processed_count = 0
        self._progress_callback = None
        self._stop_checker = None

        # Lazy load detector with timeout protection
        self._detector = None
        self._detector_loaded = False
        self._detector_lock = threading.Lock()
        self._init_timeout = init_timeout

        self.recognizer = None # Lazy load later
        self.exif_writer = ExifWriter()

        self.path_generator = PathGenerator(
            template=out_conf.get('structure_template', "{year}/{location}/{species_cn}/{filename}"),
            output_root=output_root if output_root else "data/output"
        ) if output_root else None
        self.write_back_raw = out_conf.get('write_back_to_source', False)

        # Store source_dir and output_root for relative path conversion and exclusion
        self.source_dir = source_dir
        self.output_root = output_root  # Absolute path for exclusion, may be empty
        
        # Recognizer init lock
        self.batch_lock = threading.Lock()
        self.inference_batch_size = self.config.get('recognition', {}).get('local', {}).get('inference_batch_size', 16)

        # Existing hashes for fast deduplication (loaded on demand)
        self.existing_hashes = None

        # Track photo IDs created during a run for post-processing (e.g. grouping)
        self._new_photo_ids = []

        # Outing associated with this run (for import workflow)
        self.outing_id = None

        # Load taxonomy and config lists (with defaults for backward compatibility)
        paths_config = self.config.get('paths', {})
        self.foreign_countries = self._load_list(paths_config.get('foreign_list', 'config/dictionaries/foreign_countries.txt'))
        self.china_allowlist = self._load_list(paths_config.get('china_list', 'config/dictionaries/china_bird_list.txt'))
        self.all_labels = self._get_taxonomy_labels()

    def set_progress_callback(self, callback):
        """设置进度回调函数"""
        self._progress_callback = callback

    def _log_memory(self, stage: str):
        if not getattr(self, "memory_profile_enabled", False):
            return

        logging.info(
            "[MemoryProfile][Pipeline][%s][thread=%s] rss=%.1fMB recognizer=%s detector_loaded=%s",
            stage,
            threading.current_thread().name,
            _get_process_rss_mb(),
            type(self.recognizer).__name__ if self.recognizer is not None else "None",
            self._detector_loaded,
        )

    def set_stop_checker(self, callback):
        """Register a cooperative stop checker."""
        self._stop_checker = callback

    def _should_stop(self) -> bool:
        stop_checker = getattr(self, "_stop_checker", None)
        if stop_checker is None:
            return False

        try:
            return bool(stop_checker())
        except Exception as exc:
            logging.warning(f"Stop checker failed, ignoring stop signal: {exc}")
            return False

    def _emit_progress(self):
        """发送进度更新"""
        callback = getattr(self, '_progress_callback', None)
        total = getattr(self, 'total_files', 0)
        if callback and total > 0:
            callback(self.processed_count, total)

    @property
    def detector(self):
        """Lazy load detector with thread-safe initialization."""
        # Double-check locking pattern for thread safety
        if self._detector is None:
            with self._detector_lock:
                if self._detector is None and not self._detector_loaded:
                    import signal
                    import functools

                    class TimeoutError(Exception):
                        pass

                    def timeout_handler(signum, frame):
                        raise TimeoutError("Model loading timed out")

                    # Set alarm for timeout (only works on Unix-like systems and main thread)
                    # On Windows or non-main threads, we'll skip the timeout protection
                    use_signal = hasattr(signal, 'SIGALRM') and threading.current_thread() == threading.main_thread()

                    if use_signal:
                        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                        signal.alarm(self._init_timeout)

                    try:
                        logging.info(f"Loading YOLO model: {self.config['processing']['yolo_model']}")
                        self._detector = BirdDetector(
                            self.config['processing']['yolo_model'],
                            self.config['processing']['confidence_threshold'],
                            device=self.device
                        )
                        self._detector_loaded = True
                        logging.info("YOLO model loaded successfully")
                    except TimeoutError:
                        logging.error(f"Detector loading timed out after {self._init_timeout} seconds")
                        self._detector_loaded = True
                        raise
                    except Exception as e:
                        logging.error(f"Failed to load detector: {e}")
                        raise
                    finally:
                        if use_signal:
                            signal.alarm(0)
                            signal.signal(signal.SIGALRM, old_handler)

        return self._detector

    def _load_list(self, path_str):
        path = Path(path_str)
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return set(line.strip() for line in f if line.strip())
        return set()

    def _calculate_file_hash(self, provider, file_path: str, size: int) -> str:
        """
        Calculate partial SHA256 hash for fast deduplication.
        """
        sha256 = hashlib.sha256()
        
        data = provider.read_bytes(file_path)
        
        if size < 12288:
             sha256.update(data)
        else:
             sha256.update(data[:4096])
             sha256.update(data[size//2 : size//2 + 4096])
             sha256.update(data[-4096:])

        return f"{size}_{sha256.hexdigest()}"

    def _get_taxonomy_labels(self):
        # Check if DB is empty
        cursor = self.db.conn.execute("SELECT count(*) FROM taxonomy")
        count = cursor.fetchone()[0]

        if count == 0:
            logging.warning("Taxonomy table is empty! Attempting auto-import from Excel...")

            # Try to find IOC Excel file
            refs_dir = Path(self.config['paths'].get('references_path', 'data/references'))
            excel_file = None

            # First try configured path (with quotes handling for spaces)
            configured_path = self.config['paths'].get('ioc_list_path', '')
            if configured_path:
                p = Path(configured_path)
                if p.exists():
                    excel_file = p
                    logging.info(f"Using configured IOC file: {excel_file}")

            # If not found, search in references directory for Multiling IOC file
            if excel_file is None and refs_dir.exists():
                for f in sorted(refs_dir.glob("*.xlsx")):
                    # Look for Multiling IOC files (they have the correct format)
                    name_lower = f.name.lower()
                    if 'multiling' in name_lower and 'ioc' in name_lower:
                        excel_file = f
                        logging.info(f"Found IOC file: {excel_file}")
                        break

            if excel_file and excel_file.exists():
                try:
                    refs_dir = str(self.config['paths'].get('references_path', 'data/references'))
                    self.db.import_from_excel(str(excel_file), refs_dir=refs_dir)
                    # Verify import
                    cursor = self.db.conn.execute("SELECT count(*) FROM taxonomy")
                    count = cursor.fetchone()[0]
                    logging.info(f"Auto-import completed. Taxonomy count: {count}")
                except Exception as e:
                    logging.error(f"Failed to import Excel: {e}")
            else:
                logging.error(f"IOC Excel file not found. Searched: {refs_dir}")

        # Fetch all scientific names from taxonomy table
        cursor = self.db.conn.execute("SELECT scientific_name FROM taxonomy")
        all_labels = [row[0] for row in cursor.fetchall()]
        logging.info(f"Loaded {len(all_labels)} total labels from DB.")
        return all_labels

    def _select_candidate_labels(self, location_tag: str):
        mode = self.config.get('recognition', {}).get('region_filter')
        
        if mode == 'china':
            if not self.china_allowlist:
                 return self.all_labels
            return [name for name in self.all_labels if name in self.china_allowlist]
            
        if mode == 'auto':
            is_foreign = False
            for country in self.foreign_countries:
                if country in location_tag:
                    is_foreign = True
                    break
            
            if is_foreign:
                return self.all_labels
            else:
                if not self.china_allowlist:
                    return self.all_labels
                return [name for name in self.all_labels if name in self.china_allowlist]

        return self.all_labels

    def _init_recognizer(self):
        """
        Lazy load the recognizer to save resources if no birds are found.
        """
        rec_config = self.config['recognition']
        mode = rec_config.get('mode', 'local')
        hf_mirror = rec_config.get('hf_mirror')

        if mode == 'local':
            conf = rec_config.get('local', {})
            self.recognizer = LocalBirdRecognizer(
                model_name=conf.get('model_type', 'bioclip'),
                device=self.device,
                hf_mirror=hf_mirror
            )
        elif mode == 'dongniao':
            conf = rec_config.get('dongniao', {})
            self.recognizer = DongniaoRecognizer(
                api_key=conf.get('key'),
                api_url=conf.get('url')
            )
        elif mode == 'api':
             conf = rec_config.get('api', {})
             self.recognizer = APIBirdRecognizer(
                 api_key=conf.get('key'),
                 api_url=conf.get('url')
             )
        else:
            logging.error(f"Unknown recognition mode: {mode}")
            raise ValueError(f"Unknown recognition mode: {mode}")

        self._log_memory(f"after_recognizer_init mode={mode}")

    def _recognize_batch(self, items, candidate_labels):
        if not items:
            return

        try:
            image_paths = [item['crop_path'] for item in items]
            top_k = self.config.get('recognition', {}).get('top_k', 5)
            self._log_memory(f"before_recognize_batch items={len(items)} labels={len(candidate_labels)}")

            if hasattr(self.recognizer, 'predict_batch'):
                batch_results = self.recognizer.predict_batch(image_paths, candidate_labels, top_k=top_k)
            else:
                batch_results = [
                    self.recognizer.predict(p, candidate_labels, top_k=top_k)
                    for p in image_paths
                ]
            self._log_memory(f"after_recognize_batch items={len(items)} labels={len(candidate_labels)}")

            alt_threshold = self.config.get('recognition', {}).get('alternatives_threshold', 70)
            low_conf_threshold = self.config.get('recognition', {}).get('low_confidence_threshold', 60)

            for item, results in zip(items, batch_results):
                self._archive_item(item, results, alt_threshold, low_conf_threshold)
        except Exception as e:
            logging.error(f"Batch processing failed: {e}", exc_info=True)
            for item in items:
                try: os.remove(item['crop_path'])
                except: pass

    def _archive_item(self, item, results, alt_threshold, low_conf_threshold):
        entry = item['entry']
        meta = item['meta']
        temp_crop_path = item['crop_path']
        detections_len = item['detections_count']
        i_det = item['detection_index']
        img_width = item['width']
        img_height = item['height']
        file_hash = item['file_hash']

        quality_score = item.get('quality_score', 0)
        quality_details = item.get('quality_details', {})
        bird_bbox = item.get('bird_bbox')
        candidates_data = []

        # Initialize default values
        is_low_conf = False
        cn_name = "Unknown"
        sci_name = "Unknown"
        user_comment = "No recognition results."

        if not results:
            top_result = {"scientific_name": "Unknown", "confidence": 0.0}
        else:
            top_result = results[0]
            top_conf_pct = top_result['confidence'] * 100
            is_low_conf = top_conf_pct < low_conf_threshold
            
            comment_lines = []
            candidates_data = []
            
            show_alternatives = (top_conf_pct <= alt_threshold) or is_low_conf
            display_results = results if show_alternatives else [results[0]]

            for i, res in enumerate(results):
                r_sci = res.get('scientific_name') or 'Unknown'
                r_conf = res['confidence'] * 100
                r_info = self.db.get_bird_info(r_sci)
                r_cn = r_info['chinese_name'] if r_info else r_sci
                
                candidates_data.append({"sci": r_sci, "cn": r_cn, "score": float(res['confidence'])})

                if i < len(display_results):
                    if i == 0:
                        prefix = "Top Match" if not is_low_conf else "Low Confidence Match"
                        comment_lines.append(f"{prefix}: {r_cn} ({r_sci}) - {r_conf:.1f}%")
                        if show_alternatives and len(results) > 1:
                            comment_lines.append("Alternatives:")
                    else:
                        comment_lines.append(f"{i}. {r_cn} ({r_sci}) - {r_conf:.1f}%")
            
            user_comment = "&#xa;".join(comment_lines)

        if is_low_conf:
            cn_name = "待确认鸟种"
            sci_name = "Uncertain"
        else:
            sci_name = top_result['scientific_name']
            bird_info = self.db.get_bird_info(sci_name)
            cn_name = bird_info['chinese_name'] if bird_info else sci_name
        
        confidence = top_result['confidence']
        
        # Common variables for both modes
        raw_exts = {'.nef', '.orf', '.cr2', '.cr3', '.arw', '.dng', '.rw2', '.pef', '.raf'}
        ext = Path(entry.path).suffix.lower()
        photo_id = item.get('photo_id')
        
        # Generate output path if output_root is configured; otherwise keep original file
        if self.path_generator is not None:
            gen_meta = {
                'captured_date': meta.get('captured_date', '00000000'),
                'location_tag': meta.get('location_tag', 'Unknown'),
                'primary_bird_cn': cn_name,
                'scientific_name': sci_name,
                'confidence_score': confidence,
                'source_structure': meta.get('source_structure', '.')
            }
            
            current_filename = entry.name
            if detections_len > 1:
                base = Path(entry.name).stem
                ext = Path(entry.name).suffix
                current_filename = f"{base}_{i_det+1}{ext}"
            # Normalize archived image to JPEG regardless of original format
            if not current_filename.lower().endswith(('.jpg', '.jpeg')):
                current_filename = Path(current_filename).with_suffix('.jpg').name

            final_path = self.path_generator.generate_path(gen_meta, current_filename)
            Path(final_path).parent.mkdir(parents=True, exist_ok=True)
            
            try:
                # The recognizer needs a square crop, but the archived/processed
                # image shown in the UI should preserve the bird crop's aspect
                # ratio to avoid distortion.
                source_path = item.get('source_path') or temp_crop_path
                ImageProcessor.crop_and_resize(
                    source_path,
                    bird_bbox,
                    str(final_path),
                    target_size=self.config['processing']['target_size'],
                    padding=self.config['processing']['crop_padding'],
                    preserve_aspect=True,
                )
                try:
                    os.remove(temp_crop_path)
                except Exception:
                    pass
            except Exception as e:
                logging.error(f"Failed to generate preserved-aspect crop to {final_path}: {e}")
                return
            
            if is_low_conf:
                description = "Uncertain Bird (Low Confidence)"
                keywords = ["WingScribe", "LowConfidence", meta.get('location_tag')]
            else:
                description = f"{cn_name} ({sci_name})"
                keywords = [cn_name, sci_name, meta.get('location_tag'), "WingScribe"]

            # Filter out None values from keywords
            keywords = [k for k in keywords if k is not None]

            self.exif_writer.write_metadata(str(final_path), {
                'ImageDescription': description,
                'XMP:Description': description,
                'XPTitle': description,
                'XPSubject': "",
                'Keywords': keywords,
                'UserComment': user_comment
            })
            write_metadata_for_photo_mode = "xmp_sidecar" if ext in raw_exts else "exif"
            db_file_path = str(final_path)
            db_filename = Path(final_path).name
        else:
            # Index-only mode: keep original file path, do not write metadata back
            db_file_path = entry.path
            db_filename = entry.name
            write_metadata_for_photo_mode = None
            try:
                os.remove(temp_crop_path)
            except Exception:
                pass
        
        # Store absolute paths for database
        captured_at = read_capture_datetime(self.exif_writer, entry.path)
        if isinstance(captured_at, datetime):
            captured_at = captured_at.isoformat()
        if photo_id is not None:
            update_record = {
                'file_path': db_file_path,
                'filename': db_filename,
                'original_path': entry.path,
                'file_hash': file_hash,
                'captured_date': meta.get('captured_date'),
                'captured_at': captured_at,
                'location_tag': meta.get('location_tag'),
                'location_level1': meta.get('location_level1'),
                'location_level2': meta.get('location_level2'),
                'location_level3': meta.get('location_level3'),
                'primary_bird_cn': cn_name,
                'scientific_name': sci_name,
                'confidence_score': confidence,
                'width': img_width,
                'height': img_height,
                'candidates_json': json.dumps(candidates_data, ensure_ascii=False),
                'quality_score': quality_score,
                'quality_details': quality_details,
                'bird_bbox': bird_bbox,
            }
            if self.outing_id is not None:
                update_record['outing_id'] = self.outing_id
            self.db.update_photo_record(photo_id, update_record)
            self._new_photo_ids.append(photo_id)
        else:
            new_record = {
                'file_path': db_file_path,
                'filename': db_filename,
                'original_path': entry.path,
                'file_hash': file_hash,
                'captured_date': meta.get('captured_date'),
                'captured_at': captured_at,
                'location_tag': meta.get('location_tag'),
                'location_level1': meta.get('location_level1'),
                'location_level2': meta.get('location_level2'),
                'location_level3': meta.get('location_level3'),
                'primary_bird_cn': cn_name,
                'scientific_name': sci_name,
                'confidence_score': confidence,
                'width': img_width,
                'height': img_height,
                'candidates_json': json.dumps(candidates_data, ensure_ascii=False),
                'quality_score': quality_score,
                'quality_details': quality_details,
                'bird_bbox': bird_bbox,
            }
            if self.outing_id is not None:
                new_record['outing_id'] = self.outing_id
            new_photo_id = self.db.add_photo_record(new_record)
            if new_photo_id:
                self._new_photo_ids.append(new_photo_id)
        
        # Write metadata to original file (JPEG embed, RAW sidecar) only when output is enabled
        if write_metadata_for_photo_mode is not None:
            ext = Path(entry.path).suffix.lower()
            write_mode = "xmp_sidecar" if ext in raw_exts else "exif"
            meta_record = SimpleNamespace(
                original_path=entry.path,
                file_path=entry.path,
                primary_bird_cn=cn_name,
                scientific_name=sci_name,
                location_tag=meta.get('location_tag'),
                captured_date=meta.get('captured_date'),
                quality_score=quality_score,
                is_selected=False,
            )
            write_metadata_for_photo(meta_record, self.exif_writer, write_mode=write_mode)
        
        log_name = cn_name if not is_low_conf else f"Uncertain ({top_result['scientific_name']})"
        # 根据日志等级决定输出详细程度
        if getattr(self, 'log_level', 'info') == 'debug':
            logging.info(f"Processed: {entry.name} -> {log_name} ({confidence*100:.1f}%)")
        # 更新进度
        self.processed_count = getattr(self, 'processed_count', 0) + 1
        if getattr(self, '_emit_progress', None):
            self._emit_progress()

    def process_image(self, provider, entry, meta, photo_id=None):
        # 1. Deduplication (skip when re-processing an already indexed photo)
        if photo_id is None:
            file_hash = self._calculate_file_hash(provider, entry.path, entry.size)
            # Use in-memory set if available (much faster), otherwise fallback to database
            if self.existing_hashes is not None:
                if file_hash in self.existing_hashes:
                    logging.debug(f"Skipping duplicate (in-memory): {entry.name}")
                    return
            elif self.db.check_hash_exists(file_hash):
                logging.debug(f"Skipping duplicate: {entry.name}")
                return
        else:
            # Recalculate hash for existing record to ensure consistency
            file_hash = self._calculate_file_hash(provider, entry.path, entry.size)

        local_source_path = provider.get_local_path(entry.path)
        if not local_source_path: return

        decoded_temp_path = None
        try:
            # For RAW formats, decode to a temporary JPEG first
            if ImageProcessor.is_raw(local_source_path):
                temp_dir = Path(self.output_root) / "temp" if self.output_root else Path("data/temp")
                temp_dir.mkdir(parents=True, exist_ok=True)
                decoded_temp_path = ImageProcessor.decode_raw_to_temp_jpg(local_source_path, str(temp_dir))
                detection_input_path = decoded_temp_path
            else:
                detection_input_path = local_source_path

            # 2. Detect (Thread-safe if YOLO is)
            try:
                detections = self.detector.detect(detection_input_path)
            except Exception as e:
                logging.error(f"Detection failed for {entry.name}: {e}")
                return

            if not detections: return

            # Init recognizer if needed (double check locking if lazily init)
            if self.recognizer is None:
                with self.batch_lock:
                    if self.recognizer is None: self._init_recognizer()

            # 3. Candidate labels for this image only.
            location_tag = meta.get('location_tag', 'Unknown')
            candidates = self._select_candidate_labels(location_tag)

            # 4. Crop & recognize as an image-local batch.
            img_width, img_height = 0, 0
            try:
                from PIL import Image
                with Image.open(detection_input_path) as tmp_img:
                    img_width, img_height = tmp_img.size
            except: pass

            image_batch_items = []

            for i, (box, score) in enumerate(detections):
                temp_dir = Path(self.output_root) / "temp" if self.output_root else Path("data/temp")
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_crop_path = temp_dir / f"temp_{entry.name}_{i}.jpg"

                success = ImageProcessor.crop_and_resize(
                    detection_input_path, box, str(temp_crop_path),
                    target_size=self.config['processing']['target_size'],
                    padding=self.config['processing']['crop_padding']
                )

                if success:
                    # 5. Quality scoring (5-dim weighted score: clarity, contrast, exposure, subject_size, iso)
                    exif_writer = getattr(self, "exif_writer", None)
                    iso = read_iso(exif_writer, local_source_path) if exif_writer and local_source_path else None
                    quality_result = QualityScorer().score_from_path(str(temp_crop_path), box, iso=iso)
                    quality_score = quality_result["score"]
                    quality_details = quality_result["details"]

                    # 6. Blur detection (legacy quality check)
                    blur_threshold = self.config.get('processing', {}).get('blur_threshold', 40.0)
                    if blur_threshold > 0:
                        blur_score = QualityChecker.calculate_blur_score(str(temp_crop_path))
                        if blur_score < blur_threshold:
                            logging.info(f"[Quality] blur_score={blur_score:.1f} < {blur_threshold} SKIP - {temp_crop_path.name}")
                            try:
                                os.remove(str(temp_crop_path))
                            except:
                                pass
                            continue

                    image_batch_items.append({
                        'entry': entry,
                        'meta': meta,
                        'crop_path': str(temp_crop_path),
                        'source_path': detection_input_path,
                        'file_hash': file_hash,
                        'width': img_width,
                        'height': img_height,
                        'bird_bbox': box,
                        'detection_index': i,
                        'detections_count': len(detections),
                        'quality_score': quality_score,
                        'quality_details': quality_details,
                        'photo_id': photo_id,
                    })

            self._recognize_batch(image_batch_items, candidates)
        finally:
            # Clean up the temporary decoded JPEG for RAW files
            if decoded_temp_path and Path(decoded_temp_path).exists():
                try:
                    os.remove(decoded_temp_path)
                except Exception:
                    pass

    def process_image_by_id(self, provider, photo_record: dict, meta: dict):
        """Process an already-indexed photo by its database record."""
        from types import SimpleNamespace

        class PhotoEntry:
            def __init__(self, record):
                self.path = record['file_path'] or record['original_path']
                self.name = record['filename']
                self.size = Path(self.path).stat().st_size if Path(self.path).exists() else 0

        entry = PhotoEntry(photo_record)
        return self.process_image(provider, entry, meta, photo_id=photo_record['id'])

    def run_by_photo_ids(self, photo_ids: list, progress_callback=None, outing_id: int = None):
        """Run recognition on already indexed photos by their IDs."""
        t_start = time.time()
        start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stop_requested = False

        self._progress_callback = progress_callback
        self._new_photo_ids = []
        self.outing_id = outing_id
        self.total_files = len(photo_ids)
        self.processed_count = 0
        self._emit_progress()

        # Load photo records from database
        records = []
        for pid in photo_ids:
            row = self.db.conn.execute(
                "SELECT id, file_path, filename, original_path, captured_date, location_tag, location_level1, location_level2, location_level3 FROM photos WHERE id = ?",
                (pid,)
            ).fetchone()
            if row:
                records.append(dict(row))

        if not records:
            logging.info("No photos found for the provided IDs")
            self.outing_id = None
            return

        logging.info(f"Running recognition for {len(records)} indexed photos")

        provider = LocalProvider(base_dir=None)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for record in records:
                if self._should_stop():
                    stop_requested = True
                    break

                file_path = record.get('file_path') or record.get('original_path')
                if not file_path or not Path(file_path).exists():
                    logging.warning(f"Photo file not found for ID {record['id']}: {file_path}")
                    self.processed_count += 1
                    self._emit_progress()
                    continue

                source_root = Path(file_path).parent
                parser = PathParser(source_root, None)
                meta = parser.parse(file_path)
                # Override location/captured_date with DB values if available
                if record.get('captured_date'):
                    meta['captured_date'] = record['captured_date']
                if record.get('location_tag'):
                    meta['location_tag'] = record['location_tag']
                if record.get('location_level1'):
                    meta['location_level1'] = record['location_level1']
                if record.get('location_level2'):
                    meta['location_level2'] = record['location_level2']
                if record.get('location_level3'):
                    meta['location_level3'] = record['location_level3']

                futures.append(executor.submit(self.process_image_by_id, provider, record, meta))

                if len(futures) > 500:
                    done, not_done = wait(futures, timeout=0.1)
                    futures = list(not_done)

            if futures:
                done, not_done = wait(futures)
                for future in done:
                    exc = future.exception()
                    if exc:
                        logging.error(f"process_image_by_id failed: {exc}", exc_info=True)

        t_end = time.time()
        duration = t_end - t_start
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.db.add_scan_history({
            'start_time': start_time_str,
            'end_time': end_time_str,
            'range_start': "Photo IDs",
            'range_end': str(len(photo_ids)),
            'processed_count': len(records),
            'duration_seconds': round(duration, 2),
            'status': 'Stopped' if stop_requested else 'Completed'
        })

        logging.info(f"Pipeline (by photo IDs) completed. Processed: {len(records)}. Duration: {duration:.2f}s")
        self._group_new_photos()
        self.outing_id = None

    def run(self, start_date: str = None, end_date: str = None, existing_hashes: set = None):
        t_start = time.time()
        start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        processed_count = 0
        stop_requested = False

        # Use provided hashes or load from database
        if existing_hashes is not None:
            self.existing_hashes = existing_hashes
            logging.info(f"Using provided existing_hashes set with {len(existing_hashes)} entries")
        elif self.existing_hashes is None:
            # Lazy load from database on first run
            logging.info("Loading existing hashes from database...")
            self.existing_hashes = self.db.get_all_hashes()
            logging.info(f"Loaded {len(self.existing_hashes)} existing hashes from database")

        if start_date:
            logging.info(f"Pipeline Filter: Range [{start_date} - {end_date or 'Max'}]")

        sources = self.config['paths'].get('sources', [])
        # Fallback for old config
        if not sources and 'raw_dir' in self.config['paths']:
             sources = [{'path': self.config['paths']['raw_dir'], 'recursive': False}]

        # source.path is now always absolute (required), no conversion needed

        # Use ThreadPool for detection/cropping
        # 4 workers is a good start for IO/CPU bound mix
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []

            for source in sources:
                if self._should_stop():
                    stop_requested = True
                    logging.info("Stop requested before scanning next source, stopping pipeline submission")
                    break

                if not source.get('enabled', True):
                    continue

                path_str = source['path']
                recursive = source.get('recursive', True)
                structure_pattern = source.get('structure_pattern', None)

                logging.info(f"Scanning source: {path_str} (Recursive: {recursive})")

                # 使用 LocalProvider 替代 fs_manager
                provider = LocalProvider(base_dir=self.source_dir)
                if not provider.exists(path_str):
                    logging.warning(f"Source path not found: {path_str}")
                    continue

                source_root_abs = Path(provider.get_local_path(path_str))
                parser = PathParser(source_root_abs, structure_pattern)

                # Get output directory to exclude from scanning (use pre-resolved absolute path)
                exclude_dirs = [self.output_root] if self.output_root else []

                iterator = []
                if recursive and (start_date or end_date):
                    scanner = SmartScanner(source_root_abs, start_date, end_date, exclude_dirs)
                    iterator = scanner.scan(source_root_abs)
                else:
                    iterator = provider.list_dir(path_str, recursive=recursive)

                # 收集有效的图片文件并统计总数
                valid_entries = []
                supported_formats = self.config.get('paths', {}).get('supported_formats', ['.jpg', '.jpeg'])
                supported_suffixes = tuple(fmt.lower() for fmt in supported_formats)
                for entry in iterator:
                    is_dir = entry.is_dir() if callable(entry.is_dir) else entry.is_dir
                    if is_dir: continue

                    entry_name = entry.name
                    entry_path = entry.path

                    # Skip files in output directory
                    if self.output_root:
                        try:
                            entry_path_obj = Path(entry_path)
                            output_path_obj = Path(self.output_root)
                            entry_norm = os.path.normpath(str(entry_path_obj))
                            output_norm = os.path.normpath(str(output_path_obj))
                            if entry_norm.startswith(output_norm):
                                logging.debug(f"Skipping output file: {entry_name}")
                                continue
                        except:
                            pass

                    if not entry_name.lower().endswith(supported_suffixes):
                        continue

                    valid_entries.append((entry, entry_path))

                # 设置进度总数
                self.total_files += len(valid_entries)
                self._emit_progress()

                for entry, entry_path in valid_entries:
                    if self._should_stop():
                        stop_requested = True
                        logging.info("Stop requested, stopping new task submission")
                        break

                    meta = parser.parse(entry_path)
                    
                    c_date = meta.get('captured_date')
                    if start_date and c_date:
                        if int(c_date) < int(start_date): continue
                    if end_date and c_date:
                        if int(c_date) > int(end_date): continue

                    if not hasattr(entry, 'size'):
                        class Adapter:
                            def __init__(self, e):
                                self.path = e.path
                                self.name = e.name
                                self.size = e.stat().st_size
                        entry_obj = Adapter(entry)
                    else:
                        entry_obj = entry
                        
                    processed_count += 1
                    # Submit task to pool
                    futures.append(executor.submit(self.process_image, provider, entry_obj, meta))
                    
                    # Prevent memory explosion from too many futures
                    if len(futures) > 500:
                        done, not_done = wait(futures, timeout=0.1)
                        futures = list(not_done)

                if stop_requested:
                    break

            # Wait for all tasks to complete
            if futures:
                wait(futures)

        t_end = time.time()
        duration = t_end - t_start
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        self.db.add_scan_history({
            'start_time': start_time_str,
            'end_time': end_time_str,
            'range_start': start_date or "All",
            'range_end': end_date or "All",
            'processed_count': processed_count,
            'duration_seconds': round(duration, 2),
            'status': 'Stopped' if stop_requested else 'Completed'
        })
        if stop_requested:
            logging.info(f"Pipeline stopped by request. Processed: {processed_count}. Duration: {duration:.2f}s")
        else:
            logging.info(f"Pipeline completed. Processed: {processed_count}. Duration: {duration:.2f}s")

        self._group_new_photos()

    def _group_new_photos(self):
        """Group newly archived photos by burst capture time window."""
        if not getattr(self, "_new_photo_ids", None):
            return

        try:
            group_config = self.config.get("grouper", {})
            if not group_config.get("enabled", True):
                return

            time_window = group_config.get("time_window", 5)
            photo_ids = list(self._new_photo_ids)
            self._new_photo_ids = []

            # Only group photos that haven't been assigned already
            ungrouped_ids = self.db.get_photos_without_group(photo_ids)
            if not ungrouped_ids:
                return

            grouped = self.db.group_photo_ids(ungrouped_ids, time_window_seconds=time_window)
            if not grouped:
                return

            # Filter out single-photo groups (no need to create a group for one image)
            multi_groups = [g for g in grouped if len(g) > 1]
            if not multi_groups:
                return

            self.db.save_photo_groups(multi_groups, outing_id=self.outing_id)
            logging.info(f"Created {len(multi_groups)} burst groups from {len(ungrouped_ids)} new photos")
        except Exception as e:
            logging.error(f"Failed to group new photos: {e}")

    def run_by_folders(self, folder_paths: list, recursive: bool = True):
        """
        Run pipeline for specific folders only, ignoring date range filters.

        Args:
            folder_paths: List of folder paths (now always absolute)
            recursive: If True, scan subdirectories recursively
        """
        t_start = time.time()
        start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        processed_count = 0
        stop_requested = False

        # Ensure existing_hashes is loaded
        if self.existing_hashes is None:
            logging.info("Loading existing hashes from database...")
            self.existing_hashes = self.db.get_all_hashes()
            logging.info(f"Loaded {len(self.existing_hashes)} existing hashes from database")

        logging.info(f"Running pipeline for folders: {folder_paths} (recursive={recursive})")

        # Get configured sources to find the correct source_root for PathParser
        sources = self.config.get('paths', {}).get('sources', [])
        source_roots = {}  # Map: resolved source path -> PathParser source_root

        for source in sources:
            if not source.get('enabled', True):
                continue
            path_str = source.get('path', '')
            if path_str:
                source_roots[path_str] = path_str  # Use source root itself as source_root for PathParser

        # If no sources configured, fall back to source_dir
        if not source_roots:
            source_roots = {self.source_dir: self.source_dir}

        # folder_paths are now always absolute, no resolution needed
        resolved_paths = list(folder_paths)

        # Use ThreadPool for detection/cropping
        # For run_by_folders, folder_paths are explicit absolute paths that may lie outside
        # configured sources, so use a provider with no base restriction.
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []

            provider = LocalProvider(base_dir=None)

            for path_str in resolved_paths:
                if self._should_stop():
                    stop_requested = True
                    logging.info("Stop requested before scanning next folder, stopping pipeline submission")
                    break

                if not provider.exists(path_str):
                    logging.warning(f"Folder path not found: {path_str}")
                    continue

                # Find the correct source_root for PathParser
                # Use the longest matching source root
                source_root_abs = None
                parent_path_str = str(Path(path_str).parent)
                for src_root in source_roots:
                    src_root_str = str(src_root)
                    if path_str.startswith(src_root_str) or (src_root_str and parent_path_str.startswith(src_root_str)):
                        source_root_abs = Path(src_root_str)
                        break

                if source_root_abs is None:
                    # Fallback: use the import folder itself as source_root
                    source_root_abs = Path(path_str)

                parser = PathParser(source_root_abs, None)

                # Get output directory to exclude
                exclude_dirs = [self.output_root] if self.output_root else []

                logging.info(f"Scanning folder: {path_str} (Recursive: {recursive}, source_root: {source_root_abs})")

                # List files in folder (recursive or not)
                if recursive:
                    iterator = self._scan_folder_recursive(provider, path_str)
                else:
                    iterator = provider.list_dir(path_str, recursive=False)

                # 收集有效的图片文件
                supported_formats = self.config.get('paths', {}).get('supported_formats', ['.jpg', '.jpeg'])
                supported_suffixes = tuple(fmt.lower() for fmt in supported_formats)
                valid_entries = []
                for entry in iterator:
                    is_dir = entry.is_dir() if callable(entry.is_dir) else entry.is_dir
                    if is_dir:
                        continue

                    entry_name = entry.name
                    entry_path = entry.path

                    # Skip files in output directory
                    if self.output_root:
                        try:
                            entry_path_obj = Path(entry_path)
                            output_path_obj = Path(self.output_root)
                            entry_norm = os.path.normpath(str(entry_path_obj))
                            output_norm = os.path.normpath(str(output_path_obj))
                            if entry_norm.startswith(output_norm):
                                logging.debug(f"Skipping output file: {entry_name}")
                                continue
                        except:
                            pass

                    if not entry_name.lower().endswith(supported_suffixes):
                        continue

                    valid_entries.append((entry, entry_path))

                # 设置进度总数
                self.total_files += len(valid_entries)
                self._emit_progress()

                for entry, entry_path in valid_entries:
                    if self._should_stop():
                        stop_requested = True
                        logging.info("Stop requested, stopping new task submission")
                        break

                    # Parse path metadata (without date filtering)
                    meta = parser.parse(entry_path)

                    if not hasattr(entry, 'size'):
                        class Adapter:
                            def __init__(self, e):
                                self.path = e.path
                                self.name = e.name
                                self.size = e.stat().st_size
                        entry_obj = Adapter(entry)
                    else:
                        entry_obj = entry

                    processed_count += 1
                    # Submit task to pool
                    futures.append(executor.submit(self.process_image, provider, entry_obj, meta))

                    # Prevent memory explosion
                    if len(futures) > 500:
                        done, not_done = wait(futures, timeout=0.1)
                        futures = list(not_done)

                if stop_requested:
                    break

            # Wait for all tasks to complete
            if futures:
                wait(futures)

        t_end = time.time()
        duration = t_end - t_start
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.db.add_scan_history({
            'start_time': start_time_str,
            'end_time': end_time_str,
            'range_start': "Folders: " + ",".join(folder_paths),
            'range_end': "",
            'processed_count': processed_count,
            'duration_seconds': round(duration, 2),
            'status': 'Stopped' if stop_requested else 'Completed'
        })
        if stop_requested:
            logging.info(f"Pipeline (by folders) stopped by request. Processed: {processed_count}. Duration: {duration:.2f}s")
        else:
            logging.info(f"Pipeline (by folders) completed. Processed: {processed_count}. Duration: {duration:.2f}s")

        self._group_new_photos()

    def _scan_folder_recursive(self, provider, folder_path: str):
        """
        Recursively scan a folder, excluding output directories.
        Yields file entries.
        """
        exclude_dirs = [self.output_root] if self.output_root else []

        try:
            for entry in provider.list_dir(folder_path, recursive=False):
                is_dir = entry.is_dir() if callable(entry.is_dir) else entry.is_dir

                if is_dir:
                    # Check if should exclude
                    entry_path = str(Path(entry.path))
                    should_exclude = False
                    if exclude_dirs:
                        for excl in exclude_dirs:
                            if entry_path.startswith(os.path.normpath(excl)):
                                should_exclude = True
                                break

                    if should_exclude:
                        continue

                    # Recursively scan subfolder
                    yield from self._scan_folder_recursive(provider, entry.path)
                else:
                    yield entry
        except Exception as e:
            logging.warning(f"Error scanning folder {folder_path}: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run WingScribe pipeline")
    parser.add_argument("--config", default="config/settings.yaml", help="Path to settings YAML")
    args = parser.parse_args()

    config_path = args.config
    config = load_config(config_path)

    if not check_system_dependencies(config):
        logging.error("System check failed. Please fix the issues above and restart.")
        sys.exit(1)

    runner = WingScribePipeline(config_path)
    runner.run()

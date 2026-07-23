import logging
import sys
import shutil
import os
import gc
import asyncio
import json
import platform
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode
from fastapi import FastAPI, Request, HTTPException, WebSocket, Query
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from typing import Optional, List, Any, Dict

# Add project root to path for imports
BASE_DIR = Path(__file__).parent.parent.parent.absolute()
sys.path.append(str(BASE_DIR))

from src.core.quality import QualityScorer
from src.core.processor import ImageProcessor
from src.metadata.exif_writer import ExifWriter, write_metadata_for_photo, read_exif_summary
from src.utils.config_loader import load_config, validate_paths_config
from src.core.io.path_generator import PathGenerator
from src.core.indexer import PhotoIndexer
from src.db.models import init_database as init_sqlalchemy_db, Photo, Species, PhotoGroup, Outing
from src.db.repository import PhotoRepository, OutingRepository
from src.web.routes.recognition import router as recognition_router
from src.web import task_manager as task_manager_module
from src.web.task_manager import TaskManager as ExtractedTaskManager
from src.web import taxonomy_service
from src.web import pipeline_service
from src.web import admin_service
from src.web import import_service
from src.web.config_helpers import (
    get_config_definition,
    get_nested_value,
    set_nested_value,
)
from src.web import path_helpers
from src.web import config_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize ExifWriter
exif_writer = ExifWriter()

TaskManager = ExtractedTaskManager
threading = task_manager_module.threading
task_manager = TaskManager.get_instance()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_app_db()
    logger.info("Application started.")
    yield
    # Shutdown
    logger.info("Application shutting down...")
    if task_manager.is_running:
        logger.info("Stopping pipeline...")
        task_manager.stop()

app = FastAPI(lifespan=lifespan)

# Load config
config = load_config(str(BASE_DIR / "config" / "settings.yaml"), str(BASE_DIR / "config" / "secrets.yaml"))

# Initialize import service after config is loaded
import_service_instance = import_service.ImportService(task_manager, config)

# Initialize metadata writer
exif_writer = ExifWriter()

# Validate paths configuration
is_valid, errors = validate_paths_config(config)
if not is_valid:
    logger.error(f"Configuration validation failed: {errors}")
    for err in errors:
        logger.error(f"  - {err}")
    raise ValueError(f"Invalid paths configuration: {errors}")

# Get source directories for raw photo path resolution
sources = config['paths'].get('sources', [])
source_dirs = [
    Path(src.get('path'))
    for src in sources
    if src.get('path')
]
source_dir = ''
if sources and len(sources) > 0:
    source_dir = sources[0].get('path', '')
if source_dir:
    source_dir = Path(source_dir)

# Server startup parameters (used for restart)
_startup_host = None
_startup_port = None
_startup_python = sys.executable

# Helper function to check if path is absolute (handles both Windows and Unix formats)
def is_absolute_path(p: str) -> bool:
    """Check if path is absolute, including Windows drive letter format like 'Y:/path'"""
    return path_helpers.is_absolute_path(p)

# Resolve db_path - relative to current working directory if not set or empty
db_path_config = config['paths'].get('db_path')
if not db_path_config:
    # Default: relative to current working directory
    db_path = Path('data/db/wingscribe.db')
elif is_absolute_path(db_path_config):
    db_path = Path(db_path_config)
else:
    db_path = Path(db_path_config)

# Ensure database directory exists
db_path.parent.mkdir(parents=True, exist_ok=True)

# Handle output.root_dir - allow empty/missing for index-only mode
output_root = config['paths'].get('output', {}).get('root_dir', '')
processed_dir = Path(output_root) if output_root else None

logger.info(f"Project Base Directory: {BASE_DIR}")
logger.info(f"Photo Source Directory: {source_dir}")
logger.info(f"Database Path: {db_path}")
logger.info(f"Processed Images Directory: {processed_dir}")

if processed_dir and not processed_dir.exists():
    logger.error(f"Processed directory does not exist: {processed_dir}")
    processed_dir.mkdir(parents=True, exist_ok=True)

# Note: Using custom route for /processed (see serve_processed_file above)
app.include_router(recognition_router)

# Mount library static files (Bootstrap, icons, etc.) - does not depend on source_dir
lib_static_dir = BASE_DIR / "src" / "web" / "static"
if lib_static_dir.exists():
    app.mount("/lib", StaticFiles(directory=str(lib_static_dir), follow_symlink=True), name="lib")

templates = Jinja2Templates(directory=str(BASE_DIR / "src" / "web" / "templates"))

# --- Initialization ---
# Call explicitly
def init_app_db():
    try:
        mgr = create_db_manager()
        mgr.close()
        del mgr
        gc.collect()

        # Initialize/migrate SQLAlchemy schema on top of the existing database
        engine = create_engine(f"sqlite:///{db_path}")
        init_sqlalchemy_db(engine)
        engine.dispose()
    except Exception as e:
        logger.error(f"Startup DB Initialization failed: {e}")

def create_db_manager():
    return path_helpers.create_db_manager(db_path, source_dir, processed_dir)
# --- Helper ---
def get_db_conn():
    return path_helpers.get_db_conn(db_path)


def get_sqlalchemy_session():
    """Create a SQLAlchemy session bound to the configured database."""
    engine = create_engine(f"sqlite:///{db_path}")
    return sessionmaker(bind=engine)()


def resolve_web_path(original_path_str: str) -> Optional[str]:
    """Resolves raw file path to /raw/... URL"""
    return path_helpers.resolve_web_path(original_path_str, source_dirs, logger)

@app.get("/raw/{path:path}")
def serve_raw_file(path: str):
    """Custom file handler for original images across multiple source roots."""
    return path_helpers.get_raw_file_response(path, source_dirs)

@app.get("/processed/{path:path}")
def serve_processed_file(path: str):
    """Custom static file handler for processed images (Unicode-safe on Windows)"""
    return path_helpers.get_processed_file_response(path, processed_dir)

def resolve_processed_web_path(file_path_str: str) -> Optional[str]:
    """Resolves processed file path to /processed/... URL"""
    return path_helpers.resolve_processed_web_path(file_path_str, processed_dir, BASE_DIR, logger)

# --- API Models ---
class UpdateLabelRequest(BaseModel):
    photo_id: int
    scientific_name: str
    chinese_name: str

class StartPipelineRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class StartPipelineByFoldersRequest(BaseModel):
    paths: List[str]
    recursive: bool = True


class IndexRequest(BaseModel):
    folder: str
    recursive: bool = True

# --- Routes ---

# First-run detection helper
def is_first_run():
    """Check if this is the first run (no config file)"""
    config_path = BASE_DIR / "config" / "settings.yaml"
    return not config_path.exists()

def is_paths_configured():
    """Check if source and output paths are configured (not empty)"""
    global source_dir
    global output_root
    return bool(source_dir) and bool(output_root)

@app.get("/", response_class=HTMLResponse)
def index(request: Request, skip_first_check: bool = False):
    # Check for first run or empty paths - redirect to settings if not configured
    if not skip_first_check and (is_first_run() or not is_paths_configured()):
        return templates.TemplateResponse(
            request, name="settings.html",
            context={"request": request, "is_first_run": is_first_run()},
        )

    session = get_sqlalchemy_session()
    try:
        total_photos = session.query(func.count(Photo.id)).scalar() or 0
        total_species = session.query(func.count(Species.id)).scalar() or 0
        total_outings = session.query(func.count(Outing.id)).scalar() or 0
        recent_outing = session.query(Outing).order_by(Outing.created_at.desc()).first()

        return templates.TemplateResponse(
            request, name="index.html",
            context={
                "request": request,
                "stats": {
                    "total_photos": total_photos,
                    "total_species": total_species,
                    "total_outings": total_outings,
                },
                "recent_outing": recent_outing,
            },
        )
    finally:
        session.close()


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return admin_service.admin_dashboard(request, templates, is_paths_configured, get_stats)


@app.get("/admin/index", response_class=HTMLResponse)
def admin_index_page(request: Request):
    """Render the photo indexing page."""
    return templates.TemplateResponse(request, "admin_index.html", {"request": request})


def get_stats():
    return admin_service.get_stats(get_db_conn)

@app.get("/api/stats")
def get_api_stats():
    return get_stats()

@app.get("/api/scan_history")
def get_scan_history():
    return admin_service.get_scan_history(create_db_manager)

@app.post("/api/pipeline/start")
def start_pipeline(req: StartPipelineRequest):
    return pipeline_service.start_pipeline(task_manager, req)

@app.get("/api/pipeline/folders")
def get_folder_tree():
    """获取 sources 配置的文件夹树形结构（只返回第一层）"""
    return pipeline_service.get_folder_tree(config, logger, _build_folder_tree)


@app.get("/api/pipeline/folders/{full_path:path}")
def get_folder_children(full_path: str):
    """获取指定路径的子目录（懒加载）"""
    return pipeline_service.get_folder_children(full_path, logger, _build_folder_tree)

def _build_folder_tree(root_path: Path, recursive: bool, base_rel_path: str = "", max_depth: int = 5, current_depth: int = 0):
    """递归构建文件夹树

    Args:
        root_path: 绝对路径的根目录
        recursive: 是否递归扫描子目录
        base_rel_path: 相对于 source_dir 的基础路径
    """
    return pipeline_service.build_folder_tree(
        root_path,
        recursive,
        base_rel_path=base_rel_path,
        max_depth=max_depth,
        current_depth=current_depth,
        logger=logger,
    )

@app.post("/api/pipeline/start_by_folders")
def start_pipeline_by_folders(req: StartPipelineByFoldersRequest):
    """按文件夹执行 Pipeline"""
    return pipeline_service.start_pipeline_by_folders(task_manager, req, logger)


@app.post("/api/pipeline/stop")
def stop_pipeline():
    return pipeline_service.stop_pipeline(task_manager)

@app.websocket("/ws/progress")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        last_index = 0
        while True:
            current_len = len(task_manager.logs)
            if current_len > last_index:
                new_logs = task_manager.logs[last_index:current_len]
                for log in new_logs:
                    await websocket.send_text(log)
                last_index = current_len
            
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        # Handle server shutdown cancellation
        pass
    except Exception as e:
        # Expected disconnect or other error
        pass

@app.get("/download_raw")
def download_raw(path: str):
    return admin_service.download_raw()

@app.post("/api/admin/reset")
def reset_system():
    return admin_service.reset_system(
        config,
        BASE_DIR,
        db_path,
        processed_dir,
        init_app_db,
        create_db_manager,
        logger,
    )

@app.get("/api/admin/rebuild_stats")
def rebuild_species_stats():
    return admin_service.rebuild_species_stats(create_db_manager)

@app.get("/api/search_species")
def search_species(q: str):
    return taxonomy_service.search_species(create_db_manager, q)

@app.get("/api/taxonomy/tree")
def get_taxonomy_tree(include_empty: bool = True, date: str = None):
    """获取分类树，支持显示/隐藏空层级和日期筛选"""
    return taxonomy_service.get_taxonomy_tree(create_db_manager, include_empty, date)

@app.get("/api/taxonomy/stats")
def get_taxonomy_stats(level: str, date: str = None):
    """按层级统计物种数量（order/family/genus/species）"""
    return taxonomy_service.get_taxonomy_stats(create_db_manager, level, date)

@app.get("/api/photos/by_taxonomy")
def get_photos_by_taxonomy(
    order_cn: Optional[str] = None,
    order_sci: Optional[str] = None,
    family_cn: Optional[str] = None,
    family_sci: Optional[str] = None,
    genus_cn: Optional[str] = None,
    genus_sci: Optional[str] = None,
    scientific_name: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """按分类层级筛选照片，支持中文和拉丁名参数"""
    return taxonomy_service.get_photos_by_taxonomy(
        create_db_manager,
        get_db_conn,
        resolve_web_path,
        resolve_processed_web_path,
        order_cn=order_cn,
        order_sci=order_sci,
        family_cn=family_cn,
        family_sci=family_sci,
        genus_cn=genus_cn,
        genus_sci=genus_sci,
        scientific_name=scientific_name,
        date=date,
        limit=limit,
        offset=offset,
    )

@app.get("/api/taxonomy/search")
def search_taxonomy(q: str, limit: int = 20):
    """搜索分类信息（支持目、科、属、物种）"""
    return taxonomy_service.search_taxonomy(create_db_manager, q, limit)

@app.post("/api/update_label")
def update_label(req: UpdateLabelRequest):
    manager = create_db_manager()
    moved_from = None
    photo = {}
    final_processed_path = None
    try:
        cursor = manager.conn.execute("SELECT * FROM photos WHERE id = ?", (req.photo_id,))
        photo = cursor.fetchone()

        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        photo = dict(photo)
        old_scientific_name = photo.get("scientific_name")
        stored_processed_path = photo.get("file_path")
        stored_filename = photo.get("filename")

        if photo.get('file_path'):
            photo['file_path'] = manager.resolve_processed_path(photo['file_path'])
        if photo.get('original_path'):
            photo['original_path'] = manager.resolve_original_path(photo['original_path'])

        bird_info = manager.get_bird_info(req.scientific_name)
        family_cn = bird_info['family_cn'] if bird_info else ""

        user_comment = req.chinese_name
        try:
            candidates = []
            if 'candidates_json' in photo and photo['candidates_json']:
                candidates = json.loads(photo['candidates_json'])

            if candidates:
                alt_threshold = config.get('recognition', {}).get('alternatives_threshold', 70)
                comment_lines = []
                top_score = candidates[0].get('score', 0) * 100 if candidates else 0
                show_alternatives = (top_score <= alt_threshold)
                display_list = candidates if show_alternatives else [candidates[0]]

                for i, cand in enumerate(display_list):
                    c_sci = cand.get('sci')
                    c_cn = cand.get('cn')
                    c_conf = cand.get('score', 0) * 100

                    if i == 0:
                        comment_lines.append(f"AI Top: {c_cn} ({c_sci}) - {c_conf:.1f}%")
                        if show_alternatives and len(display_list) > 1:
                            comment_lines.append("Alternatives:")
                    else:
                        comment_lines.append(f"{i}. {c_cn} ({c_sci}) - {c_conf:.1f}%")

                if candidates[0].get('sci') != req.scientific_name:
                    comment_lines.insert(0, f"[Manual Correction] Current: {req.chinese_name}")

                user_comment = "&#xa;".join(comment_lines)
        except Exception as e:
            logger.error(f"Failed to reconstruct UserComment: {e}")
            user_comment = req.chinese_name

        description = f"{req.chinese_name} ({req.scientific_name})"
        tags = {
            "IPTC:Keywords": [req.chinese_name, photo['location_tag'], family_cn, req.scientific_name],
            "XMP:Description": description,
            "XPTitle": description,
            "XPSubject": "",
            "ImageDescription": description,
            "UserComment": user_comment
        }

        processed_path = photo.get('file_path')
        final_processed_path = processed_path

        if processed_path and os.path.exists(processed_path):
            out_conf = config.get('paths', {}).get('output', {})
            template = out_conf.get('structure_template', "")

            if any(x in template for x in ["{species_cn}", "{species_sci}", "{confidence}"]):
                source_structure = "."
                if photo.get('original_path'):
                    orig_path_obj = Path(photo['original_path'])
                    sources = config.get('paths', {}).get('sources', [])
                    for src in sources:
                        try:
                            src_path = Path(src['path']).resolve()
                            if src_path in orig_path_obj.parents:
                                rel = orig_path_obj.parent.relative_to(src_path)
                                source_structure = str(rel).replace('\\', '/')
                                break
                        except Exception:
                            continue

                gen_meta = {
                    'captured_date': photo['captured_date'],
                    'location_tag': photo['location_tag'],
                    'primary_bird_cn': req.chinese_name,
                    'scientific_name': req.scientific_name,
                    'confidence_score': 1.0,
                    'source_structure': source_structure
                }

                output_root_raw = out_conf.get('root_dir', '') or processed_dir
                generator = PathGenerator(
                    template=template,
                    output_root=str(Path(output_root_raw))
                )

                orig_filename = photo.get('filename')
                if photo.get('original_path'):
                    orig_filename = Path(photo['original_path']).name

                new_path = generator.generate_path(gen_meta, orig_filename)
                if Path(new_path).resolve() != Path(processed_path).resolve():
                    new_path.parent.mkdir(parents=True, exist_ok=True)

                    final_path = new_path
                    if final_path.exists() and final_path.resolve() != Path(processed_path).resolve():
                        stem = final_path.stem
                        counter = 1
                        while final_path.exists():
                            final_path = final_path.with_name(f"{stem}_{counter}.jpg")
                            counter += 1

                    shutil.move(processed_path, final_path)
                    moved_from = processed_path
                    final_processed_path = str(final_path)
                    stored_processed_path = manager.to_storage_processed_path(str(final_path))
                    stored_filename = final_path.name
                    logger.info(f"Renamed file to: {final_path}")

        if final_processed_path and os.path.exists(final_processed_path):
            if not exif_writer.write_metadata(final_processed_path, tags):
                raise RuntimeError("Failed to update metadata for processed image")

        original_path = photo.get('original_path')
        if original_path and os.path.exists(original_path):
            source_tags = tags.copy()
            source_tags["IPTC:Keywords"] = source_tags["IPTC:Keywords"] + ["WingScribe"]
            if not exif_writer.write_metadata(original_path, source_tags):
                raise RuntimeError("Failed to update metadata for original image")

        manager.conn.execute(
            '''
            UPDATE photos
            SET scientific_name = ?, primary_bird_cn = ?, confidence_score = ?, file_path = ?, filename = ?
            WHERE id = ?
            ''',
            (
                req.scientific_name,
                req.chinese_name,
                1.0,
                stored_processed_path,
                stored_filename,
                req.photo_id
            )
        )
        manager.conn.commit()

        if old_scientific_name:
            manager.update_species_stats_for_photo(old_scientific_name)
        if req.scientific_name:
            manager.update_species_stats_for_photo(req.scientific_name)

        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        if moved_from and final_processed_path and os.path.exists(final_processed_path) and not os.path.exists(moved_from):
            try:
                shutil.move(final_processed_path, moved_from)
            except Exception as rollback_error:
                logger.error(f"Failed to roll back renamed file: {rollback_error}")
        logger.error(f"Failed to update label for photo {req.photo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        manager.close()

# --- Configuration Management ---
class ConfigItem(BaseModel):
    key: str
    value: str
    section: str
    type: str = "string"  # string, int, float, bool

class SaveConfigRequest(BaseModel):
    configs: List[ConfigItem]
    restart: bool = False

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Configuration page"""
    return templates.TemplateResponse(request, name="settings.html", context={"request": request})

@app.get("/api/config")
async def get_config():
    """Get current configuration"""
    return config_service.get_config(BASE_DIR, get_config_definition)

@app.post("/api/config/save")
async def save_config(req: SaveConfigRequest):
    """Save configuration to file"""
    return config_service.save_config(req, BASE_DIR, set_nested_value)

@app.post("/api/config/restart")
async def restart_server():
    """Restart the server by spawning a new process and exiting current one"""
    return config_service.restart_server(
        BASE_DIR,
        config,
        _startup_host,
        _startup_port,
        _startup_python,
        logger,
    )

@app.get("/api/config/validate")
async def validate_config_path(path: str, path_type: str = "directory"):
    """Validate if a path exists and is accessible

    Args:
        path: The path to validate
        path_type: Expected type - "directory" or "file"
    """
    return config_service.validate_config_path(path, path_type)


def open_folder_dialog(title: str, initial_dir: str = "") -> str:
    return config_service.open_folder_dialog(title, initial_dir)


def open_file_dialog(title: str, initial_file: str = "", file_types: str = "") -> str:
    return config_service.open_file_dialog(title, initial_file, file_types)

@app.post("/api/config/browse_folder")
async def browse_folder_api(title: str = "选择文件夹", initial_path: str = ""):
    """API endpoint to open folder selection dialog"""
    try:
        folder_path = await asyncio.to_thread(open_folder_dialog, title, initial_path)
        return {"path": folder_path}
    except Exception as e:
        return {"error": str(e), "path": None}

@app.post("/api/config/browse_file")
async def browse_file_api(title: str = "选择文件", initial_path: str = "", file_types: str = "xlsx|xls"):
    """API endpoint to open file selection dialog"""
    try:
        file_path = await asyncio.to_thread(open_file_dialog, title, initial_path, file_types)
        return {"path": file_path}
    except Exception as e:
        return {"error": str(e), "path": None}


@app.post("/api/index")
def index_photos(req: IndexRequest):
    """Index photos from a selected folder into the database."""
    folder_path = Path(req.folder)
    if not folder_path.exists() or not folder_path.is_dir():
        raise HTTPException(status_code=400, detail="Folder does not exist or is not a directory")

    session = get_sqlalchemy_session()
    try:
        repo = PhotoRepository(session)
        formats_from_config = config.get("paths", {}).get("supported_formats")
        supported_formats = set(formats_from_config) if formats_from_config else None
        indexer = PhotoIndexer(repo, supported_formats=supported_formats)
        result = indexer.index_folder_with_stats(folder_path, req.recursive)
        return result
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

class SelectMarkRequest(BaseModel):
    photo_id: int
    action: str  # select | keep | reject


class AutoPickRequest(BaseModel):
    outing_id: int = 0
    min_quality: int = 80


class CorrectSpeciesRequest(BaseModel):
    scientific_name: str
    chinese_name: Optional[str] = None
    write_metadata: bool = True


# --- Three-domain web routes ---
def _apply_rating_filter(query, rating: str):
    """Apply tier filtering to the SQLAlchemy Photo query.

    The filter maps to a 5-star Lightroom-style rating:
    5-star = best, 4-star = usable, 3-star = record, 1-star = rejected, no-bird = 0-star.
    """
    if rating == "5":
        query = query.filter(
            Photo.primary_bird_cn.isnot(None),
            Photo.primary_bird_cn != "",
            Photo.quality_score >= 80,
            (Photo.rating.is_(None)) | (Photo.rating != -1),
        )
    elif rating == "4":
        query = query.filter(
            Photo.primary_bird_cn.isnot(None),
            Photo.primary_bird_cn != "",
            Photo.quality_score >= 50,
            Photo.quality_score < 80,
            (Photo.rating.is_(None)) | (Photo.rating != -1),
        )
    elif rating == "3":
        query = query.filter(
            Photo.primary_bird_cn.isnot(None),
            Photo.primary_bird_cn != "",
            Photo.quality_score < 50,
            (Photo.rating.is_(None)) | (Photo.rating != -1),
        )
    elif rating == "1":
        query = query.filter(Photo.rating == -1)
    elif rating == "0":
        query = query.filter(
            (Photo.primary_bird_cn.is_(None)) | (Photo.primary_bird_cn == "")
        )
    return query


@app.get("/select", response_class=HTMLResponse)
def select_page(request: Request, date: str = "", outing_id: int = 0, rating: str = ""):
    """选片工作台：默认展示最近一次外拍的照片，按连拍分组优先展示。支持等级筛选。"""
    session = get_sqlalchemy_session()
    try:
        # Determine the active outing
        current_outing = None
        if outing_id:
            current_outing = session.query(Outing).filter(Outing.id == outing_id).first()
        if not current_outing:
            current_outing = session.query(Outing).order_by(Outing.created_at.desc()).first()

        query = session.query(Photo)
        if current_outing:
            query = query.filter(Photo.outing_id == current_outing.id)
        if date:
            query = query.filter(Photo.captured_date == date)
        if rating:
            query = _apply_rating_filter(query, rating)
        photos = query.order_by(Photo.captured_date.desc(), Photo.id.desc()).limit(500).all()

        # Separate grouped and ungrouped photos
        grouped: dict[int, list[Photo]] = {}
        ungrouped: dict[str, list[Photo]] = {}
        for p in photos:
            if p.group_id:
                grouped.setdefault(p.group_id, []).append(p)
            else:
                key = p.captured_date or "未知日期"
                ungrouped.setdefault(key, []).append(p)

        display_groups = []
        gid = 1

        # Render burst groups first, ordered by best photo (highest quality first)
        group_ids = sorted(grouped.keys())
        for group_id in group_ids:
            group_photos = grouped[group_id]
            best = max(group_photos, key=lambda p: (p.quality_score or 0, p.id))
            members = sorted(group_photos, key=lambda p: (p.captured_at or p.id, p.id))
            display_groups.append({
                "id": gid,
                "type": "burst",
                "group_id": group_id,
                "date": best.captured_date or "未知日期",
                "best_photo_id": best.id,
                "photo_count": len(members),
                "primary_bird_cn": best.primary_bird_cn,
                "scientific_name": best.scientific_name,
                "quality_score": best.quality_score or 0,
                "is_selected": best.is_selected or False,
                "is_rejected": best.rating == -1,
                "web_processed_path": resolve_processed_web_path(best.file_path) if best.file_path else None,
                "web_raw_path": resolve_web_path(best.original_path) if best.original_path else None,
                "photos": [
                    {
                        "id": p.id,
                        "primary_bird_cn": p.primary_bird_cn,
                        "scientific_name": p.scientific_name,
                        "location_tag": p.location_tag,
                        "captured_date": p.captured_date,
                        "quality_score": p.quality_score or 0,
                        "is_selected": p.is_selected or False,
                        "is_rejected": p.rating == -1,
                        "web_processed_path": resolve_processed_web_path(p.file_path) if p.file_path else None,
                        "web_raw_path": resolve_web_path(p.original_path) if p.original_path else None,
                    }
                    for p in members
                ],
            })
            gid += 1

        # Render ungrouped photos by captured_date (one group per date)
        for key in sorted(ungrouped.keys(), reverse=True):
            group_photos = ungrouped[key]
            display_groups.append({
                "id": gid,
                "type": "single",
                "date": key,
                "photo_count": len(group_photos),
                "primary_bird_cn": group_photos[0].primary_bird_cn,
                "scientific_name": group_photos[0].scientific_name,
                "quality_score": group_photos[0].quality_score or 0,
                "is_selected": group_photos[0].is_selected or False,
                "is_rejected": group_photos[0].rating == -1,
                "web_processed_path": resolve_processed_web_path(group_photos[0].file_path) if group_photos[0].file_path else None,
                "web_raw_path": resolve_web_path(group_photos[0].original_path) if group_photos[0].original_path else None,
                "photos": [
                    {
                        "id": p.id,
                        "primary_bird_cn": p.primary_bird_cn,
                        "scientific_name": p.scientific_name,
                        "location_tag": p.location_tag,
                        "captured_date": p.captured_date,
                        "quality_score": p.quality_score or 0,
                        "is_selected": p.is_selected or False,
                        "is_rejected": p.rating == -1,
                        "web_processed_path": resolve_processed_web_path(p.file_path) if p.file_path else None,
                        "web_raw_path": resolve_web_path(p.original_path) if p.original_path else None,
                    }
                    for p in group_photos
                ],
            })
            gid += 1

        return templates.TemplateResponse(
            request, "select.html",
            {
                "request": request,
                "groups": display_groups,
                "current_date": date,
                "current_rating": rating,
                "current_outing": current_outing,
                "outing_id": current_outing.id if current_outing else 0,
            },
        )
    finally:
        session.close()


@app.post("/api/select/pick-best/{group_id}")
def select_pick_best(group_id: int):
    """在连拍分组中自动选出最佳照片（画质最高）。"""
    session = get_sqlalchemy_session()
    try:
        photos = session.query(Photo).filter(Photo.group_id == group_id).all()
        if not photos:
            raise HTTPException(status_code=404, detail="Group not found or empty")
        best = max(photos, key=lambda p: (p.quality_score or 0, p.id))
        best.is_selected = True
        best.rating = max(best.rating or 0, 1)
        session.commit()
        return {
            "status": "success",
            "photo": {
                "id": best.id,
                "primary_bird_cn": best.primary_bird_cn,
                "quality_score": best.quality_score or 0,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pick best for group {group_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/select/mark")
def select_mark(req: SelectMarkRequest):
    """标记照片选中/保留/淘汰状态。"""
    session = get_sqlalchemy_session()
    try:
        photo = session.query(Photo).filter(Photo.id == req.photo_id).first()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")
        if req.action == "select":
            photo.is_selected = True
            photo.rating = max(photo.rating or 0, 1)
        elif req.action == "reject":
            photo.is_selected = False
            photo.rating = -1
        elif req.action == "keep":
            photo.is_selected = False
            photo.rating = max(photo.rating or 0, 1)
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
        session.commit()
        return {"status": "success", "photo_id": req.photo_id, "action": req.action}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to mark photo {req.photo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/select/auto-pick")
def select_auto_pick(req: AutoPickRequest):
    """批量快速审阅：对连拍组每组选最佳，单张照片按质量阈值直接选中。"""
    session = get_sqlalchemy_session()
    try:
        query = session.query(Photo)
        if req.outing_id:
            query = query.filter(Photo.outing_id == req.outing_id)
        else:
            outing = session.query(Outing).order_by(Outing.created_at.desc()).first()
            if outing:
                query = query.filter(Photo.outing_id == outing.id)
        query = query.filter((Photo.rating.is_(None)) | (Photo.rating != -1))

        grouped: dict[int, list[Photo]] = {}
        ungrouped: list[Photo] = []
        for p in query.all():
            if p.group_id:
                grouped.setdefault(p.group_id, []).append(p)
            else:
                ungrouped.append(p)

        selected_ids: list[int] = []
        for group_photos in grouped.values():
            best = max(group_photos, key=lambda p: (p.quality_score or 0, p.id))
            if best.quality_score and best.quality_score >= req.min_quality:
                best.is_selected = True
                best.rating = max(best.rating or 0, 1)
                selected_ids.append(best.id)

        for p in ungrouped:
            if p.quality_score and p.quality_score >= req.min_quality:
                p.is_selected = True
                p.rating = max(p.rating or 0, 1)
                selected_ids.append(p.id)

        session.commit()
        return {"status": "success", "selected_count": len(selected_ids), "selected_ids": selected_ids}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to auto-pick: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/photo/{photo_id}/write_metadata")
def write_photo_metadata(photo_id: int):
    """Write EXIF/XMP metadata for a single photo back to its original file."""
    session = get_sqlalchemy_session()
    try:
        photo = session.query(Photo).filter(Photo.id == photo_id).first()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        write_mode = config.get("metadata", {}).get("write_mode", "xmp_sidecar")
        ok = write_metadata_for_photo(photo, exif_writer, write_mode=write_mode)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to write metadata")
        return {"status": "success", "photo_id": photo_id, "write_mode": write_mode}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to write metadata for photo {photo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


def _resolve_original_path(photo: Photo) -> str:
    """Return absolute path to the original photo file."""
    path = photo.original_path or photo.file_path
    if not path:
        return ""
    path_obj = Path(path)
    if path_obj.is_absolute():
        return str(path_obj)
    # Try each configured source directory
    for src_dir in source_dirs:
        candidate = src_dir / path_obj
        if candidate.exists():
            return str(candidate)
    # Fallback: join with first source dir even if not found
    if source_dirs:
        return str(source_dirs[0] / path_obj)
    return str(path_obj)


@app.get("/api/photo/{photo_id}/review")
def get_photo_review(photo_id: int):
    """Return full review details for a photo: metadata, candidates, quality details.

    Also returns the previous/next photo id within the same group (or same captured_date
    if the photo is ungrouped) so the review UI can navigate with arrow keys.
    """
    session = get_sqlalchemy_session()
    try:
        photo = session.query(Photo).filter(Photo.id == photo_id).first()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        original_path = _resolve_original_path(photo)
        if not original_path or not Path(original_path).exists():
            raise HTTPException(status_code=404, detail="Original file not found")

        candidates: List[Any] = []
        if photo.candidates_json:
            try:
                candidates = json.loads(photo.candidates_json) if isinstance(photo.candidates_json, str) else photo.candidates_json
            except Exception:
                pass

        quality_details: Dict[str, Any] = {}
        if photo.quality_details:
            try:
                quality_details = json.loads(photo.quality_details) if isinstance(photo.quality_details, str) else photo.quality_details
            except Exception:
                pass

        prev_photo_id, next_photo_id = _get_review_neighbors(session, photo)

        exif_summary = read_exif_summary(exif_writer, original_path)

        return {
            "photo": {
                "id": photo.id,
                "filename": photo.filename,
                "file_path": photo.file_path,
                "primary_bird_cn": photo.primary_bird_cn,
                "scientific_name": photo.scientific_name,
                "confidence_score": photo.confidence_score,
                "quality_score": photo.quality_score,
                "bird_bbox": photo.bird_bbox,
                "width": photo.width,
                "height": photo.height,
                "captured_at": photo.captured_at.isoformat() if photo.captured_at else None,
                "captured_date": photo.captured_date,
                "location_tag": photo.location_tag,
                "location_level1": photo.location_level1,
                "location_level2": photo.location_level2,
                "location_level3": photo.location_level3,
                "latitude": photo.latitude,
                "longitude": photo.longitude,
                "original_path": original_path,
                "is_selected": photo.is_selected,
                "rating": photo.rating,
                "group_id": photo.group_id,
            },
            "candidates": candidates,
            "quality_details": quality_details,
            "exif": exif_summary,
            "prev_photo_id": prev_photo_id,
            "next_photo_id": next_photo_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get photo review {photo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


def _get_review_neighbors(session, photo: Photo) -> tuple[Optional[int], Optional[int]]:
    """Return previous/next photo id within the same group or same captured_date."""
    if photo.group_id:
        siblings = (
            session.query(Photo.id)
            .filter(Photo.group_id == photo.group_id)
            .order_by(Photo.captured_at.asc(), Photo.id.asc())
            .all()
        )
    else:
        siblings = (
            session.query(Photo.id)
            .filter(Photo.captured_date == photo.captured_date)
            .order_by(Photo.captured_at.asc(), Photo.id.asc())
            .all()
        )
    ids = [row[0] for row in siblings]
    if not ids:
        return None, None
    try:
        idx = ids.index(photo.id)
    except ValueError:
        return None, None
    prev_id = ids[idx - 1] if idx > 0 else None
    next_id = ids[idx + 1] if idx < len(ids) - 1 else None
    return prev_id, next_id


@app.get("/api/photo/{photo_id}/preview")
def get_photo_preview(photo_id: int):
    """Return a JPEG preview of the photo. For RAW files, a temporary decoded JPEG is generated and removed after serving."""
    session = get_sqlalchemy_session()
    try:
        photo = session.query(Photo).filter(Photo.id == photo_id).first()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        original_path = _resolve_original_path(photo)
        if not original_path or not Path(original_path).exists():
            raise HTTPException(status_code=404, detail="Original file not found")

        if ImageProcessor.is_raw(original_path):
            tmp_path = ImageProcessor.decode_raw_to_temp_jpg(original_path)
            try:
                with open(tmp_path, "rb") as f:
                    data = f.read()
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return StreamingResponse(iter([data]), media_type="image/jpeg")
        return FileResponse(original_path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get photo preview {photo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/photo/{photo_id}/open-directory")
def open_photo_directory(photo_id: int):
    """Open the directory containing the original photo file in the local file manager.

    On Windows, this uses ``explorer /select,<path>`` to open the directory and select
    the file. On other systems, it opens the parent directory via ``xdg-open``.
    """
    session = get_sqlalchemy_session()
    try:
        photo = session.query(Photo).filter(Photo.id == photo_id).first()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        original_path = _resolve_original_path(photo)
        if not original_path or not Path(original_path).exists():
            raise HTTPException(status_code=404, detail="Original file not found")

        directory = os.path.dirname(original_path)
        system = platform.system()
        try:
            if system == "Windows":
                subprocess.Popen(["explorer", "/select,", original_path])
            elif system == "Darwin":
                subprocess.Popen(["open", "--reveal", original_path])
            else:
                subprocess.Popen(["xdg-open", directory])
        except OSError as e:
            logger.error(f"Failed to open directory for photo {photo_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to open directory: {e}")

        return {"status": "success", "directory": directory, "system": system}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to open directory for photo {photo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/gallery/write_metadata")
def write_gallery_metadata(filter: str = "", date: str = ""):
    """Batch write metadata for selected/filtered photos."""
    session = get_sqlalchemy_session()
    try:
        query = session.query(Photo).filter(Photo.is_selected == True)
        if filter == "selected":
            query = query.filter(Photo.is_selected == True)
        elif filter == "current":
            query = query.filter(Photo.captured_date == date)
        photos = query.all()

        write_mode = config.get("metadata", {}).get("write_mode", "xmp_sidecar")
        results = []
        for photo in photos:
            ok = write_metadata_for_photo(photo, exif_writer, write_mode=write_mode)
            results.append({"photo_id": photo.id, "success": ok})

        success_count = sum(1 for r in results if r["success"])
        return {
            "status": "success",
            "write_mode": write_mode,
            "total": len(results),
            "success_count": success_count,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Failed to batch write metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


def _refresh_species_for_photo(session, scientific_name: str):
    """Recalculate and update species stats in both SQLAlchemy and sqlite3 tables."""
    if not scientific_name:
        return

    from src.metadata.ioc_manager import create_db_manager

    # Update SQLAlchemy Species table
    stats = session.query(
        func.count(Photo.id).label('count'),
        func.min(Photo.captured_date).label('first_date'),
        func.max(Photo.captured_date).label('last_date'),
    ).filter(Photo.scientific_name == scientific_name).first()

    species = session.query(Species).filter(Species.scientific_name == scientific_name).first()

    if stats.count == 0:
        if species:
            session.delete(species)
    else:
        if not species:
            # Look up taxonomy for family and Chinese names
            bird_info = None
            try:
                manager = create_db_manager()
                bird_info = manager.get_bird_info(scientific_name)
            finally:
                manager.close()
            species = Species(
                scientific_name=scientific_name,
                chinese_name=bird_info.get('chinese_name') if bird_info else '',
                family_cn=bird_info.get('family_cn') if bird_info else '',
                family_sci=bird_info.get('family_sci') if bird_info else '',
                photo_count=0,
            )
            session.add(species)
        species.photo_count = stats.count
        species.first_date = stats.first_date
        species.last_date = stats.last_date

    session.commit()

    # Update sqlite3 species_stats table (pre-computed tree used by index/nav)
    try:
        manager = create_db_manager()
        manager.update_species_stats_for_photo(scientific_name)
    finally:
        manager.close()


@app.post("/api/photo/{photo_id}/correct-species")
def correct_photo_species(photo_id: int, request: CorrectSpeciesRequest):
    """Allow users to manually correct the species of a photo."""
    session = get_sqlalchemy_session()
    try:
        photo = session.query(Photo).filter(Photo.id == photo_id).first()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        new_name = request.scientific_name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Scientific name is required")

        old_name = photo.scientific_name
        if old_name == new_name:
            return {"status": "success", "message": "No change", "photo_id": photo_id}

        # Look up taxonomy for Chinese name and family if not provided
        from src.metadata.ioc_manager import create_db_manager
        try:
            manager = create_db_manager()
            bird_info = manager.get_bird_info(new_name)
        finally:
            manager.close()

        new_cn = (request.chinese_name or (bird_info.get('chinese_name') if bird_info else '') or new_name).strip()

        # Update candidate JSON so Top1 reflects the corrected species
        candidates = _load_json(photo.candidates_json) or []
        if candidates:
            candidates[0] = {
                "chinese_name": new_cn,
                "scientific_name": new_name,
                "confidence": 1.0,
            }
        else:
            candidates = [{
                "chinese_name": new_cn,
                "scientific_name": new_name,
                "confidence": 1.0,
            }]

        photo.primary_bird_cn = new_cn
        photo.scientific_name = new_name
        photo.confidence_score = 1.0
        photo.candidates_json = json.dumps(candidates, ensure_ascii=False)
        session.commit()

        # Refresh species stats for both old and new species
        if old_name:
            _refresh_species_for_photo(session, old_name)
        _refresh_species_for_photo(session, new_name)

        # Optionally write metadata to the original file
        if request.write_metadata:
            try:
                write_mode = config.get("metadata", {}).get("write_mode", "xmp_sidecar")
                write_metadata_for_photo(photo, exif_writer, write_mode=write_mode)
            except Exception as e:
                logger.warning(f"Metadata write after species correction failed: {e}")

        return {
            "status": "success",
            "message": "Species corrected",
            "photo_id": photo_id,
            "scientific_name": new_name,
            "chinese_name": new_cn,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to correct species for photo {photo_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    """照片导入向导：选择源目录、扫描预览、启动导入。"""
    return templates.TemplateResponse(
        request, "import.html",
        {
            "request": request,
            "default_source_dir": config.get("paths", {}).get("source_dir", ""),
        },
    )


@app.post("/api/import/scan")
async def import_scan(data: dict):
    """扫描指定目录，返回可导入文件统计及路径解析的地点。"""
    try:
        folder = data.get("folder", "")
        recursive = data.get("recursive", True)
        if not folder:
            raise HTTPException(status_code=400, detail="请提供文件夹路径")
        result = import_service_instance.scan_folder(folder, recursive=recursive)
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Import scan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/import/parse-location")
async def import_parse_location(data: dict):
    """从文件夹路径解析地点信息，不需要扫描文件。"""
    try:
        folder = data.get("folder", "")
        if not folder:
            raise HTTPException(status_code=400, detail="请提供文件夹路径")
        return {"status": "success", "data": import_service_instance.parse_location(folder)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Parse location failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/import/browse-folder")
async def import_browse_folder():
    """弹出系统文件夹选择对话框，返回选中的文件夹路径。"""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder = filedialog.askdirectory(title="选择照片源目录")
        root.destroy()
        if folder:
            return {"status": "success", "folder": folder}
        else:
            return {"status": "cancelled"}
    except Exception as e:
        logger.error(f"Browse folder failed: {e}")
        return {"status": "error", "detail": str(e)}


@app.post("/api/import/start")
async def import_start(data: dict):
    """启动照片导入任务（索引 + 可选识别）。"""
    folder = data.get("folder", "")
    recursive = data.get("recursive", True)
    run_recognition = data.get("run_recognition", True)
    overwrite = data.get("overwrite", False)
    location_info = data.get("location_info", None)
    if not folder:
        raise HTTPException(status_code=400, detail="请提供文件夹路径")

    result = import_service_instance.start_import(
        folder, recursive=recursive, run_recognition=run_recognition, overwrite=overwrite, location_info=location_info
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=409, detail=result["message"])
    return {"status": "success", "message": "Import started", "outing_id": result.get("outing_id")}


@app.get("/api/import/status")
async def import_status():
    """返回当前导入任务状态。"""
    return import_service_instance.get_status()


@app.get("/gallery", response_class=HTMLResponse)
def gallery_page(
    request: Request,
    q: str = "",
    view: str = "",
    filter: str = "",  # 保留旧参数兼容
    date: str = "",
    date_from: str = "",
    date_to: str = "",
    species: List[str] = Query(default=[]),
    families: List[str] = Query(default=[]),
    locations: List[str] = Query(default=[]),  # 兼容旧参数
    location_level1: List[str] = Query(default=[]),
    location_level2: List[str] = Query(default=[]),
    location_level3: List[str] = Query(default=[]),
    outing_id: int = 0,
    limit: int = 50,
    offset: int = 0,
):
    """图库浏览：按时间/地点/鸟种/视图筛选。"""

    def _list_param(values):
        if values is None:
            return []
        if isinstance(values, list):
            return values
        if isinstance(values, str):
            return [values] if values.strip() else []
        # FastAPI Query default object when called directly in tests
        if hasattr(values, "default"):
            default = values.default
            return default if isinstance(default, list) else []
        return []

    session = get_sqlalchemy_session()
    try:
        # 兼容旧 filter 参数
        effective_view = view or filter
        if effective_view not in ("", "all", "selected", "unselected", "uncertain"):
            effective_view = ""

        # Load current outing if specified
        current_outing = None
        if outing_id:
            current_outing = session.query(Outing).filter(Outing.id == outing_id).first()

        # Build base query, optionally joining Species for family filtering
        if families:
            query = session.query(Photo).join(Species, Photo.scientific_name == Species.scientific_name, isouter=True)
        else:
            query = session.query(Photo)

        if q:
            query = query.filter(
                (Photo.primary_bird_cn.like(f"%{q}%")) |
                (Photo.scientific_name.like(f"%{q}%")) |
                (Photo.location_tag.like(f"%{q}%")) |
                (Photo.captured_date.like(f"%{q}%")) |
                (Photo.filename.like(f"%{q}%"))
            )

        if effective_view == "uncertain":
            query = query.filter(
                (Photo.primary_bird_cn == "待确认鸟种") | (Photo.scientific_name == "Uncertain")
            )
        elif effective_view == "selected":
            query = query.filter(Photo.is_selected == True)
        elif effective_view == "unselected":
            query = query.filter(Photo.is_selected == False)

        # Single date (legacy) or date range
        if date:
            query = query.filter(Photo.captured_date == date)
        else:
            if date_from:
                query = query.filter(Photo.captured_date >= date_from)
            if date_to:
                query = query.filter(Photo.captured_date <= date_to)

        # Species filter (multi-select)
        selected_species = [s.strip() for s in _list_param(species) if s.strip()]
        if selected_species:
            query = query.filter(
                Photo.primary_bird_cn.in_(selected_species) |
                Photo.scientific_name.in_(selected_species)
            )

        # Family filter (multi-select, requires join)
        selected_families = [f.strip() for f in _list_param(families) if f.strip()]
        if selected_families:
            query = query.filter(Species.family_cn.in_(selected_families))

        # Location filter (cascade: province / city / site)
        selected_level1 = [loc.strip() for loc in _list_param(location_level1) if loc.strip()]
        selected_level2 = [loc.strip() for loc in _list_param(location_level2) if loc.strip()]
        selected_level3 = [loc.strip() for loc in _list_param(location_level3) if loc.strip()]
        # Backward compatibility: old "locations" parameter maps to full tag or level3
        legacy_locations = [loc.strip() for loc in _list_param(locations) if loc.strip()]
        if legacy_locations and not (selected_level1 or selected_level2 or selected_level3):
            query = query.filter(
                (Photo.location_tag.in_(legacy_locations)) |
                (Photo.location_level3.in_(legacy_locations))
            )
        else:
            if selected_level1:
                query = query.filter(Photo.location_level1.in_(selected_level1))
            if selected_level2:
                query = query.filter(Photo.location_level2.in_(selected_level2))
            if selected_level3:
                query = query.filter(Photo.location_level3.in_(selected_level3))

        # Outing filter (placeholder for future integration)
        if outing_id:
            query = query.filter(Photo.outing_id == outing_id)

        total_count = query.count()
        photos = query.order_by(Photo.captured_date.desc(), Photo.id.desc()).offset(offset).limit(limit).all()

        display_photos = []
        for p in photos:
            display_photos.append({
                "id": p.id,
                "primary_bird_cn": p.primary_bird_cn,
                "scientific_name": p.scientific_name,
                "location_tag": p.location_tag,
                "location_level1": p.location_level1,
                "location_level2": p.location_level2,
                "location_level3": p.location_level3,
                "captured_date": p.captured_date,
                "confidence_score": p.confidence_score or 0,
                "quality_score": p.quality_score or 0,
                "is_selected": p.is_selected or False,
                "filename": p.filename,
                "candidates_json": p.candidates_json,
                "web_processed_path": resolve_processed_web_path(p.file_path) if p.file_path else None,
                "web_raw_path": resolve_web_path(p.original_path) if p.original_path else None,
            })

        # Sidebar options
        available_dates = [d[0] for d in session.query(Photo.captured_date).distinct().order_by(Photo.captured_date.desc()).all() if d[0]]
        available_species = [
            {"cn": cn, "sci": sci, "count": count}
            for cn, sci, count in session.query(
                Photo.primary_bird_cn, Photo.scientific_name, func.count(Photo.id)
            ).group_by(Photo.primary_bird_cn, Photo.scientific_name).order_by(func.count(Photo.id).desc()).all()
            if cn or sci
        ]
        available_families = [
            {"family_cn": family_cn, "count": count}
            for family_cn, count in session.query(
                Species.family_cn, func.count(Species.id)
            ).filter(Species.photo_count > 0).group_by(Species.family_cn).order_by(func.count(Species.id).desc()).all()
            if family_cn
        ]
        available_locations = [
            {"level1": l1, "level2": l2, "level3": l3, "count": count}
            for l1, l2, l3, count in session.query(
                Photo.location_level1, Photo.location_level2, Photo.location_level3, func.count(Photo.id)
            ).group_by(Photo.location_level1, Photo.location_level2, Photo.location_level3).order_by(func.count(Photo.id).desc()).all()
            if l1 or l2 or l3
        ]
        available_level1 = [
            {"name": name, "count": count}
            for name, count in session.query(
                Photo.location_level1, func.count(Photo.id)
            ).filter(Photo.location_level1.isnot(None)).group_by(Photo.location_level1).order_by(func.count(Photo.id).desc()).all()
        ]
        available_level2 = [
            {"name": name, "count": count}
            for name, count in session.query(
                Photo.location_level2, func.count(Photo.id)
            ).filter(Photo.location_level2.isnot(None)).group_by(Photo.location_level2).order_by(func.count(Photo.id).desc()).all()
        ]
        available_level3 = [
            {"name": name, "count": count}
            for name, count in session.query(
                Photo.location_level3, func.count(Photo.id)
            ).filter(Photo.location_level3.isnot(None)).group_by(Photo.location_level3).order_by(func.count(Photo.id).desc()).all()
        ]

        has_next = (offset + limit) < total_count
        has_prev = offset > 0

        # Build a query string for view-switch links and pagination that preserves
        # all active filters except the one being switched.
        filter_params = {
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
        }
        for value in selected_species:
            filter_params.setdefault("species", []).append(value)
        for value in selected_families:
            filter_params.setdefault("families", []).append(value)
        for value in selected_level1:
            filter_params.setdefault("location_level1", []).append(value)
        for value in selected_level2:
            filter_params.setdefault("location_level2", []).append(value)
        for value in selected_level3:
            filter_params.setdefault("location_level3", []).append(value)
        for value in legacy_locations:
            filter_params.setdefault("locations", []).append(value)
        if outing_id:
            filter_params["outing_id"] = outing_id
        if limit != 50:
            filter_params["limit"] = limit
        filter_params = {k: v for k, v in filter_params.items() if v}
        base_query = urlencode(filter_params, doseq=True)

        return templates.TemplateResponse(
            request, "gallery.html",
            {
                "request": request,
                "photos": display_photos,
                "query": q,
                "current_view": effective_view,
                "current_date": date,
                "date_from": date_from,
                "date_to": date_to,
                "selected_species": selected_species,
                "selected_families": selected_families,
                "selected_level1": selected_level1,
                "selected_level2": selected_level2,
                "selected_level3": selected_level3,
                "selected_locations": legacy_locations,
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "available_dates": available_dates,
                "available_species": available_species,
                "available_families": available_families,
                "available_locations": available_locations,
                "available_level1": available_level1,
                "available_level2": available_level2,
                "available_level3": available_level3,
                "base_query": base_query,
                "has_next": has_next,
                "has_prev": has_prev,
                "next_offset": offset + limit,
                "prev_offset": max(0, offset - limit),
                "outing_id": outing_id,
                "current_outing": current_outing,
            },
        )
    finally:
        session.close()


@app.get("/guide", response_class=HTMLResponse)
def guide_page(request: Request, q: str = ""):
    """鸟类图鉴：已解锁物种墙，按科分组。本次外拍新增物种高亮。"""


@app.get("/log", response_class=HTMLResponse)
def birding_log_page(request: Request):
    """观鸟记录：按日期聚合每次外拍及观测到的物种。"""
    return templates.TemplateResponse(
        request, "log.html",
        {
            "request": request,
        },
    )


@app.get("/api/log")
def api_birding_log(
    date_from: str | None = None,
    date_to: str | None = None,
    year: int | None = None,
):
    """返回按日期聚合的观鸟记录。

    聚合口径：
    - 以 Outing 为主体，按 start_date 倒序。
    - 每个 outing 内列出所有识别出的物种（primary_bird_cn + scientific_name）。
    - 统计每个 outing 的照片总数、物种数、新种数（该物种首次在此 outing 出现）。
    - 返回地点信息（优先使用 outing 的地点，否则取照片地点聚合）。
    """
    session = get_sqlalchemy_session()
    try:
        outing_query = session.query(Outing).order_by(Outing.start_date.desc(), Outing.created_at.desc())
        if year:
            outing_query = outing_query.filter(Outing.start_date.like(f"{year}%"))
        if date_from:
            outing_query = outing_query.filter(Outing.start_date >= date_from)
        if date_to:
            outing_query = outing_query.filter(Outing.start_date <= date_to)

        outings = outing_query.all()
        if not outings:
            return {"status": "success", "records": [], "summary": {"total_outings": 0, "total_species": 0, "total_photos": 0}}

        # Determine "new" species for each outing by processing from oldest to newest.
        # A species is new for an outing if it appears in that outing and no earlier outing.
        sorted_for_new_check = sorted(outings, key=lambda o: (o.start_date or "", o.created_at or ""))
        species_seen_before = set()
        outing_new_species = {}
        for outing in sorted_for_new_check:
            species_rows = (
                session.query(Photo.primary_bird_cn, Photo.scientific_name)
                .filter(
                    Photo.outing_id == outing.id,
                    Photo.primary_bird_cn.isnot(None),
                )
                .group_by(Photo.primary_bird_cn, Photo.scientific_name)
                .all()
            )
            current_keys = set()
            for row in species_rows:
                current_keys.add(row.scientific_name or row.primary_bird_cn)
                current_keys.add(row.primary_bird_cn)
            outing_new_species[outing.id] = current_keys - species_seen_before
            species_seen_before.update(current_keys)

        # Build records in descending order (most recent first)
        records = []
        for outing in outings:
            species_rows = (
                session.query(
                    Photo.primary_bird_cn,
                    Photo.scientific_name,
                    func.count(Photo.id).label("photo_count"),
                    func.max(Photo.quality_score).label("best_quality"),
                )
                .filter(
                    Photo.outing_id == outing.id,
                    Photo.primary_bird_cn.isnot(None),
                )
                .group_by(Photo.primary_bird_cn, Photo.scientific_name)
                .order_by(func.count(Photo.id).desc())
                .all()
            )

            species_list = []
            for row in species_rows:
                species_keys = {row.scientific_name or row.primary_bird_cn, row.primary_bird_cn}
                is_new = any(k in outing_new_species.get(outing.id, set()) for k in species_keys)
                species_list.append({
                    "cn": row.primary_bird_cn,
                    "scientific_name": row.scientific_name,
                    "photo_count": row.photo_count,
                    "best_quality": row.best_quality or 0,
                    "is_new": is_new,
                })

            location_parts = [p for p in [outing.location_tag] if p]
            location_name = " / ".join(location_parts) if location_parts else "未知地点"

            records.append({
                "outing_id": outing.id,
                "outing_name": outing.name,
                "start_date": outing.start_date,
                "end_date": outing.end_date,
                "location": location_name,
                "photo_count": sum(s["photo_count"] for s in species_list),
                "species_count": len(species_list),
                "new_species_count": sum(1 for s in species_list if s["is_new"]),
                "species": species_list,
            })

        summary = {
            "total_outings": len(records),
            "total_species": len({(s["cn"] or s["scientific_name"]) for r in records for s in r["species"]}),
            "total_photos": sum(r["photo_count"] for r in records),
        }

        return {
            "status": "success",
            "records": records,
            "summary": summary,
        }
    except Exception as e:
        logger.error(f"Failed to fetch birding log: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.get("/api/log/years")
def api_birding_log_years():
    """返回有观鸟记录的所有年份，用于筛选。"""
    session = get_sqlalchemy_session()
    try:
        rows = session.query(Outing.start_date).filter(Outing.start_date.isnot(None)).distinct().order_by(Outing.start_date.desc()).all()
        years = sorted({str(d[0])[:4] for d in rows if d[0]}, reverse=True)
        return {"status": "success", "years": years}
    except Exception as e:
        logger.error(f"Failed to fetch birding log years: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.get("/guide", response_class=HTMLResponse)
def guide_page(request: Request, q: str = ""):
    """鸟类图鉴：已解锁物种墙，按科分组。本次外拍新增物种高亮。"""
    session = get_sqlalchemy_session()
    try:
        # Determine the most recent outing as the "current" one
        current_outing = session.query(Outing).order_by(Outing.created_at.desc()).first()
        current_outing_id = current_outing.id if current_outing else None

        species_query = session.query(Species).filter(Species.photo_count > 0)
        if q:
            species_query = species_query.filter(
                (Species.chinese_name.like(f"%{q}%")) |
                (Species.scientific_name.like(f"%{q}%")) |
                (Species.family_cn.like(f"%{q}%")) |
                (Species.family_sci.like(f"%{q}%"))
            )
        species_list = species_query.order_by(Species.family_cn, Species.chinese_name).all()

        # A species is considered "new" in the current outing if it has photos
        # associated with that outing and no photos from earlier outings.
        if current_outing_id:
            species_in_current = set(
                row[0] for row in session.query(Photo.scientific_name).filter(
                    Photo.outing_id == current_outing_id,
                    Photo.scientific_name.isnot(None),
                ).distinct().all()
            )
            species_with_history = set(
                row[0] for row in session.query(Photo.scientific_name).filter(
                    Photo.outing_id != current_outing_id,
                    Photo.outing_id.isnot(None),
                    Photo.scientific_name.isnot(None),
                ).distinct().all()
            )
            new_species = species_in_current - species_with_history
        else:
            new_species = set()

        # Group by family
        families_map = {}
        for sp in species_list:
            key = sp.family_cn or "未分类"
            families_map.setdefault(key, {
                "family_cn": key,
                "family_sci": sp.family_sci or "",
                "species": [],
            })
            # Find best thumbnail: highest quality_score or latest photo
            photo = session.query(Photo).filter(
                Photo.scientific_name == sp.scientific_name
            ).order_by(Photo.quality_score.desc(), Photo.captured_date.desc()).first()
            thumb = None
            first_date = ""
            last_date = ""
            if photo:
                thumb = resolve_processed_web_path(photo.file_path) or resolve_web_path(photo.original_path)
                first_date = photo.captured_date or ""
                last_date = photo.captured_date or ""
            families_map[key]["species"].append({
                "scientific_name": sp.scientific_name,
                "chinese_name": sp.chinese_name,
                "photo_count": sp.photo_count or 0,
                "thumbnail_url": thumb,
                "first_date": first_date,
                "last_date": last_date,
                "is_new": sp.scientific_name in new_species,
            })

        families = sorted(families_map.values(), key=lambda x: x["family_cn"])
        total_species = sum(len(f["species"]) for f in families)
        total_families = len(families)

        return templates.TemplateResponse(
            request, "guide.html",
            {
                "request": request,
                "families": families,
                "total_species": total_species,
                "total_families": total_families,
                "query": q,
                "current_outing": current_outing,
            },
        )
    finally:
        session.close()


@app.get("/api/guide/species/{scientific_name}/history")
def guide_species_history(scientific_name: str):
    """返回某物种的历史拍摄记录：时间线（按外拍分组）和地图分布。"""
    session = get_sqlalchemy_session()
    try:
        # Verify species exists
        species = session.query(Species).filter(
            Species.scientific_name == scientific_name
        ).first()
        if not species:
            raise HTTPException(status_code=404, detail="Species not found")

        # Timeline grouped by outing
        outings = (
            session.query(
                Outing.id,
                Outing.name,
                Outing.start_date,
                func.count(Photo.id).label("photo_count"),
                func.min(Photo.captured_date).label("min_date"),
                func.max(Photo.captured_date).label("max_date"),
            )
            .join(Photo, Photo.outing_id == Outing.id)
            .filter(Photo.scientific_name == scientific_name)
            .group_by(Outing.id)
            .order_by(Outing.start_date.desc(), Outing.created_at.desc())
            .all()
        )

        timeline = []
        for outing in outings:
            best_photo = session.query(Photo).filter(
                Photo.scientific_name == scientific_name,
                Photo.outing_id == outing.id,
            ).order_by(Photo.quality_score.desc(), Photo.captured_date.desc()).first()
            thumbnail = None
            if best_photo:
                thumbnail = resolve_processed_web_path(best_photo.file_path) or resolve_web_path(best_photo.original_path)
            timeline.append({
                "outing_id": outing.id,
                "outing_name": outing.name,
                "start_date": outing.start_date,
                "photo_count": outing.photo_count,
                "date_range": f"{outing.min_date or ''} ~ {outing.max_date or ''}",
                "thumbnail": thumbnail,
            })

        # Map distribution: unique locations with coordinates and shot counts
        location_rows = (
            session.query(
                Photo.location_tag,
                Photo.location_level1,
                Photo.location_level2,
                Photo.location_level3,
                Photo.latitude,
                Photo.longitude,
                func.count(Photo.id).label("photo_count"),
            )
            .filter(
                Photo.scientific_name == scientific_name,
                (
                    (Photo.location_tag.isnot(None)) |
                    (Photo.location_level1.isnot(None)) |
                    (Photo.location_level2.isnot(None)) |
                    (Photo.location_level3.isnot(None)) |
                    (Photo.latitude.isnot(None)) |
                    (Photo.longitude.isnot(None))
                ),
            )
            .group_by(
                Photo.location_tag,
                Photo.location_level1,
                Photo.location_level2,
                Photo.location_level3,
                Photo.latitude,
                Photo.longitude,
            )
            .all()
        )

        locations = []
        for row in location_rows:
            parts = [p for p in [row.location_level1, row.location_level2, row.location_level3, row.location_tag] if p]
            location_name = " / ".join(parts) or "未知地点"
            locations.append({
                "name": location_name,
                "location_tag": row.location_tag,
                "location_level1": row.location_level1,
                "location_level2": row.location_level2,
                "location_level3": row.location_level3,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "photo_count": row.photo_count,
            })

        return {
            "status": "success",
            "species": {
                "scientific_name": species.scientific_name,
                "chinese_name": species.chinese_name,
                "family_cn": species.family_cn,
                "photo_count": species.photo_count,
            },
            "timeline": timeline,
            "locations": locations,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch species history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


if __name__ == "__main__":

    import argparse
    import uvicorn
    import subprocess
    import time

    parser = argparse.ArgumentParser(description='WingScribe Web Server')
    parser.add_argument('--host', type=str, default=None, help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to bind to')
    args = parser.parse_args()

    # Use command line args if provided, otherwise fall back to config
    host = args.host if args.host else config['web']['host']
    port = args.port if args.port else config['web']['port']

    # Save startup parameters for restart (globals already declared at module level)
    _startup_host = host
    _startup_port = port

    uvicorn.run(app, host=host, port=port)

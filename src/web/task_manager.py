import logging
import os
import threading
from pathlib import Path

from src.pipeline_runner import WingScribePipeline


BASE_DIR = Path(__file__).parent.parent.parent.absolute()
logger = logging.getLogger(__name__)


class ListLogHandler(logging.Handler):
    def __init__(self, log_list):
        super().__init__()
        self.log_list = log_list

    def emit(self, record):
        msg = self.format(record)
        self.log_list.append(msg)


class TaskManager:
    _instance = None

    def __init__(self):
        self.is_running = False
        self.should_stop = False
        self.logs = []
        self.websocket_clients = []

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance

    def stop(self):
        self.should_stop = True

    def broadcast_log(self, message: str):
        self.logs.append(message)
        if len(self.logs) > 1000:
            self.logs.pop(0)

    def start_pipeline(self, start_date=None, end_date=None):
        logger.info(
            f"[TaskManager] start_pipeline called with start_date={start_date}, end_date={end_date}"
        )
        if self.is_running:
            logger.warning("[TaskManager] Pipeline already running, rejecting request")
            return False

        self.is_running = True
        self.should_stop = False
        self.logs = ["Starting pipeline..."]
        logger.info("[TaskManager] Pipeline flag set, starting thread...")

        thread = threading.Thread(
            target=self._run_pipeline_thread,
            args=(start_date, end_date),
            daemon=True,
        )
        thread.start()
        logger.info("[TaskManager] Thread started, returning success")
        return True

    def start_pipeline_by_folders(self, folder_paths: list, recursive: bool = True):
        logger.info(
            f"[TaskManager] start_pipeline_by_folders called with paths={folder_paths}, recursive={recursive}"
        )
        if self.is_running:
            logger.warning("[TaskManager] Pipeline already running, rejecting request")
            return False

        self.is_running = True
        self.should_stop = False
        self.logs = ["Starting pipeline for selected folders..."]
        logger.info("[TaskManager] Pipeline flag set, starting thread...")

        thread = threading.Thread(
            target=self._run_pipeline_thread_by_folders,
            args=(folder_paths, recursive),
            daemon=True,
        )
        thread.start()
        logger.info("[TaskManager] Thread started, returning success")
        return True

    def _run_pipeline_thread_by_folders(self, folder_paths: list, recursive: bool):
        log_capture = logging.getLogger()
        handler = ListLogHandler(self.logs)
        try:
            os.chdir(str(BASE_DIR))
            log_capture.addHandler(handler)

            self.logs.append("Initializing pipeline (this may take a while on first run)...")
            runner = WingScribePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

            def progress_callback(processed, total):
                self.logs.append(f"[PROGRESS] {processed}/{total}")

            runner.set_progress_callback(progress_callback)
            runner.set_stop_checker(lambda: self.should_stop)

            self.logs.append("Pipeline initialized, processing selected folders...")
            runner.run_by_folders(folder_paths, recursive=recursive)
            logger.info("Pipeline (by folders) execution completed.")
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self.logs.append(f"Error: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)

    def start_import(self, folder_path: str, recursive: bool = True, run_recognition: bool = True, overwrite: bool = False, config: dict = None, location_info: dict = None, outing_id: int = None):
        """Start a guided import task: index photos then optionally run recognition pipeline."""
        logger.info(
            f"[TaskManager] start_import called with path={folder_path}, recursive={recursive}, run_recognition={run_recognition}, overwrite={overwrite}, location_info={location_info}, outing_id={outing_id}"
        )
        if self.is_running:
            logger.warning("[TaskManager] Task already running, rejecting import request")
            return False

        self.is_running = True
        self.should_stop = False
        self.logs = ["开始导入照片..."]
        logger.info("[TaskManager] Import flag set, starting thread...")

        thread = threading.Thread(
            target=self._run_import_thread,
            args=(folder_path, recursive, run_recognition, overwrite, config, location_info, outing_id),
            daemon=True,
        )
        thread.start()
        logger.info("[TaskManager] Import thread started, returning success")
        return True

    def start_video_import(self, folder_path: str, recursive: bool = True, overwrite: bool = False, config: dict = None, location_info: dict = None, outing_id: int = None):
        """Start a video-only import: index then probe/thumbnail, no recognition."""
        if self.is_running:
            logger.warning("[TaskManager] Task already running, rejecting video import")
            return False

        self.is_running = True
        self.should_stop = False
        self.logs = ["开始导入视频..."]

        thread = threading.Thread(
            target=self._run_video_import_thread,
            args=(folder_path, recursive, overwrite, config, location_info, outing_id),
            daemon=True,
        )
        thread.start()
        logger.info("[TaskManager] Video import thread started")
        return True

    def start_combined_import(self, folder_path: str, recursive: bool = True, run_recognition: bool = True, overwrite: bool = False, config: dict = None, location_info: dict = None, outing_id: int = None):
        """Import photos and videos in one task: videos indexed/probed first,
        then photos indexed and (optionally) recognized."""
        if self.is_running:
            logger.warning("[TaskManager] Task already running, rejecting combined import")
            return False

        self.is_running = True
        self.should_stop = False
        self.logs = ["开始导入照片与视频..."]

        thread = threading.Thread(
            target=self._run_combined_import_thread,
            args=(folder_path, recursive, run_recognition, overwrite, config, location_info, outing_id),
            daemon=True,
        )
        thread.start()
        logger.info("[TaskManager] Combined import thread started")
        return True

    def _run_import_thread(self, folder_path: str, recursive: bool, run_recognition: bool, overwrite: bool, config: dict, location_info: dict = None, outing_id: int = None):
        log_capture = logging.getLogger()
        handler = ListLogHandler(self.logs)
        try:
            os.chdir(str(BASE_DIR))
            log_capture.addHandler(handler)

            # Step 1: Index photos
            self.logs.append("正在扫描并索引照片...")
            from src.db.models import init_database as init_sqlalchemy_db, create_engine
            from src.db.repository import PhotoRepository
            from sqlalchemy.orm import sessionmaker
            from src.core.indexer import PhotoIndexer

            db_path = config.get("paths", {}).get("db_path", "data/birder.db") if config else "data/birder.db"
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{db_path}")
            init_sqlalchemy_db(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            try:
                if outing_id:
                    self.logs.append(f"外拍记录 ID：{outing_id}")

                supported_formats = config.get("paths", {}).get("supported_formats") if config else None
                indexer = PhotoIndexer(PhotoRepository(session), supported_formats=set(supported_formats) if supported_formats else None)
                result = indexer.index_folder_with_stats(Path(folder_path), recursive=recursive, overwrite=overwrite, location_info=location_info, outing_id=outing_id)
                self.logs.append(
                    f"索引完成：新增 {result['indexed']} 张，跳过重复 {result['skipped']} 张，失败 {result['errors']} 张，覆盖 {result.get('overwritten', 0)} 张，待识别 {len(result['photo_ids'])} 张（含未处理 {result.get('reprocessed', 0)} 张）"
                )
            finally:
                session.close()
                engine.dispose()

            # Step 2: Run recognition pipeline if requested
            if run_recognition and result.get("photo_ids"):
                self.logs.append("正在初始化识别 Pipeline...")
                runner = WingScribePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

                def progress_callback(processed, total):
                    self.logs.append(f"[PROGRESS] {processed}/{total}")

                runner.set_progress_callback(progress_callback)
                runner.set_stop_checker(lambda: self.should_stop)

                self.logs.append("开始识别、评分和连拍分组...")
                runner.run_by_photo_ids(result["photo_ids"], outing_id=outing_id)
                self.logs.append("导入完成！")
                logger.info("Import and pipeline execution completed.")
            elif run_recognition:
                self.logs.append("没有新增照片，跳过识别")
                self.logs.append("导入完成！")
            else:
                self.logs.append("导入完成（未运行识别）")
        except Exception as e:
            logger.error(f"Import failed: {e}")
            self.logs.append(f"错误: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)

    def _run_video_import_thread(self, folder_path: str, recursive: bool, overwrite: bool, config: dict, location_info: dict = None, outing_id: int = None):
        log_capture = logging.getLogger()
        handler = ListLogHandler(self.logs)
        engine = None
        try:
            os.chdir(str(BASE_DIR))
            log_capture.addHandler(handler)

            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from src.db.models import init_database as init_sqlalchemy_db
            from src.db.repository import VideoRepository
            from src.core.video.indexer import VideoIndexer

            db_path = config.get("paths", {}).get("db_path", "data/birder.db") if config else "data/birder.db"
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{db_path}")
            init_sqlalchemy_db(engine)
            session = sessionmaker(bind=engine)()
            try:
                self.logs.append("正在扫描并索引视频...")
                indexer = VideoIndexer(VideoRepository(session))
                result = indexer.index_folder_with_stats(
                    Path(folder_path), recursive=recursive, overwrite=overwrite,
                    location_info=location_info, outing_id=outing_id,
                )
                self.logs.append(
                    f"视频索引完成：新增 {result['indexed']} 个，"
                    f"跳过重复 {result['skipped']} 个，"
                    f"失败 {result['errors']} 个"
                )
                self._probe_videos(session, result["video_ids"])
            finally:
                session.close()
            self.logs.append("视频导入完成（无需识别）")
            logger.info("Video import completed.")
        except Exception as e:
            logger.error(f"Video import failed: {e}")
            self.logs.append(f"错误: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)
            if engine:
                engine.dispose()

    def _run_combined_import_thread(self, folder_path: str, recursive: bool, run_recognition: bool, overwrite: bool, config: dict, location_info: dict = None, outing_id: int = None):
        log_capture = logging.getLogger()
        handler = ListLogHandler(self.logs)
        engine = None
        photo_result = None
        try:
            os.chdir(str(BASE_DIR))
            log_capture.addHandler(handler)

            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from src.db.models import init_database as init_sqlalchemy_db
            from src.db.repository import VideoRepository, PhotoRepository
            from src.core.video.indexer import VideoIndexer
            from src.core.indexer import PhotoIndexer

            db_path = config.get("paths", {}).get("db_path", "data/birder.db") if config else "data/birder.db"
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{db_path}")
            init_sqlalchemy_db(engine)
            session = sessionmaker(bind=engine)()
            try:
                # 1) Videos: index + probe + poster
                self.logs.append("正在扫描并索引视频...")
                video_indexer = VideoIndexer(VideoRepository(session))
                video_result = video_indexer.index_folder_with_stats(
                    Path(folder_path), recursive=recursive, overwrite=overwrite,
                    location_info=location_info, outing_id=outing_id,
                )
                self.logs.append(
                    f"视频索引完成：新增 {video_result['indexed']} 个，"
                    f"跳过重复 {video_result['skipped']} 个"
                )
                self._probe_videos(session, video_result["video_ids"])

                # 2) Photos: index only (recognition runs afterwards)
                self.logs.append("正在扫描并索引照片...")
                supported_formats = config.get("paths", {}).get("supported_formats") if config else None
                photo_indexer = PhotoIndexer(
                    PhotoRepository(session),
                    supported_formats=set(supported_formats) if supported_formats else None,
                )
                photo_result = photo_indexer.index_folder_with_stats(
                    Path(folder_path), recursive=recursive, overwrite=overwrite,
                    location_info=location_info, outing_id=outing_id,
                )
                self.logs.append(
                    f"照片索引完成：新增 {photo_result['indexed']} 张，"
                    f"跳过重复 {photo_result['skipped']} 张，"
                    f"待识别 {len(photo_result['photo_ids'])} 张"
                )
            finally:
                session.close()

            # 3) Recognition applies to photos only; videos are never recognized
            if run_recognition and photo_result and photo_result.get("photo_ids"):
                self.logs.append("正在初始化识别 Pipeline...")
                runner = WingScribePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

                def progress_callback(processed, total):
                    self.logs.append(f"[PROGRESS] {processed}/{total}")

                runner.set_progress_callback(progress_callback)
                runner.set_stop_checker(lambda: self.should_stop)
                self.logs.append("开始照片识别、评分和连拍分组...")
                runner.run_by_photo_ids(photo_result["photo_ids"], outing_id=outing_id)
                self.logs.append("照片与视频导入完成！")
                logger.info("Combined import completed.")
            else:
                self.logs.append("照片与视频导入完成（未运行照片识别）")
        except Exception as e:
            logger.error(f"Combined import failed: {e}")
            self.logs.append(f"错误: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)
            if engine:
                engine.dispose()

    def _probe_videos(self, session, video_ids: list):
        """Probe indexed videos in place and generate poster thumbnails."""
        from src.db.repository import VideoRepository
        from src.core.video.ffmpeg_tools import probe_video, extract_poster

        repo = VideoRepository(session)
        thumb_dir = BASE_DIR / "data" / "video_thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)

        total = len(video_ids)
        if not total:
            self.logs.append("没有需要探测的视频")
            return

        self.logs.append(f"开始探测 {total} 个视频并生成缩略图...")
        for index, video_id in enumerate(video_ids, 1):
            video = repo.get_by_id(video_id)
            if not video:
                continue
            try:
                info = probe_video(video.file_path)
                video.duration = info.get("duration")
                video.width = info.get("width")
                video.height = info.get("height")
                video.fps = info.get("fps")
                video.video_codec = info.get("video_codec")
                video.audio_codec = info.get("audio_codec")
                video.probe_failed = False

                thumb_path = thumb_dir / f"{video.file_hash[:16]}.jpg"
                extract_poster(video.file_path, thumb_path)
                video.thumbnail_path = str(thumb_path)
                self.logs.append(f"[{index}/{total}] {video.filename} 探测完成")
            except Exception as exc:
                video.probe_failed = True
                logger.warning("视频探测失败 %s: %s", video.filename, exc)
                self.logs.append(
                    f"[{index}/{total}] {video.filename} 探测失败，已跳过"
                )
            session.commit()

    def _run_pipeline_thread(self, start_date, end_date):
        log_capture = logging.getLogger()
        handler = ListLogHandler(self.logs)
        try:
            os.chdir(str(BASE_DIR))
            log_capture.addHandler(handler)

            self.logs.append("Initializing pipeline (this may take a while on first run)...")
            runner = WingScribePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

            def progress_callback(processed, total):
                self.logs.append(f"[PROGRESS] {processed}/{total}")

            runner.set_progress_callback(progress_callback)
            runner.set_stop_checker(lambda: self.should_stop)

            self.logs.append("Pipeline initialized, starting processing...")
            runner.run(start_date=start_date, end_date=end_date)
            logger.info("Pipeline execution completed.")
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self.logs.append(f"Error: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)

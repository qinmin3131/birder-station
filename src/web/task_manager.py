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

    def start_import(self, folder_path: str, recursive: bool = True, run_recognition: bool = True, overwrite: bool = False, config: dict = None):
        """Start a guided import task: index photos then optionally run recognition pipeline."""
        logger.info(
            f"[TaskManager] start_import called with path={folder_path}, recursive={recursive}, run_recognition={run_recognition}, overwrite={overwrite}"
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
            args=(folder_path, recursive, run_recognition, overwrite, config),
            daemon=True,
        )
        thread.start()
        logger.info("[TaskManager] Import thread started, returning success")
        return True

    def _run_import_thread(self, folder_path: str, recursive: bool, run_recognition: bool, overwrite: bool, config: dict):
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
                supported_formats = config.get("paths", {}).get("supported_formats") if config else None
                indexer = PhotoIndexer(PhotoRepository(session), supported_formats=set(supported_formats) if supported_formats else None)
                result = indexer.index_folder_with_stats(Path(folder_path), recursive=recursive, overwrite=overwrite)
                self.logs.append(
                    f"索引完成：新增 {result['indexed']} 张，跳过重复 {result['skipped']} 张，失败 {result['errors']} 张，覆盖 {result.get('overwritten', 0)} 张"
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
                runner.run_by_photo_ids(result["photo_ids"])
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

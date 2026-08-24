# 淘汰照片一键移入回收站 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供一键操作，将淘汰照片（`rating == -1`）的原图与 `.xmp` sidecar 移入系统回收站、删除处理后裁切图缓存、删除数据库记录并刷新物种统计与连拍分组。

**Architecture:** 新增独立模块 `src/core/trash_service.py`（`TrashService`，注入 `session` / `source_dirs` / `processed_dir` / `send_func`，便于测试）。抽取两个公共函数：`src/db/stats.py:refresh_species_for_photo`（顺带修复 `app.py:1272` 从不存在模块导入 `create_db_manager` 的 bug）与 `src/web/path_helpers.py:resolve_original_path`。API 挂在 `src/web/app.py`（`/api/trash/preview`、`/api/trash/empty`），UI 在 `select.html` 与 `gallery.html` 各加一个按钮。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, SQLite, Jinja2 + Bootstrap 5, send2trash, pytest.

## Global Constraints

- **文件安全**: 原图与 `.xmp` sidecar 只能经 `send2trash` 送入系统回收站，禁止 `os.remove` 原图；处理后裁切图是系统生成缓存，且**仅当**其解析后的绝对路径位于 `processed_dir` 内时才允许 `os.remove`。
- **失败隔离**: 单张照片 `send2trash` 抛异常（占用、权限等）时记入 `errors` 且**不删除**其 DB 记录，继续处理下一张；原图文件缺失时记 `skipped` 但仍删除 DB 记录与关联文件。
- **数据一致性**: 删除 `Photo` 后必须：组内重选 `PhotoGroup.best_photo_id`（组空则删组）、刷新 `Species.photo_count`（归零则删除物种行）、刷新 sqlite3 物种统计。
- **测试**: Pytest；`send2trash` 通过构造器注入的 `send_func` 替换，测试不得触碰真实回收站。
- **Commit 风格**: 遵循仓库现有前缀（`功能:` / `修复:` / `验证:` 等）。

---

## Task 1: 公共函数抽取与依赖（含 app.py 导入 bug 修复）

**Files:**
- Create: `src/db/stats.py`
- Modify: `src/web/path_helpers.py`（文件末尾追加 `resolve_original_path`）
- Modify: `src/web/app.py`（`_refresh_species_for_photo` 委托；`_resolve_original_path` 委托；新增 import）
- Modify: `requirements.txt`
- Test: `tests/test_db_stats.py`（新建）
- Test: `tests/test_web_path_helpers.py`（追加用例）

**Interfaces:**
- Produces: `src.db.stats.refresh_species_for_photo(session: Session, scientific_name: str, manager_factory: Optional[Callable] = None) -> None`
- Produces: `src.web.path_helpers.resolve_original_path(path_str: Optional[str], source_dirs: Sequence[Path]) -> str`
- Consumes: `src.web.app.create_db_manager()`（无参，模块内已定义，app.py:171）

- [ ] **Step 1: 添加 send2trash 依赖**

在 `requirements.txt` 的 `pydantic` 行后追加：

```
send2trash>=1.8.0
```

Run: `pip install send2trash`
Expected: 安装成功。

- [ ] **Step 2: 写 stats 失败测试**

Create `tests/test_db_stats.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo, Species
from src.db.stats import refresh_species_for_photo


class FakeManager:
    def __init__(self):
        self.updated = []
        self.closed = 0

    def get_bird_info(self, scientific_name):
        return {"chinese_name": "麻雀", "family_cn": "雀科", "family_sci": "Passeridae"}

    def update_species_stats_for_photo(self, scientific_name):
        self.updated.append(scientific_name)

    def close(self):
        self.closed += 1


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_refresh_creates_species_with_photo_count(session):
    fake = FakeManager()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", scientific_name="Passer montanus"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", scientific_name="Passer montanus"))
    session.commit()

    refresh_species_for_photo(session, "Passer montanus", manager_factory=lambda: fake)

    sp = session.query(Species).filter(Species.scientific_name == "Passer montanus").first()
    assert sp is not None
    assert sp.photo_count == 2
    assert sp.chinese_name == "麻雀"
    assert fake.updated == ["Passer montanus"]


def test_refresh_updates_existing_species_count(session):
    session.add(Species(scientific_name="Passer montanus", photo_count=5))
    session.add(Photo(file_path="a.jpg", filename="a.jpg", scientific_name="Passer montanus"))
    session.commit()

    refresh_species_for_photo(session, "Passer montanus")

    sp = session.query(Species).filter(Species.scientific_name == "Passer montanus").first()
    assert sp.photo_count == 1


def test_refresh_deletes_species_when_no_photos(session):
    session.add(Species(scientific_name="Passer montanus", photo_count=1))
    session.commit()

    refresh_species_for_photo(session, "Passer montanus")

    assert session.query(Species).filter(Species.scientific_name == "Passer montanus").first() is None


def test_refresh_empty_name_is_noop(session):
    refresh_species_for_photo(session, "")
    assert session.query(Species).count() == 0
```

Run: `python -m pytest tests/test_db_stats.py -v`
Expected: FAIL（`ModuleNotFoundError: src.db.stats`）。

- [ ] **Step 3: 实现 `src/db/stats.py`**

Create `src/db/stats.py`:

```python
import logging
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Photo, Species

logger = logging.getLogger(__name__)


def refresh_species_for_photo(
    session: Session,
    scientific_name: str,
    manager_factory: Optional[Callable] = None,
) -> None:
    """Recalculate species stats after a photo is added/removed/corrected.

    Updates the SQLAlchemy ``species`` table (create/update/delete the row based
    on the remaining photo count) and, when *manager_factory* is provided,
    refreshes the legacy sqlite3 species_stats tree via the returned manager.
    """
    if not scientific_name:
        return

    stats = session.query(
        func.count(Photo.id).label("count"),
    ).filter(Photo.scientific_name == scientific_name).first()

    species = session.query(Species).filter(Species.scientific_name == scientific_name).first()

    if stats.count == 0:
        if species:
            session.delete(species)
    else:
        if not species:
            bird_info = None
            if manager_factory is not None:
                manager = manager_factory()
                try:
                    bird_info = manager.get_bird_info(scientific_name)
                finally:
                    manager.close()
            species = Species(
                scientific_name=scientific_name,
                chinese_name=bird_info.get("chinese_name") if bird_info else "",
                family_cn=bird_info.get("family_cn") if bird_info else "",
                family_sci=bird_info.get("family_sci") if bird_info else "",
                photo_count=0,
            )
            session.add(species)
        species.photo_count = stats.count

    session.commit()

    if manager_factory is not None:
        manager = manager_factory()
        try:
            manager.update_species_stats_for_photo(scientific_name)
        finally:
            manager.close()
```

注意：与旧 `app.py:_refresh_species_for_photo` 相比，删除了 `species.first_date = ...` / `species.last_date = ...` 两行——`Species` 模型没有这两列，属于无效的内存赋值（guide 页的 `first_date/last_date` 来自 `guide_page` 构造的 dict，不受影响）。

Run: `python -m pytest tests/test_db_stats.py -v`
Expected: 4 PASS。

- [ ] **Step 4: 修复 app.py 的 `_refresh_species_for_photo`（消除坏导入）**

现状（app.py:1267-1314）：函数内部 `from src.metadata.ioc_manager import create_db_manager`——`ioc_manager.py` 中不存在该函数，鸟种修正触发此路径会 ImportError。

修改 `src/web/app.py`：在文件顶部 import 区追加

```python
from src.db.stats import refresh_species_for_photo
```

并将整个 `_refresh_species_for_photo` 函数体替换为：

```python
def _refresh_species_for_photo(session, scientific_name: str):
    """Recalculate and update species stats in both SQLAlchemy and sqlite3 tables."""
    refresh_species_for_photo(session, scientific_name, manager_factory=create_db_manager)
```

Run: `python -m pytest tests/test_web_app.py tests/test_web_three_domain.py -v`
Expected: 全部 PASS（回归）。

- [ ] **Step 5: 抽取 `resolve_original_path` 到 path_helpers 并写测试**

在 `src/web/path_helpers.py` 末尾追加：

```python
def resolve_original_path(path_str: Optional[str], source_dirs: Sequence[Path]) -> str:
    """Resolve a stored photo path to an absolute filesystem path.

    Absolute paths are returned as-is. Relative paths are tried against each
    configured source directory; falls back to joining the first source dir.
    """
    if not path_str:
        return ""
    path_obj = Path(path_str)
    if path_obj.is_absolute() or is_absolute_path(path_str):
        return str(path_obj)
    for src_dir in source_dirs:
        candidate = Path(src_dir) / path_obj
        if candidate.exists():
            return str(candidate)
    if source_dirs:
        return str(Path(source_dirs[0]) / path_obj)
    return str(path_obj)
```

（`Optional` / `Sequence` 在 path_helpers.py 顶部 typing import 中补齐。）

在 `tests/test_web_path_helpers.py` 末尾追加：

```python
def test_resolve_original_path_absolute_passthrough(tmp_path):
    from src.web.path_helpers import resolve_original_path
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    assert resolve_original_path(str(p), []) == str(p)


def test_resolve_original_path_relative_against_sources(tmp_path):
    from src.web.path_helpers import resolve_original_path
    src = tmp_path / "src1"
    src.mkdir()
    (src / "sub" ).mkdir()
    (src / "sub" / "b.jpg").write_bytes(b"x")
    assert resolve_original_path("sub/b.jpg", [src]) == str(src / "sub" / "b.jpg")


def test_resolve_original_path_fallback_first_source(tmp_path):
    from src.web.path_helpers import resolve_original_path
    src = tmp_path / "src1"
    src.mkdir()
    assert resolve_original_path("missing.jpg", [src]) == str(src / "missing.jpg")


def test_resolve_original_path_empty():
    from src.web.path_helpers import resolve_original_path
    assert resolve_original_path("", [Path(".")]) == ""
    assert resolve_original_path(None, [Path(".")]) == ""
```

Run: `python -m pytest tests/test_web_path_helpers.py -v`
Expected: 新增 4 个 PASS。

- [ ] **Step 6: app.py 的 `_resolve_original_path` 委托给 path_helpers**

将 `src/web/app.py:997-1013` 的 `_resolve_original_path` 整体替换为：

```python
def _resolve_original_path(photo: Photo) -> str:
    """Return absolute path to the original photo file."""
    return path_helpers.resolve_original_path(photo.original_path or photo.file_path, source_dirs)
```

Run: `python -m pytest tests/test_web_review.py tests/test_web_app.py tests/test_web_path_helpers.py -v`
Expected: 全部 PASS（回归）。

- [ ] **Step 7: Commit**

```bash
git add requirements.txt src/db/stats.py src/web/path_helpers.py src/web/app.py tests/test_db_stats.py tests/test_web_path_helpers.py
git commit -m "功能: 抽取物种统计刷新与原图路径解析公共函数，修复 _refresh_species_for_photo 坏导入"
```

---

## Task 2: `src/core/trash_service.py` 核心服务

**Files:**
- Create: `src/core/trash_service.py`
- Test: `tests/test_trash_service.py`

**Interfaces:**
- Consumes: Task 1 的 `refresh_species_for_photo`、`resolve_original_path`；`src.db.models.Photo/PhotoGroup/Species`。
- Produces: `TrashService(session, source_dirs, processed_dir=None, send_func=send2trash.send2trash, manager_factory=None)`，方法 `list_rejected(outing_id: int = 0) -> dict`（返回 `{"count": int, "total_bytes": int, "sample_filenames": list[str]}`）与 `empty(outing_id: int = 0) -> dict`（返回 `{"moved": int, "deleted": int, "skipped": int, "errors": list[{"photo_id": int, "error": str}]}`）。Task 3 的 API 直接调用这两个方法。

- [ ] **Step 1: 写失败测试**

Create `tests/test_trash_service.py`:

```python
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.trash_service import TrashService
from src.db.models import Base, Photo, PhotoGroup, Species


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


@pytest.fixture
def sent():
    return []


@pytest.fixture
def service(session, tmp_path, sent):
    def _send(path):
        sent.append(str(path))
    processed = tmp_path / "processed"
    processed.mkdir()
    return TrashService(session, [tmp_path], processed_dir=processed, send_func=_send)


def _make_photo(tmp_path, name="a.jpg", rating=-1, **kwargs):
    src = tmp_path / name
    src.write_bytes(b"fake image data")
    return Photo(file_path=str(src), original_path=str(src), filename=name, rating=rating, **kwargs)


def test_empty_moves_original_and_sidecar_and_deletes_record(service, session, tmp_path, sent):
    photo = _make_photo(tmp_path)
    session.add(photo)
    session.commit()
    sidecar = tmp_path / "a.jpg.xmp"
    sidecar.write_text("<xmp/>", encoding="utf-8")

    result = service.empty()

    assert result["moved"] == 1
    assert result["deleted"] == 1
    assert result["errors"] == []
    assert sent == [str(tmp_path / "a.jpg"), str(sidecar)]
    assert session.query(Photo).count() == 0


def test_empty_filters_by_outing(service, session, tmp_path):
    p1 = _make_photo(tmp_path, "a.jpg", outing_id=1)
    p2 = _make_photo(tmp_path, "b.jpg", outing_id=2)
    session.add_all([p1, p2])
    session.commit()

    result = service.empty(outing_id=1)

    assert result["deleted"] == 1
    remaining = session.query(Photo).all()
    assert len(remaining) == 1
    assert remaining[0].outing_id == 2


def test_empty_ignores_non_rejected(service, session, tmp_path):
    session.add(_make_photo(tmp_path, "keep.jpg", rating=3))
    session.add(_make_photo(tmp_path, "bad.jpg", rating=-1))
    session.commit()

    result = service.empty()

    assert result["deleted"] == 1
    assert session.query(Photo).one().filename == "keep.jpg"


def test_missing_original_counts_skipped_but_deletes_record(service, session):
    session.add(Photo(file_path="D:/gone/a.jpg", original_path="D:/gone/a.jpg", filename="a.jpg", rating=-1))
    session.commit()

    result = service.empty()

    assert result["skipped"] == 1
    assert result["moved"] == 0
    assert result["deleted"] == 1
    assert session.query(Photo).count() == 0


def test_send_error_keeps_record(session, tmp_path):
    def boom(path):
        raise OSError("file in use")
    service = TrashService(session, [tmp_path], processed_dir=tmp_path / "processed", send_func=boom)
    session.add(_make_photo(tmp_path))
    session.commit()

    result = service.empty()

    assert result["errors"][0]["error"] == "file in use"
    assert result["deleted"] == 0
    assert session.query(Photo).count() == 1


def test_reselects_best_photo_in_group(service, session, tmp_path, sent):
    group = PhotoGroup(best_photo_id=0)
    session.add(group)
    session.flush()
    bad = _make_photo(tmp_path, "bad.jpg", group_id=group.id, quality_score=30)
    good = _make_photo(tmp_path, "good.jpg", rating=None, group_id=group.id, quality_score=90)
    session.add_all([bad, good])
    session.flush()
    group.best_photo_id = bad.id
    session.commit()

    service.empty()

    session.expire_all()
    assert group.best_photo_id == good.id
    assert session.query(PhotoGroup).count() == 1


def test_deletes_empty_group(service, session, tmp_path):
    group = PhotoGroup(best_photo_id=0)
    session.add(group)
    session.flush()
    bad = _make_photo(tmp_path, "bad.jpg", group_id=group.id)
    session.add(bad)
    session.flush()
    group.best_photo_id = bad.id
    session.commit()

    service.empty()

    assert session.query(PhotoGroup).count() == 0


def test_refreshes_species_stats(service, session, tmp_path):
    session.add(Species(scientific_name="Passer montanus", chinese_name="麻雀", photo_count=1))
    session.add(_make_photo(tmp_path, scientific_name="Passer montanus"))
    session.commit()

    service.empty()

    assert session.query(Species).filter(Species.scientific_name == "Passer montanus").first() is None


def test_removes_processed_crop_only_inside_processed_dir(service, session, tmp_path):
    processed = tmp_path / "processed"
    photo = _make_photo(tmp_path, "a.jpg")
    crop = processed / "a_crop.jpg"
    crop.write_bytes(b"crop")
    photo.file_path = str(crop)          # 裁切图在 processed_dir 内 → 应被直接删除
    session.add(photo)
    outside = _make_photo(tmp_path, "b.jpg")  # file_path == 原图，位于 processed_dir 外 → 不得删除
    session.add(outside)
    session.commit()

    service.empty()

    assert not crop.exists()
    assert (tmp_path / "b.jpg").exists()  # 原图仅被 send2trash，未被 os.remove


def test_list_rejected_counts_and_samples(service, session, tmp_path):
    for name in ["a.jpg", "b.jpg", "c.jpg"]:
        session.add(_make_photo(tmp_path, name))
    session.commit()

    info = service.list_rejected()

    assert info["count"] == 3
    assert info["total_bytes"] == 3 * len(b"fake image data")
    assert info["sample_filenames"] == ["a.jpg", "b.jpg", "c.jpg"]
```

Run: `python -m pytest tests/test_trash_service.py -v`
Expected: FAIL（`ModuleNotFoundError: src.core.trash_service`）。

- [ ] **Step 2: 实现 `src/core/trash_service.py`**

Create `src/core/trash_service.py`:

```python
import logging
import os
from pathlib import Path
from typing import Callable, Optional, Sequence

import send2trash
from sqlalchemy.orm import Session

from src.db.models import Photo, PhotoGroup
from src.db.stats import refresh_species_for_photo
from src.web.path_helpers import resolve_original_path

logger = logging.getLogger(__name__)


class TrashService:
    """Move rejected (rating == -1) photos to the OS recycle bin and delete
    their database records.

    ``send_func`` and ``manager_factory`` are injectable for tests; production
    code uses the defaults (``send2trash.send2trash`` and no legacy-stats
    manager, which the web layer supplies explicitly).
    """

    def __init__(
        self,
        session: Session,
        source_dirs: Sequence[Path],
        processed_dir: Optional[Path] = None,
        send_func: Callable = send2trash.send2trash,
        manager_factory: Optional[Callable] = None,
    ):
        self.session = session
        self.source_dirs = list(source_dirs)
        self.processed_dir = processed_dir
        self._send = send_func
        self._manager_factory = manager_factory

    def _rejected_query(self, outing_id: int):
        query = self.session.query(Photo).filter(Photo.rating == -1)
        if outing_id:
            query = query.filter(Photo.outing_id == outing_id)
        return query

    def list_rejected(self, outing_id: int = 0) -> dict:
        photos = self._rejected_query(outing_id).all()
        total_bytes = 0
        for p in photos:
            original = resolve_original_path(p.original_path or p.file_path, self.source_dirs)
            if original:
                try:
                    total_bytes += os.path.getsize(original)
                except OSError:
                    pass
        return {
            "count": len(photos),
            "total_bytes": total_bytes,
            "sample_filenames": [p.filename for p in photos[:5]],
        }

    def empty(self, outing_id: int = 0) -> dict:
        photos = self._rejected_query(outing_id).all()
        moved = 0
        deleted = 0
        skipped = 0
        errors: list[dict] = []
        affected_species: set[str] = set()

        for photo in photos:
            try:
                was_moved = self._trash_files(photo)
            except Exception as e:
                logger.error(f"Failed to trash files for photo {photo.id}: {e}")
                errors.append({"photo_id": photo.id, "error": str(e)})
                continue
            if was_moved:
                moved += 1
            else:
                skipped += 1
            if photo.scientific_name:
                affected_species.add(photo.scientific_name)
            self._delete_record(photo)
            deleted += 1

        for name in affected_species:
            try:
                refresh_species_for_photo(self.session, name, self._manager_factory)
            except Exception as e:
                logger.error(f"Failed to refresh species stats for {name}: {e}")

        return {"moved": moved, "deleted": deleted, "skipped": skipped, "errors": errors}

    def _trash_files(self, photo: Photo) -> bool:
        """Send original + .xmp sidecar to the recycle bin.

        Returns True if the original file existed (and was sent).
        """
        original = resolve_original_path(photo.original_path or photo.file_path, self.source_dirs)
        if not original or not Path(original).exists():
            return False
        self._send(original)
        sidecar = Path(original).with_suffix(Path(original).suffix + ".xmp")
        if sidecar.exists():
            self._send(str(sidecar))
        return True

    def _delete_record(self, photo: Photo) -> None:
        """Remove the processed crop cache, then delete the DB record and fix
        up the owning PhotoGroup."""
        self._remove_processed_crop(photo)
        group = None
        if photo.group_id:
            group = self.session.query(PhotoGroup).filter(PhotoGroup.id == photo.group_id).first()
        self.session.delete(photo)
        self.session.flush()
        if group is not None:
            remaining = self.session.query(Photo).filter(Photo.group_id == group.id).all()
            if not remaining:
                self.session.delete(group)
            elif group.best_photo_id == photo.id:
                best = max(remaining, key=lambda x: (x.quality_score or 0, x.id))
                group.best_photo_id = best.id
        self.session.commit()

    def _remove_processed_crop(self, photo: Photo) -> None:
        """Delete the generated crop only when it lives inside processed_dir.

        The crop is a system-generated cache, so it is removed directly (not
        via the recycle bin). The processed_dir guard makes it impossible to
        delete the user's original file through this path.
        """
        if not photo.file_path or not self.processed_dir:
            return
        path = Path(photo.file_path)
        if not path.is_absolute():
            path = Path(self.processed_dir) / path
        try:
            resolved = path.resolve()
            if resolved.is_file() and Path(self.processed_dir).resolve() in resolved.parents:
                os.remove(resolved)
        except OSError as e:
            logger.warning(f"Failed to remove processed crop {path}: {e}")
```

Run: `python -m pytest tests/test_trash_service.py -v`
Expected: 10 PASS。

- [ ] **Step 3: Commit**

```bash
git add src/core/trash_service.py tests/test_trash_service.py
git commit -m "功能: 实现 TrashService，淘汰照片原图/sidecar 移入回收站并清理记录与分组"
```

---

## Task 3: Web API 端点

**Files:**
- Modify: `src/web/app.py`（import + 两个端点，追加在 `write_gallery_metadata` 之后约 app.py:1265 处）
- Test: `tests/test_web_trash.py`

**Interfaces:**
- Consumes: Task 2 的 `TrashService`；app.py 模块级 `source_dirs`（`list[Path]`）、`processed_dir`（`Optional[Path]`）、`create_db_manager()`、`get_sqlalchemy_session()`。
- Produces: `GET /api/trash/preview?outing_id=0` → `{"status": "success", "count": int, "total_bytes": int, "sample_filenames": [str]}`；`POST /api/trash/empty`，body `{"outing_id": int}` → `{"status": "success", "moved": int, "deleted": int, "skipped": int, "errors": list}`。Task 4 前端调用这两个端点。

- [ ] **Step 1: 写失败测试**

Create `tests/test_web_trash.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo
from src.web import app as web_app


class FakeTrashService:
    last_init = None
    list_result = {"count": 2, "total_bytes": 1234, "sample_filenames": ["a.jpg", "b.jpg"]}
    empty_result = {"moved": 2, "deleted": 2, "skipped": 0, "errors": []}

    def __init__(self, session, source_dirs, processed_dir=None, **kwargs):
        FakeTrashService.last_init = {"source_dirs": source_dirs, "processed_dir": processed_dir}

    def list_rejected(self, outing_id: int = 0):
        self.last_outing_id = outing_id
        return FakeTrashService.list_result

    def empty(self, outing_id: int = 0):
        self.last_outing_id = outing_id
        return FakeTrashService.empty_result


def _create_temp_db(tmp_path: Path) -> str:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return str(db_path)


def test_trash_preview_endpoint(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    monkeypatch.setattr(web_app, "TrashService", FakeTrashService)

    result = web_app.trash_preview(outing_id=7)

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["sample_filenames"] == ["a.jpg", "b.jpg"]


def test_trash_empty_endpoint(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    monkeypatch.setattr(web_app, "TrashService", FakeTrashService)

    result = web_app.trash_empty(web_app.EmptyTrashRequest(outing_id=3))

    assert result["status"] == "success"
    assert result["moved"] == 2
    assert result["errors"] == []


def test_select_and_gallery_pages_have_trash_button(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    session_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(session_engine)
    SessionLocal = sessionmaker(bind=session_engine)
    monkeypatch.setattr(web_app, "get_sqlalchemy_session", lambda: SessionLocal())

    with TestClient(web_app.app) as client:
        select_resp = client.get("/select")
        gallery_resp = client.get("/gallery")

    assert select_resp.status_code == 200
    assert "清空淘汰" in select_resp.text
    assert gallery_resp.status_code == 200
    assert "清空淘汰" in gallery_resp.text
```

Run: `python -m pytest tests/test_web_trash.py -v`
Expected: 前两个测试 FAIL（`AttributeError: trash_preview / EmptyTrashRequest`），第三个 FAIL（页面无「清空淘汰」）。

- [ ] **Step 2: 实现端点**

修改 `src/web/app.py`：

1. 顶部 import 区追加：

```python
from src.core.trash_service import TrashService
```

2. 在 `SelectMarkRequest` 等 API Models 区域（约 app.py:704 后）追加：

```python
class EmptyTrashRequest(BaseModel):
    outing_id: int = 0
```

3. 在 `write_gallery_metadata` 函数（app.py:1234-1264）之后追加：

```python
@app.get("/api/trash/preview")
def trash_preview(outing_id: int = 0):
    """Preview rejected photos that would be moved to the OS recycle bin."""
    session = get_sqlalchemy_session()
    try:
        service = TrashService(session, source_dirs, processed_dir, manager_factory=create_db_manager)
        data = service.list_rejected(outing_id)
        return {"status": "success", **data}
    except Exception as e:
        logger.error(f"Failed to preview trash: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/trash/empty")
def trash_empty(req: EmptyTrashRequest):
    """Move rejected photos to the OS recycle bin and delete their records."""
    session = get_sqlalchemy_session()
    try:
        service = TrashService(session, source_dirs, processed_dir, manager_factory=create_db_manager)
        result = service.empty(req.outing_id)
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"Failed to empty trash: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
```

Run: `python -m pytest tests/test_web_trash.py::test_trash_preview_endpoint tests/test_web_trash.py::test_trash_empty_endpoint -v`
Expected: 2 PASS（第三个测试待 Task 4）。

- [ ] **Step 3: Commit**

```bash
git add src/web/app.py tests/test_web_trash.py
git commit -m "功能: 添加 /api/trash/preview 与 /api/trash/empty 接口"
```

---

## Task 4: UI 入口（选片页 + 图库页）

**Files:**
- Modify: `src/web/templates/select.html`
- Modify: `src/web/templates/gallery.html`
- Test: `tests/test_web_trash.py::test_select_and_gallery_pages_have_trash_button`（Task 3 已创建）

**Interfaces:**
- Consumes: Task 3 的两个端点；select.html 模板变量 `outing_id`（已存在，select.html:111 已使用）。

- [ ] **Step 1: 选片页按钮与 JS**

修改 `src/web/templates/select.html`，在按钮组中（约 line 110，`batchAction('reject')` 按钮之后、`查看本次外拍 → 图库` 链接之前）插入：

```html
                        <button class="btn btn-outline-danger" onclick="emptyTrash()">🗑️ 清空淘汰</button>
```

在 `<script>` 内 `autoPickBest` 函数定义之后追加：

```javascript
        function emptyTrash() {
            fetch(`/api/trash/preview?outing_id={{ outing_id }}`)
                .then(r => r.json())
                .then(data => {
                    if (!data.count) { alert('当前没有淘汰照片'); return; }
                    const mb = (data.total_bytes / 1024 / 1024).toFixed(1);
                    const samples = data.sample_filenames.join('、');
                    if (!confirm(`将把 ${data.count} 张淘汰照片移入系统回收站（约 ${mb} MB）。\n示例：${samples}\n\n此操作同时删除数据库记录；文件可在系统回收站还原。\n确认继续？`)) return;
                    fetch('/api/trash/empty', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({outing_id: {{ outing_id }}})
                    })
                        .then(r => r.json())
                        .then(res => {
                            alert(`完成：回收 ${res.moved} 张，删除记录 ${res.deleted} 条，跳过 ${res.skipped} 张，失败 ${res.errors.length} 张`);
                            location.reload();
                        })
                        .catch(e => { console.error(e); alert('清空淘汰失败'); });
                })
                .catch(e => { console.error(e); alert('获取淘汰照片预览失败'); });
        }
```

- [ ] **Step 2: 图库页按钮与 JS**

修改 `src/web/templates/gallery.html`，在 line 139「💾 写入选中照片元数据」按钮之后插入：

```html
                                <button class="btn btn-sm btn-outline-danger" type="button" onclick="emptyTrash()">🗑️ 清空淘汰照片</button>
```

在 `<script>` 内 `writeSelectedMetadata` 函数定义之后追加：

```javascript
        function emptyTrash() {
            fetch('/api/trash/preview?outing_id=0')
                .then(r => r.json())
                .then(data => {
                    if (!data.count) { alert('当前没有淘汰照片'); return; }
                    const mb = (data.total_bytes / 1024 / 1024).toFixed(1);
                    const samples = data.sample_filenames.join('、');
                    if (!confirm(`将把全部 ${data.count} 张淘汰照片移入系统回收站（约 ${mb} MB）。\n示例：${samples}\n\n此操作同时删除数据库记录；文件可在系统回收站还原。\n确认继续？`)) return;
                    fetch('/api/trash/empty', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({outing_id: 0})
                    })
                        .then(r => r.json())
                        .then(res => {
                            alert(`完成：回收 ${res.moved} 张，删除记录 ${res.deleted} 条，跳过 ${res.skipped} 张，失败 ${res.errors.length} 张`);
                            location.reload();
                        })
                        .catch(e => { console.error(e); alert('清空淘汰失败'); });
                })
                .catch(e => { console.error(e); alert('获取淘汰照片预览失败'); });
        }
```

- [ ] **Step 3: 跑测试验证**

Run: `python -m pytest tests/test_web_trash.py -v`
Expected: 3 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/select.html src/web/templates/gallery.html tests/test_web_trash.py
git commit -m "功能: 选片页与图库页新增一键清空淘汰入口"
```

---

## Task 5: 全量验证

**Files:**
- 以上全部。

- [ ] **Step 1: 全量测试**

Run: `python -m pytest`
Expected: 全部 PASS（含既有 348 项 + 新增用例），无新 failure。

- [ ] **Step 2: 语法检查**

Run: `python -m py_compile src/core/trash_service.py src/db/stats.py src/web/app.py src/web/path_helpers.py`
Expected: 无输出（退出码 0）。

- [ ] **Step 3: 变更审查**

Run: `git diff --stat HEAD~4`
Expected: 变更范围与本计划一致（trash_service、stats、path_helpers、app.py、两个模板、requirements、四个测试文件）。

---

## Spec 覆盖自查

| 设计文档条目 | 覆盖 Task |
|--------------|-----------|
| `TrashService.list_rejected` / `empty`（src/core/trash_service.py） | Task 2 |
| 原图 + sidecar 送回收站、裁切图直接删（含 processed_dir 护栏） | Task 2（`_trash_files` / `_remove_processed_crop`） |
| best_photo_id 重选 / 空组删除 / 物种统计刷新 | Task 2（`_delete_record` / `empty`） |
| `refresh_species_for_photo` 迁移复用 + 修复坏导入 | Task 1 |
| `resolve_original_path` 抽取复用 | Task 1 |
| `/api/trash/preview`、`/api/trash/empty` | Task 3 |
| 选片页按钮（当前外拍）、图库页按钮（全部）+ 确认弹窗 | Task 4 |
| send2trash 依赖 | Task 1 Step 1 |
| 错误处理矩阵（缺失→skipped、异常→errors 且保留记录、无淘汰→count 0） | Task 2 测试 + Task 4 JS |
| 范围之外（不做恢复入口/自动清空/单张回收） | 无对应 Task（符合 YAGNI） |

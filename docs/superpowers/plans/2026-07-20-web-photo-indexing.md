# Web Photo Indexing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend API, frontend page, and tests for indexing photos from a selected folder.

**Architecture:** Extend `src/web/app.py` with a new API route and page route; add a stats-returning method to `PhotoIndexer`; create a new Bootstrap template; add unit tests in `tests/test_web_index.py`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, Jinja2, Bootstrap 5, PyTest.

## Global Constraints

- Python 3.11+, 4-space indentation, PEP 8.
- `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Type hints for public interfaces.
- Every behavior change must have tests.
- Tests must pass before commit.
- Commit style: scoped prefixes like `功能:`, `UI:`, `测试:`.

---

## Task 1: Add `index_folder_with_stats` to `PhotoIndexer`

**Files:**
- Modify: `src/core/indexer.py`
- Test: `tests/test_indexer.py` (add new test)

**Interfaces:**
- Consumes: `PhotoRepository` (`get_by_hash`, `add`), `Photo` model.
- Produces: `PhotoIndexer.index_folder_with_stats(folder: Path, recursive: bool = True) -> dict` returning `{"indexed": int, "skipped": int, "errors": int}`.

- [ ] **Step 1: Add failing test**

```python
def test_index_folder_with_stats_counts_indexed_and_skipped(repo, tmp_path):
    indexer = PhotoIndexer(repo)
    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (100, 100), color="green").save(img_path)
    duplicate = tmp_path / "bird_copy.jpg"
    Image.new("RGB", (100, 100), color="green").save(duplicate)
    (tmp_path / "notes.txt").write_text("not a photo")

    result = indexer.index_folder_with_stats(tmp_path)

    assert result == {"indexed": 1, "skipped": 1, "errors": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_indexer.py::test_index_folder_with_stats_counts_indexed_and_skipped -v`
Expected: FAIL with `AttributeError: 'PhotoIndexer' object has no attribute 'index_folder_with_stats'`.

- [ ] **Step 3: Implement method**

Add to `src/core/indexer.py` after `index_folder`:

```python
def index_folder_with_stats(self, folder: Path, recursive: bool = True) -> dict:
    indexed = 0
    skipped = 0
    errors = 0
    glob_pattern = "**/*" if recursive else "*"
    for path in folder.glob(glob_pattern):
        if not path.is_file():
            continue
        if path.suffix.lower() not in self.supported_formats:
            continue
        try:
            file_hash = self._file_hash(path)
            existing = self.repo.get_by_hash(file_hash)
            if existing is not None:
                logger.info(f"Skipping duplicate photo: {path} (hash {file_hash[:8]}...)")
                skipped += 1
                continue
            photo = Photo(
                file_path=str(path),
                filename=path.name,
                original_path=str(path),
                file_hash=file_hash,
            )
            self.repo.add(photo)
            indexed += 1
        except Exception as e:
            logger.error(f"Failed to index {path}: {e}")
            errors += 1
    return {"indexed": indexed, "skipped": skipped, "errors": errors}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_indexer.py::test_index_folder_with_stats_counts_indexed_and_skipped -v`
Expected: PASS.

- [ ] **Step 5: Run full indexer tests**

Run: `python -m pytest tests/test_indexer.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/core/indexer.py tests/test_indexer.py
git commit -m "功能: 为 PhotoIndexer 添加索引统计方法"
```

---

## Task 2: Add Backend API `POST /api/index` and Session Helper

**Files:**
- Modify: `src/web/app.py`
- Test: `tests/test_web_index.py`

**Interfaces:**
- Consumes: `db_path` global, `config` global, `PhotoIndexer`, `PhotoRepository`.
- Produces: `POST /api/index` returns `{"indexed": int, "skipped": int, "errors": int}`; `get_sqlalchemy_session()` returns `Session`.

- [ ] **Step 1: Add test for API endpoint**

Create/update `tests/test_web_index.py`:

```python
from pathlib import Path
from PIL import Image
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.web import app as web_app


def _create_temp_db(tmp_path: Path) -> str:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return str(db_path)


def test_api_index_counts_indexed_and_skipped(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    monkeypatch.setattr(web_app, "config", {"paths": {"supported_formats": [".jpg", ".jpeg"]}})

    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (100, 100), color="red").save(folder / "a.jpg")
    Image.new("RGB", (100, 100), color="red").save(folder / "b.jpg")

    result = web_app.index_photos(
        web_app.IndexRequest(folder=str(folder), recursive=True)
    )

    assert result == {"indexed": 2, "skipped": 0, "errors": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web_index.py::test_api_index_counts_indexed_and_skipped -v`
Expected: FAIL with `AttributeError: module 'src.web.app' has no attribute 'index_photos'` or `IndexRequest` not defined.

- [ ] **Step 3: Implement API endpoint and helper**

In `src/web/app.py` add imports:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.core.indexer import PhotoIndexer
from src.db.repository import PhotoRepository
```

Add request model near other API models:

```python
class IndexRequest(BaseModel):
    folder: str
    recursive: bool = True
```

Add helper after `get_db_conn`:

```python
def get_sqlalchemy_session():
    engine = create_engine(f"sqlite:///{db_path}")
    return sessionmaker(bind=engine)()
```

Add endpoint:

```python
@app.post("/api/index")
def index_photos(req: IndexRequest):
    folder_path = Path(req.folder)
    if not folder_path.exists() or not folder_path.is_dir():
        raise HTTPException(status_code=400, detail="Folder does not exist or is not a directory")

    session = get_sqlalchemy_session()
    try:
        repo = PhotoRepository(session)
        supported_formats = set(config.get("paths", {}).get("supported_formats", []))
        indexer = PhotoIndexer(repo, supported_formats=supported_formats)
        result = indexer.index_folder_with_stats(folder_path, req.recursive)
        return result
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web_index.py::test_api_index_counts_indexed_and_skipped -v`
Expected: PASS.

- [ ] **Step 5: Add test for duplicate skipping**

```python
def test_api_index_skips_duplicate_photos(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    monkeypatch.setattr(web_app, "config", {"paths": {"supported_formats": [".jpg"]}})

    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (100, 100), color="blue").save(folder / "bird.jpg")

    first = web_app.index_photos(web_app.IndexRequest(folder=str(folder)))
    second = web_app.index_photos(web_app.IndexRequest(folder=str(folder)))

    assert first == {"indexed": 1, "skipped": 0, "errors": 0}
    assert second == {"indexed": 0, "skipped": 1, "errors": 0}
```

- [ ] **Step 6: Run duplicate test**

Run: `python -m pytest tests/test_web_index.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/web/app.py tests/test_web_index.py
git commit -m "功能: 添加照片索引 API 与 SQLAlchemy 会话辅助"
```

---

## Task 3: Add Frontend Page `/admin/index`

**Files:**
- Create: `src/web/templates/admin_index.html`
- Modify: `src/web/app.py` (add route)
- Modify: `src/web/templates/admin.html` (add link)

**Interfaces:**
- Consumes: `templates` global, `IndexRequest` model.
- Produces: `GET /admin/index` renders `admin_index.html`.

- [ ] **Step 1: Create template**

Create `src/web/templates/admin_index.html` with Bootstrap layout and JavaScript for folder dialog and indexing API.

- [ ] **Step 2: Add route**

In `src/web/app.py`:

```python
@app.get("/admin/index", response_class=HTMLResponse)
def admin_index_page(request: Request):
    return templates.TemplateResponse("admin_index.html", {"request": request})
```

- [ ] **Step 3: Link from `/admin`**

Add a link/button in `src/web/templates/admin.html` pointing to `/admin/index`.

- [ ] **Step 4: Verify page renders**

Run: `python -m pytest tests/test_web_app.py -v` (existing tests should still pass) and manually start server if needed.

- [ ] **Step 5: Commit**

```bash
git add src/web/templates/admin_index.html src/web/templates/admin.html src/web/app.py
git commit -m "UI: 添加 /admin/index 索引页面"
```

---

## Task 4: Full Test Run and Final Commit

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_web_index.py -v`
Expected: All pass.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest -v`
Expected: All pass.

- [ ] **Step 3: Commit any remaining changes**

If no further changes, no extra commit needed.

- [ ] **Step 4: Report back**

Write report to `docs/superpowers/reports/task-web-index-report.md` and report status.

---

## Self-Review Checklist

- [ ] Spec coverage: backend API, frontend page, tests, link from admin all implemented.
- [ ] No placeholders: every step has code/commands.
- [ ] Type consistency: `index_folder_with_stats` returns `dict` with keys `indexed`, `skipped`, `errors`; `IndexRequest` has `folder: str`, `recursive: bool`.
- [ ] Backward compatibility: existing `index_folder` return type unchanged.
- [ ] Tests included for new behavior.

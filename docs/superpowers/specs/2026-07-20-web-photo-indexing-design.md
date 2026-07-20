# Web Photo Indexing Page Design

## Overview

Add a dedicated web page and API for indexing photos into the WingScribe database. The feature is grouped under `/admin` and uses the existing `PhotoIndexer` + `PhotoRepository` stack.

## Decisions

- **Folder dialog API**: Keep the existing query-param style `POST /api/config/browse_folder?title=...&initial_path=...`.
- **Page route**: `GET /admin/index`, linked from the existing `/admin` page.
- **Database session**: Add a small helper in `src/web/app.py` to create a SQLAlchemy session from the configured `db_path`.

## Components

### Backend (`src/web/app.py`)

- `IndexRequest` Pydantic model: `{ folder: str, recursive: bool = true }`.
- `get_sqlalchemy_session()` helper returns a SQLAlchemy `Session` bound to `sqlite:///{db_path}`.
- `POST /api/index`:
  1. Validate folder exists and is a directory.
  2. Open a SQLAlchemy session and instantiate `PhotoRepository`.
  3. Instantiate `PhotoIndexer` with configured `supported_formats`.
  4. Call `PhotoIndexer.index_folder_with_stats(...)` and return `{indexed, skipped, errors}`.
  5. Close the session and handle errors gracefully.

### Indexer (`src/core/indexer.py`)

- Add `index_folder_with_stats(self, folder: Path, recursive: bool = True) -> dict`.
- Returns `{"indexed": int, "skipped": int, "errors": int}`.
- Existing `index_folder` remains unchanged to preserve current tests.

### Frontend

- `GET /admin/index` renders `src/web/templates/admin_index.html`.
- Template contains:
  - Folder path input + “Browse” button calling `/api/config/browse_folder`.
  - “Recursive” checkbox.
  - “Start Indexing” button calling `POST /api/index`.
  - Results area showing `indexed`, `skipped`, `errors`.
- The existing `/admin` page gets a link to `/admin/index`.

### Tests

- `tests/test_web_index.py`:
  - Create a temp SQLAlchemy database.
  - Create a temp folder with images and a duplicate.
  - Call `index_photos` directly.
  - Assert the response counts match the created files.

## Error Handling

- Non-existent folder → `400 Bad Request`.
- Indexing errors → `500 Internal Server Error` and logged; partial counts returned only if the indexer handles them internally.

## Global Constraints

- Python 3.11+, 4-space indentation, PEP 8.
- Type hints for public interfaces.
- Every behavior change must have tests.
- Commit style: scoped prefixes like `功能:`, `UI:`, `测试:`.

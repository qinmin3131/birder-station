# Dev-Newspec 鸟类照片管理系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 `dev-newspec` 分支的 `spec.md`，将现有 WingScribe 重构为面向生态摄影爱好者的本地鸟类照片管理系统：保留照片原位、支持 RAW 解码、增加多维画质评估/连拍分组/选片工作台/图鉴三域动线，并建立 SQLAlchemy 数据层。

**Architecture:** 保持现有 `src/core`、`src/recognition`、`src/metadata`、`src/web` 分层，新增 `src/db`（SQLAlchemy 模型 + Repository）作为唯一数据层。新增 `src/core/indexer.py`、`src/core/pose.py`、`src/core/focus.py`、`src/core/grouper.py` 支撑选片工作流。Web 层从单页相册拆分为 `/select`、 `/gallery`、 `/guide` 三域。识别复用 YOLO + BioCLIP，画质评估从单一 Laplacian 扩展为 7 维加权评分。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, SQLite, Jinja2, rawpy, Pillow, OpenCV, Ant Design (CDN), PyExifTool/exiftool.

## Global Constraints

- **仅索引不移动**: 照片保持原位，系统通过数据库记录位置和元数据。
- **本地优先**: 所有功能本地运行，无需服务器。
- **三域动线**: 选片（`/select`）→ 图库（`/gallery`）→ 图鉴（`/guide`），单向递进。
- **分层减量工作流**: 导入 → 自动分析 → 智能缩略图 → 组内复核 → 最终精选。
- **选片即入库**: 选片结果直接影响图库筛选和图鉴物种解锁。
- **RAW 安全**: RAW 文件只生成 `.xmp` sidecar，不修改原文件；JPEG 可直接写入 EXIF。
- **Python 3.11+**: 使用 4 空格缩进、PEP 8、snake_case/PascalCase/UPPER_SNAKE_CASE。
- **测试**: Pytest，行为变更必须补充测试，尤其是路径解析、画质、DB、元数据流程。

---

## Phase 1: Data Layer & Configuration

### Task 1.1: Create SQLAlchemy models in `src/db/models.py`

**Files:**
- Create: `src/db/__init__.py`
- Create: `src/db/models.py`
- Modify: `requirements.txt`
- Test: `tests/test_db_models.py`

**Interfaces:**
- Produces: `Photo`, `RecognitionResult`, `Species`, `PhotoGroup`, `Outing` SQLAlchemy ORM classes.
- Produces: `Base.metadata.create_all(engine)` 初始化表。

- [ ] **Step 1: Add SQLAlchemy dependency**

`requirements.txt` 中已含 `sqlalchemy`，但需确保版本 2.x。检查并固定：

```
sqlalchemy>=2.0.0
aiosqlite>=0.20.0
rawpy>=0.23.0
```

Run: `pip install -r requirements.txt`
Expected: 成功安装，无冲突。

- [ ] **Step 2: Define ORM models**

Create `src/db/models.py`:

```python
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON, Text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Species(Base):
    __tablename__ = "species"
    id = Column(Integer, primary_key=True)
    scientific_name = Column(String, unique=True, nullable=False)
    chinese_name = Column(String)
    english_name = Column(String)
    family_cn = Column(String)
    order_cn = Column(String)
    genus_cn = Column(String)
    family_sci = Column(String)
    order_sci = Column(String)
    genus_sci = Column(String)
    photo_count = Column(Integer, default=0)

class Photo(Base):
    __tablename__ = "photos"
    id = Column(Integer, primary_key=True)
    file_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    original_path = Column(String)
    file_hash = Column(String, unique=True)
    captured_at = Column(DateTime)
    captured_date = Column(String)
    location_tag = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    primary_bird_cn = Column(String)
    scientific_name = Column(String)
    confidence_score = Column(Float)
    candidates_json = Column(JSON)
    width = Column(Integer)
    height = Column(Integer)
    is_selected = Column(Boolean, default=False)
    rating = Column(Integer)
    quality_score = Column(Integer)
    quality_details = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

class PhotoGroup(Base):
    __tablename__ = "photo_groups"
    id = Column(Integer, primary_key=True)
    outing_id = Column(Integer, ForeignKey("outings.id"))
    best_photo_id = Column(Integer, ForeignKey("photos.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

class Outing(Base):
    __tablename__ = "outings"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    location_tag = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 3: Write failing tests for model creation**

Create `tests/test_db_models.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, Photo, Species

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

def test_create_photo(session):
    photo = Photo(file_path="D:/Photos/test.jpg", filename="test.jpg")
    session.add(photo)
    session.commit()
    assert photo.id is not None

def test_create_species(session):
    sp = Species(scientific_name="Acrocephalus arundinaceus", chinese_name="大苇莺")
    session.add(sp)
    session.commit()
    assert sp.id is not None
```

Run: `python -m pytest tests/test_db_models.py -v`
Expected: FAIL with import errors (models not yet created). Wait until after Step 2, then PASS.

- [ ] **Step 4: Verify tests pass**

Run: `python -m pytest tests/test_db_models.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/db/ tests/test_db_models.py requirements.txt
git commit -m "功能: 添加 SQLAlchemy 数据模型 (Photo, Species, PhotoGroup, Outing)"
```

---

### Task 1.2: Create Repository layer in `src/db/repository.py`

**Files:**
- Create: `src/db/repository.py`
- Test: `tests/test_db_repository.py`

**Interfaces:**
- Consumes: `src.db.models` ORM classes and a `session`.
- Produces: `PhotoRepository`, `SpeciesRepository`, `OutingRepository` with CRUD methods.

- [ ] **Step 1: Implement PhotoRepository**

Create `src/db/repository.py`:

```python
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from src.db.models import Photo, Species, Outing, PhotoGroup

class PhotoRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, photo_id: int) -> Optional[Photo]:
        return self.session.query(Photo).filter(Photo.id == photo_id).first()

    def add(self, photo: Photo) -> Photo:
        self.session.add(photo)
        self.session.commit()
        self.session.refresh(photo)
        return photo

    def list_photos(self, limit: int = 50, offset: int = 0,
                    is_selected: Optional[bool] = None) -> List[Photo]:
        query = self.session.query(Photo)
        if is_selected is not None:
            query = query.filter(Photo.is_selected == is_selected)
        return query.order_by(Photo.captured_at.desc()).offset(offset).limit(limit).all()

    def update_species(self, photo_id: int, scientific_name: str, chinese_name: str) -> None:
        photo = self.get_by_id(photo_id)
        if photo:
            photo.scientific_name = scientific_name
            photo.primary_bird_cn = chinese_name
            photo.confidence_score = 1.0
            self.session.commit()
```

- [ ] **Step 2: Add SpeciesRepository and OutingRepository stubs**

Extend `src/db/repository.py`:

```python
class SpeciesRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_scientific_name(self, name: str) -> Optional[Species]:
        return self.session.query(Species).filter(Species.scientific_name == name).first()

    def add(self, species: Species) -> Species:
        self.session.add(species)
        self.session.commit()
        self.session.refresh(species)
        return species

    def list_unlocked(self) -> List[Species]:
        return self.session.query(Species).filter(Species.photo_count > 0).all()

class OutingRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_or_create(self, name: str, start_date: str) -> Outing:
        outing = self.session.query(Outing).filter(
            Outing.name == name, Outing.start_date == start_date
        ).first()
        if not outing:
            outing = Outing(name=name, start_date=start_date)
            self.session.add(outing)
            self.session.commit()
            self.session.refresh(outing)
        return outing
```

- [ ] **Step 3: Write tests**

Create `tests/test_db_repository.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, Photo
from src.db.repository import PhotoRepository

@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return PhotoRepository(Session())

def test_add_and_get_photo(repo):
    photo = Photo(file_path="D:/test.jpg", filename="test.jpg")
    added = repo.add(photo)
    assert added.id is not None
    fetched = repo.get_by_id(added.id)
    assert fetched.filename == "test.jpg"
```

Run: `python -m pytest tests/test_db_repository.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/db/repository.py tests/test_db_repository.py
git commit -m "功能: 添加 Repository 数据访问层"
```

---

### Task 1.3: Update project configuration (`config/settings.yaml`)

**Files:**
- Modify: `config/settings.yaml`
- Create: `config/settings.example.yaml` (if not exists)

**Interfaces:**
- Produces: `config` dict with `paths`, `quality.weights`, `grouper.time_window`, `metadata.write_mode`.

- [ ] **Step 1: Add new configuration keys**

Modify `config/settings.yaml` to include:

```yaml
paths:
  sources:
    - path: "D:/Photos/Birds"
      recursive: true
  db_path: "data/birder.db"
  supported_formats: [".jpg", ".jpeg", ".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"]

processing:
  device: auto
  yolo_model: data/models/yolo26n.pt
  confidence_threshold: 0.5

recognition:
  mode: local
  top_k: 5

metadata:
  write_mode: "xmp_sidecar"
  generate_xmp_sidecar: true

quality:
  weights:
    clarity: 0.25
    contrast: 0.10
    position: 0.10
    exposure: 0.10
    pose: 0.20
    bif: 0.10
    focus: 0.15
  pose_upgrade_threshold:
    head_eye_visible: true
    flight_probability: 0.35

grouper:
  time_window: 5

web:
  host: "0.0.0.0"
  port: 8000
```

- [ ] **Step 2: Update config loader if needed**

Check `src/utils/config_loader.py` for compatibility with new keys. If it validates paths strictly, loosen validation for `supported_formats` and `quality.weights`.

Run: `python -c "from src.utils.config_loader import load_config; print(load_config('config/settings.yaml'))"`
Expected: 成功加载，无异常。

- [ ] **Step 3: Commit**

```bash
git add config/settings.yaml
git commit -m "配置: 更新 settings.yaml 以匹配 dev-newspec 配置项"
```

---

## Phase 2: Indexer & RAW Decoding

### Task 2.1: Create `src/core/indexer.py` for photo indexing

**Files:**
- Create: `src/core/indexer.py`
- Test: `tests/test_indexer.py`

**Interfaces:**
- Consumes: `PhotoRepository`, `file_path`, `supported_formats`.
- Produces: `index_photos(folder: Path) -> List[Photo]`.

- [ ] **Step 1: Implement file scanning and hash check**

Create `src/core/indexer.py`:

```python
import hashlib
import logging
from pathlib import Path
from typing import List, Set
from src.db.models import Photo
from src.db.repository import PhotoRepository

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"}

class PhotoIndexer:
    def __init__(self, repo: PhotoRepository, supported_formats: Set[str] = None):
        self.repo = repo
        self.supported_formats = supported_formats or SUPPORTED_FORMATS

    def _file_hash(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def index_folder(self, folder: Path, recursive: bool = True) -> List[Photo]:
        photos = []
        glob = "**/*" if recursive else "*"
        for path in folder.glob(glob):
            if path.suffix.lower() not in self.supported_formats:
                continue
            try:
                file_hash = self._file_hash(path)
                # TODO: check hash exists in DB
                photo = Photo(
                    file_path=str(path),
                    filename=path.name,
                    original_path=str(path),
                    file_hash=file_hash,
                )
                photos.append(self.repo.add(photo))
            except Exception as e:
                logging.error(f"Failed to index {path}: {e}")
        return photos
```

- [ ] **Step 2: Write test for folder indexing**

Create `tests/test_indexer.py` with a temporary folder containing a JPEG and a non-image file.

Run: `python -m pytest tests/test_indexer.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/core/indexer.py tests/test_indexer.py
git commit -m "功能: 实现照片索引扫描与去重基础"
```

---

### Task 2.2: Add RAW decoding support using `rawpy`

**Files:**
- Modify: `src/core/indexer.py`
- Test: `tests/test_raw_decoder.py`

**Interfaces:**
- Produces: `decode_raw(path: Path) -> np.ndarray`.
- Produces: `load_image(path: Path) -> np.ndarray` that handles both RAW and JPEG.

- [ ] **Step 1: Add rawpy import and fallback**

Modify `src/core/indexer.py`:

```python
import numpy as np
from PIL import Image

try:
    import rawpy
    RAWPY_AVAILABLE = True
except ImportError:
    RAWPY_AVAILABLE = False
    logging.warning("rawpy not installed; RAW decoding disabled")

def decode_raw(path: Path) -> np.ndarray:
    if not RAWPY_AVAILABLE:
        raise RuntimeError("rawpy is not installed")
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess()
    return rgb

def load_image(path: Path) -> np.ndarray:
    ext = path.suffix.lower()
    if ext in {".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"}:
        return decode_raw(path)
    return np.array(Image.open(path))
```

- [ ] **Step 2: Write test with mocked rawpy**

Create `tests/test_raw_decoder.py`:

```python
import numpy as np
from pathlib import Path
from PIL import Image
from src.core.indexer import load_image

def test_load_jpeg(tmp_path):
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    path = tmp_path / "test.jpg"
    Image.fromarray(img).save(path)
    arr = load_image(path)
    assert arr.shape == (100, 100, 3)
```

Run: `python -m pytest tests/test_raw_decoder.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/core/indexer.py tests/test_raw_decoder.py
git commit -m "功能: 添加 rawpy RAW 解码支持"
```

---

## Phase 3: Quality Assessment

### Task 3.1: Refactor `src/core/quality.py` to multi-dimensional scoring

**Files:**
- Modify: `src/core/quality.py`
- Test: `tests/test_quality.py` (rewrite)

**Interfaces:**
- Produces: `QualityScorer` class with `calculate_quality_score(image, bird_bbox, visibility, focus_points) -> int`.
- Produces: helper functions for each dimension.

- [ ] **Step 1: Implement dimension calculators**

Rewrite `src/core/quality.py`:

```python
import cv2
import numpy as np
from typing import Dict, List, Tuple

class QualityScorer:
    WEIGHTS = {
        "clarity": 0.25,
        "contrast": 0.10,
        "position": 0.10,
        "exposure": 0.10,
        "pose": 0.20,
        "bif": 0.10,
        "focus": 0.15,
    }

    def calculate_clarity(self, image: np.ndarray) -> float:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
        score = cv2.Laplacian(gray, cv2.CV_64F).var()
        return min(score / 500.0, 1.0)

    def calculate_contrast(self, image: np.ndarray) -> float:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
        return min(gray.std() / 80.0, 1.0)

    def calculate_position(self, image_shape: Tuple[int, ...], bird_bbox: Tuple[int, int, int, int]) -> float:
        h, w = image_shape[:2]
        x, y, bw, bh = bird_bbox
        cx, cy = x + bw / 2, y + bh / 2
        center_dist = ((cx - w / 2) ** 2 + (cy - h / 2) ** 2) ** 0.5
        max_dist = (w ** 2 + h ** 2) ** 0.5 / 2
        return max(0.0, 1.0 - center_dist / max_dist)

    def calculate_exposure(self, image: np.ndarray) -> float:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist = hist.flatten() / hist.sum()
        return 1.0 - float(np.sum(hist * np.abs(np.arange(256) - 127) / 127.0))

    def calculate_pose_score(self, visibility: Dict[str, float]) -> float:
        if not visibility:
            return 0.0
        return sum(visibility.values()) / len(visibility)

    def calculate_bif_score(self, visibility: Dict[str, float], flight_prob: float = 0.0) -> float:
        pose = self.calculate_pose_score(visibility)
        if flight_prob > 0.35:
            return min(pose + 0.2, 1.0)
        return pose

    def calculate_focus_score(self, focus_points: List[Tuple[int, int]], bird_bbox: Tuple[int, int, int, int]) -> float:
        if not focus_points:
            return 0.5
        x, y, bw, bh = bird_bbox
        inside = sum(1 for px, py in focus_points if x <= px <= x + bw and y <= py <= y + bh)
        return inside / len(focus_points)

    def calculate_quality_score(self, image: np.ndarray, bird_bbox: Tuple[int, int, int, int],
                                 visibility: Dict[str, float], focus_points: List[Tuple[int, int]]) -> int:
        clarity = self.calculate_clarity(image)
        contrast = self.calculate_contrast(image)
        position = self.calculate_position(image.shape, bird_bbox)
        exposure = self.calculate_exposure(image)
        pose = self.calculate_pose_score(visibility)
        bif = self.calculate_bif_score(visibility)
        focus = self.calculate_focus_score(focus_points, bird_bbox)
        score = (
            clarity * self.WEIGHTS["clarity"] +
            contrast * self.WEIGHTS["contrast"] +
            position * self.WEIGHTS["position"] +
            exposure * self.WEIGHTS["exposure"] +
            pose * self.WEIGHTS["pose"] +
            bif * self.WEIGHTS["bif"] +
            focus * self.WEIGHTS["focus"]
        )
        return int(score * 100)
```

- [ ] **Step 2: Rewrite tests**

Update `tests/test_quality.py`:

```python
import numpy as np
import pytest
from src.core.quality import QualityScorer

@pytest.fixture
def scorer():
    return QualityScorer()

@pytest.fixture
def sample_image():
    return np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)

def test_calculate_quality_score_returns_int(scorer, sample_image):
    score = scorer.calculate_quality_score(
        sample_image,
        bird_bbox=(25, 25, 50, 50),
        visibility={"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0},
        focus_points=[(50, 50)]
    )
    assert isinstance(score, int)
    assert 0 <= score <= 100
```

Run: `python -m pytest tests/test_quality.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/core/quality.py tests/test_quality.py
git commit -m "功能: 实现多维画质评估评分 (7 维加权)"
```

---

### Task 3.2: Add stub pose detection and AF focus parsing modules

**Files:**
- Create: `src/core/pose.py`
- Create: `src/core/focus.py`
- Test: `tests/test_pose.py`
- Test: `tests/test_focus.py`

**Interfaces:**
- `pose.py`: `detect_visibility(image, bird_bbox) -> Dict[str, float]` and `is_flying(image, bird_bbox) -> float`.
- `focus.py`: `parse_af_points(image_path: str) -> List[Tuple[int, int]]`.

- [ ] **Step 1: Create pose.py stub**

Create `src/core/pose.py`:

```python
from typing import Dict
import numpy as np

class PoseDetector:
    def detect_visibility(self, image: np.ndarray, bird_bbox: tuple) -> Dict[str, float]:
        # Stub: full visibility for MVP; ONNX model integration later
        return {"head": 1.0, "eye": 1.0, "body": 1.0, "tail": 1.0, "wing": 1.0}

    def is_flying(self, image: np.ndarray, bird_bbox: tuple) -> float:
        return 0.0
```

- [ ] **Step 2: Create focus.py stub**

Create `src/core/focus.py`:

```python
from typing import List, Tuple

class FocusParser:
    def parse_af_points(self, image_path: str) -> List[Tuple[int, int]]:
        # Stub: return center of image until EXIF AF parsing is implemented
        return []
```

- [ ] **Step 3: Write tests**

Create `tests/test_pose.py` and `tests/test_focus.py` with basic assertions.

Run: `python -m pytest tests/test_pose.py tests/test_focus.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/core/pose.py src/core/focus.py tests/test_pose.py tests/test_focus.py
git commit -m "功能: 添加姿态检测与 AF 对焦点解析模块 (初始桩)"
```

---

## Phase 4: Burst Grouping

### Task 4.1: Implement `src/core/grouper.py`

**Files:**
- Create: `src/core/grouper.py`
- Test: `tests/test_grouper.py`

**Interfaces:**
- `group_photos(photo_ids: List[int]) -> List[PhotoGroup]`.
- Consumes: `PhotoRepository` to fetch photos with `captured_at`.

- [ ] **Step 1: Implement grouping by time window**

Create `src/core/grouper.py`:

```python
from typing import List
from datetime import datetime, timedelta
from src.db.models import Photo, PhotoGroup
from src.db.repository import PhotoRepository

class PhotoGrouper:
    def __init__(self, repo: PhotoRepository, time_window: int = 5):
        self.repo = repo
        self.time_window = time_window

    def group_photos(self, photos: List[Photo]) -> List[PhotoGroup]:
        sorted_photos = sorted(photos, key=lambda p: p.captured_at or datetime.min)
        groups = []
        current_group = []
        for photo in sorted_photos:
            if not current_group:
                current_group = [photo]
            else:
                last = current_group[-1]
                if photo.captured_at and last.captured_at and \
                   (photo.captured_at - last.captured_at).total_seconds() <= self.time_window:
                    current_group.append(photo)
                else:
                    groups.append(current_group)
                    current_group = [photo]
        if current_group:
            groups.append(current_group)
        return groups
```

- [ ] **Step 2: Write tests**

Create `tests/test_grouper.py`:

```python
import pytest
from datetime import datetime, timedelta
from src.core.grouper import PhotoGrouper
from src.db.models import Photo

class FakeRepo:
    pass

def test_group_photos_by_time():
    grouper = PhotoGrouper(FakeRepo(), time_window=5)
    base = datetime(2026, 7, 20, 10, 0, 0)
    photos = [
        Photo(file_path=f"p{i}.jpg", filename=f"p{i}.jpg", captured_at=base + timedelta(seconds=i))
        for i in [0, 1, 2, 10, 11]
    ]
    groups = grouper.group_photos(photos)
    assert len(groups) == 2
    assert len(groups[0]) == 3
    assert len(groups[1]) == 2
```

Run: `python -m pytest tests/test_grouper.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/core/grouper.py tests/test_grouper.py
git commit -m "功能: 实现基于时间窗口的连拍分组"
```

---

## Phase 5: Web UI (3-Domain Workflow)

### Task 5.1: Add FastAPI routers for `/select`, `/gallery`, `/guide`

**Files:**
- Create: `src/web/routers/select.py`
- Create: `src/web/routers/gallery.py`
- Create: `src/web/routers/guide.py`
- Modify: `src/web/app.py` to include routers
- Test: `tests/test_web_routers.py`

**Interfaces:**
- `select.py`: GET `/select`, POST `/api/select/best`.
- `gallery.py`: GET `/gallery`, GET `/api/photos`.
- `guide.py`: GET `/guide`, GET `/api/guide/species`.

- [ ] **Step 1: Create stub routers**

Create `src/web/routers/select.py`:

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/select", response_class=HTMLResponse)
def select_page(request: Request):
    return "<html><body>Select Workbench</body></html>"
```

Similarly create `gallery.py` and `guide.py`.

- [ ] **Step 2: Register routers in app.py**

Modify `src/web/app.py`:

```python
from src.web.routers.select import router as select_router
from src.web.routers.gallery import router as gallery_router
from src.web.routers.guide import router as guide_router

app.include_router(select_router)
app.include_router(gallery_router)
app.include_router(guide_router)
```

- [ ] **Step 3: Write tests**

Create `tests/test_web_routers.py`:

```python
from fastapi.testclient import TestClient
from src.web.app import app

def test_select_page():
    client = TestClient(app)
    resp = client.get("/select")
    assert resp.status_code == 200
    assert "Select" in resp.text
```

Run: `python -m pytest tests/test_web_routers.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/web/routers/ tests/test_web_routers.py src/web/app.py
git commit -m "功能: 添加选片/图库/图鉴路由骨架"
```

---

### Task 5.2: Create Jinja2 templates for the three domains

**Files:**
- Create: `src/web/templates/select.html`
- Create: `src/web/templates/gallery.html`
- Create: `src/web/templates/guide.html`
- Modify: `src/web/routers/*.py` to use templates

**Interfaces:**
- Produces: HTML pages with Ant Design CDN components.

- [ ] **Step 1: Create minimal templates with Ant Design**

Create `src/web/templates/select.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>选片工作台</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="p-4">
    <h1 class="text-2xl font-bold">选片工作台</h1>
    <p>连拍分组 → 组内复核 → 质量评分 → 确认选中</p>
</body>
</html>
```

Create similar `gallery.html` and `guide.html`.

- [ ] **Step 2: Update routers to render templates**

Modify `src/web/routers/select.py` to use Jinja2Templates:

```python
from fastapi.templating import Jinja2Templates
from pathlib import Path

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/select", response_class=HTMLResponse)
def select_page(request: Request):
    return templates.TemplateResponse("select.html", {"request": request})
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_web_routers.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/ src/web/routers/
git commit -m "UI: 添加选片/图库/图鉴基础模板"
```

---

## Phase 6: Metadata Writing (XMP Sidecar for RAW)

### Task 6.1: Update `src/metadata/exif_writer.py` to support XMP sidecar

**Files:**
- Modify: `src/metadata/exif_writer.py`
- Test: `tests/test_exif_writer.py` (update)

**Interfaces:**
- `write_metadata(image_path, tags, write_mode="xmp_sidecar") -> bool`.
- For RAW: write `.xmp` sidecar; for JPEG: direct EXIF.

- [ ] **Step 1: Add sidecar logic**

Modify `src/metadata/exif_writer.py`:

```python
from pathlib import Path
import xml.etree.ElementTree as ET

RAW_EXTS = {".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"}

class ExifWriter:
    def write_metadata(self, image_path: str, tags: dict, write_mode: str = "xmp_sidecar") -> bool:
        path = Path(image_path)
        if write_mode == "xmp_sidecar" and path.suffix.lower() in RAW_EXTS:
            return self._write_xmp_sidecar(path, tags)
        return self._write_exif(image_path, tags)

    def _write_exif(self, image_path: str, tags: dict) -> bool:
        # existing exiftool logic
        return True

    def _write_xmp_sidecar(self, path: Path, tags: dict) -> bool:
        xmp_path = path.with_suffix(path.suffix + ".xmp")
        # Build minimal XMP sidecar
        root = ET.Element("xmpmeta")
        rdf = ET.SubElement(root, "RDF")
        desc = ET.SubElement(rdf, "Description")
        for key, value in tags.items():
            ET.SubElement(desc, key.replace(":", "_")).text = str(value)
        tree = ET.ElementTree(root)
        tree.write(xmp_path, encoding="utf-8", xml_declaration=True)
        return True
```

- [ ] **Step 2: Update tests**

Update `tests/test_exif_writer.py` to cover sidecar creation.

Run: `python -m pytest tests/test_exif_writer.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/metadata/exif_writer.py tests/test_exif_writer.py
git commit -m "功能: 支持 RAW 文件 XMP sidecar 元数据写入"
```

---

## Phase 7: Integration, Testing & Verification

### Task 7.1: Wire new modules into pipeline entry point

**Files:**
- Modify: `src/pipeline_runner.py` or create `src/cli/main.py`
- Test: `tests/test_full_pipeline.py` (update)

**Interfaces:**
- CLI command: `python -m src.cli.main index --folder D:/Photos/Birds`.
- Or reuse `python src/pipeline_runner.py`.

- [ ] **Step 1: Create CLI entry point (optional)**

Create `src/cli/main.py`:

```python
import argparse
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base
from src.db.repository import PhotoRepository
from src.core.indexer import PhotoIndexer

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["index"])
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()

    engine = create_engine("sqlite:///data/birder.db")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    repo = PhotoRepository(session)

    if args.command == "index":
        indexer = PhotoIndexer(repo)
        photos = indexer.index_folder(Path(args.folder))
        print(f"Indexed {len(photos)} photos")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/test_full_pipeline.py -v`
Expected: Adjust tests to use new SQLAlchemy layer; PASS.

- [ ] **Step 3: Commit**

```bash
git add src/cli/main.py tests/test_full_pipeline.py
git commit -m "工具: 添加 CLI 入口与集成测试"
```

---

### Task 7.2: Final verification

**Files:**
- All modified files.
- Test: `python -m pytest`

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest`
Expected: All tests pass (with reasonable coverage for new modules).

- [ ] **Step 2: Check code style**

Run: `python -m py_compile src/**/*.py` (or project lint command)
Expected: No syntax errors.

- [ ] **Step 3: Review diff**

Run: `git diff --stat`
Expected: Changes match plan scope.

- [ ] **Step 4: Commit final state**

```bash
git commit -m "验证: 全量测试通过，dev-newspec 第一阶段实现完成"
```

---

## Spec Coverage Check

| Spec Section | Covered By |
|--------------|------------|
| 2.1 `src/db/models.py`, `src/db/repository.py` | Task 1.1, 1.2 |
| 2.1 `src/core/indexer.py` | Task 2.1, 2.2 |
| 3.2 `quality.py` multi-dimensional | Task 3.1 |
| 3.2 `pose.py`, `focus.py` | Task 3.2 |
| 3.3 `grouper.py` | Task 4.1 |
| 3.5 metadata XMP sidecar | Task 6.1 |
| 4.1 `/select`, `/gallery`, `/guide` | Task 5.1, 5.2 |
| 8 config `settings.yaml` | Task 1.3 |
| 9 testing | All tasks |

**Gaps:**
- ONNX pose model integration is stubbed; requires actual model files.
- Real AF point EXIF parsing requires camera-specific maker notes.
- Ant Design templates are minimal; full UI polish is later.
- 图鉴地图分布需要地图库/Geo 数据，未在本计划内实现。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-20-dev-newspec-implementation.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — 每个 task 派一个独立 subagent，执行 + 两阶段 review（spec 符合性 + 代码质量），迭代快。
2. **Inline Execution** — 在本会话中用 `superpowers:executing-plans` 按 task 顺序执行，带检查点。

**Which approach?**

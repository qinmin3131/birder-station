# 选片复核质量分、鸟种修正、连拍组最佳高亮实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复选片详情窗口质量评分展示、鸟种修正只能选自 IOC 名录并展示识别候选 Top 5、连拍组最高质量照片高亮。

**Architecture:** 在 `/api/photo/{photo_id}/review` 中补齐质量分兜底与重算；在 `correct-species` 后端校验 IOC 名录；在 `select.html`/`gallery.html` 中增强质量分渲染、鸟种修正候选交互、连拍组最佳高亮。

**Tech Stack:** Python 3.11+、FastAPI、Jinja2、Bootstrap 5、SQLAlchemy、pytest。

## Global Constraints

- Python 3.11+，PEP 8 命名，`snake_case` 函数/变量，4 空格缩进。
- 修改必须保持现有测试通过，并新增/更新对应测试。
- 前端改动限制在 `src/web/templates/select.html` 与 `src/web/templates/gallery.html`。
- 后端改动限制在 `src/web/app.py` 的相关接口。
- 所有候选/名录搜索必须基于 `taxonomy` 表（IOC 鸟类名录）。

---

### Task 1: 后端 Review 接口补齐质量分兜底与重算

**Files:**
- Modify: `src/web/app.py:1040-1060`
- Test: `tests/test_web_review.py`

**Interfaces:**
- Consumes: `Photo.quality_score`, `Photo.quality_details`, `Photo.bird_bbox`, `Photo.original_path`
- Produces: `quality_score` (int 0-100), `quality_details` (dict[str, float] 0-1)

- [ ] **Step 1: 编写失败测试**

在 `tests/test_web_review.py` 末尾新增：

```python
def test_review_falls_back_to_zero_when_quality_data_missing(client, sample_jpg, monkeypatch):
    """当照片没有 quality_score/quality_details 且无 bbox 时，应返回 0 和全 0 分项。"""
    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(
        session,
        original_path=str(sample_jpg),
        quality_score=None,
        quality_details=None,
        bird_bbox=None,
    )
    photo_id = photo.id
    session.close()

    response = client.get(f"/api/photo/{photo_id}/review")
    assert response.status_code == 200
    data = response.json()
    assert data["photo"]["quality_score"] == 0
    assert data["quality_details"] == {
        "clarity": 0.0,
        "contrast": 0.0,
        "exposure": 0.0,
        "subject_size": 0.0,
        "iso": 0.0,
    }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_review.py::test_review_falls_back_to_zero_when_quality_data_missing -v`
Expected: FAIL (`AssertionError` 因为 `quality_score` 是 `None` 或 `quality_details` 为空)

- [ ] **Step 3: 修改后端兜底逻辑**

替换 `src/web/app.py` 中 `get_photo_review` 的质量分处理块（约 1040-1060 行）为：

```python
        quality_score: Optional[int] = photo.quality_score
        quality_details: Dict[str, Any] = {}
        if photo.quality_details:
            try:
                quality_details = json.loads(photo.quality_details) if isinstance(photo.quality_details, str) else photo.quality_details
            except Exception:
                pass

        # Always attempt to recompute with the latest scorer if bbox is available.
        if photo.bird_bbox and original_path and Path(original_path).exists():
            try:
                bbox = photo.bird_bbox
                if isinstance(bbox, str):
                    bbox = json.loads(bbox)
                if len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
                    iso = read_iso(exif_writer, original_path)
                    recomputed = QualityScorer().score_from_path(original_path, bbox, iso=iso)
                    quality_score = recomputed["score"]
                    quality_details = recomputed["details"]
            except Exception as e:
                logger.debug(f"Recompute quality score for review failed: {e}")

        # Fallbacks: ensure frontend always has a score and details to render.
        if quality_score is None:
            quality_score = 0
        if not quality_details:
            quality_details = {dim: 0.0 for dim in QualityScorer.DEFAULT_WEIGHTS}

        # Normalize details to 0-1 scale (older data may be stored as 0-100).
        normalized_details: Dict[str, float] = {}
        for dim in QualityScorer.DEFAULT_WEIGHTS:
            v = quality_details.get(dim, 0.0)
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = 0.0
            if v > 1.0:
                v = v / 100.0
            normalized_details[dim] = min(max(v, 0.0), 1.0)
        quality_details = normalized_details
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web_review.py::test_review_falls_back_to_zero_when_quality_data_missing -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/web/app.py tests/test_web_review.py
git commit -m "修复: review 接口质量分兜底与 0-1 归一化"
```

---

### Task 2: 前端详情弹窗增强质量分展示

**Files:**
- Modify: `src/web/templates/select.html:202-207`, `src/web/templates/select.html:491-517`
- Modify: `src/web/templates/gallery.html:249-250`, `src/web/templates/gallery.html:407-427`
- Test: 手动验证（模板变更以 UI 测试为主）

**Interfaces:**
- Consumes: `photo.quality_score`, `data.quality_details` (0-1)
- Produces: 渲染后的 DOM

- [ ] **Step 1: 修改 select.html 质量总分 HTML**

将约 202-204 行：

```html
                                <p class="mb-1">
                                    <span class="text-white-50">质量总分：</span>
                                    <span id="reviewQualityScore">--</span>
                                </p>
```

替换为：

```html
                                <p class="mb-1 d-flex align-items-center gap-2">
                                    <span class="text-white-50">质量总分：</span>
                                    <span id="reviewQualityScore" class="badge">--</span>
                                </p>
                                <div class="progress mb-2" style="height: 8px;">
                                    <div id="reviewQualityScoreBar" class="progress-bar" role="progressbar" style="width: 0%;"></div>
                                </div>
```

- [ ] **Step 2: 修改 select.html 质量总分渲染 JS**

在约 491 行附近，把：

```js
            document.getElementById('reviewQualityScore').textContent = photo.quality_score || '--';
```

替换为：

```js
            const qScore = photo.quality_score ?? '--';
            document.getElementById('reviewQualityScore').textContent = qScore;
            const qScoreBar = document.getElementById('reviewQualityScoreBar');
            const qScoreNum = photo.quality_score ?? 0;
            qScoreBar.style.width = `${qScoreNum}%`;
            qScoreBar.className = `progress-bar ${qScoreNum >= 80 ? 'bg-success' : qScoreNum >= 60 ? 'bg-warning' : 'bg-danger'}`;
            const qScoreBadge = document.getElementById('reviewQualityScore');
            qScoreBadge.className = `badge ${qScoreNum >= 80 ? 'bg-success' : qScoreNum >= 60 ? 'bg-warning' : 'bg-danger'}`;
```

- [ ] **Step 3: 修改 select.html 质量分项渲染 JS**

在约 496-517 行附近，把分项渲染块改为显示数值：

```js
            const qd = data.quality_details || {};
            const qdContainer = document.getElementById('reviewQualityDetails');
            qdContainer.innerHTML = '';
            const qdNames = {clarity: '清晰度', contrast: '对比度', exposure: '曝光', subject_size: '主体占比', iso: 'ISO/噪点'};
            Object.keys(qdNames).forEach(key => {
                if (key in qd) {
                    const score = qd[key];
                    const pct = Math.max(0, Math.min(100, score * 100));
                    const div = document.createElement('div');
                    div.className = 'mb-2';
                    div.innerHTML = `
                        <div class="d-flex justify-content-between small">
                            <span>${qdNames[key]}</span>
                            <span>${pct.toFixed(1)}</span>
                        </div>
                        <div class="progress" style="height: 6px;">
                            <div class="progress-bar ${pct >= 80 ? 'bg-success' : pct >= 60 ? 'bg-warning' : 'bg-danger'}" role="progressbar" style="width: ${pct}%"></div>
                        </div>
                    `;
                    qdContainer.appendChild(div);
                }
            });
```

- [ ] **Step 4: 对 gallery.html 做相同修改**

在 `gallery.html`：
- 249-250 行总分 HTML 替换为与 select.html 相同结构（id 改为 `photoDetailQualityScore` / `photoDetailQualityScoreBar`）。
- 370 行 `document.getElementById('photoDetailQualityScore').textContent = photo.quality_score || '--';` 替换为与 select.html 相同的总分渲染逻辑。
- 410-427 行质量分项渲染替换为与 select.html 相同逻辑。

- [ ] **Step 5: 运行相关测试**

Run: `python -m pytest tests/test_web_review.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add src/web/templates/select.html src/web/templates/gallery.html
git commit -m "修复: 详情弹窗质量总分与分项展示"
```

---

### Task 3: 后端鸟种修正校验 IOC 名录

**Files:**
- Modify: `src/web/app.py:1291-1365`
- Test: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `CorrectSpeciesRequest.scientific_name`
- Produces: HTTP 400 if not in checklist, 200 on success

- [ ] **Step 1: 编写失败测试**

在 `tests/test_web_app.py` 中新增（需要 IOCManager 里有测试用物种）：

```python
def test_correct_species_rejects_not_in_checklist(client, tmp_path, monkeypatch):
    """修正鸟种时，若物种不在 IOC 名录应拒绝。"""
    import sqlite3
    from src.db.models import Base, Photo
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient

    db_path = tmp_path / "test_correct.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    # Seed taxonomy with a known species directly into the IOC checklist
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO taxonomy (scientific_name, chinese_name, family_cn, order_cn, genus_cn, family_sci, order_sci, genus_sci, english_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Passer montanus", "麻雀", "雀科", "雀形目", "麻雀属", "Passeridae", "Passeriformes", "Passer", "Eurasian Tree Sparrow")
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(web_app, "db_path", db_path)
    monkeypatch.setattr(web_app, "source_dir", tmp_path)
    monkeypatch.setattr(web_app, "processed_dir", tmp_path)
    monkeypatch.setattr(web_app, "config", {"paths": {"source_dir": str(tmp_path)}})
    def _get_session():
        return SessionLocal()
    monkeypatch.setattr(web_app, "get_sqlalchemy_session", _get_session)

    session = _get_session()
    photo = Photo(
        file_path="bird.jpg",
        filename="bird.jpg",
        original_path=None,
        primary_bird_cn="未知",
        scientific_name="Unknown",
        confidence_score=0.5,
    )
    session.add(photo)
    session.commit()
    photo_id = photo.id
    session.close()

    with TestClient(web_app.app) as c:
        response = c.post(f"/api/photo/{photo_id}/correct-species", json={
            "scientific_name": "Not In Checklist",
            "chinese_name": "",
            "write_metadata": False,
        })
    assert response.status_code == 400
    assert "not found in IOC checklist" in response.json()["detail"].lower()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_app.py::test_correct_species_rejects_not_in_checklist -v`
Expected: FAIL（当前后端不会拒绝不在名录的物种，且内部导入路径也有 bug）

- [ ] **Step 3: 修改后端校验逻辑并修复现有导入 bug**

在 `src/web/app.py` 的 `correct_photo_species` 中，约 1308-1314 行：

```python
        # Look up taxonomy for Chinese name and family if not provided
        from src.metadata.ioc_manager import create_db_manager
        try:
            manager = create_db_manager()
            bird_info = manager.get_bird_info(new_name)
        finally:
            manager.close()
```

替换为：

```python
        # Validate species exists in IOC checklist and fetch Chinese name
        try:
            manager = create_db_manager()
            bird_info = manager.get_bird_info(new_name)
        finally:
            manager.close()

        if not bird_info:
            raise HTTPException(status_code=400, detail=f"Species {new_name} not found in IOC checklist")
```

同时把这段 `bird_info` 查询提前到 `new_name` 校验之后、无变化检查之前（约 1301-1308 行）：

```python
        new_name = request.scientific_name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Scientific name is required")

        # Validate species exists in IOC checklist and fetch Chinese name
        try:
            manager = create_db_manager()
            bird_info = manager.get_bird_info(new_name)
        finally:
            manager.close()

        if not bird_info:
            raise HTTPException(status_code=400, detail=f"Species {new_name} not found in IOC checklist")

        old_name = photo.scientific_name
        if old_name == new_name:
            return {"status": "success", "message": "No change", "photo_id": photo_id}

        new_cn = (request.chinese_name or bird_info.get('chinese_name', '') or new_name).strip()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_web_app.py::test_correct_species_rejects_not_in_checklist -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/web/app.py tests/test_web_app.py
git commit -m "修复: 鸟种修正限制只能选 IOC 名录"
```

---

### Task 4: 前端鸟种修正展示识别候选 Top 5 并限制选择

**Files:**
- Modify: `src/web/templates/select.html:212-219`, `src/web/templates/select.html:680-738`
- Test: 手动验证

**Interfaces:**
- Consumes: `data.candidates`, `/api/search-species` results
- Produces: 候选列表 DOM 与确认校验

- [ ] **Step 1: 修改候选列表容器 HTML**

将约 212-219 行：

```html
                                <div class="input-group input-group-sm mb-2">
                                    <input type="text" class="form-control form-control-sm bg-dark text-white border-secondary" id="reviewSpeciesInput"
                                           placeholder="输入中文名或学名" autocomplete="off"
                                           oninput="searchReviewSpecies(this.value)">
                                    <button class="btn btn-outline-secondary" type="button" onclick="confirmReviewSpecies()">确认</button>
                                </div>
                                <div class="list-group list-group-flush small bg-dark border-secondary" id="reviewSpeciesCandidates" style="max-height: 120px; overflow-y: auto;"></div>
```

保持不变，仅确保 `oninput` 调用 `searchReviewSpecies(this.value)`。

- [ ] **Step 2: 重构 searchReviewSpecies / 新增 render helper**

将约 680-738 行的 `searchReviewSpecies` 和 `confirmReviewSpecies` 区域替换为：

```js
        let reviewSpeciesMatches = [];
        let selectedReviewSpecies = null;

        function renderReviewSpeciesMatches() {
            const list = document.getElementById('reviewSpeciesCandidates');
            list.innerHTML = '';
            reviewSpeciesMatches.forEach((s) => {
                const sci = s.scientific_name || s.sci || '';
                const cn = s.chinese_name || s.cn || '';
                const display = cn ? `${cn} (${sci})` : sci;
                const item = document.createElement('button');
                item.className = 'list-group-item list-group-item-action list-group-item-dark text-white-50 small py-1';
                item.type = 'button';
                item.textContent = display;
                item.onclick = () => {
                    selectedReviewSpecies = s;
                    document.getElementById('reviewSpeciesInput').value = cn || sci;
                    list.innerHTML = '';
                };
                list.appendChild(item);
            });
        }

        function searchReviewSpecies(query) {
            const list = document.getElementById('reviewSpeciesCandidates');
            list.innerHTML = '';
            reviewSpeciesMatches = [];
            selectedReviewSpecies = null;

            // Empty input: show top 5 recognition candidates
            if (!query || query.trim().length < 2) {
                if (currentReviewData && currentReviewData.candidates) {
                    reviewSpeciesMatches = currentReviewData.candidates.slice(0, 5).map(c => ({
                        scientific_name: c.scientific_name || c.sci || '',
                        chinese_name: c.chinese_name || c.cn || '',
                    }));
                    renderReviewSpeciesMatches();
                }
                return;
            }

            fetch(`/api/search-species?q=${encodeURIComponent(query)}`)
                .then(r => r.json())
                .then(data => {
                    reviewSpeciesMatches = data.results || [];
                    renderReviewSpeciesMatches();
                })
                .catch(e => console.error(e));
        }

        function confirmReviewSpecies() {
            if (!selectedReviewSpecies) {
                alert('请从候选列表中选择鸟种');
                return;
            }
            if (!currentReviewPhotoId) return;
            const sci = selectedReviewSpecies.scientific_name || selectedReviewSpecies.sci || '';
            const cn = selectedReviewSpecies.chinese_name || selectedReviewSpecies.cn || '';
            fetch(`/api/photo/${currentReviewPhotoId}/correct-species`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    scientific_name: sci,
                    chinese_name: cn,
                    write_metadata: true
                })
            })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'success') {
                        document.getElementById('reviewBirdName').textContent = cn || sci;
                        document.getElementById('reviewSciName').textContent = sci;
                        document.getElementById('reviewSpeciesInput').value = '';
                        document.getElementById('reviewSpeciesCandidates').innerHTML = '';
                        selectedReviewSpecies = null;
                        alert('鸟种已修正');
                    } else {
                        throw new Error(data.detail || 'unknown error');
                    }
                })
                .catch(e => {
                    console.error(e);
                    alert('修正失败：' + (e.message || '未知错误'));
                });
        }
```

- [ ] **Step 3: 在打开复核时预填候选**

在 `renderReview(data)` 函数末尾、绘制 canvas 之前，调用：

```js
            // Pre-fill species candidates when opening review
            searchReviewSpecies('');
```

- [ ] **Step 4: 运行后端测试**

Run: `python -m pytest tests/test_web_app.py -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add src/web/templates/select.html
git commit -m "修复: 鸟种修正空输入展示识别候选 Top5 并限制选择"
```

---

### Task 5: 连拍组最高质量照片高亮

**Files:**
- Modify: `src/web/templates/select.html:18-22`（CSS）, `src/web/templates/select.html:124`（卡片 class）
- Test: 手动验证

**Interfaces:**
- Consumes: `group.best_photo_id`, `photo.id`
- Produces: 高亮卡片 DOM

- [ ] **Step 1: 添加最佳卡片 CSS**

在 `select.html` 的 `<style>` 中约 18-22 行之后添加：

```css
        .best-photo-card { border: 3px solid #ffc107; position: relative; }
        .best-photo-card::after {
            content: '最佳';
            position: absolute;
            top: 4px;
            right: 4px;
            background: #ffc107;
            color: #000;
            font-size: 12px;
            padding: 2px 6px;
            border-radius: 4px;
            z-index: 5;
            font-weight: bold;
        }
```

- [ ] **Step 2: 给最佳照片卡片加 class**

将约 124-126 行：

```html
                <div class="card h-100 shadow-sm {{ 'selected-card' if photo.is_selected else '' }} {{ 'rejected-card' if photo.is_rejected else '' }}"
                     data-id="{{ photo.id }}"
                     data-score="{{ photo.quality_score|default(0) }}">
```

替换为：

```html
                <div class="card h-100 shadow-sm {{ 'selected-card' if photo.is_selected else '' }} {{ 'rejected-card' if photo.is_rejected else '' }} {{ 'best-photo-card' if group.best_photo_id == photo.id else '' }}"
                     data-id="{{ photo.id }}"
                     data-score="{{ photo.quality_score|default(0) }}">
```

- [ ] **Step 3: 运行后端测试**

Run: `python -m pytest tests/test_web_app.py tests/test_web_review.py -v`
Expected: 全部通过

- [ ] **Step 4: 提交**

```bash
git add src/web/templates/select.html
git commit -m "修复: 连拍组最高质量照片高亮"
```

---

### Task 6: 全量测试与手动验证

**Files:**
- All modified files

- [ ] **Step 1: 运行全量测试**

Run: `python -m pytest -v`
Expected: 全部通过（若已有失败需先确认非本次引入）

- [ ] **Step 2: 手动验证选片页面**

Run: `python src/web/app.py`
然后：
1. 打开 `http://localhost:8000/select`
2. 点击任意照片打开复核弹窗
3. 确认：质量总分显示数字 + 彩色进度条；质量分项显示名称 + 数值 + 进度条
4. 清空鸟种修正输入框，确认展示识别候选 Top 5
5. 点击一个候选并确认，确认只能修改成功（后端校验 IOC 名录）
6. 在连拍组中，确认分数最高卡片有金色边框和「最佳」标签

- [ ] **Step 3: 提交最终验证**

```bash
git add -A
git commit -m "测试: 验证选片复核修复"
```

---

## Self-Review Checklist

- [ ] Spec coverage：每个问题（质量分展示、鸟种修正、连拍组高亮）都对应 Task 1-5。
- [ ] Placeholder scan：无 TBD/TODO，无模糊描述，每个步骤含代码/命令。
- [ ] Type consistency：`quality_score` 为 int 0-100，`quality_details` 为 dict[str, float 0-1]，候选结构统一使用 `scientific_name`/`chinese_name` 并回退 `sci`/`cn`。
- [ ] 测试覆盖：新增后端测试 2 个，前端以手动验证为主，全量测试兜底。

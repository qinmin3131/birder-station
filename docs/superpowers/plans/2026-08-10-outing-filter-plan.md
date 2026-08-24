# 外拍全局筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在导航栏增加全局外拍选择器，使选片、图库、图鉴三个页面都能按“默认 / 全部 / 单次外拍”筛选，并保留查看全量数据的能力。

**Architecture:** 通过 URL 参数 `outing_id`（空/缺失=默认，`all`=全部，数字=指定外拍）传递选择；后端新增统一解析 helper；前端导航栏用 JS 调用 `/api/outings` 填充下拉框并维护当前选择；各页面模板根据后端传入的 `outing_id` 和 `current_outing` 显示范围并保留参数。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Jinja2, Bootstrap 5, vanilla JS

## Global Constraints

- Python 3.11+ with 4-space indentation and PEP 8 naming (`snake_case` functions, `PascalCase` classes).
- Keep modules focused by domain (`src/web/app.py` for routes, `src/web/templates/*.html` for UI).
- Use type hints for public/helper functions.
- Add/adjust tests for every behavior change (`pytest`, `tests/test_web_three_domain.py`, `tests/test_web_app.py`).
- Preserve existing date / rating / species / location / view filters.
- Old numeric `outing_id` query parameters must remain compatible.

---

## Task 1: Add outing resolution helper and `/api/outings` endpoint

**Files:**
- Modify: `src/web/app.py:746-748` (after `_apply_rating_filter`)
- Modify: `src/web/app.py` near other API endpoints (add `/api/outings`)
- Test: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `Outing` model, `get_sqlalchemy_session()`
- Produces: `_resolve_outing_scope(session, outing_id, default) -> tuple[str, Optional[Outing]]`, `GET /api/outings`

- [ ] **Step 1: Write the failing test**

Update `tests/test_web_app.py` imports to include `Outing`:

```python
from src.db.models import Base, Photo, Outing
```

Then add the test:

```python
# tests/test_web_app.py

def test_api_outings_returns_sorted_list(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    from datetime import datetime, timedelta
    o1 = Outing(name="旧外拍", start_date="20260710", created_at=datetime.utcnow() - timedelta(days=1))
    o2 = Outing(name="新外拍", start_date="20260720", created_at=datetime.utcnow())
    session.add(o1)
    session.add(o2)
    session.commit()
    session.close()
    monkeypatch.setattr(web_app, "db_path", db_path)

    with TestClient(web_app.app) as client:
        resp = client.get("/api/outings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert [o["id"] for o in data["outings"]] == [o2.id, o1.id]
    assert data["outings"][0]["name"] == "新外拍"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_web_app.py::test_api_outings_returns_sorted_list -v
```

Expected: FAIL with `404: Not Found` (endpoint does not exist).

- [ ] **Step 3: Add helper and endpoint**

In `src/web/app.py`, add the helper immediately after `_apply_rating_filter` (around line 746):

```python
def _resolve_outing_scope(
    session,
    outing_id: Any,
    default: str,
) -> tuple[str, Optional[Outing]]:
    """Resolve the active outing scope for a page.

    Args:
        session: SQLAlchemy session.
        outing_id: Raw outing_id from URL (str/int). Empty/None means page default.
        default: Page default when outing_id is empty - "latest" or "all".

    Returns:
        (scope, current_outing):
        - scope: "default" | "all" | "outing"
        - current_outing: the active Outing object, or None for all/default-all.
    """
    raw = str(outing_id).strip() if outing_id is not None else ""
    if raw == "all":
        return "all", None
    if raw:
        try:
            oid = int(raw)
            outing = session.query(Outing).filter(Outing.id == oid).first()
            if outing:
                return "outing", outing
        except ValueError:
            pass
    if default == "latest":
        outing = session.query(Outing).order_by(Outing.created_at.desc()).first()
        return ("outing", outing) if outing else ("all", None)
    return "all", None
```

Add the endpoint near the existing log API endpoints (e.g., after `api_birding_log_years` around line 1856):

```python
@app.get("/api/outings")
def api_outings():
    """返回所有外拍列表，按开始日期倒序，供导航栏选择器使用。"""
    session = get_sqlalchemy_session()
    try:
        outings = session.query(Outing).order_by(Outing.start_date.desc(), Outing.created_at.desc()).all()
        return {
            "status": "success",
            "outings": [
                {
                    "id": o.id,
                    "name": o.name,
                    "start_date": o.start_date or "",
                    "end_date": o.end_date or "",
                }
                for o in outings
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch outings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_web_app.py::test_api_outings_returns_sorted_list -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py tests/test_web_app.py
git commit -m "feat: add outing scope helper and /api/outings endpoint"
```

---

## Task 2: Update `/select` route and template

**Files:**
- Modify: `src/web/app.py:748-865` (`select_page` route)
- Modify: `src/web/templates/select.html:60-106` (filter bar and links)
- Test: `tests/test_web_three_domain.py`

**Interfaces:**
- Consumes: `_resolve_outing_scope`, `outing_id` as `str`
- Produces: `select_page` accepts `outing_id: str = ""`, context includes `outing_id` string and `current_outing`

- [ ] **Step 1: Write/update failing tests**

Replace the existing `test_select_page_renders_template` and add new tests in `tests/test_web_three_domain.py`:

```python
def test_select_page_renders_template(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = web_app.select_page(request=object(), date="", outing_id="", rating="")

    assert result == {
        "template": "select.html",
        "context": {
            "request": ANY,
            "groups": [],
            "current_date": "",
            "current_rating": "",
            "current_outing": None,
            "outing_id": "",
        },
    }


def test_select_page_defaults_to_latest_outing(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    from datetime import datetime, timedelta
    old = Outing(name="旧外拍", start_date="20260710", created_at=datetime.utcnow() - timedelta(days=1))
    new = Outing(name="新外拍", start_date="20260720", created_at=datetime.utcnow())
    session.add(old)
    session.add(new)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", outing_id=old.id, quality_score=60))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", outing_id=new.id, quality_score=70))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.select_page(request=object(), date="", outing_id="", rating="")
    context = templates.calls[0]["context"]
    assert context["current_outing"].id == new.id
    assert context["outing_id"] == ""
    assert len(context["groups"]) == 1
    assert context["groups"][0]["photo_count"] == 1
    assert context["groups"][0]["primary_bird_cn"] is None  # no recognition, just raw photo


def test_select_page_all_outings_shows_all_photos(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="外拍1", start_date="20260710")
    o2 = Outing(name="外拍2", start_date="20260720")
    session.add(o1)
    session.add(o2)
    session.commit()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", outing_id=o1.id, quality_score=60))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", outing_id=o2.id, quality_score=70))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.select_page(request=object(), date="", outing_id="all", rating="")
    context = templates.calls[0]["context"]
    assert context["current_outing"] is None
    assert context["outing_id"] == "all"
    assert len(context["groups"]) == 2


def test_select_page_specific_outing_filters_photos(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="外拍1", start_date="20260710")
    o2 = Outing(name="外拍2", start_date="20260720")
    session.add(o1)
    session.add(o2)
    session.commit()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", outing_id=o1.id, quality_score=60))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", outing_id=o2.id, quality_score=70))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.select_page(request=object(), date="", outing_id=str(o1.id), rating="")
    context = templates.calls[0]["context"]
    assert context["current_outing"].id == o1.id
    assert context["outing_id"] == str(o1.id)
    assert len(context["groups"]) == 1
```

Also update all existing `web_app.select_page(...)` direct calls in `tests/test_web_three_domain.py` to pass `outing_id=""` instead of `outing_id=0`.

- [ ] **Step 2: Run updated tests to verify they fail**

```bash
python -m pytest tests/test_web_three_domain.py -k select -v
```

Expected: FAIL due to signature/behavior mismatch.

- [ ] **Step 3: Update `/select` route**

In `src/web/app.py`, change the `select_page` signature and opening logic:

```python
@app.get("/select", response_class=HTMLResponse)
def select_page(request: Request, date: str = "", outing_id: str = "", rating: str = ""):
    """选片工作台：默认展示最近一次外拍的照片，按连拍分组优先展示。支持等级筛选。"""
    session = get_sqlalchemy_session()
    try:
        # Normalize and resolve the active outing scope
        outing_id = str(outing_id) if outing_id is not None else ""
        current_outing_scope, current_outing = _resolve_outing_scope(
            session, outing_id, default="latest"
        )

        query = session.query(Photo)
        if current_outing:
            query = query.filter(Photo.outing_id == current_outing.id)
        if date:
            query = query.filter(Photo.captured_date == date)
        if rating:
            query = _apply_rating_filter(query, rating)
        photos = query.order_by(Photo.captured_date.desc(), Photo.id.desc()).limit(500).all()
```

Keep the rest of the function unchanged except the final context:

```python
        return templates.TemplateResponse(
            request, "select.html",
            {
                "request": request,
                "groups": display_groups,
                "current_date": date,
                "current_rating": rating,
                "current_outing": current_outing,
                "outing_id": outing_id,
            },
        )
```

- [ ] **Step 4: Update `select.html` template**

In `src/web/templates/select.html`, around the date search form (line 70), add a hidden `outing_id` input and an explicit current scope label:

```html
                <div>
                    <h5 class="mb-0">🎯 选片工作台</h5>
                    <small class="text-muted">
                        {% if outing_id == 'all' %}
                            当前范围：全部外拍
                        {% elif current_outing %}
                            当前外拍：{{ current_outing.name }}（{{ current_outing.start_date }}）
                        {% else %}
                            当前范围：全部外拍
                        {% endif %}
                    </small>
                </div>
```

In the date/rating filter form (line 70), add a hidden input to preserve the selected outing:

```html
                    <form class="d-flex" action="/select" method="get">
                        <input type="hidden" name="outing_id" value="{{ outing_id }}">
                        <input class="form-control form-control-sm me-2" type="search" name="date" placeholder="选择日期 YYYY-MM-DD" value="{{ current_date }}">
                        <button class="btn btn-sm btn-outline-secondary" type="submit">筛选</button>
                    </form>
```

Update the rating filter links (lines 93-104) to also preserve `outing_id`:

```html
                    <a href="?outing_id={{ outing_id }}{% if current_date %}&date={{ current_date }}{% endif %}"
                       class="btn btn-outline-secondary {{ 'active' if not current_rating else '' }}">全部</a>
                    <a href="?rating=5&outing_id={{ outing_id }}{% if current_date %}&date={{ current_date }}{% endif %}"
                       class="btn btn-outline-success {{ 'active' if current_rating == '5' else '' }}">🌟🌟🌟🌟🌟 精选</a>
                    <a href="?rating=4&outing_id={{ outing_id }}{% if current_date %}&date={{ current_date }}{% endif %}"
                       class="btn btn-outline-primary {{ 'active' if current_rating == '4' else '' }}">🌟🌟🌟🌟 可用</a>
                    <a href="?rating=3&outing_id={{ outing_id }}{% if current_date %}&date={{ current_date }}{% endif %}"
                       class="btn btn-outline-info {{ 'active' if current_rating == '3' else '' }}">🌟🌟🌟 记录</a>
                    <a href="?rating=1&outing_id={{ outing_id }}{% if current_date %}&date={{ current_date }}{% endif %}"
                       class="btn btn-outline-danger {{ 'active' if current_rating == '1' else '' }}">❌ 淘汰</a>
                    <a href="?rating=0&outing_id={{ outing_id }}{% if current_date %}&date={{ current_date }}{% endif %}"
                       class="btn btn-outline-dark {{ 'active' if current_rating == '0' else '' }}">🚫 无鸟</a>
```

Update the gallery link (line 83) to use the actual current outing or `all`:

```html
                    <a href="/gallery?outing_id={{ current_outing.id if current_outing else 'all' }}" class="btn btn-primary">查看本次外拍 → 图库</a>
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_web_three_domain.py -k select -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/web/app.py src/web/templates/select.html tests/test_web_three_domain.py
git commit -m "feat: select page supports default/latest/all/specific outing filter"
```

---

## Task 3: Update `/gallery` route and template

**Files:**
- Modify: `src/web/app.py:1485-1720` (`gallery_page` route)
- Modify: `src/web/templates/gallery.html:50-168` (filter form and status bar)
- Test: `tests/test_web_three_domain.py`

**Interfaces:**
- Consumes: `_resolve_outing_scope`, `outing_id` as `str`
- Produces: `gallery_page` accepts `outing_id: str = ""`, context includes `outing_id` string and `current_outing`

- [ ] **Step 1: Write/update failing tests**

Add to `tests/test_web_three_domain.py`:

```python
def test_gallery_page_defaults_to_all_outings(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="外拍1", start_date="20260710")
    o2 = Outing(name="外拍2", start_date="20260720")
    session.add(o1)
    session.add(o2)
    session.commit()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", primary_bird_cn="麻雀", scientific_name="Passer", outing_id=o1.id, quality_score=60))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", primary_bird_cn="麻雀", scientific_name="Passer", outing_id=o2.id, quality_score=70))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(request=object())
    context = templates.calls[0]["context"]
    assert context["outing_id"] == ""
    assert context["current_outing"] is None
    assert context["total_count"] == 2


def test_gallery_page_filters_by_outing_id(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="外拍1", start_date="20260710")
    o2 = Outing(name="外拍2", start_date="20260720")
    session.add(o1)
    session.add(o2)
    session.commit()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", primary_bird_cn="麻雀", scientific_name="Passer", outing_id=o1.id, quality_score=60))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", primary_bird_cn="麻雀", scientific_name="Passer", outing_id=o2.id, quality_score=70))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(request=object(), outing_id=str(o1.id))
    context = templates.calls[0]["context"]
    assert context["outing_id"] == str(o1.id)
    assert context["current_outing"].id == o1.id
    assert context["total_count"] == 1


def test_gallery_page_preserves_outing_id_in_base_query(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="外拍1", start_date="20260710")
    session.add(o1)
    session.commit()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", primary_bird_cn="麻雀", scientific_name="Passer", outing_id=o1.id, quality_score=60))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(request=object(), outing_id=str(o1.id))
    context = templates.calls[0]["context"]
    assert f"outing_id={o1.id}" in context["base_query"]
```

Also update existing gallery direct calls to pass `outing_id=""` if they currently pass `outing_id=0`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_web_three_domain.py -k gallery -v
```

Expected: FAIL.

- [ ] **Step 3: Update `/gallery` route**

Change the function signature in `src/web/app.py`:

```python
@app.get("/gallery", response_class=HTMLResponse)
def gallery_page(
    request: Request,
    q: str = "",
    view: str = "",
    filter: str = "",
    date: str = "",
    date_from: str = "",
    date_to: str = "",
    species: List[str] = Query(default=[]),
    families: List[str] = Query(default=[]),
    locations: List[str] = Query(default=[]),
    location_level1: List[str] = Query(default=[]),
    location_level2: List[str] = Query(default=[]),
    location_level3: List[str] = Query(default=[]),
    outing_id: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """图库浏览：按时间/地点/鸟种/视图/外拍筛选。"""
```

After `session = get_sqlalchemy_session()` and the `_list_param` helper, resolve the outing:

```python
    session = get_sqlalchemy_session()
    try:
        # Resolve outing scope: default = all outings
        outing_id = str(outing_id) if outing_id is not None else ""
        current_outing_scope, current_outing = _resolve_outing_scope(
            session, outing_id, default="all"
        )
```

The existing `if outing_id:` filter block (around line 1589) becomes:

```python
        if current_outing:
            query = query.filter(Photo.outing_id == current_outing.id)
```

In the `filter_params` dict (around line 1663), the existing condition:

```python
        if outing_id:
            filter_params["outing_id"] = outing_id
```

should become:

```python
        if outing_id:
            filter_params["outing_id"] = outing_id
```

This already works because `outing_id` is now a string and `all` / numeric IDs are truthy.

Update the final context:

```python
                "outing_id": outing_id,
                "current_outing": current_outing,
```

- [ ] **Step 4: Update `gallery.html` template**

Add a current scope display after the filter form card (around line 58, inside the filter form area):

```html
                            <div class="col-12">
                                <span class="text-muted small">
                                    {% if outing_id == 'all' or not current_outing %}
                                        当前范围：全部外拍
                                    {% else %}
                                        当前外拍：{{ current_outing.name }}（{{ current_outing.start_date }}）
                                    {% endif %}
                                </span>
                            </div>
```

Add a hidden input inside the filter form (`#filterForm`) to preserve `outing_id`:

```html
                        <form id="filterForm" action="/gallery" method="get" class="row g-2 align-items-end">
                            <input type="hidden" name="outing_id" value="{{ outing_id }}">
```

In the status bar (line 158), update the outing display to use `current_outing`:

```html
                {% if current_outing %} | 外拍：{{ current_outing.name }}（{{ current_outing.start_date }}）{% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_web_three_domain.py -k gallery -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/web/app.py src/web/templates/gallery.html tests/test_web_three_domain.py
git commit -m "feat: gallery page supports default/all/specific outing filter"
```

---

## Task 4: Update `/guide` route and template

**Files:**
- Modify: `src/web/app.py:1867-1956` (`guide_page` route)
- Modify: `src/web/templates/guide.html:29-45` (stats bar)
- Test: `tests/test_web_three_domain.py`

**Interfaces:**
- Consumes: `_resolve_outing_scope`, `outing_id` as `str`
- Produces: `guide_page` accepts `outing_id: str = ""`, filters species by selected outing when provided, highlights new species for that outing

- [ ] **Step 1: Write/update failing tests**

Update existing guide tests and add new ones in `tests/test_web_three_domain.py`:

```python
def test_guide_page_renders_template(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = web_app.guide_page(request=object(), q="")

    assert result == {
        "template": "guide.html",
        "context": {
            "request": ANY,
            "families": [],
            "total_species": 0,
            "total_families": 0,
            "query": "",
            "outing_id": "",
            "current_outing": None,
        },
    }


def test_guide_page_filters_species_by_outing(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="外拍1", start_date="20260710")
    o2 = Outing(name="外拍2", start_date="20260720")
    session.add(o1)
    session.add(o2)
    session.commit()
    session.add(Species(scientific_name="Passer domesticus", chinese_name="家麻雀", family_cn="雀科", family_sci="Passeridae", photo_count=1))
    session.add(Species(scientific_name="Cyanocitta cristata", chinese_name="冠蓝鸦", family_cn="鸦科", family_sci="Corvidae", photo_count=1))
    session.add(Photo(file_path="a.jpg", filename="a.jpg", scientific_name="Passer domesticus", outing_id=o1.id, quality_score=80, captured_date="2026-07-10"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", scientific_name="Cyanocitta cristata", outing_id=o2.id, quality_score=80, captured_date="2026-07-20"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.guide_page(request=object(), q="", outing_id=str(o1.id))
    context = templates.calls[0]["context"]
    assert context["outing_id"] == str(o1.id)
    assert context["current_outing"].id == o1.id
    assert context["total_species"] == 1
    families = {f["family_cn"]: f["species"] for f in context["families"]}
    assert "雀科" in families
    assert "鸦科" not in families
```

Update `test_guide_page_highlights_new_species` to pass an explicit `outing_id` (the new outing) since the default no longer auto-selects the latest outing:

```python
    web_app.guide_page(request=object(), q="", outing_id=str(new_outing.id))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_web_three_domain.py -k guide -v
```

Expected: FAIL.

- [ ] **Step 3: Update `/guide` route**

Change the signature and opening logic in `src/web/app.py`:

```python
@app.get("/guide", response_class=HTMLResponse)
def guide_page(request: Request, q: str = "", outing_id: str = ""):
    """鸟类图鉴：已解锁物种墙，按科分组。本次外拍新增物种高亮。"""
    session = get_sqlalchemy_session()
    try:
        # Resolve outing scope: default = all outings
        outing_id = str(outing_id) if outing_id is not None else ""
        current_outing_scope, current_outing = _resolve_outing_scope(
            session, outing_id, default="all"
        )
        current_outing_id = current_outing.id if current_outing else None

        species_query = session.query(Species).filter(Species.photo_count > 0)
        if current_outing_id:
            species_query = species_query.join(
                Photo, Species.scientific_name == Photo.scientific_name
            ).filter(Photo.outing_id == current_outing_id).distinct()
        if q:
            species_query = species_query.filter(
                (Species.chinese_name.like(f"%{q}%")) |
                (Species.scientific_name.like(f"%{q}%")) |
                (Species.family_cn.like(f"%{q}%")) |
                (Species.family_sci.like(f"%{q}%"))
            )
        species_list = species_query.order_by(Species.family_cn, Species.chinese_name).all()
```

Keep the rest of the function, including the new-species calculation which already uses `current_outing_id` correctly.

Update the final context:

```python
        return templates.TemplateResponse(
            request, "guide.html",
            {
                "request": request,
                "families": families,
                "total_species": total_species,
                "total_families": total_families,
                "query": q,
                "outing_id": outing_id,
                "current_outing": current_outing,
            },
        )
```

- [ ] **Step 4: Update `guide.html` template**

In the stats bar (around line 29), replace the current outing display with:

```html
                <div>
                    <span class="fw-bold">📚 已解锁物种：</span>
                    <span class="badge bg-primary fs-6">{{ total_species }}</span>
                    <span class="text-muted ms-2">（共 {{ total_families }} 科）</span>
                </div>
                <div class="text-muted small">
                    {% if outing_id == 'all' or not current_outing %}
                        当前范围：全部外拍
                    {% else %}
                        当前外拍：{{ current_outing.name }}（{{ current_outing.start_date }}）
                    {% endif %}
                </div>
```

Add a hidden `outing_id` input to the search form (line 39):

```html
                <form class="d-flex" action="/guide" method="get">
                    <input type="hidden" name="outing_id" value="{{ outing_id }}">
                    <input class="form-control form-control-sm me-2" type="search" name="q" placeholder="搜索物种/科..." value="{{ query }}">
                    <button class="btn btn-sm btn-outline-secondary" type="submit">搜索</button>
                </form>
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_web_three_domain.py -k guide -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/web/app.py src/web/templates/guide.html tests/test_web_three_domain.py
git commit -m "feat: guide page supports default/all/specific outing filter"
```

---

## Task 5: Add global outing selector to navbar

**Files:**
- Modify: `src/web/templates/navbar.html`
- Test: `tests/test_web_three_domain.py` or `tests/test_web_app.py`

**Interfaces:**
- Consumes: `GET /api/outings`, current URL `outing_id` parameter
- Produces: global `<select>` in navbar, navigation links preserve `outing_id`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_web_three_domain.py`:

```python
def test_navbar_contains_outing_selector_and_preserves_outing_id(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="测试外拍", start_date="20260720")
    session.add(o1)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", primary_bird_cn="麻雀", scientific_name="Passer", outing_id=o1.id, quality_score=60))
    session.commit()
    session.close()

    with TestClient(web_app.app) as client:
        resp = client.get(f"/select?outing_id={o1.id}")
    assert resp.status_code == 200
    body = resp.text
    # Selector skeleton and class are present
    assert "outing-selector" in body
    assert 'id="outingSelector"' in body
    # Default options are rendered server-side
    assert "默认（按页面）" in body
    assert "全部外拍" in body
    # The inline script updates URL and nav links with outing_id
    assert "url.searchParams.set('outing_id', value)" in body
    assert "url.searchParams.set('outing_id', currentOuting)" in body
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_web_three_domain.py::test_navbar_contains_outing_selector_and_preserves_outing_id -v
```

Expected: FAIL (selector not present).

- [ ] **Step 3: Update `navbar.html`**

Replace the content of `src/web/templates/navbar.html` with:

```html
<nav class="navbar navbar-expand-lg shadow-sm" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
    <div class="container">
        <a class="navbar-brand fw-bold text-white" href="/">
            <span style="font-size: 1.3em;">🕊️</span> 飞羽志 <span class="opacity-75">| WingScribe</span>
        </a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav me-auto">
                <li class="nav-item"><a class="nav-link text-white {% if active_page == 'import' %}active bg-white bg-opacity-25 rounded{% endif %}" href="/import"><i class="bi bi-cloud-upload"></i> 导入</a></li>
                <li class="nav-item"><a class="nav-link text-white {% if active_page == 'select' %}active bg-white bg-opacity-25 rounded{% endif %}" href="/select">选片</a></li>
                <li class="nav-item"><a class="nav-link text-white {% if active_page == 'gallery' %}active bg-white bg-opacity-25 rounded{% endif %}" href="/gallery">图库</a></li>
                <li class="nav-item"><a class="nav-link text-white {% if active_page == 'guide' %}active bg-white bg-opacity-25 rounded{% endif %}" href="/guide">图鉴</a></li>
                <li class="nav-item"><a class="nav-link text-white {% if active_page == 'log' %}active bg-white bg-opacity-25 rounded{% endif %}" href="/log">观鸟记录</a></li>
                <li class="nav-item"><a class="nav-link text-white {% if active_page == 'admin' %}active bg-white bg-opacity-25 rounded{% endif %}" href="/admin">管理</a></li>
            </ul>
            <form class="d-flex align-items-center gap-2">
                <select id="outingSelector" class="form-select form-select-sm outing-selector" style="width: auto; min-width: 10rem;" data-current-outing="">
                    <option value="">默认（按页面）</option>
                    <option value="all">全部外拍</option>
                </select>
                <a class="btn btn-light btn-sm" href="/settings"><i class="bi bi-gear-fill"></i> 设置</a>
            </form>
        </div>
    </div>
</nav>

<script>
(function() {
    const selector = document.getElementById('outingSelector');
    if (!selector) return;

    const params = new URLSearchParams(window.location.search);
    const currentOuting = params.get('outing_id') || '';
    selector.setAttribute('data-current-outing', currentOuting);

    // Fetch outings and populate dropdown
    fetch('/api/outings')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success' || !Array.isArray(data.outings)) return;
            data.outings.forEach(o => {
                const option = document.createElement('option');
                option.value = String(o.id);
                const date = o.start_date ? o.start_date.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3') : '';
                option.textContent = `${o.name}${date ? ' (' + date + ')' : ''}`;
                selector.appendChild(option);
            });
            selector.value = currentOuting;
        })
        .catch(err => {
            console.error('加载外拍列表失败:', err);
        });

    // On change, reload current page with the selected outing_id
    selector.addEventListener('change', () => {
        const value = selector.value;
        const url = new URL(window.location.href);
        if (value) {
            url.searchParams.set('outing_id', value);
        } else {
            url.searchParams.delete('outing_id');
        }
        window.location.href = url.toString();
    });

    // Update top-level nav links to preserve the selected outing_id
    document.querySelectorAll('#navbarNav .nav-link').forEach(link => {
        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;
        const url = new URL(href, window.location.origin);
        if (currentOuting) {
            url.searchParams.set('outing_id', currentOuting);
        } else {
            url.searchParams.delete('outing_id');
        }
        link.setAttribute('href', url.pathname + url.search);
    });
})();
</script>
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_web_three_domain.py::test_navbar_contains_outing_selector_and_preserves_outing_id -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/templates/navbar.html tests/test_web_three_domain.py
git commit -m "feat: add global outing selector to navbar"
```

---

## Task 6: Run full test suite and fix regressions

**Files:**
- All modified files above
- Tests: `tests/test_web_*.py` and the full suite

- [ ] **Step 1: Run the focused web test files**

```bash
python -m pytest tests/test_web_three_domain.py tests/test_web_app.py tests/test_web_log.py tests/test_web_review.py -v
```

Expected: All tests pass. If any fail, fix the route/template/test in the relevant task file.

- [ ] **Step 2: Run the full test suite**

```bash
python -m pytest
```

Expected: All tests pass (or only pre-existing failures).

- [ ] **Step 3: Manual smoke test (if local server is running)**

```bash
python src\web\app.py
```

Then in browser:
1. Open `http://localhost:8000/select` → should show最近一次外拍（或无数据）。
2. Use navbar dropdown to select “全部外拍” → page should reload and show all outings' photos.
3. Select a specific outing → should filter to that outing.
4. Navigate to `/gallery` and `/guide` → default should be “全部外拍”.
5. Select an outing in navbar and switch between pages → selected outing should be preserved.
6. Select “默认（按页面）” → each page reverts to its own default.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: global outing filter for select/gallery/guide pages"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - [ ] Navigation bar global selector → Task 5.
   - [ ] URL `outing_id` with `all`/numeric/empty → all route tasks.
   - [ ] Select default latest → Task 2.
   - [ ] Gallery default all → Task 3.
   - [ ] Guide default all, single outing filters species → Task 4.
   - [ ] Log unchanged → no task.
   - [ ] Tests for helper/API and regressions → Task 1 and 6.

2. **Placeholder scan:**
   - [ ] No “TBD” or “TODO” in plan steps.
   - [ ] Every code step contains actual code or exact commands.

3. **Type consistency:**
   - [ ] `outing_id` is consistently `str` in route signatures and template contexts.
   - [ ] `_resolve_outing_scope` returns `tuple[str, Optional[Outing]]` everywhere.
   - [ ] `/api/outings` returns consistent JSON schema.

If any item is missing, go back and add the corresponding step before execution.

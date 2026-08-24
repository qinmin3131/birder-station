# 选片工作台已处理进度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 选片页顶部新增「已处理/未处理」进度统计条，已处理 =（选中且鸟种已确认）或（已淘汰），随标记/修正操作实时刷新。

**Architecture:** 在 `src/web/app.py` 新增模块级函数 `_compute_select_progress(session, outing_id, date)` 作为唯一统计实现，同时供 `/api/select/progress` 端点与 `/select` 页面上下文使用。前端在 select.html 标题栏下方渲染 Bootstrap 进度条，标记/修正成功后 JS 调端点刷新。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, Jinja2 + Bootstrap 5, pytest.

## Global Constraints

- **口径唯一**: 统计逻辑只存在于 `_compute_select_progress`，端点与页面共用，禁止重复实现。
- **已处理定义**: `(is_selected AND primary_bird_cn 非 '待确认鸟种' AND scientific_name 非 'Uncertain') OR rating == -1`；鸟种字段为 NULL（无鸟）视为已确认。
- **统计口径**: 应用 `outing_id`（0 = 最近一次外拍；无外拍则全表）与 `date` 筛选；不接收、不应用 `rating` 筛选。
- **测试**: Pytest；TDD 先红后绿。
- **Commit 风格**: `功能:` 前缀。

---

## Task 1: 进度统计函数与 API 端点

**Files:**
- Modify: `src/web/app.py`（`_apply_rating_filter` 之前插入 `_compute_select_progress`；`select_page` 之后插入 `select_progress` 端点）
- Test: `tests/test_web_three_domain.py`（追加用例）

**Interfaces:**
- Consumes: `src.db.models.Photo/Outing`、`get_sqlalchemy_session()`。
- Produces: `_compute_select_progress(session, outing_id: int = 0, date: str = "") -> dict`，返回 `{"total": int, "processed": int, "unprocessed": int, "percent": int}`；`GET /api/select/progress?outing_id=0&date=` 返回 `{"status": "success", **进度dict}`。Task 2 的 `select_page` 与 select.html 依赖此 dict。

- [ ] **Step 1: 写失败测试**

在 `tests/test_web_three_domain.py` 末尾追加：

```python
def test_select_progress_endpoint_empty_db(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))

    result = web_app.select_progress(outing_id=0, date="")

    assert result == {"status": "success", "total": 0, "processed": 0, "unprocessed": 0, "percent": 0}


def test_select_progress_counts_processed_states(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    # 选中 + 已确认 → 已处理
    session.add(Photo(file_path="a.jpg", filename="a.jpg", is_selected=True, primary_bird_cn="麻雀", scientific_name="Passer montanus"))
    # 选中 + 待确认 → 未处理
    session.add(Photo(file_path="b.jpg", filename="b.jpg", is_selected=True, primary_bird_cn="待确认鸟种"))
    # 选中 + Uncertain 学名 → 未处理
    session.add(Photo(file_path="c.jpg", filename="c.jpg", is_selected=True, primary_bird_cn="麻雀", scientific_name="Uncertain"))
    # 淘汰 → 已处理
    session.add(Photo(file_path="d.jpg", filename="d.jpg", rating=-1, primary_bird_cn="待确认鸟种"))
    # 未动 → 未处理
    session.add(Photo(file_path="e.jpg", filename="e.jpg", primary_bird_cn="麻雀", scientific_name="Passer montanus"))
    # 选中 + 无鸟（NULL）→ 已处理
    session.add(Photo(file_path="f.jpg", filename="f.jpg", is_selected=True))
    session.commit()
    session.close()

    result = web_app.select_progress(outing_id=0, date="")

    assert result["total"] == 6
    assert result["processed"] == 3
    assert result["unprocessed"] == 3
    assert result["percent"] == 50


def test_select_progress_filters_outing_and_date(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="外拍1", start_date="20260720")
    o2 = Outing(name="外拍2", start_date="20260721")
    session.add_all([o1, o2])
    session.flush()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", outing_id=o1.id, captured_date="2026-07-20", is_selected=True, primary_bird_cn="麻雀"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", outing_id=o1.id, captured_date="2026-07-21", rating=-1))
    session.add(Photo(file_path="c.jpg", filename="c.jpg", outing_id=o2.id, captured_date="2026-07-21", rating=-1))
    session.commit()
    o1_id, o2_id = o1.id, o2.id
    session.close()

    # outing_id 过滤
    result = web_app.select_progress(outing_id=o1_id, date="")
    assert result["total"] == 2 and result["processed"] == 2
    # outing_id + date 过滤
    result = web_app.select_progress(outing_id=o1_id, date="2026-07-21")
    assert result["total"] == 1 and result["processed"] == 1
    # 指定外拍优先于"最近一次外拍"回退
    result = web_app.select_progress(outing_id=o2_id, date="")
    assert result["total"] == 1
```

Run: `python -m pytest tests/test_web_three_domain.py -k select_progress -v`
Expected: FAIL（`AttributeError: module 'src.web.app' has no attribute 'select_progress'`）。

- [ ] **Step 2: 实现统计函数与端点**

修改 `src/web/app.py`：

1. 在 `_apply_rating_filter` 函数定义之前插入：

```python
def _compute_select_progress(session, outing_id: int = 0, date: str = "") -> dict:
    """选片进度：已处理 =（选中且鸟种已确认）或已淘汰。

    鸟种字段为 NULL（无鸟）视为已确认； outing_id=0 时回退到最近一次外拍，
    无外拍则统计全表；应用 date 筛选；不涉及 rating 等级筛选。
    """
    query = session.query(Photo)
    current_outing = None
    if outing_id:
        current_outing = session.query(Outing).filter(Outing.id == outing_id).first()
    if not current_outing:
        current_outing = session.query(Outing).order_by(Outing.created_at.desc()).first()
    if current_outing:
        query = query.filter(Photo.outing_id == current_outing.id)
    if date:
        query = query.filter(Photo.captured_date == date)

    cn_confirmed = (Photo.primary_bird_cn.is_(None)) | (Photo.primary_bird_cn != "待确认鸟种")
    sci_confirmed = (Photo.scientific_name.is_(None)) | (Photo.scientific_name != "Uncertain")
    processed_cond = ((Photo.is_selected == True) & cn_confirmed & sci_confirmed) | (Photo.rating == -1)

    total = query.count()
    processed = query.filter(processed_cond).count()
    percent = round(processed / total * 100) if total else 0
    return {"total": total, "processed": processed, "unprocessed": total - processed, "percent": percent}
```

2. 在 `select_page` 函数结束之后（`@app.post("/api/select/pick-best/{group_id}")` 之前）插入：

```python
@app.get("/api/select/progress")
def select_progress(outing_id: int = 0, date: str = ""):
    """选片进度统计：已处理/未处理数量与百分比。"""
    session = get_sqlalchemy_session()
    try:
        data = _compute_select_progress(session, outing_id, date)
        return {"status": "success", **data}
    except Exception as e:
        logger.error(f"Failed to compute select progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
```

Run: `python -m pytest tests/test_web_three_domain.py -k select_progress -v`
Expected: 3 PASS。

- [ ] **Step 3: Commit**

```bash
git add src/web/app.py tests/test_web_three_domain.py
git commit -m "功能: 添加选片进度统计 /api/select/progress"
```

---

## Task 2: 选片页进度条 UI 与实时刷新

**Files:**
- Modify: `src/web/app.py`（`select_page` 上下文增加 `progress`）
- Modify: `src/web/templates/select.html`
- Test: `tests/test_web_three_domain.py`（更新 `test_select_page_renders_template` 期望上下文 + 新增进度上下文用例）

**Interfaces:**
- Consumes: Task 1 的 `_compute_select_progress`。
- Produces: `select_page` 模板上下文新增键 `progress: dict`（结构同 Task 1）；模板元素 id `progressText`、`progressBar`；JS 函数 `refreshProgress()`。

- [ ] **Step 1: 更新现有上下文测试（先红）**

`tests/test_web_three_domain.py::test_select_page_renders_template` 的期望上下文字典中，在 `"outing_id": 0` 后增加一行：

```python
            "progress": {"total": 0, "processed": 0, "unprocessed": 0, "percent": 0},
```

并在文件末尾追加：

```python
def test_select_page_includes_progress_context(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", is_selected=True, primary_bird_cn="麻雀", scientific_name="Passer montanus"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.select_page(request=object(), date="")

    progress = templates.calls[0]["context"]["progress"]
    assert progress == {"total": 2, "processed": 1, "unprocessed": 1, "percent": 50}
```

Run: `python -m pytest tests/test_web_three_domain.py -k "select_page_renders_template or progress_context" -v`
Expected: 两个都 FAIL（上下文缺 `progress` 键）。

- [ ] **Step 2: `select_page` 传入 progress**

修改 `src/web/app.py` 的 `select_page`，在 `return templates.TemplateResponse(...)` 的上下文字典中 `"outing_id": current_outing.id if current_outing else 0,` 之后增加：

```python
                "progress": _compute_select_progress(
                    session, current_outing.id if current_outing else 0, date
                ),
```

Run: `python -m pytest tests/test_web_three_domain.py -k "select_page_renders_template or progress_context" -v`
Expected: 2 PASS。再跑 `python -m pytest tests/test_web_three_domain.py -v` 确认全文件回归 PASS。

- [ ] **Step 3: 模板加进度条 + JS 刷新**

修改 `src/web/templates/select.html`：

1. 在 `<!-- Star rating filter bar -->` 注释行之前插入：

```html
        <div class="row mb-3">
            <div class="col-12">
                <div class="d-flex align-items-center gap-3">
                    <span class="small text-muted text-nowrap" id="progressText">共 {{ progress.total }} 张 · 已处理 {{ progress.processed }} · 未处理 {{ progress.unprocessed }}</span>
                    <div class="progress flex-grow-1" style="height: 12px;">
                        <div id="progressBar" class="progress-bar bg-success" role="progressbar" style="width: {{ progress.percent }}%;">{{ progress.percent }}%</div>
                    </div>
                </div>
            </div>
        </div>
```

2. 在 `<script>` 内 `emptyTrash` 函数定义之后追加：

```javascript
        function refreshProgress() {
            fetch(`/api/select/progress?outing_id={{ outing_id }}{% if current_date %}&date={{ current_date }}{% endif %}`)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('progressText').textContent = `共 ${data.total} 张 · 已处理 ${data.processed} · 未处理 ${data.unprocessed}`;
                    const bar = document.getElementById('progressBar');
                    bar.style.width = `${data.percent}%`;
                    bar.textContent = `${data.percent}%`;
                })
                .catch(e => console.error(e));
        }
```

3. `markPhoto` 的 fetch 链中增加刷新（`emptyTrash` 成功后已 `location.reload()`，无需挂钩）：

```javascript
        function markPhoto(id, action) {
            const card = document.querySelector(`#photo-card-${id} .card`);
            card.classList.remove('selected-card', 'rejected-card');
            if (action === 'select') card.classList.add('selected-card');
            if (action === 'reject') card.classList.add('rejected-card');
            fetch('/api/select/mark', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({photo_id: id, action: action})
            }).then(() => refreshProgress()).catch(e => console.error(e));
        }
```

4. `autoPickBest` 成功分支 `alert(...)` 之前增加一行 `refreshProgress();`。
5. `confirmReviewSpecies` 成功分支 `alert('鸟种已修正');` 之前增加一行 `refreshProgress();`。

- [ ] **Step 4: 验证**

Run: `python -m pytest tests/test_web_three_domain.py tests/test_web_trash.py -v`
Expected: 全部 PASS（模板渲染断言不受新增 DOM 影响；`/select` HTTP 渲染用例仍 PASS）。

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py src/web/templates/select.html tests/test_web_three_domain.py
git commit -m "功能: 选片页顶部显示已处理/未处理进度条并随操作实时刷新"
```

---

## Task 3: 全量验证

- [ ] **Step 1: 全量测试**

Run: `python -m pytest`
Expected: 全部 PASS（370 + 新增用例），无新 failure。

- [ ] **Step 2: 语法检查**

Run: `python -m py_compile src/web/app.py`
Expected: 无输出（退出码 0）。

---

## Spec 覆盖自查

| 设计文档条目 | 覆盖 Task |
|--------------|-----------|
| `/api/select/progress` 端点（outing 回退/date 筛选/忽略 rating） | Task 1 |
| `_compute_select_progress` 唯一实现 | Task 1 Step 2 |
| 已处理定义含 NULL 鸟种、淘汰 | Task 1 测试用例覆盖 |
| select_page 上下文 progress（首屏服务端渲染） | Task 2 Step 1-2 |
| 顶部进度条 UI（progressText/progressBar） | Task 2 Step 3 |
| 标记/一键精选/修正鸟种后刷新 | Task 2 Step 3（emptyTrash 走 reload 故不挂钩） |
| 空库 percent=0 | Task 1 `test_select_progress_endpoint_empty_db` |
| 范围之外（组头进度/角标/筛选） | 无对应 Task（符合 YAGNI） |

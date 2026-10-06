# 图库分类树侧边栏 & 外拍筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为图库页面新增分类树侧边栏和外拍下拉筛选，替代现有物种/科下拉筛选

**Architecture:** 左侧 3 列分类树侧边栏 + 右侧 9 列照片网格，分类树通过 AJAX 过滤照片，外拍下拉通过页面跳转

**Tech Stack:** Python/FastAPI/Jinja2, Bootstrap 5, vanilla JavaScript, SQLAlchemy, SQLite

## Global Constraints

- Python 3.11+, 4-space indentation, PEP 8 naming
- Bootstrap 5 CSS/JS (already in project)
- No new JS frameworks — vanilla JS only
- All API parameters are optional, no breaking changes
- localStorage for expand state persistence

---

## Task 1: Add outings list API endpoint

**Files:**
- Modify: `src/web/app.py` (add new endpoint after existing taxonomy endpoints)
- Test: `tests/test_api_outings.py` (new file)

**Interfaces:**
- Produces: `GET /api/outings` → `{ outings: [{ id, name, start_date, end_date, location_tag, photo_count }] }`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_outings.py
import pytest
from src.web.app import app
from fastapi.testclient import TestClient

def test_list_outings():
    client = TestClient(app)
    response = client.get("/api/outings")
    assert response.status_code == 200
    data = response.json()
    assert "outings" in data
    assert isinstance(data["outings"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_outings.py -v`
Expected: FAIL with 404 or endpoint not found

- [ ] **Step 3: Write minimal implementation**

在 `src/web/app.py` 中，找到 taxonomy endpoints 区域（约 line 420 之后），添加：

```python
@app.get("/api/outings")
def list_outings():
    """返回所有外拍列表，按日期倒序"""
    session = get_sqlalchemy_session()
    try:
        from sqlalchemy import func
        outings = (
            session.query(
                Outing.id,
                Outing.name,
                Outing.start_date,
                Outing.end_date,
                Outing.location_tag,
                func.count(Photo.id).label("photo_count"),
            )
            .outerjoin(Photo, Photo.outing_id == Outing.id)
            .group_by(Outing.id)
            .order_by(Outing.start_date.desc(), Outing.created_at.desc())
            .all()
        )
        return {
            "outings": [
                {
                    "id": o.id,
                    "name": o.name,
                    "start_date": o.start_date,
                    "end_date": o.end_date,
                    "location_tag": o.location_tag,
                    "photo_count": o.photo_count,
                }
                for o in outings
            ]
        }
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_outings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py tests/test_api_outings.py
git commit -m "功能: 新增 /api/outings 外拍列表接口"
```

---

## Task 2: Add outing_id to taxonomy tree API

**Files:**
- Modify: `src/web/taxonomy_service.py` (add outing_id parameter)
- Modify: `src/web/app.py` (add outing_id to taxonomy endpoints)
- Modify: `src/metadata/ioc_manager.py` (add outing_id to tree queries)

**Interfaces:**
- Produces: `GET /api/taxonomy/tree?outing_id=123` → filtered tree

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_outings.py (append)
def test_taxonomy_tree_with_outing_filter():
    client = TestClient(app)
    response = client.get("/api/taxonomy/tree?outing_id=1")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_outings.py::test_taxonomy_tree_with_outing_filter -v`
Expected: FAIL (outings param ignored)

- [ ] **Step 3: Modify taxonomy_service.py**

```python
# src/web/taxonomy_service.py - 修改 get_taxonomy_tree
def get_taxonomy_tree(create_db_manager, include_empty: bool = True, date: str = None, outing_id: int = 0):
    manager = create_db_manager()
    try:
        if date:
            return manager.get_taxonomy_tree(include_empty=include_empty, date_filter=date, outing_id=outing_id)
        return manager.get_taxonomy_tree_fast(include_empty=include_empty, outing_id=outing_id)
    finally:
        manager.close()
```

- [ ] **Step 4: Modify app.py taxonomy endpoints**

```python
# src/web/app.py - 修改 get_taxonomy_tree 路由
@app.get("/api/taxonomy/tree")
def get_taxonomy_tree(include_empty: bool = True, date: str = None, outing_id: int = 0):
    """获取分类树，支持显示/隐藏空层级、日期筛选和外拍筛选"""
    return taxonomy_service.get_taxonomy_tree(create_db_manager, include_empty, date, outing_id)
```

- [ ] **Step 5: Modify ioc_manager.py get_taxonomy_tree**

在 `src/metadata/ioc_manager.py` 的 `get_taxonomy_tree` 方法（line 550）中，添加 `outing_id` 参数：

```python
def get_taxonomy_tree(self, include_empty: bool = True, date_filter: str = None, outing_id: int = 0) -> List[Dict]:
    params = []
    count_expr = "COUNT(DISTINCT p.id)"
    if date_filter:
        count_expr = "COUNT(DISTINCT CASE WHEN p.captured_date = ? THEN p.id END)"
        params.append(date_filter)

    # Outing filter
    outing_join = ""
    outing_where = ""
    if outing_id:
        outing_join = "JOIN photos p ON t.scientific_name = p.scientific_name AND p.outing_id = ?"
        params.insert(0, outing_id)
        # Need to use different join when outing_id is set
        # Replace the default LEFT JOIN
    # ... rest of method
```

更精确的修改方式：修改 SQL 中的 JOIN 和 WHERE 子句：

```python
def get_taxonomy_tree(self, include_empty: bool = True, date_filter: str = None, outing_id: int = 0) -> List[Dict]:
    params = []
    
    if date_filter and outing_id:
        count_expr = "COUNT(DISTINCT CASE WHEN p.captured_date = ? AND p.outing_id = ? THEN p.id END)"
        params.extend([date_filter, outing_id])
    elif date_filter:
        count_expr = "COUNT(DISTINCT CASE WHEN p.captured_date = ? THEN p.id END)"
        params.append(date_filter)
    elif outing_id:
        count_expr = "COUNT(DISTINCT CASE WHEN p.outing_id = ? THEN p.id END)"
        params.append(outing_id)
    else:
        count_expr = "COUNT(DISTINCT p.id)"

    sql = f'''
        SELECT
            t.order_cn, t.order_sci,
            t.family_cn, t.family_sci,
            t.genus_cn, t.genus_sci,
            t.scientific_name, t.chinese_name, t.english_name,
            {count_expr} as photo_count
        FROM taxonomy t
        LEFT JOIN photos p ON t.scientific_name = p.scientific_name
        WHERE t.order_cn IS NOT NULL AND t.order_cn != ''
        GROUP BY t.scientific_name
        ORDER BY t.order_cn, t.family_cn, t.genus_cn, t.chinese_name
    '''
    rows = self.conn.execute(sql, params).fetchall()
    # ... rest unchanged
```

- [ ] **Step 6: Modify ioc_manager.py get_taxonomy_tree_fast**

在 `get_taxonomy_tree_fast` 方法（line 988）中，添加 outing_id 参数，修改 `get_species_stats_fast` 调用：

```python
def get_taxonomy_tree_fast(self, include_empty: bool = False, outing_id: int = 0) -> List[Dict]:
    stats = self.get_species_stats_fast(min_count=0 if include_empty else 1, outing_id=outing_id)
    # ... rest unchanged
```

- [ ] **Step 7: Run test**

Run: `python -m pytest tests/test_api_outings.py::test_taxonomy_tree_with_outing_filter -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/web/taxonomy_service.py src/web/app.py src/metadata/ioc_manager.py
git commit -m "功能: taxonomy tree API 支持 outing_id 筛选"
```

---

## Task 3: Add outing_id to photos by taxonomy API

**Files:**
- Modify: `src/web/taxonomy_service.py` (add outing_id to get_photos_by_taxonomy)
- Modify: `src/web/app.py` (add outing_id to route)

**Interfaces:**
- Produces: `GET /api/photos/by_taxonomy?outing_id=123&order_sci=...` → filtered photos

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_outings.py (append)
def test_photos_by_taxonomy_with_outing_filter():
    client = TestClient(app)
    response = client.get("/api/photos/by_taxonomy?outing_id=1")
    assert response.status_code == 200
    data = response.json()
    assert "photos" in data
    assert "total_count" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_outings.py::test_photos_by_taxonomy_with_outing_filter -v`
Expected: FAIL

- [ ] **Step 3: Modify taxonomy_service.py**

```python
# src/web/taxonomy_service.py - 修改 get_photos_by_taxonomy
def get_photos_by_taxonomy(
    create_db_manager, get_db_conn, resolve_web_path, resolve_processed_web_path,
    order_cn=None, order_sci=None, family_cn=None, family_sci=None,
    genus_cn=None, genus_sci=None, scientific_name=None,
    date=None, outing_id=0, limit=50, offset=0
):
    manager = create_db_manager()
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        query_parts = ["1=1"]
        params = []
        # ... existing filters ...
        if date:
            query_parts.append("p.captured_date = ?")
            params.append(date)
        if outing_id:
            query_parts.append("p.outing_id = ?")
            params.append(outing_id)
        # ... rest unchanged ...
```

- [ ] **Step 4: Modify app.py route**

```python
# src/web/app.py - 修改 get_photos_by_taxonomy 路由
@app.get("/api/photos/by_taxonomy")
def get_photos_by_taxonomy(
    order_cn=None, order_sci=None, family_cn=None, family_sci=None,
    genus_cn=None, genus_sci=None, scientific_name=None,
    date=None, outing_id: int = 0, limit=50, offset=0
):
    return taxonomy_service.get_photos_by_taxonomy(
        create_db_manager, get_db_conn, resolve_web_path, resolve_processed_web_path,
        order_cn=order_cn, order_sci=order_sci, family_cn=family_cn, family_sci=family_sci,
        genus_cn=genus_cn, genus_sci=genus_sci, scientific_name=scientific_name,
        date=date, outing_id=outing_id, limit=limit, offset=offset
    )
```

- [ ] **Step 5: Run test**

Run: `python -m pytest tests/test_api_outings.py::test_photos_by_taxonomy_with_outing_filter -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/web/taxonomy_service.py src/web/app.py
git commit -m "功能: photos by taxonomy API 支持 outing_id 筛选"
```

---

## Task 4: Modify gallery page to pass outings data to template

**Files:**
- Modify: `src/web/app.py` (gallery_page route)

**Interfaces:**
- Produces: Template context with `available_outings` list

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_outings.py (append)
def test_gallery_page_includes_outings():
    client = TestClient(app)
    response = client.get("/gallery")
    assert response.status_code == 200
    assert "外拍" in response.text  # Outing dropdown present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_outings.py::test_gallery_page_includes_outings -v`
Expected: FAIL

- [ ] **Step 3: Modify gallery_page in app.py**

在 `src/web/app.py` 的 `gallery_page` 函数中，在 `session = get_sqlalchemy_session()` 之后的 try 块内，添加：

```python
# Load all outings for dropdown
from sqlalchemy import func
available_outings = [
    {"id": o.id, "name": o.name, "start_date": o.start_date, "end_date": o.end_date, "location_tag": o.location_tag, "photo_count": pc}
    for o, pc in session.query(
        Outing, func.count(Photo.id).label("photo_count")
    ).outerjoin(Photo, Photo.outing_id == Outing.id).group_by(Outing.id).order_by(Outing.start_date.desc()).all()
]
```

并在 `templates.TemplateResponse` 的 context dict 中添加：

```python
"available_outings": available_outings,
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/test_api_outings.py::test_gallery_page_includes_outings -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py
git commit -m "功能: 图库页面传递外拍列表数据到模板"
```

---

## Task 5: Add sidebar HTML and outing dropdown to gallery template

**Files:**
- Modify: `src/web/templates/gallery.html` (major restructuring)

**Interfaces:**
- Consumes: `available_outings` from template context
- Produces: HTML structure with sidebar and main content area

- [ ] **Step 1: Modify gallery.html layout**

在 `gallery.html` 中，将 `<div class="container-fluid mt-4 px-4">` 内部重构为左右分栏布局：

1. 筛选栏保持在顶部（col-12）
2. 新增 `<div class="row">` 包裹侧边栏和主内容区
3. 左侧 `col-md-3` 为分类树侧边栏
4. 右侧 `col-md-9` 为照片网格和分页

具体 HTML 结构：

```html
<div class="container-fluid mt-4 px-4">
    <!-- 筛选栏（顶部） -->
    <div class="row mb-3">
        <div class="col-12">
            <div class="card">
                <div class="card-body">
                    <form id="filterForm" action="/gallery" method="get" class="row g-2 align-items-end">
                        <!-- 视图切换 -->
                        <div class="col-12 col-md-auto">
                            <div class="btn-group btn-group-sm" role="group">
                                <!-- 保持现有按钮 -->
                            </div>
                        </div>
                        <!-- 搜索 -->
                        <div class="col-12 col-md-2">
                            <input class="form-control form-control-sm" type="search" name="q" placeholder="搜索" value="{{ query }}">
                        </div>
                        <!-- 外拍下拉（新增） -->
                        <div class="col-6 col-md-2">
                            <label class="form-label small text-muted mb-0">外拍</label>
                            <select class="form-select form-select-sm" name="outing_id" onchange="this.form.submit()">
                                <option value="0">全部</option>
                                {% for o in available_outings %}
                                <option value="{{ o.id }}" {{ 'selected' if o.id == outing_id else '' }}>
                                    {{ o.name }} ({{ o.photo_count }}张)
                                </option>
                                {% endfor %}
                            </select>
                        </div>
                        <!-- 日期范围 -->
                        <div class="col-6 col-md-2">
                            <label class="form-label small text-muted mb-0">开始日期</label>
                            <input type="date" class="form-control form-control-sm" name="date_from" value="{{ date_from }}">
                        </div>
                        <div class="col-6 col-md-2">
                            <label class="form-label small text-muted mb-0">结束日期</label>
                            <input type="date" class="form-control form-control-sm" name="date_to" value="{{ date_to }}">
                        </div>
                        <!-- 移除鸟种和科下拉 -->
                        <!-- 省/市/公园下拉保留 -->
                        <!-- ... -->
                        <div class="col-6 col-md-auto d-flex gap-2">
                            <button class="btn btn-sm btn-primary" type="submit">筛选</button>
                            <a href="/gallery" class="btn btn-sm btn-outline-secondary">重置</a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>

    <!-- 主内容区：侧边栏 + 照片 -->
    <div class="row">
        <!-- 左侧分类树侧边栏 -->
        <div class="col-md-3">
            <div class="card sidebar" style="position: sticky; top: 70px; height: calc(100vh - 80px); overflow-y: auto;">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h6 class="mb-0">物种分类</h6>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-secondary btn-sm" id="expand-all-btn" title="展开所有">⊞</button>
                        <button class="btn btn-outline-secondary btn-sm" id="collapse-all-btn" title="折叠所有">⊟</button>
                        <button class="btn btn-outline-secondary btn-sm" id="reset-tree-btn" title="重置筛选">↺</button>
                    </div>
                </div>
                <div class="card-body p-0">
                    <div id="taxonomy-tree" style="padding: 8px;">
                        <div class="text-center text-muted py-3">加载中...</div>
                    </div>
                </div>
                <div id="taxonomy-info" class="card-footer" style="display: none;"></div>
            </div>
        </div>

        <!-- 右侧照片区 -->
        <div class="col-md-9">
            <!-- 状态栏 -->
            <div class="status-bar">
                <!-- 保持现有状态栏内容 -->
            </div>

            <!-- 照片网格 -->
            <div id="photo-gallery-container" class="photo-grid">
                {% for photo in photos %}
                <!-- 保持现有照片卡片 -->
                {% endfor %}
            </div>

            <!-- 分页 -->
            <div class="d-flex justify-content-center mt-4 mb-5">
                <!-- 保持现有分页按钮 -->
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Add sidebar CSS styles**

在 `<style>` 标签中添加：

```css
.sidebar .tree-node {
    padding: 4px 8px;
    cursor: pointer;
    border-radius: 4px;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 4px;
}
.sidebar .tree-node:hover {
    background: #e9ecef;
}
.sidebar .tree-node.active {
    background: #0d6efd;
    color: white;
}
.sidebar .tree-toggle {
    display: inline-block;
    width: 16px;
    text-align: center;
    font-size: 11px;
    color: #666;
}
.sidebar .tree-children {
    display: none;
    padding-left: 16px;
}
.sidebar .tree-children.expanded {
    display: block;
}
.sidebar .node-count {
    font-size: 11px;
    color: #999;
    margin-left: auto;
}
.sidebar .tree-node.active .node-count {
    color: #ddd;
}
#taxonomy-info {
    font-size: 12px;
    padding: 8px 12px;
    background: #f8f9fa;
    border-top: 1px solid #dee2e6;
}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/gallery.html
git commit -m "功能: 图库页面新增分类树侧边栏和外拍下拉HTML结构"
```

---

## Task 6: Add taxonomy tree JavaScript logic

**Files:**
- Modify: `src/web/templates/gallery.html` (add JS in script tag)

**Interfaces:**
- Consumes: `/api/taxonomy/tree`, `/api/photos/by_taxonomy`
- Produces: Tree rendering, AJAX filtering, expand/collapse state

- [ ] **Step 1: Add tree state variables and config**

在 `gallery.html` 的 `<script>` 标签中，在现有 JS 代码之前添加：

```javascript
// Taxonomy tree state
const TREE_CONFIG = {
    defaultExpandLevel: 'none',
    includeEmptyNodes: false,
    rememberExpandState: true,
    expandStateKey: 'birder_station_tree_expand_state'
};

let currentTaxonomyTree = null;
let currentTaxonomyFilter = null;
let expandState = {};

// Load saved expand state from localStorage
function loadExpandState() {
    try {
        const saved = localStorage.getItem(TREE_CONFIG.expandStateKey);
        if (saved) expandState = JSON.parse(saved);
    } catch (e) {
        console.error('Failed to load expand state:', e);
    }
}

// Save expand state to localStorage
function saveExpandState() {
    try {
        localStorage.setItem(TREE_CONFIG.expandStateKey, JSON.stringify(expandState));
    } catch (e) {
        console.error('Failed to save expand state:', e);
    }
}
```

- [ ] **Step 2: Add loadTaxonomyTree function**

```javascript
function loadTaxonomyTree() {
    const container = document.getElementById('taxonomy-tree');
    if (!container) return;

    const outingId = new URLSearchParams(window.location.search).get('outing_id') || '';
    let url = `/api/taxonomy/tree?include_empty=${TREE_CONFIG.includeEmptyNodes}`;
    if (outingId) url += `&outing_id=${outingId}`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            currentTaxonomyTree = data;
            if (!data || data.length === 0) {
                container.innerHTML = '<div class="text-center text-muted py-3">暂无数据</div>';
                return;
            }
            renderTree(data, container);
        })
        .catch(err => {
            container.innerHTML = '<div class="text-center text-danger py-3">加载失败</div>';
        });
}
```

- [ ] **Step 3: Add render functions**

```javascript
function renderTree(orders, container) {
    container.innerHTML = '';
    const ul = document.createElement('ul');
    ul.className = 'list-unstyled ps-0';
    ul.style.marginBottom = '0';
    orders.forEach(order => {
        const li = renderOrderNode(order);
        if (li) ul.appendChild(li);
    });
    container.appendChild(ul);
}

function renderOrderNode(order) {
    if (!order.photo_count && !TREE_CONFIG.includeEmptyNodes) return null;
    const li = document.createElement('li');
    li.style.marginBottom = '2px';
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.dataset.type = 'order';
    node.dataset.value = order.order_cn;
    node.dataset.sci = order.order_sci;
    node.innerHTML = `<span class="tree-toggle">▶</span>${order.order_cn}<span class="node-count">(${order.photo_count})</span>`;
    const shouldExpand = expandState[`order_${order.order_cn}`];
    const childrenDiv = document.createElement('div');
    childrenDiv.className = 'tree-children' + (shouldExpand ? ' expanded' : '');
    if (shouldExpand) node.querySelector('.tree-toggle').textContent = '▼';
    if (order.families) {
        order.families.forEach(family => {
            const familyLi = renderFamilyNode(family, order.order_sci);
            if (familyLi) childrenDiv.appendChild(familyLi);
        });
    }
    node.onclick = (e) => { e.stopPropagation(); toggleNode(node); filterByTaxonomy('order', order.order_cn, order.order_sci); };
    li.appendChild(node);
    li.appendChild(childrenDiv);
    return li;
}

function renderFamilyNode(family, orderSci) {
    if (family.photo_count === 0 && !TREE_CONFIG.includeEmptyNodes) return null;
    const li = document.createElement('li');
    li.style.marginBottom = '2px';
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.dataset.type = 'family';
    node.dataset.value = family.family_cn;
    node.dataset.sci = family.family_sci;
    node.innerHTML = `<span class="tree-toggle">▶</span>${family.family_cn}<span class="node-count">(${family.photo_count})</span>`;
    const shouldExpand = expandState[`family_${family.family_cn}`];
    const childrenDiv = document.createElement('div');
    childrenDiv.className = 'tree-children' + (shouldExpand ? ' expanded' : '');
    if (shouldExpand) node.querySelector('.tree-toggle').textContent = '▼';
    if (family.genera) {
        family.genera.forEach(genus => {
            const genusLi = renderGenusNode(genus, orderSci, family.family_sci);
            if (genusLi) childrenDiv.appendChild(genusLi);
        });
    }
    node.onclick = (e) => { e.stopPropagation(); toggleNode(node); filterByTaxonomy('family', family.family_cn, orderSci, family.family_sci); };
    li.appendChild(node);
    li.appendChild(childrenDiv);
    return li;
}

function renderGenusNode(genus, orderSci, familySci) {
    if (genus.photo_count === 0 && !TREE_CONFIG.includeEmptyNodes) return null;
    const li = document.createElement('li');
    li.style.marginBottom = '2px';
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.dataset.type = 'genus';
    node.dataset.value = genus.genus_cn;
    node.dataset.sci = genus.genus_sci;
    node.innerHTML = `<span class="tree-toggle">▶</span>${genus.genus_cn}<span class="node-count">(${genus.photo_count})</span>`;
    const shouldExpand = expandState[`genus_${genus.genus_cn}`];
    const childrenDiv = document.createElement('div');
    childrenDiv.className = 'tree-children' + (shouldExpand ? ' expanded' : '');
    if (shouldExpand) node.querySelector('.tree-toggle').textContent = '▼';
    if (genus.species) {
        genus.species.forEach(sp => {
            const spLi = renderSpeciesNode(sp, orderSci, familySci, genus.genus_sci);
            if (spLi) childrenDiv.appendChild(spLi);
        });
    }
    node.onclick = (e) => { e.stopPropagation(); toggleNode(node); filterByTaxonomy('genus', genus.genus_cn, orderSci, familySci, genus.genus_sci); };
    li.appendChild(node);
    li.appendChild(childrenDiv);
    return li;
}

function renderSpeciesNode(species, orderSci, familySci, genusSci) {
    if (species.photo_count === 0 && !TREE_CONFIG.includeEmptyNodes) return null;
    const li = document.createElement('li');
    li.style.marginBottom = '2px';
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.dataset.type = 'species';
    node.dataset.value = species.scientific_name;
    node.innerHTML = `<span class="tree-toggle" style="visibility: hidden;">◦</span>${species.chinese_name}<span class="node-count">(${species.photo_count})</span>`;
    node.onclick = (e) => { e.stopPropagation(); highlightNode(node); filterByTaxonomy('species', species.scientific_name, orderSci, familySci, genusSci); };
    li.appendChild(node);
    return li;
}
```

- [ ] **Step 4: Add interaction functions**

```javascript
function toggleNode(node) {
    const children = node.nextElementSibling;
    const toggle = node.querySelector('.tree-toggle');
    if (children && children.classList.contains('tree-children')) {
        const isExpanded = children.classList.toggle('expanded');
        toggle.textContent = isExpanded ? '▼' : '▶';
        const type = node.dataset.type;
        const value = node.dataset.value;
        if (type && value) {
            expandState[`${type}_${value}`] = isExpanded;
            if (TREE_CONFIG.rememberExpandState) saveExpandState();
        }
    }
}

function highlightNode(node) {
    document.querySelectorAll('.tree-node.active').forEach(n => n.classList.remove('active'));
    node.classList.add('active');
}

function filterByTaxonomy(type, value, orderSci, familySci, genusSci) {
    currentTaxonomyFilter = { type, value, orderSci, familySci, genusSci };
    const outingId = new URLSearchParams(window.location.search).get('outing_id') || '';
    let url = '/api/photos/by_taxonomy?';
    if (orderSci) url += `order_sci=${encodeURIComponent(orderSci)}&`;
    if (familySci) url += `family_sci=${encodeURIComponent(familySci)}&`;
    if (genusSci) url += `genus_sci=${encodeURIComponent(genusSci)}&`;
    if (type === 'species') url += `scientific_name=${encodeURIComponent(value)}&`;
    if (outingId) url += `outing_id=${outingId}&`;
    url += `limit=${currentLimit || 50}&offset=0`;
    updatePhotoGrid(url);
}

function updatePhotoGrid(url) {
    const container = document.getElementById('photo-gallery-container');
    if (!container) return;
    container.innerHTML = '<div class="col-12 text-center py-5"><div class="spinner-border" role="status"></div></div>';
    fetch(url)
        .then(r => r.json())
        .then(data => {
            renderPhotos(data.photos);
            updateStatus(data);
        })
        .catch(err => {
            container.innerHTML = '<div class="col-12 text-center text-danger py-5">加载失败</div>';
        });
}

function renderPhotos(photos) {
    const container = document.getElementById('photo-gallery-container');
    if (!container) return;
    container.innerHTML = '';
    if (!photos || photos.length === 0) {
        container.innerHTML = '<div class="col-12 text-center text-muted py-5">暂无照片</div>';
        return;
    }
    // Update galleryPhotos for detail modal
    galleryPhotos.length = 0;
    photos.forEach(p => galleryPhotos.push(p));
    photos.forEach(photo => {
        const isUncertain = photo.primary_bird_cn === '待确认鸟种' || photo.scientific_name === 'Uncertain';
        const processedPath = photo.web_processed_path || '';
        const rawPath = photo.web_raw_path || '';
        const card = document.createElement('div');
        card.className = 'photo-card';
        card.id = `photo-card-${photo.id}`;
        card.innerHTML = `
            <div class="card h-100 shadow-sm ${isUncertain ? 'status-uncertain' : ''}" onclick="openPhotoDetail(${photo.id})" style="cursor: pointer;">
                <div class="position-relative">
                    <div class="btn-group btn-group-sm position-absolute top-0 start-0 m-1" style="z-index: 10;" onclick="event.stopPropagation();">
                        ${processedPath ? `<a href="${processedPath}" download class="btn btn-dark btn-sm">裁切</a>` : ''}
                        ${rawPath ? `<a href="${rawPath}" download class="btn btn-dark btn-sm">原图</a>` : ''}
                    </div>
                    <img src="${processedPath || rawPath}" class="card-img-top" alt="${photo.primary_bird_cn}" loading="lazy">
                </div>
                <div class="card-body">
                    <h5 class="card-title">${photo.primary_bird_cn || ''}${isUncertain ? '<span class="badge badge-uncertain small align-top">?</span>' : ''}</h5>
                    <h6 class="card-subtitle mb-2 text-muted fst-italic">${photo.scientific_name || ''}</h6>
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="location-tag">📍 ${photo.location_tag || ''}</span>
                        <span class="badge bg-light text-dark border">${((photo.confidence_score || 0) * 100)|int}%</span>
                    </div>
                    <div class="path-info" title="${photo.filename || ''}">📁 ${photo.filename || ''}</div>
                    ${photo.quality_score ? `<div class="mt-2"><span class="badge bg-info text-dark">画质 ${photo.quality_score|int}</span></div>` : ''}
                </div>
                <div class="card-footer text-muted small">${photo.captured_date || ''}</div>
            </div>`;
        container.appendChild(card);
    });
}

function updateStatus(data) {
    // Update status bar with new count
    const statusEl = document.querySelector('.status-bar span');
    if (statusEl && data.total_count !== undefined) {
        const filterText = currentTaxonomyFilter ? ` | 分类筛选：${currentTaxonomyFilter.value}` : '';
        statusEl.textContent = `显示 1-${Math.min(data.limit, data.total_count)} / 共 ${data.total_count} 张${filterText}`;
    }
}

function expandAll() {
    document.querySelectorAll('.tree-children').forEach(el => el.classList.add('expanded'));
    document.querySelectorAll('.tree-toggle').forEach(el => { if (el.textContent === '▶') el.textContent = '▼'; });
    document.querySelectorAll('.tree-node[data-type]').forEach(node => {
        expandState[`${node.dataset.type}_${node.dataset.value}`] = true;
    });
    if (TREE_CONFIG.rememberExpandState) saveExpandState();
}

function collapseAll() {
    document.querySelectorAll('.tree-children').forEach(el => el.classList.remove('expanded'));
    document.querySelectorAll('.tree-toggle').forEach(el => { if (el.textContent === '▼') el.textContent = '▶'; });
    expandState = {};
    if (TREE_CONFIG.rememberExpandState) saveExpandState();
}

function clearTaxonomyFilter() {
    currentTaxonomyFilter = null;
    document.querySelectorAll('.tree-node.active').forEach(n => n.classList.remove('active'));
    const infoPanel = document.getElementById('taxonomy-info');
    if (infoPanel) infoPanel.style.display = 'none';
    // Reload with current outing filter if any
    const outingId = new URLSearchParams(window.location.search).get('outing_id');
    window.location.href = outingId ? `/gallery?outing_id=${outingId}` : '/gallery';
}
```

- [ ] **Step 5: Add event listeners and initialization**

```javascript
// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    loadExpandState();
    loadTaxonomyTree();

    // Tree control buttons
    document.getElementById('expand-all-btn')?.addEventListener('click', expandAll);
    document.getElementById('collapse-all-btn')?.addEventListener('click', collapseAll);
    document.getElementById('reset-tree-btn')?.addEventListener('click', clearTaxonomyFilter);
});
```

- [ ] **Step 6: Commit**

```bash
git add src/web/templates/gallery.html
git commit -m "功能: 图库页面新增分类树JS逻辑和AJAX过滤"
```

---

## Task 7: Add OutingRepository.get_all_outings method

**Files:**
- Modify: `src/db/repository.py`

**Interfaces:**
- Produces: `OutingRepository.get_all_outings()` → `List[Outing]`

- [ ] **Step 1: Add method to OutingRepository**

```python
# src/db/repository.py - 在 OutingRepository 类中添加
def get_all_outings(self) -> List[Outing]:
    """获取所有外拍，按日期倒序"""
    return self.session.query(Outing).order_by(Outing.start_date.desc(), Outing.created_at.desc()).all()
```

- [ ] **Step 2: Commit**

```bash
git add src/db/repository.py
git commit -m "功能: OutingRepository 新增 get_all_outings 方法"
```

---

## Task 8: Integration test

**Files:**
- Modify: `tests/test_api_outings.py`

**Interfaces:**
- Tests full flow: gallery page loads → taxonomy tree renders → AJAX filter works

- [ ] **Step 1: Add integration test**

```python
# tests/test_api_outings.py (append)
def test_gallery_with_taxonomy_tree_and_outing():
    client = TestClient(app)
    # Test gallery page loads with outings data
    response = client.get("/gallery")
    assert response.status_code == 200
    assert "物种分类" in response.text  # Sidebar present
    assert "外拍" in response.text  # Outing dropdown present

    # Test taxonomy tree API
    response = client.get("/api/taxonomy/tree")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    # Test photos by taxonomy API
    response = client.get("/api/photos/by_taxonomy")
    assert response.status_code == 200
    data = response.json()
    assert "photos" in data

    # Test outings API
    response = client.get("/api/outings")
    assert response.status_code == 200
    data = response.json()
    assert "outings" in data
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_outings.py
git commit -m "测试: 图库分类树和外拍筛选集成测试"
```

---

## Task 9: Manual verification

- [ ] **Step 1: Start the web server**

Run: `python src/web/app.py`

- [ ] **Step 2: Open browser to http://localhost:8000/gallery**

- [ ] **Step 3: Verify the following:**
  - [ ] Left sidebar shows taxonomy tree with expand/collapse arrows
  - [ ] Clicking tree nodes filters photos via AJAX (no page reload)
  - [ ] Outing dropdown shows all outings with photo counts
  - [ ] Selecting an outing reloads page and updates tree + photos
  - [ ] Expand/collapse state persists in localStorage
  - [ ] Reset button clears taxonomy filter
  - [ ] Location filters (province/city/park) still work
  - [ ] Date range filter still works
  - [ ] Search filter still works
  - [ ] Pagination works with taxonomy filter active

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "完成: 图库分类树侧边栏和外拍筛选功能"
```

# 选片页面时间排序与跨组导航实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现选片页面照片按时间升序排列，并支持大图预览跨组导航

**Architecture:** 修改后端排序逻辑和分组聚合方式，调整大图预览导航逻辑，前端保持现有交互

**Tech Stack:** Python/FastAPI, Jinja2模板, JavaScript

## Global Constraints

- Python 3.11+
- FastAPI
- SQLAlchemy ORM
- 现有测试框架 pytest
- 保持现有代码风格和命名约定

---

### Task 1: 修改后端查询排序为升序

**Files:**
- Modify: `src/web/app.py:831`

**Interfaces:**
- Consumes: Photo 模型
- Produces: 排序后的 photos 查询结果

- [ ] **Step 1: 修改 select_page 函数中的查询排序**

```python
# 当前代码（第831行）
photos = query.order_by(Photo.captured_date.desc(), Photo.id.desc()).limit(500).all()

# 修改为
photos = query.order_by(Photo.captured_date.asc(), Photo.id.asc()).limit(500).all()
```

- [ ] **Step 2: 运行测试验证**

Run: `python -m pytest tests/ -v -k select`
Expected: 测试通过或无相关测试失败

- [ ] **Step 3: 提交更改**

```bash
git add src/web/app.py
git commit -m "fix: 选片页面查询排序改为时间升序"
```

---

### Task 2: 实现无分组照片的时间聚合

**Files:**
- Modify: `src/web/app.py:834-915`

**Interfaces:**
- Consumes: photos 查询结果（已按时间升序）
- Produces: display_groups 列表（统一的分组结构）

- [ ] **Step 1: 创建时间聚合函数**

```python
def _aggregate_ungrouped_photos(ungrouped_photos: list, threshold_minutes: int = 2) -> list:
    """将无分组照片按时间间隔聚合为虚拟组
    
    Args:
        ungrouped_photos: 无分组照片列表（已按captured_at升序）
        threshold_minutes: 时间间隔阈值（分钟）
    
    Returns:
        虚拟组列表，每个元素是照片列表
    """
    if not ungrouped_photos:
        return []
    
    groups = []
    current_group = [ungrouped_photos[0]]
    
    for i in range(1, len(ungrouped_photos)):
        prev_photo = ungrouped_photos[i - 1]
        curr_photo = ungrouped_photos[i]
        
        # 计算时间间隔
        if prev_photo.captured_at and curr_photo.captured_at:
            time_diff = (curr_photo.captured_at - prev_photo.captured_at).total_seconds() / 60
        else:
            time_diff = float('inf')
        
        if time_diff <= threshold_minutes:
            current_group.append(curr_photo)
        else:
            groups.append(current_group)
            current_group = [curr_photo]
    
    groups.append(current_group)
    return groups
```

- [ ] **Step 2: 修改 select_page 函数中的分组逻辑**

```python
# 当前代码（第834-915行）分别处理 grouped 和 ungrouped
# 修改为统一处理

# 导入 datetime（如未导入）
from datetime import datetime

# 将无分组照片按 captured_at 排序
ungrouped_sorted = []
for photos_list in ungrouped.values():
    ungrouped_sorted.extend(photos_list)
ungrouped_sorted.sort(key=lambda p: (p.captured_at or datetime.min, p.id))

# 聚合无分组照片为虚拟组
virtual_groups = _aggregate_ungrouped_photos(ungrouped_sorted)

# 构建 display_groups
display_groups = []
gid = 1

# 渲染连拍组（按组内最早照片时间升序）
group_ids = sorted(grouped.keys(), key=lambda gid: min(
    (p.captured_at for p in grouped[gid] if p.captured_at),
    default=datetime.min
))
for group_id in group_ids:
    group_photos = grouped[group_id]
    best = max(group_photos, key=lambda p: (p.quality_score or 0, p.id))
    members = sorted(group_photos, key=lambda p: (p.captured_at or p.id, p.id))
    display_groups.append({
        "id": gid,
        "type": "burst",
        "group_id": group_id,
        "date": best.captured_date or "未知日期",
        "best_photo_id": best.id,
        "photo_count": len(members),
        "primary_bird_cn": best.primary_bird_cn,
        "scientific_name": best.scientific_name,
        "quality_score": best.quality_score or 0,
        "is_selected": best.is_selected or False,
        "is_rejected": best.rating == -1,
        "web_processed_path": resolve_processed_web_path(best.file_path) if best.file_path else None,
        "web_raw_path": resolve_web_path(best.original_path) if best.original_path else None,
        "photos": [
            {
                "id": p.id,
                "primary_bird_cn": p.primary_bird_cn,
                "scientific_name": p.scientific_name,
                "location_tag": p.location_tag,
                "captured_date": p.captured_date,
                "quality_score": p.quality_score or 0,
                "is_selected": p.is_selected or False,
                "is_rejected": p.rating == -1,
                "web_processed_path": resolve_processed_web_path(p.file_path) if p.file_path else None,
                "web_raw_path": resolve_web_path(p.original_path) if p.original_path else None,
            }
            for p in members
        ],
    })
    gid += 1

# 渲染虚拟组（按最早照片时间升序）
for group_photos in virtual_groups:
    best = group_photos[0]  # 虚拟组中第一张作为代表
    members = sorted(group_photos, key=lambda p: (p.captured_at or p.id, p.id))
    display_groups.append({
        "id": gid,
        "type": "single",
        "group_id": 0,
        "date": best.captured_date or "未知日期",
        "best_photo_id": 0,
        "photo_count": len(members),
        "primary_bird_cn": best.primary_bird_cn,
        "scientific_name": best.scientific_name,
        "quality_score": best.quality_score or 0,
        "is_selected": best.is_selected or False,
        "is_rejected": best.rating == -1,
        "web_processed_path": resolve_processed_web_path(best.file_path) if best.file_path else None,
        "web_raw_path": resolve_web_path(best.original_path) if best.original_path else None,
        "photos": [
            {
                "id": p.id,
                "primary_bird_cn": p.primary_bird_cn,
                "scientific_name": p.scientific_name,
                "location_tag": p.location_tag,
                "captured_date": p.captured_date,
                "quality_score": p.quality_score or 0,
                "is_selected": p.is_selected or False,
                "is_rejected": p.rating == -1,
                "web_processed_path": resolve_processed_web_path(p.file_path) if p.file_path else None,
                "web_raw_path": resolve_web_path(p.original_path) if p.original_path else None,
            }
            for p in members
        ],
    })
    gid += 1
```

- [ ] **Step 3: 运行测试验证**

Run: `python -m pytest tests/ -v -k select`
Expected: 测试通过或无相关测试失败

- [ ] **Step 4: 提交更改**

```bash
git add src/web/app.py
git commit -m "feat: 选片页面无分组照片按时间间隔聚合为虚拟组"
```

---

### Task 3: 修改大图预览导航逻辑

**Files:**
- Modify: `src/web/app.py:1280-1305`

**Interfaces:**
- Consumes: photo 对象
- Produces: (prev_photo_id, next_photo_id) 元组

- [ ] **Step 1: 创建全局照片序列函数**

```python
def _get_all_photo_ids_ordered(session) -> list[int]:
    """获取所有照片ID的全局序列（按时间升序）"""
    all_photos = (
        session.query(Photo.id)
        .order_by(Photo.captured_date.asc(), Photo.id.asc())
        .all()
    )
    return [row[0] for row in all_photos]
```

- [ ] **Step 2: 修改 _get_review_neighbors 函数**

```python
def _get_review_neighbors(session, photo: Photo) -> tuple[Optional[int], Optional[int]]:
    """返回该照片在整个序列中的前后照片ID"""
    all_ids = _get_all_photo_ids_ordered(session)
    if not all_ids:
        return None, None
    
    try:
        idx = all_ids.index(photo.id)
    except ValueError:
        return None, None
    
    prev_id = all_ids[idx - 1] if idx > 0 else None
    next_id = all_ids[idx + 1] if idx < len(all_ids) - 1 else None
    return prev_id, next_id
```

- [ ] **Step 3: 运行测试验证**

Run: `python -m pytest tests/ -v -k review`
Expected: 测试通过或无相关测试失败

- [ ] **Step 4: 提交更改**

```bash
git add src/web/app.py
git commit -m "feat: 大图预览支持跨组导航"
```

---

### Task 4: 更新前端分组显示

**Files:**
- Modify: `src/web/templates/select.html:168-180`

**Interfaces:**
- Consumes: groups 数据（已按时间升序）
- Produces: 分组标题显示

- [ ] **Step 1: 修改分组标题显示逻辑**

```html
<!-- 当前代码（第168-180行）-->
<div class="group-header d-flex justify-content-between align-items-center" data-group-index="{{ global_group_index }}">
    <span>
        {% if group.type == 'burst' %}📦 连拍组{% else %}🖼️ 照片{% endif %} #{{ group.id }}
        · {{ group.date }}
        · {{ group.photo_count }} 张
        {% if group.type == 'burst' %}
        <span class="badge bg-info text-white ms-1">连拍</span>
        {% endif %}
    </span>
    {% if group.type == 'burst' %}
    <button class="btn btn-sm btn-outline-primary" onclick="pickBest({{ group.group_id }})">选最佳</button>
    {% endif %}
</div>

<!-- 修改为：显示最早拍摄时间 -->
<div class="group-header d-flex justify-content-between align-items-center" data-group-index="{{ global_group_index }}">
    <span>
        {% if group.type == 'burst' %}📦 连拍组{% else %}🖼️ 照片{% endif %} #{{ group.id }}
        · {{ group.date }}
        · {{ group.photo_count }} 张
        {% if group.type == 'burst' %}
        <span class="badge bg-info text-white ms-1">连拍</span>
        {% endif %}
    </span>
    {% if group.type == 'burst' %}
    <button class="btn btn-sm btn-outline-primary" onclick="pickBest({{ group.group_id }})">选最佳</button>
    {% endif %}
</div>
```

注意：此任务的代码与当前代码相同，因为分组标题显示逻辑不需要修改。实际修改在后端 Task 2 中完成，分组数据已按时间升序排列。

- [ ] **Step 2: 运行测试验证**

Run: `python -m pytest tests/ -v -k select`
Expected: 测试通过或无相关测试失败

- [ ] **Step 3: 提交更改**

```bash
git add src/web/templates/select.html
git commit -m "fix: 选片页面分组标题显示最早拍摄时间"
```

---

### Task 5: 运行完整测试套件

**Files:**
- N/A

**Interfaces:**
- N/A

- [ ] **Step 1: 运行完整测试**

Run: `python -m pytest tests/ -v`
Expected: 所有测试通过

- [ ] **Step 2: 检查测试覆盖率**

Run: `python -m pytest tests/ --cov=src --cov-report=term-missing`
Expected: 覆盖率无显著下降

- [ ] **Step 3: 提交最终更改**

```bash
git add .
git commit -m "chore: 完成选片页面时间排序与跨组导航功能"
```

---

### Task 6: 手动验证功能

**Files:**
- N/A

**Interfaces:**
- N/A

- [ ] **Step 1: 启动应用**

Run: `python src/web/app.py`
Expected: 应用正常启动

- [ ] **Step 2: 访问选片页面**

1. 打开浏览器访问 http://localhost:8000/select
2. 验证照片按时间从早到晚排列
3. 验证无分组照片按时间间隔聚合显示

- [ ] **Step 3: 测试大图预览导航**

1. 点击任意照片打开大图预览
2. 使用左右箭头按钮或键盘←/→键切换照片
3. 验证可跨组切换照片
4. 验证到达序列首/尾时导航按钮正确禁用

- [ ] **Step 4: 测试现有功能**

1. 测试选中/淘汰按钮功能
2. 测试标签和备注功能
3. 测试鸟种修正功能
4. 验证所有功能正常工作

---

## 执行选项

**Plan complete and saved to `docs/superpowers/plans/2026-08-30-select-page-time-sort-and-cross-group-navigation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
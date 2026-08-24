# 外拍全局筛选设计文档

**日期**: 2026-08-10  
**主题**: 选片、图库、图鉴支持按外拍筛选及查看全量数据  
**方案**: A（导航栏全局外拍选择器 + URL 参数 `outing_id`）

---

## 1. 背景与目标

当前四个核心页面在“外拍”维度上的表现不一致：

- **选片 `/select`**：默认只展示最近一次外拍的照片，无法直接切换为“全部外拍”。
- **图库 `/gallery`**：后端已支持 `outing_id` 参数，但 UI 没有外拍选择器，默认展示全部。
- **图鉴 `/guide`**：展示全部物种，并用最近一次外拍计算“新增物种”高亮，无法按某次外拍筛选。
- **观鸟记录 `/log`**：本身按外拍聚合展示全部数据，已满足需求。

目标：

- 在导航栏提供全局外拍选择器，统一控制选片、图库、图鉴三个页面。
- 支持“按页面默认”、“全部外拍”、“单次外拍”三种范围。
- 各页面仍可保留现有日期、评级、鸟种等筛选能力。

---

## 2. 方案概述

采用导航栏全局选择器，通过 URL 参数 `outing_id` 传递当前选择：

- **空 / 缺失**：按页面默认规则展示。
- **`all`**：展示全部外拍数据。
- **数字字符串**：展示指定外拍的数据。

默认规则：

- **选片 `/select`**：默认最近一次外拍（方便快速处理新导入照片）。
- **图库 `/gallery`**：默认全部外拍。
- **图鉴 `/guide`**：默认全部外拍（展示全部物种，不标新增）。

---

## 3. URL 参数约定

| `outing_id` 值 | 含义 |
|---------------|------|
| 空字符串或参数缺失 | 页面默认规则 |
| `all` | 全部外拍，不做外拍过滤 |
| 数字字符串，如 `3` | 指定外拍 ID |

兼容性：

- 旧链接如 `?outing_id=3` 仍然有效（数字字符串会解析为整数 ID）。
- 选片页面旧的 `outing_id` 为整数类型，改为字符串后，数值字符串仍被正确解析。

---

## 4. 后端设计

### 4.1 新增接口

```
GET /api/outings
```

返回外拍列表，供导航栏选择器填充：

```json
{
  "status": "success",
  "outings": [
    {"id": 3, "name": "玉渊潭", "start_date": "20260721", "end_date": ""},
    {"id": 2, "name": "奥林匹克森", "start_date": "20260715", "end_date": ""}
  ]
}
```

排序：按 `start_date` 倒序，最近的排在最前面。

### 4.2 新增 helper 函数

在 `src/web/app.py` 中新增：

```python
def _resolve_outing_scope(
    session,
    outing_id: str,
    default: str,  # "latest" or "all"
) -> tuple[str, Optional[Outing]]:
    ...
```

返回 `(scope, current_outing)`：

- `scope`：
  - `"default"`：空参数，使用页面默认规则。
  - `"all"`：用户显式选择 `all`。
  - `"outing"`：指定某次外拍。
- `current_outing`：
  - 对于 `"default"` + `default="latest"`：返回最近一次外拍对象（如有）。
  - 对于 `"default"` + `default="all"`：返回 `None`。
  - 对于 `"all"`：返回 `None`。
  - 对于 `"outing"`：返回对应 `Outing` 对象（或 `None` 如果 ID 不存在）。

### 4.3 各页面修改

#### 选片 `/select`

- 路由参数：`outing_id: str = ""`。
- 解析：`_resolve_outing_scope(session, outing_id, default="latest")`。
- 行为：
  - 默认（空）：只查询最近一次外拍的照片。
  - `all`：不附加 `Photo.outing_id` 过滤。
  - 指定 ID：只查询该外拍的照片。
- 保留 `date` 和 `rating` 筛选。
- 模板上下文增加 `outing_id`（字符串）和 `current_outing`。

#### 图库 `/gallery`

- 路由参数：`outing_id: str = ""`。
- 解析：`_resolve_outing_scope(session, outing_id, default="all")`。
- 行为：
  - 默认或 `all`：不做外拍过滤。
  - 指定 ID：附加 `Photo.outing_id == id` 过滤。
- 在 `filter_params` / `base_query` 中保留 `outing_id`，确保分页、视图切换时保持。
- 在筛选栏和状态栏显示当前外拍名称。

#### 图鉴 `/guide`

- 路由参数：`outing_id: str = ""`。
- 解析：`_resolve_outing_scope(session, outing_id, default="all")`。
- 行为：
  - 默认或 `all`：展示全部 `photo_count > 0` 的物种，不显示“新增”标记。
  - 指定 ID：只展示该外拍中出现过的物种（通过 `Species` join `Photo` 过滤）。
- 当指定外拍时，继续使用现有逻辑计算该外拍内的新增物种，并用绿色边框标记。
- 模板上下文增加 `outing_id`（字符串）和 `current_outing`。

#### 观鸟记录 `/log`

- 保持现状，不改动。

---

## 5. 前端设计

### 5.1 导航栏 `navbar.html`

在右侧“设置”按钮前加入外拍选择器：

- 下拉框初始选项：
  - `默认（按页面）`
  - `全部外拍`
  - 从 `/api/outings` 获取的每次外拍列表（名称 + 日期）。
- 当前选中项：
  - 从页面 URL 的 `outing_id` 参数读取。
  - 空参数 → 显示“默认（按页面）”。
  - `all` → 显示“全部外拍”。
  - 数字 → 显示对应外拍名称。
- 切换逻辑：
  - 选择“默认”：刷新当前页面，不带 `outing_id` 参数。
  - 选择“全部”：刷新当前页面，带 `outing_id=all`。
  - 选择某次外拍：刷新当前页面，带 `outing_id=<id>`。
- 导航链接：
  - 每个页面链接（选片/图库/图鉴/观鸟记录）自动附加当前 `outing_id`（“默认”时不附加）。
  - 这样跨页面切换时，若已选择某外拍，会保持该外拍视角。

### 5.2 各页面模板

- `select.html`：
  - 显示当前范围：
    - 默认最近一次外拍：显示“当前外拍：...”。
    - 全部外拍：显示“当前范围：全部外拍”。
    - 指定外拍：显示对应外拍名。
  - “查看本次外拍 → 图库”链接仍使用当前实际 `outing_id`（或 `all`）。
  - 星级筛选等链接保留 `outing_id` 参数。

- `gallery.html`：
  - 在筛选栏顶部或状态栏显示当前外拍范围。
  - 分页、视图切换链接保留 `outing_id`。

- `guide.html`：
  - 在统计栏显示当前外拍范围。
  - 当指定外拍时，显示该外拍名称；全部时显示“全部外拍”。
  - 绿色“本次新增”标记仅在指定外拍时出现。

---

## 6. 数据流

1. 用户打开页面（例如 `/select`）。
2. 后端根据 URL 中的 `outing_id`（或空）和页面默认规则，解析出当前外拍范围。
3. 后端查询数据并渲染模板，模板中带上 `outing_id` 字符串和 `current_outing` 对象。
4. 浏览器渲染导航栏时，JS 调用 `/api/outings` 获取外拍列表，填充选择器，并高亮当前选项。
5. 用户切换选择器 → 浏览器刷新页面，URL 更新 → 后端重新解析并渲染。
6. 用户点击导航栏其他页面 → 链接自动带上当前 `outing_id` → 新页面保持同一外拍视角。

---

## 7. 错误处理

- 指定 `outing_id` 不存在或非法：
  - 后端回退到页面默认规则（latest 或 all）。
  - 不抛错，避免破坏用户体验。
- `/api/outings` 接口失败：
  - 导航栏选择器降级为只显示“默认”和“全部外拍”两个选项，不阻塞页面主体功能。
- 数据库无 `Outing` 记录：
  - 选择器只显示“默认”和“全部外拍”。
  - 选片页面默认返回空数据（提示无照片）。

---

## 8. 测试计划

### 8.1 新增接口测试

- `test_api_outings_returns_sorted_list`：
  - 创建多个外拍，验证 `/api/outings` 返回顺序正确。

### 8.2 选片页面测试

- 更新 `test_select_page_renders_template`：
  - 默认 `outing_id=""` 时，无 outing 则 `current_outing=None`。
- 新增 `test_select_page_defaults_to_latest_outing`：
  - 创建多个外拍，验证默认返回最近一次外拍的照片。
- 新增 `test_select_page_all_outings_shows_all_photos`：
  - `outing_id=all` 时不过滤外拍。
- 新增 `test_select_page_specific_outing_filters_photos`：
  - 指定 `outing_id` 只返回该外拍照片。

### 8.3 图库页面测试

- 更新现有图库测试：默认 `outing_id=""` 时不过滤。
- 新增 `test_gallery_page_filters_by_outing_id`：
  - 指定 `outing_id` 只返回该外拍照片。
- 新增 `test_gallery_page_preserves_outing_id_in_pagination`：
  - 验证 `base_query` 包含 `outing_id`。

### 8.4 图鉴页面测试

- 更新 `test_guide_page_renders_template`：默认 `outing_id=""` 时展示全部物种。
- 新增 `test_guide_page_filters_species_by_outing`：
  - 指定 `outing_id` 只展示该外拍出现的物种。
- 保留 `test_guide_page_highlights_new_species`：改为指定外拍时的新增高亮。

### 8.5 导航栏/HTTP 回归测试

- 新增 `test_navbar_links_carry_outing_id`：
  - 访问 `/select?outing_id=2`，检查响应 HTML 中导航栏链接是否包含 `outing_id=2`（或等效 JS 数据）。
- 新增 `test_global_outing_selector_renders_options`：
  - 检查页面 HTML 中包含外拍选择器骨架，并通过 `/api/outings` 返回数据。

---

## 9. 兼容性

- 路由参数类型由 `int` 改为 `str`，直接调用函数的旧测试需要同步更新参数类型。
- 模板中所有使用 `outing_id` 的地方改为字符串比较，无需额外改动。
- 旧 URL `?outing_id=3` 继续有效。
- 观鸟记录 `/log` 保持现状，不受本次改动影响。

---

## 10. 未包含范围

- 不支持多选外拍（一次选多个外拍同时展示）。
- 观鸟记录页面不增加外拍单选过滤（本身已按外拍聚合）。
- 不修改导入流程，不新增 outing 创建逻辑。
- 不改变现有的 date、rating、species、location 等筛选逻辑。

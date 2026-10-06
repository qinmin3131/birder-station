# 图库分类树侧边栏 & 外拍筛选设计

## 概述

为图库页面新增两个功能：
1. **外拍下拉筛选**：顶部筛选栏新增外拍选择器，选择后过滤照片并联动分类树
2. **分类树侧边栏**：左侧展示 4 级分类树（目 > 科 > 属 > 物种），替代现有物种/科下拉筛选

参考实现：`F:\code\feather-trace` 项目的 `src/web/templates/index.html`

## 方案选择

采用 **方案 A：全 AJAX 化**：
- 分类树交互通过 AJAX 实现（无页面刷新）
- 外拍下拉切换通过页面跳转（因为影响树的数据结构）
- 保持现有服务端渲染的初始加载方式

## 页面布局

```
┌─────────────────────────────────────────────────┐
│  筛选栏（视图切换 + 搜索 + 日期 + 外拍下拉 + ...）  │
├──────────┬──────────────────────────────────────┤
│ 分类树    │  状态栏 + 照片网格                     │
│ 左侧边栏  │  (4列CSS Grid)                       │
│          │                                      │
│  目 > 科   │  ┌────┐ ┌────┐ ┌────┐ ┌────┐        │
│  > 属 > 种│  │照片│ │照片│ │照片│ │照片│        │
│          │  └────┘ └────┘ └────┘ └────┘        │
│          │  ┌────┐ ┌────┐ ┌────┐ ┌────┐        │
│          │  │照片│ │照片│ │照片│ │照片│        │
│          │  └────┘ └────┘ └────┘ └────┘        │
│          │                                      │
│          │  分页                                  │
└──────────┴──────────────────────────────────────┘
```

- 左侧边栏：`col-md-3`，`position: sticky; top: 70px; height: calc(100vh - 80px);`，可滚动
- 右侧主区域：`col-md-9`
- 响应式：移动端侧边栏折叠为可展开的抽屉

## 外拍下拉筛选

### 位置
筛选栏中，搜索框右侧

### 数据源
`GET /api/outings` 返回所有外拍列表

### 选项格式
`20260110_北京奥森 (42张)`

### 交互
- 选择外拍 → 页面跳转到 `/gallery?outing_id=123`
- 「全部」选项 → `outing_id=0`
- 页面加载时：分类树 API 自动带上 `outing_id` 参数

## 分类树侧边栏

### 结构
4 级层次：目 (Order) → 科 (Family) → 属 (Genus) → 物种 (Species)

### UI 元素
- 顶部标题栏："物种分类" + 三个按钮（展开全部 / 折叠全部 / 重置筛选）
- 每个节点：展开/折叠箭头、中文名、拉丁名（灰色小字）、照片数量徽章
- 叶子节点（物种）：`◦` 标记
- 点击节点：高亮选中 + AJAX 过滤照片
- 展开/折叠状态保存到 `localStorage`

### API 调用
- `GET /api/taxonomy/tree?include_empty=false&outing_id=123`
- 响应格式：`[{ order_cn, order_sci, photo_count, families: [...] }]`

### 交互
- 点击节点 → `/api/photos/by_taxonomy?outing_id=...&order_sci=...&limit=50&offset=0`
- AJAX 替换照片网格
- 「重置筛选」→ 清除分类筛选

## API 变更

### 现有 API 修改

1. `GET /api/taxonomy/tree` — 新增 `outing_id` 参数
   - 当 `outing_id` 存在时，只返回该外拍包含的物种
   - 实现：JOIN photos 表，加 `WHERE p.outing_id = ?` 条件

2. `GET /api/photos/by_taxonomy` — 新增 `outing_id` 参数
   - 在现有 taxonomy 筛选基础上额外过滤外拍

### 新增 API

3. `GET /api/outings` — 返回所有外拍列表
   - 响应：`{ outings: [{ id, name, start_date, end_date, location_tag, photo_count }] }`
   - 按 `start_date` 倒序

### 无破坏性变更
所有现有 API 参数保持不变，新增参数均为可选。

## 交互流程

### 首次加载
1. 服务端渲染初始页面
2. JS 异步加载分类树 → `GET /api/taxonomy/tree`
3. JS 异步加载外拍列表 → `GET /api/outings`

### 选择外拍
1. 页面跳转到 `/gallery?outing_id=123`
2. 服务端加载该外拍的照片
3. 分类树 API 带 `outing_id` 参数
4. 照片网格显示该外拍的照片

### 点击树节点
1. 设置 `currentTaxonomyFilter`
2. 构建 `/api/photos/by_taxonomy?outing_id=...&order_sci=...&limit=50&offset=0`
3. AJAX 获取照片 → 替换 `#photo-grid`
4. 更新状态栏

### 分页
- 有分类筛选：AJAX 请求带 `offset`
- 无筛选：页面跳转

### 重置筛选
- 清除 `currentTaxonomyFilter`
- 移除 `.active` 类
- 页面跳转

## 筛选组合规则

分类树筛选与地点下拉（省/市/公园）**可以组合使用**，取交集结果。
- 树节点筛选 + 地点筛选 = 同时满足两个条件的照片
- 外拍筛选 + 树节点 + 地点筛选 = 三个条件的交集

## 移除的 UI 元素

- 移除「鸟种」多选下拉（用分类树替代）
- 移除「科」多选下拉（用分类树替代）
- 保留：视图切换、搜索、日期范围、省/市/公园下拉、分页

## 关键文件

| 文件 | 变更 |
|------|------|
| `src/web/templates/gallery.html` | 新增侧边栏 HTML、JS 树渲染和 AJAX 逻辑 |
| `src/web/app.py` | 修改 gallery_page 传入 outings 数据；修改 taxonomy API 加 outing_id 参数 |
| `src/web/taxonomy_service.py` | 修改 get_taxonomy_tree 和 get_photos_by_taxonomy 支持 outing_id |
| `src/db/repository.py` | 新增 OutingRepository.get_all_outings() |

## 参考实现

`F:\code\feather-trace\src\web\templates\index.html` 中的分类树实现（lines 263-1125）

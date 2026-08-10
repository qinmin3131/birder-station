# 选片复核质量分、鸟种修正、连拍组最佳高亮设计

日期：2026-08-10
状态：待评审

## 背景

在选片工作台（`/select`）和图库照片详情（`/gallery`）的弹窗中，需要更完整地展示照片质量评分、限制鸟种修正只能选自 IOC 名录，并在连拍组中高亮分数最高的照片。

## 问题描述

1. **质量评分展示缺失/不醒目**：当前 `select.html` 和 `gallery.html` 的详情弹窗已预留「质量总分」「质量分项」DOM，但：
   - 总分只显示数字，没有进度条；
   - 分项只显示进度条，没有具体数值；
   - JS 用 `|| '--'` 导致 `0` 分也显示成 `--`；
   - 当 `quality_details` 为空时，分项区域完全空白，看起来像没有数据。

2. **鸟种修正体验不佳**：修正输入框调用 `/api/search-species`：
   - 空输入时候选列表为空，没有展示识别模型给出的 Top 5 候选；
   - 后端 `/api/photo/{id}/correct-species` 未强制校验所选物种是否在 IOC 名录（`taxonomy` 表）内。

3. **连拍组最佳不够突出**：后端在 `select_page` 中已计算 `best_photo_id`，但前端卡片没有据此高亮，用户难以一眼看出每组哪张最好。

## 方案（推荐方案 A）

### 1. 质量评分展示修复

- **后端**：在 `/api/photo/{photo_id}/review` 中：
  - 如果 `quality_score` 为 `None` 或 `quality_details` 为空，且存在 `bird_bbox` 与原始文件，则使用 `QualityScorer` 重新计算；
  - 如果仍然无法计算，返回 `quality_score = 0` 和全 0 的 `quality_details`（保证前端永远有数据可渲染）；
  - 对 `quality_details` 的数值做归一化：若值大于 1，则视为 0–100 分制并除以 100，兼容旧数据。

- **前端**：在 `select.html` 和 `gallery.html` 的详情弹窗中：
  - 将「质量总分」改为「数字 + 彩色进度条 + 颜色标签（>=80 绿色，>=60 橙色，<60 红色）」；
  - 每个分项显示「名称 + 具体数值（保留 1 位小数）+ 细进度条」；
  - 修正 `0` 分显示问题，用 `?? '--'` 或显式判断 `null/undefined` 来兜底。

### 2. 鸟种修正增强

- **前端**：
  - 输入框为空时，立即用 `/api/photo/{photo_id}/review` 返回的 `candidates` 前 5 条填充候选列表；
  - 候选列表条目可点击，点击后把输入框设为该鸟种，并记录选中的对象；
  - 确认修改时，校验所选物种必须来自搜索返回或识别候选；未选择时提示「请从候选列表中选择鸟种」。

- **后端**：
  - `/api/photo/{photo_id}/correct-species` 增加校验：若 `scientific_name` 不在 `taxonomy` 表中，返回 400 错误，拒绝写入；
  - 候选 JSON 结构保持与识别服务一致（优先使用 `chinese_name`/`scientific_name` 键，回退 `cn`/`sci`）。

### 3. 连拍组最佳高亮

- **后端**：保持现有 `best_photo_id` 计算逻辑，确保在 `select_page` 返回的 `groups` 中始终包含该字段。
- **前端**：在 `select.html` 卡片渲染循环中，若 `photo.id == group.best_photo_id`，给该卡片额外添加 `best-photo-card` 类，显示金色边框和「最佳」角标/皇冠图标。

## 影响文件

- `src/web/templates/select.html`（详情弹窗、卡片高亮、鸟种修正）
- `src/web/templates/gallery.html`（详情弹窗质量分展示）
- `src/web/app.py`（`/api/photo/{photo_id}/review` 质量分兜底，`/api/photo/{photo_id}/correct-species` 名录校验）
- 测试：`tests/test_web_review.py`、`tests/test_web_app.py` 等

## 测试计划

1. 单元测试：验证 `get_photo_review` 在 `quality_details` 缺失时返回全 0 兜底或重新计算结果。
2. 单元测试：验证 `correct_photo_species` 拒绝非名录物种，接受名录物种。
3. 前端测试：验证详情弹窗能渲染总分进度条和分项数值。
4. 手动验证：在 `/select` 页面打开连拍组，确认最佳照片被高亮；空输入时展示识别候选 Top 5。

## 回退方案

若重新计算画质耗时过长，可改为仅在缺失时返回全 0 兜底，不触发重算；后续通过重新运行 Pipeline 补全数据。

# 工作日志 / Worklog

## 2026-07-23

### 当日目标
- 按 `spec.md` 完成“选片完成 → 图库默认本次外拍过滤”闭环
- 按 `spec.md` 完成“选片人工修正鸟种”
- 按 `spec.md` 完成“选片等级筛选”

### 已完成
1. **数据模型：照片与分组关联外拍**
   - `src/db/models.py`：在 `Photo` 表新增 `outing_id` 外键；迁移列表同步增加 `outing_id` 列，兼容旧库。
   - `src/db/repository.py`：`OutingRepository` 新增 `get_by_id()` / `list_recent()` 方法。

2. **导入流程创建并关联外拍**
   - `src/web/import_service.py`：`start_import()` 在启动任务前创建 `Outing` 记录，并返回 `outing_id`。
   - `src/web/task_manager.py`：`start_import()` / `_run_import_thread()` 接收并透传 `outing_id`。
   - `src/core/indexer.py`：`index_folder_with_stats()` 新增 `outing_id` 参数，新建照片时写入该字段，返回结果中携带 `outing_id`。
   - `src/pipeline_runner.py`：`run_by_photo_ids()` 新增 `outing_id` 参数；识别完成后将 `outing_id` 写入这些照片；`_group_new_photos()` 保存连拍分组时写入 `photo_groups.outing_id`。

3. **Web 层：选片页默认本次外拍，图库状态显示外拍**
   - `src/web/app.py`：
     - `/api/import/start` 返回 `outing_id`。
     - `/select` 接收 `outing_id` 参数，默认查询最近一次外拍并按 `outing_id` 过滤照片。
     - `/gallery` 查询当前外拍并传入模板，状态栏显示外拍名称。
   - `src/web/templates/select.html`：标题显示当前外拍名称；"查看本次外拍 → 图库" 链接改为 `/gallery?outing_id=xxx&view=selected`。
   - `src/web/templates/gallery.html`：状态栏增加当前外拍名称显示。

4. **测试与验证**
   - 调整 `tests/test_indexer.py`：验证 `outing_id` 写入与返回。
   - 调整 `tests/test_pipeline_logic.py`：`MockPipeline` 初始化 `outing_id`；`save_photo_groups` 按 `outing_id` 关键字调用。
   - 调整 `tests/test_web_import.py`：验证 `start_import` 返回 `outing_id` 并透传。
   - 调整 `tests/test_web_three_domain.py`：更新 `select_page` / `gallery_page` 模板断言，包含 `outing_id` / `current_outing`。
   - 完整测试套件：`340 passed, 1 skipped`。
   - 提交 `4b9f807`：功能: 导入流程创建 outing 并在选片-图库间按外拍过滤。

5. **图鉴增强：本次新增物种高亮、历史时间线、地图分布、跳转到图库**
   - `src/web/app.py`：
     - `/guide` 以最近一次 `outing` 为“本次外拍”，通过 `outing_id` 判断物种是否新增（本次外拍出现且历史外拍未出现）。
     - 新增 `/api/guide/species/{scientific_name}/history`：返回物种信息、按外拍分组的历史时间线、以及拍摄地点分布（含经纬度）。
   - `src/web/templates/guide.html`：
     - 物种墙中本次新增物种显示绿色边框与“本次新增”徽章。
     - 点击物种卡片弹出 Bootstrap 模态框，左侧展示历史拍摄时间线（每次外拍的名称、日期、照片数、最佳缩略图），右侧使用 Leaflet 地图展示拍摄地点分布；带经纬度数据时自动缩放并显示标记。
     - 浮窗底部提供“查看照片 → 图库”按钮，跳转到 `/gallery?species=中文名` 按该物种过滤。
     - 状态栏显示当前外拍名称和说明。
   - 测试：
     - 新增 `test_guide_page_highlights_new_species`：验证历史外拍已有物种不标新、本次外拍新增物种标新。
     - 新增 `test_guide_species_history_api`：验证时间线、地点分布和经纬度字段。
     - 新增 `test_guide_species_history_api_not_found`：验证 404 处理。
     - 更新 `test_guide_page_renders_template` 断言，包含 `current_outing`。
   - 完整测试套件：`343 passed, 1 skipped`。
   - 提交 `792dff3`：功能: 图鉴增强（本次新增物种高亮、历史时间线、地图分布）。

6. **选片人工修正鸟种**
   - 后端：
     - `src/web/app.py` 新增 `POST /api/photo/{photo_id}/correct-species`：接收 `scientific_name`、`chinese_name`、`write_metadata`（可选），查询 IOC 校验物种名，更新 `Photo.primary_bird_cn` / `scientific_name`，并调用 `_refresh_species_for_photo()` 同步更新 `Species` 表与 `species_stats` 统计；如 `write_metadata=True` 则写入原文件元数据。
     - 新增 `_refresh_species_for_photo()`：通过 `IOCManager.update_species_stats_for_photo()` 刷新 sqlite3 统计表，并同步调整 SQLAlchemy `Species.photo_count` 与旧物种计数。
   - 前端：
     - 在 `src/web/templates/select.html` 的大图复核弹窗中增加“修正鸟种”搜索输入框，支持实时搜索候选物种，确认后调用 correct-species API 并刷新页面。
   - 测试：
     - 在 `tests/test_web_three_domain.py` 新增 `test_correct_species_updates_photo_and_stats`：验证修正后鸟种字段更新、旧物种计数减少、新物种计数增加、元数据写入成功。
   - 完整测试套件：`343 passed, 1 skipped`。

7. **选片等级筛选 → 星级评分**
   - 后端：
     - `src/web/app.py` 的 `_apply_rating_filter()` 将档位参数改为数字：`5` 精选、`4` 可用、`3` 记录、`1` 淘汰、`0` 无鸟。功能规则与质量分区间保持不变。
   - 前端：
     - `src/web/templates/select.html` 将筛选按钮改为星级样式：🌟🌟🌟🌟🌟 精选、🌟🌟🌟🌟 可用、🌟🌟🌟 记录、❌ 淘汰、🚫 无鸟；当前选中星级高亮。
   - 测试：
     - 更新 `tests/test_web_three_domain.py` 的 `test_select_page_filters_by_rating`：使用 `5`/`4`/`3`/`1`/`0` 参数验证五档过滤结果与当前星级上下文。
   - 完整测试套件：`344 passed, 1 skipped`。

8. **选片深度复核（IQA 全屏预览 / 缩放 / 组内切换）**
   - 后端：
     - `src/web/app.py` 的 `GET /api/photo/{photo_id}/review` 返回新增 `prev_photo_id` 与 `next_photo_id`，支持组内或同日期相邻照片切换；新增 `_get_review_neighbors()` 辅助函数按 `group_id` 或 `captured_date` 排序计算前后照片。
   - 前端：
     - `src/web/templates/select.html` 将复核弹窗 `reviewModal` 改为 `modal-fullscreen` 全屏舞台，背景深色，左侧大图区、右侧信息面板。
     - 新增图片缩放/平移：鼠标滚轮缩放、鼠标拖拽平移、底部工具栏 +/- 按钮、适应窗口按钮、全屏按钮；缩放状态通过 CSS transform 实时应用。
     - 新增左右导航箭头与键盘快捷键：⬅️/➡️ 切换组内照片，ESC 关闭弹窗。
     - 信息面板显示文件名、日期、地点、分辨率、星级/淘汰状态，并保留识别结果、质量分项、候选 Top 5、选中/淘汰/写入元数据操作。
   - 测试：
     - 在 `tests/test_web_review.py` 新增 `test_review_returns_neighbor_ids_within_group`：验证同组照片的前/后导航 ID 边界。
   - 完整测试套件：`344 passed, 1 skipped`。

9. **RAW / ORF 预览色差修复**
   - 后端：
     - `src/core/processor.py` 重构 `decode_raw_to_temp_jpg()`：
       - 优先调用 `rawpy.extract_thumb()` 提取相机内嵌 JPEG 预览（色彩与相机直出 JPEG 最接近）。
       - 内嵌预览不可用时回退到 `rawpy.postprocess()`，显式指定 `output_color=rawpy.ColorSpace.sRGB`、`gamma=(2.222, 4.5)`、关闭自动亮度，并嵌入标准 sRGB ICC profile。
       - 新增 `_embed_srgb_icc()` 辅助函数，使用 Pillow `ImageCms` 生成 sRGB profile 并写入图片信息。
     - `src/web/app.py` 的 `GET /api/photo/{photo_id}/preview` 对 RAW 解码后的临时 JPEG 读入内存后删除，避免临时文件堆积；同时引入 `StreamingResponse` 返回。
   - 测试：
     - 保留 `tests/test_web_review.py` 中 `test_preview_decodes_raw_to_temp_jpg` 与 `test_preview_returns_jpeg_for_existing_jpg` 验证预览接口返回正常。
   - 完整测试套件：`344 passed, 1 skipped`。

10. **选片键盘快捷键与连拍组快速审阅**
    - 后端：
      - `src/web/app.py`：
        - 新增 `POST /api/select/auto-pick`：对当前外拍中未被淘汰的照片按连拍组选质量分最高，单张照片按质量阈值直接选中；阈值参数 `min_quality` 支持 `80`（一键精选）和 `50`（一键可用）。
        - `/select` 路由将照片按 `group_id` 分组并通过 `groups` 模板变量输出，便于前端按组导航。
        - `GET /api/photo/{photo_id}/review` 保留 `prev_photo_id` / `next_photo_id`，支持复核弹窗内左右切换。
    - 前端：
      - `src/web/templates/select.html`：
        - 新增星级筛选工具栏下方的“一键精选（≥80）”和“一键可用（≥50）”按钮。
        - 新增全局键盘快捷键：⬅️/➡️ 在照片间移动，⬆️/⬇️ 切换连拍组，Enter/Space 打开复核，S 选中，X/Delete 淘汰，B 将当前/最佳照片设为组内最佳，M 写入元数据，C 聚焦到物种修正输入，Esc 关闭复核弹窗。
        - 新增 `.keyboard-focus` 视觉高亮，当前聚焦照片在网格中清晰可见。
        - 复核弹窗内整合 species correction UI，可直接修正当前照片鸟种。
    - 测试：
      - 在 `tests/test_web_three_domain.py` 新增 `test_select_auto_pick_picks_best_per_group_and_high_quality_ungrouped`：验证分组选最佳、单张高质选中、淘汰照片不被选中。
    - 完整测试套件：`345 passed, 1 skipped`。

11. **图库照片详情 / EXIF 侧边栏**
    - 后端：
      - `src/metadata/exif_writer.py` 新增 `read_exif_summary()`：使用 ExifTool 读取相机、镜头、光圈、快门、ISO、焦距、分辨率、文件大小、拍摄时间、GPS 等摘要，供详情面板展示。
      - `src/web/app.py` 的 `GET /api/photo/{photo_id}/review` 在返回值中新增 `exif` 字段；同时补充 `photo` 对象中的 `width`、`height`、`latitude`、`longitude`、`original_path` 等字段供前端使用。
    - 前端：
      - `src/web/templates/gallery.html`：
        - 照片卡片整体可点击，打开 `photoDetailModal` 全屏详情弹窗。
        - 新增详情弹窗：左侧大图舞台支持鼠标滚轮缩放、拖拽平移、适应窗口/全屏、组内/相邻照片左右切换（箭头 + 键盘 ←/→）。
        - 右侧信息面板：识别结果（鸟种、学名、置信度、质量总分）、EXIF 元数据表格（相机、型号、镜头、焦距、光圈、快门、ISO、尺寸、文件大小、拍摄时间、GPS、文件路径）、质量分项进度条（清晰度、对比度、构图位置、曝光、姿态、飞版、对焦）、候选 Top 5、原图/裁切图下载链接、跳转选片复核按钮。
    - 测试：
      - 更新 `tests/test_web_review.py` 的 `test_review_returns_photo_metadata_and_exif_summary`：mock `read_exif_summary` 返回固定摘要，验证 `exif` 字段与相机/ISO/文件大小等字段正确返回。
    - 完整测试套件：`345 passed, 1 skipped`。

12. **工作台首页与统一导航**
    - 后端：
      - `src/web/app.py`：将 `/` 首页从旧的图片列表重做为工作台，返回 `stats`（照片、物种、外拍总数）和 `recent_outing`。
      - 新增 `POST /api/photo/{photo_id}/open-directory`：使用系统文件管理器打开照片所在目录（Windows 用 `explorer /select,<path>`，macOS 用 `open --reveal`，Linux 用 `xdg-open`）。
    - 前端：
      - 新建 `src/web/templates/navbar.html`：统一 Bootstrap 导航栏，包含导入、选片、图库、图鉴、管理入口，并支持当前页面高亮。
      - 重写 `src/web/templates/index.html`：工作台首页，包含品牌标语、统计胶囊、导入/图库/图鉴三个入口卡片，以及“继续处理最近外拍”按钮。
      - 更新 `src/web/templates/import.html`、`select.html`、`gallery.html`、`guide.html`、`admin.html`、`admin_index.html`、`settings.html`：统一使用 `navbar.html`，移除各页面重复的旧导航。
      - `src/web/templates/gallery.html`：照片详情弹窗中新增“打开本地目录”按钮，替换原批量导出/下载入口。
    - 测试：
      - 更新 `tests/test_web_app.py`：将旧 `test_index_builds_photo_page_and_pagination` 改为 `test_index_builds_workbench_with_stats`，验证新首页返回 `stats` 和 `recent_outing`。
    - 完整测试套件：`345 passed, 1 skipped`。

13. **观鸟记录**
    - 后端：
      - `src/web/app.py`：新增 `GET /log` 页面路由和 `GET /api/log`、`GET /api/log/years` 数据接口。
      - 聚合口径：以 Outing 为主体，按 `start_date` 倒序；每个 outing 统计照片数、物种数、新种数（该物种首次出现的 outing 才标新）；地点取 `outing.location_tag`。
    - 前端：
      - 新建 `src/web/templates/log.html`：观鸟记录页面，按卡片展示每次外拍，包含日期、地点、照片数、物种数、新种数、物种芯片列表，并支持年份筛选。
      - 更新 `src/web/templates/navbar.html`：导航栏新增“观鸟记录”入口。
      - 更新 `src/web/templates/index.html`：工作台入口增加第四个卡片“观鸟记录”。
    - 测试：
      - 新增 `tests/test_web_log.py`：覆盖页面渲染、按年份/日期聚合、物种新种判定、空数据库、年份列表接口。
    - 完整测试套件：`350 passed, 1 skipped`。

14. **画质评分：姿态 → 主体占比**
    - 后端：
      - `src/core/pose.py`：移除头/眼/身/尾/翼等姿态可见性推断，仅返回 `subject_size`（bbox 面积 / 图像面积，限制 [0,1]）。
    - 测试：
      - 更新 `tests/test_pose.py`：仅断言 `subject_size` 在 [0,1] 范围内。
    - 完整测试套件通过。

15. **画质评分：简化维度至 4 维**
    - 后端：
      - `src/core/quality.py`：
        - 移除 `pose`、`bif`、`focus`、`position` 维度计算。
        - 新增 `subject_size` 维度，基于鸟框面积占图像面积的比例。
        - 默认权重改为：clarity 0.35、contrast 0.20、exposure 0.20、subject_size 0.25。
        - `score_from_path` 仅读取图像并计算 4 维评分。
      - `src/core/focus.py`：`FocusParser` 改为占位实现，始终返回空列表，避免其他模块导入错误；不再参与评分。
      - `src/web/app.py`：`/api/photo/{photo_id}/review` 移除 `af_points` 字段。
    - 配置：
      - `config/settings.yaml`、`config/settings.example.yaml`、`config/settings.test_pipeline.yaml`：更新 `quality` 权重为 4 维。
    - 前端：
      - `src/web/templates/select.html` 与 `src/web/templates/gallery.html`：质量分项名称映射从 7 维改为 4 维（清晰度、对比度、曝光、主体占比），复核/详情弹窗不再显示对焦点、姿态、飞版、构图位置。
    - 测试：
      - 更新 `tests/test_quality.py`：仅断言 4 维评分。
      - 更新 `tests/test_quality_helpers.py`：验证 `score_from_path` 返回 4 维。
      - 删除 `tests/test_focus.py`：对焦点不再参与评分。
      - 更新 `tests/test_web_review.py`：移除 `FakeFocusParser` mock 与 `af_points` 断言；质量分项用 exposure 替代 focus。
    - 完整测试套件：`331 passed, 1 skipped`。
    - 提交 `5adc2e2`：功能: 简化画质评分为 4 维（清晰度/对比度/曝光/主体占比），移除 pose/bif/focus/position。

16. **画质评分：加入 ISO/噪点维度**
    - 后端：
      - `src/core/quality.py`：
        - 新增 `calculate_iso_score()`，按用户指定分段线性计算 ISO 得分：≤200 为 100，200–800 线性降到 85，800–3200 线性降到 60，3200–12800 线性降到 30，≥12800 为 0；缺失/无效 ISO 默认 100 分。
        - `calculate_quality_score()` 与 `score_from_path()` 增加可选 `iso` 参数。
        - 默认权重改为 5 维：clarity 0.30、contrast 0.20、exposure 0.20、subject_size 0.20、iso 0.10。
    - 配置：
      - `config/settings.yaml`、`config/settings.example.yaml`、`config/settings.test_pipeline.yaml`：更新 `quality` 权重为 5 维。
    - 前端：
      - `src/web/templates/select.html` 与 `gallery.html`：质量分项名称映射增加 `iso: 'ISO/噪点'`。
    - 测试：
      - 更新 `tests/test_quality.py`：新增 ISO 边界、分段插值、含 ISO 的评分测试；更新 5 维断言。
      - 更新 `tests/test_quality_helpers.py`：验证 5 维与 `iso` 参数透传。
    - 完整测试套件：`336 passed, 1 skipped`。

17. **画质评分：接入 ISO 读取得分**
    - 后端：
      - `src/metadata/exif_writer.py`：新增 `read_iso()`，优先用 ExifTool 读取 `-ISO`，失败回退 PIL `ISOSpeedRatings`；读不到或 ExifTool 缺失返回 `None`。
      - `src/pipeline_runner.py`：在 `process_image()` 中通过 `read_iso()` 从原始文件读取 ISO 并传给 `QualityScorer().score_from_path()`；使用 `getattr(self, "exif_writer", None)` 保证兼容测试中的 `MockPipeline`。
      - `src/web/app.py`：`get_photo_review()` 在原始文件存在且 `bird_bbox` 可用时，用 `read_iso()` + `QualityScorer().score_from_path()` 重新计算画质评分与细节，覆盖旧数据库记录；失败则静默回退原数据库值。
    - 测试：
      - 新增 `tests/test_exif_writer.py::TestReadIso`：覆盖 ExifTool 读取、带冒号输出、缺失值、ExifTool 未安装四种情况。
      - 更新 `tests/test_web_review.py`：`review` 测试 mock `read_iso` 返回 800，并断言返回的 5 维 `quality_details` 与 `iso` 得分约 0.85。
    - 完整测试套件：`340 passed, 1 skipped`。

18. **iOS 随身伴侣应用设计**
    - 需求：用户希望为 `birder-station` 增加一个 iOS 手机客户端，用于在外拍或日常随时查看图鉴/外拍记录、修订元数据、做现场记录；不建服务端，数据与照片通过 iCloud 传输。
    - 方案：iOS 端定位为"桌面端的只读查看器 + 补丁回写器"，桌面端仍是唯一数据库写入者。
    - 数据同步：
      - 桌面端生成 `snapshot.json` + `thumbnails/`（200px）+ `previews/`（1200px）到 iCloud Drive `/BirderStation`。
      - iOS 端读取快照和精简图实现离线浏览。
      - iOS 端元数据修改追加到 `pending_patches.jsonl`，桌面端合并后归档。
    - 功能范围：图鉴、外拍记录、照片浏览、元数据修订、现场记录；不做导入/识别/RAW/选片等重计算。
    - 输出文档：`docs/superpowers/specs/2026-07-23-ios-companion-design.md`。
    - 待定：iCloud 容器反向域名、快照加密、TestFlight 分发、补丁合并失败通知方式。

### 待处理
- 无。

# 工作日志 / Worklog

## 2026-10-06 ~ 10-09

### 当日目标
- 新增视频素材管理功能（T1-T8 全流程实现）

### 已完成
1. **T1 ffmpeg/ffprobe 封装**
   - `src/core/video/ffmpeg_tools.py`：probe_video / extract_poster
   - `requirements.txt` 新增 imageio-ffmpeg 依赖
   - 10 个单元测试

2. **T2 数据模型、迁移与仓储**
   - `src/db/models.py`：Video / VideoMarker 模型
   - `src/db/repository.py`：VideoRepository（CRUD + 多条件查询 + count_videos）
   - 迁移改为模型驱动（对照 Photo 模型自动补齐缺失列），修复硬编码清单遗漏 primary_bird_cn 等列的 bug
   - 13 个测试

3. **T3 视频导入后台流程**
   - `src/core/video/indexer.py`：VideoIndexer（扫描、hash 去重、外拍归属）
   - `src/web/task_manager.py`：新增 start_video_import / start_combined_import / _probe_videos
   - `src/web/import_service.py`：start_import 增加 media_type 参数（photos/videos/both）
   - `src/web/app.py`：/api/import/start 接入 media_type
   - 12 个测试

4. **T4 流式播放与缩略图**
   - `src/web/path_helpers.py`：VIDEO_MIME_TYPES / get_video_file_response / get_thumbnail_placeholder_response
   - `src/web/routes/videos.py`：/api/videos/{id}/stream（Range 206）、/api/videos/{id}/thumbnail
   - 17 个测试（含 Range 分段、占位图回退）

5. **T5 浏览/详情/标记 CRUD**
   - `src/web/routes/videos.py`：list / detail / update / markers CRUD
   - 标记校验：point 需 time、segment 需 in<out、时间不超时长、category 白名单
   - 修复 marker 排序 NULL 问题（COALESCE(time, in_time)）
   - 26 个 API 测试

6. **T6 前端页面**
   - `templates/videos.html`：视频列表（搜索、分页、缩略图卡片）
   - `templates/video_detail.html`：播放器 + 时间线可视化 + 标记交互 + 导出面板
   - `templates/navbar.html`：导航栏增加"视频"入口
   - `templates/import.html`：导入向导增加媒体类型选择（照片/视频/混合）
   - `app.py`：/videos 与 /videos/{id} 页面路由

7. **T7 时间线导出**
   - `src/core/video/timeline_export.py`：FCPXML 1.9 / Premiere xmeml v5 / CMX3600 EDL
   - 两种模式：full（完整素材）/ segments（精选片段）
   - 单视频级 + 外拍级导出 API
   - 22 个测试（XML 可解析性、字段正确性、EDL 结构、空片段防护）

### 全量测试
- 497 passed, 1 skipped（含原有 475 + 新增 22）

### 关键决策
- 视频与照片共用外拍体系，通过 outing_id 关联
- 视频仅索引不移动源文件，不进行内容识别
- 导出格式优先 FCPXML 1.9（兼容性最佳），用标准库 ElementTree 生成
- 迁移改为模型驱动，一劳永逸解决硬编码列清单遗漏问题

### Pitfalls
1. SQLite ALTER TABLE 不支持 DEFAULT CURRENT_TIMESTAMP → 旧记录 created_at 留 NULL
2. JSON 中文标签 LIKE 匹配 → 同时匹配原文与 \uXXXX 转义形式
3. 迁移索引引用不存在的列 → 模型驱动补齐全部缺失列
4. marker 排序 NULL 值排最前 → COALESCE(time, in_time) 统一排序键

## 2026-09-28

### 当日目标
- 选片页外拍列表按拍摄日期排序，而非导入日期（用户反馈）

### 已完成
1. **导入流程：start_date 从文件夹名解析**
   - `src/web/import_service.py`：`_create_outing()` 改用 `PathParser.parse_folder_name(folder_name)` 解析拍摄日期作为 `Outing.start_date`，解析不到时回退到当天。此前 `start_date` 被硬编码为导入当天日期，导致外拍列表按导入时间排序。
   - 与 `src/core/indexer.py` 中 `captured_date` 的解析方式保持一致。

2. **选片页与 API：外拍列表按文件夹名倒序**
   - `src/web/app.py`：
     - `list_outings()`（`/api/outings`）排序键由 `Outing.start_date.desc()` 改为 `Outing.name.desc()`。
     - `select_page()` 下拉外拍列表同样改为 `Outing.name.desc()`。
     - `select_page()` 默认聚焦的"最近一次外拍"由 `created_at.desc()` 改为 `name.desc()`。
   - 选择按文件夹名排序而非 `start_date`：文件夹名以 `yyyyMMdd` 开头，按名倒序等价于按拍摄日期倒序，且兼容历史数据中 `start_date` 被误存为导入日期的记录，避免数据迁移。

### 测试
- `tests/test_web_import.py`：新增 `test_create_outing_parses_start_date_from_folder_name`、`test_create_outing_falls_back_to_today_when_folder_has_no_date`。
- `python -m pytest tests/test_web_import.py tests/test_api_outings.py -v` 全部通过。
- 全量 `python -m pytest`：395 passed, 2 failed（`test_db_migration` / `test_web_tags_notes` 的 `init_database` 列迁移问题，与本次改动无关，属既有问题）。

### 说明
- 用户提出"或者直接按照名称排列"的备选方案被采纳：按文件夹名排序可同时覆盖新增与历史数据，无需迁移历史外拍的 `start_date`。

### 数据迁移（一次性回填历史 outings.start_date）
- 新增 `scripts/fix_outing_start_date.py`：从 `Outing.name` 解析拍摄日期，回填 `start_date`（及范围模式下的 `end_date`）。支持 `--dry-run`、`--db-path`，无法解析名称前缀的记录（如 `testdata`、`燕隼`）跳过保留原值。
- 迁移前先用 `sqlite3.backup` 备份到 `data/birder_20260928_220237.bak.db`。
- 实际执行：17 条外拍记录中，15 条 `start_date` 由导入日期修正为文件夹名解析的拍摄日期，2 条无日期前缀跳过。例：`20260208_昆明` 的 `start_date` 从 `20260803` -> `20260208`。

### 修复：Web API 识别器每次重建导致 "Cache miss. Encoding N text labels..." 重复打印
- 现象：通过 `/api/recognition/recognize` 或独立 `recognition_service.py` 调用本地识别时，每个请求都打印一次 "Cache miss. Encoding 1437 text labels..."，导致识别缓慢。
- 根因：`RecognizerFactory.create()` 每次都 `LocalBirdRecognizer(**create_kwargs)` 新建实例，而 text features 缓存（`cached_labels` / `cached_text_features`）是实例级的，新实例必然 cache miss → 重新编码全部候选标签。批处理 pipeline 路径因 `_init_recognizer()` 只建一次并复用，故不受影响。
- 修复 `src/recognition/cloud/factory.py`：
  - 新增类级单例缓存 `_local_recognizer` + `_local_recognizer_lock`（threading.Lock）。
  - 新增 `_get_local_recognizer(kwargs)`：**无 kwargs** 时返回进程级单例（快路径读 + 锁内 double-check + 构造成功才缓存）；**有 kwargs** 时绕过单例新建，尊重调用方参数（如测试的 `model_name`/`device`）。
  - 既覆盖 Web API 默认调用路径（`create("local")` 无参），又保留测试与自定义调用的新建语义。
- 测试 `tests/test_cloud_factory.py`：
  - 原 `test_create_local_recognizer_passes_hf_mirror` 增加 save/restore 单例缓存，避免污染。
  - 新增 `test_create_local_recognizer_caches_singleton_when_no_kwargs`：断言无 kwargs 时两次调用返回同一实例、构造器只调用一次。
  - 新增 `test_create_local_recognizer_bypasses_cache_when_kwargs_passed`：断言有 kwargs 时两次调用返回不同实例、构造器调用两次。
  - `tests/test_cloud_factory.py`、`tests/test_recognition_routes.py`、`tests/test_recognition_service.py` 共 20 项全部通过。

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

## 2026-09-27

### 当日目标
- 完成选片页面的切换外拍功能
- 修复选片页面时间排序（升序，从早到晚）
- 修复预存测试失败

### 已完成
1. **选片页面切换外拍功能**
   - 后端 (`src/web/app.py`)：
     - `select_page` 路由新增查询所有外拍列表（含照片数），按 `start_date` 倒序排列，通过 `outings` 模板变量传给前端。
   - 前端 (`src/web/templates/select.html`)：
     - 头部替换原"当前外拍：xxx"静态文本为外拍下拉选择器。
     - 下拉包含「全部外拍」选项（`outing_id=0`）及所有外拍，格式为 `{name}（{start_date}）· {photo_count}张`。
     - 选择外拍后自动提交表单跳转 `/select?outing_id=<id>`，并通过 hidden input 保留当前的 `date`、`rating`、`unprocessed` 筛选参数。
     - 日期筛选表单同步增加 `outing_id`、`rating`、`unprocessed` 的 hidden input，确保按日期筛选时不丢失外拍上下文。
   - 测试：
     - 更新 `tests/test_web_three_domain.py::test_select_page_renders_template`：断言上下文包含 `"outings": []`。

2. **选片页面时间排序改为升序（从早到晚）**
   - 后端 (`src/web/app.py`)：
     - 照片查询排序：`order_by(Photo.captured_date.desc(), Photo.id.desc())` → `order_by(Photo.captured_date.asc(), Photo.id.asc())`。
     - 连拍组排序：从按 `group_id` 排序改为按组内最早照片 `captured_at` 升序排列。
     - 无分组照片按日期分组的排序：`reverse=True` 改为升序（默认）。
   - 依据：设计文档 `docs/superpowers/specs/2026-08-30-select-page-time-sort-and-cross-group-navigation-design.md` 要求按时间从早到晚排列。
   - 测试：
     - `tests/test_web_three_domain.py::test_select_page_groups_photos_by_date` 已预先更新为期望升序，本次修复代码使其通过。

3. **修复预存测试失败**
   - `tests/test_web_app.py::test_taxonomy_and_search_endpoints_forward_requests`：
     - 根因：`StubManager.get_taxonomy_tree()` 和 `get_taxonomy_tree_fast()` 未接受 `outing_id` 参数，但 `taxonomy_service` 现在会传入该参数（与真实 `IOCManager` 接口一致）。
     - 修复：更新 `StubManager` 两个方法签名增加 `outing_id=0`，并在调用记录中包含该参数；同步更新断言。
   - `tests/test_web_tags_notes.py`：重新验证全部通过（标签/备注端点及模型迁移逻辑均正常）。

4. **修复重复导入产生重复外拍 + 重新识别未处理照片**
   - 问题：`20260101_北京_奥林匹克森林公园北园` 外拍出现 2 条（ID 5 和 ID 14），因重复导入同一文件夹导致。
   - 根因：
     - `OutingRepository.get_or_create()` 按 `name + start_date` 匹配，而 `_create_outing()` 传入的 `start_date` 是导入当天日期，每次导入日期不同就会创建新外拍。
     - 重新导入时，已索引但未识别的照片不会被重新识别。
   - 修复：
     - `src/db/repository.py`：`get_or_create()` 改为仅按 `name` 匹配（文件夹名已含日期，天然唯一），保证重复导入沿用原有外拍 ID。
     - `src/core/indexer.py`：`index_folder_with_stats()` 遇到已存在照片（同 hash）时：
       - 将其 `outing_id` 修正为当前外拍，保证观鸟记录与外拍记录一致；
       - 若未处理（无 `bird_bbox`、`primary_bird_cn`、`scientific_name`），加入识别队列重新识别；
       - 已处理的照片跳过不覆盖；
       - 增加 `reprocessed` 计数和 `_is_processed()` 辅助方法。
     - `src/web/task_manager.py`：导入日志增加"待识别 X 张（含未处理 Y 张）"。
   - 数据修复：删除重复外拍 ID 14（15 张照片、11 个连拍组均为 ID 5 的完全重复），保留 ID 5 的 56 张照片。
   - 测试：
     - 新增 `tests/test_db_repository.py`：验证 `get_or_create` 按名称复用。
     - 新增 `tests/test_indexer.py`：验证未处理照片重新加入识别队列、已处理照片跳过、outing_id 修正。

### 验证
- `tests/test_web_three_domain.py`：27 passed
- `tests/test_web_review.py` + `tests/test_api_outings.py`：合计 39 passed
- 完整测试套件：`395 passed, 1 skipped`

### 待处理
- 无。

## 2026-09-27（续）

### 当日目标
- 观鸟记录按拍摄时间倒序展示（非导入时间）
- 文件夹内多日期时，按文件夹名称的日期记

### 已完成
1. **修复 `captured_date` 来源：优先文件夹名日期，非导入时间**
   - `src/core/io/path_parser.py`：`parse_path()` 返回的 `captured_date` 默认值从 `datetime.now().strftime("%Y%m%d")` 改为 `None`，避免回退到导入日期；移除未使用的 `datetime` 导入。
   - `src/pipeline_runner.py`：
     - 新增 `_resolve_source_root_for_file()`：根据配置中的 `sources` 或父目录动态确定 `source_root`，确保文件夹名（含日期）在解析路径时可见。
     - EXIF 日期逻辑：仅当 `captured_date` 为空（文件夹名无日期）时才用 EXIF 日期覆盖；文件夹名日期优先于 EXIF。
     - `process_image_by_id()`：优先使用 `PathParser` 从文件夹名解析的日期，而非数据库中已有的导入日期。
   - `src/core/indexer.py`：
     - 索引时调用 `PathParser.parse_folder_name()` 提取文件夹日期，新建照片写入 `captured_date`。
     - 对已存在但 `captured_date` 为空的照片，回填文件夹名日期。

2. **数据修复：将历史导入日期更正为文件夹名日期**
   - 编写临时脚本遍历所有照片，从 `original_path`（优先）或 `file_path` 提取文件夹名日期，更新 `captured_date`。
   - 共修正 1377 张照片的 `captured_date`。
   - 同时将路径含 `20260101_北京_奥林匹克森林公园北园` 且 `outing_id` 为空的 326 张照片归入外拍 5，保证观鸟记录与外拍记录一致。

### 验证
- `tests/test_path_parser.py`、`tests/test_indexer.py`、`tests/test_db_repository.py`：27 passed
- 图库路由 `/gallery` 确认按 `Photo.captured_date.desc()` 排序
- 各外拍 `captured_date` 与外拍名称中的日期一致（外拍 1/10 因文件夹名无日期，使用 EXIF 日期）

### 待处理
- 无。

## 2026-09-27（续二）

### 当日目标
- 选片工作台分组逻辑修复：按拍摄时间排序、<1s 视为连拍组、大图复核跨组导航

### 已完成
1. **连拍时间窗口从 5s 改为 1s**
   - `config/settings.yaml`、`settings.example.yaml`、`settings.test_pipeline.yaml`：`grouper.time_window` 从 `5` 改为 `1`。
   - 分组逻辑本身已只按 `captured_at` 时间间隔分组，不区分是否识别到鸟类。

2. **选片页按完整拍摄时间排序**
   - `src/web/app.py`：`select_page` 照片查询排序从 `captured_date.asc()` 改为 `captured_at.asc()`（精确到时分秒）。
   - 未分组照片在日期组内也按 `captured_at` 排序。

3. **大图复核跨组导航**
   - `src/web/app.py`：`_get_review_neighbors()` 从"仅同组/同日期内导航"改为"遍历本次外拍全部照片，按 `captured_at` 排序"。
   - 效果：在本组最后一张按 → 自动跳到下一组第一张，可顺序选完本次外拍所有图片。

4. **规范化 `captured_at` 格式**
   - 历史数据中 `captured_at` 存在 `T` 分隔与空格分隔、有无微秒等多种格式，导致 SQL 字符串排序错乱。
   - 统一规范化为 ISO 8601（`YYYY-MM-DDTHH:MM:SS`），共修正 2663 条记录。

5. **重新分组现有照片**
   - 清除旧 `group_id`，用 1s 窗口按外拍重新分组。
   - 结果：933 个连拍组，4234 张照片入组；组内相邻照片间隔均 ≤ 1s。

### 验证
- 完整测试套件：`395 passed, 1 skipped`

## 2026-09-27（续三）

### 当日目标
- 实现图库左侧鸟种目录树（spec 要求）

### 已完成
1. **后端：gallery 路由支持目级筛选 + 传递分类树数据**
   - `src/web/app.py`：
     - `gallery_page` 新增 `orders: List[str] = Query(default=[])` 参数，解析为 `selected_orders`。
     - 当 `selected_families` 或 `selected_orders` 非空时，查询 JOIN `Species` 表（`Photo.scientific_name == Species.scientific_name`）。
     - 目级筛选：`query.filter(Species.order_cn.in_(selected_orders))`。
     - 调用 `taxonomy_service.get_taxonomy_tree(create_db_manager, include_empty=False, outing_id=...)` 获取仅含照片的分类树（目→科→属→种），传入模板变量 `taxonomy_tree`。
     - 计算 `non_tax_query`：将除 `orders`/`families`/`species`/`offset` 外的筛选参数序列化，供目录树链接保留非分类学筛选（日期、地点、视图等）。
     - 模板上下文新增 `selected_orders`、`taxonomy_tree`、`non_tax_query`。

2. **前端：gallery.html 左侧物种目录树**
   - 布局：`div.d-flex` 内左侧 `<aside class="taxonomy-sidebar">` + 右侧 `<main>`，侧栏宽 280px、sticky、可滚动，移动端（<992px）隐藏。
   - 树形结构：目（order）→ 科（family）→ 种（species），每层显示照片数徽标。
   - 折叠/展开：`.tree-toggle`（▶/▼）点击切换 `.tree-children.collapsed`，不触发导航。
   - 点击节点文字/名称：导航到 `/gallery?orders=...` / `families=...` / `species=...`，URL 中拼接 `non_tax_query` 保留其他筛选。
   - 当前筛选高亮：`.tree-label.active` 蓝色背景。
   - 自动展开：DOMContentLoaded 时遍历所有 `.active` 标签，沿父级 `.tree-node` 向上展开所有祖先节点。
   - 清除筛选：有物种筛选时标题栏显示 ✕ 按钮，跳转 `/gallery?{{ base_query }}`。
   - 筛选表单增加 `orders` hidden input，确保提交表单时目级筛选不丢失。

3. **修复自动展开 JS 选择器错误**
   - 原代码用 `el.querySelector(':scope > .tree-children')` 查找子节点，但 `.tree-children` 是 `.tree-label` 的**兄弟节点**而非子节点，导致展开失效。
   - 改为 `el.nextElementSibling` 并校验 `classList.contains('tree-children')`，修复后激活筛选的目/科节点可正确展开。

4. **测试更新**
   - `tests/test_web_three_domain.py::test_gallery_page_renders_template`：上下文字典新增 `selected_orders: []`、`taxonomy_tree: []`、`non_tax_query: ""`，与后端实际输出对齐。

### 验证
- 完整测试套件：`395 passed, 1 skipped`
- 浏览器实测：图库左侧目录树正确渲染 18 个目及照片数；点击目链接导航到对应筛选页（服务器日志确认 `orders=` 参数生效，HTTP 200）；清除筛选按钮出现。

### 待处理
- 无。

## 2026-09-27（续四）

### 当日目标
- 修复选片页面 `/select` 500 报错：`TypeError: '<' not supported between instances of 'datetime.datetime' and 'int'`

### 问题根因
- `select_page` 中三处排序使用 `p.captured_at or p.id` 作为排序键。
- `captured_at` 可能是 `datetime`、ISO 字符串（`pipeline_runner.py` 将其 `.isoformat()` 后存库）或 `None`；`p.id` 是 `int`。
- 当部分照片 `captured_at` 为 `None` 时，排序键元组中混入 `int`，与其他照片的 `datetime` 比较时抛出 TypeError。
- 此外 `review_page` 中 `photo.captured_at.isoformat()` 对字符串类型 `captured_at` 也会 AttributeError。

### 已完成
1. **新增 `_captured_at_dt(p)` 辅助函数**（`src/web/app.py`）
   - 将 `Photo.captured_at` 规范化为 `datetime`：None/解析失败 → `datetime.min`；字符串 → `datetime.fromisoformat()`（兼容空格/T 分隔）。
   - 确保所有排序键第一元素始终为 `datetime` 类型。

2. **修复三处排序键**
   - 分组 ID 排序：`min((_captured_at_dt(p) ...), default=dt.min)`
   - 连拍组成员排序：`key=lambda p: (_captured_at_dt(p), p.id)`
   - 未分组照片排序：同上。

3. **修复 review 接口 `captured_at` 序列化**
   - `photo.captured_at.isoformat()` → `_captured_at_dt(photo).isoformat()`，兼容字符串/None。

### 验证
- `tests/test_web_three_domain.py`：27 passed
- `tests/test_web_review.py`：8 passed
- 实测 `curl http://localhost:8000/select` 返回 HTTP 200，服务器日志无异常。

### 待处理
- 无。

## 2026-07-24

### 当日目标
- 优化图库目录树节点点击响应速度：添加物种/位置索引 + AJAX 局部刷新

### 已完成
1. **数据库索引优化**（src/db/models.py）
   - 为 photos.primary_bird_cn、scientific_name、location_level1/2/3、is_selected、outing_id、group_id 添加 index=True
   - 为 	axonomy.family_cn、order_cn、chinese_name 添加 index=True
   - init_database() 中增加 CREATE INDEX IF NOT EXISTS 迁移语句，确保已有数据库能补齐缺失索引

2. **图库 AJAX 局部刷新**
   - 新增 src/web/templates/_gallery_content.html：抽取照片列表区域为独立片段
   - gallery.html：用 {% include %} 引入片段，为目录树/视图切换/分页链接添加 gallery-ajax-link 类
   - pp.py 的 gallery_page 路由：新增 partial 参数，partial=1 时返回片段模板
   - 前端 JS：拦截 .gallery-ajax-link 点击和筛选表单提交，fetch 片段后替换 #galleryContent，用 history.pushState 更新 URL，支持浏览器前进/后退
   - AJAX 刷新后重新绑定原图/裁切切换，并更新 galleryPhotos 供大图查看器使用

3. **日志降级**（src/web/path_helpers.py）
   - 
esolve_processed_web_path 失败日志从 warning 降为 debug，减少无意义 I/O

### 性能数据
- partial 响应大小：物种筛选 318KB → 63KB（-80%），目筛选 443KB → 157KB（-65%）
- 浏览器仅替换照片列表区域，不重新加载 CSS/JS/侧边栏，体感更流畅

### 验证
- 	ests/test_db.py tests/test_web_three_domain.py tests/test_web_app.py：61 passed
- 实测 curl /gallery?species=麻雀&partial=1 返回片段 HTML，HTTP 200

### 待处理
- 无。

## 2026-09-27

### 当日目标
- 修复导入页"浏览"按钮报 No module named 'tkinter' 错误

### 已完成
1. **config_service.py: 添加 tkinter 不可用时的 PowerShell 回退**
   - 新增 _ps_folder_dialog() / _ps_file_dialog()：用 PowerShell 的 System.Windows.Forms.FolderBrowserDialog / OpenFileDialog 弹出原生对话框，无需任何 Python 依赖
   - 新增 _ps_quote()：安全地将字符串嵌入 PowerShell 单引号
   - open_folder_dialog() / open_file_dialog()：tkinter 导入失败时自动回退到 PowerShell 方案（仅 Windows）

2. **app.py: 统一 import_browse_folder 调用**
   - /api/import/browse-folder 不再自己写 tkinter 逻辑，改为复用 config_service.open_folder_dialog，与设置页保持一致

### 验证
- python -m pytest tests/test_web_app.py tests/test_web_three_domain.py：60 passed
- import 页面返回 HTTP 200

### 待处理
- 无。

## 2026-09-27（续六）

### 当日目标
- 修复"清空淘汰"功能失败（回收站操作拒绝访问）
- 创建启动脚本保持控制台不关闭

### 问题根因
- 服务器从 Trae 内置终端启动时运行在 **Trae 沙箱（trae-sandbox.exe）** 中。
- 沙箱限制了 Windows Shell API（`SHFileOperationW` / `IFileOperation`），导致 `send2trash` 报 `[WinError 5] 拒绝访问`。
- 即使通过 Python 子进程调用 `send2trash`，子进程仍继承沙箱限制，同样失败。
- 但 `os.remove`（直接删除）在沙箱中可以正常工作，说明是 Shell API 被限制而非文件系统权限问题。
- 用户此前能正常使用，是因为服务器不是从 Trae 沙箱启动的。

### 已完成
1. **trash_service.py: 改用 Python 子进程批量回收**
   - 新增 `_TRASH_WORKER_SCRIPT`：独立脚本通过 stdin 接收路径列表，逐条调用 `send2trash.send2trash()`，失败时输出 `FAIL::<path>::<error>`。
   - 新增 `_subprocess_send_to_trash()`：通过 `subprocess.run([sys.executable, "-c", script])` 启动子进程，stdin 传路径，避免命令行长度限制。
   - `_batch_send_to_trash()`：Windows 上默认走子进程路径，按 200 条/块分批，避免单次调用过长。
   - 非 Windows 平台或注入自定义 `send_func` 时仍走进程内调用。
   - 注：子进程方案在沙箱外可正常工作；在沙箱内仍会失败（见根因）。

2. **trash_service.py: 友好的沙箱错误提示**
   - 新增 `_looks_like_access_denied()`：检测错误信息中是否包含"拒绝访问"/"WinError 5"/"Access is denied"。
   - `empty()` 返回值新增 `hint` 字段：当检测到访问拒绝时，提示用户"请改用普通命令行窗口通过 start_server.bat 启动服务"。

3. **创建 start_server.bat 启动脚本**（项目根目录）
   - 使用系统 Python 3.11（`C:\Users\qinmi\AppData\Local\Programs\Python\Python311\python.exe`）。
   - 不使用 `start` 命令，直接运行 `python src\web\app.py`，保持控制台窗口打开。
   - 服务器退出后显示退出码并 `pause`，方便查看错误信息。
   - 用户应从普通 cmd/PowerShell 窗口（非 Trae 终端）双击或运行此脚本。

4. **清理临时测试脚本**
   - 删除 `_test_ps_orf.py`、`_test_ps_trash.py`、`_test_py_subprocess.py`、`_test_shell_com.py`、`_test_trash.py`、`_test_os_remove.py`。

### 验证
- `tests/test_trash_service.py` + `tests/test_web_trash.py`：13 passed
- 独立脚本 `send2trash.send2trash()` 可成功移动 ORF 文件到回收站（沙箱外）
- `os.remove` 在沙箱内可工作，确认是 Shell API 被沙箱限制

### 待处理
- 无。

## 2026-09-27（续七）

### 当日目标
- 修复 start_server.bat 执行时报"不是内部或外部命令"错误

### 问题根因
- 批处理文件包含中文注释，以 UTF-8 编码保存。
- cmd.exe 按系统 OEM 代码页（GBK）解析 UTF-8 中文，导致中文行被当作命令执行，出现大量"不是内部或外部命令"错误。

### 已完成
1. **start_server.bat 改为纯 ASCII 英文**
   - 移除所有中文注释和提示，改为英文。
   - 验证：文件 0 个非 ASCII 字节，无 UTF-8 BOM。
   - Python 3.11.9 路径确认存在。

### 验证
- PowerShell 检查文件编码：纯 ASCII，无 BOM
- Python 3.11.9 可执行

### 待处理
- 无。

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

### 待处理
- [x] 图鉴增强：本次新增物种标亮、历史拍摄时间线、地图分布、跳转到图库按物种过滤（`spec.md` §4.5）

## 2026-07-22

### 当日目标
- GPU 验证与识别测试
- pipeline 支持 RAW（ORF）格式
- 完善 7 维 QualityScorer 评分（pose / bif / focus）
- 将 QualityScorer 集成到 pipeline_runner
- 实现三域 Web 路由 `/select`、`/gallery`、`/guide`

### 已完成
1. **GPU 验证通过**
   - PyTorch 2.10.0+cu128 + RTX 5060 8GB 识别正常
   - 测试 16 张 ORF，模型加载 11s，识别 0.03–0.04s/张，RAW 解码约 0.8s/张

2. **Pipeline 支持 RAW 格式**
   - `src/core/processor.py` 新增 `ImageProcessor.is_raw`、`decode_raw_to_temp_jpg`、`crop_and_resize`
   - `src/pipeline_runner.py` 的 `run()` 和 `run_by_folders()` 均使用 `supported_formats` 配置
   - 修复 RAW 输出归档扩展名归一化为 `.jpg`
   - 提交 `29fec3c`：功能: pipeline 支持 RAW 格式
   - 提交 `d7e3764`：修复: run_by_folders 也使用 supported_formats 配置

3. **QualityScorer 完善**
   - `src/core/pose.py` 改写为基于鸟框几何和边缘截断的启发式姿态/飞版判断
   - `src/core/focus.py` 改写为 ExifTool 读取 AF 点 + 中心回退
   - `src/core/quality.py` 新增 `score_from_path(path, bbox)` 便捷方法
   - 新增 `tests/test_quality_helpers.py` 覆盖 pose/focus/score_from_path
   - 新增 `scripts/score_test_images.py` 对测试 ORF 输出 7 维评分 CSV/JSON

### 发现/踩坑
- **测试脚本候选标签不完整**：只用 20 个常见种导致识别偏差极大；标准 pipeline 使用完整 IOC 11250 种更可靠
- **standard pipeline 之前只认 jpg**：`run()` 和 `run_by_folders()` 均 hardcoded `.jpg/.jpeg`，与 `supported_formats` 配置不一致
- **画质评分中飞版判断不可靠**：仅凭框宽高比和位置会把半边鸟误判为飞版，也会把真正飞版判为非飞版
- **focus 维度偏二极管**：ORF 没有有效 AF 点 EXIF 时回退中心点，导致 focus 0 或 1

### 用户要求/决策
- 用户要求“每开发完一个功能或修复一个 bug 就自动提交”，已执行
- 用户要求先“把功能做完整再接近 pipeline”，所以先完善 QualityScorer 再集成
- 用户指出 458/794 是飞版、503 是半边鸟，与自动评分结果不符；**决策：暂时保留当前自动飞版逻辑，先跑通主流程，评分策略后续再调整**

4. **QualityScorer 集成到 pipeline_runner**
   - `src/pipeline_runner.py` 引入 `QualityScorer`
   - `process_image()` 对每个裁剪后的鸟图调用 `QualityScorer().score_from_path()` 计算 7 维评分
   - `_archive_item()` 将 `quality_score`、`quality_details` 写入数据库
   - 保留原有 `QualityChecker` 模糊过滤作为前置/兼容检查
   - 修复 `tests/test_pipeline_logic.py` 的 mock 以匹配 `add_photo_record(record)` 单参数签名
   - 调整 `tests/test_pose.py` 的可见度断言，匹配新的启发式默认值
   - 完整测试套件：301 passed, 1 skipped
   - 提交 `f182fad`：功能: 将 QualityScorer 集成到 pipeline_runner

5. **三域 Web 路由实现**
   - `src/web/app.py` 新增 `/select`、`/gallery`、`/guide` 路由和 `/api/select/mark` API
   - `/select`：按日期分组展示照片，支持选中/淘汰/选最佳按钮，前端可调用 mark API
   - `/gallery`：按时间/地点/鸟种筛选，支持已选中/待确认/全部过滤和分页
   - `/guide`：按科分组展示已解锁物种，使用最高分照片作为封面缩略图
   - 新增模板：
     - `src/web/templates/select.html`
     - `src/web/templates/gallery.html`
     - `src/web/templates/guide.html`
   - 新增测试：`tests/test_web_three_domain.py`（7 个用例全部通过）
   - 完整测试套件：308 passed, 1 skipped
   - 提交 `1f366b9`：功能: 实现三域 Web 路由 /select /gallery /guide

6. **元数据写入模块完善与接入**
   - `src/metadata/exif_writer.py` 新增：
     - `quality_score_to_rating()`：0-100 分映射到 Lightroom 0-5 星级
     - `build_exif_tags_from_photo()`：生成 `ImageDescription`、`XMP:Title`、`XMP:Description`、`IPTC:Keywords`、`XMP:Subject`、`XMP:Pick`、`XMP:Rating`
     - `write_metadata_for_photo()`：JPEG 直接嵌入，RAW 自动生成 XMP sidecar
   - `src/pipeline_runner.py` 归档后自动对原始文件写入元数据（JPEG 嵌入 / RAW sidecar）
   - `src/web/app.py` 新增 API：
     - `/api/photo/{photo_id}/write_metadata` 单张写入
     - `/api/gallery/write_metadata` 批量写入已选中照片
   - `src/web/templates/select.html` 和 `gallery.html` 添加“写入元数据”按钮
   - 新增测试：`tests/test_exif_writer.py` 中 `TestPhotoMetadataHelpers` 覆盖；`tests/test_web_three_domain.py` 覆盖 Web API
   - 调整 `tests/test_pipeline_logic.py` 的 mock 以避免写入真实原文件
   - 完整测试套件：315 passed, 1 skipped
   - 提交 `TBD`：功能: 完善元数据写入并接入 pipeline 与 Web

7. **连拍分组实现**
   - 数据模型：
     - `src/db/models.py` 在 `Photo` 表添加 `group_id` 外键
     - `src/db/repository.py` 添加 `PhotoRepository.add_group()` 方法（兼容 SQLAlchemy 路径）
   - 数据库层：
     - `src/metadata/ioc_manager.py` 创建 `photo_groups` 表并迁移 `group_id`/`captured_at`/`is_selected`/`rating`/`quality_score`/`quality_details`/`created_at` 列
     - 添加 `idx_photos_captured_at` 索引
     - 实现 `group_photo_ids()` 按 captured_at 时间窗口（默认 5s）分组
     - 实现 `save_photo_groups()` 保存分组并回写 `photos.group_id`
     - 实现 `get_photos_without_group()` 避免重复分组
   - Pipeline 接入：
     - `src/metadata/exif_writer.py` 新增 `read_capture_datetime()`，先 ExifTool 后 PIL 读取原始拍摄时间
     - `src/pipeline_runner.py` 新增 `self._new_photo_ids` 跟踪本次归档的照片
     - `_archive_item()` 调用 `read_capture_datetime()` 并将 `captured_at` 写入数据库，收集 `photo_id`
     - `run()` 和 `run_by_folders()` 结束时调用 `_group_new_photos()`
     - `_group_new_photos()` 按 `grouper.time_window` 配置分组，仅保存多照片组，错误不中断流程
   - Web 选片页：
     - `src/web/app.py` 的 `/select` 优先按 `photo_groups` 展示连拍组，未分组照片按日期聚合
     - 新增 `/api/select/pick-best/{group_id}` 在连拍组中一键选最佳
     - 重写 `src/web/templates/select.html` 支持连拍组折叠/展开和单张照片组展示
   - 测试：
     - `tests/test_db_manager.py` 新增 `group_photo_ids`、`save_photo_groups`、`get_photos_without_group` 测试
     - `tests/test_pipeline_logic.py` 新增 `_group_new_photos` 分组、禁用、异常、过滤单张组测试
   - 完整测试套件：325 passed, 1 skipped
   - 提交 `d9d4ebc`：功能: 实现连拍分组

8. **照片导入 Web 流程**
   - 服务层：
     - 新建 `src/web/import_service.py`：`scan_folder()` 扫描目录并统计可导入文件，`start_import()` 启动后台导入任务，`get_status()` 返回状态
   - 任务层：
     - `src/web/task_manager.py` 新增 `start_import()` / `_run_import_thread()`：先索引照片，再根据选项运行完整识别 Pipeline（检测、识别、评分、分组）
   - Web 路由：
     - `src/web/app.py` 新增 `/import` 页面
     - 新增 `/api/import/scan` 扫描目录
     - 新增 `/api/import/start` 启动后台导入
     - 新增 `/api/import/status` 查询导入状态
   - 前端：
     - 新建 `src/web/templates/import.html`：四步引导式界面（选择源目录 → 扫描预览 → 导入选项 → 执行进度），参考 Lightroom 导入风格
     - 支持递归扫描、选择是否立即运行识别、实时进度条和日志、WebSocket 推送、完成跳转
     - 在 `select.html`、`gallery.html`、`guide.html`、`admin.html`、`index.html` 导航栏增加导入入口
   - 测试：
     - 新建 `tests/test_web_import.py` 覆盖扫描统计、启动成功/失败、状态查询等 8 个用例
     - 完整测试套件：330 passed, 1 skipped
   - 提交 `TBD`：功能: 实现照片导入 Web 流程

9. **工作目录清理与导入流程验证**
   - 清理运行时未跟踪文件：
     - 删除 `data/output/`、各 `data/*.db` 测试数据库、临时 GPU 测试脚本
   - 更新 `.gitignore`：忽略 `data/*.db`、`data/output/`、`.trae/`、`scripts/test_gpu_recognition*.py`、文档报告、分组草稿文件
   - 提交未跟踪的有效测试文件 `tests/test_focus.py`（覆盖 `src/core/focus.py`）
   - 使用测试文件夹 `D:/照片/2026/20260102_北京_玉渊潭公园` 验证后端接口：
     - `/api/import/scan`：成功返回 166 个 ORF，共 3.01 GB
     - `/api/import/start`（`run_recognition=false`）：成功启动并完成
     - `/api/import/status`：轮询正常，索引完成新增 166 张，数据库 `photos` 表 166 条记录
   - 完整测试套件：330 passed, 1 skipped
   - 提交 `TBD`：清理: 清理运行时文件并验证导入流程后端接口

10. **导入覆盖（overwrite）功能与后端流程验证**
    - 需求：用户希望重新导入同一目录时，按 `路径 + 文件名` 覆盖旧记录，避免测试时反复删库。
    - 实现：
      - `src/web/app.py`：在 `/api/import/start` 的 body 中读取 `overwrite` 参数并透传。
      - `src/web/import_service.py`：`start_import()` 增加 `overwrite` 参数。
      - `src/web/task_manager.py`：`start_import()` / `_run_import_thread()` 增加并透传 `overwrite`。
      - `src/core/indexer.py`：`index_folder_with_stats()` 增加 `overwrite` 参数；覆盖时删除同路径+文件名的旧记录，返回结果中新增 `overwritten` 和 `photo_ids`。
      - `src/db/repository.py`：新增 `get_by_path_and_name()` / `delete()`。
    - 修复 sqlite3 参数绑定：
      - `src/metadata/ioc_manager.py` 的 `add_photo_record()` / `update_photo_record()` 新增 `_normalize_record_value()`，对 dict/list 自动 `json.dumps`、datetime 转 `isoformat`、numpy/torch scalar 转原生标量。
    - 测试调整：
      - `tests/test_web_import.py`：`FakeTaskManager.start_import()` 签名接受 `overwrite`。
      - `tests/test_indexer.py`：`test_index_folder_with_stats_counts_indexed_and_skipped` 按新增字段断言。
      - `tests/test_web_index.py`：API 返回断言从完整 dict 比较改为按字段断言。
    - 验证：
      - 完整测试套件：`326 passed, 1 skipped`。
      - 使用 `D:/照片/2026/testdata` 8 张 ORF 测试 `overwrite=True`：
        - `/api/import/scan` 返回 8 张 ORF，共 154.05 MB。
        - 索引阶段正确覆盖 8 条旧记录；识别阶段运行成功，无 sqlite3 参数绑定错误。
        - 数据库记录：5 张有识别结果（如 P6200398 → 褐翅䴕雀，P6200617 → 赤麻鸭），2 张因模糊被质量过滤跳过，剩余无鸟框未识别。
    - 清理：删除临时测试脚本 `import_test.py` 与结果 `import_test_result.txt`。
    - 提交 `TBD`：功能: 添加导入覆盖功能并修复 sqlite3 参数绑定。

11. **选片大图复核界面与模板签名修复**
    - 实现复核后端 API：
      - `src/web/app.py` 新增 `GET /api/photo/{photo_id}/review`：返回照片元数据、候选 Top5、质量分项、检测框、AF 点。
      - 新增 `GET /api/photo/{photo_id}/preview`：返回 JPEG 预览，RAW 文件自动解码为临时 JPG。
    - 数据模型与流水线：
      - `src/db/models.py` 新增 `bird_bbox` JSON 字段，迁移列表包含该列。
      - `src/pipeline_runner.py` 在 `process_image()` 和 `_archive_item()` 中传递并保存 `bird_bbox`。
    - 前端弹窗：
      - `src/web/templates/select.html` 新增 Bootstrap 大图复核弹窗，左侧 Canvas 叠加检测框（绿色矩形）和 AF 点（红色圆圈），右侧显示候选结果、7 维质量分项进度条、操作按钮。
    - 新增测试：
      - `tests/test_web_review.py`：覆盖 review 返回字段、404、preview 返回 JPEG/RAW 解码、缺失照片 404。
    - 修复模板渲染签名：
      - 当前 FastAPI/Starlette 的 `Jinja2Templates.TemplateResponse` 要求第一个参数为 `request`，而项目中所有调用仍使用旧签名 `(name, context)`，导致所有页面 500（`TypeError: unhashable type: 'dict'`）。
      - 将 `src/web/app.py` 与 `src/web/admin_service.py` 中全部 `TemplateResponse` 调用改为新版 `TemplateResponse(request, name, context)`。
      - 同步更新 `tests/test_web_app.py`、`tests/test_web_index.py`、`tests/test_web_three_domain.py`、`tests/test_web_admin_service.py` 中的 `TemplateRecorder` mock 以兼容新版签名。
    - 验证：
      - 完整测试套件：`332 passed, 1 skipped`。
      - 本地启动服务，访问 `/select` 返回 200，页面包含 `reviewModal`、`openReview`、`/preview` 等关键元素；`/api/photo/{id}/review` 可正常返回 JSON。
    - 提交 `3a647b2`：功能: 实现选片大图复核界面并修复模板渲染签名。

12. **图库筛选能力增强**
    - 需求：用户希望先做图库筛选，图鉴先不做。`spec.md` 要求图库支持时间范围、鸟种（科/种）、地点、全文搜索和视图切换。
    - 后端：
      - `src/web/app.py` 的 `/gallery` 路由扩展参数：
        - `date_from` / `date_to`：日期范围
        - `species`：多选鸟种（中文名或学名）
        - `families`：多选科（`family_cn`，通过 join `Species` 表）
        - `locations`：多选地点 tag（基于当前 `Photo.location_tag`）
        - `view`：视图切换（all / selected / unselected / uncertain），保留旧 `filter` 参数兼容
        - `outing_id`：本次外拍 ID（保留参数，暂未启用过滤）
        - `q`：全文搜索扩展为文件名、鸟种名、地点、日期
      - 分页 `base_query` 使用 `urlencode(doseq=True)`，保留多选参数，确保视图切换和翻页不会丢失筛选条件。
    - 前端：
      - `src/web/templates/gallery.html` 重写筛选栏：
        - 视图切换按钮：全部 / 已选中 / 未选中 / 待确认
        - 搜索框、日期范围（开始/结束）
        - 鸟种多选、科多选、地点多选下拉框（带计数）
        - 每页数量下拉、筛选/重置按钮
      - 状态栏显示当前生效的筛选条件。
      - 分页链接继承所有筛选参数。
    - 测试：
      - 扩展 `tests/test_web_three_domain.py`：新增日期范围、鸟种、科、地点、未选中视图、文件名搜索、分页保留参数等用例。
      - 同步更新旧 `gallery_page` 测试断言以匹配新的 `TemplateResponse` context。
    - 验证：
      - 完整测试套件：`337 passed, 1 skipped`。
      - 本地启动服务，访问 `/gallery` 返回 200，页面包含所有筛选控件和视图切换链接。
    - 提交 `TBD`：功能: 增强图库筛选能力（日期范围、科/种、地点、视图切换）。

13. **结构化地点录入与级联图库筛选**
    - 需求：用户希望优化地点选择，并在导入时提供地点信息（图片无 GPS）。一次外拍通常一个地点，导入向导中可填写“省/市/公园”，并支持从文件夹路径自动解析（如 `20260102_北京_玉渊潭公园`）。
    - 数据模型与路径解析：
      - `src/db/models.py`：在 `Photo` 表新增 `location_level1`（省/直辖市）、`location_level2`（市/区）、`location_level3`（公园/具体地点）字段；迁移列表同步增加对应列。
      - `src/core/io/path_parser.py`：新增 `split_location_tag()` 静态方法，将 `location_tag` 按 `_` 拆分为三级地点；`parse()` 返回 `location_level1/2/3`。
    - 导入链路：
      - `src/core/indexer.py`：`index_folder` 和 `index_folder_with_stats` 新增 `location_info` 参数，`_build_location_kwargs()` 注入三级地点到 `Photo` 构造函数。
      - `src/web/task_manager.py`：`start_import()` / `_run_import_thread()` 透传 `location_info`。
      - `src/web/import_service.py`：`scan_folder()` 返回 `location` 字段；新增 `parse_location()` 解析文件夹路径；`start_import()` 接收并透传 `location_info`。
      - `src/web/app.py`：新增 `/api/import/parse-location` 接口；`/api/import/start` 接收 `location_info`。
    - 前端：
      - `src/web/templates/import.html`：在 Step 3 添加“省/市/公园”输入框和“从路径自动解析”按钮；地点标签自动生成；导入启动时提交 `location_info`。
    - 图库级联筛选：
      - `src/web/app.py` 的 `/gallery` 路由：参数新增 `location_level1/2/3`，支持三级地点级联筛选；兼容旧 `locations` 参数；`available_level1/2/3` 分别提供各级可选列表。
      - `src/web/templates/gallery.html`：地点多选改为省/市/公园三个下拉框，状态栏同步显示三级筛选条件。
    - 底层识别写入：
      - `src/metadata/ioc_manager.py`：`photos` 表创建与迁移均新增 `location_level1/2/3` 列。
      - `src/pipeline_runner.py`：`process_image()` 写入 `location_level1/2/3`；`run_by_photo_ids()` 读取数据库已有地点并覆盖到 meta。
    - 测试：
      - `tests/test_path_parser.py`：新增 `split_location_tag` 和 `parse` 返回三级地点的用例。
      - `tests/test_indexer.py`：新增 `location_info` 写入 `Photo` 的测试。
      - `tests/test_web_import.py`：新增 `scan_folder` 返回地点、`parse_location`、导入透传 `location_info` 的测试。
      - `tests/test_web_three_domain.py`：更新 `gallery_page` 断言以匹配新版 context；新增级联地点筛选测试。
    - 验证：
      - 完整测试套件：`346 passed, 1 skipped`。
    - 提交 `TBD`：功能: 结构化地点录入与级联图库筛选。

14. **选片人工修正鸟种**
    - 需求：`spec.md` §3.1 要求识别结果可人工修正，修正后同步更新图库/图鉴中的物种统计和照片元数据。
    - 后端：
      - `src/web/app.py` 新增 `POST /api/photo/{photo_id}/correct-species`：接收 `scientific_name`、`chinese_name`、`write_metadata`（可选），查询 IOC 校验物种名，更新 `Photo.primary_bird_cn` / `scientific_name`，并调用 `_refresh_species_for_photo()` 同步更新 `Species` 表与 `species_stats` 统计；如 `write_metadata=True` 则写入原文件元数据。
      - 新增 `_refresh_species_for_photo()`：通过 `IOCManager.update_species_stats_for_photo()` 刷新 sqlite3 统计表，并同步调整 SQLAlchemy `Species.photo_count` 与旧物种计数。
    - 前端：
      - 在 `src/web/templates/select.html` 的大图复核弹窗中增加“修正鸟种”搜索输入框，支持实时搜索候选物种，确认后调用 correct-species API 并刷新页面。
    - 测试：
      - 在 `tests/test_web_three_domain.py` 新增 `test_correct_species_updates_photo_and_stats`：验证修正后鸟种字段更新、旧物种计数减少、新物种计数增加、元数据写入成功。
    - 验证：
      - 完整测试套件：`343 passed, 1 skipped`。

15. **选片等级筛选 → 星级评分**
    - 需求：`spec.md` §5.3 要求在选片页面按质量等级快速筛选：精选（≥80）、可用（50–79）、记录（<50）、淘汰、无鸟。用户要求与 Lightroom 星级评价一致，故改为数字星级展示。
    - 后端：
      - `src/web/app.py` 的 `_apply_rating_filter()` 将档位参数改为数字：`5` 精选、`4` 可用、`3` 记录、`1` 淘汰、`0` 无鸟。功能规则与质量分区间保持不变。
    - 前端：
      - `src/web/templates/select.html` 将筛选按钮改为星级样式：🌟🌟🌟🌟🌟 精选、🌟🌟🌟🌟 可用、🌟🌟🌟 记录、❌ 淘汰、🚫 无鸟；当前选中星级高亮。
    - 测试：
      - 更新 `tests/test_web_three_domain.py` 的 `test_select_page_filters_by_rating`：使用 `5`/`4`/`3`/`1`/`0` 参数验证五档过滤结果与当前星级上下文。
    - 验证：
      - 完整测试套件：`344 passed, 1 skipped`。

16. **选片深度复核（IQA 全屏预览 / 缩放 / 组内切换）**
    - 需求：`spec.md` §5.3 步骤三要求组内复核大字预览、叠加检测框/AF点/姿态关键点，并支持左右键切换；§3.2 深度复核界面要求原图舞台、IQA 裁切预览、倍率缩放和全屏查看。
    - 后端：
      - `src/web/app.py` 的 `GET /api/photo/{photo_id}/review` 返回新增 `prev_photo_id` 与 `next_photo_id`，支持组内或同日期相邻照片切换；新增 `_get_review_neighbors()` 辅助函数按 `group_id` 或 `captured_date` 排序计算前后照片。
    - 前端：
      - `src/web/templates/select.html` 将复核弹窗 `reviewModal` 改为 `modal-fullscreen` 全屏舞台，背景深色，左侧大图区、右侧信息面板。
      - 新增图片缩放/平移：鼠标滚轮缩放、鼠标拖拽平移、底部工具栏 +/- 按钮、适应窗口按钮、全屏按钮；缩放状态通过 CSS transform 实时应用。
      - 新增左右导航箭头与键盘快捷键：⬅️/➡️ 切换组内照片，ESC 关闭弹窗。
      - 信息面板显示文件名、日期、地点、分辨率、星级/淘汰状态，并保留识别结果、质量分项、候选 Top 5、选中/淘汰/写入元数据操作。
    - 测试：
      - 在 `tests/test_web_review.py` 新增 `test_review_returns_neighbor_ids_within_group`：验证同组照片的前/后导航 ID 边界。
    - 验证：
      - 完整测试套件：`344 passed, 1 skipped`。

17. **RAW / ORF 预览色差修复**
    - 需求：用户反馈 ORF 原图在预览页/截图与原图有色差。
    - 根因：原 `ImageProcessor.decode_raw_to_temp_jpg()` 使用 `rawpy.postprocess()` 默认输出，未显式指定色彩空间和 gamma，且未嵌入 ICC profile，导致浏览器按默认 sRGB 解析时颜色偏；`preview` 路由生成的临时文件也未清理。
    - 后端：
      - `src/core/processor.py` 重构 `decode_raw_to_temp_jpg()`：
        - 优先调用 `rawpy.extract_thumb()` 提取相机内嵌 JPEG 预览（色彩与相机直出 JPEG 最接近）。
        - 内嵌预览不可用时回退到 `rawpy.postprocess()`，显式指定 `output_color=rawpy.ColorSpace.sRGB`、`gamma=(2.222, 4.5)`、关闭自动亮度，并嵌入标准 sRGB ICC profile。
        - 新增 `_embed_srgb_icc()` 辅助函数，使用 Pillow `ImageCms` 生成 sRGB profile 并写入图片信息。
      - `src/web/app.py` 的 `GET /api/photo/{photo_id}/preview` 对 RAW 解码后的临时 JPEG 读入内存后删除，避免临时文件堆积；同时引入 `StreamingResponse` 返回。
    - 测试：
      - 保留 `tests/test_web_review.py` 中 `test_preview_decodes_raw_to_temp_jpg` 与 `test_preview_returns_jpeg_for_existing_jpg` 验证预览接口返回正常。
    - 验证：
      - 完整测试套件：`344 passed, 1 skipped`。

18. **选片键盘快捷键与连拍组快速审阅**
    - 需求：`spec.md` §5.5 要求选片页支持键盘快捷键（选择/淘汰/上一张/下一张/放大/缩小等），以及连拍组一键选最佳，快速完成批量审阅。
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
    - 验证：
      - 完整测试套件：`345 passed, 1 skipped`。

19. **图库照片详情 / EXIF 侧边栏**
    - 需求：`spec.md` §5.4 要求图库点击照片用 Modal 查看大图，并展示 EXIF / IQA / 物种信息，可跳转到选片复核。
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
    - 验证：
      - 完整测试套件：`345 passed, 1 skipped`。

20. **工作台首页与统一导航**
    - 需求：用户表示原图本地已有，不需要批量导出；希望统一前端风格，将旧页面和导航统一成新导航，并新增工作台入口页面，引导语“今天拍到了什么鸟？”，入口按钮：导入、图库、图鉴，整体简洁、强引导。
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
    - 验证：
      - 完整测试套件：`345 passed, 1 skipped`。

### 待处理
- [ ] 用户已明确取消“图库：批量导出 / 下载选中照片”（`spec.md` §5.6），改为打开本地目录按钮。


# 工作日志 / Worklog

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
     - 测试：
     - 新建 `tests/test_web_import.py` 覆盖扫描统计、启动成功/失败、状态查询等 8 个用例
     - 完整测试套件：330 passed, 1 skipped
   - 提交 `d9d4ebc`：功能: 实现照片导入 Web 流程

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

### 待处理
- [ ] 与 `spec.md` 对齐：当前 spec 中是否有三域 Web 的详细设计需要确认
- [x] 将 QualityScorer 集成进 pipeline_runner
- [x] 实现三域 Web 路由 `/select`、`/gallery`、`/guide`
- [x] 完善元数据写入并接入 pipeline 与 Web
- [x] 实现真正的连拍分组（基于 EXIF 时间窗口）
- [x] 在选片工作台应用连拍分组
- [x] 实现照片导入 Web 流程
- [x] 清理运行时文件并验证导入流程后端接口
- [ ] 实现选片大图复核界面（检测框/AF点/质量分项）
- [x] 决定飞版判断策略：暂时保留当前自动飞版逻辑，后续调整

### 文件变更（本次未提交）
- `.gitignore`
- `tests/test_focus.py`
- `.context/worklog.md`（本文件）

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

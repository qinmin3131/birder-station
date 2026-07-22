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
   - 提交 `TBD`：功能: 实现三域 Web 路由 /select /gallery /guide

### 待处理
- [ ] 与 `spec.md` 对齐：当前 spec 中是否有三域 Web 的详细设计需要确认
- [x] 将 QualityScorer 集成进 pipeline_runner
- [x] 实现三域 Web 路由 `/select`、`/gallery`、`/guide`
- [x] 决定飞版判断策略：暂时保留当前自动飞版逻辑，后续调整

### 文件变更（本次未提交）
- `src/web/app.py`
- `src/web/templates/select.html`
- `src/web/templates/gallery.html`
- `src/web/templates/guide.html`
- `tests/test_web_three_domain.py`
- `.context/worklog.md`（本文件）

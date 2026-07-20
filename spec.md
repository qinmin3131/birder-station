# 鸟类照片管理系统设计文档

**版本**: 1.0  
**日期**: 2026-07-20  
**作者**: opencode + 用户  
**状态**: 已批准

## 1. 项目概述

### 1.1 背景

用户是一名生态摄影爱好者，拥有大量鸟类照片。需要一个本地桌面系统来管理这些照片，核心需求包括：

- 使用本地模型识别照片中的鸟种，支持人工修正
- 图库管理、鸟类图鉴解锁功能
- 观鸟记录管理，通过照片时间线总结当日记录
- 连拍/重复照片的智能选片功能

### 1.2 技术选型

- **架构**: 基于 wingscribe 项目定制
- **后端**: Python 3.11 + FastAPI + SQLAlchemy
- **前端**: Jinja2 + Ant Design
- **数据库**: SQLite（轻量，适合桌面应用）
- **识别引擎**: 复用 wingscribe 的 YOLO + BioCLIP 模块

### 1.3 设计原则

- **仅索引不移动**: 照片保持原位，系统通过数据库记录位置和元数据
- **简洁功能型 UI**: 功能优先，界面简洁实用
- **本地优先**: 所有功能本地运行，无需服务器
- **分层减量工作流**: 从大量原始照片到最终精选，通过自动筛选、连拍分组、组内选片逐层缩小范围，每次决策只面对合理数量的照片
- **三域动线**: 选片（当前外拍）→ 图库（浏览管理）→ 图鉴（生涯沉淀），三个空间单向递进，互不混淆
- **选片即入库**: 选片操作的结果直接影响图库的筛选视图和图鉴的物种解锁，不需要额外的手动同步

## 2. 系统架构

### 2.1 目录结构

```
birder_photo_manager/
├── src/
│   ├── core/           # 核心业务逻辑
│   │   ├── recognizer.py    # 鸟种识别（复用 wingscribe）
│   │   ├── quality.py       # 画质评估综合评分
│   │   ├── pose.py          # 姿态可见性检测 + 飞版分类
│   │   ├── focus.py         # AF 对焦点解析
│   │   ├── grouper.py       # 连拍分组
│   │   └── indexer.py       # 照片索引，RAW 解码
│   ├── db/             # 数据层
│   │   ├── models.py        # SQLAlchemy 模型
│   │   └── repository.py    # 数据访问
│   ├── web/            # Web 界面
│   │   ├── app.py           # FastAPI 应用
│   │   ├── routers/         # API 路由
│   │   └── templates/       # Jinja2 模板
│   └── cli/            # 命令行工具
├── config/
│   └── settings.yaml   # 配置文件
└── data/
    └── birder.db       # SQLite 数据库
```

### 2.2 模块职责

| 模块 | 职责 | 依赖 |
|------|------|------|
| `recognizer.py` | 鸟种识别，调用 YOLO + BioCLIP | wingscribe 核心模块 |
| `quality.py` | 画质评估，含清晰度/对比度/曝光/姿态/对焦点 | OpenCV, NumPy |
| `pose.py` | 姿态可见性检测（头/眼/身/尾/翼）+ 飞版分类 | ONNX 模型 |
| `focus.py` | 解析相机 AF 对焦点数据，判断是否落在主体上 | EXIF 解析 |
| `grouper.py` | 连拍分组，基于 EXIF 时间窗口 | EXIF 数据 |
| `indexer.py` | 照片索引，支持 ORF/NEF 等 RAW 格式 | rawpy, Pillow |
| `metadata.py` | EXIF/XMP 元数据读写，Lightroom 兼容 | exiftool |
| `repository.py` | 数据访问层 | SQLAlchemy |

## 3. 功能模块设计

### 3.1 鸟种识别模块

**功能**: 识别照片中的鸟类物种

**流程**:
1. 读取照片文件
2. YOLO 检测鸟类区域
3. BioCLIP 对裁剪区域进行物种识别
4. 保存 Top5 候选结果
5. 支持人工修正

**接口**:
```python
class Recognizer:
    def recognize(self, photo_path: str) -> RecognitionResult:
        """
        识别照片中的鸟种
        
        Returns:
            RecognitionResult: 包含 top5 候选和置信度
        """
        pass
    
    def confirm(self, recognition_id: int, species_id: int) -> None:
        """
        人工确认识别结果
        """
        pass
```

**扩展点**:
- 识别结果与图鉴解锁关联
- 支持批量识别

### 3.2 画质评估模块

**功能**: 评估照片画质，用于选片评分

**评估指标**:

| 指标 | 方法 | 权重 | 参考 |
|------|------|------|------|
| 对焦清晰度 | Laplacian 方差 | 0.25 | wingscribe 现有模糊检测 |
| 对比度 | 直方图标准差 | 0.10 | - |
| 主体位置 | 鸟在画面中的位置和大小 | 0.10 | - |
| 曝光 | 直方图分布均匀度 | 0.10 | - |
| 姿态可见性 | 头/眼/身/尾/翼 5 项可见度 | 0.20 | PlumeLens bird_visibility |
| 飞版加分 | 飞行姿态概率 P(fly) | 0.10 | PlumeLens flight_classifier |
| 对焦准确性 | AF 对焦点是否落在鸟的眼/头部 | 0.15 | 相机 EXIF AF 数据 |

**综合评分**:
```python
def calculate_quality_score(image: np.ndarray, bird_bbox: tuple,
                            visibility: dict, focus_points: list) -> int:
    """
    计算综合质量分数
    
    Args:
        image: 图像数组
        bird_bbox: 鸟的边界框 (x, y, w, h)
        visibility: 姿态可见性结果 {head, eye, body, tail, wing}
        focus_points: AF 对焦点列表
    
    Returns:
        int: 0-100 的质量分数
    """
    clarity = calculate_clarity(image)
    contrast = calculate_contrast(image)
    position = calculate_position(image.shape, bird_bbox)
    exposure = calculate_exposure(image)
    pose = calculate_pose_score(visibility)
    bif = calculate_bif_score(visibility)
    focus = calculate_focus_score(focus_points, bird_bbox)
    
    weights = [0.25, 0.10, 0.10, 0.10, 0.20, 0.10, 0.15]
    score = (
        clarity * weights[0] +
        contrast * weights[1] +
        position * weights[2] +
        exposure * weights[3] +
        pose * weights[4] +
        bif * weights[5] +
        focus * weights[6]
    )
    return int(score)
```

**深度复核界面**:
- 原图舞台显示检测框、姿态关键点、AF 对焦点
- IQA 裁切预览（语义裁切 + 技术裁切）
- 倍率缩放和全屏查看
- 信息面板展示 EXIF、姿态可见性、画质分项评分

### 3.3 连拍分组模块

**功能**: 基于 EXIF 数据自动分组连拍照片

**分组逻辑**:
1. 按拍摄时间排序
2. 计算相邻照片的时间间隔
3. 间隔 < 5 秒的归为同一组
4. 利用 EXIF 连拍序列号辅助分组

**接口**:
```python
class Grouper:
    def group_photos(self, photo_ids: list[int]) -> list[PhotoGroup]:
        """
        对照片进行连拍分组
        
        Returns:
            list[PhotoGroup]: 分组结果，每组包含照片列表和质量评分
        """
        pass
```

### 3.4 照片索引与 RAW 解码模块

**功能**: 扫描和导入照片，支持 RAW 格式解码

**流程**:
1. 用户选择文件夹
2. 递归扫描照片文件
3. 使用 rawpy 解码 RAW 文件（ORF/NEF 等）
4. 使用 Pillow 处理 JPEG
5. 读取 EXIF 信息
6. 检查是否已索引（去重）
7. 写入数据库

**支持的格式**:
- JPEG/JPG
- RAW 格式: ORF（奥林巴斯）、NEF（尼康）、CR2/CR3（佳能）、ARW（索尼）、DNG、RW2（松下）

**RAW 解码方案**: 使用 `rawpy`（基于 dcraw），解码后转为 numpy array 供后续处理

### 3.5 元数据写入模块

**功能**: 将识别结果和质量评分写入元数据，兼容 Lightroom

**写入方式**:
- JPEG 文件：使用 exiftool 直接写入源文件
- RAW 文件（NEF/ORF 等）：生成 `.xmp` 旁车文件（sidecar），不修改 RAW 原文件
- 用户也可选择强制写入 RAW EXIF（需确认风险）

**写入字段**:

**写入字段**:

| 字段 | 内容 | Lightroom 兼容 |
|------|------|----------------|
| `ImageDescription` | 中文名 \| 英文名 \| 学名 | 通用描述 |
| `XMP:Title` | 中文名 \| 英文名 | 标题 |
| `XMP:Description` | 鸟种描述 | 简介 |
| `IPTC:Keywords` | 中文名、英文名、学名、拍摄地点 | 关键字（可搜索） |
| `XMP:Subject` | 同上 | 通用 |
| `XMP:Pick` | 精选标记 | 旗标 |
| `XMP:Rating` | 质量评分 | 星级 |

**Lightroom 同步**:
- 写入后 Lightroom 选照片 → 「元数据」→「从文件读取元数据」
- 或开启「自动将更改写入 XMP」实现双向同步

## 4. Web 界面设计

### 4.1 页面结构与动线

| 空间 | 页面 | 路由 | 核心任务 |
|------|------|------|----------|
| 选片 | 选片工作台 | `/select` | 连拍分组 → 组内复核 → 质量评分 → 确认选中 |
| 图库 | 多维度浏览 | `/gallery` | 按时间/地点/鸟种筛选 → 查看/修正/导出 |
| 图鉴 | 物种墙 | `/guide` | 已解锁物种 → 拍摄时间线 → 地图分布 |

**页面间导航**：
- 选片完成 → 「查看本次外拍」→ 跳转到图库并按本次外拍过滤
- 图库 → 頂部导航切换到图鉴
- 图鉴 → 点击物种 → 跳转到图库并按该物种过滤

### 4.2 图库页面

**筛选栏**:
- 时间筛选: DatePicker（选择日期） + DatePicker.RangePicker（日期范围）
- 鸟种筛选: Select 多选（按科/种层级）
- 地点筛选: Select 多选（省/市/公园）
- 搜索: Input.Search 全文搜索（文件名、鸟种名、地点）
- 视图切换: Toggle（只看选中 / 只看未选 / 显示全部）

**布局**:
- 顶部：使用 `Layout.Header`，包含筛选栏 + 导入按钮
- 主体：使用 `List` 组件展示照片网格，按日期分组
- 底部：使用 `Descriptions` 组件显示统计信息（照片数、鸟种数、组数）

**交互**:
- 点击照片使用 `Modal` 查看大图
- 连拍组用 `Badge` 标记编号
- 使用 `Checkbox` 支持多选操作
- 从选片进入时默认筛选为本次外拍

### 4.3 选片工具

**布局**:
- 顶部：使用 `Steps` 或 `Tabs` 展示连拍组导航
- 中间：使用 `Card` 展示主预览区（当前选中照片）
- 底部：使用 `Image.PreviewGroup` 展示缩略图列表，质量评分用 `Progress` 或 `Tag` 显示

**交互**:
- 点击缩略图使用 `Image` 组件切换预览
- 使用 `Rate` 组件星级标记推荐照片
- 使用 `Button` 一键选择最佳（最高分）
- 使用 `Checkbox` 批量选择（所有 > 80 分的）

### 4.5 鸟类图鉴

**布局**:
- 主体：物种墙网格展示，按科分组。本次外拍新增物种标亮显示
- 顶部：搜索和筛选（按科/目/保护等级）
- 底部：解锁进度（已解锁 / 总数）

**交互**:
- 点击物种卡 → 浮窗展示该物种的历史拍摄记录
- 历史记录：时间线（每次外拍的照片数）+ 地图分布（所有拍摄地点标记）
- 「查看照片」→ 跳转到图库并按该物种过滤

## 5. 工作流程

### 5.1 核心理念：分层减量

一次外拍 300-500 张照片，不逐张翻阅，通过逐层筛选缩小范围：

```
  500 张                   画质/无鸟自动筛除
   ↓
  ~300 张                  连拍分组，每组推荐最佳
   ↓
  ~60 组                   组内选片（挑 1-2 张）
   ↓
  ~80-100 张               按鸟种/场景浏览，最终精选
   ↓
  ~30-50 张                导出 + 写入元数据
```

### 5.2 三域动线

用户在不同阶段在三个空间之间单向递进：

```
选片（当前外拍）──── 图库（浏览管理）──── 图鉴（生涯沉淀）
     │                      │                      │
     │ 分层筛选              │ 按时间/地点/鸟种      │ 已解锁物种墙
     │ 连拍分组              │ 查看/修正/导出         │ 时间线+地图分布
     │ 组内选片              │                      │ 拍摄记录检索
```

**动线规则**：
- 选片结束后进入图库，默认只显示本次选中的照片
- 从图库可以切换到图鉴，查看跨外拍的物种沉淀
- 新外拍开始后回到选片，不影响已有图库和图鉴

### 5.3 用户操作动线

#### 步骤一：导入 → 全自动分析
选择文件夹后后台执行：RAW 解码 → YOLO 检测 → BioCLIP 识别 → 画质评分 → 姿态检测 → AF 对焦点解析 → 连拍分组。用户在此期间可先浏览缩略图。

#### 步骤二：智能缩略图视图（默认）
每组自动推荐最佳一张。用户按等级筛选：精选/可用/记录/淘汰/无鸟。每组显示质量分 + 鸟种 + 地点 + 日期。

#### 步骤三：组内复核（按空格进入）
大字预览最佳照片，左右键在同组内切换。叠加信息：检测框、姿态关键点、AF 对焦点、质量分项。操作：保留、替换最佳、调整评分、修正鸟种。

#### 步骤四：最终筛选进入图库
选片完成后点击「查看本次外拍」进入图库，默认只看选中照片。可追加操作：标记、修正鸟种、写入元数据、导出。

#### 步骤五：沉淀到图鉴
在图鉴中查看本次新增物种（标亮显示）。点击物种查看历史拍摄时间线 + 地图分布。

## 6. 开发计划

### 阶段 1：基础框架（第 1 周）
- [ ] Fork wingscribe 项目
- [ ] 简化项目结构，移除不需要的功能
- [ ] 添加 RAW 解码支持（rawpy + ORF/NEF 兼容）
- [ ] 搭建开发环境，确保能运行
- [ ] 配置开发工具（linting, testing）

### 阶段 2：核心功能（第 2 周）
- [ ] 完善照片索引和 RAW 解码流程
- [ ] 集成识别模块，支持人工修正
- [ ] 实现元数据写入（EXIF/XMP + sidecar）
- [ ] 实现基础图库浏览
- [ ] 编写单元测试

### 阶段 3：选片功能（第 3 周）
- [ ] 实现画质评估算法
- [ ] 实现连拍分组逻辑
- [ ] 开发选片工具界面
- [ ] 性能优化

### 阶段 4：记录与图鉴（第 4 周）
- [ ] 实现观鸟记录管理
- [ ] 实现鸟类图鉴系统
- [ ] 添加统计和时间线功能
- [ ] 文档和部署脚本

### 后期路线图
- [ ] 视频选片：基于 FFmpeg 抽帧 + YOLO 检测，自动识别视频中的鸟种并生成 SRT 字幕

## 7. 依赖项

### Python 依赖
- fastapi
- uvicorn
- sqlalchemy
- jinja2
- python-multipart
- pillow
- opencv-python
- numpy
- pyyaml
- rawpy（RAW 解码，支持 ORF/NEF 等）
- aiosqlite（异步数据库）

### 前端依赖（通过 CDN 引入）
- Ant Design 5.x
- React 18（Ant Design 依赖）
- ReactDOM 18

### 外部工具
- exiftool（EXIF/XMP 元数据读写）

### 模型依赖
- YOLOv11（鸟类检测）
- BioCLIP（物种识别）

## 8. 配置项

```yaml
# config/settings.yaml
paths:
  # 照片源目录（可配置多个）
  sources:
    - path: "D:/Photos/Birds"
      recursive: true
  
  # 数据库路径
  db_path: "data/birder.db"
  
  # 支持的文件扩展名
  supported_formats: [".jpg", ".jpeg", ".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"]

recognition:
  # 设备类型: cpu 或 cuda
  device: "cpu"
  
  # YOLO 检测阈值
  detection_threshold: 0.5
  
  # TopK 候选数量
  top_k: 5

metadata:
  # JPEG 直接写入，RAW 生成 XMP sidecar
  write_mode: "xmp_sidecar"  # xmp_sidecar | direct_exif
  
  # 是否生成 XMP sidecar 文件
  generate_xmp_sidecar: true

quality:
  # 画质评估权重
  weights:
    clarity: 0.25
    contrast: 0.10
    position: 0.10
    exposure: 0.10
    pose: 0.20
    bif: 0.10
    focus: 0.15
  
  # 头眼可见性 + 飞版自动升档阈值
  pose_upgrade_threshold:
    head_eye_visible: true
    flight_probability: 0.35

grouper:
  # 连拍分组时间窗口（秒）
  time_window: 5

web:
  # Web 服务配置
  host: "0.0.0.0"
  port: 8000
```

## 9. 测试策略

### 单元测试
- 画质评估算法测试
- 连拍分组逻辑测试
- 数据访问层测试

### 集成测试
- 识别流程测试
- 导入流程测试

### 端到端测试
- 完整工作流测试

## 10. 部署方式

### 开发环境
```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn src.web.app:app --reload
```

### 生产环境
```bash
# 构建
python -m build

# 运行
python -m src.cli.main serve
```

## 11. 待定事项

- [ ] 具体的画质评估算法参数调优
- [ ] 图鉴数据来源（手动录入 or 从数据库导入）
- [ ] 与观鸟记录中心的同步接口（优先级低）

## 12. 参考资料

- [wingscribe 项目](https://github.com/jiangyuyi/wingscribe)
- [BioCLIP 论文](https://arxiv.org/abs/2311.16117)
- [FastAPI 文档](https://fastapi.tiangolo.com/)

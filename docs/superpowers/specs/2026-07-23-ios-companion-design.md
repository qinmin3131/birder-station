# iOS 随身伴侣应用设计文档

**版本**: 1.0  
**日期**: 2026-07-23  
**作者**: opencode + 用户  
**状态**: 已批准

---

## 1. 项目概述

### 1.1 背景

`birder-station` 桌面端已覆盖「导入 → 识别 → 选片 → 图库 → 图鉴 → 观鸟记录」的完整工作流，但用户在外拍途中或回家后，希望能在 iPhone 上：

- 随时查看自己的生涯图鉴和单次外拍成果。
- 对照片元数据进行轻量修订（如地点补正、备注）。
- 快速记录一笔现场观鸟见闻，回家后自动合并到桌面端数据库。

由于用户不希望维护服务端，也不想在手机端做复杂的 AI 识别或 RAW 处理，iOS 端定位为 **"桌面端的只读查看器 + 补丁回写器"**。

### 1.2 设计原则

- **无服务端**：所有数据通过 iCloud Drive 在桌面端与 iOS 端之间同步。
- **桌面端是唯一权威写入者**：SQLite 数据库仍由桌面端独占写入；iOS 端通过生成补丁文件回写，桌面端合并。
- **精简图优先**：iOS 端只接收桌面端生成的压缩缩略图和预览图，不传输 RAW 原图。
- **离线可用**：快照和精简图下载到本地后，iOS 端无需联网即可浏览大部分内容。
- **只做看/改/记**：不实现导入、识别、连拍分组、画质评分等重计算功能。

### 1.3 与桌面端的关系

```
┌──────────────────┐   生成 snapshot + 精简图   ┌──────────────────┐
│   birder-station │  ─────────────────────────▶  │   iCloud Drive   │
│     桌面端       │                            │   /BirderStation │
│   SQLite 权威库   │  ◀────────────────────────  │                  │
└──────────────────┘   读取 pending_patches      │   iOS 端补丁文件  │
        │                                       └──────────────────┘
        │                                                    │
        ▼                                                    ▼
   本地 RAW / JPEG 照片                                本地缓存 + UI
```

---

## 2. 功能范围

### 2.1 必须实现（MVP）

| 模块 | 功能 | 说明 |
|------|------|------|
| **图鉴** | 物种墙、解锁进度、按科/目筛选 | 只展示桌面端已索引的物种 |
| **外拍记录** | 外拍列表、单天外拍摘要、新增物种高亮 | 与桌面端 `/log` 页面对应 |
| **照片浏览** | 按日期/地点/鸟种查看精简图 | 只展示 `is_selected=true` 或评分达到阈值的照片 |
| **元数据修订** | 修改照片的地点、备注、鸟种 | 以补丁形式回写桌面端 |
| **现场记录** | 不绑照片的观鸟笔记 | 以补丁形式回写桌面端 |

### 2.2 不做

- 照片导入、RAW 解码、AI 识别。
- 连拍分组、画质评分、星级修改（只读展示）。
- 元数据直接写入原图文件。
- 跨设备实时同步冲突自动仲裁（由桌面端合并时按时间戳覆盖）。

---

## 3. iCloud Drive 目录约定

桌面端在 iCloud Drive 中创建固定目录：

```
~/Library/Mobile Documents/iCloud~com~example/BirderStation/
├── snapshot.json                # 元数据索引快照
├── snapshot.version             # 快照版本号，用于 iOS 端判断是否需要刷新
├── pending_patches.jsonl        # iOS 端追加的补丁队列（桌面端读取后归档）
├── thumbnails/                  # 200px 长边 JPEG 缩略图
│   └── {year}/{month}/{day}/{file_hash_prefix}.jpg
├── previews/                    # 1200px 长边 JPEG 预览图
│   └── {year}/{month}/{day}/{file_hash_prefix}.jpg
└── full/                        # 可选：原图同步目录（本版本不使用）
```

> 注：实际容器标识符使用桌面端应用包名反向域名，开发期可用 `BirderStation` 作为占位目录名。

---

## 4. 数据快照格式

### 4.1 `snapshot.json`

桌面端导出，iOS 端只读。

```json
{
  "version": "1.0",
  "generated_at": "2026-07-23T15:30:00Z",
  "desktop_device_id": "desktop-opencode",
  "schema_version": 1,
  "photos": [
    {
      "id": 1234,
      "file_hash": "a1b2c3d4e5f67890",
      "filename": "DSC_0001.jpg",
      "captured_at": "2026-07-20T08:15:30",
      "captured_date": "2026-07-20",
      "primary_bird_cn": "白头鹎",
      "scientific_name": "Pycnonotus sinensis",
      "family_cn": "鹎科",
      "order_cn": "雀形目",
      "location_level1": "上海",
      "location_level2": "浦东新区",
      "location_level3": "世纪公园",
      "latitude": 31.23,
      "longitude": 121.55,
      "is_selected": true,
      "rating": 4,
      "quality_score": 87,
      "thumbnail_path": "thumbnails/2026/07/20/a1b2c3d4.jpg",
      "preview_path": "previews/2026/07/20/a1b2c3d4.jpg",
      "outing_id": 5,
      "group_id": 12
    }
  ],
  "species": [
    {
      "id": 42,
      "scientific_name": "Pycnonotus sinensis",
      "chinese_name": "白头鹎",
      "english_name": "Light-vented Bulbul",
      "family_cn": "鹎科",
      "order_cn": "雀形目",
      "photo_count": 15,
      "first_seen_at": "2024-03-10",
      "last_seen_at": "2026-07-20"
    }
  ],
  "outings": [
    {
      "id": 5,
      "name": "世纪公园晨拍",
      "start_date": "2026-07-20",
      "end_date": "2026-07-20",
      "location_tag": "世纪公园",
      "location_level1": "上海",
      "location_level2": "浦东新区",
      "location_level3": "世纪公园",
      "latitude": 31.23,
      "longitude": 121.55,
      "photo_count": 120,
      "species_count": 18
    }
  ]
}
```

### 4.2 字段说明

- `schema_version`：快照结构版本。桌面端升级字段时递增，iOS 端遇到未知字段应忽略。
- `file_hash`：与桌面端 `Photo.file_hash` 一致，用于关联图片文件。
- `thumbnail_path` / `preview_path`：相对于 iCloud Drive 根目录的路径。
- `outing_id` / `group_id`：与桌面端外拍、连拍组对应，便于按外拍聚合。

---

## 5. 精简图策略

### 5.1 生成规则

| 图片类型 | 尺寸 | 质量 | 生成对象 | 用途 |
|----------|------|------|----------|------|
| 缩略图 | 200px 长边 | 70% | 所有 `is_selected=true` 的照片 | 网格、列表、时间线 |
| 预览图 | 1200px 长边 | 80% | 评分 ≥ 3 或质量分 ≥ 60 的照片 | 详情页、全屏查看 |

### 5.2 增量同步

- 桌面端每次只生成新增或发生变更的照片对应的精简图。
- 删除照片时，桌面端同时删除对应的精简图（可选：留空占位）。
- iOS 端通过对比 `snapshot.version` 决定是否重新加载 `snapshot.json` 和图片清单。

### 5.3 存储估算

一次外拍 500 张，最终保留约 50 张：

- 缩略图：50 × 15 KB ≈ 0.75 MB
- 预览图：50 × 120 KB ≈ 6 MB
- 快照 JSON：约 100 KB

总计单次外拍约 7 MB，对 iCloud 和手机本地存储压力很小。

---

## 6. 补丁回写机制

### 6.1 原则

iOS 端不直接修改 `snapshot.json`，也不写入 SQLite。所有修改追加到 `pending_patches.jsonl`，由桌面端在启动或用户手动触发"同步"时合并。

### 6.2 补丁格式（JSON Lines）

```jsonl
{"type":"update_photo","photo_id":1234,"changes":{"location_level3":"世纪公园-七号线入口","note":"白头鹎在荷花池边叫了许久"},"timestamp":"2026-07-23T15:35:00Z","device_id":"ios-iphone15"}
{"type":"add_note","outing_id":5,"note":"今天白头鹎特别多","timestamp":"2026-07-23T15:36:00Z","device_id":"ios-iphone15"}
{"type":"create_checklist","date":"2026-07-20","species":[{"scientific_name":"Pycnonotus sinensis","chinese_name":"白头鹎","count":3}],"location":{"level1":"上海","level2":"浦东新区","level3":"世纪公园","latitude":31.23,"longitude":121.55},"timestamp":"2026-07-23T15:40:00Z","device_id":"ios-iphone15"}
{"type":"update_species","scientific_name":"Pycnonotus sinensis","changes":{"english_name":"Custom English Name"},"timestamp":"2026-07-23T15:45:00Z","device_id":"ios-iphone15"}
```

### 6.3 补丁类型

| 类型 | 用途 | 桌面端合并行为 |
|------|------|----------------|
| `update_photo` | 修改单张照片的地点、备注、鸟种 | 更新 `Photo` 对应字段；如修改鸟种，同步刷新 `Species` 统计 |
| `add_note` | 给某次外拍添加文字备注 | 在 `Outing` 记录中追加备注字段（如 `notes` JSON） |
| `create_checklist` | 不绑照片的现场观鸟清单 | 在桌面端生成一条观鸟记录或临时 `outing` |
| `update_species` | 修改物种信息（如英文名备注） | 更新 `Species` 表对应字段（仅允许非关键字段） |

### 6.4 合并与清理

- 桌面端读取 `pending_patches.jsonl` 后，按时间顺序逐条应用。
- 合并完成后，将已处理的补丁归档到 `pending_patches.applied.{timestamp}.jsonl`，原文件清空。
- 合并失败时，保留原文件并在桌面端日志中提示，避免数据丢失。

---

## 7. iOS 端界面设计

### 7.1 主结构

底部 Tab 栏四入口：

```
┌─────────┬─────────┬─────────┬─────────┐
│  图鉴   │  外拍   │  浏览   │  记录   │
└─────────┴─────────┴─────────┴─────────┘
```

### 7.2 图鉴页

- 顶部：搜索框 + 科/目筛选。
- 主体：物种网格，每个格子显示最佳缩略图、中文名、英文名、拍摄次数。
- 本次外拍新增物种带绿色边框和"本次新增"徽章。
- 点击物种卡片进入物种详情：
  - 顶部：物种名称、科/目、首次/最近拍摄日期。
  - 中部：历史拍摄时间线（按外拍分组）。
  - 底部：地图分布（使用 Apple Maps / MapKit）。

### 7.3 外拍页

- 列表展示每次外拍卡片：日期、地点、照片数、物种数。
- 点击卡片进入外拍详情：
  - 顶部：外拍名称、地点、当日物种数 / 新种数。
  - 中部：照片时间线。
  - 底部：新增物种列表。

### 7.4 浏览页

- 顶部筛选栏：日期范围、鸟种、地点三级级联、搜索。
- 主体：照片网格或列表。
- 点击照片进入全屏详情：
  - 大图预览（使用预览图，支持双指缩放）。
  - 信息面板：鸟种、地点、时间、质量分、星级、备注。
  - 操作按钮：编辑备注、修正地点、加入待同步。

### 7.5 记录页

- "快速记一笔"入口。
- 表单：日期、地点（可自动获取当前 GPS）、鸟种、数量、备注。
- 已提交但未同步的本地记录列表。

---

## 8. iOS 端技术选型

| 层面 | 推荐方案 | 理由 |
|------|----------|------|
| 语言 / 框架 | Swift + SwiftUI | 原生访问 iCloud Drive、照片图库、MapKit 最自然 |
| 本地缓存 | Core Data（轻量）或 Codable + 文件 | 快照结构稳定，Core Data 便于查询 |
| iCloud Drive | `NSFileManager` + `NSMetadataQuery` | 可监听文件变化，离线时回退到本地缓存 |
| 地图 | MapKit | 原生集成，无需第三方 SDK |
| 图片加载 | `AsyncImage` / `SDWebImageSwiftUI` | 异步加载 iCloud Drive 中的 JPEG |
| 位置服务 | Core Location | 现场记录 GPS 锚点、补正照片地点 |
| 语音识别 | Speech 框架 | 快速备注转文字（可选） |

---

## 9. 桌面端扩展

### 9.1 新增服务：`iOSExportService`

位置：`src/core/ios_export.py`（或 `src/web/ios_export_service.py`）。

职责：

1. 从 SQLite 读取 `Photo`、`Species`、`Outing` 数据。
2. 按规则生成 `snapshot.json`。
3. 为每张照片生成/更新缩略图和预览图到 iCloud Drive 目录。
4. 读取 `pending_patches.jsonl` 并调用现有仓库方法合并到数据库。

### 9.2 导出触发时机

- 手动：在桌面端设置页或工作台新增"同步到 iOS"按钮。
- 自动：每次导入/选片/元数据写入后异步触发（可配置开关）。

### 9.3 补丁合并

- 新增 `PatchApplier` 类处理 `pending_patches.jsonl`：
  - `update_photo` → 调用 `PhotoRepository.update()`。
  - `add_note` → 更新 `Outing.notes`（如字段不存在则先迁移）。
  - `create_checklist` → 创建临时 `outing` 或追加到现有 outing。
  - `update_species` → 更新 `Species` 允许字段。

---

## 10. 安全与隐私

- 快照和精简图均存储在用户私有 iCloud Drive 中，不经过第三方服务器。
- GPS 坐标仅在用户主动记录或修订时上传/同步。
- 快照文件建议支持可选加密（V2 考虑），防止 iCloud 共享链接泄露。

---

## 11. 开发阶段

### 阶段 1：只读图鉴（1 周）

- 桌面端实现 `iOSExportService` 导出 `snapshot.json` + `thumbnails/`。
- iOS 端实现图鉴页：读取快照、展示物种墙、筛选。

### 阶段 2：外拍摘要与照片浏览（1 周）

- 桌面端导出预览图。
- iOS 端实现外拍页、浏览页、照片详情。

### 阶段 3：元数据修订与补丁回写（1 周）

- iOS 端实现照片备注/地点修改、生成 `pending_patches.jsonl`。
- 桌面端实现补丁合并。

### 阶段 4：现场记录（1 周）

- iOS 端实现"快速记一笔"、GPS 锚点、语音备注。
- 桌面端将现场清单合并为观鸟记录。

---

## 12. 测试策略

### 桌面端

- `tests/test_ios_export.py`：验证 `snapshot.json` 字段完整、缩略图/预览图生成正确、增量同步只处理变更。
- `tests/test_patch_applier.py`：验证四种补丁类型的合并行为、未知类型不崩溃、归档清理。

### iOS 端

- 单元测试：快照解析、本地缓存、补丁队列序列化。
- UI 测试：图鉴筛选、照片详情缩放、记录表单提交。
- 集成测试：iCloud Drive 文件变化监听、离线缓存回退。

---

## 13. 风险与规避

| 风险 | 影响 | 规避方案 |
|------|------|----------|
| iCloud 同步延迟 | iOS 端看到的数据不是最新 | 显示"最后同步时间"，提供手动刷新；容忍分钟级延迟 |
| 快照文件变大 | 加载变慢 | 按外拍/日期分片快照（V2）；MVP 期单文件即可 |
| 补丁合并冲突 | 桌面端与 iOS 端同时改同一字段 | 桌面端合并时按时间戳覆盖；关键字段（鸟种）提供冲突提示 |
| iOS 沙盒限制 | 无法直接访问桌面端文件 | 所有数据通过 iCloud Drive 中转 |
| 模型变更 | iOS 端解析旧快照出错 | `schema_version` 机制；未知字段忽略 |

---

## 14. 待定事项

- [ ] iCloud 容器确切的反向域名标识符（需 Apple Developer 账号配置）。
- [ ] 是否启用快照文件加密（AES-GCM，密钥由桌面端本地保存）。
- [ ] 是否需要把 iOS 端也纳入 TestFlight 分发流程。
- [ ] 桌面端补丁合并失败时的用户通知方式（Web UI 弹窗 / 日志）。

# 一键将淘汰照片移入回收站 — 设计文档

**版本**: 1.0
**日期**: 2026-08-23
**状态**: 已批准（待实现）

## 1. 背景与目标

选片阶段用户可将照片标记为「淘汰」（`rating = -1`）。当前淘汰仅是数据库标记，文件仍留在原目录，用户需手动清理。本功能提供一键操作：将所有淘汰照片的原图与关联文件移入操作系统回收站，并同步清理数据库记录。

## 2. 需求确认

| 决策点 | 结论 |
|--------|------|
| 回收站形式 | 移入**系统回收站**（Windows 回收站），可在系统中还原 |
| 操作范围 | **两个入口**：选片页（仅当前外拍）、图库页（全部淘汰照片） |
| 关联文件 | 原图 + `.xmp` sidecar 送回收站；处理后裁切图（系统生成缓存）直接删除 |
| 数据库记录 | 删除 `Photo` 记录，同步刷新物种统计与分组 best_photo_id |
| 技术方案 | 使用 `send2trash` 库（跨平台、可 mock、单包依赖） |

## 3. 设计原则

- **仅索引不移动**的例外：本功能是唯一主动移动/删除原始文件的操作，必须显式确认、可还原（回收站）、失败不中断。
- **单张失败隔离**：某张照片处理失败（文件缺失、占用等）不影响其余照片；结果分类返回 `moved / deleted / skipped / errors`。
- **数据一致性**：删除 Photo 记录后，必须刷新 `Species.photo_count`、sqlite3 `species_stats` 以及所属 `PhotoGroup.best_photo_id`。

## 4. 架构

### 4.1 新增模块 `src/core/trash_service.py`

```python
class TrashService:
    def __init__(self, session: Session, config: dict, send_func=send2trash.send2trash):
        """session: SQLAlchemy 会话；send_func 可注入以便测试 mock。"""

    def list_rejected(self, outing_id: int = 0) -> dict:
        """查询 rating == -1 的照片。
        Returns: {"count": int, "total_bytes": int, "sample_filenames": list[str]}
        outing_id > 0 时只统计该外拍；为 0 时统计全部。"""

    def empty(self, outing_id: int = 0) -> dict:
        """执行清理。
        Returns: {"moved": int, "deleted": int, "skipped": int,
                  "errors": list[{"photo_id": int, "error": str}]}"""
```

**单张照片处理流程（`empty` 内部）**：

1. 解析原图绝对路径（复用 `app.py` 中 `_resolve_original_path` 等价逻辑，抽取为 `path_helpers` 公共函数供两处使用）。
2. 原图存在 → `send_func(原图)`；不存在 → 记 `skipped`，继续。
3. 同名 `.xmp` sidecar 存在 → `send_func(sidecar)`。
4. 处理后裁切图（`photo.file_path`，若指向 processed 目录且文件存在）→ `os.remove` 直接删除，**不进回收站**。
5. 若照片属于某 `PhotoGroup` 且是 `best_photo_id`：组内剩余照片重选质量最高者为 best；组内无剩余照片则删除该 `PhotoGroup`。
6. 删除 `Photo` 记录，提交。
7. 对该照片的 `scientific_name` 刷新物种统计（复用 `app.py:_refresh_species_for_photo` 的等价逻辑；为便于复用，将该函数迁移到 `src/db/repository.py` 或新模块 `src/db/stats.py`，`app.py` 改为引用）。
8. 任一步骤抛异常：捕获并记入 `errors`，继续下一张；**DB 记录删除以"文件已处理成功或被跳过"为前提**，文件移动失败（非"缺失"类错误，如占用）时不删记录。

### 4.2 API（`src/web/app.py`）

- `GET /api/trash/preview?outing_id=0` → `{"status": "success", "count": int, "total_bytes": int, "sample_filenames": [str, ...]}`（最多 5 个示例文件名）
- `POST /api/trash/empty`，body `{"outing_id": 0}` → `{"status": "success", "moved": int, "deleted": int, "skipped": int, "errors": [...]}`

### 4.3 UI

**选片页**（`src/web/templates/select.html`）：
- 顶部按钮组中「一键精选」旁新增「🗑️ 清空淘汰」按钮。
- 点击 → 调 preview API → 确认框展示「将移入回收站 N 张（约 X MB），含文件：a.jpg、b.jpg …」，确认后调 empty API，完成后刷新页面并提示结果。

**图库页**（`src/web/templates/gallery.html`）：
- 批量「写入元数据」旁新增「🗑️ 清空淘汰」按钮，行为同上但 `outing_id=0`（全部淘汰照片）。

### 4.4 依赖

`requirements.txt` 新增：`send2trash>=1.8.0`

## 5. 数据流

```
用户点击「清空淘汰」
  → GET /api/trash/preview（张数/大小/示例）
  → 确认
  → POST /api/trash/empty
      → 逐张：send2trash(原图) → send2trash(sidecar) → os.remove(裁切图)
              → 更新/删除 PhotoGroup → 删除 Photo → 刷新物种统计
  → 返回统计结果 → 前端刷新
```

## 6. 错误处理

| 场景 | 行为 |
|------|------|
| 原图文件已不存在 | 记 `skipped`，仍删除 DB 记录与 sidecar/裁切图 |
| send2trash 抛异常（占用、权限） | 记 `errors`，**不删** DB 记录，继续下一张 |
| 无淘汰照片 | preview 返回 count=0，empty 返回全 0，前端提示"没有淘汰照片" |
| 中途部分成功 | 返回各自计数，前端如实展示 |

## 7. 测试

`tests/test_trash_service.py`（mock `send_func`）：

1. 正常流程：原图 + sidecar 进回收站、裁切图被删除、记录删除
2. outing_id 过滤：只清理指定外拍
3. 原图缺失：skipped 计数，记录仍删除
4. send2trash 抛异常：errors 计数，记录保留
5. best_photo_id 重选：删除 best 后组内重选最高分；删空组
6. 物种统计刷新：删除后 `Species.photo_count` 下降，归零物种被移除
7. preview 返回正确的 count/total_bytes/示例文件名

## 8. 范围之外（YAGNI）

- 不做"恢复已回收照片"的界面入口（用户可在系统回收站还原后重新导入）
- 不做回收站自动清空/保留天数策略
- 不做多选单张回收（本功能只针对"淘汰"集合的一键操作）

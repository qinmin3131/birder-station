# 选片工作台已处理/未处理进度 — 设计文档

**版本**: 1.0
**日期**: 2026-08-24
**状态**: 已批准（待实现）

## 1. 背景与目标

选片工作台当前无法直观看到本次外拍还剩多少照片未处理。用户需要一个顶部进度统计，实时反映处理进度。

## 2. 需求确认

| 决策点 | 结论 |
|--------|------|
| 已处理定义 | `(is_selected AND 鸟种已确认) OR rating == -1`（淘汰也算已处理） |
| 待确认鸟种判定 | `primary_bird_cn == '待确认鸟种' OR scientific_name == 'Uncertain'`（与图库 uncertain 视图口径一致） |
| 展示方式 | 仅**顶部进度统计条**（总数 / 已处理 / 未处理 / 百分比进度条） |
| 统计口径 | 应用 `outing_id` 与 `date` 筛选，**忽略** `rating` 等级筛选 |
| 更新方式 | **方案 A**：新增 API 端点，页面加载与每次标记/修正后 JS 拉取刷新 |

无鸟照片（鸟种字段为空）不算「待确认」，被选中后即为已处理。

## 3. 设计

### 3.1 API

`GET /api/select/progress?outing_id=0&date=` →

```json
{"status": "success", "total": 120, "processed": 80, "unprocessed": 40, "percent": 67}
```

- `outing_id=0` 时回退到最近一次外拍（与 `/select` 页面逻辑一致）；无外拍时统计全表
- `date` 非空时叠加 `captured_date` 筛选
- `percent = round(processed / total * 100)`，total 为 0 时 percent=0

SQLAlchemy 查询：

```python
query = session.query(Photo)
# outing/date 过滤（与 select_page 相同逻辑，去掉 rating 过滤）
confirmed = (Photo.primary_bird_cn != "待确认鸟种") & (Photo.scientific_name != "Uncertain")
processed_cond = ((Photo.is_selected == True) & confirmed) | (Photo.rating == -1)
total = query.count()
processed = query.filter(processed_cond).count()
```

### 3.2 UI（`src/web/templates/select.html`）

- 标题栏下方插入统计条：`共 N 张 · 已处理 X · 未处理 Y` + Bootstrap `progress` 进度条（带百分比文本），容器 id 为 `progressBar` 等固定 id
- 页面加载后调 `refreshProgress()`；在 `markPhoto`、`pickBest`、`autoPickBest`、`confirmReviewSpecies`、`emptyTrash` 成功后调用
- 初始渲染由服务端在 `select_page` 上下文提供（`progress` dict），避免首屏闪烁；后续由 JS 刷新

### 3.3 服务端上下文

`select_page` 复用同一计算函数 `compute_select_progress(session, outing_id, date)`，传入模板：

```python
{"total": int, "processed": int, "unprocessed": int, "percent": int}
```

## 4. 边界与错误处理

| 场景 | 行为 |
|------|------|
| 空库/无照片 | total=0，percent=0，进度条显示 0% |
| API 异常 | 返回 500 + detail；前端静默 console.error，不影响选片操作 |
| 口径一致性 | `compute_select_progress` 为唯一实现，端点与页面共用 |

## 5. 测试

`tests/test_web_three_domain.py` 追加：

1. progress 端点：空库 → total=0/percent=0
2. 已选中+已确认 → 已处理；已选中+待确认 → 未处理；淘汰 → 已处理；未动 → 未处理
3. `outing_id` / `date` 过滤生效，`rating` 筛选参数不影响（端点不接收 rating）
4. `select_page` 上下文包含 `progress` dict

## 6. 范围之外（YAGNI）

- 不做组头进度、卡片角标、未处理筛选（用户只选了顶部统计）
- 不做图库/图鉴页的进度

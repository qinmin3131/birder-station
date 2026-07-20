# Phase 2 Implementation Report

## 任务概述

在 `dev-newspec` 分支上执行 `docs/superpowers/plans/2026-07-20-dev-newspec-implementation.md` 的 Phase 2：

- Task 2.1：创建 `src/core/indexer.py` 实现照片索引扫描与文件哈希去重。
- Task 2.2：在 `src/core/indexer.py` 中增加基于 `rawpy` 的 RAW 解码支持，并提供缺失时的优雅回退。

## 实施内容

### Task 2.1 照片索引器

1. 新增 `src/core/indexer.py`：
   - `PhotoIndexer` 类接收 `PhotoRepository` 与可选的 `supported_formats`。
   - `_file_hash` 使用 SHA-256 分块读取计算文件哈希。
   - `index_folder` 按递归或非递归方式扫描目录，过滤支持的后缀。
   - **去重逻辑**：在插入前通过 `repo.get_by_hash(file_hash)` 查询数据库；若已存在则跳过并记录日志。
   - 异常路径单独捕获并记录，避免单文件失败中断整批索引。

2. 扩展 `src/db/repository.py`：
   - 为 `PhotoRepository` 增加 `get_by_hash(file_hash: str) -> Optional[Photo]`，使索引器可通过 Repository 完成去重查询，保持数据层抽象一致。

3. 新增 `tests/test_indexer.py`：
   - 验证仅支持格式被索引、非图像文件被忽略。
   - 验证重复哈希在第二次扫描时不会被再次添加。
   - 验证自定义 `supported_formats` 可限制索引范围。

### Task 2.2 RAW 解码支持

1. 修改 `src/core/indexer.py`：
   - 添加 `numpy` 与 `PIL.Image` 导入。
   - 使用 `try/except` 检测 `rawpy` 可用性；缺失时设置 `rawpy = None`、`RAWPY_AVAILABLE = False` 并记录警告，保证模块仍可导入。
   - 新增 `decode_raw(path: Path) -> np.ndarray`：调用 `rawpy.imread` + `postprocess`。
   - 新增 `load_image(path: Path) -> np.ndarray`：根据后缀自动选择 `decode_raw`（RAW）或 `PIL.Image.open`（JPEG 等）。

2. 新增 `tests/test_raw_decoder.py`：
   - 验证 JPEG 可被正常加载为 `numpy.ndarray`。
   - 使用 `monkeypatch` 模拟 `rawpy` 已安装，验证 `.nef` 等 RAW 文件路径走 `decode_raw` 分支。
   - 验证 `rawpy` 缺失时访问 RAW 文件抛出 `RuntimeError`。

## 测试结果

运行 `python -m pytest`：

```
249 passed, 1 skipped, 5 warnings in 9.44s
```

Phase 2 相关测试：
- `tests/test_indexer.py`：3 passed
- `tests/test_raw_decoder.py`：3 passed

## 提交记录

| 短 SHA | 提交信息 |
|--------|----------|
| `5aaa193` | `功能: 实现照片索引扫描与去重基础` |
| `123d08b` | `功能: 添加 rawpy RAW 解码支持` |

## 自检与说明

- 已按需求在索引器中实现文件哈希去重（计划中的 `TODO` 已落地）。
- `load_image` 同时支持 JPEG 与常见 RAW 格式，并在 `rawpy` 未安装时抛出明确异常。
- 测试不依赖真实 RAW 文件，使用 `monkeypatch` 模拟 `rawpy` 行为。
- 代码遵循 4 空格缩进、PEP 8 命名与项目既有风格，关键公共接口使用类型提示。
- 无新增外部依赖，`rawpy` 已在 `requirements.txt` 中声明。

## 状态

**DONE**

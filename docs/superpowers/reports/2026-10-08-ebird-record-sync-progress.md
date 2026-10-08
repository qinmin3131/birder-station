# eBird 观鸟记录同步开发与测试记录

- 日期：2026-10-08
- 开发分支：`feature/ebird-record-sync`
- 目标平台：Windows
- 功能范围：中国观鸟记录中心记录获取、物种映射、人工确认、eBird 文件导出，以及与现有“观鸟记录”模块整合

## 开发进度

已完成以下功能：

1. 增加观鸟记录中心 Token 配置入口，Token 保存到本地密钥配置，页面仅显示掩码，不写入日志或数据库。
2. 增加观鸟记录中心客户端，支持身份验证、记录拉取、超时与认证失效提示。
3. 增加同步草稿、同步条目、导出批次和观鸟中心报告等数据模型及数据库迁移兼容逻辑。
4. 增加观鸟中心记录与本地观鸟记录的匹配、合并和去重逻辑。
5. 增加物种名称到 eBird taxonomy 的映射，并将低置信度或未匹配条目交给人工确认。
6. 根据照片拍摄时间推算观鸟开始时间和持续时长；缺少照片时间时提供默认值并允许人工修改。
7. 增加同步工作流接口：拉取记录、查看候选项、创建/更新草稿、确认、导出、标记已上传和下载文件。
8. 将“观鸟记录”页面改为左侧按年/月组织的日期与地点目录，右侧展示记录详情，不再使用原卡片布局。
9. 增加人工确认弹窗，支持修改地点、日期、开始时间、时长、距离、完整清单状态及物种映射。
10. 生成 eBird 可导入的无表头 Record Format CSV，并在导出前校验必填字段。
11. 补充 README、示例密钥配置和忽略规则说明。

## 测试结果

专项测试命令：

```text
.venv/bin/python -m pytest tests/test_db_models.py tests/test_db_migration.py tests/test_record_secrets.py tests/test_birdreport_client.py tests/test_record_matching.py tests/test_ebird_mapping.py tests/test_ebird_sync_service.py tests/test_ebird_export.py tests/test_web_record_sync.py tests/test_birdreport_settings.py -q
```

结果：`46 passed, 95 warnings in 1.54s`

语法编译检查：

```text
.venv/bin/python -m py_compile src/web/app.py src/records/*.py src/web/record_sync_service.py src/web/birdreport_settings_service.py
```

结果：通过。

差异格式检查：

```text
git diff --check master...HEAD
```

结果：通过。

## 全量测试说明

在当前 macOS 开发环境运行全量测试时，测试收集阶段得到 `263 items / 10 errors / 1 skipped`。10 个错误均由运行配置中的 Windows 路径（例如 `D:/照片`）在导入 `src/web/app.py` 时被路径校验拒绝导致，测试尚未进入产品逻辑执行阶段。

本项目按 Windows 目标环境实施，因此本轮暂不修改该平台差异。应在 Windows 环境使用实际配置再次运行完整测试套件。

## 已知限制与后续验证

1. 观鸟记录中心客户端目前按 `/api/user` 和 `/api/reports` 接口实现。需在 Windows 环境使用真实 Token 和浏览器网络请求确认线上接口路径及返回字段；接口异常时不会覆盖已有本地数据。
2. eBird 导出使用旧版无表头 Record Format，国家固定为 `CN`，省/州字段当前留空；首次使用前应在 eBird 导入页用样例文件验证。
3. SQLAlchemy 测试中存在 `datetime.utcnow()` 弃用警告，以及新增本地物种时的一条 autoflush 警告，均未导致测试失败，可在后续维护中处理。
4. 仍需在 Windows 环境完成：Token 保存与过期提示、真实记录拉取、页面人工确认、CSV 下载与 eBird 手工导入、全量 `python -m pytest`。

## 安全与提交范围

- Token 仅保存在被忽略的本地 `config/secrets.yaml` 中；仓库只提交不含真实凭据的示例配置。
- `.venv/`、`.coverage`、`htmlcov/`、缓存文件和 `.superpowers/` 工作记录均不纳入版本控制。
- 本报告记录的是当前分支已提交实现和提交前验证状态。

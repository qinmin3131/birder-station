# eBird 观鸟记录同步实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有观鸟记录模块中实现中国观鸟记录中心报告获取、人工匹配与确认、eBird CSV 导出，并把记录页改造成按年/月组织的目录式界面。

**Architecture:** 以新增 SQLAlchemy 实体保存远端报告缓存、同步草稿、物种明细和导出批次；外部 API、匹配映射、草稿编排和 CSV 输出分别放在独立服务中。FastAPI 路由仅做输入输出适配，设置页安全维护 Token，记录页通过 JSON API 加载目录和详情。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、SQLAlchemy 2、SQLite、requests、Jinja2、Bootstrap、原生 JavaScript、pytest

**Spec:** `docs/superpowers/specs/2026-10-08-ebird-record-sync-design.md`

## Global Constraints

- 中国观鸟记录中心 Token 只能保存在本地 `config/secrets.yaml`，不得进入数据库、日志、页面源码或 API 响应。
- 不保存观鸟记录中心账号密码，不自动登录或续期 Token。
- 不调用 eBird 写入 API，不自动操作 eBird 网页，也不自动判断上传成功。
- 远端报告是鸟种和数量的主数据源；本地照片只补充证据、元数据和默认未选中的鸟种。
- 本地独有鸟种经确认加入后数量默认为 `X`，不得用照片张数推断个体数。
- 候选报告只排序，不自动绑定；缺少映射、坐标或 eBird 必填努力量时禁止导出。
- 复用现有 Bootstrap 和原生 JavaScript，不新增前端框架。

## Review Focus

- 远端接口返回 HTML、空体或结构变化时应返回安全错误，不缓存半成品；Task 2 覆盖。
- Token 含空白、已过期或远端错误正文回显 Token 时不得泄露；Task 2 和 Task 7 覆盖。
- 照片时间跨日、倒序、缺失或存在多个大间隔时必须给出确定且可解释的建议；Task 3 覆盖。
- 中文逗号、双引号、换行和非 ASCII 鸟名必须生成可被 eBird 接受的 UTF-8 CSV；Task 5 覆盖。
- 重复点击导出、远端报告更新、已上传后修订必须保留历史并提示重复风险；Task 4、Task 5 和 Task 6 覆盖。

---

### Task 1: 同步数据模型与幂等迁移

**Files:**
- Modify: `src/db/models.py`
- Modify: `tests/test_db_models.py`
- Modify: `tests/test_db_migration.py`

**Interfaces:**
- Produces: `BirdReportReport`, `EBirdSyncDraft`, `EBirdSyncItem`, `EBirdExportBatch`; enums `EBirdDraftStatus`, `EBirdItemSource`; `init_database(engine)` creates all tables and indexes idempotently.

- [ ] **Step 1: Write failing model tests**

```python
def test_ebird_sync_models_persist_relationships(session):
    report = BirdReportReport(remote_id="202610070001", observed_on="20261007", location_name="奥森")
    draft = EBirdSyncDraft(report=report, status=EBirdDraftStatus.PENDING_CONFIRMATION.value)
    draft.items.append(EBirdSyncItem(source=EBirdItemSource.BIRDREPORT.value, scientific_name="Pica pica", count_value="2", included=True))
    session.add(draft)
    session.commit()
    assert draft.report.remote_id == "202610070001"
    assert draft.items[0].count_value == "2"

def test_init_database_is_idempotent_for_ebird_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    init_database(engine)
    init_database(engine)
    assert {"birdreport_reports", "ebird_sync_drafts", "ebird_sync_items", "ebird_export_batches"} <= set(inspect(engine).get_table_names())
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_db_models.py tests/test_db_migration.py -q`
Expected: FAIL because the four models and enums do not exist.

- [ ] **Step 3: Implement models and indexes**

Add string-valued enums and SQLAlchemy models. Use a unique constraint on `BirdReportReport.remote_id`; index draft status and foreign keys; store normalized/raw JSON with `JSON`; store `content_hash`, `taxonomy_version`, timestamps and optional `ebird_checklist_id`. Relationships use `cascade="all, delete-orphan"` only from draft to items/batches, never from draft to cached report or outing.

- [ ] **Step 4: Run model and migration tests**

Run: `python -m pytest tests/test_db_models.py tests/test_db_migration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/db/models.py tests/test_db_models.py tests/test_db_migration.py
git commit -m "功能: 添加 eBird 同步数据模型"
```

### Task 2: Token 秘密配置与观鸟中心客户端

**Files:**
- Create: `src/records/__init__.py`
- Create: `src/records/birdreport_client.py`
- Create: `src/records/secrets.py`
- Create: `tests/test_birdreport_client.py`
- Create: `tests/test_record_secrets.py`
- Modify: `config/secrets.example.yaml`

**Interfaces:**
- Produces: `BirdReportClient(base_url: str, token_provider: Callable[[], str], session: requests.Session | None = None)`; `test_connection() -> ConnectionResult`; `fetch_reports(date_from: str, date_to: str) -> list[NormalizedReport]`; `load_birdreport_token(base_dir: Path) -> str | None`; `save_birdreport_token(base_dir: Path, token: str) -> None`; `clear_birdreport_token(base_dir: Path) -> None`.

- [ ] **Step 1: Write failing secret and client tests**

```python
def test_secret_round_trip_never_returns_other_settings(tmp_path):
    save_birdreport_token(tmp_path, " token-value ")
    assert load_birdreport_token(tmp_path) == "token-value"
    clear_birdreport_token(tmp_path)
    assert load_birdreport_token(tmp_path) is None

def test_fetch_reports_normalizes_response(fake_session):
    fake_session.queue(200, {"data": [{"id": "R1", "date": "2026-10-07", "place": "奥森", "species": []}]})
    reports = BirdReportClient("https://api.birdreport.cn", lambda: "secret", fake_session).fetch_reports("20261001", "20261008")
    assert reports[0].remote_id == "R1"
    assert reports[0].observed_on == "20261007"

@pytest.mark.parametrize("status", [401, 403])
def test_expired_token_raises_without_leaking_token(fake_session, status):
    fake_session.queue(status, {"message": "secret rejected"})
    with pytest.raises(BirdReportAuthError) as exc:
        BirdReportClient("https://api.birdreport.cn", lambda: "secret", fake_session).test_connection()
    assert "secret" not in str(exc.value)
```

```python
@pytest.mark.parametrize("case", ["blank_token", "html", "empty", "timeout", "rate_limit", "missing_fields"])
def test_client_rejects_unusable_input_with_safe_domain_error(client_case, case):
    client = client_case(case)
    with pytest.raises(BirdReportError) as exc:
        client.fetch_reports("20261001", "20261008")
    assert exc.value.category in {"auth", "network", "rate_limit", "invalid_response"}
    assert "X-Auth-Token" not in str(exc.value)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_record_secrets.py tests/test_birdreport_client.py -q`
Expected: FAIL because `src.records` does not exist.

- [ ] **Step 3: Implement secret helpers and defensive client**

Use `yaml.safe_load/safe_dump`, preserve unrelated keys, and store under `birdreport.token`. Send the stripped value as `X-Auth-Token`. Convert external payloads into frozen dataclasses `NormalizedReport` and `NormalizedSpecies`; reject malformed payloads before returning. Exceptions expose a stable Chinese message and status category, never response headers/body or Token.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_record_secrets.py tests/test_birdreport_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/records config/secrets.example.yaml tests/test_record_secrets.py tests/test_birdreport_client.py
git commit -m "功能: 添加观鸟中心认证与记录客户端"
```

### Task 3: 候选匹配、鸟种合并与照片时间推导

**Files:**
- Create: `src/records/matching.py`
- Create: `src/records/mapping.py`
- Create: `tests/test_record_matching.py`
- Create: `tests/test_ebird_mapping.py`

**Interfaces:**
- Consumes: `NormalizedReport`, `NormalizedSpecies`, `Outing`, `Photo`.
- Produces: `rank_report_candidates(outing, reports) -> list[ReportCandidate]`; `derive_effort_from_photos(photos) -> EffortSuggestion`; `merge_species(report_species, local_species, taxonomy_lookup) -> list[MappedSpecies]`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_candidates_are_ranked_but_not_bound():
    candidates = rank_report_candidates(outing("20261007", "奥森北园"), [report("R1", "20261007", "柳荫公园"), report("R2", "20261007", "奥森北园")])
    assert [c.remote_id for c in candidates] == ["R2", "R1"]
    assert all(c.is_bound is False for c in candidates)

def test_photo_effort_detects_two_hour_gap():
    result = derive_effort_from_photos([photo("2026-10-07T08:00:00"), photo("2026-10-07T08:05:00"), photo("2026-10-07T10:06:00")])
    assert result.start_time == time(8, 0)
    assert result.duration_minutes == 126
    assert result.split_recommended is True

def test_local_only_species_is_excluded_with_x_count():
    mapped = merge_species([], [local_species("Tarsiger cyanurus")], taxonomy_lookup)
    assert mapped[0].source == "local_supplement"
    assert mapped[0].included is False
    assert mapped[0].count_value == "X"
```

```python
@pytest.mark.parametrize(
    ("timestamps", "duration", "has_error"),
    [(["2026-10-07T08:00:00"], 10, False),
     (["2026-10-07T08:00:00", "2026-10-07T08:05:00"], 10, False),
     (["2026-10-07T08:00:00", "2026-10-07T20:00:00"], 720, False),
     (["2026-10-07T08:00:00", "2026-10-07T20:00:01"], None, True),
     (["2026-10-07T23:59:00", "2026-10-08T00:01:00"], None, True)],
)
def test_effort_boundaries(timestamps, duration, has_error):
    result = derive_effort_from_photos([photo(value) for value in reversed(timestamps)])
    assert result.duration_minutes == duration
    assert bool(result.errors) is has_error

def test_remote_count_wins_and_ambiguous_taxonomy_requires_confirmation():
    mapped = merge_species([remote_species("灰喜鹊", "8")], [local_species("Cyanopica cyanus")], ambiguous_taxonomy_lookup)
    assert mapped[0].count_value == "8"
    assert mapped[0].mapping_status == "needs_confirmation"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_record_matching.py tests/test_ebird_mapping.py -q`
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement pure functions and dataclasses**

Keep all functions free of database and network dependencies. Normalize dates before comparison, use coordinate distance only when both sides provide valid coordinates, and expose score reasons for the UI. `EffortSuggestion` includes `source_photo_count`, `first_captured_at`, `last_captured_at`, `warnings`, and `split_recommended`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_record_matching.py tests/test_ebird_mapping.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/records/matching.py src/records/mapping.py tests/test_record_matching.py tests/test_ebird_mapping.py
git commit -m "功能: 添加记录匹配与 eBird 映射"
```

### Task 4: 报告缓存与同步草稿服务

**Files:**
- Create: `src/records/sync_service.py`
- Create: `tests/test_ebird_sync_service.py`

**Interfaces:**
- Consumes: SQLAlchemy `Session`, Task 1 models, Task 3 pure functions.
- Produces: `RecordSyncService(session)` with `upsert_reports(reports)`, `list_candidates(outing_id, date_from, date_to)`, `bind_report(outing_id | None, remote_id)`, `update_draft(draft_id, patch)`, `mark_uploaded(draft_id, checklist_id=None)`, `get_draft(draft_id)`.

- [ ] **Step 1: Write failing service tests**

```python
def test_changed_remote_report_marks_draft_needs_revision(service):
    service.upsert_reports([report("R1", species=[("Pica pica", "2")])])
    draft = service.bind_report(outing_id=None, remote_id="R1")
    service.upsert_reports([report("R1", species=[("Pica pica", "3")])])
    assert service.get_draft(draft.id).status == "needs_revision"

def test_only_one_active_draft_per_report(service):
    first = service.bind_report(None, "R1")
    second = service.bind_report(None, "R1")
    assert second.id == first.id

def test_uploaded_draft_is_copied_for_revision(service):
    original = service.bind_report(None, "R1")
    service.mark_uploaded(original.id, "S123")
    revised = service.bind_report(None, "R1")
    assert revised.id != original.id
    assert revised.duplicate_warning is True
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/test_ebird_sync_service.py -q`
Expected: FAIL because service does not exist.

- [ ] **Step 3: Implement transactional service**

Hash canonical normalized JSON with SHA-256. Preserve user-confirmed draft fields when a cached report changes. Enforce allowed state transitions in one helper and raise domain exceptions for invalid transitions, missing entities and incomplete patches.

- [ ] **Step 4: Run service tests**

Run: `python -m pytest tests/test_ebird_sync_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/records/sync_service.py tests/test_ebird_sync_service.py
git commit -m "功能: 添加 eBird 同步草稿服务"
```

### Task 5: eBird 校验与 CSV 导出

**Files:**
- Create: `src/records/ebird_export.py`
- Create: `tests/test_ebird_export.py`
- Create: `tests/fixtures/ebird_expected.csv`

**Interfaces:**
- Consumes: confirmed `EBirdSyncDraft` and included `EBirdSyncItem` rows.
- Produces: `validate_draft(draft) -> list[ValidationIssue]`; `build_ebird_record_csv(draft) -> bytes`; `export_draft(session, draft_id, export_dir: Path) -> ExportResult`.

- [ ] **Step 1: Write failing validation and golden-file tests**

```python
def test_missing_required_effort_blocks_export(complete_draft):
    complete_draft.observer_count = None
    assert validate_draft(complete_draft) == [ValidationIssue(field="observer_count", code="required")]

def test_csv_matches_golden_file(complete_draft):
    actual = build_ebird_record_csv(complete_draft)
    assert actual == Path("tests/fixtures/ebird_expected.csv").read_bytes()

def test_csv_quotes_commas_quotes_newlines_and_chinese(complete_draft):
    complete_draft.location_name = '奥森, 北园 "湿地"\n东侧'
    parsed = list(csv.reader(io.StringIO(build_ebird_record_csv(complete_draft).decode("utf-8"))))
    assert parsed[0][LOCATION_COLUMN] == complete_draft.location_name
```

```python
def test_csv_has_no_header_and_keeps_x_count(complete_draft):
    rows = list(csv.reader(io.StringIO(build_ebird_record_csv(complete_draft).decode("utf-8"))))
    assert rows[0] != list(EBIRD_RECORD_COLUMNS)
    assert any(row[COUNT_COLUMN] == "X" for row in rows)

def test_repeated_export_reuses_hash_but_changed_content_versions(session, complete_draft, tmp_path):
    first = export_draft(session, complete_draft.id, tmp_path)
    repeated = export_draft(session, complete_draft.id, tmp_path)
    assert repeated.duplicate_of_batch_id == first.batch_id
    complete_draft.location_name = "新地点"
    session.commit()
    changed = export_draft(session, complete_draft.id, tmp_path)
    assert changed.batch_id != first.batch_id

def test_write_failure_does_not_create_batch(session, complete_draft, unwritable_path):
    with pytest.raises(EBirdExportError):
        export_draft(session, complete_draft.id, unwritable_path)
    assert session.query(EBirdExportBatch).count() == 0
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_ebird_export.py -q`
Expected: FAIL because exporter does not exist.

- [ ] **Step 3: Implement strict validator and exporter**

Use Python `csv.writer` with `newline=""` semantics and UTF-8 bytes. Define the exact eBird Record Format column tuple once as `EBIRD_RECORD_COLUMNS`; do not emit a header row. Write through a temporary file in the target directory and atomically replace the final path only after success. Record a batch only after the file exists and its SHA-256 is known.

- [ ] **Step 4: Run exporter tests**

Run: `python -m pytest tests/test_ebird_export.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/records/ebird_export.py tests/test_ebird_export.py tests/fixtures/ebird_expected.csv
git commit -m "功能: 生成并校验 eBird 导入文件"
```

### Task 6: 同步 Web API 与下载流程

**Files:**
- Create: `src/web/record_sync_service.py`
- Create: `tests/test_web_record_sync.py`
- Modify: `src/web/app.py`

**Interfaces:**
- Consumes: Tasks 2–5 services.
- Produces: JSON endpoints `GET /api/log/{outing_id}`, `POST /api/records/pull`, `GET /api/records/candidates`, `POST /api/ebird/drafts`, `PATCH /api/ebird/drafts/{id}`, `POST /api/ebird/drafts/{id}/export`, `POST /api/ebird/drafts/{id}/uploaded`; file endpoint `GET /api/ebird/exports/{batch_id}`.

- [ ] **Step 1: Write failing route tests**

```python
def test_pull_records_supports_outing_and_date_range(client, fake_client):
    response = client.post("/api/records/pull", json={"date_from": "20261001", "date_to": "20261008"})
    assert response.status_code == 200
    assert response.json()["report_count"] == 2

def test_export_returns_download_and_import_urls(client, ready_draft):
    response = client.post(f"/api/ebird/drafts/{ready_draft.id}/export")
    assert response.json()["download_url"].startswith("/api/ebird/exports/")
    assert response.json()["import_url"] == "https://ebird.org/import/upload.form"

def test_unresolved_mapping_returns_422_with_field_path(client, draft):
    response = client.post(f"/api/ebird/drafts/{draft.id}/export")
    assert response.status_code == 422
    assert response.json()["detail"][0]["field"].startswith("items.")
```

Add tests for expired Token, malformed dates, nonexistent outing/draft, invalid state transition, repeated export and export path traversal.

- [ ] **Step 2: Run route tests and verify failure**

Run: `python -m pytest tests/test_web_record_sync.py -q`
Expected: FAIL with missing routes.

- [ ] **Step 3: Implement thin request models and routes**

Keep orchestration in `src/web/record_sync_service.py`; `app.py` registers models/routes and maps domain errors to 400/401/404/409/422/502. Resolve downloads only from persisted batch IDs and verified export roots; never accept a caller-provided filesystem path.

- [ ] **Step 4: Run route and existing app tests**

Run: `python -m pytest tests/test_web_record_sync.py tests/test_web_app.py tests/test_web_log.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/record_sync_service.py src/web/app.py tests/test_web_record_sync.py
git commit -m "功能: 添加 eBird 同步接口"
```

### Task 7: 设置页 Token 管理

**Files:**
- Create: `src/web/birdreport_settings_service.py`
- Create: `tests/test_birdreport_settings.py`
- Modify: `src/web/app.py`
- Modify: `src/web/templates/settings.html`

**Interfaces:**
- Consumes: Task 2 secret helpers and `BirdReportClient.test_connection()`.
- Produces: `GET /api/settings/birdreport/status`, `POST /api/settings/birdreport/token`, `POST /api/settings/birdreport/test`, `DELETE /api/settings/birdreport/token`.

- [ ] **Step 1: Write failing security and behavior tests**

```python
def test_status_never_returns_token(client, saved_token):
    payload = client.get("/api/settings/birdreport/status").json()
    assert payload["configured"] is True
    assert "token" not in payload
    assert "secret" not in str(payload)

def test_save_and_test_strips_token(client, monkeypatch):
    response = client.post("/api/settings/birdreport/token", json={"token": " secret ", "test": True})
    assert response.status_code == 200
    assert response.json()["connected"] is True

def test_remote_error_cannot_echo_token(client, fake_client):
    fake_client.raise_error("secret rejected")
    response = client.post("/api/settings/birdreport/test")
    assert "secret" not in response.text
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_birdreport_settings.py -q`
Expected: FAIL with missing endpoints.

- [ ] **Step 3: Implement settings service, routes and UI panel**

Render a dedicated panel below existing configuration sections. Never put the stored value into `value`, `data-*`, inline script or current config JSON. The input accepts only a newly typed Token; status displays “已保存/未配置”、last checked time and optional username. Buttons call the dedicated endpoints and clear the input after each request.

- [ ] **Step 4: Run settings tests**

Run: `python -m pytest tests/test_birdreport_settings.py tests/test_web_config.py tests/test_web_config_helpers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/birdreport_settings_service.py src/web/app.py src/web/templates/settings.html tests/test_birdreport_settings.py
git commit -m "功能: 在设置页维护观鸟中心 Token"
```

### Task 8: 目录式观鸟记录页与确认界面

**Files:**
- Modify: `src/web/app.py`
- Modify: `src/web/templates/log.html`
- Modify: `tests/test_web_log.py`
- Modify: `tests/test_web_record_sync.py`

**Interfaces:**
- Consumes: Tasks 4、6 JSON endpoints and existing `/gallery?outing_id=`.
- Produces: `/api/log` returns `groups -> months -> entries` summary plus selected detail URL; `/log` renders accessible master-detail UI and a four-step Bootstrap modal/offcanvas workflow.

- [ ] **Step 1: Write failing directory API and template tests**

```python
def test_api_log_groups_entries_by_year_and_month(tmp_path, monkeypatch):
    result = web_app.api_birding_log()
    assert result["groups"][0]["year"] == "2026"
    assert result["groups"][0]["months"][0]["month"] == "07"
    assert result["groups"][0]["months"][0]["entries"][0]["sync_status"] == "not_started"

def test_log_template_uses_directory_not_cards(client):
    html = client.get("/log").text
    assert 'id="recordDirectory"' in html
    assert 'id="recordDetail"' in html
    assert "record-card" not in html
```

Add detail selection, search, empty state, sync badge, narrow-screen drawer markup, modal step navigation and safe text rendering tests.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_web_log.py tests/test_web_record_sync.py -q`
Expected: FAIL because current response is flat and template uses cards.

- [ ] **Step 3: Refactor log aggregation and replace template**

Return a compact tree from `/api/log`; fetch the selected record from `/api/log/{outing_id}`. Build directory nodes with DOM methods and assign user data through `textContent`, not interpolated HTML. Desktop uses a fixed-width left directory and flexible detail pane; under the Bootstrap `lg` breakpoint, directory moves into an offcanvas. Add tabs for bird species, photos and sync history, and implement the four confirmation steps against Task 6 endpoints.

- [ ] **Step 4: Run page tests and visual smoke check**

Run: `python -m pytest tests/test_web_log.py tests/test_web_record_sync.py tests/test_web_index.py -q`
Expected: PASS.

Manual: run `python src/web/app.py`, verify `/log` at desktop width and a 390px viewport, select multiple year/month nodes, search Chinese locations, and complete a mocked draft through CSV download.

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py src/web/templates/log.html tests/test_web_log.py tests/test_web_record_sync.py
git commit -m "功能: 重构观鸟记录并接入 eBird 同步"
```

### Task 9: 配置说明、全量验证与临时文件隔离

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-10-08-ebird-record-sync-implementation.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented setup and clean repository state.

- [ ] **Step 1: Add an end-to-end regression test before documentation**

Add to `tests/test_web_record_sync.py`:

```python
def test_pull_bind_confirm_export_and_mark_uploaded(client, fake_client, seeded_outing):
    assert client.post("/api/records/pull", json={"date_from": "20261007", "date_to": "20261007"}).status_code == 200
    candidates = client.get(f"/api/records/candidates?outing_id={seeded_outing.id}").json()["candidates"]
    draft = client.post("/api/ebird/drafts", json={"outing_id": seeded_outing.id, "remote_id": candidates[0]["remote_id"]}).json()
    confirmed = confirm_all_required_fields(client, draft["id"])
    exported = client.post(f"/api/ebird/drafts/{confirmed['id']}/export").json()
    assert client.get(exported["download_url"]).status_code == 200
    assert client.post(f"/api/ebird/drafts/{confirmed['id']}/uploaded", json={"checklist_id": "S123"}).json()["status"] == "uploaded"
```

- [ ] **Step 2: Run the end-to-end test**

Run: `python -m pytest tests/test_web_record_sync.py::test_pull_bind_confirm_export_and_mark_uploaded -v`
Expected: PASS.

- [ ] **Step 3: Document setup and ignore visual scratch files**

Add `.superpowers/` to `.gitignore`. Document Token retrieval, expiration behavior, the four-step workflow, CSV/manual eBird upload boundary and how to clear credentials. Do not include a real Token, endpoint response or account identifier.

- [ ] **Step 4: Run full verification**

Run: `python -m pytest`
Expected: PASS with the repository's configured coverage and strict marker checks.

Run: `git status --short`
Expected: only the intended Task 9 files are modified; `.superpowers/` is absent.

- [ ] **Step 5: Commit**

```bash
git add .gitignore README.md docs/superpowers/plans/2026-10-08-ebird-record-sync-implementation.md tests/test_web_record_sync.py
git commit -m "文档: 完善 eBird 同步使用说明"
```

- [ ] **Step 6: Final branch review**

Review the complete diff against `docs/superpowers/specs/2026-10-08-ebird-record-sync-design.md`, confirm no secret or `.superpowers/` file is tracked, and run focused security checks:

```bash
git grep -n "X-Auth-Token" -- ':!docs/superpowers/*'
git ls-files config/secrets.yaml .superpowers
```

Expected: the header name appears only in client/help text and no real value is present; the second command prints nothing.

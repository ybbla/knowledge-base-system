## Context

当前资源处理存在四层问题：
1. **AssetType 枚举与实际业务不匹配** — `audio` 几乎无产出，`attachment` 语义模糊
2. **除 image 外所有类型无下载→上传链路** — 视频和外链文档的原始字节从未被持久化
3. **内嵌图片和外部图片链接混用同一类型** — 处理逻辑通过 `_data` 是否存在来区分，隐含两条分支
4. **RecursiveLoader 实际不可用** — 创建的子 Document `source_uri=""`，parser 拿到空内容直接失败

前期已完成：删除 `max_asset_size_mb` 和 `max_assets_per_doc` 限制；删除 `ParseResult.embedded_docs`；删除 `SourceLocation.char_start/char_end`。

## Goals / Non-Goals

**Goals:**
- 重构 `AssetType` 枚举为四种语义明确的类型
- 所有链接类型统一"HTTP 下载 → MinIO 上传"流程
- 图片链接（image_link）与内嵌图片（image）共享校验→去重→理解管线
- 视频链接补充下载+上传
- 文档链接下载后触发完整子文档入库流水线（对标用户上传）
- 移除不可用的 `RecursiveLoader`，Markdown `[[link]]` 改为产出 `document_link`
- 清理关联死字段：`ElementType.embedded_document`、`ParsedElement.embedded_doc_id`

**Non-Goals:**
- 不改变 PPTX/PDF 解析器（只适配枚举，不改变解析逻辑）
- 不实现下载重试/断点续传
- 不改变视觉理解模型的调用方式
- 不新增 HTTP 客户端库（使用标准库 urllib）

## Decisions

### 1. AssetType 枚举设计

```
image           — 内嵌图片（解析器提供了实际字节 _data）
image_link      — 外部图片链接（仅有 URL，需下载）
video_link      — 视频链接（仅有 URL，需下载）
document_link   — 文档链接（仅有 URL，需下载后触发子文档入库）
```

**理由**: 每种类型对应一条明确的处理链路，`_prepare_assets` 不再需要靠 `_data` 是否存在来隐式判断。

### 2. 下载逻辑放置

新增 `assets/downloader.py`，提供 `download_to_bytes(url, timeout=30)` 工具函数。

**理由**: 下载是 image_link / video_link / document_link 的共同需求，抽到独立模块避免重复。

### 3. image / image_link 处理流程

```
image:      _data读取 → 魔数校验 → SHA-256去重 → 视觉理解 → MinIO上传
image_link: HTTP下载  → 魔数校验 → SHA-256去重 → 视觉理解 → MinIO上传
```

从 `process_image` 抽出 `_process_image_data(data, asset, asset_store, minio_store)` 共享函数。`process_image` 和 `process_image_link` 区别仅在起点。

**理由**: 消除重复，而非在 process_image 内部增加 if/else 分支。

### 4. video_link 处理流程

```
HTTP下载 → 视觉理解 → MinIO上传
```

相比当前 `process_video`（仅视觉理解，不上传），新增下载和上传。函数签名改为 `process_video(asset, asset_store, minio_store)`。

**理由**: 视频本身有检索价值，下载上传后可供后续回放和更完整的 AI 理解。

### 5. document_link 处理流程（避免循环依赖）

`process_document_link` 不能放在 `image_processor.py`（会导致循环 import：pipeline import image_processor，image_processor import pipeline）。

**方案**: 作为 `IngestionPipeline._process_document_link(asset)` 私有方法，天然可访问 `self._document_repo`、`self._minio_store`、`self.ingest()`。

```
IngestionPipeline._process_document_link(asset):
  data = download_to_bytes(asset.original_uri)
  if 下载失败: asset→failed, return

  推断 source_type（从 URL 后缀）
  if 后缀不可识别: asset→failed, return

  key = make_minio_key(child_doc_id, file_name)
  minio_store.upload_bytes(kb-input-bucket, key, data)
  source_uri = "minio://kb-input-bucket/key"

  child_doc = Document(
    doc_id = new_id("doc"),
    title = URL 文件名,
    source_type = 推断值,
    source_uri = source_uri,
    source_hash = sha256(data),
    parent_doc_id = 当前文档,
    root_doc_id = 当前文档.root_doc_id or 当前文档.doc_id,
  )
  document_repo.create(child_doc)
  self.ingest(child_doc, raw_content=data)
  asset.storage_uri = source_uri
  asset.status = ready
```

### 6. 同步嵌套 ingest 的时序

`_prepare_assets` 在解析之后、语义抽取之前调用。`document_link` 的子文档 `ingest` 在此阶段同步完成：

```
主文档 _run_create:
  解析 ✓
  _prepare_assets:
    _process_document_link:
      子文档 ingest → 解析 → 语义抽取 → 双路索引（同步完成）
  语义抽取（主文档）
  双路索引（主文档）
```

子文档在主文档语义抽取前完整入库，时序无冲突。子文档失败不传播到主文档（ingest 内部 try/except）。

### 7. 移除 RecursiveLoader + 关联死字段

删除：
- `ingestion/recursive_loader.py`（含 `RecursiveLoadResult`）
- `pipeline.py` 中 `_run_create` 的 RecursiveLoader 调用
- `tests/test_recursive_loader.py`
- `ElementType.embedded_document` 枚举值
- `ParsedElement.embedded_doc_id` 字段

**理由**: `document_link` 处理链路更完整（有真实文件内容），子文档无论来自 Markdown 还是 DOCX，统一走"下载→上传→ingest"路径。

### 8. 解析器适配策略

| 当前产出 | 改为 | 判断条件 |
|---------|------|---------|
| `AssetType.image`（有 _data） | `AssetType.image` | 内嵌图片字节（DOCX 内嵌、PDF 渲染） |
| `AssetType.image`（仅 URL） | `AssetType.image_link` | URL 且指向图片后缀 |
| `AssetType.video` | `AssetType.video_link` | URL 且指向视频 |
| `AssetType.attachment` | `AssetType.document_link` | URL 指向可入库文档 |
| `AssetType.audio` | `AssetType.video_link` | 仅 PPTX，归入视频处理 |

各解析器适配要点：
- **Markdown**: `![alt](url)` → `image_link`（都是URL）；`_classify_link_url` 返回新枚举；`_extract_video_assets` 中 `AssetType.video`→`video_link`
- **DOCX**: `_classify_link_url` 中 `image`→`image_link`（链接URL非内嵌字节）、`video`→`video_link`、`attachment`→`document_link`；内嵌图片保持 `image`
- **PPTX**: `video`→`video_link`、`audio`→`video_link`、`attachment`→`document_link`；内嵌图片保持 `image`
- **PDF**: `video`→`video_link`、`attachment`→`document_link`；内嵌图片保持 `image`
- **XLSX**: 同上

### 9. 其他需要同步更新的硬编码引用

- `_attach_unreferenced_video_assets`: `AssetType.video` → `AssetType.video_link`
- 所有解析器中 `AssetType.video` → `AssetType.video_link`
- `parsers/utils.py` `guess_mime()` 中 `AssetType.video` / `AssetType.audio` / `AssetType.attachment` 适配

## Risks / Trade-offs

- **[风险] 大量外链下载可能导致入库时间显著变长** → 设置 30s 超时
- **[风险] 外部链接可能失效或需要认证** → 下载失败标记 failed 不阻塞
- **[Trade-off] 视频下载占用带宽和存储** → 当前阶段先统一处理

## Migration Plan

1. 修改 `models.py`：AssetType 枚举 + 删除 `ElementType.embedded_document` + 删除 `ParsedElement.embedded_doc_id`
2. 新增 `assets/downloader.py`
3. 重构 `assets/image_processor.py`：抽共享函数、`process_image_link`、`process_video` 加参数
4. `ingestion/pipeline.py`：`_prepare_assets` 分支 + `_process_document_link` + 移除 RecursiveLoader
5. 删除 `ingestion/recursive_loader.py`
6. 适配解析器 + `parsers/utils.py`
7. 更新 `_attach_unreferenced_video_assets` 硬编码
8. 更新所有测试
9. 运行全量测试

**回滚**: 恢复 models.py + 恢复 image_processor.py + 恢复 recursive_loader.py。已入库数据不受影响（枚举值为字符串）。

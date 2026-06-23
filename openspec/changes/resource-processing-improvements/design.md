## Context

当前资源处理存在四层问题：
1. **AssetType 枚举与实际业务不匹配** — `audio` 几乎无产出，`attachment` 语义模糊
2. **除 image 外所有类型无下载→上传链路** — 视频和外链文档的原始字节从未被持久化
3. **内嵌图片和外部图片链接混用同一类型** — 处理逻辑通过 `_data` 是否存在来区分，隐含两条分支
4. **RecursiveLoader 实际不可用** — 创建的子 Document `source_uri=""`，parser 拿到空内容直接失败

前期已完成：删除 `max_asset_size_mb` / `max_assets_per_doc`；删除 `ParseResult.embedded_docs`；删除 `SourceLocation.char_start/char_end`；新增 `classify_link()` 工具函数（返回 `image/video/audio/document/url` 字符串，用于 structured_data.links 标注）。

## Goals / Non-Goals

**Goals:**
- 重构 `AssetType` 枚举为四种语义明确的类型
- 所有链接类型统一"HTTP 下载 → MinIO 上传"流程
- 图片链接（image_link）与内嵌图片（image）共享校验→去重→理解管线
- 视频链接补充下载+上传
- 文档链接下载后触发完整子文档入库流水线（对标用户上传）
- 移除不可用的 `RecursiveLoader`
- 清理关联死字段：`ElementType.embedded_document`、`ParsedElement.embedded_doc_id`

**Non-Goals:**
- 不改变解析器的结构解析逻辑，只改 AssetType 映射
- 不实现下载重试/断点续传
- 不改变视觉理解模型的调用方式
- 不新增 HTTP 客户端库（使用标准库 urllib）

## Decisions

### 1. AssetType 枚举设计

```python
class AssetType(str, Enum):
    image = "image"                   # 内嵌图片（解析器提供了实际字节 _data）
    image_link = "image_link"         # 外部图片链接（仅有 URL，需下载）
    video_link = "video_link"         # 视频链接（仅有 URL，需下载）
    document_link = "document_link"   # 文档链接（仅有 URL，需下载后触发子文档入库）
```

**理由**: 每种类型对应一条明确的处理链路，`_prepare_assets` 不再需要靠 `_data` 是否存在来隐式判断。

### 2. 下载逻辑放置

新增 `assets/downloader.py`，提供 `download_to_bytes(url, timeout=30)` 工具函数。

### 3. image / image_link 处理

从 `process_image` 抽出 `_process_image_data(data, asset, asset_store, minio_store)`（魔数校验 → 去重 → 视觉理解 → MinIO上传）。`process_image` 从 `_data` 读，`process_image_link` 从 URL 下载后调共享函数。

### 4. video_link 处理

`process_video(asset, asset_store, minio_store)`：HTTP下载 → 视觉理解 → MinIO上传。签名加 `minio_store`。

### 5. document_link 处理（避免循环依赖）

作为 `IngestionPipeline._process_document_link(asset)` 私有方法：

```
download_to_bytes(original_uri)
  → 推断 source_type（URL 后缀 → pdf/docx/xlsx/pptx/html/md/txt）
  → 上传 MinIO kb-input bucket
  → 创建子 Document（parent_doc_id/root_doc_id/source_uri/source_hash）
  → document_repo.create(child_doc)
  → self.ingest(child_doc, raw_content=data)
```

**理由**: 放在 pipeline 上避免 `image_processor` ← `pipeline` 循环 import。

### 6. 同步嵌套 ingest 时序

`_prepare_assets` 在解析后、语义抽取前调用。子文档 `ingest` 在此阶段同步完成。子文档在主文档语义抽取前完整入库，子文档失败不传播。

### 7. 移除 RecursiveLoader + 关联死字段

删除：
- `ingestion/recursive_loader.py`（含 `RecursiveLoadResult`）
- `pipeline.py` 中 `_run_create` 的 RecursiveLoader 调用
- `tests/test_recursive_loader.py`
- `ElementType.embedded_document`（L58）
- `ParsedElement.embedded_doc_id`（L144）+ 所有引用点

### 8. 解析器适配策略

当前已有 `classify_link()` 工具函数（返回 `image/video/audio/document/url` 字符串）。各解析器的 `_classify_link_url()` / `_asset_type_for_url()` 负责将 URL 映射到 `AssetType`。**只需改这些映射函数**，结构解析逻辑不动。

| 解析器 | 映射函数 | 当前返回 | 改为 |
|--------|---------|---------|------|
| Markdown | `_classify_link_url`(L288) | `video`/`image`/`attachment`/None | `video_link`/`image_link`/`document_link`/None |
| Markdown | `_asset_from_image`(L305) | `video`/`image` | `video_link`/`image_link` |
| Markdown | `_extract_video_assets`(L348) | `video` | `video_link` |
| DOCX | `_classify_link_url`(L305) | `video`/`image`/`attachment`/None | `video_link`/`image_link`/`document_link`/None |
| DOCX | 内嵌图片(L574) | `image`（有 _data） | 保持 `image` |
| PPTX | `_asset_type_for_url`(L824) | 用 `classify_link` 映射到 `video`/`audio`/`attachment` | 映射到 `video_link`/`video_link`/`document_link` |
| PPTX | 内嵌图片(L385) | `image`（有 _data） | 保持 `image` |
| PDF | `_asset_type_for_url`(L1078) | `video`/`attachment` | `video_link`/`document_link` |
| PDF | 内嵌图片(L731) | `image`（有 _data） | 保持 `image` |
| XLSX | `_classify_link_asset_type`(L433) | `video`/`image`/`attachment`/None | `video_link`/`image_link`/`document_link`/None |
| XLSX | 内嵌图片(L183) | `image`（有 _data） | 保持 `image` |

### 9. `classify_link()` 与 AssetType 的边界

`classify_link()` 返回字符串用于 `structured_data.links[].link_type` 标注，**不做修改**。它和 `AssetType` 是两个独立维度——前者记录"链接指向什么类型的内容"，后者决定"系统如何处理这个资源"。

### 10. 其他同步更新

- `_attach_unreferenced_video_assets`: `AssetType.video` → `AssetType.video_link` (pipeline L206)
- `guess_mime()`: `AssetType.video`→`video_link`，删 `audio` 分支，加 `image_link`→`image/*` 回退
- `app/db/repositories/elements.py`: 删 `embedded_doc_id` 映射(L31/48)
- `llm/semantic_extractor.py`: 删 `el.embedded_doc_id` 分支(L212-213)
- `app/api/v1/documents.py`: 删 `embedded_doc_id` 返回字段(L116)

## Risks / Trade-offs

- **[风险] 大量外链下载可能导致入库时间显著变长** → 30s 超时
- **[风险] 外部链接可能失效或需要认证** → 下载失败标记 failed 不阻塞
- **[Trade-off] 视频下载占用带宽和存储** → 当前统一处理

## Migration Plan

1. 修改 `models.py`：AssetType 枚举 + 删 `ElementType.embedded_document` + 删 `ParsedElement.embedded_doc_id`
2. 新增 `assets/downloader.py`
3. 重构 `assets/image_processor.py`
4. `pipeline.py`：`_prepare_assets` 分支 + `_process_document_link` + 移除 RecursiveLoader
5. 删除 `ingestion/recursive_loader.py`
6. 适配解析器映射函数 + `parsers/utils.py` `guess_mime`
7. 清理 `embedded_doc_id` 引用点（semantic_extractor / elements repo / documents API）
8. 更新所有测试
9. 运行全量测试

**回滚**: 恢复 models.py + image_processor.py + recursive_loader.py。已入库数据不受影响。
